"""Run DiagnosisAgent on WoL Mode 3 (full 450 test windows).

Mirror of run_biencoder_wol_mode3.py.

Reuses the cached Hybrid-RRF predictions from `tch-lite-refit/hybrid-rrf-predictions.jsonl`
to skip the 73-min BiEncoder + SPLADE refit. Loads the LLM-extracted ticket
entities from `v2_kg_extractions/all_extractions.jsonl`. For each test
window, gives the agent the top-10 hybrid candidates and lets it re-rank
into top-5 via LM-Studio-served LLM (qwen/qwen3.6-35b-a3b).

Prerequisites:
    * `lms load qwen/qwen3.6-35b-a3b -y` — model loaded in LM Studio
    * Hybrid-RRF predictions already cached (run_hybrid_rrf_wol_mode3.py)
    * LLM ticket extractions already cached (extract_tickets_cli.py)

Outputs:
    <out>/diagnosis-agent-predictions.jsonl
    <out>/diagnosis-agent-mode3-results.json
"""
from __future__ import annotations

import argparse
import json
import os
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
    ap.add_argument("--model", default="qwen/qwen3.6-35b-a3b")
    ap.add_argument("--subsample-size", type=int, default=0,
                    help="0 = run on all test windows; >0 = sample N for latency")
    ap.add_argument("--top-k-input", type=int, default=10)
    ap.add_argument("--top-k-output", type=int, default=5)
    args = ap.parse_args()

    sys.path.insert(0, "src")

    from v2_advanced.proposal_e_agent.pipeline import DiagnosisAgentPipeline
    from loganalyzer.data.loaders import load_dataset

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Point the agent at the cached Hybrid-RRF predictions so it skips
    # the 73-min refit.
    hybrid_preds = args.out_dir / "hybrid-rrf-predictions.jsonl"
    if not hybrid_preds.exists():
        raise SystemExit(f"Cached hybrid predictions missing at {hybrid_preds}. "
                         "Run run_hybrid_rrf_wol_mode3.py first.")
    os.environ["V2_AGENT_HYBRID_PREDICTIONS_PATH"] = str(hybrid_preds)
    print(f"[agent] V2_AGENT_HYBRID_PREDICTIONS_PATH = {hybrid_preds}", flush=True)
    print(f"[agent] subsample_size={args.subsample_size}, top_k_input={args.top_k_input}, "
          f"top_k_output={args.top_k_output}", flush=True)

    pipeline = DiagnosisAgentPipeline(
        humanized_subdir=args.humanized_subdir,
        humanized_root=args.humanized_root,
        lm_studio_model=args.model,
        subsample_size=args.subsample_size,
        top_k_input=args.top_k_input,
        top_k_output=args.top_k_output,
    )

    t0 = time.time()
    result = pipeline.train_and_predict(
        global_dir=args.global_dir,
        runs_root=Path("data/runs"),
        target_fpr=0.05,
    )
    wall = time.time() - t0
    print(f"\n[agent] fit+predict completed in {wall:.1f}s "
          f"(fit={result.fit_seconds:.1f}s, predict={result.predict_seconds:.1f}s)", flush=True)
    print(f"[agent] {len(result.predictions)} test predictions", flush=True)

    pred_path = args.out_dir / "diagnosis-agent-predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as fh:
        for p in result.predictions:
            fh.write(json.dumps(p.as_dict(), default=str, ensure_ascii=False) + "\n")
    print(f"[agent] wrote predictions to {pred_path}", flush=True)

    strong_path = args.global_dir / "window-memory-matchings-strong.jsonl"
    strong_gold = {}
    if strong_path.exists():
        for line in strong_path.open(encoding="utf-8"):
            d = json.loads(line)
            strong_gold[d["window_id"]] = set(d.get("matched_memory_issue_ids") or [])
    print(f"[agent] loaded strong-match gold for {len(strong_gold)} windows", flush=True)

    def metrics(predictions, gold_lookup, label):
        h1 = h5 = n = 0
        mrr_sum = 0.0
        per_proj_stats = defaultdict(lambda: {"n": 0, "h1": 0, "h5": 0, "mrr_sum": 0.0})
        ds = load_dataset(args.global_dir)
        proj_by_wid = {w.window_id: getattr(w, "scenario_family", "?") for w in ds.windows}

        for p in predictions:
            wid = p.window_id
            gold = set(p.gold_matched_issue_ids or []) if gold_lookup is None else gold_lookup.get(wid, set())
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
                for proj, v in per_proj_stats.items()
            },
        }

    coarse_m = metrics(result.predictions, None,        "coarse")
    strong_m = metrics(result.predictions, strong_gold, "strong")

    results = {
        "config": {
            "global_dir":     str(args.global_dir),
            "humanized_root": args.humanized_root,
            "humanized_subdir": args.humanized_subdir,
            "model":          args.model,
            "subsample_size": args.subsample_size,
            "top_k_input":    args.top_k_input,
            "top_k_output":   args.top_k_output,
            "hybrid_predictions_path": str(hybrid_preds),
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

    out_path = args.out_dir / "diagnosis-agent-mode3-results.json"
    out_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"[agent] wrote results to {out_path}\n", flush=True)

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
