"""Build a cross-corpus gold relation: WoL Kafka memory × OTel Demo Kafka queries.

Closes RQ-B5 (Mode 4). The gold relation is a Jaccard symptom-token
overlap: for each OTel Demo Kafka query window, all WoL Kafka tickets
with Jaccard(token_set(query.text), token_set(ticket.memory_text)) >= θ
become its gold matches.

This is a coarse gold relation by design — Mode 4 doesn't claim
perfect alignment between two corpora; it asks "does retrieval find
the right SHAPE of incident even when the two corpora come from
different applications?".

Filter:
  - WoL memory tickets where wol_project == --project (default Kafka)
  - OTel Demo query windows where service_name lower-contains "kafka"

Output JSONL (one row per query window):
  {
    "window_id": "<otel-window-id>",
    "service_name": "kafka",
    "gold_matched_issue_ids": ["wol-m-...", ...],   # WoL Kafka tickets
    "n_gold": 3,
    "method": "jaccard",
    "threshold": 0.10
  }

Usage:
    PYTHONPATH=src python scripts/agent/build_cross_corpus_gold.py \\
        --memory-dataset data/derived/global/2026-06-15-wol-real-v2-global \\
        --query-dataset  data/derived/global/2026-06-09-otel-demo-v1-global \\
        --project-filter Kafka \\
        --threshold 0.10 \\
        --output data/derived/cross-corpus-kafka-gold.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path


log = logging.getLogger(__name__)


#: Stopwords + filler tokens that shouldn't drive overlap.
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "was", "are", "were", "be", "been", "being",
    "of", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "with", "from", "by", "as", "it", "this", "that", "these", "those",
    "i", "we", "you", "he", "she", "they", "them", "him", "her",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "must",
    "not", "no", "yes", "so", "just", "now",
    "issue", "ticket", "log", "error", "exception",     # too generic in this domain
})


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]{2,}")


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    return {
        t.lower() for t in _TOKEN_RE.findall(text)
        if t.lower() not in _STOPWORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


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


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--memory-dataset", type=Path, required=True,
                   help="root for the MEMORY corpus (e.g. WoL)")
    p.add_argument("--query-dataset", type=Path, required=True,
                   help="root for the QUERY corpus (e.g. OTel Demo)")
    p.add_argument("--project-filter", default="Kafka",
                   help="wol_project value to filter memory (default Kafka)")
    p.add_argument("--service-filter", default="kafka",
                   help="case-insensitive substring of service_name to "
                        "filter query windows (default 'kafka')")
    p.add_argument("--threshold", type=float, default=0.10,
                   help="Jaccard token-overlap threshold (default 0.10)")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # ----- Load memory (WoL Kafka)
    memory_path = args.memory_dataset / "jira-memory-corpus.jsonl"
    if not memory_path.exists():
        raise SystemExit(f"missing {memory_path}")

    memory_tokens: dict[str, set[str]] = {}
    for row in _iter_jsonl(memory_path):
        if row.get("wol_project") != args.project_filter:
            continue
        mid = row.get("jira_shadow_issue_id") or row.get("issue_id")
        if not mid:
            continue
        tokens = _tokenize(row.get("memory_text") or "")
        if tokens:
            memory_tokens[mid] = tokens
    log.info("loaded %d %s memory tickets from %s",
             len(memory_tokens), args.project_filter, memory_path)

    # ----- Load query windows (OTel Demo Kafka)
    examples = args.query_dataset / "global-triage-examples.jsonl"
    if not examples.exists():
        raise SystemExit(f"missing {examples}")

    n_query_total = 0
    n_query_kept = 0
    n_with_gold = 0
    gold_counts: list[int] = []

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out_fh:
        for row in _iter_jsonl(examples):
            n_query_total += 1
            svc = (row.get("service_name") or "").lower()
            if args.service_filter.lower() not in svc:
                continue
            window_id = row.get("window_id")
            if not window_id:
                continue

            q_tokens = _tokenize(row.get("triage_evidence_text") or "")
            matched: list[tuple[str, float]] = []
            for mid, m_tokens in memory_tokens.items():
                j = _jaccard(q_tokens, m_tokens)
                if j >= args.threshold:
                    matched.append((mid, j))
            matched.sort(key=lambda x: -x[1])

            gold_row = {
                "window_id": window_id,
                "service_name": row.get("service_name"),
                "gold_matched_issue_ids": [m for m, _ in matched],
                "gold_match_scores": [round(s, 4) for _, s in matched],
                "n_gold": len(matched),
                "method": "jaccard",
                "threshold": args.threshold,
                "n_query_tokens": len(q_tokens),
            }
            out_fh.write(json.dumps(gold_row) + "\n")
            n_query_kept += 1
            gold_counts.append(len(matched))
            if matched:
                n_with_gold += 1

    print()
    print("=" * 78)
    print(f"  Cross-corpus gold built ({args.project_filter})")
    print("=" * 78)
    print(f"  memory tickets:        {len(memory_tokens)}")
    print(f"  query windows scanned: {n_query_total}")
    print(f"  query windows kept:    {n_query_kept}")
    print(f"  with at least 1 gold:  {n_with_gold} "
          f"({n_with_gold * 100 / max(1, n_query_kept):.1f}%)")
    if gold_counts:
        gc = Counter()
        for n in gold_counts:
            if n == 0: gc["0"] += 1
            elif n <= 3: gc["1-3"] += 1
            elif n <= 10: gc["4-10"] += 1
            else: gc["11+"] += 1
        print(f"  gold-count buckets:    {dict(gc)}")
    print(f"  threshold:             jaccard >= {args.threshold}")
    print(f"  output:                {args.output}")
    print("=" * 78)


if __name__ == "__main__":
    main()
