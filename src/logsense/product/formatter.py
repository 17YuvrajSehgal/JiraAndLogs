"""Plain-text rendering of a LogAnalysisResult.

Mirrors loganalyzer's render_explanation but adds the anomalous-template
section, which is the main user-facing differentiator of the log-only
analyzer.
"""

from __future__ import annotations

from .analyzer import LogAnalysisResult


def render_log_explanation(result: LogAnalysisResult, *, max_matches: int = 3, max_anomalies: int = 5) -> str:
    lines: list[str] = []
    lines.append(f"Window: {result.window_id}")
    lines.append(f"Triage: {result.triage_decision} (score={result.triage_score:.3f})")

    if result.anomalous_templates:
        lines.append("")
        lines.append("Anomalous log templates (vs same-service baseline):")
        for a in result.anomalous_templates[:max_anomalies]:
            lines.append(
                f"  - severity={a.severity:<8} active={a.count_active:<3} "
                f"baseline={a.count_baseline:<3} novelty={a.novelty_score:>6.2f}"
            )
            lines.append(f"    template: {a.template[:140]}")
            example = a.example_body.replace('\n', ' ')[:140]
            if example and example != a.template[:140]:
                lines.append(f"    example:  {example}")

    if result.triage_decision == "noise":
        lines.append("")
        lines.append("Recommendation: do not file a ticket.")
        return "\n".join(lines)

    lines.append("")
    if result.is_novel:
        lines.append("Novelty: NOVEL - no close log-template match in Jira memory.")
        lines.append("Recommendation: file a new ticket; surface the anomalous lines above.")
    else:
        lines.append("Novelty: matches an existing log pattern in Jira memory.")
        lines.append("Recommendation: link to the top match before filing a new ticket.")

    if result.matched_issues:
        lines.append("")
        lines.append("Top matches:")
        for hit in result.matched_issues[:max_matches]:
            lines.append(
                f"  #{hit.rank} {hit.issue.jira_issue_key:>10} score={hit.score:.3f} "
                f"family={hit.issue.scenario_family} service={hit.issue.affected_service}"
            )
            preview = hit.issue.memory_text.replace('\n', ' ').strip()
            if len(preview) > 160:
                preview = preview[:160] + "..."
            lines.append(f"        \"{preview}\"")

    if result.citation_summary:
        lines.append("")
        lines.append(f"Summary: {result.citation_summary}")
    return "\n".join(lines)
