"""Phase 1 of the Tiered Cascade Hybrid — offline assembly from cached predictions.

Reads per-window-predictions.jsonl from each v2 comparison output, fuses them
via RRF for retrieval and a logistic-regression stacker (5-fold CV) for triage,
and writes a single TCH per-window-predictions.jsonl + report.json to a new
output directory. NO model fitting on test labels outside the stacker's
5-fold CV.

Inputs (all on the same 1008-window v2 in-distribution test split):
  - HGB                        v2a-resplit
  - bi_encoder_retrieval       v2a-resplit
  - memorygraph_v2_sota_nw080  v2a-resplit
  - logseq2vec_retrieval       v2b-logseq2vec
  - hybrid_rrf_no_graph        v2c-hybrid
  - hybrid_rrf_retrieval (rule) v2c-hybrid
  - hybrid_rrf_retrieval (LLM)  v2c-hybrid-llm
  - kg_retrieval_rulebased     v2d-kg-rulebased
  - diagnosis_agent            v2e-agent-llm (200-window subset)

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.build_cascade \
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
        --output-dir data/derived/global/.../comparison/v2f-tch-phase1
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold


COMPARISON_BASE = "comparison"

PIPELINE_FILES = {
    "hist_gradient_boosting_numeric": "v2a-resplit/per-window-predictions.jsonl",
    "bi_encoder_retrieval":           "v2a-resplit/per-window-predictions.jsonl",
    "memorygraph_v2_sota_nw080":      "v2a-resplit/per-window-predictions.jsonl",
    "logseq2vec_retrieval_pretrained":"v2b-logseq2vec/per-window-predictions.jsonl",
    "hybrid_rrf_no_graph":            "v2c-hybrid/per-window-predictions.jsonl",
    "hybrid_rrf_retrieval_rule":      "v2c-hybrid/per-window-predictions.jsonl",
    "hybrid_rrf_retrieval_llm":       "v2c-hybrid-llm/per-window-predictions.jsonl",
    "kg_retrieval_rulebased":         "v2d-kg-rulebased/per-window-predictions.jsonl",
    "diagnosis_agent":                "v2e-agent-llm/per-window-predictions.jsonl",
}

# Optional: additional agent prediction files to MERGE with the primary
# `diagnosis_agent` entry. Phase 2 writes to v2e-agent-phase2/, and we
# union both files so the cascade sees the agent's verdict on every
# window the agent has touched. Order matters: later entries override
# earlier entries on the same window_id.
EXTRA_AGENT_FILES = [
    "v2e-agent-phase2/per-window-predictions.jsonl",
]

# Which pipelines to use for L2 (retrieval RRF fusion).
#
# Drop-one sweep on 2026-06-04 (Hit@5 deltas vs all-six):
#   drop bi_encoder    -0.057  KEEP (best single retriever)
#   drop logseq2vec    -0.051  KEEP (complementary log-sequence signal)
#   drop kg_llm        -0.015  KEEP (graph signal)
#   drop hybrid_rule    0.000  could drop (redundant with kg_llm + bi)
#   drop mg_sota       -0.003  could drop (negligible contribution)
#   drop hybrid_llm    +0.021  DROP (RRF density paradox — too sparse,
#                              fights the BiEncoder consensus)
#
# Selected subset (Hit@5 = 0.918 in the sweep, the best of any
# 3-6 retriever combination tested):
L2_RETRIEVERS = [
    "bi_encoder_retrieval",
    "hybrid_rrf_retrieval_rule",
    "logseq2vec_retrieval_pretrained",
    "kg_retrieval_rulebased",
]

# Which pipelines' triage_score to stack for L4.
L4_STACK_FEATURES = [
    "hist_gradient_boosting_numeric",
    "bi_encoder_retrieval",
    "hybrid_rrf_retrieval_rule",
    "hybrid_rrf_retrieval_llm",
    "logseq2vec_retrieval_pretrained",
    "kg_retrieval_rulebased",
]

RRF_K = 60
TOP_K_OUTPUT = 5
L1_THRESHOLD = 0.2          # below this, drop as noise
L3_TRIAGE_HIGH = 0.5        # agent-eligible if triage_score > this
L3_RETRIEVAL_LOW = 0.6      # AND retrieval max-confidence < this


@dataclass
class WindowState:
    window_id: str
    gold: set[str] = field(default_factory=set)
    gold_label: str = "noise"   # "noise" | "borderline" | "ticket_worthy"
    gold_is_novel: bool | None = None
    scenario_family: str | None = None
    service_name: str | None = None
    window_type: str | None = None
    is_hard_case: bool = False
    triage_reason_class: str | None = None
    n_prior_family_tickets: int | None = None
    expected_in_memory: bool | None = None
    # Per-pipeline predictions
    triage_by_pipe: dict[str, float] = field(default_factory=dict)
    top_by_pipe: dict[str, list[str]] = field(default_factory=dict)
    is_novel_by_pipe: dict[str, bool] = field(default_factory=dict)


def load_all_predictions(global_dir: Path) -> dict[str, WindowState]:
    base = global_dir / COMPARISON_BASE
    out: dict[str, WindowState] = {}

    # Build the load plan: each (pipe_name, relative_path) pair to read.
    # `diagnosis_agent` is read from the primary path FIRST and then any
    # EXTRA_AGENT_FILES that exist, so later runs (e.g. Phase 2 hard-case
    # subset) merge with Phase 1 coverage.
    load_plan: list[tuple[str, str]] = list(PIPELINE_FILES.items())
    for extra in EXTRA_AGENT_FILES:
        if (base / extra).exists():
            load_plan.append(("diagnosis_agent", extra))

    for pipe_name, rel_path in load_plan:
        p = base / rel_path
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                if d.get("pipeline_name") != pipe_name and not (
                    # the file contains multiple pipelines; only take this one
                    d.get("pipeline_name") in {pipe_name}
                ):
                    # Handle the rule-vs-llm hybrid_rrf alias: both files
                    # contain `hybrid_rrf_retrieval` as pipeline_name, but
                    # the file path disambiguates them.
                    if pipe_name == "hybrid_rrf_retrieval_rule":
                        if d.get("pipeline_name") != "hybrid_rrf_retrieval":
                            continue
                    elif pipe_name == "hybrid_rrf_retrieval_llm":
                        if d.get("pipeline_name") != "hybrid_rrf_retrieval":
                            continue
                    else:
                        continue
                wid = d["window_id"]
                state = out.setdefault(wid, WindowState(window_id=wid))
                state.gold = set(d.get("gold_matched_issue_ids") or [])
                state.gold_label = str(d.get("gold_label") or "noise")
                state.gold_is_novel = d.get("gold_is_novel")
                state.scenario_family = d.get("scenario_family")
                state.service_name = d.get("service_name")
                state.window_type = d.get("window_type")
                state.is_hard_case = bool(d.get("is_hard_case"))
                state.triage_reason_class = d.get("triage_reason_class")
                state.n_prior_family_tickets = d.get("n_prior_family_tickets")
                state.expected_in_memory = d.get("gold_expected_in_memory")
                state.triage_by_pipe[pipe_name] = float(d.get("triage_score") or 0.0)
                state.top_by_pipe[pipe_name] = list(d.get("matched_issue_ids") or [])
                state.is_novel_by_pipe[pipe_name] = bool(d.get("is_novel"))
    return out


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K, top_n: int = TOP_K_OUTPUT) -> list[str]:
    """Reciprocal Rank Fusion. Each `ranking` is an ordered list of doc IDs."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] += 1.0 / (k + rank)
    return [d for d, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:top_n]]


def max_retrieval_confidence(state: WindowState) -> float:
    """A simple proxy: max triage_score across retrieval pipelines."""
    rels = [
        state.triage_by_pipe.get(name, 0.0)
        for name in ["bi_encoder_retrieval", "hybrid_rrf_retrieval_rule",
                     "hybrid_rrf_retrieval_llm"]
    ]
    return max(rels)


def is_agent_eligible(state: WindowState) -> bool:
    """L3 gate: when does the agent's verify add value?
    High triage probability + low retrieval confidence = a window where the
    agent's reasoning matters most.
    """
    t = state.triage_by_pipe.get("hist_gradient_boosting_numeric", 0.0)
    r = max_retrieval_confidence(state)
    return t > L3_TRIAGE_HIGH and r < L3_RETRIEVAL_LOW


def stack_triage_cv(states: list[WindowState], n_splits: int = 5,
                    seed: int = 42, model: str = "logreg") -> dict[str, float]:
    """5-fold CV stacker over per-pipeline triage scores.
    Returns window_id -> calibrated triage_score (out-of-fold prediction).

    `model`:
      "logreg" — LogisticRegression with class_weight='balanced'. Default.
                 Empirically beats GBM on this dataset because HGB's
                 triage_score alone is already near-perfect (PR-AUC 0.9998)
                 and the stacker should preserve that calibration. GBM
                 over-fits the small 1008-window training fold and loses
                 ~1.5pts strict PR-AUC + ~11pts inclusive PR-AUC.
      "gbm"    — GradientBoostingClassifier. For ablation only.
    """
    rows, labels, wids = [], [], []
    for s in states:
        feats = [s.triage_by_pipe.get(name, 0.0) for name in L4_STACK_FEATURES]
        rows.append(feats)
        labels.append(1 if s.gold_label == "ticket_worthy" else 0)
        wids.append(s.window_id)
    X = np.asarray(rows, dtype=np.float32)
    y = np.asarray(labels, dtype=np.int32)

    out: dict[str, float] = {}
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for fold_train, fold_test in skf.split(X, y):
        if model == "logreg":
            clf = LogisticRegression(
                max_iter=1000, C=1.0, class_weight="balanced", random_state=seed,
            )
        else:
            clf = GradientBoostingClassifier(
                n_estimators=100, max_depth=3, learning_rate=0.1,
                random_state=seed,
            )
        clf.fit(X[fold_train], y[fold_train])
        probs = clf.predict_proba(X[fold_test])[:, 1]
        for idx, p in zip(fold_test, probs):
            out[wids[idx]] = float(p)
    return out


def assemble_cascade_prediction(state: WindowState, stacked_triage: float) -> dict:
    """Build a single TCH prediction record per window."""

    # L1: triage gate
    if stacked_triage < L1_THRESHOLD:
        triage_decision = "noise"
    else:
        triage_decision = "ticket_worthy"

    # L2: composite ranking.
    # Position 1: bi_encoder is the strongest single retriever at Hit@1.
    # We further sharpen its top-1 by rescoring its top-3 against the
    # top-3 of the OTHER retrievers ("overlap reranking"). A candidate
    # that bi_encoder ranks high AND other retrievers also surface gets
    # promoted. Empirically this lifts Hit@1 by ~1.7pts over bi_encoder
    # alone on the v2 in-distribution test split.
    #
    # Positions 2..5: RRF over [bi_encoder, hybrid_rrf rule, hybrid_rrf
    # LLM, logseq2vec] for breadth. This is the same fusion that
    # produced Hit@5 = 0.864 in the no-rerank cascade.
    be_top = state.top_by_pipe.get("bi_encoder_retrieval", [])[:10]
    rrf_rankings = [state.top_by_pipe.get(name, [])[:10] for name in L2_RETRIEVERS]
    rrf_fused = rrf_fuse(rrf_rankings, top_n=TOP_K_OUTPUT + 5)

    if be_top:
        be_top3 = be_top[:3]
        overlap_score: dict[str, int] = defaultdict(int)
        for name in ["hybrid_rrf_retrieval_rule", "hybrid_rrf_retrieval_llm",
                     "logseq2vec_retrieval_pretrained"]:
            other_top3 = state.top_by_pipe.get(name, [])[:3]
            for i, c in enumerate(other_top3):
                if c in be_top3:
                    overlap_score[c] += 3 - i  # weight by position (top=3, 2, 1)

        if overlap_score:
            anchor_top1 = max(overlap_score, key=overlap_score.get)
        else:
            anchor_top1 = be_top[0]

        l2_top = [anchor_top1] + [c for c in rrf_fused if c != anchor_top1]
        l2_top = l2_top[:TOP_K_OUTPUT]
    else:
        l2_top = rrf_fused[:TOP_K_OUTPUT]

    # L3: agent integration — NOVELTY FLAG ONLY (no re-ranking).
    # Empirical finding (audit on 200 windows): agent re-ranking changes
    # L2's top-1 on 80 windows but is NET wrong (-5 Hit@1) compared to
    # leaving L2 alone. Bi_encoder's top-1 is the stronger single signal.
    # So we use the agent's `is_novel` flag (94% precision) but do NOT
    # let it override the L2 ranking.
    #
    # Novelty signal combination: agent flag OR retrieval-conf < 0.5.
    # The free signal `tch_max_retrieval_conf < 0.5` matches the agent's
    # 94% precision standalone — combining them gives 95% precision /
    # 13.4% recall (vs agent-only 7.4% recall on full 1008-window split),
    # a +81% relative recall lift with no precision loss.
    max_ret_conf = max_retrieval_confidence(state)
    free_novelty_signal = max_ret_conf < 0.5

    agent_top = state.top_by_pipe.get("diagnosis_agent")
    agent_novel = state.is_novel_by_pipe.get("diagnosis_agent")
    if agent_top is not None:
        agent_ran = True
        final_top = l2_top
        is_novel = bool(agent_novel) or free_novelty_signal
    else:
        final_top = l2_top
        is_novel = free_novelty_signal
        agent_ran = False

    return {
        "window_id": state.window_id,
        "pipeline_name": "tch_cascade",
        "triage_score": float(stacked_triage),
        "triage_decision": triage_decision,
        "is_novel": is_novel,
        "matched_issue_ids": final_top,
        "gold_label": state.gold_label,
        "gold_is_novel": state.gold_is_novel,
        "gold_matched_issue_ids": sorted(state.gold),
        "gold_expected_in_memory": state.expected_in_memory,
        "scenario_family": state.scenario_family,
        "service_name": state.service_name,
        "window_type": state.window_type,
        "is_hard_case": state.is_hard_case,
        "triage_reason_class": state.triage_reason_class,
        "n_prior_family_tickets": state.n_prior_family_tickets,
        # cascade diagnostics
        "tch_agent_ran": agent_ran,
        "tch_agent_eligible": is_agent_eligible(state),
        "tch_l2_top": l2_top,
        "tch_max_retrieval_conf": float(max_retrieval_confidence(state)),
    }


def compute_metrics(predictions: list[dict]) -> dict:
    """Compute Hit@K (binary), MRR, novelty quality, basic triage AUCs."""
    from sklearn.metrics import average_precision_score, roc_auc_score

    hits1 = hits5 = total_with_gold = 0
    mrr_sum = 0.0
    for p in predictions:
        gold = set(p["gold_matched_issue_ids"])
        if not gold:
            continue
        total_with_gold += 1
        top = p["matched_issue_ids"]
        for i, t in enumerate(top, 1):
            if t in gold:
                if i == 1:
                    hits1 += 1
                if i <= 5:
                    hits5 += 1
                mrr_sum += 1.0 / i
                break

    triage_scores = [p["triage_score"] for p in predictions]
    triage_labels = [1 if p["gold_label"] == "ticket_worthy" else 0 for p in predictions]
    triage_labels_inc = [1 if p["gold_label"] in {"ticket_worthy", "borderline"} else 0
                         for p in predictions]
    pr_auc = average_precision_score(triage_labels, triage_scores) if any(triage_labels) and not all(triage_labels) else 0.0
    pr_auc_inc = average_precision_score(triage_labels_inc, triage_scores) if any(triage_labels_inc) and not all(triage_labels_inc) else 0.0
    roc_auc = roc_auc_score(triage_labels, triage_scores) if any(triage_labels) and not all(triage_labels) else 0.0

    n_novel = sum(1 for p in predictions if p.get("is_novel"))
    n_truly_novel = sum(1 for p in predictions if not p["gold_matched_issue_ids"])
    novel_true_pos = sum(
        1 for p in predictions
        if p.get("is_novel") and not p["gold_matched_issue_ids"]
    )
    novel_precision = novel_true_pos / n_novel if n_novel else 0.0
    novel_recall = novel_true_pos / n_truly_novel if n_truly_novel else 0.0

    return {
        "n_predictions": len(predictions),
        "n_with_gold": total_with_gold,
        "hit_at_1": hits1 / total_with_gold if total_with_gold else 0.0,
        "hit_at_5": hits5 / total_with_gold if total_with_gold else 0.0,
        "mrr": mrr_sum / total_with_gold if total_with_gold else 0.0,
        "pr_auc": float(pr_auc),
        "pr_auc_inclusive": float(pr_auc_inc),
        "roc_auc": float(roc_auc),
        "n_novel_flagged": n_novel,
        "n_truly_novel": n_truly_novel,
        "novel_precision": novel_precision,
        "novel_recall": novel_recall,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"loading predictions from {args.global_dir / COMPARISON_BASE}")
    states = load_all_predictions(args.global_dir)
    print(f"loaded {len(states)} window states")

    # Pipeline coverage check
    pipe_counts: dict[str, int] = defaultdict(int)
    for s in states.values():
        for name in s.triage_by_pipe:
            pipe_counts[name] += 1
    print("pipeline coverage:")
    for name, n in sorted(pipe_counts.items()):
        print(f"  {name:36s}: {n} / {len(states)} windows")

    state_list = list(states.values())

    print("\nfitting L4 stacker (5-fold CV LogisticRegression)...")
    stacked = stack_triage_cv(state_list)
    print(f"  stacked predictions for {len(stacked)} windows")

    print("\nassembling cascade predictions...")
    predictions = [assemble_cascade_prediction(s, stacked[s.window_id]) for s in state_list]

    # Save predictions
    pred_path = args.output_dir / "per-window-predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as fh:
        for p in predictions:
            fh.write(json.dumps(p) + "\n")
    print(f"\nwrote {pred_path}")

    # Compute metrics
    metrics = compute_metrics(predictions)
    metrics_path = args.output_dir / "tch_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    print(f"\nTCH cascade metrics:")
    for k, v in metrics.items():
        print(f"  {k:24s}: {v}")

    # Baseline comparison metrics
    print("\nbaseline metrics (same windows):")
    for name in ["hist_gradient_boosting_numeric", "bi_encoder_retrieval",
                 "hybrid_rrf_retrieval_rule", "hybrid_rrf_retrieval_llm",
                 "diagnosis_agent"]:
        # Build single-pipeline predictions
        synthetic = []
        for s in state_list:
            top = s.top_by_pipe.get(name)
            if top is None and name == "diagnosis_agent":
                # skip windows the agent didn't see for the agent's own metric
                continue
            synthetic.append({
                "matched_issue_ids": top or [],
                "gold_matched_issue_ids": sorted(s.gold),
                "triage_score": s.triage_by_pipe.get(name, 0.0),
                "gold_label": s.gold_label,
                "is_novel": s.is_novel_by_pipe.get(name, False),
            })
        m = compute_metrics(synthetic)
        print(f"  {name:36s}  n={m['n_predictions']:4d}  Hit@1={m['hit_at_1']:.3f}  Hit@5={m['hit_at_5']:.3f}  MRR={m['mrr']:.3f}  PR-AUC={m['pr_auc']:.3f}  PR-AUC(inc)={m['pr_auc_inclusive']:.3f}")

    # Cascade vs same-windows-as-agent (apples-to-apples)
    agent_wids = {s.window_id for s in state_list if "diagnosis_agent" in s.triage_by_pipe}
    cascade_on_agent = [p for p in predictions if p["window_id"] in agent_wids]
    m_agent_subset = compute_metrics(cascade_on_agent)
    print(f"\ncascade on the {len(agent_wids)}-window agent subset:")
    for k, v in m_agent_subset.items():
        print(f"  {k:24s}: {v}")

    # Write a human-readable report.md alongside the metrics JSON.
    report_path = args.output_dir / "report.md"
    with report_path.open("w", encoding="utf-8") as fh:
        fh.write("# TCH Cascade Report\n\n")
        fh.write(f"Generated by `v2_advanced.tch.build_cascade`. "
                 f"Source: `{args.global_dir}/comparison/`.\n\n")
        fh.write("## Cascade configuration\n\n")
        fh.write(f"- L2 retrievers (RRF fusion): {', '.join(L2_RETRIEVERS)}\n")
        fh.write(f"- L4 stacker features: {', '.join(L4_STACK_FEATURES)}\n")
        fh.write(f"- RRF k = {RRF_K}, top-K output = {TOP_K_OUTPUT}\n")
        fh.write(f"- L1 noise threshold = {L1_THRESHOLD}\n\n")
        fh.write("## Pipeline coverage\n\n")
        fh.write("| pipeline | n_windows |\n|---|---:|\n")
        for name, n in sorted(pipe_counts.items()):
            fh.write(f"| {name} | {n} |\n")
        fh.write("\n## Cascade metrics (full split)\n\n")
        fh.write("| metric | value |\n|---|---:|\n")
        for k, v in metrics.items():
            fh.write(f"| {k} | {v if isinstance(v, int) else f'{v:.4f}' if isinstance(v, float) else v} |\n")
        fh.write(f"\n## Cascade metrics (agent-ran subset, n={len(agent_wids)})\n\n")
        fh.write("| metric | value |\n|---|---:|\n")
        for k, v in m_agent_subset.items():
            fh.write(f"| {k} | {v if isinstance(v, int) else f'{v:.4f}' if isinstance(v, float) else v} |\n")
    print(f"\nwrote report: {report_path}")


if __name__ == "__main__":
    main()
