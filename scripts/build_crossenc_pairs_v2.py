"""G2: build (window, ticket) training pairs for cross-encoder fine-tune
on the v2 in-distribution resplit.

Differences from build_crossenc_pairs.py:
  - Uses the v2 window-level resplit manifest (train/val by run, not by family).
  - Mixes BM25-mined hard negatives with random negatives, matching G1's
    BiEncoder recipe (n_hard_negs=2, n_random_negs=1).

Output: <out> .jsonl with rows {"query","doc","label","window_id","memory_id","split"}.

Usage:
    PYTHONPATH=src python scripts/build_crossenc_pairs_v2.py \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --out data/derived/.../v2g-final-models/g2-crossencoder-rerank/triplets_v2.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from loganalyzer.data.loaders import load_dataset
from loganalyzer.features.text import build_memory_doc_text, build_window_query_text
from loganalyzer.memory.corpus import MemoryCorpus
from loganalyzer.memory.retrieval import BM25Retriever
from memorygraph.humanized_loader import load_humanized_corpus
from v2_advanced.proposal_a_resplit.window_split import (
    WindowSplitManifest,
    iter_window_split,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--humanized-subdir", default="bulk-20260531")
    p.add_argument("--humanized-root", default="jira-shadow-humanized-v2")
    p.add_argument("--n-hard-negs", type=int, default=2)
    p.add_argument("--n-random-negs", type=int, default=1)
    p.add_argument("--bm25-top-n", type=int, default=20)
    p.add_argument("--manifest-name", default="triage-split-manifest-v2-resplit.json")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    rng = random.Random(args.seed)

    # Load dataset + V2 manifest
    print(f"[g2-pairs] loading dataset from {args.global_dir}")
    ds = load_dataset(args.global_dir)
    manifest_path = args.global_dir / args.manifest_name
    print(f"[g2-pairs] loading v2 window manifest {args.manifest_name}")
    v2 = WindowSplitManifest.from_path(manifest_path)

    train = list(iter_window_split(ds.windows, v2, "train"))
    val = list(iter_window_split(ds.windows, v2, "validation"))
    print(f"[g2-pairs] train={len(train)} val={len(val)}")

    # Load humanized memory
    print(f"[g2-pairs] loading humanized corpus "
          f"{args.humanized_root}/{args.humanized_subdir}")
    memory = load_humanized_corpus(
        args.global_dir,
        humanized_subdir=args.humanized_subdir,
        humanized_root=args.humanized_root,
    )
    corpus = MemoryCorpus(issues=memory, mode="time_ordered")
    by_id = corpus.by_id()
    print(f"[g2-pairs] memory: {len(memory)} tickets")

    print("[g2-pairs] fitting BM25 over corpus")
    bm25 = BM25Retriever()
    bm25.fit(corpus)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_pos = n_neg_bm25 = n_neg_random = 0
    n_windows = 0

    val_ids = {w.window_id for w in val}

    with args.out.open("w", encoding="utf-8") as f:
        for window in train + val:
            gold_ids = list(
                getattr(window, "matched_memory_issue_ids", None)
                or window.raw.get("matched_memory_issue_ids", [])
                or []
            )
            if not gold_ids:
                continue
            visible = corpus.visible_to(window)
            visible_ids = {iss.jira_shadow_issue_id for iss in visible}
            gold_in_view = [gid for gid in gold_ids if gid in visible_ids]
            if not gold_in_view:
                continue

            query_text = build_window_query_text(window) or ""
            if not query_text:
                continue
            window_split = "val" if window.window_id in val_ids else "train"
            n_windows += 1
            gold_set = set(gold_in_view)

            # Positives
            for gid in gold_in_view:
                doc_text = build_memory_doc_text(by_id[gid])
                row = {
                    "query": query_text,
                    "doc": doc_text,
                    "label": 1,
                    "window_id": window.window_id,
                    "memory_id": gid,
                    "split": window_split,
                }
                f.write(json.dumps(row) + "\n")
                n_pos += 1

            # BM25 hard negs (top-N not in gold)
            hits = bm25.retrieve(window, corpus, top_k=args.bm25_top_n)
            wrong = [h for h in hits if h.issue_id not in gold_set]
            chosen_wrong = rng.sample(wrong, min(args.n_hard_negs, len(wrong))) if wrong else []
            wrong_ids = {h.issue_id for h in chosen_wrong}
            for h in chosen_wrong:
                doc_text = build_memory_doc_text(h.issue)
                row = {
                    "query": query_text,
                    "doc": doc_text,
                    "label": 0,
                    "window_id": window.window_id,
                    "memory_id": h.issue_id,
                    "neg_kind": "bm25_hard",
                    "split": window_split,
                }
                f.write(json.dumps(row) + "\n")
                n_neg_bm25 += 1

            # Random negs (visible, not gold, not BM25-top-N)
            bm25_top_ids = {h.issue_id for h in hits}
            random_pool = [
                iss for iss in visible
                if iss.jira_shadow_issue_id not in gold_set
                and iss.jira_shadow_issue_id not in bm25_top_ids
            ]
            chosen_random = rng.sample(random_pool, min(args.n_random_negs, len(random_pool)))
            for iss in chosen_random:
                doc_text = build_memory_doc_text(iss)
                row = {
                    "query": query_text,
                    "doc": doc_text,
                    "label": 0,
                    "window_id": window.window_id,
                    "memory_id": iss.jira_shadow_issue_id,
                    "neg_kind": "random",
                    "split": window_split,
                }
                f.write(json.dumps(row) + "\n")
                n_neg_random += 1

    print(f"\n[g2-pairs] wrote {args.out}")
    print(f"  windows kept:    {n_windows}")
    print(f"  positives:       {n_pos}")
    print(f"  bm25 hard negs:  {n_neg_bm25}")
    print(f"  random negs:     {n_neg_random}")
    print(f"  total rows:      {n_pos + n_neg_bm25 + n_neg_random}")


if __name__ == "__main__":
    main()
