"""core - shared data + features + memory + eval infrastructure.

This package is the foundation every TCH pipeline depends on. It provides:

    data       -> dataset schemas + jsonl loaders + train/val/test split iterator
    features   -> text feature builders (build_window_query_text,
                  build_memory_doc_text) used by every retriever
    memory     -> MemoryCorpus.visible_to() — time-ordered, same-run-excluded
                  view of the Jira corpus used by every retrieval pipeline
    eval       -> metrics (PR-AUC, ROC-AUC, ECE, precision-at-FPR,
                  recall@K, MRR, novelty F1)

The package owns no pipeline code; it is purely shared infrastructure.
Originally lived as `src/loganalyzer/` (a baseline-pipeline implementation);
the baseline code was removed and only the data/features/memory/eval layers
were kept. Imports were renamed `loganalyzer.X -> core.X` accordingly.

The dataset contract this package consumes is documented in
docs/triage-task-contract.md and docs/dataset-v4-plan.md.
"""

# Top-level re-exports are deliberately omitted to avoid pulling in the
# heavy submodules at import time. Users should import from the submodule
# that owns the symbol they want:
#
#     from core.data.loaders import load_dataset
#     from core.features.text import build_memory_doc_text
#     from core.memory.corpus import MemoryCorpus

__version__ = "0.2.0"
