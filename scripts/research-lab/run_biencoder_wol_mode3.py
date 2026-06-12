"""Run the G1 BiEncoder on the WoL Mode 3 self-contained retrieval task.

Mode 3 evaluation per docs7/REAL-DATA-WoL-PLAN.md v3 §7. This is the
core retrieval signal — TCH-Lite's L2 anchor pool and one of its four
L2 RRF retrievers. We measure Hit@1, Hit@5, MRR under BOTH match
relations (coarse and strong) on the family-stratified test partition
(test families = wol-kafka, wol-mariadb-server).

The full Mode 3 cascade evaluation requires also running Hybrid-RRF,
LogSeq2Vec, KG-Retrieval, and the agent against the WoL dataset; this
script does the cheapest, most load-bearing slice first. See the doc
for follow-up phases.

Outputs:
    <out>/biencoder-predictions.jsonl       — per-window prediction records
    <out>/biencoder-mode3-results.json      — headline Hit@K metrics
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path,
                    default="data/derived/global/2026-06-11-wol-real-global")
    ap.add_argument("--out-dir", type=Path,
                    default="data/derived/global/2026-06-11-wol-real-global/tch-lite-refit")
    ap.add_argument("--humanized-subdir", default="bulk-20260611")
    ap.add_argument("--humanized-root",   default="jira-shadow-humanized-v2")
    ap.add_argument("--n-hard-negs",   type=int, default=2)
    ap.add_argument("--n-random-negs", type=int, default=1)
    ap.add_argument("--use-all-golds", action="store_true",
                    help="If set, emit one training example per (window, gold) pair. "
                         "Default off — one random gold per window per epoch keeps fit "
                         "time tractable when coarse-match yields ~25 golds per window.")
    ap.add_argument("--finetune-epochs", type=int, default=5)
    ap.add_argument("--max-chars", type=int, default=512)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    sys.path.insert(0, "src")

    # Defer the heavy import until after the path is set.
    from neural_models.bi_encoder import BiEncoderRetrievalPipeline
    from core.data.loaders import load_dataset

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Instantiate and run the G1 BiEncoder ----
    print(f"[bienc] global_dir = {args.global_dir}")
    print(f"[bienc] config: n_hard_negs={args.n_hard_negs}, "
          f"n_random_negs={args.n_random_negs}, use_all_golds={args.use_all_golds}, "
          f"epochs={args.finetune_epochs}")
    print()

    pipeline = BiEncoderRetrievalPipeline(
        humanized_subdir=args.humanized_subdir,
        humanized_root=args.humanized_root,
        max_chars=args.max_chars,
        finetune_epochs=args.finetune_epochs,
        n_hard_negs=args.n_hard_negs,
        n_random_negs=args.n_random_negs,
        use_all_golds=args.use_all_golds,
        seed=args.seed,
    )

    t0 = time.time()
    result = pipeline.train_and_predict(
        global_dir=args.global_dir,
        runs_root=Path("data/runs"),  # unused but required
        target_fpr=0.05,
    )
    wall = time.time() - t0
    print(f"\n[bienc] fit+predict completed in {wall:.1f}s "
          f"(fit={result.fit_seconds:.1f}s, predict={result.predict_seconds:.1f}s)")
    print(f"[bienc] {len(result.predictions)} test predictions")

    # ---- Persist per-window predictions ----
    pred_path = args.out_dir / "biencoder-predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as fh:
        for p in result.predictions:
            fh.write(json.dumps(p.as_dict(), default=str, ensure_ascii=False) + "\n")
    print(f"\n[bienc] wrote predictions to {pred_path}")

    # ---- Load strong-match gold ----
    strong_path = args.global_dir / "window-memory-matchings-strong.jsonl"
    strong_gold = {}
    if strong_path.exists():
        for line in strong_path.open(encoding="utf-8"):
            d = json.loads(line)
            strong_gold[d["window_id"]] = set(d.get("matched_memory_issue_ids") or [])
    print(f"[bienc] loaded strong-match gold for {len(strong_gold)} windows")

    # ---- Compute Hit@K under both relations ----
    def metrics(predictions, gold_lookup, label):
        """gold_lookup is either None (use prediction's own gold) or a dict."""
        h1 = h5 = n = 0
        mrr_sum = 0.0
        per_proj_stats = defaultdict(lambda: {"n": 0, "h1": 0, "h5": 0, "mrr_sum": 0.0})

        # Load per-window project for stratification
        ds = load_dataset(args.global_dir)
        proj_by_wid = {w.window_id: getattr(w, "scenario_family", "?") for w in ds.windows}

        for p in predictions:
            wid = p.window_id
            if gold_lookup is None:
                gold = set(p.gold_matched_issue_ids or [])
            else:
                gold = gold_lookup.get(wid, set())
            if not gold:
                continue
            n += 1
            top = list(p.matched_issue_ids or [])
            proj = proj_by_wid.get(wid, "?")
            per_proj_stats[proj]["n"] += 1
            for i, t in enumerate(top, 1):
                if t in gold:
                    if i == 1:
                        h1 += 1
                        per_proj_stats[proj]["h1"] += 1
                    if i <= 5:
                        h5 += 1
                        per_proj_stats[proj]["h5"] += 1
                    mrr_sum += 1.0 / i
                    per_proj_stats[proj]["mrr_sum"] += 1.0 / i
                    break

        out = {
            "label":      label,
            "n_with_gold": n,
            "hit_at_1":   h1 / max(1, n),
            "hit_at_5":   h5 / max(1, n),
            "mrr":        mrr_sum / max(1, n),
            "per_project": {
                proj: {
                    "n":        v["n"],
                    "hit_at_1": v["h1"] / max(1, v["n"]),
                    "hit_at_5": v["h5"] / max(1, v["n"]),
                    "mrr":      v["mrr_sum"] / max(1, v["n"]),
                }
                for proj, v in per_proj_stats.items()
            },
        }
        return out

    coarse_m = metrics(result.predictions, None,                "coarse")
    strong_m = metrics(result.predictions, strong_gold,         "strong")

    # ---- Save and print ----
    results = {
        "config": {
            "global_dir":     str(args.global_dir),
            "humanized_root": args.humanized_root,
            "humanized_subdir": args.humanized_subdir,
            "n_hard_negs":    args.n_hard_negs,
            "n_random_negs":  args.n_random_negs,
            "use_all_golds":  args.use_all_golds,
            "finetune_epochs": args.finetune_epochs,
            "max_chars":      args.max_chars,
            "seed":           args.seed,
        },
        "metadata": {
            "n_predictions": len(result.predictions),
            "fit_seconds":   result.fit_seconds,
            "predict_seconds": result.predict_seconds,
            "wall_seconds":  wall,
            **result.metadata,
        },
        "coarse": coarse_m,
        "strong": strong_m,
    }

    out_path = args.out_dir / "biencoder-mode3-results.json"
    out_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"[bienc] wrote results to {out_path}\n")

    print("=" * 78)
    print(f"{'metric':<20s}  {'coarse-match':>14s}  {'strong-match':>14s}")
    print("-" * 78)
    print(f"{'n test queries':<20s}  {coarse_m['n_with_gold']:>14d}  {strong_m['n_with_gold']:>14d}")
    print(f"{'Hit@1':<20s}  {coarse_m['hit_at_1']:>14.4f}  {strong_m['hit_at_1']:>14.4f}")
    print(f"{'Hit@5':<20s}  {coarse_m['hit_at_5']:>14.4f}  {strong_m['hit_at_5']:>14.4f}")
    print(f"{'MRR':<20s}  {coarse_m['mrr']:>14.4f}  {strong_m['mrr']:>14.4f}")
    print()
    print("=== per-project Hit@5 (coarse match) ===")
    for proj, v in sorted(coarse_m["per_project"].items()):
        print(f"  {proj:<30s}  n={v['n']:>4d}  Hit@1={v['hit_at_1']:>.4f}  "
              f"Hit@5={v['hit_at_5']:>.4f}  MRR={v['mrr']:>.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
