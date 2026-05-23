"""Human-readable rendering of an AnalysisResult.

Used by the CLI demo and by anyone surfacing analyzer output into a chatops
flow. Plain text - no Markdown - so it embeds cleanly in Slack or email.
"""

from __future__ import annotations

from .analyzer import AnalysisResult


def render_explanation(result: AnalysisResult, *, max_matches: int = 3) -> str:
    lines: list[str] = []
    lines.append(f"Window: {result.window_id}")
    lines.append(
        f"Triage: {result.triage_decision} (score={result.triage_score:.3f})"
    )
    if result.triage_decision == "noise":
        lines.append("Recommendation: do not file a ticket.")
        return "\n".join(lines)

    if result.is_novel:
        lines.append("Novelty: NOVEL - no close match in Jira memory.")
        lines.append("Recommendation: file a new ticket; this looks unfamiliar.")
    else:
        lines.append("Novelty: matches an existing pattern in Jira memory.")
        lines.append("Recommendation: link to the top match before filing a new ticket.")

    if result.matched_issues:
        lines.append("")
        lines.append("Top matches:")
        for hit in result.matched_issues[:max_matches]:
            lines.append(
                f"  #{hit.rank} {hit.issue.jira_issue_key:>10} "
                f"score={hit.score:.3f} family={hit.issue.scenario_family} "
                f"service={hit.issue.affected_service}"
            )
            preview = hit.issue.memory_text.replace("\n", " ").strip()
            if len(preview) > 160:
                preview = preview[:160] + "..."
            lines.append(f"        \"{preview}\"")

    if result.citation_summary:
        lines.append("")
        lines.append(f"Summary: {result.citation_summary}")
    return "\n".join(lines)
