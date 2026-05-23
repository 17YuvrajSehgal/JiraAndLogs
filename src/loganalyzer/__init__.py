"""loganalyzer - smart log analysis with Jira-as-memory triage and retrieval.

Top-level entrypoint for companies who want to triage telemetry windows and
cite matching past Jira issues. See product.analyzer.SmartLogAnalyzer.

The package is organized into independent layers so a team can swap any one
piece (retrieval backend, triage model, feature extractor) without touching
the others. Layer order matches data flow:

    data       -> schema + jsonl loaders + split iterator
    features   -> numeric + text feature builders
    triage     -> ticket_worthy / borderline / noise classifiers
    memory     -> Jira corpus + retriever (time-ordered)
    product    -> end-to-end SmartLogAnalyzer
    eval       -> metrics + runner for offline benchmarking

The dataset contract this package consumes is documented in
docs/triage-task-contract.md and docs/dataset-v4-plan.md.
"""

from .product.analyzer import SmartLogAnalyzer, AnalysisResult

__all__ = ["SmartLogAnalyzer", "AnalysisResult"]
__version__ = "0.1.0"
