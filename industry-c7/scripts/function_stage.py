"""Function-level second stage (reviewer W4: "code regions, not files").

For each benchmark instance:
  gold functions   = functions in the SNAPSHOT whose line span overlaps a
                     parent-side diff hunk of the fix commit (tree-sitter
                     spans x `git diff -U0` ranges). Only hunks whose
                     parent IS the snapshot are used, so line numbers are
                     exact; later commits of multi-commit fixes are
                     skipped and counted.
  candidates       = all functions in the top-10 files of the persisted
                     cond_ours file ranking ({p}-instances.jsonl).
  ranking          = BM25 of each function body vs. the query text,
                     within that candidate set.

Metrics (eval split only, same time split as localize.py): function-level
Acc@K / MRR end-to-end (file stage misses count as misses), plus the
oracle ceiling (gold function present anywhere in the candidate set).

Usage:
    python industry-c7/scripts/function_stage.py --project kafka
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import (BENCH, FULL_REPOS, KS, MAX_BLOB_BYTES, OUT,  # noqa: E402
                      PROJECTS, bm25_rank, is_dead_row, tokenize)
from mine_benchmark import run_git  # noqa: E402

from tree_sitter_language_pack import get_parser  # noqa: E402

TOP_FILES = 10
LIST_LEN = 50
ROOT_AG = Path(__file__).resolve().parents[1] / "data/agent"
TRANSCRIPTS = ROOT_AG / "transcripts"


def read_functions(project: str, issue_key: str) -> set:
    """{(path, symbol)} the agent opened by name with read_code.

    read_code takes `around`, a symbol, so an opened region is already
    identified the same way a function candidate is. Calls without `around`
    read an offset window and name no function, so they are skipped rather
    than guessed at."""
    f = TRANSCRIPTS / f"v3-full-{project}_{issue_key}.json"
    if not f.exists():
        return set()
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a truncated transcript is not a crash
        return set()
    out = set()
    for e in d.get("events") or []:
        if e.get("type") == "tool" and e.get("name") == "read_code":
            a = e.get("args") or {}
            path, around = a.get("path"), a.get("around")
            if path and around:
                out.add((str(path), str(around)))
    return out
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")

# extension -> grammar. Every entry here was checked against REAL gold files
# from the repos, not a toy snippet, because a grammar that loads is not a
# grammar that parses: tree-sitter's groovy produced 554 ERROR nodes and no
# function node at all over 12 real Groovy files, so .groovy stays out.
# .yy (bison), .idl (mongo IDL) and .qml have no usable function grammar
# either, and .qml never appears in a gold file, so none of them are wired.
LANG_OF = {".java": "java", ".scala": "scala", ".py": "python", ".go": "go"}
for _e in (".c", ".cc", ".cpp", ".h", ".hpp", ".ic", ".inl", ".mm"):
    LANG_OF[_e] = "cpp"

# Which node types are a function-like DEFINITION, per language. This is not
# one shared tuple, because the same name means different things across
# grammars. Counted on real gold files:
#   java   method_declaration 81, constructor_declaration 13
#   scala  function_definition 298  (function_declaration is an abstract
#          member with no body, so it is not a region and is excluded)
#   cpp    function_definition 425  (function_declarator is a signature)
#   python function_definition 101
#   go     method_declaration 131, function_declaration 58  <- the second is
#          every top-level func; matching only the first would have silently
#          dropped them while still looking like Go support.
FUNC_NODES = {
    "java": ("method_declaration", "constructor_declaration"),
    "scala": ("function_definition",),
    "cpp": ("function_definition",),
    "python": ("function_definition",),
    "go": ("function_declaration", "method_declaration"),
}

def grammar_key(src_ext) -> str:
    """Fingerprint of the grammar rules THIS project can actually hit.

    Per project, not global: adding Python must rebuild ambari's cache, and
    must not rebuild hive's, which has no .py in its src_ext and whose
    entries are provably unchanged.
    """
    exts = sorted(e for e in src_ext if e in LANG_OF)
    langs = sorted({LANG_OF[e] for e in exts})
    return hashlib.sha1(repr((exts, [(l, tuple(FUNC_NODES[l]))
                                     for l in langs])).encode()
                        ).hexdigest()[:16]

_parsers: dict[str, object] = {}


def _save_cache(path: Path, fcache: dict, key: str) -> None:
    path.write_bytes(pickle.dumps({"__grammar__": key, "fcache": fcache}))


def lang_for(path: str) -> str | None:
    return LANG_OF.get(Path(path).suffix.lower())


def parser_for(path: str):
    lang = lang_for(path)
    if lang is None:
        return None
    if lang not in _parsers:
        _parsers[lang] = get_parser(lang)
    return _parsers[lang]


def _cpp_name(node) -> str | None:
    d = node.child_by_field_name("declarator")
    seen = 0
    while d is not None and d.type != "function_declarator" and seen < 8:
        d = (d.child_by_field_name("declarator")
             or (d.children[0] if d.children else None))
        seen += 1
    if d is None or d.type != "function_declarator":
        return None
    nm = d.child_by_field_name("declarator")
    return nm.text.decode("utf-8", "replace") if nm is not None else None


def list_functions(path: str, blob_text: bytes) -> list[tuple[str, int, int]]:
    """(name, start_line, end_line) 1-based inclusive, document order."""
    p = parser_for(path)
    if p is None:
        return []
    lang = lang_for(path)
    wanted = FUNC_NODES[lang]
    tree = p.parse(blob_text)
    out: list[tuple[str, int, int]] = []
    stack = [tree.root_node]
    while stack:
        n = stack.pop()
        if n.type in wanted:
            # C++ hides the name under a chain of declarators; every other
            # grammar here exposes a `name` field directly.
            if lang == "cpp":
                name = _cpp_name(n)
            else:
                nm = n.child_by_field_name("name")
                name = nm.text.decode("utf-8", "replace") if nm is not None else None
            if name:
                out.append((name, n.start_point[0] + 1, n.end_point[0] + 1))
        stack.extend(n.children)
    out.sort(key=lambda f: f[1])
    return out


def raw_blobs(git_dir: Path, blobs: list[str]) -> dict[str, bytes]:
    """Binary cat-file --batch (byte offsets; text mode desyncs on CRLF)."""
    if not blobs:
        return {}
    r = subprocess.run(["git", "--git-dir", str(git_dir), "cat-file", "--batch"],
                       input="\n".join(blobs).encode(), capture_output=True)
    pos, out, res = 0, r.stdout, {}
    for blob in blobs:
        header_end = out.find(b"\n", pos)
        if header_end < 0:
            break
        header = out[pos:header_end].split()
        if len(header) == 3 and header[1] == b"blob":
            size = int(header[2])
            res[blob] = out[header_end + 1:header_end + 1 + size][:MAX_BLOB_BYTES]
            pos = header_end + 1 + size + 1
        else:
            res[blob] = b""
            pos = header_end + 1
    return res


def parent_side_ranges(git_dir: Path, snapshot: str, fix_sha: str,
                       paths: list[str]) -> dict[str, list[tuple[int, int]]]:
    """Parent(=snapshot)-side changed line ranges per gold file."""
    out: dict[str, list[tuple[int, int]]] = {}
    txt = run_git(git_dir, "diff", "-U0", snapshot, fix_sha, "--", *paths)
    cur = None
    for line in txt.splitlines():
        if line.startswith("--- a/"):
            cur = line[6:]
        elif line.startswith("--- /dev/null"):
            cur = None  # file added by the fix: nothing to localize in snapshot
        else:
            m = HUNK_RE.match(line)
            if m and cur is not None:
                a, b = int(m.group(1)), int(m.group(2) or "1")
                # pure insertion (b=0) after line a: charge the surrounding line
                out.setdefault(cur, []).append((a, a + b - 1) if b else (a, a + 1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, choices=list(FULL_REPOS))
    ap.add_argument("--limit", type=int, default=0)
    # T20. The candidate set is whatever the file stage put in its top 10, so
    # a better file stage should raise the ceiling before any function-level
    # ranking change can matter. cond_ours scores 0.686 Acc@5 at file level
    # and agent v3 scores 0.888, so this is the first thing to try.
    # "submitted" is the agent's OWN region, not a stage bolted on after it.
    # The other sources rank candidate functions by keyword overlap; this one
    # scores what the model actually committed to in submit_ranking.
    ap.add_argument("--ranking", default="cond_ours",
                    help="file ranking to take candidates from: a key in "
                         "rankings (cond_ours), or 'agent' for agent-v3-full")
    # Functions the agent opened BY NAME via read_code. Attention, not
    # relevance: it says the agent looked, not that it was right.
    ap.add_argument("--read-boost", action="store_true",
                    help="rank functions the agent actually read above the "
                         "rest, BM25 order preserved inside each group")
    ap.add_argument("--tag", default="",
                    help="output suffix, e.g. --tag -agent writes "
                         "{p}-functions-agent-summary.json")
    # The agent file used to be the hardcoded name "agent-v3-full.jsonl",
    # which does not exist any more: the main run is cut into five
    # project-disjoint shards writing agent-full-s1..s5.jsonl. So
    # --ranking submitted either crashed on a missing file or, worse, read
    # a stale one and reported regions from a run nobody asked about.
    # The default is a glob over the shards, and every match is read.
    ap.add_argument("--agent-glob", default="agent-full-*.jsonl",
                    help="glob under data/agent for the rows carrying the "
                         "submitted regions (default: the sharded main run)")
    args = ap.parse_args()
    git_dir = FULL_REPOS[args.project]

    bench = {b["issue_key"]: b for b in
             (json.loads(l) for l in
              (BENCH / f"{args.project}.jsonl").open(encoding="utf-8"))}
    rows = [json.loads(l) for l in
            (OUT / f"{args.project}-instances.jsonl").open(encoding="utf-8")]
    rows.sort(key=lambda r: r["fix_time"])
    n_dev = json.load((OUT / f"{args.project}-summary.json").open())["n_dev"]
    if args.limit:
        rows = rows[:args.limit]

    agent_rank: dict[str, list] = {}
    agent_read: dict[str, set] = {}
    agent_regions: dict[str, list] = {}
    if args.ranking in ("agent", "submitted") or args.read_boost:
        files = sorted(ROOT_AG.glob(args.agent_glob))
        if not files:
            print(f"no agent rows match {args.agent_glob} under {ROOT_AG}",
                  file=sys.stderr)
            return 1
        print(f"agent rows from: {', '.join(f.name for f in files)}")
        # Shards are project-disjoint, so one issue_key must not appear
        # twice. If it does, two shards overlapped and whichever file sorts
        # last would silently win; say so instead.
        seen_in: dict[str, str] = {}
        for af in files:
            for line in af.open(encoding="utf-8"):
                if not line.strip():
                    continue
                a = json.loads(line)
                if a["project"] != args.project or is_dead_row(a):
                    continue
                k = a["issue_key"]
                if k in seen_in:
                    print(f"REFUSING: {args.project}:{k} appears in both "
                          f"{seen_in[k]} and {af.name}; the shards are not "
                          f"disjoint", file=sys.stderr)
                    return 1
                seen_in[k] = af.name
                agent_rank[k] = a["ranking"]
                # notes carry the submitted region per file, already
                # resolved against the snapshot at submit time. An
                # unresolved symbol is dropped here, which scores it as a
                # miss rather than inventing a key that could never match.
                # "regions" lives in the row; "notes" only in the
                # transcript. Prefer the row so scoring never depends on
                # transcripts being present, and fall back for rows written
                # before the field existed.
                src = a.get("regions") or [
                    {"path": n["file"],
                     "resolved": n.get("symbol_resolved", ""),
                     "lines": n.get("symbol_lines", [])}
                    for n in (a.get("notes") or [])]
                agent_regions[k] = [
                    f"{g['path']}::{g['resolved']}@{g['lines'][0]}"
                    for g in src if g.get("resolved") and g.get("lines")]
                if args.read_boost:
                    agent_read[k] = read_functions(args.project, k)
        # The agent ran the eval split only, so an instance with no agent
        # ranking has no candidate set at all. Dropping it here instead of
        # scoring it as a miss keeps the population honest; the dev rows it
        # removes were never scored anyway.
        rows = [r for r in rows if r["issue_key"] in agent_rank]
        n_dev = 0
        print(f"agent mode: {len(rows)} instances with an agent ranking")

    # The cache is keyed by blob sha and stores [] for a file no grammar
    # covers. That is the trap: widen LANG_OF and every previously
    # unparseable blob still answers [] forever, so the new grammar silently
    # does nothing. Adding .py to ambari moved its coverage from 0.472 to
    # 0.921 only because the cache was deleted by hand first. Stamping the
    # grammar config into the cache makes that automatic.
    cache_path = OUT / f"funcs-{args.project}.pkl"
    gkey = grammar_key(PROJECTS[args.project]["src_ext"])
    fcache: dict[str, list] = {}
    if cache_path.exists():
        blob = pickle.loads(cache_path.read_bytes())
        if isinstance(blob, dict) and blob.get("__grammar__") == gkey:
            fcache = blob["fcache"]
        else:
            print("  grammar config changed since this cache was written; "
                  "rebuilding it from scratch", flush=True)

    out_rows, stats, t0 = [], Counter(), time.time()
    for i, r in enumerate(rows):
        b = bench[r["issue_key"]]
        snap_files = (agent_rank[r["issue_key"]]
                      if args.ranking in ("agent", "submitted")
                      else r["rankings"][args.ranking])[:TOP_FILES]
        gold_paths = [f for f in b["gold_files"] if parser_for(f)]
        stats["gold_files_unparseable"] += len(b["gold_files"]) - len(gold_paths)

        # blob ids for every file we must parse (gold + candidates)
        need_paths = list(dict.fromkeys(gold_paths + snap_files))
        blob_of: dict[str, str] = {}
        if need_paths:
            ls = run_git(git_dir, "ls-tree", b["snapshot_sha"], "--", *need_paths)
            for line in ls.splitlines():
                meta, path = line.split("\t", 1)
                _, otype, blob = meta.split()
                if otype == "blob":
                    blob_of[path] = blob
        missing = [bl for bl in {blob_of[p] for p in blob_of} if bl not in fcache]
        texts = raw_blobs(git_dir, missing)
        for p_, bl in blob_of.items():
            if bl not in fcache:
                fcache[bl] = list_functions(p_, texts.get(bl, b""))

        # ---- gold functions: only the fix sha whose parent IS the snapshot
        gold_funcs: set[tuple[str, str, int]] = set()
        usable_shas = (list(b["fix_shas"]) if b["n_fix_commits"] == 1
                       else [s for s in b["fix_shas"]
                             if run_git(git_dir, "rev-parse", f"{s}^").strip()
                             == b["snapshot_sha"]])
        stats["fix_shas_skipped_not_snapshot_child"] += (
            len(b["fix_shas"]) - len(usable_shas))
        for sha in usable_shas:
            for path, ranges in parent_side_ranges(
                    git_dir, b["snapshot_sha"], sha, gold_paths).items():
                for name, s, e in fcache.get(blob_of.get(path, ""), []):
                    if any(a <= e and s <= z for a, z in ranges):
                        gold_funcs.add((path, name, s))
        eligible = bool(gold_funcs)
        stats["eligible" if eligible else "no_derivable_gold_function"] += 1

        # ---- candidates + ranking
        docs: dict[str, Counter] = {}
        blob_txt = raw_blobs(git_dir, [blob_of[p] for p in snap_files
                                       if p in blob_of])
        for path in snap_files:
            bl = blob_of.get(path)
            if not bl:
                continue
            lines = blob_txt.get(bl, b"").decode("utf-8", "replace").splitlines()
            for name, s, e in fcache[bl]:
                docs[f"{path}::{name}@{s}"] = Counter(
                    tokenize("\n".join(lines[s - 1:e])))
        if args.ranking == "submitted":
            # no keyword stage: this IS the model's answer, in its own order
            ranking = agent_regions.get(r["issue_key"], [])
        else:
            qtoks = tokenize(b["query_text"])
            ranking = [d for d, _ in bm25_rank(qtoks, docs)]
        if args.read_boost:
            read = agent_read.get(r["issue_key"], set())
            hot = [d for d in ranking if (d.split("::")[0],
                                          d.split("::")[1].split("@")[0]) in read]
            ranking = hot + [d for d in ranking if d not in set(hot)]
        ranking = ranking[:LIST_LEN]

        gold_keys = {f"{p_}::{n_}@{s_}" for p_, n_, s_ in gold_funcs}
        metrics = {}
        if eligible:
            first = next((k + 1 for k, d in enumerate(ranking)
                          if d in gold_keys), 0)
            metrics["mrr"] = 1.0 / first if first else 0.0
            for k in KS:
                metrics[f"acc@{k}"] = float(any(d in gold_keys
                                                for d in ranking[:k]))
            # For a bolted-on stage this is "could the ranker have won".
            # For the submitted answer the model never had a candidate set,
            # so the honest ceiling is whether it named the gold region at
            # all, anywhere in its list.
            pool = set(ranking) if args.ranking == "submitted" else set(docs)
            metrics["oracle_in_candidates"] = float(
                any(k_ in pool for k_ in gold_keys))
        out_rows.append({"issue_key": r["issue_key"], "fix_time": r["fix_time"],
                         "strata": r["strata"], "eligible": eligible,
                         "n_gold_functions": len(gold_funcs),
                         "n_candidate_functions": len(docs),
                         "gold_functions": sorted(gold_keys),
                         "ranking": ranking[:20], "metrics": metrics})
        if i % 200 == 0:
            print(f"  {i}/{len(rows)} ({time.time() - t0:.0f}s, "
                  f"fcache {len(fcache)})", flush=True)
            _save_cache(cache_path, fcache, gkey)
    _save_cache(cache_path, fcache, gkey)

    ev = [x for x in out_rows[n_dev:] if x["eligible"]] \
        if not args.limit else [x for x in out_rows if x["eligible"]]
    def agg(sub):
        if not sub:
            return {}
        keys = sub[0]["metrics"].keys()
        return {m: round(sum(x["metrics"][m] for x in sub) / len(sub), 4)
                for m in keys}
    summary = {
        "project": args.project, "n_rows": len(out_rows), "n_dev": n_dev,
        "n_eval_eligible": len(ev),
        "eligible_fraction_all": round(
            stats["eligible"] / len(out_rows), 4),
        "stats": dict(stats),
        "eval_eligible": agg(ev),
        "eval_eligible_hard": agg([x for x in ev if not x["strata"]["easy"]]),
        "eval_eligible_easy": agg([x for x in ev if x["strata"]["easy"]]),
    }
    summary["ranking_source"] = args.ranking
    summary["read_boost"] = args.read_boost
    (OUT / f"{args.project}-functions{args.tag}-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    with (OUT / f"{args.project}-functions{args.tag}.jsonl").open(
            "w", encoding="utf-8") as f:
        for x in out_rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(json.dumps(summary["eval_eligible"], indent=1))
    print("eligible:", summary["eligible_fraction_all"], dict(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
