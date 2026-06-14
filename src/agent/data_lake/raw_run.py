"""RawRunDataLake — read-only access to raw per-run telemetry files.

Backs the v1 ReAct EvidenceRequestSkills. Each method maps to one
tool name (per `DOCS/docs8/IMPLEMENTATION-PLAN.md` §5.2 + §5.3).

v1 scope:
  - `get_pod_events(window_id)` — k8s events from
    `data/runs/<run_id>/raw/kubernetes/<window_id>.json`. Parses out the
    Event objects' (timestamp, reason, message, type, pod) for the
    requested window's service.

Deferred to v2 (Phase 2 follow-ups):
  - `get_extended_trace_window(...)` — Tempo span aggregate
  - `get_pod_metrics(...)` — Prometheus snapshots
  - `get_similar_incident_window(...)` — peer-incident retrieval

Per the charter §14, `get_debug_logs` cannot ship — collection was
info-only and we don't re-collect. The tool is documented as a v3
data-collection investment.

Caching: each tool result is cached at
`data/tool_cache/<tool_name>/<args_hash>.json`. Re-fetches hit cache
unless the file mtime is newer than the cache's. Cache invalidates
on `RawRunDataLake.bump_cache_version()` or by deleting the dir.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


# -----------------------------------------------------------------------------
# Run discovery — window_id encodes the run_id as its leading segment
# -----------------------------------------------------------------------------


def _run_id_from_window_id(window_id: str) -> str:
    """Extract the run_id (everything up to the scenario chunk).

    OB window IDs look like:
        2026-05-25-dataset-v5-large-compact-a-r01-cart-redis-degradation-critical-20260525T134155Z-active_fault-cartservice
    The run_id is the prefix matching `<global-prefix>-<scenario-bag>-<r##>`:
        2026-05-25-dataset-v5-large-compact-a-r01
    OTel:
        2026-06-09-otel-demo-v1-kafka-r01

    Heuristic: the run_id ends at the first `-r\\d+` segment.
    """
    import re
    m = re.match(r"^(.*?-r\d+)-", window_id)
    return m.group(1) if m else window_id


# -----------------------------------------------------------------------------
# K8s event extraction
# -----------------------------------------------------------------------------


def _extract_k8s_events(raw: dict) -> list[dict[str, Any]]:
    """Pull a clean list of (timestamp, type, reason, message, pod, kind)
    tuples from a k8s events.json file's `events.response.items`."""
    events_block = (raw or {}).get("events") or {}
    response = (events_block or {}).get("response") or {}
    items = (response or {}).get("items") or []
    if not isinstance(items, list):
        return []

    out: list[dict[str, Any]] = []
    for ev in items:
        if not isinstance(ev, dict):
            continue
        inv = ev.get("involvedObject") or {}
        out.append({
            "timestamp": ev.get("lastTimestamp") or ev.get("firstTimestamp"),
            "type": ev.get("type"),               # "Normal" | "Warning"
            "reason": ev.get("reason"),           # "Pulled" | "FailedScheduling" | ...
            "message": ev.get("message"),
            "pod": inv.get("name"),
            "kind": inv.get("kind"),              # "Pod" | "Deployment" | ...
            "count": ev.get("count", 1),
        })
    return out


# -----------------------------------------------------------------------------
# Data lake
# -----------------------------------------------------------------------------


class RawRunDataLake:
    """Read raw collection runs from disk; serve tool requests.

    Construct with a `runs_root` Path. Methods accept the same args the
    corresponding `EvidenceRequestSkill` would pass. Returned values are
    plain dicts/lists for JSON-friendliness.

    Caching is content-addressed at `cache_root/<tool>/<args_hash>.json`.
    """

    def __init__(
        self,
        runs_root: Path,
        *,
        cache_root: Path | None = None,
    ) -> None:
        self.runs_root = Path(runs_root)
        self.cache_root = (
            Path(cache_root) if cache_root else None
        )
        # Module version — bump to invalidate all cached results.
        self.cache_version = "v1"

    # ------------------------------------------------------------------ caching

    def _cache_path(self, tool_name: str, args: dict[str, Any]) -> Path | None:
        if not self.cache_root:
            return None
        canon = json.dumps(
            {"v": self.cache_version, "args": args},
            sort_keys=True, default=str,
        )
        digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:24]
        return self.cache_root / tool_name / f"{digest}.json"

    def _read_cache(self, tool_name: str, args: dict[str, Any]) -> dict | None:
        p = self._cache_path(tool_name, args)
        if not p or not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(
        self, tool_name: str, args: dict[str, Any], payload: dict,
    ) -> None:
        p = self._cache_path(tool_name, args)
        if not p:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            # Cache write is best-effort; never raise into the caller.
            pass

    def bump_cache_version(self) -> None:
        """Invalidate all caches on the next access without deleting
        on-disk entries (they become stale but harmless)."""
        from datetime import datetime as _dt
        self.cache_version = f"v1+{_dt.utcnow().isoformat()}"

    # ------------------------------------------------------------------ tools

    def get_pod_events(
        self,
        window_id: str,
        *,
        max_events: int = 50,
    ) -> dict[str, Any]:
        """Return the full k8s event list for the (run, service, window)
        identified by `window_id`. Each event is a dict with
        `(timestamp, type, reason, message, pod, kind)`.

        On a missing file (e.g. windows without a k8s capture) returns
        `{events: [], n_events: 0, source_path: ..., error: "missing"}`.
        Never raises — emits an error field instead so the calling skill
        can record `tool_returned_empty` in its trace.
        """
        args = {"window_id": window_id, "max_events": max_events}
        cached = self._read_cache("pod_events", args)
        if cached is not None:
            cached["cache_hit"] = True
            return cached

        run_id = _run_id_from_window_id(window_id)
        source_path = (
            self.runs_root / run_id / "raw" / "kubernetes" / f"{window_id}.json"
        )
        if not source_path.is_file():
            payload: dict[str, Any] = {
                "events": [],
                "n_events": 0,
                "source_path": str(source_path),
                "error": "missing",
            }
        else:
            try:
                raw = json.loads(source_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                payload = {
                    "events": [],
                    "n_events": 0,
                    "source_path": str(source_path),
                    "error": f"{type(e).__name__}: {e}"[:140],
                }
            else:
                events = _extract_k8s_events(raw)
                # Trim to max_events most-recent
                events.sort(key=lambda e: str(e.get("timestamp", "")), reverse=True)
                events = events[:max_events]
                payload = {
                    "events": events,
                    "n_events": len(events),
                    "source_path": str(source_path),
                    "window": raw.get("window"),
                    "service_name": raw.get("service_name"),
                    "warning_count": sum(
                        1 for e in events if (e.get("type") or "").lower() == "warning"
                    ),
                }

        payload["cache_hit"] = False
        self._write_cache("pod_events", args, payload)
        return payload
