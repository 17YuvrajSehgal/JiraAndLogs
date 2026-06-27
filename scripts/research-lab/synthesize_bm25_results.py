"""Build bm25-mode3-results.json from bm25-predictions.jsonl.

run_bm25_wol_mode3.py only writes the predictions JSONL — it doesn't write
the headline-metrics JSON that biencoder / kg-retrieval emit. This script
fills that gap so the cascade aggregator (run_all_v3_cascades.sh) can find
all four results files.

Same metric computation as run_biencoder_wol_mode3.py lines 100-150:
  - Hit@1, Hit@5, MRR under BOTH coarse and strong match
  - Per-project stratification
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path, required=True)
    args = ap.parse_args()

    out_dir = args.global_dir / "tch-lite-refit"
    preds_path = out_dir / "bm25-predictions.jsonl"
    if not preds_path.exists():
        raise SystemExit(f"missing predictions file: {preds_path}")

    # Load predictions
    with preds_path.open(encoding="utf-8") as fh:
        predictions = [json.loads(line) for line in fh if line.strip()]
    print(f"[synth] loaded {len(predictions)} BM25 predictions")

    # Load strong-match gold
    strong_path = args.global_dir / "window-memory-matchings-strong.jsonl"
    strong_gold: dict[str, set[str]] = {}
    if strong_path.exists():
        with strong_path.open(encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                strong_gold[d["window_id"]] = set(d.get("matched_memory_issue_ids") or [])
    print(f"[synth] loaded strong-match gold for {len(strong_gold)} windows")

    def metrics(preds, gold_lookup, label: str) -> dict:
        h1 = h5 = n = 0
        mrr_sum = 0.0
        per_proj = defaultdict(lambda: {"n": 0, "h1": 0, "h5": 0, "mrr_sum": 0.0})
        for p in preds:
            wid = p["window_id"]
            if gold_lookup is None:
                gold = set(p.get("gold_matched_issue_ids") or [])
            else:
                gold = gold_lookup.get(wid, set())
            if not gold:
                continue
            n += 1
            top = list(p.get("matched_issue_ids") or [])
            proj = p.get("scenario_family", "?")
            per_proj[proj]["n"] += 1
            for i, t in enumerate(top, 1):
                if t in gold:
                    if i == 1:
                        h1 += 1
                        per_proj[proj]["h1"] += 1
                    if i <= 5:
                        h5 += 1
                        per_proj[proj]["h5"] += 1
                    mrr_sum += 1.0 / i
                    per_proj[proj]["mrr_sum"] += 1.0 / i
                    break
        return {
            "label":       label,
            "n_with_gold": n,
            "hit_at_1":    h1 / max(1, n),
            "hit_at_5":    h5 / max(1, n),
            "mrr":         mrr_sum / max(1, n),
            "per_project": {
                proj: {
                    "n":        v["n"],
                    "hit_at_1": v["h1"] / max(1, v["n"]),
                    "hit_at_5": v["h5"] / max(1, v["n"]),
                    "mrr":      v["mrr_sum"] / max(1, v["n"]),
                }
                for proj, v in per_proj.items()
            },
        }

    coarse = metrics(predictions, None, "coarse")
    strong = metrics(predictions, strong_gold, "strong")

    results = {
        "config": {
            "global_dir": str(args.global_dir),
            "synthesized_post_hoc": True,
            "note": (
                "Results JSON synthesized from bm25-predictions.jsonl because "
                "run_bm25_wol_mode3.py does not write a headline-metrics file. "
                "Metric computation mirrors run_biencoder_wol_mode3.py."
            ),
        },
        "metadata": {
            "n_predictions": len(predictions),
            "retrieval":     "bm25_retrieval_only",
            # Wall time + fit/predict seconds not available — they were
            # printed to stdout by the original run. Sourced from the
            # user-pasted log lines:
            "fit_seconds":     13167.36,  # 22:07:16 → 01:46:34 = ~3h 39m
            "predict_seconds": 56275.54,  # from log line
            "wall_seconds":    69442.9,
        },
        "coarse": coarse,
        "strong": strong,
    }

    out_path = out_dir / "bm25-mode3-results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[synth] wrote {out_path}")

    print()
    print("=" * 78)
    print(f"{'metric':<20s}  {'coarse-match':>14s}  {'strong-match':>14s}")
    print("-" * 78)
    print(f"{'n test queries':<20s}  {coarse['n_with_gold']:>14d}  {strong['n_with_gold']:>14d}")
    print(f"{'Hit@1':<20s}  {coarse['hit_at_1']:>14.4f}  {strong['hit_at_1']:>14.4f}")
    print(f"{'Hit@5':<20s}  {coarse['hit_at_5']:>14.4f}  {strong['hit_at_5']:>14.4f}")
    print(f"{'MRR':<20s}  {coarse['mrr']:>14.4f}  {strong['mrr']:>14.4f}")
    print()
    print("=== per-project Hit@5 (coarse) ===")
    for proj, v in sorted(coarse["per_project"].items()):
        print(f"  {proj:<30s}  n={v['n']:>4d}  Hit@1={v['hit_at_1']:>.4f}  "
              f"Hit@5={v['hit_at_5']:>.4f}  MRR={v['mrr']:>.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
