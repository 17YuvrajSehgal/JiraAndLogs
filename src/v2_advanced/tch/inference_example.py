"""Example: load the deployed TCH stacker and score a single window.

Demonstrates the inference path you'd use in production where each new
incoming window has retrieval+triage features pre-computed and you want
TCH's final triage_score + ranked top-5.

The stacker.pkl artifact is produced by `build_cascade.py` and contains:
  - model:               sklearn LogisticRegression trained on the full
                         test split
  - feature_names:       ordered feature columns the model expects
  - coefficients:        for inspection
  - intercept:           for inspection
  - trained_on_n_windows: provenance

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.inference_example \\
        --stacker-path data/derived/global/.../v2f-tch-phase1/stacker.pkl
"""
from __future__ import annotations

import argparse
import pickle
from collections import defaultdict
from pathlib import Path


# Example "live" window: per-pipeline triage_scores and top-5 candidate IDs.
# In production you'd populate these from your live pipelines.
EXAMPLE_WINDOW = {
    "window_id": "live-window-001",
    "triage_scores": {
        "hist_gradient_boosting_numeric": 0.92,
        "bi_encoder_retrieval": 0.61,
        "hybrid_rrf_retrieval_rule": 0.58,
        "hybrid_rrf_retrieval_llm": 0.45,
        "logseq2vec_retrieval_pretrained": 0.39,
        "kg_retrieval_rulebased": 0.33,
    },
    "retriever_top5": {
        "bi_encoder_retrieval": ["TICKET-101", "TICKET-202", "TICKET-303", "TICKET-404", "TICKET-505"],
        "hybrid_rrf_retrieval_rule": ["TICKET-101", "TICKET-303", "TICKET-202", "TICKET-606", "TICKET-707"],
        "logseq2vec_retrieval_pretrained": ["TICKET-303", "TICKET-808", "TICKET-101", "TICKET-202", "TICKET-909"],
        "kg_retrieval_rulebased": ["TICKET-101", "TICKET-707", "TICKET-808", "TICKET-606", "TICKET-505"],
        "hybrid_rrf_retrieval_llm": ["TICKET-202", "TICKET-101", "TICKET-303", "TICKET-505", "TICKET-606"],
    },
}

RRF_K = 60
L2_RETRIEVERS = ["bi_encoder_retrieval", "hybrid_rrf_retrieval_rule",
                 "logseq2vec_retrieval_pretrained", "kg_retrieval_rulebased"]
TOP_K_OUTPUT = 5


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K, top_n: int = TOP_K_OUTPUT) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] += 1.0 / (k + rank)
    return [d for d, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:top_n]]


def score_window(stacker_bundle: dict, window: dict) -> dict:
    """Run the TCH inference path on one window."""
    model = stacker_bundle["model"]
    feature_names = stacker_bundle["feature_names"]
    triage_scores = window["triage_scores"]
    retrieves = window["retriever_top5"]

    # L1: triage_score from stacker
    feat_vec = [[triage_scores.get(f, 0.0) for f in feature_names]]
    triage_score = float(model.predict_proba(feat_vec)[0, 1])

    # L2: overlap-rerank top-1 + RRF for 2-5
    be_top = retrieves.get("bi_encoder_retrieval", [])[:10]
    rrf_fused = rrf_fuse(
        [retrieves.get(r, [])[:10] for r in L2_RETRIEVERS],
        top_n=TOP_K_OUTPUT + 5,
    )
    if be_top:
        be_top3 = be_top[:3]
        overlap_score: dict[str, int] = defaultdict(int)
        for r in ["hybrid_rrf_retrieval_rule", "hybrid_rrf_retrieval_llm",
                  "logseq2vec_retrieval_pretrained"]:
            for i, c in enumerate(retrieves.get(r, [])[:3]):
                if c in be_top3:
                    overlap_score[c] += 3 - i
        anchor = (max(overlap_score, key=overlap_score.get)
                  if overlap_score else be_top[0])
        final_top = [anchor] + [c for c in rrf_fused if c != anchor]
        final_top = final_top[:TOP_K_OUTPUT]
    else:
        final_top = rrf_fused[:TOP_K_OUTPUT]

    # Free novelty: max retrieval-confidence proxy
    max_ret_conf = max(triage_scores.get(r, 0.0)
                       for r in ["bi_encoder_retrieval", "hybrid_rrf_retrieval_rule",
                                 "hybrid_rrf_retrieval_llm"])
    is_novel = max_ret_conf < 0.5

    return {
        "window_id": window["window_id"],
        "triage_score": triage_score,
        "triage_decision": "ticket_worthy" if triage_score >= 0.5 else "noise",
        "matched_issue_ids": final_top,
        "is_novel": is_novel,
        "max_retrieval_confidence": float(max_ret_conf),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stacker-path", type=Path, required=True)
    args = ap.parse_args()

    bundle = pickle.loads(args.stacker_path.read_bytes())
    print(f"Loaded stacker: trained on {bundle['trained_on_n_windows']} windows")
    print(f"Features ({len(bundle['feature_names'])}):")
    for name, coef in zip(bundle["feature_names"], bundle["coefficients"]):
        print(f"  {name:36s}  coef={coef:+.3f}")
    print(f"intercept: {bundle['intercept']:+.3f}")
    print()

    print(f"Scoring example window: {EXAMPLE_WINDOW['window_id']}")
    out = score_window(bundle, EXAMPLE_WINDOW)
    print("\nOutput:")
    for k, v in out.items():
        print(f"  {k:28s}: {v}")


if __name__ == "__main__":
    main()
