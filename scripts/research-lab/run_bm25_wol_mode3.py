"""Run BM25 baseline on the WoL Mode 3 test split.

Naive single-retriever baseline that the paper's "Hybrid-RRF fusion
beats BM25" claim needs as a reference (RQ-E3).

Mirrors `run_biencoder_wol_mode3.py` shape: instantiates the
`BM25RetrievalPipeline` from `src/comparison/pipelines_retrieval.py`
against the WoL global_dir; writes predictions to
`tch-lite-refit/bm25-predictions.jsonl`.

BM25 is rule-based (no fine-tune), so this completes in seconds
even on 2000-ticket WoL memory.

Usage:
    PYTHONPATH=src python scripts/research-lab/run_bm25_wol_mode3.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path,
                    default="data/derived/global/2026-06-11-wol-real-global")
    ap.add_argument("--out-dir", type=Path,
                    default="data/derived/global/2026-06-11-wol-real-global/tch-lite-refit")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.path.insert(0, "src")

    from comparison.pipelines_retrieval import BM25RetrievalPipeline

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[bm25] global_dir = {args.global_dir}")
    pipeline = BM25RetrievalPipeline()

    t0 = time.time()
    result = pipeline.train_and_predict(
        global_dir=args.global_dir,
        runs_root=Path("data/runs"),       # unused but required
        target_fpr=0.05,
    )
    wall = time.time() - t0
    print(f"\n[bm25] fit+predict completed in {wall:.1f}s "
          f"({len(result.predictions)} predictions)")

    # Write the predictions JSONL
    preds_path = args.out_dir / "bm25-predictions.jsonl"
    with preds_path.open("w", encoding="utf-8") as fh:
        for pred in result.predictions:
            fh.write(json.dumps(pred.as_dict()) + "\n")
    print(f"[bm25] wrote {preds_path}")

    # Quick Hit@K
    h1 = h5 = evaluable = 0
    for pred in result.predictions:
        gold = set(pred.gold_matched_issue_ids or ())
        if not gold:
            continue
        evaluable += 1
        matched = pred.matched_issue_ids or []
        if matched and matched[0] in gold:
            h1 += 1
        if any(m in gold for m in matched[:5]):
            h5 += 1
    if evaluable:
        print(f"[bm25] WoL Hit@K: n_evaluable={evaluable}, "
              f"Hit@1={h1/evaluable:.4f}, Hit@5={h5/evaluable:.4f}")
    else:
        print("[bm25] no evaluable cases")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
