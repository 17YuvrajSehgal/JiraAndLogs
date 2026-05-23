"""logsense - log-only smart analysis with Jira-as-memory triage.

Sibling of `loganalyzer`. Where loganalyzer ingests the pre-aggregated
`triage_feature_*` columns spanning traces+metrics+kubernetes+logs, logsense
goes back to the *raw* Loki log lines exported under
`data/runs/<run>/raw/loki/<window>.json` and builds everything it needs
from log signal alone.

Why a separate package?
  - companies whose only observability source is logs (ELK, CloudWatch,
    Loki) should not need to compute trace / metric features just to use
    the system.
  - the modelling layer here is different: template mining + baseline-delta
    novelty detection + log-template BM25, rather than 28-dim numeric
    logistic.

What it reuses from loganalyzer:
  - data.splits.iter_split / iter_lofo_folds (split logic is pipeline-
    agnostic)
  - memory.corpus.MemoryCorpus (time-ordered visibility logic)
  - eval.metrics + eval.retrieval_metrics (PR-AUC, recall@k, etc.)
  - data.loaders for the global label / memory / split manifests

Public entrypoint: LogSenseAnalyzer.
"""

from .product.analyzer import LogSenseAnalyzer, LogAnalysisResult

__all__ = ["LogSenseAnalyzer", "LogAnalysisResult"]
__version__ = "0.1.0"
