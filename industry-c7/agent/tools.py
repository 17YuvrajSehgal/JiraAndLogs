"""Deterministic tool layer for the localization agent.

Every tool is a pure function of (snapshot, memory pool, query): no model
in the loop, so a transcript replays to byte-identical tool results. That
is what makes an agent built on these reproducible even though the model
itself is not.

The tool set is shaped by a failure analysis of the plain LLM baseline on
this benchmark (6,437 instances): 73% of its misses were RANKING failures
(right directory, wrong file) because an Agentless-style prompt shows
only path names and never a line of code. So these tools exist to answer
"which file actually defines, raises, or calls this?".

Techniques adopted from the literature (see ARCHITECTURE.md for the
evidence behind each):

  * symbol resolution over the WHOLE snapshot via `git grep` rather than
    a path-name heuristic. A stack frame names a symbol, not a file.
  * whole-file BM25 for `search_text`. Per-segment max scoring (Pathidea
    TSE 2022; BLAZE TSE 2025) was implemented and A/B tested here and was
    WORSE on 3 of 4 projects, so it was rejected: segmentation corrects
    rVSM's length bias, and BM25 already normalises length. Segments are
    still computed, but only to label which region matched. See
    ARCHITECTURE.md §3.1.
  * `callers_of`: one hop of reverse call structure. SBEST reports 78.3%
    of buggy methods sit within an average 0.34 calls of the trace.
  * incident votes divided by fix size (BugLocator's sim/n_b), so a
    40-file refactor cannot outvote a surgical one-file fix, and recency
    weighting with k=5 neighbours (RCACopilot).
  * report symbols filtered to things that exist in this snapshot, so
    turns are not spent looking up `NullPointerException` (Pathidea drops
    frames that are not in the repository).
  * tool errors return near-miss suggestions rather than a dead turn
    (CoSIL and RCAgent both identify format/hallucinated-path failures as
    a main engineering failure mode of LLM localizers).

Firewall: recall_incidents applies the paper's four exclusion rules.
Gold files are unreachable from every tool.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from function_stage import list_functions, parser_for, raw_blobs  # noqa: E402
from localize import (FULL_REPOS, MAX_BLOB_BYTES, PROJECTS,  # noqa: E402
                      BM25Index, Snapshot, bm25_rank, path_tokens, tokenize)

MAX_HITS = 20
MAX_CODE_LINES = 80
SNIPPET_CHARS = 2600
SEG_LINES = 60           # fallback segment size when a file has no parsed functions
SEG_TARGET_TOKENS = 500  # Pathidea measured 400-800 tokens as the useful range
MEM_K = 5                # RCACopilot: K=5 neighbours, more did not help
MEM_HALFLIFE_DAYS = 540  # recency weight; tuned shape, not RCACopilot's raw alpha
GREP_CAP = 400

# One BM25 index per PROJECT, shared across instances and threads. The
# memory pool is identical for every instance of a project (MongoDB has
# 19,819 incidents); only the firewall differs, and it is applied per
# instance at vote time. Building this per Workspace made Phase 0b
# CPU-bound once incident recall became unconditional.
_MEM_INDEX: dict[str, "BM25Index"] = {}
_MEM_LOCK = threading.Lock()

FRAME_RE = re.compile(r"\bat\s+([\w.$]+)\.([A-Za-z_]\w*)\s*\(")
CPP_FRAME_RE = re.compile(r"\b([A-Za-z_]\w*)::([A-Za-z_]\w*)\s*\(")
CAMEL_ID_RE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")
SNAKE_ID_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,})\b")
FILE_RE = re.compile(r"\b([A-Za-z_][\w$\-]*\.(?:java|scala|cc?|cpp|h|hpp|ic|yy|mm|idl))\b")
# Language and library names that appear in almost every stack trace and
# carry no localizing information. Pathidea drops frames outside the
# repository; these survive that test (the repo does reference them) but
# are still worthless as search targets, so they are dropped by name.
GENERIC_SYMBOLS = {
    "nullpointerexception", "illegalstateexception", "illegalargumentexception",
    "indexoutofboundsexception", "arrayindexoutofboundsexception",
    "unsupportedoperationexception", "classcastexception", "ioexception",
    "runtimeexception", "interruptedexception", "timeoutexception",
    "concurrentmodificationexception", "numberformatexception",
    "filenotfoundexception", "outofmemoryerror", "stackoverflowerror",
    "assertionerror", "exception", "throwable", "error",
    "arraylist", "hashmap", "hashset", "linkedlist", "concurrenthashmap",
    "stringbuilder", "string", "integer", "boolean", "object", "thread",
    "std", "vector", "shared_ptr", "unique_ptr", "size_t", "nullptr",
    "printstacktrace", "tostring", "hashcode", "equals", "getmessage",
}
# a line that plausibly DECLARES the symbol rather than merely using it
DECL_HINT = re.compile(
    r"\b(class|struct|interface|enum|trait|object|def|fun|func|void|static|"
    r"public|private|protected|template|typedef|using|inline)\b")


BOILER_RE = re.compile(
    r"^\s*(import|package|#include|using\s|//|/\*|\*|\*/|--|$)")


def _mostly_boilerplate(body: str) -> bool:
    """Import blocks and licence headers match many query terms while saying
    nothing about behaviour. Observed dominating the segment ranking, so
    they are dropped rather than merely down-weighted."""
    lines = [l for l in body.splitlines() if l.strip()]
    if not lines:
        return True
    return sum(1 for l in lines if BOILER_RE.match(l)) / len(lines) > 0.6


def _merge_to_target(segs: list, target: int = SEG_TARGET_TOKENS) -> list:
    """Merge consecutive segments until each holds ~`target` tokens."""
    out: list[list] = []
    for label, start, toks in segs:
        if out and sum(out[-1][2].values()) < target:
            out[-1][2].update(toks)
            out[-1][3] += 1
        else:
            out.append([label, start, Counter(toks), 1])
    return [(lab if n == 1 else f"{lab} and {n - 1} more", st, tk)
            for lab, st, tk, n in out]


def raw_report_symbols(text: str, limit: int = 60) -> list[str]:
    """Candidate symbols in priority order: stack frames first."""
    out, seen = [], set()

    def add(s):
        if s and len(s) >= 4 and s not in seen:
            seen.add(s)
            out.append(s)

    for m in FRAME_RE.finditer(text):
        add(m.group(1).rsplit(".", 1)[-1])
        add(m.group(2))
    for m in CPP_FRAME_RE.finditer(text):
        add(m.group(1))
        add(m.group(2))
    for m in FILE_RE.finditer(text):
        add(Path(m.group(1)).stem)
    for m in CAMEL_ID_RE.finditer(text):
        add(m.group(1))
    for m in SNAKE_ID_RE.finditer(text):
        add(m.group(1))
    return out[:limit]


def frame_symbols(text: str, limit: int = 6) -> list[str]:
    """Stack-frame symbols only, innermost name first.

    Narrower than raw_report_symbols, which also returns any CamelCase or
    snake_case word in the report. Phase 0 walks backwards from a frame, so
    it needs the frames and not the prose.
    """
    out, seen = [], set()

    def add(s):
        if s and len(s) >= 4 and s not in seen:
            seen.add(s)
            out.append(s)

    for m in FRAME_RE.finditer(text):
        add(m.group(2))                       # method before its class
        add(m.group(1).rsplit(".", 1)[-1])
    for m in CPP_FRAME_RE.finditer(text):
        add(m.group(2))
        add(m.group(1))
    return out[:limit]


class Workspace:
    """Everything the agent may touch for ONE instance."""

    def __init__(self, project: str, snapshot_sha: str, query_text: str,
                 memory: dict, dupclusters: dict, cutoff: float,
                 issue_key: str, fix_shas: set, fcache: dict,
                 seed_candidates: list[str] | None = None):
        self.project = project
        self.git_dir = FULL_REPOS[project]
        self.sha = snapshot_sha
        self.snap = Snapshot(self.git_dir, snapshot_sha,
                             PROJECTS[project]["src_ext"])
        self.query_text = query_text
        self.memory = memory
        self.dupclusters = dupclusters
        self.cutoff = cutoff
        self.issue_key = issue_key
        self.fix_shas = fix_shas
        self.fcache = fcache
        self.seed_candidates = [f for f in (seed_candidates or [])
                                if f in self.snap.blob_of]
        self.notes: list[dict] = []
        self.calls: list[dict] = []
        # v3. False keeps the v2 behaviour byte for byte: rank over the whole
        # pool, then drop inadmissible hits. See _memory_index.
        self.strict_memory_firewall = False
        self._blob_text: dict[str, str] = {}
        self._segs: dict[str, list] = {}
        self._mem_index = None
        self._dirs = None
        self._grep_cache: dict[str, list] = {}

    # ---- internals ---------------------------------------------------------
    def _text_of(self, path: str) -> str:
        blob = self.snap.blob_of.get(path)
        if not blob:
            return ""
        if blob not in self._blob_text:
            raw = raw_blobs(self.git_dir, [blob]).get(blob, b"")
            self._blob_text[blob] = raw[:MAX_BLOB_BYTES].decode("utf-8", "replace")
        return self._blob_text[blob]

    def _funcs_of(self, path: str):
        blob = self.snap.blob_of.get(path)
        if not blob or not parser_for(path):
            return []
        if blob not in self.fcache:
            raw = raw_blobs(self.git_dir, [blob]).get(blob, b"")
            self.fcache[blob] = list_functions(path, raw[:MAX_BLOB_BYTES])
        return self.fcache[blob]

    def _segments(self, path: str) -> list[tuple[str, int, Counter]]:
        """(label, start_line, tokens) per segment.

        Segments follow function boundaries (BLAZE: boundary-aware chunking
        beats fixed windows) but are then MERGED up to a token target,
        because Pathidea measured the useful range at 400-800 tokens.
        Per-function segments alone are far smaller than that and dilute a
        diffuse match across many tiny documents, which cost recall in
        testing.
        """
        if path in self._segs:
            return self._segs[path]
        txt = self._text_of(path)
        lines = txt.splitlines()
        segs = []
        fns = self._funcs_of(path)
        if fns:
            for name, s, e in fns:
                body = "\n".join(lines[max(0, s - 1):min(len(lines), e)])
                if body.strip():
                    segs.append((name, s, Counter(tokenize(body))))
            # Lines outside any function (imports, fields, top-level code).
            # These go into fixed windows, NOT one blob: a single catch-all
            # segment is long enough to win on raw term coverage and would
            # reintroduce exactly the long-document bias segmentation exists
            # to remove.
            covered = set()
            for _n, s, e in fns:
                covered.update(range(s - 1, e))
            rest_idx = [i for i in range(len(lines)) if i not in covered]
            for w in range(0, len(rest_idx), SEG_LINES):
                chunk = rest_idx[w:w + SEG_LINES]
                body = "\n".join(lines[i] for i in chunk)
                if body.strip() and not _mostly_boilerplate(body):
                    segs.append((f"outside functions, line {chunk[0] + 1}",
                                 chunk[0] + 1, Counter(tokenize(body))))
        if not segs:
            for i in range(0, max(1, len(lines)), SEG_LINES):
                body = "\n".join(lines[i:i + SEG_LINES])
                if body.strip():
                    segs.append((f"lines {i + 1}", i + 1, Counter(tokenize(body))))
        segs = _merge_to_target(segs)
        self._segs[path] = segs
        return segs

    def _grep(self, symbol: str) -> list[tuple[str, int, str]]:
        """Whole-word matches across the snapshot. (path, line, text)."""
        if symbol in self._grep_cache:
            return self._grep_cache[symbol]
        out = []
        try:
            r = subprocess.run(
                ["git", "--git-dir", str(self.git_dir), "grep", "-n", "-w",
                 "-F", "--", symbol, self.sha],
                capture_output=True, timeout=90)
            for line in r.stdout.decode("utf-8", "replace").splitlines()[:GREP_CAP]:
                try:
                    rest = line.split(":", 1)[1]        # drop the sha prefix
                    path, lno, text = rest.split(":", 2)
                except (IndexError, ValueError):
                    continue
                if path in self.snap.blob_of:            # non-test source only
                    out.append((path, int(lno), text.strip()[:200]))
        except Exception:  # noqa: BLE001 - grep failure must not kill the run
            out = []
        self._grep_cache[symbol] = out
        return out

    def symbols_in_snapshot(self, cands: list[str], limit: int = 12,
                            max_probes: int = 18) -> list[str]:
        """Keep only symbols that exist in THIS snapshot, most specific
        (fewest matches) first. Pathidea drops frames that are not in the
        repository; the same rule stops the agent spending turns on
        library names. Probe count is capped because each probe is a grep.
        """
        scored = []
        for s in cands[:max_probes]:
            if s in GENERIC_SYMBOLS or s.lower() in GENERIC_SYMBOLS:
                continue
            hits = self._grep(s)
            if hits:
                scored.append((len(hits), s))
        scored.sort()
        return [s for _n, s in scored[:limit]]

    def dirs(self) -> dict[str, int]:
        if self._dirs is None:
            d: dict[str, int] = defaultdict(int)
            for f in self.snap.files:
                d[str(Path(f).parent).replace("\\", "/")] += 1
            self._dirs = dict(d)
        return self._dirs

    def _near_paths(self, path: str, n: int = 3) -> list[str]:
        base = path.strip().replace("\\", "/").rsplit("/", 1)[-1].lower()
        if not base:
            return []
        hits = [f for f in self.snap.files
                if f.rsplit("/", 1)[-1].lower() == base]
        if not hits:
            stem = base.split(".")[0]
            hits = [f for f in self.snap.files if stem and stem in f.lower()]
        return hits[:n]

    def _admissible(self, key: str) -> bool:
        rec = self.memory.get(key)
        if not rec or key == self.issue_key:
            return False
        qc = self.dupclusters.get(self.issue_key)
        if qc is not None and self.dupclusters.get(key) == qc:
            return False
        if rec["fix_shas"] & self.fix_shas:
            return False
        if rec["resolved"] is not None and rec["resolved"] > self.cutoff:
            return False
        return True

    # ---- tools -------------------------------------------------------------
    def search_symbol(self, name: str) -> dict:
        """Where a symbol is DEFINED and where it is used, across the whole
        snapshot (git grep, whole word). The step from detection site to
        cause: a trace frame names this, not the faulty file."""
        name = (name or "").strip()
        if len(name) < 3:
            return {"error": "symbol too short (need 3+ chars)",
                    "hint": "use a class, function or field name from the report"}
        hits = self._grep(name)
        if not hits:
            return {"symbol": name, "defined_in": [], "used_in": [],
                    "note": "not present in this snapshot; it may come from a "
                            "library. Try another symbol from the report."}
        declared_files = {f for f in self.snap.files
                          if Path(f).stem.lower() == name.lower()}
        defs, uses = [], []
        by_file: dict[str, list] = defaultdict(list)
        for path, lno, text in hits:
            by_file[path].append((lno, text))
        for path, rows in by_file.items():
            fn_names = {f.rsplit("::", 1)[-1] for f, _s, _e in self._funcs_of(path)}
            is_def = path in declared_files or name in fn_names
            first_decl = next((r for r in rows if DECL_HINT.search(r[1])), None)
            entry = {"file": path, "n_matches": len(rows),
                     "first_line": rows[0][0],
                     "sample": (first_decl or rows[0])[1][:160]}
            (defs if (is_def or first_decl) else uses).append(entry)
        defs.sort(key=lambda e: (e["file"] not in declared_files, -e["n_matches"]))
        uses.sort(key=lambda e: -e["n_matches"])
        # Callers are returned inline rather than behind a separate tool.
        # v1 measured the standalone callers_of at 1 call in 105 runs: the
        # model never chose to walk backwards. search_symbol is called 3.8
        # times per run, so the reverse hop now arrives whether or not the
        # model thinks to ask for it. [R4]: 78.3% of buggy methods sit within
        # an average 0.34 calls of the trace.
        callers = self.callers_of(name).get("callers", [])
        return {"symbol": name, "total_matches": len(hits),
                "defined_in": defs[:MAX_HITS], "used_in": uses[:MAX_HITS],
                "called_from": callers[:12],
                "hint": ("the fault is often in a CALLER that created the bad "
                         "state, not in the file that reported it")}

    def callers_of(self, symbol: str) -> dict:
        """Which functions call or reference this symbol. One hop of reverse
        structure: the code that CREATES a bad state usually sits one call
        above the code that reports it."""
        symbol = (symbol or "").strip()
        if len(symbol) < 3:
            return {"error": "symbol too short"}
        out = []
        for path, lno, text in self._grep(symbol):
            enclosing = None
            for fn, s, e in self._funcs_of(path):
                if s <= lno <= e:
                    enclosing = fn
                    break
            if enclosing and enclosing.rsplit("::", 1)[-1] != symbol:
                out.append({"file": path, "caller": enclosing, "line": lno,
                            "code": text[:140]})
        seen, uniq = set(), []
        for o in out:
            k = (o["file"], o["caller"])
            if k not in seen:
                seen.add(k)
                uniq.append(o)
        return {"symbol": symbol, "callers": uniq[:MAX_HITS],
                "n_calling_files": len({o["file"] for o in uniq})}

    def data_flow_back(self, symbol: str) -> dict:
        """Where this symbol's value is SET. One hop of reverse data flow.

        callers_of walks control backwards; this walks data backwards. A
        field read with a bad value is usually written somewhere else
        entirely, and the write site is the defect far more often than the
        read site that reported it. Grep-shaped like callers_of, and shares
        its cache, so it costs one grep at most.
        """
        symbol = (symbol or "").strip()
        if len(symbol) < 3:
            return {"error": "symbol too short"}
        s = re.escape(symbol)
        # assignment to the symbol, compound assignment, or a setter named
        # after it. [^\w] rather than \b so `this->f =` and `obj.f =` count
        # while `other_f =` does not.
        write = re.compile(
            r"(?:^|[^\w])" + s + r"\s*(?:\+|-|\*|/|\||&|\^|%|<<|>>)?=(?!=)"
            r"|\bset_?" + s + r"\s*\(", re.I)
        out = []
        for path, lno, text in self._grep(symbol):
            if not write.search(text):
                continue
            enclosing = None
            for fn, st, en in self._funcs_of(path):
                if st <= lno <= en:
                    enclosing = fn
                    break
            out.append({"file": path, "writer": enclosing or "(file scope)",
                        "line": lno, "code": text[:140]})
        seen, uniq = set(), []
        for o in out:
            k = (o["file"], o["writer"])
            if k not in seen:
                seen.add(k)
                uniq.append(o)
        return {"symbol": symbol, "writes": uniq[:MAX_HITS],
                "n_writing_files": len({o["file"] for o in uniq}),
                "note": "write sites only. callers_of gives the control-flow "
                        "hop; this gives the data-flow one."}

    def search_text(self, query: str, k: int = 12) -> dict:
        """BM25 over file CONTENT. Describe the BEHAVIOUR, not the symptom.

        Scoring is whole-file. Per-segment max scoring (Pathidea/BRTracer
        segmentation) was implemented and A/B tested on 60 instances and
        was WORSE here: Hit@8 .600 vs .867 on MariaDB, .333 vs .467 on Qt,
        better only on Kafka. Segmentation exists to fix rVSM's length
        bias, and BM25's own length normalisation already covers that, so
        all that remains is the dilution. The best-matching function is
        still reported per hit, because naming the region is useful context
        for the agent even when it should not drive the ranking.
        """
        qtoks = tokenize(query or "")
        if not qtoks:
            return {"error": "empty query",
                    "hint": "describe what went wrong, e.g. 'partition "
                            "assignment returns null for regex subscription'"}
        pool = list(dict.fromkeys(
            self.seed_candidates
            + [f for f, _ in bm25_rank(qtoks, {p: path_tokens(p)
                                               for p in self.snap.files})][:120]))
        docs = {}
        for path in pool[:120]:
            txt = self._text_of(path)
            if txt:
                docs[path] = Counter(tokenize(txt))
        if not docs:
            return {"query": query, "hits": []}
        terms: dict[str, list[str]] = {}
        ranked = bm25_rank(qtoks, docs, explain=terms)[:k]
        qset = set(qtoks)
        out = []
        for path, score in ranked:
            region, best_n = "", 0
            for label, start, toks in self._segments(path):
                n = sum(toks[t] for t in qset if t in toks)
                if n > best_n:
                    region, best_n = label, n
            out.append({"file": path, "score": round(score, 2),
                        "best_region": region or "whole file",
                        "matched_terms": terms.get(path, [])[:4]})
        return {"query": query, "hits": out}

    def list_dir(self, path: str = "") -> dict:
        p = (path or "").strip().strip("/").replace("\\", "/")
        if not p:
            top = sorted({d.split("/")[0] for d in self.dirs()})
            return {"path": "", "subdirectories": top[:60],
                    "total_source_files": len(self.snap.files)}
        files = [f for f in self.snap.files
                 if str(Path(f).parent).replace("\\", "/") == p]
        subs = sorted({d for d in self.dirs() if d.startswith(p + "/")})[:40]
        if not files and not subs:
            near = sorted({d for d in self.dirs()
                           if p.split("/")[-1] in d})[:3]
            return {"error": f"no such directory: {p}", "did_you_mean": near}
        return {"path": p, "files": files[:120], "n_files": len(files),
                "subdirectories": subs}

    def read_skeleton(self, path: str) -> dict:
        path = (path or "").strip().replace("\\", "/").lstrip("./")
        if path not in self.snap.blob_of:
            return {"error": f"not in snapshot: {path}",
                    "did_you_mean": self._near_paths(path)}
        fns = self._funcs_of(path)
        txt = self._text_of(path)
        return {"file": path, "n_lines": txt.count("\n") + 1,
                "declares": [{"symbol": f, "line": s} for f, s, _ in fns][:60]}

    def read_code(self, path: str, around: str = "", line: int = 0,
                  n: int = 50) -> dict:
        path = (path or "").strip().replace("\\", "/").lstrip("./")
        if path not in self.snap.blob_of:
            return {"error": f"not in snapshot: {path}",
                    "did_you_mean": self._near_paths(path)}
        txt = self._text_of(path)
        lines = txt.splitlines()
        n = max(10, min(int(n or 50), MAX_CODE_LINES))
        start = 0
        if around:
            for fn, s, _e in self._funcs_of(path):
                if around.lower() in fn.lower():
                    start = max(0, s - 6)
                    break
            else:
                i = txt.find(around)
                start = max(0, txt.count("\n", 0, i) - 6) if i >= 0 else 0
        elif line:
            start = max(0, int(line) - 6)
        body = "\n".join(f"{i + 1}: {lines[i]}"
                         for i in range(start, min(len(lines), start + n)))
        return {"file": path, "from_line": start + 1,
                "code": body[:SNIPPET_CHARS]}

    def _memory_index(self):
        """BM25 over the project's memory pool.

        v2 built this ONCE per project over the whole pool (MongoDB:
        19,819 incidents) and applied the firewall afterwards, at vote
        time. That puts the firewall at the wrong stage twice over:
        idf, df and avgdl are then computed across documents that did not
        exist yet, and inadmissible incidents occupy slots in the ranked
        pool, so admissible ones get crowded out before the filter ever
        runs. Measured over 500 instances
        (scripts/memory_index_leak.py): half the ranked pool is
        inadmissible, 7.4% of instances come back with fewer than k
        incidents against 1.2% under the correct construction, and the
        returned top-5 differs on 27.6%.

        v3 builds the index from this instance's admissible incidents
        alone. The original reason for the shortcut does not survive
        measurement: filtering and rebuilding costs 0.06-0.12 s even on
        MongoDB's pool, against 232 s of wall time per instance.
        """
        if self.strict_memory_firewall:
            adm = {k: r["toks"] for k, r in self.memory.items()
                   if self._admissible(k)}
            return BM25Index(adm) if adm else None
        with _MEM_LOCK:
            idx = _MEM_INDEX.get(self.project)
            if idx is None:
                idx = BM25Index({k_: r["toks"]
                                 for k_, r in self.memory.items()})
                _MEM_INDEX[self.project] = idx
        return idx

    def recall_incidents(self, query: str, k: int = MEM_K) -> dict:
        """Past incidents that read like this one, and the files their fixes
        touched. Votes are weighted by similarity / fix size, so a sweeping
        refactor does not outweigh a surgical fix, and by recency."""
        mem_index = self._memory_index()
        if mem_index is None:          # v3, nothing admissible for this report
            return {"query": (query or self.query_text)[:120],
                    "admissible_matches": [],
                    "note": "no incident in this project was resolved before "
                            "this report"}
        qtoks = tokenize(query or self.query_text)
        k = max(1, min(int(k or MEM_K), 8))
        out = []
        for rank, key in enumerate(mem_index.rank(qtoks, k * 10), start=1):
            if not self._admissible(key):
                continue
            rec = self.memory[key]
            files = [f for f in rec["gold_files"] if f in self.snap.blob_of]
            if not files:
                continue
            n_fix = max(1, len(rec["gold_files"]))
            age_days = (max(0.0, self.cutoff - (rec["resolved"] or self.cutoff))
                        / 86400.0)
            recency = math.exp(-age_days / MEM_HALFLIFE_DAYS)
            out.append({"incident": key,
                        "fixed_files": files[:6],
                        "n_files_in_that_fix": n_fix,
                        "weight": round((1.0 / rank) * recency / n_fix, 4),
                        "resolved_days_before_this_report": int(age_days)})
            if len(out) >= k:
                break
        out.sort(key=lambda d: -d["weight"])
        return {"query": (query or self.query_text)[:120],
                "note": "weight = similarity/rank x recency / files-in-fix; "
                        "a one-file fix is stronger evidence than a 40-file "
                        "refactor",
                "admissible_matches": out}

    def note_candidate(self, path: str, reason: str,
                       confidence: float = 0.5) -> dict:
        raw = (path or "").strip().replace("\\", "/").lstrip("./")
        known = raw in self.snap.blob_of
        rec = {"file": raw, "reason": (reason or "")[:400],
               "confidence": float(confidence or 0), "in_snapshot": known}
        self.notes.append(rec)
        if not known:
            return {"recorded": raw, "in_snapshot": False,
                    "warning": "this path is not in the snapshot and cannot "
                               "be ranked",
                    "did_you_mean": self._near_paths(raw), "n_notes": len(self.notes)}
        return {"recorded": raw, "in_snapshot": True, "n_notes": len(self.notes)}


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_symbol",
        "description": ("Find where a class, function or identifier is DEFINED "
                        "and where it is used, anywhere in the snapshot. Use "
                        "this on names from a stack trace or error message: a "
                        "frame names a symbol, not the file that caused the "
                        "fault."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "callers_of",
        "description": ("Which functions call or reference a symbol. Use it to "
                        "walk one hop back from where the failure was detected "
                        "towards the code that created the bad state."),
        "parameters": {"type": "object", "properties": {
            "symbol": {"type": "string"}}, "required": ["symbol"]}}},
    {"type": "function", "function": {
        "name": "search_text",
        "description": ("BM25 search over the CONTENT of source files, scored "
                        "per function. Describe the BEHAVIOUR that went wrong "
                        "rather than quoting the error."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List source files and subdirectories. Empty path "
                       "lists the top level.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "read_skeleton",
        "description": "List the functions and classes a file declares.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "read_code",
        "description": "Read real source lines, optionally centred on a "
                       "symbol or line number.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "around": {"type": "string"},
            "line": {"type": "integer"}, "n": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "recall_incidents",
        "description": ("Past resolved incidents in this project whose reports "
                        "resemble a query, with the files their fixes touched. "
                        "Only incidents resolved before this report existed."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "k": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "note_candidate",
        "description": ("Record a suspect file with its evidence. Record every "
                        "file you seriously considered, including ones you rule "
                        "out, and say why."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "reason": {"type": "string"},
            "confidence": {"type": "number"}},
            "required": ["path", "reason"]}}},
]

# v3 only, so the v2 tool count stays at the 8 the paper reports.
V3_TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "data_flow_back",
        "description": ("Where a symbol's value is SET, as opposed to where "
                        "it is called. Use it when a value is wrong rather "
                        "than missing: the write site is the defect far more "
                        "often than the read site that reported it."),
        "parameters": {"type": "object", "properties": {
            "symbol": {"type": "string"}}, "required": ["symbol"]}}},
]

_DISPATCH = {"search_symbol": "search_symbol", "callers_of": "callers_of",
             "search_text": "search_text", "list_dir": "list_dir",
             "read_skeleton": "read_skeleton", "read_code": "read_code",
             "recall_incidents": "recall_incidents",
             "note_candidate": "note_candidate",
             "data_flow_back": "data_flow_back"}


def dispatch(ws: Workspace, name: str, args: dict) -> dict:
    """Run one tool. Repeated identical calls return the cached result with
    a note, rather than letting the agent spend its turn budget looping."""
    meth = _DISPATCH.get(name)
    if meth is None:
        return {"error": f"unknown tool {name}",
                "available": sorted(_DISPATCH)}
    key = f"{name}:{json.dumps(args or {}, sort_keys=True, default=str)}"
    prior = next((c for c in ws.calls if c.get("key") == key), None)
    if prior is not None and name != "note_candidate":
        return {**prior["result"],
                "note": "identical call already made; cached result returned. "
                        "Try a different symbol, query, or file."}
    fn = getattr(ws, meth)
    try:
        allowed = fn.__code__.co_varnames[:fn.__code__.co_argcount]
        res = fn(**{k: v for k, v in (args or {}).items() if k in allowed})
    except Exception as e:  # noqa: BLE001 - a tool error must not kill the run
        res = {"error": f"{type(e).__name__}: {e}"}
    ws.calls.append({"tool": name, "args": args, "key": key, "result": res})
    return res
