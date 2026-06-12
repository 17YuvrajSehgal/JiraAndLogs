"""Run LogSeq2Vec on the WoL Mode 3 self-contained retrieval task.

Mirror of run_biencoder_wol_mode3.py: same dataset, same family-stratified
split, same dual-relation (coarse / strong) Hit@K evaluation, same
per-project stratification. Outputs land alongside the BiEncoder results.

Prerequisites:
    * scripts/research-lab/build_wol_logseq.py has run so
      data/derived/global/2026-06-11-wol-real-global/v2_logseq/<wid>.jsonl
      exists for every window.

Outputs:
    <out>/logseq2vec-predictions.jsonl   — per-window predictions
    <out>/logseq2vec-mode3-results.json  — headline Hit@K
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
                    default=Path("data/derived/global/2026-06-11-wol-real-global"))
    ap.add_argument("--out-dir", type=Path,
                    default=Path("data/derived/global/2026-06-11-wol-real-global/tch-lite-refit"))
    ap.add_argument("--humanized-subdir", default="bulk-20260611")
    ap.add_argument("--humanized-root",   default="jira-shadow-humanized-v2")
    ap.add_argument("--logseq-subdir",    default="v2_logseq")
    ap.add_argument("--epochs",        type=int, default=5)
    ap.add_argument("--batch-size",    type=int, default=8)
    ap.add_argument("--n-hard-negs",   type=int, default=3)
    ap.add_argument("--max-lines",     type=int, default=80)
    ap.add_argument("--max-chars-doc", type=int, default=512)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    sys.path.insert(0, "src")

    from v2_advanced.proposal_b_logseq2vec.pipeline import LogSeq2VecRetrievalPipeline
    from loganalyzer.data.loaders import load_dataset

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[logseq2vec] global_dir = {args.global_dir}")
    print(f"[logseq2vec] config: epochs={args.epochs}, n_hard_negs={args.n_hard_negs}, "
          f"max_lines={args.max_lines}")
    print()

    pipeline = LogSeq2VecRetrievalPipeline(
        humanized_subdir=args.humanized_subdir,
        humanized_root=args.humanized_root,
        logseq_subdir=args.logseq_subdir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        n_hard_negs=args.n_hard_negs,
        max_lines=args.max_lines,
        max_chars_doc=args.max_chars_doc,
        seed=args.seed,
    )

    t0 = time.time()
    result = pipeline.train_and_predict(
        global_dir=args.global_dir,
        runs_root=Path("data/runs"),  # unused
        target_fpr=0.05,
    )
    wall = time.time() - t0
    print(f"\n[logseq2vec] fit+predict completed in {wall:.1f}s "
          f"(fit={result.fit_seconds:.1f}s, predict={result.predict_seconds:.1f}s)")
    print(f"[logseq2vec] {len(result.predictions)} test predictions")

    pred_path = args.out_dir / "logseq2vec-predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as fh:
        for p in result.predictions:
            fh.write(json.dumps(p.as_dict(), default=str, ensure_ascii=False) + "\n")
    print(f"[logseq2vec] wrote predictions to {pred_path}")

    strong_path = args.global_dir / "window-memory-matchings-strong.jsonl"
    strong_gold = {}
    if strong_path.exists():
        for line in strong_path.open(encoding="utf-8"):
            d = json.loads(line)
            strong_gold[d["window_id"]] = set(d.get("matched_memory_issue_ids") or [])
    print(f"[logseq2vec] loaded strong-match gold for {len(strong_gold)} windows")

    def metrics(predictions, gold_lookup, label):
        h1 = h5 = n = 0
        mrr_sum = 0.0
        per_proj_stats = defaultdict(lambda: {"n": 0, "h1": 0, "h5": 0, "mrr_sum": 0.0})

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

        return {
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

    coarse_m = metrics(result.predictions, None,        "coarse")
    strong_m = metrics(result.predictions, strong_gold, "strong")

    results = {
        "config": {
            "global_dir":      str(args.global_dir),
            "humanized_root":  args.humanized_root,
            "humanized_subdir": args.humanized_subdir,
            "logseq_subdir":   args.logseq_subdir,
            "epochs":          args.epochs,
            "n_hard_negs":     args.n_hard_negs,
            "max_lines":       args.max_lines,
            "max_chars_doc":   args.max_chars_doc,
            "seed":            args.seed,
        },
        "metadata": {
            "n_predictions":   len(result.predictions),
            "fit_seconds":     result.fit_seconds,
            "predict_seconds": result.predict_seconds,
            "wall_seconds":    wall,
            **result.metadata,
        },
        "coarse": coarse_m,
        "strong": strong_m,
    }

    out_path = args.out_dir / "logseq2vec-mode3-results.json"
    out_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"[logseq2vec] wrote results to {out_path}\n")

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
