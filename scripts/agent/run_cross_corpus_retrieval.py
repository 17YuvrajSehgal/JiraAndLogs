"""Cross-corpus retrieval (Mode 4): WoL Kafka memory × OTel Demo Kafka queries.

Closes RQ-B5. Uses TF-IDF as a strong-but-cheap retrieval baseline
(BM25-equivalent at the agent layer; the cascade-side BM25 baseline
lives in v2_advanced/tch/run_bm25_baseline.py).

For each query window in `--gold`, retrieves top-K from the memory
corpus by TF-IDF cosine, scores against the gold relation built by
`build_cross_corpus_gold.py`, and reports Hit@K + MRR with bootstrap
CIs.

Usage:
    PYTHONPATH=src python scripts/agent/run_cross_corpus_retrieval.py \\
        --memory-dataset data/derived/global/2026-06-11-wol-real-global \\
        --query-dataset  data/derived/global/2026-06-09-otel-demo-v1-global \\
        --gold data/derived/cross-corpus-kafka-gold.jsonl \\
        --project-filter Kafka \\
        --service-filter kafka \\
        --top-k 10 \\
        --output data/agent_runs/mode4-cross-corpus-kafka.json
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
    metric_hit_at_10,
    metric_mrr,
    rows_from_dicts,
)


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _load_memory_texts(
    memory_path: Path,
    project_filter: str,
) -> tuple[list[str], list[str]]:
    """Return (memory_ids, memory_texts) for tickets in `project_filter`."""
    ids: list[str] = []
    texts: list[str] = []
    for row in _iter_jsonl(memory_path):
        if row.get("wol_project") != project_filter:
            continue
        mid = row.get("jira_shadow_issue_id") or row.get("issue_id")
        text = row.get("memory_text") or ""
        if mid and text:
            ids.append(mid)
            texts.append(text)
    return ids, texts


def _load_query_index(
    examples_path: Path,
    service_filter: str,
) -> dict[str, str]:
    """Return window_id → triage_evidence_text for matching windows."""
    out: dict[str, str] = {}
    for row in _iter_jsonl(examples_path):
        svc = (row.get("service_name") or "").lower()
        if service_filter.lower() not in svc:
            continue
        wid = row.get("window_id")
        text = row.get("triage_evidence_text") or ""
        if wid and text:
            out[wid] = text
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--memory-dataset", type=Path, required=True)
    p.add_argument("--query-dataset", type=Path, required=True)
    p.add_argument("--gold", type=Path, required=True,
                   help="JSONL produced by build_cross_corpus_gold.py")
    p.add_argument("--project-filter", default="Kafka")
    p.add_argument("--service-filter", default="kafka")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--n-resamples", type=int, default=DEFAULT_N_RESAMPLES)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        raise SystemExit("scikit-learn required: pip install scikit-learn")

    # ----- Load memory + queries
    memory_path = args.memory_dataset / "jira-memory-corpus.jsonl"
    examples_path = args.query_dataset / "global-triage-examples.jsonl"
    if not memory_path.exists():
        raise SystemExit(f"missing {memory_path}")
    if not examples_path.exists():
        raise SystemExit(f"missing {examples_path}")
    if not args.gold.exists():
        raise SystemExit(f"missing gold file: {args.gold}")

    memory_ids, memory_texts = _load_memory_texts(
        memory_path, args.project_filter,
    )
    log.info("loaded %d %s memory tickets",
             len(memory_ids), args.project_filter)

    query_index = _load_query_index(examples_path, args.service_filter)
    log.info("loaded %d query windows matching service ~ %s",
             len(query_index), args.service_filter)

    if not memory_ids or not query_index:
        raise SystemExit("empty memory or query set; check filters")

    # ----- Fit TF-IDF
    corpus = memory_texts + list(query_index.values())
    vec = TfidfVectorizer(
        max_features=10_000, min_df=2, ngram_range=(1, 1),
        lowercase=True, stop_words="english",
    )
    X = vec.fit_transform(corpus)
    n_mem = len(memory_texts)
    M = X[:n_mem]
    log.info("TF-IDF fit done; %d memory vectors, vocab=%d",
             n_mem, len(vec.vocabulary_))

    # ----- Retrieve + score
    query_id_order = list(query_index.keys())
    query_vecs = X[n_mem:]
    sims = (query_vecs @ M.T).toarray()
    log.info("similarity matrix: %s", sims.shape)

    # Load gold by window_id
    gold_by_window: dict[str, list[str]] = {}
    for g in _iter_jsonl(args.gold):
        wid = g.get("window_id")
        if wid:
            gold_by_window[wid] = list(g.get("gold_matched_issue_ids") or [])

    # Build prediction rows
    rows = []
    for i, wid in enumerate(query_id_order):
        # Top-K by similarity
        row_sims = sims[i]
        top_idx = sorted(range(len(memory_ids)),
                         key=lambda k: -row_sims[k])[: args.top_k]
        matched = [memory_ids[k] for k in top_idx]
        rows.append({
            "window_id": wid,
            "matched_issue_ids": matched,
            "gold_matched_issue_ids": gold_by_window.get(wid, []),
        })

    n_with_gold = sum(1 for r in rows if r["gold_matched_issue_ids"])
    log.info("scored %d windows; %d have gold (the rest are excluded "
             "from Hit@K via len(gold)>=1 filter)",
             len(rows), n_with_gold)

    # ----- Bootstrap
    bs_rows = rows_from_dicts(rows)
    metrics = {}
    for name, fn in (
        ("hit_at_1", metric_hit_at_1),
        ("hit_at_5", metric_hit_at_5),
        ("hit_at_10", metric_hit_at_10),
        ("mrr", metric_mrr),
    ):
        bs = bootstrap_metric(
            bs_rows, fn, metric_name=name,
            n_resamples=args.n_resamples,
            seed=args.seed, confidence=args.confidence,
        )
        metrics[name] = bs.to_dict()

    # ----- Output
    print()
    print("=" * 80)
    print(f"  Mode 4 cross-corpus retrieval (RQ-B5)")
    print(f"  memory:  {args.project_filter} from {args.memory_dataset.name}  (n={len(memory_ids)})")
    print(f"  queries: {args.service_filter} from {args.query_dataset.name} (n={len(query_id_order)})")
    print(f"  windows with gold: {n_with_gold} / {len(rows)}")
    print("=" * 80)
    print(f"  {'metric':<12} {'point':>8}  {'95% CI':>22}")
    print("  " + "-" * 45)
    for name, m in metrics.items():
        print(f"  {name:<12} {m['point_estimate']:>8.4f}  "
              f"[{m['ci_low']:>7.4f}, {m['ci_high']:>7.4f}]")
    print("=" * 80)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "method": "tfidf_jaccard_gold",
        "memory_project": args.project_filter,
        "query_service_filter": args.service_filter,
        "n_memory": len(memory_ids),
        "n_queries": len(rows),
        "n_with_gold": n_with_gold,
        "top_k": args.top_k,
        "metrics": metrics,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\n[mode4] wrote -> {args.output}")


log = logging.getLogger("mode4")

if __name__ == "__main__":
    main()
