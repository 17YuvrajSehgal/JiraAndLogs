"""Deterministic tool layer for the localization agent.

Every tool is a pure function of (snapshot, memory pool, query) with no
model in the loop, so a transcript can be replayed and will produce
byte-identical tool results. That is what makes an agent built on these
reproducible even though the model itself is not.

The tool set is chosen from a failure analysis of the plain LLM
baseline on this benchmark (6,437 instances): 73% of its misses were
RANKING failures, where it had the right directory but picked the wrong
file from a list of bare path names, and only 27% were search failures.
The plain baseline never sees code. So the tools here are built to let
an agent answer "which file actually defines or raises this?" instead
of guessing from path names:

  search_symbol   where a class/function/identifier is DEFINED, and
                  where it is merely mentioned (the decisive tool for
                  stack traces: a frame names a symbol, not a file)
  search_text     BM25 over file CONTENT inside the snapshot
  list_dir        tree navigation
  read_skeleton   the functions/classes a file declares
  read_code       real source lines, around a symbol or a line number
  recall_incidents  past incidents that read like this one, with the
                  files their fixes touched, behind the same temporal
                  firewall as the lexical pipeline
  note_candidate  record a suspect file with evidence

Firewall: recall_incidents applies the four exclusion rules of the
paper (self, duplicate cluster, shared fix commit, resolved after the
query was created). Gold files are NEVER reachable from any tool.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from function_stage import list_functions, parser_for, raw_blobs  # noqa: E402
from localize import (FULL_REPOS, MAX_BLOB_BYTES, PROJECTS,  # noqa: E402
                      BM25Index, Snapshot, bm25_rank, path_tokens, tokenize)

MAX_HITS = 25
MAX_CODE_LINES = 80
SNIPPET_CHARS = 2600

# a stack frame names a symbol; these pull the symbols out of report text
FRAME_RE = re.compile(r"\bat\s+([\w.$]+)\.([A-Za-z_]\w*)\s*\(")
CPP_FRAME_RE = re.compile(r"\b([A-Za-z_]\w*)::([A-Za-z_]\w*)\s*\(")
CAMEL_ID_RE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")
SNAKE_ID_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,})\b")
FILE_RE = re.compile(r"\b([A-Za-z_][\w$\-]*\.(?:java|scala|cc?|cpp|h|hpp|ic|yy|mm|idl))\b")


def report_symbols(text: str, limit: int = 40) -> list[str]:
    """Symbols worth looking up, most specific first: stack frames, then
    CamelCase identifiers, then snake_case."""
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


class Workspace:
    """Everything the agent may touch for ONE instance."""

    def __init__(self, project: str, snapshot_sha: str, query_text: str,
                 memory: dict, dupclusters: dict, cutoff: float,
                 issue_key: str, fix_shas: set, fcache: dict,
                 seed_candidates: list[str] | None = None):
        self.project = project
        self.git_dir = FULL_REPOS[project]
        self.snap = Snapshot(self.git_dir, snapshot_sha,
                             PROJECTS[project]["src_ext"])
        self.query_text = query_text
        self.memory = memory
        self.dupclusters = dupclusters
        self.cutoff = cutoff
        self.issue_key = issue_key
        self.fix_shas = fix_shas
        self.fcache = fcache
        self.seed_candidates = seed_candidates or []
        self.notes: list[dict] = []
        self.calls: list[dict] = []
        self._blob_text: dict[str, str] = {}
        self._mem_index = None
        self._dirs = None

    # ---- internals ---------------------------------------------------------
    def _text_of(self, path: str) -> str:
        blob = self.snap.blob_of.get(path)
        if not blob:
            return ""
        if blob not in self._blob_text:
            raw = raw_blobs(self.git_dir, [blob]).get(blob, b"")
            self._blob_text[blob] = raw.decode("utf-8", "replace")
        return self._blob_text[blob]

    def _funcs_of(self, path: str):
        blob = self.snap.blob_of.get(path)
        if not blob or not parser_for(path):
            return []
        if blob not in self.fcache:
            raw = raw_blobs(self.git_dir, [blob]).get(blob, b"")
            self.fcache[blob] = list_functions(path, raw[:MAX_BLOB_BYTES])
        return self.fcache[blob]

    def dirs(self) -> dict[str, int]:
        if self._dirs is None:
            d: dict[str, int] = defaultdict(int)
            for f in self.snap.files:
                d[str(Path(f).parent).replace("\\", "/")] += 1
            self._dirs = dict(d)
        return self._dirs

    def _admissible(self, key: str) -> bool:
        rec = self.memory.get(key)
        if not rec or key == self.issue_key:
            return False
        if self.dupclusters.get(key) is not None and \
                self.dupclusters.get(key) == self.dupclusters.get(self.issue_key):
            return False
        if rec["fix_shas"] & self.fix_shas:
            return False
        if rec["resolved"] is not None and rec["resolved"] > self.cutoff:
            return False
        return True

    # ---- tools -------------------------------------------------------------
    def search_symbol(self, name: str) -> dict:
        """Where is this symbol defined, and where is it mentioned?"""
        name = (name or "").strip()
        if len(name) < 3:
            return {"error": "symbol too short"}
        defines, mentions, stem_match = [], [], []
        target = name.lower()
        for path in self.snap.files:
            if Path(path).stem.lower() == target:
                stem_match.append(path)
        # definition sites come from the parsed function/class inventory
        scanned = 0
        for path in self.snap.files:
            if scanned >= 4000:
                break
            base = Path(path).stem.lower()
            if target not in base and target[:6] not in path.lower():
                continue
            scanned += 1
            for fn, s, _e in self._funcs_of(path):
                if fn.rsplit("::", 1)[-1].lower() == target:
                    defines.append({"file": path, "symbol": fn, "line": s})
        # textual mentions, restricted to a BM25 shortlist for cost
        pool = (stem_match + self.seed_candidates
                + [f for f, _ in bm25_rank(tokenize(name),
                                           {p: path_tokens(p)
                                            for p in self.snap.files})][:60])
        for path in list(dict.fromkeys(pool))[:80]:
            txt = self._text_of(path)
            if not txt:
                continue
            idx = txt.find(name)
            if idx >= 0:
                line = txt.count("\n", 0, idx) + 1
                mentions.append({"file": path, "line": line})
                for fn, s, e in self._funcs_of(path):
                    if s <= line <= e:
                        mentions[-1]["in_function"] = fn
                        break
        return {"symbol": name,
                "files_named_after_it": stem_match[:MAX_HITS],
                "defined_in": defines[:MAX_HITS],
                "mentioned_in": mentions[:MAX_HITS]}

    def search_text(self, query: str, k: int = 12) -> dict:
        """BM25 over file CONTENT (what the plain baseline never sees)."""
        qtoks = tokenize(query or "")
        if not qtoks:
            return {"error": "empty query"}
        pool = list(dict.fromkeys(
            self.seed_candidates
            + [f for f, _ in bm25_rank(qtoks, {p: path_tokens(p)
                                               for p in self.snap.files})][:150]))
        docs = {}
        for path in pool[:150]:
            txt = self._text_of(path)
            if txt:
                docs[path] = Counter(tokenize(txt[:MAX_BLOB_BYTES]))
        terms: dict[str, list[str]] = {}
        ranked = bm25_rank(qtoks, docs, explain=terms)[:k]
        return {"query": query,
                "hits": [{"file": f, "score": round(s, 2),
                          "matched_terms": terms.get(f, [])[:4]}
                         for f, s in ranked]}

    def list_dir(self, path: str = "") -> dict:
        p = (path or "").strip().strip("/").replace("\\", "/")
        if not p:
            top = sorted({d.split("/")[0] for d in self.dirs()})
            return {"path": "", "subdirectories": top[:60],
                    "total_source_files": len(self.snap.files)}
        files = [f for f in self.snap.files
                 if str(Path(f).parent).replace("\\", "/") == p]
        subs = sorted({d for d in self.dirs()
                       if d.startswith(p + "/")})[:40]
        return {"path": p, "files": files[:120], "n_files": len(files),
                "subdirectories": subs}

    def read_skeleton(self, path: str) -> dict:
        path = (path or "").strip()
        if path not in self.snap.blob_of:
            return {"error": f"not in snapshot: {path}"}
        fns = self._funcs_of(path)
        txt = self._text_of(path)
        return {"file": path, "n_lines": txt.count("\n") + 1,
                "declares": [{"symbol": f, "line": s} for f, s, _ in fns][:60]}

    def read_code(self, path: str, around: str = "", line: int = 0,
                  n: int = 50) -> dict:
        path = (path or "").strip()
        if path not in self.snap.blob_of:
            return {"error": f"not in snapshot: {path}"}
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
                if i >= 0:
                    start = max(0, txt.count("\n", 0, i) - 6)
        elif line:
            start = max(0, int(line) - 6)
        body = "\n".join(f"{i + 1}: {lines[i]}"
                         for i in range(start, min(len(lines), start + n)))
        return {"file": path, "from_line": start + 1,
                "code": body[:SNIPPET_CHARS]}

    def recall_incidents(self, query: str, k: int = 6) -> dict:
        """Past incidents that read like this one, and the files their
        fixes touched. Firewalled: nothing resolved after this report."""
        if self._mem_index is None:
            self._mem_index = BM25Index({k_: r["toks"]
                                         for k_, r in self.memory.items()})
        qtoks = tokenize(query or self.query_text)
        out = []
        for key in self._mem_index.rank(qtoks, k * 8):
            if not self._admissible(key):
                continue
            rec = self.memory[key]
            files = [f for f in rec["gold_files"] if f in self.snap.blob_of]
            if not files:
                continue
            out.append({"incident": key, "fixed_files": files[:6]})
            if len(out) >= k:
                break
        return {"query": (query or self.query_text)[:120],
                "admissible_matches": out}

    def note_candidate(self, path: str, reason: str,
                       confidence: float = 0.5) -> dict:
        path = (path or "").strip()
        known = path in self.snap.blob_of
        self.notes.append({"file": path, "reason": (reason or "")[:400],
                           "confidence": float(confidence or 0),
                           "in_snapshot": known})
        return {"recorded": path, "in_snapshot": known,
                "n_notes": len(self.notes)}


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_symbol",
        "description": ("Find where a class, function or identifier is DEFINED "
                        "and where it is mentioned. Use this on names taken "
                        "from a stack trace or error message: a frame names a "
                        "symbol, not the file that caused the fault."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "search_text",
        "description": ("BM25 search over the CONTENT of source files in this "
                        "snapshot. Use it for error strings, log messages, or "
                        "a description of the behaviour."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List source files and subdirectories of a directory. "
                       "Empty path lists the top level.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "read_skeleton",
        "description": "List the functions and classes a file declares.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "read_code",
        "description": "Read real source lines from a file, optionally "
                       "centred on a symbol or line number.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "around": {"type": "string"},
            "line": {"type": "integer"},
            "n": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "recall_incidents",
        "description": ("Find past resolved incidents in this project whose "
                        "reports resemble a query, and the files their fix "
                        "commits touched. Only incidents resolved before this "
                        "report existed are returned."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "note_candidate",
        "description": ("Record a suspect file with the evidence for it. "
                        "Record every file you seriously considered, including "
                        "ones you later rule out, and say why."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "reason": {"type": "string"},
            "confidence": {"type": "number"}},
            "required": ["path", "reason"]}}},
]


def dispatch(ws: Workspace, name: str, args: dict) -> dict:
    fn = {"search_symbol": ws.search_symbol, "search_text": ws.search_text,
          "list_dir": ws.list_dir, "read_skeleton": ws.read_skeleton,
          "read_code": ws.read_code, "recall_incidents": ws.recall_incidents,
          "note_candidate": ws.note_candidate}.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        res = fn(**{k: v for k, v in (args or {}).items()
                    if k in fn.__code__.co_varnames})
    except Exception as e:  # noqa: BLE001 - a tool error must not kill the run
        res = {"error": f"{type(e).__name__}: {e}"}
    ws.calls.append({"tool": name, "args": args,
                     "result_chars": len(json.dumps(res, default=str))})
    return res
