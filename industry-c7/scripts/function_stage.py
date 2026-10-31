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
                      PROJECTS, bm25_rank, tokenize)
from mine_benchmark import run_git  # noqa: E402

from tree_sitter_language_pack import get_parser  # noqa: E402

TOP_FILES = 10
LIST_LEN = 50
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")

# extension -> grammar; .yy/.idl/.qml have no reliable function grammar here
LANG_OF = {".java": "java", ".scala": "scala"}
for _e in (".c", ".cc", ".cpp", ".h", ".hpp", ".ic", ".inl", ".mm"):
    LANG_OF[_e] = "cpp"

_parsers: dict[str, object] = {}


def parser_for(path: str):
    lang = LANG_OF.get(Path(path).suffix.lower())
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
    tree = p.parse(blob_text)
    out: list[tuple[str, int, int]] = []
    stack = [tree.root_node]
    while stack:
        n = stack.pop()
        if n.type in ("method_declaration", "constructor_declaration",
                      "function_definition"):
            if n.type == "function_definition" and n.child_by_field_name("declarator"):
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

    cache_path = OUT / f"funcs-{args.project}.pkl"
    fcache: dict[str, list] = (pickle.loads(cache_path.read_bytes())
                               if cache_path.exists() else {})

    out_rows, stats, t0 = [], Counter(), time.time()
    for i, r in enumerate(rows):
        b = bench[r["issue_key"]]
        snap_files = r["rankings"]["cond_ours"][:TOP_FILES]
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
        qtoks = tokenize(b["query_text"])
        ranking = [d for d, _ in bm25_rank(qtoks, docs)][:LIST_LEN]

        gold_keys = {f"{p_}::{n_}@{s_}" for p_, n_, s_ in gold_funcs}
        metrics = {}
        if eligible:
            first = next((k + 1 for k, d in enumerate(ranking)
                          if d in gold_keys), 0)
            metrics["mrr"] = 1.0 / first if first else 0.0
            for k in KS:
                metrics[f"acc@{k}"] = float(any(d in gold_keys
                                                for d in ranking[:k]))
            metrics["oracle_in_candidates"] = float(
                any(k_ in docs for k_ in gold_keys))
        out_rows.append({"issue_key": r["issue_key"], "fix_time": r["fix_time"],
                         "strata": r["strata"], "eligible": eligible,
                         "n_gold_functions": len(gold_funcs),
                         "n_candidate_functions": len(docs),
                         "gold_functions": sorted(gold_keys),
                         "ranking": ranking[:20], "metrics": metrics})
        if i % 200 == 0:
            print(f"  {i}/{len(rows)} ({time.time() - t0:.0f}s, "
                  f"fcache {len(fcache)})", flush=True)
            cache_path.write_bytes(pickle.dumps(fcache))
    cache_path.write_bytes(pickle.dumps(fcache))

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
    (OUT / f"{args.project}-functions-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    with (OUT / f"{args.project}-functions.jsonl").open("w", encoding="utf-8") as f:
        for x in out_rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(json.dumps(summary["eval_eligible"], indent=1))
    print("eligible:", summary["eligible_fraction_all"], dict(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
