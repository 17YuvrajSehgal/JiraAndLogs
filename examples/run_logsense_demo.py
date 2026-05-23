"""Quick demo: build LogSenseAnalyzer on pilot logs, print one analysis
per gold label so anomalous-line surfacing is visible.

    python examples/run_logsense_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from loganalyzer.memory.corpus import MemoryCorpus
from logsense.data.dataset import load_logs_dataset
from logsense.memory.retrieval import LogTemplateBM25Retriever
from logsense.product.analyzer import LogSenseAnalyzer
from logsense.product.formatter import render_log_explanation
from logsense.triage.hybrid import HybridLogModel


GLOBAL_DIR = REPO_ROOT / "data" / "derived" / "global" / "2026-05-21-dataset-v4-pilot-global"
RUNS_ROOT = REPO_ROOT / "data" / "runs"


def main() -> int:
    if not GLOBAL_DIR.is_dir():
        print(f"Pilot global dir not found: {GLOBAL_DIR}", file=sys.stderr)
        return 1
    if not RUNS_ROOT.is_dir():
        print(f"Runs root not found: {RUNS_ROOT}", file=sys.stderr)
        return 1

    print(f"Loading log dataset from {GLOBAL_DIR}, runs={RUNS_ROOT} ...")
    ds = load_logs_dataset(GLOBAL_DIR, RUNS_ROOT, progress_every=100)
    print(
        f"  loaded={len(ds.labeled_windows)} "
        f"missing={len(ds.missing_window_ids)} "
        f"memory={len(ds.memory_corpus)}"
    )

    train = ds.by_split("train")
    test = ds.by_split("test")
    print(f"  train={len(train)} test={len(test)}")

    analyzer = LogSenseAnalyzer(
        triage_model=HybridLogModel(),
        retriever=LogTemplateBM25Retriever(),
        memory_corpus=MemoryCorpus(issues=ds.memory_corpus),
        retrieval_top_k=3,
        top_anomalies=4,
    )
    print("Fitting LogSenseAnalyzer (hybrid_log + log_template_bm25) ...")
    analyzer.fit(train)

    print("\nSample analyses from the test split (one per gold label):")
    seen: set[str] = set()
    for lw in test:
        if lw.triage_label in seen:
            continue
        seen.add(lw.triage_label)
        result = analyzer.analyze_labeled(lw)
        print("-" * 78)
        print(f"GOLD label: {lw.triage_label} | scenario={lw.label.scenario_id} | service={lw.label.service_name}")
        print(render_log_explanation(result, max_matches=2, max_anomalies=4))
        print()
        if len(seen) == 3:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
