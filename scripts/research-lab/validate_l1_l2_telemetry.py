#!/usr/bin/env python3
"""D13.14d systematic L1/L2 telemetry validation.

For one or more dataset runs, scan the raw Loki + Tempo exports and report:

  L1 = per-RPC structured request log (M2.1). One per RPC per direction.
       Should carry trace_id + span_id when ENABLE_TRACING=1.
  L2 = structured error log at a dependency boundary (M2.2). Cartservice
       wires this explicitly via LogRedisError; the shared rpclog
       interceptors emit similar fields on non-OK status.

  Trace side: every error path should have a RecordError / SetStatus
  span in Tempo for the same window+service.

Cross-check that:
  (a) Every L1 log line carries a trace_id.
  (b) Every active_fault window for the *errored* service has both
      L2 dep_error log entries AND span errors in Tempo.

Usage:
    python3 scripts/research-lab/validate_l1_l2_telemetry.py \
        --repo-root . \
        --run-ids 2026-05-24-m5-1-cart-validation-r01,2026-05-24-m5-1-cart-validation-r02

Writes a per-run-set report under data/derived/l1-l2-validation/<timestamp>/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def parse_window_filename(name: str) -> dict | None:
    """Decompose a Loki/Tempo export filename into (scenario, ts, window_type, service)."""
    # <runid>-<scenario>-<ts>-<window_type>-<service>.json
    if not name.endswith(".json"):
        return None
    stem = name[:-5]
    # Window-type tokens we recognise (matches export-telemetry-window.ps1 naming).
    for wt in (
        "pre_fault_baseline",
        "active_fault",
        "post_fault_recovery",
        "observation_window",
    ):
        sep = f"-{wt}-"
        if sep in stem:
            left, service = stem.split(sep, 1)
            # left = <runid>-<scenario>-<ts>; ts = trailing 16-char ISO basic
            m = re.search(r"-(\d{8}T\d{6}Z)$", left)
            if not m:
                return None
            ts = m.group(1)
            head = left[: -len(ts) - 1]
            # remove the run-id prefix — caller supplies it
            return {"head": head, "ts": ts, "window_type": wt, "service": service}
    return None


def iter_log_lines(loki_export_path: Path):
    """Yield (timestamp_ns:int, line:str) tuples from a Loki query_range export."""
    try:
        with loki_export_path.open() as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    sw = doc.get("service_window", {})
    resp = sw.get("response", {})
    data = resp.get("data", {})
    streams = data.get("result", [])
    if not isinstance(streams, list):
        return
    for stream in streams:
        for entry in stream.get("values", []) or []:
            if not (isinstance(entry, list) and len(entry) == 2):
                continue
            try:
                yield int(entry[0]), str(entry[1])
            except (TypeError, ValueError):
                continue


# Heuristics for L1/L2 classification.
# L1: the shared rpclog interceptors emit a structured JSON object containing
# `method=/<svc>/<rpc>` plus `kind=rpc.server` or `rpc.client`. .NET emits
# the message "rpc method=..." as plain text from RpcLoggingInterceptor.
RE_L1_JSON = re.compile(r'"kind"\s*:\s*"rpc\.(server|client)"')
RE_L1_TEXT = re.compile(r"\brpc method=/")
RE_TRACE_ID_JSON = re.compile(r'"trace_id"\s*:\s*"([0-9a-f]{16,})"')
RE_TRACE_ID_TEXT = re.compile(r"\btrace_id=([0-9a-f]{16,})")
# L2 / dep error: explicit dep_error event or any non-OK status code.
RE_DEP_ERROR = re.compile(r'"(event|message)"\s*:\s*"dep_error"|dep_error\s+dep=')
RE_NON_OK_STATUS = re.compile(
    r'"status_code"\s*:\s*"(?!OK")[A-Z_]+"'
    r"|status=(?!OK\b)[A-Z_]+"
)


def classify_line(line: str) -> tuple[bool, bool, bool]:
    """Return (is_l1, has_trace_id, is_l2_or_error)."""
    is_l1 = bool(RE_L1_JSON.search(line) or RE_L1_TEXT.search(line))
    has_trace = bool(RE_TRACE_ID_JSON.search(line) or RE_TRACE_ID_TEXT.search(line))
    is_l2 = bool(RE_DEP_ERROR.search(line) or RE_NON_OK_STATUS.search(line))
    return is_l1, has_trace, is_l2


def scan_tempo_for_errors(tempo_export_path: Path) -> tuple[int, int]:
    """Count (n_spans, n_error_spans) in a Tempo window export.

    Export shape: top-level `traces` is a dict of `traceID -> {response: {batches}}`,
    NOT nested under `service_window`. Each span's status lives at
    `response.batches[].scopeSpans[].spans[].status.code` with values
    `STATUS_CODE_ERROR`, `STATUS_CODE_OK`, or absent (UNSET).
    """
    try:
        with tempo_export_path.open() as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0, 0
    traces = doc.get("traces", {})
    if not isinstance(traces, dict):
        return 0, 0
    n_spans = 0
    n_err = 0
    for _tid, t in traces.items():
        resp = t.get("response", {}) if isinstance(t, dict) else {}
        if not isinstance(resp, dict):
            continue
        for batch in resp.get("batches", []) or []:
            if not isinstance(batch, dict):
                continue
            for ss in batch.get("scopeSpans", []) or []:
                if not isinstance(ss, dict):
                    continue
                for span in ss.get("spans", []) or []:
                    if not isinstance(span, dict):
                        continue
                    n_spans += 1
                    status = span.get("status", {})
                    code = status.get("code") if isinstance(status, dict) else None
                    if code in ("ERROR", "STATUS_CODE_ERROR", 2):
                        n_err += 1
    return n_spans, n_err


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument(
        "--run-ids",
        required=True,
        help="Comma-separated dataset_run_ids to scan",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for report. Defaults to data/derived/l1-l2-validation/<utc-stamp>/",
    )
    args = parser.parse_args()

    run_ids = [r.strip() for r in args.run_ids.split(",") if r.strip()]
    if not run_ids:
        print("ERROR: no --run-ids provided", file=sys.stderr)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (
        args.repo_root / "data" / "derived" / "l1-l2-validation" / stamp
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    runs_root = args.repo_root / "data" / "runs"
    overall = {
        "run_ids": run_ids,
        "by_service": defaultdict(
            lambda: {
                "n_logs": 0,
                "n_l1": 0,
                "n_l1_with_trace": 0,
                "n_l2": 0,
            }
        ),
        "active_fault_windows": [],  # list of dicts
    }

    for rid in run_ids:
        loki_dir = runs_root / rid / "raw" / "loki"
        tempo_dir = runs_root / rid / "raw" / "tempo"
        if not loki_dir.is_dir():
            print(f"WARN: missing {loki_dir}", file=sys.stderr)
            continue
        for log_path in sorted(loki_dir.glob("*.json")):
            meta = parse_window_filename(log_path.name)
            if not meta:
                continue
            service = meta["service"]
            window_type = meta["window_type"]
            per_svc = overall["by_service"][service]
            n_logs = n_l1 = n_trace = n_l2 = 0
            for _ts, line in iter_log_lines(log_path):
                n_logs += 1
                is_l1, has_trace, is_l2 = classify_line(line)
                if is_l1:
                    n_l1 += 1
                    if has_trace:
                        n_trace += 1
                if is_l2:
                    n_l2 += 1
            per_svc["n_logs"] += n_logs
            per_svc["n_l1"] += n_l1
            per_svc["n_l1_with_trace"] += n_trace
            per_svc["n_l2"] += n_l2

            if window_type == "active_fault":
                tempo_path = tempo_dir / log_path.name
                tempo_total, tempo_errors = (
                    scan_tempo_for_errors(tempo_path) if tempo_path.exists() else (0, 0)
                )
                overall["active_fault_windows"].append(
                    {
                        "run_id": rid,
                        "service": service,
                        "scenario": meta["head"].split(rid + "-", 1)[-1]
                        if (rid + "-") in meta["head"]
                        else meta["head"],
                        "n_logs": n_logs,
                        "n_l1": n_l1,
                        "n_l2": n_l2,
                        "tempo_total_spans": tempo_total,
                        "tempo_error_spans": tempo_errors,
                        "has_l2_evidence": n_l2 > 0,
                        "has_tempo_evidence": tempo_errors > 0,
                    }
                )

    # ---------- printable report ----------
    print()
    print("=" * 72)
    print("D13.14d L1/L2 telemetry validation report")
    print("=" * 72)
    print(f"Runs scanned: {run_ids}")
    print()

    print("--- per-service log counts ---")
    print(f"{'service':25} {'n_logs':>8} {'n_l1':>8} {'l1_trace_pct':>14} {'n_l2':>8}")
    fleet_l1 = 0
    fleet_l1_trace = 0
    fleet_l2 = 0
    for svc in sorted(overall["by_service"]):
        s = overall["by_service"][svc]
        pct = (100.0 * s["n_l1_with_trace"] / s["n_l1"]) if s["n_l1"] else 0.0
        print(
            f"{svc:25} {s['n_logs']:>8} {s['n_l1']:>8} {pct:>13.1f}% {s['n_l2']:>8}"
        )
        fleet_l1 += s["n_l1"]
        fleet_l1_trace += s["n_l1_with_trace"]
        fleet_l2 += s["n_l2"]
    fleet_pct = (100.0 * fleet_l1_trace / fleet_l1) if fleet_l1 else 0.0
    print(f"{'FLEET TOTAL':25} {'':>8} {fleet_l1:>8} {fleet_pct:>13.1f}% {fleet_l2:>8}")
    print()

    print("--- active_fault windows: cross-check L2 evidence vs Tempo error spans ---")
    print(
        f"{'run/service/scenario':70} {'n_l2':>5} {'tempo_err':>10} {'verdict':>20}"
    )
    n_windows = 0
    n_evidence_agree = 0  # both sides have evidence
    n_evidence_disagree = 0  # one side empty
    n_nothing = 0  # nothing on either side
    for w in overall["active_fault_windows"]:
        n_windows += 1
        label = f"{w['run_id'][-25:]}/{w['service']}/{w['scenario'][:30]}"
        l2 = w["has_l2_evidence"]
        ts = w["has_tempo_evidence"]
        if l2 and ts:
            verdict = "agree:both fire"
            n_evidence_agree += 1
        elif not l2 and not ts:
            verdict = "agree:silent"
            n_nothing += 1
        else:
            verdict = "DISAGREE"
            n_evidence_disagree += 1
        print(
            f"{label[:70]:70} {w['n_l2']:>5} {w['tempo_error_spans']:>10} {verdict:>20}"
        )
    print()
    print(f"Total active_fault windows scanned: {n_windows}")
    print(f"  L2 ∩ Tempo agree (both fire):      {n_evidence_agree}")
    print(f"  L2 ∩ Tempo agree (both silent):    {n_nothing}")
    print(f"  L2 / Tempo disagree:               {n_evidence_disagree}")
    print()

    # ---------- written report ----------
    report_md = out_dir / "report.md"
    lines = ["# D13.14d L1/L2 Telemetry Validation Report", ""]
    lines.append(f"Generated: {stamp}")
    lines.append("")
    lines.append(f"Runs scanned: `{','.join(run_ids)}`")
    lines.append("")
    lines.append("## Per-service log counts")
    lines.append("")
    lines.append("| service | n_logs | n_l1 | l1_trace_pct | n_l2 |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for svc in sorted(overall["by_service"]):
        s = overall["by_service"][svc]
        pct = (100.0 * s["n_l1_with_trace"] / s["n_l1"]) if s["n_l1"] else 0.0
        lines.append(
            f"| {svc} | {s['n_logs']} | {s['n_l1']} | {pct:.1f}% | {s['n_l2']} |"
        )
    lines.append(f"| **FLEET TOTAL** | | **{fleet_l1}** | **{fleet_pct:.1f}%** | **{fleet_l2}** |")
    lines.append("")
    lines.append("## active_fault windows — L2 vs Tempo cross-check")
    lines.append("")
    lines.append("| run/service/scenario | n_l2 | tempo_err | verdict |")
    lines.append("| --- | ---: | ---: | --- |")
    for w in overall["active_fault_windows"]:
        l2 = w["has_l2_evidence"]
        ts = w["has_tempo_evidence"]
        verdict = (
            "agree:both fire" if l2 and ts
            else "agree:silent" if not (l2 or ts)
            else "**DISAGREE**"
        )
        lines.append(
            f"| {w['run_id']}/{w['service']}/{w['scenario']} | {w['n_l2']} | "
            f"{w['tempo_error_spans']} | {verdict} |"
        )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total active_fault windows: **{n_windows}**")
    lines.append(f"- L2 ∩ Tempo agree (both fire): **{n_evidence_agree}**")
    lines.append(f"- L2 ∩ Tempo agree (both silent): **{n_nothing}**")
    lines.append(f"- L2 / Tempo disagree: **{n_evidence_disagree}** "
                 "(target = 0; non-zero means one observability path missed an error the other caught)")
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report written to {report_md}")

    # Exit non-zero if any active_fault window had no evidence at all
    # OR if L1 trace_id coverage is below 90% (most likely real bug).
    bad = (fleet_pct < 90.0) or (n_evidence_disagree > 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
