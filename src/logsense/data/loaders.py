"""Read raw Loki JSON exports off disk into LogLine lists.

File layout: data/runs/<dataset_run_id>/raw/loki/<window_id>.json
Each file contains streams of (timestamp_ns, body) pairs grouped by Loki
labels (app, container, pod, detected_level, namespace, ...).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .schema import LogLine, WindowLogs


# Severity inference (matches scripts/research-lab/triage_labels.py _log_severity_from_body)

_JSON_SEVERITY_KEYS = ("severity", "level", "log.level", "loglevel", "@level", "status")
_PREFIX_SEVERITY = (
    ("error", "error"),
    ("err ", "error"),
    ("err:", "error"),
    ("warn", "warning"),
    ("info", "info"),
    ("debug", "debug"),
    ("fatal", "critical"),
    ("crit", "critical"),
    ("trace", "debug"),
)
_INLINE_LEVEL_RE = re.compile(r"\b(ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b")
# .NET-style logger output: "fail: Foo[0]", "warn: Bar[1]", etc.
_LOGGER_TAG_RE = re.compile(r"^\s*(fail|crit|warn|error|info|dbug|trce):\s")
# Stack-trace / exception context heuristics
_STACK_FRAME_RE = re.compile(r"^\s*(?:at\s+\w|---\s*End of (?:inner )?exception)", re.IGNORECASE)
_EXCEPTION_HINT_RE = re.compile(
    r"\b(?:Exception|Error|Throwable|RedisConnectionException|TimeoutException|"
    r"NullReferenceException|raised|inner exception|stack trace|caused by)\b",
    re.IGNORECASE,
)
_LOGGER_TAG_TO_SEV = {
    "fail": "error",
    "crit": "critical",
    "error": "error",
    "warn": "warning",
    "info": "info",
    "dbug": "debug",
    "trce": "debug",
}


def _severity_from_body(body: str, fallback: str | None = None) -> str:
    s = (body or "").strip()
    if not s:
        return (fallback or "unknown").lower()
    # JSON body: pick the canonical severity field
    if s[0] == "{":
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for key in _JSON_SEVERITY_KEYS:
                value = parsed.get(key)
                if isinstance(value, str) and value:
                    return value.strip().lower()
    # .NET-style "fail: Type[N]" tag
    m = _LOGGER_TAG_RE.match(s)
    if m:
        return _LOGGER_TAG_TO_SEV[m.group(1).lower()]
    # Stack frame -> almost always error context
    if _STACK_FRAME_RE.match(s):
        return "error"
    # Leading textual marker
    low = s.lower()
    for prefix, sev in _PREFIX_SEVERITY:
        if low.startswith(prefix):
            return sev
    # Exception keywords anywhere
    if _EXCEPTION_HINT_RE.search(s):
        return "error"
    # Inline marker anywhere in line (case-insensitive)
    m = _INLINE_LEVEL_RE.search(s)
    if m:
        token = m.group(1).lower()
        if token.startswith("warn"):
            return "warning"
        return token
    if fallback:
        return fallback.lower()
    return "unknown"


def find_loki_file(window_id: str, runs_root: Path) -> Path | None:
    """Resolve the raw Loki JSON path for a given window_id.

    window_id starts with <dataset_run_id> so we can find the run root.
    The file under runs/<run>/raw/loki/ is named "<window_id>.json".
    """
    parts = window_id.split("-")
    # dataset_run_id is everything before the scenario_id - heuristic: stop
    # at the segment that introduces a scenario like "<service>-...". To
    # avoid getting clever we just scan candidate prefixes.
    candidates = []
    for end in range(len(parts), 1, -1):
        prefix = "-".join(parts[:end])
        run_dir = runs_root / prefix
        if (run_dir / "raw" / "loki").is_dir():
            candidates.append(run_dir)
            break
    if not candidates:
        return None
    target = candidates[0] / "raw" / "loki" / f"{window_id}.json"
    return target if target.is_file() else None


def _streams_from_response(blob: dict) -> list[dict]:
    if not isinstance(blob, dict):
        return []
    resp = blob.get("response") or {}
    data = resp.get("data") or {}
    result = data.get("result") or []
    return [s for s in result if isinstance(s, dict)]


def _stream_to_lines(stream: dict, target_service: str | None) -> list[LogLine]:
    labels = stream.get("stream") or {}
    service = labels.get("service_name") or labels.get("app") or ""
    container = labels.get("container")
    pod = labels.get("pod")
    detected_level = labels.get("detected_level")
    out: list[LogLine] = []
    for entry in stream.get("values") or []:
        if not (isinstance(entry, list) and len(entry) >= 2):
            continue
        try:
            ts = int(entry[0])
        except (TypeError, ValueError):
            continue
        body = str(entry[1] or "")
        severity = _severity_from_body(body, fallback=detected_level)
        if target_service and service and service != target_service:
            continue
        out.append(
            LogLine(
                timestamp_ns=ts,
                body=body,
                severity=severity,
                service=service,
                container=container,
                pod=pod,
                detected_level=detected_level,
            )
        )
    return out


def load_window_logs(
    window_id: str,
    *,
    dataset_run_id: str,
    incident_episode_id: str,
    service_name: str,
    window_type: str,
    start_time: str,
    end_time: str,
    runs_root: Path,
) -> WindowLogs | None:
    """Load and parse the raw Loki JSON for one window. Returns None when
    the file is missing (e.g. partial corpus, or non-Loki dataset)."""

    path = runs_root / dataset_run_id / "raw" / "loki" / f"{window_id}.json"
    if not path.is_file():
        return None

    with path.open("r", encoding="utf-8-sig") as fh:
        blob = json.load(fh)

    service_lines: list[LogLine] = []
    for stream in _streams_from_response(blob.get("service_window") or {}):
        service_lines.extend(_stream_to_lines(stream, target_service=service_name))

    namespace_lines: list[LogLine] = []
    for stream in _streams_from_response(blob.get("namespace_context") or {}):
        namespace_lines.extend(_stream_to_lines(stream, target_service=None))

    return WindowLogs(
        window_id=window_id,
        dataset_run_id=dataset_run_id,
        incident_episode_id=incident_episode_id,
        service_name=service_name,
        window_type=window_type,
        start_time=start_time,
        end_time=end_time,
        lines=service_lines,
        namespace_lines=namespace_lines,
        fetched_at=str(blob.get("fetched_at", "")),
    )
