"""LogSenseAnalyzer - end-to-end log-only triage + memory retrieval.

For a given WindowLogs it answers:
  1. is this worth a Jira ticket?       (triage)
  2. which past Jira issues match?       (BM25 over log templates + memory)
  3. is this a novel incident?           (no close match)
  4. what are the weirdest log lines?    (top anomalous templates vs baseline)

The fourth output is the differentiator vs loganalyzer: companies running
this on production logs get *specific log lines surfaced* alongside the
triage decision, not just a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loganalyzer.data.schema import TriageWindow
from loganalyzer.memory.corpus import MemoryCorpus

from ..data.schema import LabeledWindowLogs, WindowLogs
from ..memory.retrieval import LogRetrievalHit, LogTemplateBM25Retriever
from ..templates.fingerprint import (
    AnomalousTemplate,
    compare_to_baseline,
    fingerprint_window,
)
from ..templates.miner import mask_line
from ..triage.base import LogTriageModel


@dataclass
class LogAnalysisResult:
    window_id: str
    triage_score: float
    triage_decision: str  # ticket_worthy | noise
    is_novel: bool
    anomalous_templates: list[AnomalousTemplate] = field(default_factory=list)
    matched_issues: list[LogRetrievalHit] = field(default_factory=list)
    citation_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "triage_score": self.triage_score,
            "triage_decision": self.triage_decision,
            "is_novel": self.is_novel,
            "anomalous_templates": [
                {
                    "template": a.template,
                    "count_active": a.count_active,
                    "count_baseline": a.count_baseline,
                    "severity": a.severity,
                    "example_body": a.example_body,
                    "novelty_score": a.novelty_score,
                }
                for a in self.anomalous_templates
            ],
            "matched_issues": [
                {
                    "rank": hit.rank,
                    "issue_id": hit.issue_id,
                    "jira_issue_key": hit.issue.jira_issue_key,
                    "score": hit.score,
                    "scenario_family": hit.issue.scenario_family,
                    "affected_service": hit.issue.affected_service,
                    "memory_text_preview": hit.issue.memory_text[:240],
                    "resolution_notes": hit.issue.resolution_notes,
                }
                for hit in self.matched_issues
            ],
            "citation_summary": self.citation_summary,
        }


class LogSenseAnalyzer:
    """Train on labeled log windows, analyze on a WindowLogs."""

    def __init__(
        self,
        triage_model: LogTriageModel,
        retriever: LogTemplateBM25Retriever,
        memory_corpus: MemoryCorpus,
        *,
        triage_threshold: float = 0.5,
        retrieval_top_k: int = 5,
        novelty_min_score: float = 1.0,
        top_anomalies: int = 5,
    ) -> None:
        self.triage_model = triage_model
        self.retriever = retriever
        self.memory_corpus = memory_corpus
        self.triage_threshold = triage_threshold
        self.retrieval_top_k = retrieval_top_k
        self.novelty_min_score = novelty_min_score
        self.top_anomalies = top_anomalies
        # baseline_index: (dataset_run_id, service_name) -> baseline fingerprint
        # built at fit time from pre_fault_baseline windows so anomalies have
        # something to diff against at inference time.
        self._baseline_index: dict[tuple[str, str], "object"] = {}
        # severity_lookup: template -> modal severity learned from training.
        self._severity_lookup: dict[str, str] = {}
        self._fit_done = False

    def fit(self, training: list[LabeledWindowLogs]) -> None:
        # Build baseline fingerprints per (run, service) - we average across
        # all baseline windows for the same run+service.
        from collections import defaultdict
        baseline_groups: dict[tuple[str, str], list[LabeledWindowLogs]] = defaultdict(list)
        for lw in training:
            if lw.label.window_type in {"pre_fault_baseline", "observation_window"}:
                key = (lw.label.dataset_run_id, lw.label.service_name)
                baseline_groups[key].append(lw)

        for key, group in baseline_groups.items():
            from ..templates.fingerprint import WindowFingerprint
            from collections import Counter as _C
            agg_fp = WindowFingerprint(window_id=f"baseline[{key[0]}|{key[1]}]")
            counts: _C[str] = _C()
            for lw in group:
                fp = fingerprint_window(lw.logs)
                counts.update(fp.template_counts)
                for tmpl, ex in fp.example_by_template.items():
                    agg_fp.example_by_template.setdefault(tmpl, ex)
            agg_fp.template_counts = counts
            self._baseline_index[key] = agg_fp

        # severity lookup for human-readable anomaly tagging
        for lw in training:
            for ln in lw.logs.lines:
                tmpl = mask_line(ln.body)
                if tmpl and tmpl not in self._severity_lookup:
                    self._severity_lookup[tmpl] = ln.severity

        self.triage_model.fit(training)
        self.retriever.fit(self.memory_corpus)
        self._fit_done = True

    def _baseline_for(self, window: WindowLogs):
        return self._baseline_index.get((window.dataset_run_id, window.service_name))

    def analyze(
        self,
        window: WindowLogs,
        *,
        as_triage_window: TriageWindow | None = None,
    ) -> LogAnalysisResult:
        if not self._fit_done:
            raise RuntimeError("LogSenseAnalyzer.fit must be called before analyze")

        score = self.triage_model.predict_score(window)
        decision = "ticket_worthy" if score >= self.triage_threshold else "noise"

        active_fp = fingerprint_window(window)
        baseline_fp = self._baseline_for(window)
        # Prefer this window's own line severities (the loader tagged stack
        # frames as 'error' etc); fall back to the training-time lookup so
        # rare-in-window templates still get a reasonable label.
        per_window_severity: dict[str, str] = {}
        for ln in window.lines:
            tmpl = mask_line(ln.body)
            if tmpl and tmpl not in per_window_severity:
                per_window_severity[tmpl] = ln.severity
        merged_severity = {**self._severity_lookup, **per_window_severity}
        anomalies = compare_to_baseline(
            active_fp,
            baseline_fp,
            top_n=self.top_anomalies,
            severity_lookup=merged_severity,
        )

        hits: list[LogRetrievalHit] = []
        if decision == "ticket_worthy":
            hits = self.retriever.retrieve(
                window,
                self.memory_corpus,
                anomalies,
                top_k=self.retrieval_top_k,
                as_triage_window=as_triage_window,
            )

        is_novel = decision == "ticket_worthy" and (
            not hits or hits[0].score < self.novelty_min_score
        )

        citation = _citation_summary(hits, is_novel=is_novel, decision=decision, anomalies=anomalies)
        return LogAnalysisResult(
            window_id=window.window_id,
            triage_score=score,
            triage_decision=decision,
            is_novel=is_novel,
            anomalous_templates=anomalies,
            matched_issues=hits,
            citation_summary=citation,
        )

    def analyze_labeled(self, lw: LabeledWindowLogs) -> LogAnalysisResult:
        return self.analyze(lw.logs, as_triage_window=lw.label)


def _citation_summary(
    hits: list[LogRetrievalHit],
    *,
    is_novel: bool,
    decision: str,
    anomalies: list[AnomalousTemplate],
) -> str:
    if decision == "noise":
        return "No ticket suggested - log signal scored below triage threshold."
    if is_novel:
        if anomalies:
            top = anomalies[0]
            return (
                f"Likely novel log pattern. Top weird line: \"{top.example_body[:100]}\" "
                f"({top.count_active}x in window, {top.count_baseline}x in baseline)."
            )
        return "Likely novel log pattern. No close match in Jira memory."
    top = hits[0]
    return (
        f"Likely matches {top.issue.jira_issue_key} "
        f"({top.issue.scenario_family} / {top.issue.affected_service}). "
        f"Resolution notes: {top.issue.resolution_notes[:140]}"
    )
