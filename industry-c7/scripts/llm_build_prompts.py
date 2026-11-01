"""Build the LLM fault-localization prompt sets (reviewer W1: 'an
LLM-based localizer, Agentless-style').

Conditions, all on the SAME instances as the lexical pipeline:

  a1  Agentless stage 1: report + the snapshot's directory list ->
      pick up to 15 directories that may hold the faulty code.
  a2  Agentless stage 2: report + the source files inside the chosen
      directories -> ranked top 10 files. (Built from a1 responses.)
  rr  LLM rerank: report + our top-20 fused candidates, each shown with
      its path and up to 25 function/class names (tree-sitter skeleton)
      -> ranked top 10.
  cp  Contamination probe: the issue KEY alone (no body) -> which files
      did the fix touch? Measures how much of this public history the
      model memorized during pretraining. A second variant adds the
      report's first line (title).
  a1d/a2d  de-identified replay of a1/a2 with every issue key scrubbed
      from the report text, on the pre-registered 200/project sample:
      isolates recall-by-key from genuine localization.

Nothing about gold files, memory votes, or strata ever enters a prompt.

Prompt ORDER is deliberate: the 200/project pre-registered sample first
(so the comparable experiment completes even if the GPU job dies), then
the rest of the evaluation split, then the development split.

Usage:
    python industry-c7/scripts/llm_build_prompts.py --stage a1
    python industry-c7/scripts/llm_build_prompts.py --stage a2 \
        --responses industry-c7/data/llm/resp-a1.jsonl
"""

from __future__ import annotations

import argparse
import json
import pickle
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from function_stage import list_functions, parser_for, raw_blobs  # noqa: E402
from localize import (BENCH, FULL_REPOS, OUT, PROJECTS,  # noqa: E402
                      Snapshot, run_git)

P = ("kafka", "mariadb", "mongodb", "qt")
LLM = Path(__file__).resolve().parents[1] / "data/llm"
SEED, SAMPLE = 42, 200
MAX_DIRS_SHOWN = 900
# 500 truncated the candidate list for ~10% of instances and cost ~4 points
# of stage-2 oracle, biased alphabetically (files are listed sorted). 1500
# keeps the prompt near 18k tokens at worst, far inside the 131k window.
MAX_FILES_SHOWN = 1500
MAX_REPORT_CHARS = 24_000
PICK_DIRS, TOP_N, RERANK_N = 15, 10, 20
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,15}-\d{1,6}\b")

SYS = ("You are an expert software maintainer doing fault localization. "
       "You are given a bug report with its logs and a view of the source "
       "tree as it was when the bug was open. The logs usually show where "
       "the failure was DETECTED, which is often not where it was CAUSED. "
       "Reason about the likely cause, then answer with JSON only.")


def report_block(text: str, deid: bool) -> str:
    t = text[:MAX_REPORT_CHARS]
    if deid:
        t = KEY_RE.sub("[ISSUE]", t)
    return t


def ordered_instances() -> list[tuple[str, dict, dict]]:
    """(project, bench row, result row) ordered sample -> eval -> dev."""
    rng = random.Random(SEED)
    buckets: dict[str, list] = {"sample": [], "eval": [], "dev": []}
    for p in P:
        bench = {b["issue_key"]: b for b in
                 (json.loads(l) for l in
                  (BENCH / f"{p}.jsonl").open(encoding="utf-8"))}
        rows = [json.loads(l) for l in
                (OUT / f"{p}-instances.jsonl").open(encoding="utf-8")]
        rows.sort(key=lambda r: r["fix_time"])
        n_dev = json.load((OUT / f"{p}-summary.json").open())["n_dev"]
        dev, ev = rows[:n_dev], rows[n_dev:]
        # same seeded 200 as noise/dense experiments: sample over bench
        # rows sorted by fix_time, eval slice
        bench_sorted = sorted(bench.values(), key=lambda b: b["fix_time"])
        ev_bench = bench_sorted[n_dev:]
        sample_keys = {ev_bench[i]["issue_key"] for i in
                       sorted(rng.sample(range(len(ev_bench)),
                                         min(SAMPLE, len(ev_bench))))}
        for r in ev:
            tag = "sample" if r["issue_key"] in sample_keys else "eval"
            buckets[tag].append((p, bench[r["issue_key"]], r))
        for r in dev:
            buckets["dev"].append((p, bench[r["issue_key"]], r))
    out = []
    for tag in ("sample", "eval", "dev"):
        # round-robin across projects so partial runs cover all four
        byp = defaultdict(list)
        for item in buckets[tag]:
            byp[item[0]].append(item)
        for i in range(max((len(byp[p]) for p in P), default=0)):
            for p in P:
                if i < len(byp[p]):
                    out.append(byp[p][i])
    return out


def tree_of(project: str, sha: str) -> Snapshot:
    return Snapshot(FULL_REPOS[project], sha, PROJECTS[project]["src_ext"])


def skeleton(project: str, snap: Snapshot, paths: list[str],
             fcache: dict) -> dict[str, list[str]]:
    """path -> up to 25 function/class names, from the tree-sitter cache."""
    git_dir = FULL_REPOS[project]
    want = [p_ for p_ in paths if p_ in snap.blob_of and parser_for(p_)]
    missing = [snap.blob_of[p_] for p_ in want if snap.blob_of[p_] not in fcache]
    texts = raw_blobs(git_dir, missing) if missing else {}
    for p_ in want:
        bl = snap.blob_of[p_]
        if bl not in fcache:
            fcache[bl] = list_functions(p_, texts.get(bl, b""))
    return {p_: [n for n, _s, _e in fcache[snap.blob_of[p_]]][:25]
            for p_ in want}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", required=True,
                    choices=["a1", "a2", "rr", "cp", "a1d", "a2d"])
    ap.add_argument("--responses", help="stage-1 responses (for a2/a2d)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    LLM.mkdir(parents=True, exist_ok=True)
    deid = args.stage.endswith("d")
    base = args.stage.rstrip("d")

    items = ordered_instances()
    if deid:  # de-identified ablation runs on the 200/project sample only
        seen: dict[str, int] = defaultdict(int)
        keep = []
        for it in items:
            if seen[it[0]] < SAMPLE:
                seen[it[0]] += 1
                keep.append(it)
        items = keep
    if args.limit:
        items = items[:args.limit]

    picks: dict[str, list[str]] = {}
    if base == "a2":
        for line in open(args.responses, encoding="utf-8"):
            d = json.loads(line)
            picks[d["id"]] = d.get("parsed", {}).get("directories", []) or []

    # the tree-sitter caches are ~100 MB; only the rerank stage reads them
    fcache_by_p = {p: (pickle.loads((OUT / f"funcs-{p}.pkl").read_bytes())
                       if base == "rr" and (OUT / f"funcs-{p}.pkl").exists()
                       else {}) for p in P}
    n_written = 0
    with (LLM / f"prompts-{args.stage}.jsonl").open("w", encoding="utf-8") as f:
        for project, b, r in items:
            pid = f"{project}:{b['issue_key']}"
            rep = report_block(b["query_text"], deid)
            if base == "cp":
                for variant, extra in (
                        ("key", ""),
                        ("key_title", "\nIssue title: "
                         + b["query_text"].splitlines()[0][:200])):
                    user = (
                        f"Issue {b['issue_key']} in the {project} project was "
                        f"fixed by a commit.{extra}\n\n"
                        "From your knowledge of this project's public history, "
                        "which source files did that fix commit modify? "
                        "If you do not recall this specific issue, return an "
                        "empty list and set recalled to false. Do not guess "
                        "from the issue number alone.\n\n"
                        'Answer as JSON: {"recalled": true|false, '
                        '"files": ["path/from/repo/root.ext", ...]}')
                    f.write(json.dumps({
                        "id": f"{pid}:{variant}", "project": project,
                        "issue_key": b["issue_key"], "stage": "cp",
                        "variant": variant, "max_tokens": 1200,
                        "schema": {"type": "object", "properties": {
                            "recalled": {"type": "boolean"},
                            "files": {"type": "array", "maxItems": 20,
                                      "items": {"type": "string"}}},
                            "required": ["recalled", "files"]},
                        "messages": [{"role": "system", "content": SYS},
                                     {"role": "user", "content": user}],
                    }, ensure_ascii=False) + "\n")
                    n_written += 1
                continue

            snap = tree_of(project, b["snapshot_sha"])
            if base == "a1":
                dirs: dict[str, int] = defaultdict(int)
                for path in snap.files:
                    dirs[str(Path(path).parent).replace("\\", "/")] += 1
                listing = sorted(dirs)[:MAX_DIRS_SHOWN]
                body = "\n".join(f"{d}/  ({dirs[d]} files)" for d in listing)
                user = (
                    f"Project: {project}\n\n=== BUG REPORT (with logs) ===\n"
                    f"{rep}\n\n=== SOURCE DIRECTORIES AT THE TIME OF THE "
                    f"REPORT ({len(dirs)} directories, {len(snap.files)} "
                    f"source files) ===\n{body}\n\n"
                    f"Which directories most likely contain the file that "
                    f"CAUSED this bug? List at most {PICK_DIRS}, most likely "
                    "first. Copy the paths exactly.\n"
                    'Answer as JSON: {"directories": ["path/to/dir", ...]}')
                schema = {"type": "object", "properties": {"directories": {
                    "type": "array", "maxItems": PICK_DIRS,
                    "items": {"type": "string"}}}, "required": ["directories"]}
                mt = 2500
            elif base == "a2":
                chosen = [d.rstrip("/") for d in picks.get(pid, [])]
                files = [path for path in snap.files
                         if str(Path(path).parent).replace("\\", "/") in chosen]
                if not files:  # stage-1 gave nothing usable: whole tree head
                    files = snap.files
                files = files[:MAX_FILES_SHOWN]
                body = "\n".join(files)
                user = (
                    f"Project: {project}\n\n=== BUG REPORT (with logs) ===\n"
                    f"{rep}\n\n=== CANDIDATE SOURCE FILES ===\n{body}\n\n"
                    f"Rank the {TOP_N} files most likely to contain the ROOT "
                    "CAUSE of this bug, most likely first. The faulty file is "
                    "often NOT one named in the logs. Copy paths exactly from "
                    "the list.\n"
                    'Answer as JSON: {"files": ["path/from/repo/root.ext", ...]}')
                schema = {"type": "object", "properties": {"files": {
                    "type": "array", "maxItems": TOP_N,
                    "items": {"type": "string"}}}, "required": ["files"]}
                mt = 2500
            else:  # rr
                cands = r["rankings"]["cond_ours"][:RERANK_N]
                sk = skeleton(project, snap, cands, fcache_by_p[project])
                lines = []
                for i, path in enumerate(cands, 1):
                    names = ", ".join(sk.get(path, [])[:25]) or "(not parsed)"
                    lines.append(f"{i}. {path}\n   defines: {names}")
                user = (
                    f"Project: {project}\n\n=== BUG REPORT (with logs) ===\n"
                    f"{rep}\n\n=== CANDIDATE FILES (retrieved, unordered for "
                    f"your purposes) ===\n" + "\n".join(lines) + "\n\n"
                    f"Re-rank these candidates: list the {TOP_N} most likely "
                    "to contain the ROOT CAUSE, most likely first. Use only "
                    "paths from the list above.\n"
                    'Answer as JSON: {"files": ["path/from/repo/root.ext", ...]}')
                schema = {"type": "object", "properties": {"files": {
                    "type": "array", "maxItems": TOP_N,
                    "items": {"type": "string"}}}, "required": ["files"]}
                mt = 2500
            f.write(json.dumps({
                "id": pid, "project": project, "issue_key": b["issue_key"],
                "stage": args.stage, "max_tokens": mt, "schema": schema,
                "messages": [{"role": "system", "content": SYS},
                             {"role": "user", "content": user}],
            }, ensure_ascii=False) + "\n")
            n_written += 1
    if base == "rr":
        for p in P:
            (OUT / f"funcs-{p}.pkl").write_bytes(pickle.dumps(fcache_by_p[p]))
    size = (LLM / f"prompts-{args.stage}.jsonl").stat().st_size
    print(f"wrote {n_written} prompts, {size / 1e6:.1f} MB -> "
          f"{LLM / f'prompts-{args.stage}.jsonl'}")
    print(f"approx input tokens: {size / 4 / 1e6:.1f}M")
    return 0


if __name__ == "__main__":
    sys.exit(main())
