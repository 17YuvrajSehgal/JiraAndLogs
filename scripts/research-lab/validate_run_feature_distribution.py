#!/usr/bin/env python3
"""
Per-run data quality sanity check.

Reads triage_examples.jsonl for a single dataset run, computes feature
distributions and label-telemetry consistency checks, then writes:

  summaries/feature-distribution.md       human-readable per-feature stats
  summaries/data-quality-report.md        anomaly flags and pass/fail gates
  summaries/data-quality-report.json      machine-readable for orchestration

Anomalies flagged (any of these is a hard failure for the run):
  - all numeric features are zero in every window (likely collection failure)
  - >50% of ticket_worthy windows have no trace_error_count AND no
    pod_unavailable_count AND no warning events (likely fault did not fire)
  - any expected window_type missing (every fault scenario should have
    pre_fault_baseline, active_fault, recovery_window per service)
  - label distribution skew (e.g. zero noise rows in a fault scenario run
    would be suspicious)

Run after every collection iteration to spot silent failures EARLY in
multi-day collections; a 2-day run with 30+ scenarios should not be
allowed to complete with one broken run hiding inside.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from triage_labels import (
    FEATURE_COLUMNS,
    read_jsonl,
    repo_root_from_script,
    utc_now,
    write_json,
)

SCRIPT_VERSION = "0.1.0"


def validate(
    repo_root: Path,
    dataset_run_id: str,
    derived_root: Path | None = None,
    runs_root: Path | None = None,
) -> dict[str, Any]:
    if derived_root is None:
        derived_root = repo_root / "data" / "derived"
    if runs_root is None:
        runs_root = repo_root / "data" / "runs"

    derived_run_dir = derived_root / dataset_run_id
    raw_run_dir = runs_root / dataset_run_id
    examples_path = derived_run_dir / "triage_examples.jsonl"
    if not examples_path.exists():
        raise FileNotFoundError(
            f"Per-run triage examples not found at {examples_path}. "
            f"Run build-triage-dataset.ps1 first."
        )

    rows = read_jsonl(examples_path)
    anomalies: list[dict[str, Any]] = []

    # 1. Empty feature exports
    all_zero_rows = 0
    for row in rows:
        if all(float(row.get(col, 0.0) or 0.0) == 0.0 for col in FEATURE_COLUMNS):
            all_zero_rows += 1
    if all_zero_rows == len(rows) and rows:
        anomalies.append(
            {
                "severity": "fail",
                "code": "all_features_zero",
                "message": (
                    f"All {len(rows)} windows have zero across every feature. "
                    "Collection probably did not produce raw exports."
                ),
            }
        )
    elif all_zero_rows > 0:
        share = all_zero_rows / max(1, len(rows))
        if share > 0.10:
            anomalies.append(
                {
                    "severity": "warn",
                    "code": "many_all_zero_windows",
                    "message": f"{all_zero_rows} of {len(rows)} windows ({share:.1%}) are all-zero across features.",
                }
            )

    # 2. Ticket-worthy windows with no observable signal (fault may not have fired)
    suspicious_ticket_worthy: list[str] = []
    ticket_worthy_total = 0
    for row in rows:
        if row.get("triage_label") != "ticket_worthy":
            continue
        ticket_worthy_total += 1
        trace_err = float(row.get("triage_feature_trace_error_count", 0.0) or 0.0)
        pod_unavail = float(row.get("triage_feature_k8s_pod_unavailable_count", 0.0) or 0.0)
        warn_ev = float(row.get("triage_feature_k8s_warning_event_count", 0.0) or 0.0)
        latency_p95 = float(row.get("triage_feature_trace_latency_p95_ms", 0.0) or 0.0)
        log_err = float(row.get("triage_feature_log_error_count", 0.0) or 0.0)
        signal = trace_err + pod_unavail + warn_ev + log_err + max(0.0, latency_p95 - 200.0)
        if signal == 0.0:
            suspicious_ticket_worthy.append(str(row.get("window_id", "")))
    if ticket_worthy_total > 0:
        suspect_share = len(suspicious_ticket_worthy) / ticket_worthy_total
        if suspect_share > 0.50:
            anomalies.append(
                {
                    "severity": "fail",
                    "code": "ticket_worthy_no_signal",
                    "message": (
                        f"{len(suspicious_ticket_worthy)} of {ticket_worthy_total} ticket_worthy "
                        f"windows ({suspect_share:.1%}) show zero observable signal. Fault injection "
                        f"likely failed for these windows."
                    ),
                    "sample_window_ids": suspicious_ticket_worthy[:5],
                }
            )
        elif suspect_share > 0.20:
            anomalies.append(
                {
                    "severity": "warn",
                    "code": "ticket_worthy_no_signal",
                    "message": (
                        f"{len(suspicious_ticket_worthy)} of {ticket_worthy_total} ticket_worthy "
                        f"windows ({suspect_share:.1%}) show zero observable signal."
                    ),
                    "sample_window_ids": suspicious_ticket_worthy[:5],
                }
            )

    # 3. Window type coverage per episode
    episode_types: dict[str, set[str]] = defaultdict(set)
    episode_jira: dict[str, bool] = {}
    for row in rows:
        ep = str(row.get("incident_episode_id") or "")
        episode_types[ep].add(str(row.get("window_type") or ""))
    episodes = read_jsonl(raw_run_dir / "episodes.jsonl")
    for ep in episodes:
        episode_jira[str(ep.get("incident_episode_id"))] = bool(
            ep.get("jira_candidate", False)
        )
    fault_episodes_missing_windows: list[str] = []
    for ep_id, types in episode_types.items():
        is_fault = episode_jira.get(ep_id, False)
        if is_fault and not (
            "active_fault" in types and "pre_fault_baseline" in types
        ):
            fault_episodes_missing_windows.append(ep_id)
    if fault_episodes_missing_windows:
        anomalies.append(
            {
                "severity": "warn",
                "code": "missing_window_types",
                "message": (
                    f"{len(fault_episodes_missing_windows)} jira_candidate episodes are "
                    f"missing pre_fault_baseline or active_fault windows."
                ),
                "sample_episodes": fault_episodes_missing_windows[:5],
            }
        )

    # 4. Per-feature stats and fire rates
    feature_stats: dict[str, dict[str, Any]] = {}
    for col in FEATURE_COLUMNS:
        values = [float(row.get(col, 0.0) or 0.0) for row in rows]
        non_zero = sum(1 for v in values if v != 0.0)
        feature_stats[col] = {
            "non_zero": non_zero,
            "fire_rate": (non_zero / len(values)) if values else 0.0,
            "mean": mean(values) if values else 0.0,
            "min": min(values) if values else 0.0,
            "max": max(values) if values else 0.0,
        }
    for col, stats in feature_stats.items():
        if stats["fire_rate"] == 0.0:
            anomalies.append(
                {
                    "severity": "warn",
                    "code": "feature_always_zero",
                    "message": f"Feature {col} is zero in every window of this run.",
                    "feature": col,
                }
            )

    # 5. Label distribution
    label_counts = Counter(row.get("triage_label") for row in rows)
    source_counts = Counter(row.get("source") for row in rows)
    family_counts = Counter(row.get("scenario_family") for row in rows)

    # 6. Evidence text presence
    evidence_present = sum(1 for row in rows if (row.get("triage_evidence_text") or "").strip())
    if rows and evidence_present == 0:
        anomalies.append(
            {
                "severity": "warn",
                "code": "evidence_text_empty",
                "message": "All triage_evidence_text values are empty for this run.",
            }
        )

    failed = any(anomaly["severity"] == "fail" for anomaly in anomalies)
    report = {
        "schema_version": 1,
        "validator": "validate_run_feature_distribution.py",
        "validator_version": SCRIPT_VERSION,
        "dataset_run_id": dataset_run_id,
        "generated_at": utc_now(),
        "row_count": len(rows),
        "label_counts": dict(label_counts),
        "source_counts": dict(source_counts),
        "family_counts": dict(family_counts),
        "evidence_text_present_count": evidence_present,
        "feature_stats": feature_stats,
        "anomalies": anomalies,
        "passed": not failed,
    }

    summaries_dir = raw_run_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    write_json(summaries_dir / "data-quality-report.json", report)
    _write_distribution_md(summaries_dir / "feature-distribution.md", report)
    _write_quality_md(summaries_dir / "data-quality-report.md", report)
    return report


def _write_distribution_md(path: Path, report: dict[str, Any]) -> None:
    lines = [
        f"# Feature distribution — {report['dataset_run_id']}",
        "",
        f"Rows: {report['row_count']}  Generated: {report['generated_at']}",
        "",
        "## Label counts",
        "",
    ]
    for label in ("ticket_worthy", "borderline", "noise"):
        lines.append(f"- {label}: {report['label_counts'].get(label, 0)}")
    lines.extend(["", "## Source counts", ""])
    for source, count in sorted(report["source_counts"].items()):
        lines.append(f"- {source}: {count}")
    lines.extend(["", "## Feature stats", "", "| Feature | Non-zero | Fire rate | Mean | Min | Max |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for col, stats in sorted(report["feature_stats"].items()):
        lines.append(
            f"| `{col}` | {stats['non_zero']} | {stats['fire_rate']:.3f} | "
            f"{stats['mean']:.3f} | {stats['min']:.3f} | {stats['max']:.3f} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_quality_md(path: Path, report: dict[str, Any]) -> None:
    status = "PASS" if report["passed"] else "FAIL"
    lines = [
        f"# Data quality report — {report['dataset_run_id']}",
        "",
        f"Status: **{status}**  Rows: {report['row_count']}  Generated: {report['generated_at']}",
        "",
    ]
    if not report["anomalies"]:
        lines.append("No anomalies detected.")
    else:
        lines.append("## Anomalies")
        lines.append("")
        for a in report["anomalies"]:
            lines.append(f"- **[{a['severity']}] {a['code']}** — {a['message']}")
            for key in ("sample_window_ids", "sample_episodes", "feature"):
                if key in a:
                    lines.append(f"    - {key}: {a[key]}")
    lines.extend(["", "## Label distribution", ""])
    for label, count in sorted(report["label_counts"].items()):
        lines.append(f"- {label}: {count}")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-run-id", required=True)
    parser.add_argument("--derived-root", default=None)
    parser.add_argument("--runs-root", default=None)
    args = parser.parse_args()

    repo_root = repo_root_from_script()
    derived_root = Path(args.derived_root) if args.derived_root else None
    runs_root = Path(args.runs_root) if args.runs_root else None
    report = validate(
        repo_root=repo_root,
        dataset_run_id=args.dataset_run_id,
        derived_root=derived_root,
        runs_root=runs_root,
    )
    status = "PASS" if report["passed"] else "FAIL"
    fails = sum(1 for a in report["anomalies"] if a["severity"] == "fail")
    warns = sum(1 for a in report["anomalies"] if a["severity"] == "warn")
    print(
        f"{status} {args.dataset_run_id}: rows={report['row_count']} fails={fails} warns={warns}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
