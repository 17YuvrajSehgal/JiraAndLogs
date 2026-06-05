"""Bootstrap CIs + per-stratum breakdown for the TCH cascade headline numbers.

Reads `v2f-tch-phase1/per-window-predictions.jsonl` and computes:
  - Headline (Hit@1, Hit@5, MRR) with 95% CIs via 1000-resample paired bootstrap
  - Per-family Hit@5 to identify wins / losses by scenario family
  - Per-window-type Hit@5 (active_fault, observation_window, pre_fault_baseline, recovery_window)
  - is_hard_case stratification
  - n_prior_family_tickets depth-curve (Sub-claim 1 of the RESEARCH-CHARTER)
  - Failure analysis: windows where TCH MISSES top-5 — sample 10 for review

Compares TCH vs the per-baseline predictions on the same windows so the
CIs are paired (resample the same window indices for both).

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.analyze_cascade \\
        --cascade-dir data/derived/global/.../v2f-tch-phase1 \\
        --comparison-base data/derived/global/.../comparison
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


PIPELINE_FILES = {
    "TCH":               "v2f-tch-phase1/per-window-predictions.jsonl",
    "bi_encoder":        "v2a-resplit/per-window-predictions.jsonl",
    "hybrid_rrf_rule":   "v2c-hybrid/per-window-predictions.jsonl",
    "hybrid_rrf_llm":    "v2c-hybrid-llm/per-window-predictions.jsonl",
    "logseq2vec":        "v2b-logseq2vec/per-window-predictions.jsonl",
}
TARGET_PIPE = {
    "TCH":             "tch_cascade",
    "bi_encoder":      "bi_encoder_retrieval",
    "hybrid_rrf_rule": "hybrid_rrf_retrieval",
    "hybrid_rrf_llm":  "hybrid_rrf_retrieval",
    "logseq2vec":      "logseq2vec_retrieval_pretrained",
}


def hit_at_k_per_window(top: list[str], gold: set[str], k: int) -> int:
    return 1 if any(c in gold for c in top[:k]) else 0


def rank_in(top: list[str], gold: set[str]) -> int | None:
    for i, c in enumerate(top, 1):
        if c in gold:
            return i
    return None


def per_window_metrics(predictions: list[dict]) -> dict[str, list]:
    """Return per-window {hit@1, hit@5, reciprocal-rank} arrays for windows
    that have gold. NaN for windows without gold so we can mask later."""
    h1, h5, rr = [], [], []
    has_gold = []
    for p in predictions:
        gold = set(p.get("gold_matched_issue_ids") or [])
        has_gold.append(bool(gold))
        if not gold:
            h1.append(0); h5.append(0); rr.append(0.0)
            continue
        top = p.get("matched_issue_ids") or []
        h1.append(hit_at_k_per_window(top, gold, 1))
        h5.append(hit_at_k_per_window(top, gold, 5))
        r = rank_in(top, gold)
        rr.append(1.0 / r if r is not None else 0.0)
    return {"h1": np.asarray(h1), "h5": np.asarray(h5), "rr": np.asarray(rr),
            "has_gold": np.asarray(has_gold)}


def bootstrap_ci(per_pipe_metrics: dict[str, dict], n_resamples: int = 1000,
                 seed: int = 42) -> dict[str, dict]:
    """1000-resample paired bootstrap CIs. Resample indices once per
    iteration; apply to every pipeline so comparisons are paired."""
    rng = np.random.default_rng(seed)
    # All pipelines must have same number of windows
    pipe_names = list(per_pipe_metrics.keys())
    n = len(per_pipe_metrics[pipe_names[0]]["h1"])
    has_gold = per_pipe_metrics[pipe_names[0]]["has_gold"]
    gold_idx = np.where(has_gold)[0]

    out = {name: {"h1": [], "h5": [], "rr": []} for name in pipe_names}
    for _ in range(n_resamples):
        sampled = rng.choice(gold_idx, size=len(gold_idx), replace=True)
        for name, m in per_pipe_metrics.items():
            out[name]["h1"].append(float(m["h1"][sampled].mean()))
            out[name]["h5"].append(float(m["h5"][sampled].mean()))
            out[name]["rr"].append(float(m["rr"][sampled].mean()))

    ci = {}
    for name in pipe_names:
        ci[name] = {}
        for metric in ("h1", "h5", "rr"):
            vals = np.asarray(out[name][metric])
            ci[name][metric] = {
                "mean": float(vals.mean()),
                "ci_low": float(np.percentile(vals, 2.5)),
                "ci_high": float(np.percentile(vals, 97.5)),
            }
    return ci


def paired_delta_ci(per_pipe_metrics: dict[str, dict],
                    pipe_a: str, pipe_b: str,
                    n_resamples: int = 1000, seed: int = 42) -> dict[str, dict]:
    """Per-metric paired delta: TCH - baseline. CI of the difference."""
    rng = np.random.default_rng(seed)
    n = len(per_pipe_metrics[pipe_a]["h1"])
    has_gold = per_pipe_metrics[pipe_a]["has_gold"]
    gold_idx = np.where(has_gold)[0]

    deltas = {"h1": [], "h5": [], "rr": []}
    for _ in range(n_resamples):
        sampled = rng.choice(gold_idx, size=len(gold_idx), replace=True)
        for metric in ("h1", "h5", "rr"):
            a = per_pipe_metrics[pipe_a][metric][sampled].mean()
            b = per_pipe_metrics[pipe_b][metric][sampled].mean()
            deltas[metric].append(float(a - b))

    out = {}
    for metric in ("h1", "h5", "rr"):
        vals = np.asarray(deltas[metric])
        out[metric] = {
            "mean_delta": float(vals.mean()),
            "ci_low": float(np.percentile(vals, 2.5)),
            "ci_high": float(np.percentile(vals, 97.5)),
            "fraction_positive": float((vals > 0).mean()),
        }
    return out


def stratify_hit5(predictions: list[dict], key_fn) -> dict[str, tuple[int, float]]:
    """Group predictions by key_fn(p) and compute Hit@5 per stratum."""
    buckets: dict[str, list[int]] = defaultdict(list)
    for p in predictions:
        gold = set(p.get("gold_matched_issue_ids") or [])
        if not gold:
            continue
        key = key_fn(p)
        if key is None:
            continue
        top = p.get("matched_issue_ids") or []
        buckets[str(key)].append(hit_at_k_per_window(top, gold, 5))
    out = {}
    for k, vals in buckets.items():
        out[k] = (len(vals), float(np.mean(vals)) if vals else 0.0)
    return out


def n_prior_bucket(n: int | None) -> str | None:
    if n is None:
        return None
    if n == 0: return "n_prior=0"
    if n <= 2: return "n_prior=1-2"
    if n <= 5: return "n_prior=3-5"
    if n <= 20: return "n_prior=6-20"
    return "n_prior=21+"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cascade-dir", type=Path, required=True)
    ap.add_argument("--comparison-base", type=Path, required=True)
    args = ap.parse_args()

    # Load each pipeline's predictions, keyed by window_id
    per_pipe: dict[str, dict[str, dict]] = {}
    for name, rel_path in PIPELINE_FILES.items():
        path = (args.cascade_dir.parent / rel_path
                if name == "TCH" else args.comparison_base / rel_path)
        target = TARGET_PIPE[name]
        windows: dict[str, dict] = {}
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                if d.get("pipeline_name") == target:
                    windows[d["window_id"]] = d
        per_pipe[name] = windows
        print(f"  loaded {name:20s}  n={len(windows):4d}  from {rel_path}")

    # Intersect on common window_ids (should be 1008)
    common = set.intersection(*[set(w.keys()) for w in per_pipe.values()])
    print(f"\ncommon windows across all pipelines: {len(common)}")
    common_sorted = sorted(common)

    # Build aligned prediction arrays
    aligned: dict[str, list[dict]] = {}
    for name in per_pipe:
        aligned[name] = [per_pipe[name][wid] for wid in common_sorted]

    # Per-window metric arrays
    per_pipe_metrics = {name: per_window_metrics(aligned[name]) for name in per_pipe}

    # Headline + CIs
    print("\n=== Headline with 95% bootstrap CIs (1000 resamples, paired) ===")
    ci = bootstrap_ci(per_pipe_metrics)
    print(f"{'pipeline':22s}  {'Hit@1 [95% CI]':24s}  {'Hit@5 [95% CI]':24s}  {'MRR [95% CI]':24s}")
    for name in ["TCH", "bi_encoder", "hybrid_rrf_rule", "hybrid_rrf_llm", "logseq2vec"]:
        c = ci[name]
        print(f"{name:22s}  "
              f"{c['h1']['mean']:.3f} [{c['h1']['ci_low']:.3f},{c['h1']['ci_high']:.3f}]  "
              f"{c['h5']['mean']:.3f} [{c['h5']['ci_low']:.3f},{c['h5']['ci_high']:.3f}]  "
              f"{c['rr']['mean']:.3f} [{c['rr']['ci_low']:.3f},{c['rr']['ci_high']:.3f}]")

    # Pairwise deltas: TCH vs each
    print("\n=== TCH minus baseline (paired delta, 95% bootstrap CI) ===")
    print(f"{'baseline':22s}  {'Hit@1 delta':22s}  {'Hit@5 delta':22s}  {'MRR delta':22s}")
    for name in ["bi_encoder", "hybrid_rrf_rule", "hybrid_rrf_llm", "logseq2vec"]:
        d = paired_delta_ci(per_pipe_metrics, "TCH", name)
        print(f"{name:22s}  "
              f"{d['h1']['mean_delta']:+.3f} [{d['h1']['ci_low']:+.3f},{d['h1']['ci_high']:+.3f}]  "
              f"{d['h5']['mean_delta']:+.3f} [{d['h5']['ci_low']:+.3f},{d['h5']['ci_high']:+.3f}]  "
              f"{d['rr']['mean_delta']:+.3f} [{d['rr']['ci_low']:+.3f},{d['rr']['ci_high']:+.3f}]")

    # Per-family Hit@5
    print("\n=== Per-family Hit@5 (TCH vs bi_encoder, n=windows-with-gold) ===")
    tch_p = aligned["TCH"]
    be_p = aligned["bi_encoder"]
    tch_fam = stratify_hit5(tch_p, lambda p: p.get("scenario_family"))
    be_fam = stratify_hit5(be_p, lambda p: p.get("scenario_family"))
    all_fams = sorted(set(tch_fam) | set(be_fam))
    print(f"{'family':40s}  {'n':>4s}  {'TCH':>6s}  {'bi_enc':>7s}  {'delta':>7s}")
    for fam in all_fams:
        n_tch, h_tch = tch_fam.get(fam, (0, 0))
        n_be,  h_be  = be_fam.get(fam,  (0, 0))
        if max(n_tch, n_be) < 3:
            continue
        print(f"{fam:40s}  {max(n_tch, n_be):4d}  {h_tch:6.3f}  {h_be:7.3f}  {h_tch - h_be:+7.3f}")

    # Per-window-type
    print("\n=== Per-window-type Hit@5 ===")
    tch_wt = stratify_hit5(tch_p, lambda p: p.get("window_type"))
    be_wt = stratify_hit5(be_p, lambda p: p.get("window_type"))
    for wt in sorted(set(tch_wt) | set(be_wt)):
        n_tch, h_tch = tch_wt.get(wt, (0, 0))
        n_be, h_be = be_wt.get(wt, (0, 0))
        print(f"  {wt:30s}  n={max(n_tch,n_be):4d}  TCH={h_tch:.3f}  bi_enc={h_be:.3f}  delta={h_tch-h_be:+.3f}")

    # is_hard_case
    print("\n=== Hit@5 by is_hard_case ===")
    tch_hc = stratify_hit5(tch_p, lambda p: "hard" if p.get("is_hard_case") else "easy")
    be_hc = stratify_hit5(be_p, lambda p: "hard" if p.get("is_hard_case") else "easy")
    for hc in ("easy", "hard"):
        n_tch, h_tch = tch_hc.get(hc, (0, 0))
        n_be, h_be = be_hc.get(hc, (0, 0))
        print(f"  is_hard_case={hc:5s}  n={max(n_tch,n_be):4d}  TCH={h_tch:.3f}  bi_enc={h_be:.3f}  delta={h_tch-h_be:+.3f}")

    # n_prior_family depth curve (Sub-claim 1)
    print("\n=== Depth curve: Hit@5 by n_prior_family_tickets ===")
    tch_d = stratify_hit5(tch_p, lambda p: n_prior_bucket(p.get("n_prior_family_tickets")))
    be_d = stratify_hit5(be_p, lambda p: n_prior_bucket(p.get("n_prior_family_tickets")))
    order = ["n_prior=0", "n_prior=1-2", "n_prior=3-5", "n_prior=6-20", "n_prior=21+"]
    for bucket in order:
        n_tch, h_tch = tch_d.get(bucket, (0, 0))
        n_be, h_be = be_d.get(bucket, (0, 0))
        print(f"  {bucket:18s}  n={max(n_tch,n_be):4d}  TCH={h_tch:.3f}  bi_enc={h_be:.3f}  delta={h_tch-h_be:+.3f}")

    # Failure analysis: windows where TCH misses top-5
    print("\n=== Failure analysis: TCH misses Hit@5 (sample 10) ===")
    misses = []
    for p in tch_p:
        gold = set(p.get("gold_matched_issue_ids") or [])
        if not gold:
            continue
        top = p.get("matched_issue_ids") or []
        if not any(c in gold for c in top[:5]):
            misses.append(p)
    print(f"Total TCH Hit@5 misses on windows with gold: {len(misses)}")
    for i, p in enumerate(misses[:10]):
        print(f"  [{i+1}] wid={p['window_id'][-60:]}")
        print(f"      family={p.get('scenario_family')}  type={p.get('window_type')}  hard={p.get('is_hard_case')}")
        print(f"      n_prior={p.get('n_prior_family_tickets')}  triage_score={p.get('triage_score'):.3f}")
        print(f"      gold_first_3={list(p.get('gold_matched_issue_ids', []))[:3]}")
        print(f"      top_3={p.get('matched_issue_ids', [])[:3]}")


if __name__ == "__main__":
    main()
