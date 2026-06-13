"""RQ-B6 — cascade composition on WoL real data.

Reads the 5 cached WoL Mode 3 retriever JSONLs (`tch-lite-refit/`) and
fuses them via the agent's compose_l2 math:
  - BiEncoder-anchored overlap rerank at position 1
  - RRF (k=60) over the L2 retriever set for positions 2-5

Reports per-retriever Hit@K with CIs (the RQ-A6 numbers, repeated for
context) + the fused cascade Hit@K + a paired delta against the best
single retriever. Closes the "is multi-retriever fusion better than
the best one on real Apache Jira?" question.

The fusion math is the SAME as `agent.skills.composition.ComposeL2Skill`.
Predictions are pre-computed (no inference), so this is pure analysis
— a few seconds on 450 windows.

Usage:
    PYTHONPATH=src python scripts/agent/wol_cascade_compose.py \\
        --global-dir data/derived/global/2026-06-11-wol-real-global \\
        --output data/agent_runs/wol-cascade-composition.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.eval_harness import (
    DEFAULT_CONFIDENCE,
    DEFAULT_N_RESAMPLES,
    DEFAULT_SEED,
    bootstrap_metric,
    metric_hit_at_1,
    metric_hit_at_5,
    metric_mrr,
    paired_bootstrap_delta,
    rows_from_dicts,
)


# Constants matching ComposeL2Skill
RRF_K = 60.0
TOP_K = 5
ANCHOR_POOL_SIZE = 3
VOTER_TOP_K = 3


def _load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logging.warning("skipping malformed line in %s", path)
    return out


def _index_by_window(rows: list[dict]) -> dict[str, dict]:
    return {r["window_id"]: r for r in rows if "window_id" in r}


def _pick_position_1(
    anchor_ranking: list[str],
    voter_rankings: list[list[str]],
) -> str | None:
    """BiEncoder-anchored overlap rerank — ports ComposeL2Skill logic."""
    if not anchor_ranking:
        return None
    anchor_pool = anchor_ranking[:ANCHOR_POOL_SIZE]
    if not voter_rankings:
        return anchor_pool[0]
    scored: list[tuple[str, float, int]] = []
    for anchor_rank, c in enumerate(anchor_pool):
        score = 0.0
        for voter_list in voter_rankings:
            top_voters = voter_list[:VOTER_TOP_K]
            if c in top_voters:
                rank_in_voter = top_voters.index(c)
                score += VOTER_TOP_K - rank_in_voter
        scored.append((c, score, anchor_rank))
    scored.sort(key=lambda t: (-t[1], t[2]))
    best_c, best_score, _ = scored[0]
    if best_score == 0:
        return anchor_pool[0]
    return best_c


def _rrf_fuse(retriever_rankings: dict[str, list[str]]) -> list[str]:
    """Reciprocal Rank Fusion across the L2 retriever set."""
    scores: dict[str, float] = {}
    for ranking in retriever_rankings.values():
        for rank_idx, c in enumerate(ranking[:10], start=1):
            scores[c] = scores.get(c, 0.0) + 1.0 / (RRF_K + rank_idx)
    return sorted(scores, key=lambda c: -scores[c])


def compose_l2_window(
    *,
    biencoder_ranking: list[str],
    other_rankings: dict[str, list[str]],
) -> list[str]:
    """Top-5 composed ranking for one window."""
    # Position 1: anchored overlap rerank
    voter_rankings = [
        r for name, r in other_rankings.items()
        if name != "bi_encoder_retrieval"
    ]
    position_1 = _pick_position_1(biencoder_ranking, voter_rankings)
    # Positions 2-5 via RRF (excluding the position-1 anchor)
    all_rankings = dict(other_rankings)
    all_rankings["bi_encoder_retrieval"] = biencoder_ranking
    rrf_ranking = _rrf_fuse(all_rankings)
    rest = [c for c in rrf_ranking if c != position_1][: TOP_K - 1]
    final = []
    if position_1:
        final.append(position_1)
    final.extend(rest)
    return final[:TOP_K]


def build_composed_predictions(
    retriever_predictions: dict[str, list[dict]],
    *,
    l2_set: list[str],
) -> list[dict]:
    """For each window present in all of `l2_set`'s predictions, compose
    a top-5 ranking + a synthetic 'composed' prediction row.

    `l2_set` is the list of pipeline names to fuse. BiEncoder must be
    included (it's the anchor)."""
    if "bi_encoder_retrieval" not in l2_set:
        raise ValueError("compose_l2 requires bi_encoder_retrieval in the L2 set")
    indexed: dict[str, dict[str, dict]] = {
        name: _index_by_window(retriever_predictions[name])
        for name in l2_set
    }
    common = sorted(set.intersection(*(set(i) for i in indexed.values())))
    out = []
    for wid in common:
        biencoder_row = indexed["bi_encoder_retrieval"][wid]
        other_rankings = {
            name: indexed[name][wid].get("matched_issue_ids") or []
            for name in l2_set if name != "bi_encoder_retrieval"
        }
        composed_top = compose_l2_window(
            biencoder_ranking=biencoder_row.get("matched_issue_ids") or [],
            other_rankings=other_rankings,
        )
        # Use BiEncoder's gold as the canonical (gold is per-window)
        out.append({
            "window_id": wid,
            "pipeline_name": "composed_l2",
            "matched_issue_ids": composed_top,
            "gold_matched_issue_ids": biencoder_row.get("gold_matched_issue_ids") or [],
            "gold_is_novel": biencoder_row.get("gold_is_novel", False),
            "wol_project": biencoder_row.get("wol_project"),
            "scenario_family": biencoder_row.get("scenario_family"),
        })
    return out


def _bootstrap_rows(rows: list[dict], *, label: str,
                    n_resamples: int, seed: int, confidence: float) -> dict:
    bs_rows = rows_from_dicts(rows)
    out: dict = {"label": label, "n_rows": len(rows), "metrics": {}}
    for m_name, m_fn in (("hit_at_1", metric_hit_at_1),
                          ("hit_at_5", metric_hit_at_5),
                          ("mrr", metric_mrr)):
        bs = bootstrap_metric(
            bs_rows, m_fn, metric_name=m_name,
            n_resamples=n_resamples, seed=seed, confidence=confidence,
        )
        out["metrics"][m_name] = bs.to_dict()
    return out


def _paired_delta(
    a_rows: list[dict], b_rows: list[dict],
    *, a_label: str, b_label: str,
    n_resamples: int, seed: int, confidence: float,
) -> dict:
    a_by = _index_by_window(a_rows)
    b_by = _index_by_window(b_rows)
    common = sorted(set(a_by) & set(b_by))
    a_aligned = rows_from_dicts(a_by[w] for w in common)
    b_aligned = rows_from_dicts(b_by[w] for w in common)
    out = {
        "a_label": a_label, "b_label": b_label,
        "n_common": len(common), "deltas": {},
    }
    for m_name, m_fn in (("hit_at_1", metric_hit_at_1),
                          ("hit_at_5", metric_hit_at_5),
                          ("mrr", metric_mrr)):
        pbr = paired_bootstrap_delta(
            a_aligned, b_aligned, m_fn,
            metric_name=m_name, a_label=a_label, b_label=b_label,
            n_resamples=n_resamples, seed=seed, confidence=confidence,
        )
        out["deltas"][m_name] = pbr.to_dict()
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True,
                   help="WoL dataset root")
    p.add_argument("--retrievers", nargs="+",
                   default=["bi_encoder_retrieval",
                            "hybrid_rrf_retrieval",
                            "logseq2vec_retrieval",
                            "kg_retrieval"],
                   help="L2 retriever pipeline_names to fuse")
    p.add_argument("--n-resamples", type=int, default=DEFAULT_N_RESAMPLES)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    file_map = {
        "bi_encoder_retrieval": "biencoder-predictions.jsonl",
        "hybrid_rrf_retrieval": "hybrid-rrf-predictions.jsonl",
        "logseq2vec_retrieval": "logseq2vec-predictions.jsonl",
        "kg_retrieval":         "kg-retrieval-predictions.jsonl",
        "diagnosis_agent":      "diagnosis-agent-predictions.jsonl",
    }

    tch_dir = args.global_dir / "tch-lite-refit"
    retriever_preds: dict[str, list[dict]] = {}
    for name in args.retrievers:
        if name not in file_map:
            raise SystemExit(f"unknown retriever {name!r}; known: {sorted(file_map)}")
        path = tch_dir / file_map[name]
        if not path.exists():
            raise SystemExit(f"missing {path}")
        retriever_preds[name] = _load_jsonl(path)
        print(f"[wol_compose] loaded {len(retriever_preds[name])} rows for {name}")

    # Build composed predictions
    composed = build_composed_predictions(
        retriever_preds, l2_set=args.retrievers,
    )
    print(f"[wol_compose] composed {len(composed)} windows")

    # Per-retriever + composed bootstrap
    print()
    print("=" * 86)
    print(f"  WoL cascade composition (RQ-B6)")
    print(f"  n_resamples={args.n_resamples} seed={args.seed}")
    print("=" * 86)
    print(f"  {'pipeline':<22} {'Hit@1':>22} {'Hit@5':>22} {'MRR':>22}")
    print("  " + "-" * 84)

    report: dict = {"per_pipeline": {}, "paired_vs_best": {}}

    rows_by_label: dict[str, list[dict]] = {}
    for name in args.retrievers:
        bs = _bootstrap_rows(
            retriever_preds[name], label=name,
            n_resamples=args.n_resamples, seed=args.seed,
            confidence=args.confidence,
        )
        report["per_pipeline"][name] = bs
        rows_by_label[name] = retriever_preds[name]
        m = bs["metrics"]
        print(f"  {name:<22} "
              f"{m['hit_at_1']['point_estimate']:>6.4f} [{m['hit_at_1']['ci_low']:>5.3f},{m['hit_at_1']['ci_high']:>5.3f}] "
              f"{m['hit_at_5']['point_estimate']:>6.4f} [{m['hit_at_5']['ci_low']:>5.3f},{m['hit_at_5']['ci_high']:>5.3f}] "
              f"{m['mrr']['point_estimate']:>6.4f} [{m['mrr']['ci_low']:>5.3f},{m['mrr']['ci_high']:>5.3f}]")

    # Composed
    bs_composed = _bootstrap_rows(
        composed, label="composed_l2",
        n_resamples=args.n_resamples, seed=args.seed,
        confidence=args.confidence,
    )
    report["per_pipeline"]["composed_l2"] = bs_composed
    rows_by_label["composed_l2"] = composed
    m = bs_composed["metrics"]
    print(f"  {'composed_l2':<22} "
          f"{m['hit_at_1']['point_estimate']:>6.4f} [{m['hit_at_1']['ci_low']:>5.3f},{m['hit_at_1']['ci_high']:>5.3f}] "
          f"{m['hit_at_5']['point_estimate']:>6.4f} [{m['hit_at_5']['ci_low']:>5.3f},{m['hit_at_5']['ci_high']:>5.3f}] "
          f"{m['mrr']['point_estimate']:>6.4f} [{m['mrr']['ci_low']:>5.3f},{m['mrr']['ci_high']:>5.3f}]")

    # Paired delta: composed vs best single retriever (by Hit@5 point estimate)
    best_single = max(
        args.retrievers,
        key=lambda n: report["per_pipeline"][n]["metrics"]["hit_at_5"]["point_estimate"],
    )
    print()
    print(f"  Best single retriever (by Hit@5): {best_single}")
    print()
    paired = _paired_delta(
        rows_by_label[best_single], composed,
        a_label=best_single, b_label="composed_l2",
        n_resamples=args.n_resamples, seed=args.seed,
        confidence=args.confidence,
    )
    report["paired_vs_best"] = paired

    print(f"  Paired: composed_l2 vs {best_single}  (n_common={paired['n_common']})")
    print(f"    {'metric':<10} {'delta':>9}  {'95% delta-CI':>22} {'fraction_better':>16}")
    print("    " + "-" * 60)
    for m_name, d in paired["deltas"].items():
        sig = "*" if (d["delta_ci_low"] > 0 or d["delta_ci_high"] < 0) else " "
        print(f"    {m_name:<10} "
              f"{d['delta_point']:>+9.4f}  "
              f"[{d['delta_ci_low']:>+7.4f}, {d['delta_ci_high']:>+7.4f}] "
              f"{sig}  {d['fraction_b_better']:>14.3f}")
    print("    (* = 95% CI excludes zero)")
    print("=" * 86)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str),
                                encoding="utf-8")
        print(f"\n[wol_compose] wrote -> {args.output}")


if __name__ == "__main__":
    main()
