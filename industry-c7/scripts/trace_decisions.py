"""Boil every run trace down to the decisions the agent made.

A trace is ~380 KB per instance (8.9 GB for the main run) because it keeps
every tool output in full. The question asked of it here is small: at each
turn, which tool did the model pick, on what, and did the result contain a
gold file? This writes one compact row per instance so that question can
be answered on a laptop.

Per instance:
  turns[]   one per model call: tokens in/out, how much history was cut,
            whether tools were still offered, and the tool calls it made
  calls[]   tool, its main argument, output size, n gold files named in
            the output, and (for read tools) whether the path IS a gold file

Usage (cluster login node, stdlib only):
    python scripts/trace_decisions.py --runs data/agent/runs \
        --rows 'data/agent/agent-full-*.jsonl' --out data/agent/trace-decisions.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from multiprocessing import Pool
from pathlib import Path

ARG = ("path", "name", "symbol", "query", "line")


def same(a: str, b: str) -> bool:
    """The model writes paths; accept a suffix match either way."""
    a, b = a.strip("/"), b.strip("/")
    return bool(a) and (a == b or a.endswith("/" + b) or b.endswith("/" + a))


def _from_line(out: str):
    i = out.find('"from_line": ')
    if i < 0:
        return None
    j = i + 13
    k = j
    while k < len(out) and out[k].isdigit():
        k += 1
    return int(out[j:k]) if k > j else None


def digest(job):
    path, rid, gold = job
    turns, cur = [], None
    try:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if r["kind"] == "model_call":
                c = r.get("context") or {}
                u = r.get("usage") or {}
                cur = {"in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0),
                       "cut": c.get("pct_cut", 0), "dropped": c.get("n_dropped_results", 0),
                       "offered": len(r.get("tools_offered") or []),
                       "fin": r.get("finish_reason"), "calls": []}
                turns.append(cur)
            elif r["kind"] == "tool_call" and cur is not None:
                inp = r.get("input") or {}
                out = r.get("output_full") or ""
                p = str(inp.get("path") or "")
                cur["calls"].append({
                    "tool": r["tool"],
                    "arg": {k: inp[k] for k in ARG if inp.get(k) not in (None, "", 0)},
                    "around": bool(inp.get("around")),
                    # which part of the file was read: the symbol asked for,
                    # and the first line the tool actually returned
                    "sym": str(inp.get("around") or "")[:80],
                    "n": inp.get("n"),
                    "from": _from_line(out),
                    "chars": r.get("output_chars", len(out)),
                    "gold_in_out": sum(g in out for g in gold),
                    "path_is_gold": any(same(p, g) for g in gold) if p else None,
                    "repeat": "already made" in out[:400],
                    "err": '"error"' in out[:200]})
    except Exception as e:  # noqa: BLE001 - one bad trace must not stop the pass
        return {"id": rid, "error": f"{type(e).__name__}: {e}"}
    return {"id": rid, "turns": turns}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=8)
    args = ap.parse_args()
    gold = {}
    for f in glob.glob(args.rows):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("gold_files"):
                gold[r["id"]] = r["gold_files"]
    jobs = []
    for p in Path(args.runs).glob("full-*/*.jsonl"):
        proj, key = p.stem.split("_", 1)
        rid = f"{proj}:{key}"
        if rid in gold:
            jobs.append((str(p), rid, gold[rid]))
    print(f"{len(gold)} rows, {len(jobs)} traces", flush=True)
    with Pool(args.procs) as pool, open(args.out, "w", encoding="utf-8") as fh:
        for i, d in enumerate(pool.imap_unordered(digest, jobs, chunksize=50)):
            fh.write(json.dumps(d) + "\n")
            if i % 2000 == 0:
                print(i, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
