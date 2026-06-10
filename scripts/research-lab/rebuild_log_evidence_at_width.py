"""Re-derive log-channel features and evidence text at a wider observation
window, using the 5-minute padding that Loki already preserves per window.

This implements Path A1 from the multi-width experiment plan: only LOG
features (triage_feature_log_*  + triage_feature_delta_log_*) and the free
text triage_evidence_text are re-aggregated. Metric, trace, and k8s
features carry over unchanged because the raw Prometheus / Tempo /
kubernetes exports are bounded to the original window range and the
observability stack is no longer live to re-query.

Inputs:
  --source-global-id <id>             existing global dataset (5-min)
  --target-global-id <id>             new global dataset id (10/15-min)
  --window-width-minutes <int>        5, 10, or 15
  --apply-to-window-types pre_fault_baseline active_fault
                                      window types to re-derive (default
                                      pre_fault_baseline + active_fault;
                                      recovery is left alone because
                                      its padded coverage is only ~45 s
                                      actual + 5 min each side = unstable
                                      symmetric extension)
  --max-windows <int>                 limit for smoke-testing
  --dry-run                           validate without writing
  --repo-root <path>                  default: auto-detect

Outputs (under data/derived/global/<target-global-id>/):
  global-triage-examples.jsonl        new feature values + evidence text
  triage-feature-columns.json         (copied)
  triage-split-manifest.json          (copied)
  jira-memory-corpus.jsonl            (copied)
  window-memory-matchings.jsonl       (copied -- width-independent)
  rebuild-manifest.json               diff summary

For width == 5 the script is effectively a re-derivation pass that should
reproduce the original log features to within rounding; useful as a
self-consistency check.

Example:
  python -m scripts.research-lab.rebuild_log_evidence_at_width \
      --source-global-id 2026-05-25-dataset-v5-large-global \
      --target-global-id 2026-05-25-dataset-v5-large-global-w10 \
      --window-width-minutes 10
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Allow `from triage_labels import ...` when invoked as a script in this dir
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from triage_labels import (  # type: ignore
    _safe_read_json,
    _log_severity_from_body,
    _summarize_log_body,
    _percentile,  # noqa: F401  -- kept for parity / future use
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_BASE_COLUMNS = (
    "triage_feature_log_total_count",
    "triage_feature_log_error_count",
    "triage_feature_log_warning_count",
)
LOG_DELTA_COLUMNS = tuple("triage_feature_delta_" + c.removeprefix("triage_feature_")
                          for c in LOG_BASE_COLUMNS)

ERROR_LEVELS = {"error", "err", "critical", "crit", "fatal", "panic"}
WARNING_LEVELS = {"warning", "warn"}

EVIDENCE_MAX_CHARS = 4000
EVIDENCE_MAX_LOG_LINES = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_iso8601_ns(s: str | None) -> int | None:
    """Parse an ISO-8601 string to integer nanoseconds since the unix epoch.

    Returns None on failure. Handles the +00:00 tz suffix used by the
    collection harness.
    """
    if not s:
        return None
    try:
        # Normalize "2026-05-25T13:41:55.0000000+00:00" -- truncate frac to 6 digits
        s = s.strip()
        if "." in s:
            head, tail = s.rsplit(".", 1)
            tz_pos = None
            for marker in ("+", "-", "Z"):
                idx = tail.find(marker, 1)
                if idx > 0:
                    tz_pos = idx
                    break
            if tz_pos is not None:
                frac, tz = tail[:tz_pos], tail[tz_pos:]
            else:
                frac, tz = tail, ""
            if len(frac) > 6:
                frac = frac[:6]
            s = f"{head}.{frac}{tz}"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except (ValueError, AttributeError):
        return None


def compute_target_range_ns(
    win_start_ns: int,
    win_end_ns: int,
    padded_start_ns: int,
    padded_end_ns: int,
    target_width_sec: int,
) -> tuple[int, int]:
    """Return [new_start_ns, new_end_ns] that is symmetric around the
    original window's midpoint with the requested target width, clamped to
    the available padded range.

    If the requested width exceeds the padded coverage, the result is the
    full padded range (no extension beyond what was queried).
    """
    midpoint = (win_start_ns + win_end_ns) // 2
    half_width_ns = (target_width_sec * 1_000_000_000) // 2
    new_start = midpoint - half_width_ns
    new_end = midpoint + half_width_ns
    # Clamp symmetrically: if either side blows out, shift to keep within bounds.
    if new_start < padded_start_ns:
        shift = padded_start_ns - new_start
        new_start += shift
        new_end = min(new_end + shift, padded_end_ns)
    if new_end > padded_end_ns:
        shift = new_end - padded_end_ns
        new_end -= shift
        new_start = max(new_start - shift, padded_start_ns)
    new_start = max(new_start, padded_start_ns)
    new_end = min(new_end, padded_end_ns)
    return new_start, new_end


def iter_padded_log_lines(
    loki_raw: dict,
    start_ns: int,
    end_ns: int,
) -> Iterable[tuple[str, str, dict]]:
    """Yield (level, line_text, stream_labels) tuples for every Loki entry
    whose timestamp falls within [start_ns, end_ns).

    Walks BOTH service_context (per-service padded query) and
    namespace_context (namespace-wide padded query) -- but to avoid
    double-counting we prefer service_context when present, and only fall
    back to namespace_context if service_context is empty.
    """
    sources = []
    svc_ctx = (loki_raw.get("service_context") or {}).get("response", {}) \
        .get("data", {}).get("result") or []
    if svc_ctx:
        sources.append(svc_ctx)
    else:
        ns_ctx = (loki_raw.get("namespace_context") or {}).get("response", {}) \
            .get("data", {}).get("result") or []
        if ns_ctx:
            sources.append(ns_ctx)

    for stream_list in sources:
        for stream in stream_list:
            labels = stream.get("stream") or {}
            for entry in stream.get("values") or []:
                try:
                    ts_ns = int(entry[0])
                    line = entry[1]
                except (IndexError, TypeError, ValueError):
                    continue
                if ts_ns < start_ns or ts_ns >= end_ns:
                    continue
                yield labels, line


def derive_log_counts_at_range(
    loki_raw: dict,
    start_ns: int,
    end_ns: int,
) -> tuple[int, int, int]:
    """Re-compute (log_total, log_error, log_warning) over the given range
    using the same severity-classification rules as triage_labels.numeric_features_from_raw.
    """
    log_total = log_error = log_warning = 0
    for labels, line in iter_padded_log_lines(loki_raw, start_ns, end_ns):
        stream_level = (
            labels.get("detected_level")
            or labels.get("severity")
            or labels.get("level")
            or ""
        ).strip().lower()
        log_total += 1
        body_level = _log_severity_from_body(line) or stream_level
        if body_level in ERROR_LEVELS:
            log_error += 1
        elif body_level in WARNING_LEVELS:
            log_warning += 1
    return log_total, log_error, log_warning


def build_evidence_log_section(
    loki_raw: dict,
    start_ns: int,
    end_ns: int,
) -> list[str]:
    """Re-build the LOG-EVENTS section of triage_evidence_text over the
    target range, using the same shape as triage_labels.evidence_text_from_raw.
    """
    log_lines: list[str] = []
    for _labels, line in iter_padded_log_lines(loki_raw, start_ns, end_ns):
        level = _log_severity_from_body(line)
        try:
            body = json.loads(line)
        except json.JSONDecodeError:
            body = {}
        msg_text = (
            str(body.get("message") or body.get("Message") or body.get("msg") or "")
            .lower()
        )
        is_dep_error = "dep_error" in msg_text or body.get("dep")
        is_severity_match = level is not None and level in (ERROR_LEVELS | WARNING_LEVELS)
        if not (is_severity_match or is_dep_error):
            continue
        summary = _summarize_log_body(body) if body else str(line)[:200]
        if not summary:
            continue
        level_tag = (level or "info")[:5]
        log_lines.append(f"[{level_tag}] {summary}")
        if len(log_lines) >= EVIDENCE_MAX_LOG_LINES:
            break
    return log_lines


def splice_evidence_text(
    original_text: str,
    new_log_lines: list[str],
) -> str:
    """Replace the LOG-EVENTS section of the original evidence text with the
    re-derived lines, leaving SERVICE / TRACES / K8S-EVENTS intact.

    The original text shape (from evidence_text_from_raw) is:
        SERVICE <name>
        LOG-EVENTS                  <-- optional
        [err] ...                   <-- 0..20 lines, then non-log section
        TRACES ...                  <-- always present after the LOG block
        ...
        K8S-EVENTS                  <-- optional
        ...
    """
    lines = original_text.split("\n")
    new_lines: list[str] = []
    i = 0
    spliced = False
    while i < len(lines):
        line = lines[i]
        if line == "LOG-EVENTS":
            spliced = True
            if new_log_lines:
                new_lines.append("LOG-EVENTS")
                new_lines.extend(new_log_lines)
            # skip the original LOG-EVENTS body until we hit TRACES / K8S-EVENTS
            i += 1
            while i < len(lines) and not (
                lines[i].startswith("TRACES")
                or lines[i] == "K8S-EVENTS"
                or lines[i].startswith("SERVICE")
            ):
                i += 1
            continue
        new_lines.append(line)
        i += 1
    if not spliced and new_log_lines:
        # original text had no LOG-EVENTS section; insert one right after SERVICE
        out: list[str] = []
        inserted = False
        for ln in new_lines:
            out.append(ln)
            if not inserted and ln.startswith("SERVICE"):
                out.append("LOG-EVENTS")
                out.extend(new_log_lines)
                inserted = True
        if not inserted:
            # no SERVICE either; prepend
            out = ["LOG-EVENTS", *new_log_lines, *new_lines]
        new_lines = out
    text = "\n".join(new_lines)
    if len(text) > EVIDENCE_MAX_CHARS:
        text = text[:EVIDENCE_MAX_CHARS - 3] + "..."
    return text


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def find_loki_raw(repo_root: Path, dataset_run_id: str, window_id: str) -> dict | None:
    """Locate raw/loki/<window_id>.json under the named run dir."""
    p = repo_root / "data" / "runs" / dataset_run_id / "raw" / "loki" / f"{window_id}.json"
    return _safe_read_json(p)


def rebuild_one_row(
    repo_root: Path,
    row: dict,
    target_width_sec: int,
    apply_to_window_types: set[str],
    stats: dict[str, Any],
) -> dict:
    """Return a new row with log features + evidence text re-derived at the
    target width (where applicable). Other fields carry over unchanged.
    """
    new_row = dict(row)  # shallow copy
    window_type = str(row.get("window_type") or "")
    if window_type not in apply_to_window_types:
        stats["unchanged_by_type"] += 1
        return new_row

    dataset_run_id = str(row.get("dataset_run_id") or "")
    window_id = str(row.get("window_id") or "")
    if not (dataset_run_id and window_id):
        stats["unchanged_missing_ids"] += 1
        return new_row

    loki_raw = find_loki_raw(repo_root, dataset_run_id, window_id)
    if not loki_raw:
        stats["unchanged_no_loki"] += 1
        return new_row

    win_meta = loki_raw.get("window") or {}
    win_start_ns = parse_iso8601_ns(win_meta.get("start_time"))
    win_end_ns = parse_iso8601_ns(win_meta.get("end_time"))
    padded_start_ns = parse_iso8601_ns(win_meta.get("padded_start_time"))
    padded_end_ns = parse_iso8601_ns(win_meta.get("padded_end_time"))
    if None in (win_start_ns, win_end_ns, padded_start_ns, padded_end_ns):
        stats["unchanged_no_window_meta"] += 1
        return new_row

    new_start_ns, new_end_ns = compute_target_range_ns(
        win_start_ns, win_end_ns, padded_start_ns, padded_end_ns, target_width_sec,
    )
    achieved_width_sec = (new_end_ns - new_start_ns) / 1_000_000_000

    total, errs, warns = derive_log_counts_at_range(loki_raw, new_start_ns, new_end_ns)

    new_row["triage_feature_log_total_count"] = float(total)
    new_row["triage_feature_log_error_count"] = float(errs)
    new_row["triage_feature_log_warning_count"] = float(warns)

    new_log_lines = build_evidence_log_section(loki_raw, new_start_ns, new_end_ns)
    original_text = str(row.get("triage_evidence_text") or "")
    new_row["triage_evidence_text"] = splice_evidence_text(original_text, new_log_lines)

    stats["rebuilt"] += 1
    stats["achieved_widths_sec"].append(round(achieved_width_sec, 1))
    return new_row


def recompute_log_deltas(rows: list[dict]) -> None:
    """In-place: recompute triage_feature_delta_log_* against same-episode
    same-service pre_fault_baseline rows that were just rebuilt.

    Matches the logic in build_triage_dataset.py:118-154 except we only
    touch the LOG delta columns; trace / metric / k8s deltas carry over.
    """
    baselines: dict[tuple[str, str], dict] = {}
    for r in rows:
        if str(r.get("window_type")) == "pre_fault_baseline":
            key = (str(r.get("incident_episode_id") or ""), str(r.get("service_name") or ""))
            baselines[key] = r

    n_updated = 0
    for r in rows:
        wt = str(r.get("window_type") or "")
        key = (str(r.get("incident_episode_id") or ""), str(r.get("service_name") or ""))
        baseline = baselines.get(key)
        for base_col, delta_col in zip(LOG_BASE_COLUMNS, LOG_DELTA_COLUMNS):
            if baseline is None or wt == "pre_fault_baseline":
                r[delta_col] = 0.0
            else:
                r[delta_col] = float(r.get(base_col, 0.0)) - float(baseline.get(base_col, 0.0))
                n_updated += 1
    return n_updated


def stream_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False))
            f.write("\n")
            n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-global-id", required=True)
    parser.add_argument("--target-global-id", required=True)
    parser.add_argument("--window-width-minutes", type=int, required=True,
                        choices=[5, 10, 15])
    parser.add_argument(
        "--apply-to-window-types",
        nargs="*",
        default=["pre_fault_baseline", "active_fault"],
        help="Window types whose log features are re-derived (default: pre_fault_baseline active_fault).",
    )
    parser.add_argument("--max-windows", type=int, default=None,
                        help="Smoke-test limit on number of source rows.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root \
        else Path(__file__).resolve().parents[2]

    src_dir = repo_root / "data" / "derived" / "global" / args.source_global_id
    tgt_dir = repo_root / "data" / "derived" / "global" / args.target_global_id

    src_examples = src_dir / "global-triage-examples.jsonl"
    if not src_examples.exists():
        print(f"ERROR: source not found: {src_examples}", file=sys.stderr)
        return 2

    apply_types = set(args.apply_to_window_types)
    target_sec = args.window_width_minutes * 60

    print(f"Source:  {src_dir}")
    print(f"Target:  {tgt_dir}")
    print(f"Width:   {args.window_width_minutes} min ({target_sec} s)")
    print(f"Apply to: {sorted(apply_types)}")
    if args.dry_run:
        print("(dry run — no files will be written)")

    stats: dict[str, Any] = {
        "rebuilt": 0,
        "unchanged_by_type": 0,
        "unchanged_missing_ids": 0,
        "unchanged_no_loki": 0,
        "unchanged_no_window_meta": 0,
        "achieved_widths_sec": [],
    }

    rebuilt_rows: list[dict] = []
    n_read = 0
    for row in stream_jsonl(src_examples):
        if args.max_windows and n_read >= args.max_windows:
            break
        rebuilt_rows.append(rebuild_one_row(repo_root, row, target_sec, apply_types, stats))
        n_read += 1
        if n_read % 500 == 0:
            print(f"  ... processed {n_read} rows")

    n_delta_updated = recompute_log_deltas(rebuilt_rows)

    print()
    print(f"Read:    {n_read} rows")
    print(f"Rebuilt log features: {stats['rebuilt']}")
    print(f"Unchanged (by window-type filter): {stats['unchanged_by_type']}")
    print(f"Unchanged (no Loki raw):           {stats['unchanged_no_loki']}")
    print(f"Unchanged (no window meta):        {stats['unchanged_no_window_meta']}")
    print(f"Unchanged (missing ids):           {stats['unchanged_missing_ids']}")
    print(f"Log-delta cells updated:           {n_delta_updated}")
    if stats["achieved_widths_sec"]:
        ws = stats["achieved_widths_sec"]
        ws_min = min(ws)
        ws_max = max(ws)
        ws_mean = sum(ws) / len(ws)
        print(f"Achieved widths (sec): min={ws_min:.1f} max={ws_max:.1f} mean={ws_mean:.1f}")
        # bucket-counts at target
        n_at_target = sum(1 for w in ws if abs(w - target_sec) < 1.0)
        n_clamped = len(ws) - n_at_target
        print(f"  at target width: {n_at_target}   clamped: {n_clamped}")

    if args.dry_run:
        return 0

    # Write new global-triage-examples.jsonl
    tgt_dir.mkdir(parents=True, exist_ok=True)
    tgt_examples = tgt_dir / "global-triage-examples.jsonl"
    n_written = write_jsonl(tgt_examples, rebuilt_rows)
    print(f"Wrote {n_written} rows -> {tgt_examples}")

    # Copy width-independent sidecars
    sidecars = [
        "triage-feature-columns.json",
        "triage-split-manifest.json",
        "triage-split-manifest-v2-resplit.json",
        "jira-memory-corpus.jsonl",
        "window-memory-matchings.jsonl",
        "family-coverage.json",
        "leakage-canary-summary.json",
        "dataset-metadata.json",
    ]
    copied = []
    for name in sidecars:
        src = src_dir / name
        if src.exists():
            dst = tgt_dir / name
            dst.write_bytes(src.read_bytes())
            copied.append(name)
    print(f"Copied {len(copied)} sidecar files: {', '.join(copied)}")

    # Write rebuild manifest
    manifest = {
        "schema_version": 1,
        "builder": "rebuild_log_evidence_at_width.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_global_id": args.source_global_id,
        "target_global_id": args.target_global_id,
        "target_width_minutes": args.window_width_minutes,
        "target_width_seconds": target_sec,
        "apply_to_window_types": sorted(apply_types),
        "stats": {k: v for k, v in stats.items() if k != "achieved_widths_sec"},
        "n_read": n_read,
        "n_written": n_written,
        "n_log_delta_cells_updated": n_delta_updated,
        "achieved_width_summary": (
            {
                "min_sec": min(stats["achieved_widths_sec"]),
                "max_sec": max(stats["achieved_widths_sec"]),
                "mean_sec": sum(stats["achieved_widths_sec"]) / len(stats["achieved_widths_sec"]),
                "n_at_target": sum(1 for w in stats["achieved_widths_sec"] if abs(w - target_sec) < 1.0),
                "n_clamped": len(stats["achieved_widths_sec"]) - sum(
                    1 for w in stats["achieved_widths_sec"] if abs(w - target_sec) < 1.0
                ),
            }
            if stats["achieved_widths_sec"] else None
        ),
    }
    (tgt_dir / "rebuild-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Wrote rebuild manifest -> {tgt_dir / 'rebuild-manifest.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
