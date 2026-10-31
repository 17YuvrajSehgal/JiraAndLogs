"""Noise-robustness experiment (reviewer W4: industrial bundles are noisy).

Re-runs the full signal pipeline on PERTURBED query text for a seeded
sample of eval instances, fusing with the CLEAN-tuned conditioned weights
(noise arrives at inference time; nothing is retuned). Conditions:

  clean    unmodified text (sanity anchor; must reproduce the main run)
  dup      every added line is a repeat of a random line of the same text
  foreign  added lines sampled from OTHER issues' texts (same project)
  generic  added lines from generic timeout/retry/GC/health templates
  drop     remove every line carrying a file mention or JVM frame
           (deletes the evidence S1 feeds on; no levels)

Add conditions run at noise ratios x1, x2, x5 (added lines = ratio x
original line count), interleaved at seeded random positions.

Usage:
    python industry-c7/scripts/noise_robustness.py --project kafka
"""

from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import localize  # noqa: E402
from localize import (BENCH, FILE_MENTION_RE, FULL_REPOS, JVM_FRAME_RE,  # noqa: E402
                      LIST_LEN, MEM_DEPTH, OUT, PATH_POOL, PROJECTS,
                      BM25Index, Snapshot, bm25_rank, load_support,
                      parse_iso_epoch, path_tokens, rrf, tokenize, trace_rank)

SEED = 42
SAMPLE = 200
RATIOS = (1, 2, 5)
GENERIC_LINES = [
    "WARN request timed out after 30000 ms, retrying (attempt {i} of 10)",
    "INFO health check ok latency={i}ms",
    "WARN GC pause detected: {i} ms total stop-the-world",
    "ERROR connection reset by peer, reconnecting in {i}s",
    "INFO heartbeat sent to coordinator ({i} ms)",
    "WARN slow operation detected: {i} ms over threshold",
    "INFO periodic flush completed in {i} ms",
    "WARN queue depth {i} above watermark, applying backpressure",
]


def perturb(text: str, cond: str, ratio: int, rng: random.Random,
            foreign_pool: list[str]) -> str:
    lines = text.splitlines() or [text]
    if cond == "clean":
        return text
    if cond == "drop":
        kept = [l for l in lines
                if not (FILE_MENTION_RE.search(l) or JVM_FRAME_RE.search(l))]
        return "\n".join(kept) if kept else ""
    n_add = max(1, int(len(lines) * ratio))
    if cond == "dup":
        add = [rng.choice(lines) for _ in range(n_add)]
    elif cond == "foreign":
        add = [rng.choice(foreign_pool) for _ in range(n_add)]
    else:  # generic
        add = [rng.choice(GENERIC_LINES).format(i=rng.randrange(1, 60000))
               for _ in range(n_add)]
    out = list(lines)
    for l in add:
        out.insert(rng.randrange(len(out) + 1), l)
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, choices=list(FULL_REPOS))
    args = ap.parse_args()
    cfg, git_dir = PROJECTS[args.project], FULL_REPOS[args.project]

    bench = [json.loads(l) for l in
             (BENCH / f"{args.project}.jsonl").open(encoding="utf-8")]
    bench.sort(key=lambda b: b["fix_time"])
    summ = json.load((OUT / f"{args.project}-summary.json").open())
    n_dev = summ["n_dev"]
    w_cond = summ["tuned_weights"]["cond"]
    ev = bench[n_dev:]
    rng = random.Random(SEED)
    sample = sorted(rng.sample(range(len(ev)), min(SAMPLE, len(ev))))
    sample_b = [ev[i] for i in sample]
    # foreign noise: lines from OTHER eval issues of the same project
    foreign_all = {b["issue_key"]: [l for l in b["query_text"].splitlines()
                                    if l.strip()] for b in sample_b}

    mem_by_key, dupclusters, created_map, preds = load_support(
        args.project, cfg["key_prefix"])
    mem_index = BM25Index({k: r["toks"] for k, r in mem_by_key.items()})
    tok_cache_path = OUT / f"blob-tokens-{args.project}.pkl"
    tok_cache: dict[str, Counter] = (pickle.loads(tok_cache_path.read_bytes())
                                     if tok_cache_path.exists() else {})

    def memory_votes(candidate_keys, b, cutoff, qcluster, snap):
        votes, rank = defaultdict(float), 0
        for key in candidate_keys:
            rec = mem_by_key.get(key)
            if (not rec or key == b["issue_key"]
                    or (qcluster is not None and dupclusters.get(key) == qcluster)
                    or rec["fix_shas"] & set(b["fix_shas"])
                    or (rec["resolved"] is not None and rec["resolved"] > cutoff)):
                continue
            rank += 1
            for f in rec["gold_files"]:
                if f in snap.blob_of:
                    votes[f] += 1.0 / rank
            if rank >= MEM_DEPTH:
                break
        return [f for f, _ in
                sorted(votes.items(), key=lambda x: (-x[1], x[0]))][:LIST_LEN]

    def localize_one(b, snap, text):
        qtoks = tokenize(text)
        cutoff = (parse_iso_epoch(b.get("created"))
                  or created_map.get(b["issue_key"]) or b["fix_time"])
        qcluster = dupclusters.get(b["issue_key"])
        trace_grep, has_mention, _ = trace_rank(text, snap)
        path_docs = {f: path_tokens(f) for f in snap.files}
        path_ranked = [f for f, _ in bm25_rank(qtoks, path_docs)][:LIST_LEN]
        memory_arise = memory_votes(preds.get(b["window_id"], []), b, cutoff,
                                    qcluster, snap)
        memory_bm25 = memory_votes(mem_index.rank(qtoks, MEM_DEPTH * 4), b,
                                   cutoff, qcluster, snap)
        pool = list(dict.fromkeys(trace_grep + path_ranked[:PATH_POOL]
                                  + memory_arise + memory_bm25))
        docs = snap.contents(pool, tok_cache)
        content_ranked = [f for f, _ in bm25_rank(qtoks, docs)][:LIST_LEN]
        rk = {"trace_grep": trace_grep, "path_bm25": path_ranked,
              "content_bm25": content_ranked, "memory_arise": memory_arise,
              "memory_bm25": memory_bm25}
        regime = "mention" if has_mention else "no_mention"
        fused = rrf(rk, w_cond[regime])
        gset = set(b["gold_files"])
        return float(any(f in gset for f in fused[:5])), regime

    conds = [("clean", 0)] + [(c, r) for c in ("dup", "foreign", "generic")
                              for r in RATIOS] + [("drop", 0)]
    acc = {f"{c}_x{r}" if r else c: [] for c, r in conds}
    regime_flips = Counter()
    t0 = time.time()
    for i, b in enumerate(sample_b):
        snap = Snapshot(git_dir, b["snapshot_sha"], cfg["src_ext"])
        pool = [l for k, ls in foreign_all.items()
                if k != b["issue_key"] for l in ls]
        base_regime = None
        for c, r in conds:
            prng = random.Random(f"{SEED}:{b['issue_key']}:{c}:{r}")
            text = perturb(b["query_text"], c, r, prng, pool)
            a5, regime = localize_one(b, snap, text)
            key = f"{c}_x{r}" if r else c
            acc[key].append(a5)
            if c == "clean":
                base_regime = regime
            elif regime != base_regime:
                regime_flips[key] += 1
        if i % 25 == 0:
            print(f"  {i}/{len(sample_b)} ({time.time() - t0:.0f}s)", flush=True)

    summary = {"project": args.project, "seed": SEED, "n_sample": len(sample_b),
               "weights": "clean-tuned cond (frozen)",
               "acc@5": {k: round(sum(v) / len(v), 4) for k, v in acc.items()},
               "regime_flips": dict(regime_flips),
               "clean_main_run_acc5": summ["eval"]["cond_ours"]["acc@5"]}
    (OUT / f"{args.project}-noise-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["acc@5"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
