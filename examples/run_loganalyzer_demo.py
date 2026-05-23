"""Quick demo: build a SmartLogAnalyzer on the v4 pilot dataset and print
analysis for a few real test-set windows.

Run from project root:

    python examples/run_loganalyzer_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from loganalyzer.data import iter_split, load_dataset
from loganalyzer.memory.corpus import MemoryCorpus
from loganalyzer.memory.retrieval import BM25Retriever
from loganalyzer.product.analyzer import SmartLogAnalyzer
from loganalyzer.product.formatter import render_explanation
from loganalyzer.triage.hybrid import HybridTriageModel


GLOBAL_DIR = REPO_ROOT / "data" / "derived" / "global" / "2026-05-21-dataset-v4-pilot-global"


def main() -> int:
    if not GLOBAL_DIR.is_dir():
        print(f"Pilot global dir not found: {GLOBAL_DIR}", file=sys.stderr)
        return 1

    print(f"Loading pilot dataset from {GLOBAL_DIR} ...")
    dataset = load_dataset(GLOBAL_DIR)
    print(
        f"  windows={len(dataset.windows)} "
        f"memory_issues={len(dataset.memory_corpus)} "
        f"feature_columns={len(dataset.feature_columns)}"
    )

    train = list(iter_split(dataset.windows, dataset.split_manifest, "train"))
    test = list(iter_split(dataset.windows, dataset.split_manifest, "test"))
    print(f"  train={len(train)} test={len(test)}")

    analyzer = SmartLogAnalyzer(
        triage_model=HybridTriageModel(dataset.feature_columns),
        retriever=BM25Retriever(),
        memory_corpus=MemoryCorpus(issues=dataset.memory_corpus),
        retrieval_top_k=3,
    )
    print("Fitting analyzer (hybrid_numeric_lexical + bm25) ...")
    analyzer.fit(train)

    print("\nSample analyses from the test split:")
    sample_indices: list[int] = []
    seen_labels: set[str] = set()
    for i, w in enumerate(test):
        if w.triage_label not in seen_labels:
            sample_indices.append(i)
            seen_labels.add(w.triage_label)
        if len(seen_labels) == 3:
            break

    for i in sample_indices:
        w = test[i]
        result = analyzer.analyze(w)
        print("-" * 78)
        print(f"GOLD label: {w.triage_label} | scenario={w.scenario_id} | service={w.service_name}")
        print(render_explanation(result, max_matches=2))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
