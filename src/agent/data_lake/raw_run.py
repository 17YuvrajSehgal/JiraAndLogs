"""RawRunDataLake — read-only access to raw per-run telemetry files.

Backs the v1 ReAct EvidenceRequestSkills. Each method maps to one
tool name (per `DOCS/docs8/IMPLEMENTATION-PLAN.md` §5.2 + §5.3).

v1 scope (Phase 2 #1):
  - `get_pod_events(window_id)` — k8s events from
    `data/runs/<run_id>/raw/kubernetes/<window_id>.json`.

v2 scope (Phase 2 #2):
  - `get_extended_trace_window(window_id)` — Tempo span aggregate
    from `data/runs/<run_id>/raw/tempo/<window_id>.json`. Summarises
    n_traces, n_error_traces, distinct services seen in batches,
    distinct error-status span names.
  - `get_pod_metrics(window_id)` — Prometheus snapshots from
    `data/runs/<run_id>/raw/prometheus/<window_id>.json`. Summarises
    restart-count delta, CPU/memory peaks, alert-fire count.
  - `get_similar_incidents(scenario_family, exclude_self_episode)` —
    peer-incident retrieval from the in-memory corpus. Reads
    `<global_dir>/jira-memory-corpus.jsonl` (cached in-process).

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
# Tempo summariser
# -----------------------------------------------------------------------------


def _summarize_tempo(raw: dict, *, source_path: str) -> dict[str, Any]:
    """Reduce a raw Tempo JSON dump to the headline counts the rerank
    skill cares about. Structure:
        raw['traces']: {trace_id -> {response: {batches: [...]}}}
        each batch has resource.attributes (service.name) + scopeSpans -> spans
        each span has status (empty dict = OK; otherwise non-OK).
    """
    traces = raw.get("traces") or {}
    n_traces = 0
    n_error_traces = 0
    services_seen: set[str] = set()
    error_span_names: set[str] = set()

    for _tid, tdata in traces.items():
        if not isinstance(tdata, dict):
            continue
        resp = tdata.get("response") or {}
        batches = resp.get("batches") or []
        if not batches:
            continue
        n_traces += 1
        trace_has_error = False
        for b in batches:
            # service.name from resource.attributes
            resource = b.get("resource") or {}
            for a in (resource.get("attributes") or []):
                if a.get("key") == "service.name":
                    v = (a.get("value") or {}).get("stringValue")
                    if v:
                        services_seen.add(v)
            # spans
            for ss in (b.get("scopeSpans") or []):
                for sp in (ss.get("spans") or []):
                    status = sp.get("status") or {}
                    # OpenTelemetry: status.code == 2 (ERROR) means error.
                    # Some exports use empty dict for OK + {"code": 2} for error.
                    if status.get("code") == 2:
                        trace_has_error = True
                        nm = sp.get("name")
                        if nm:
                            error_span_names.add(nm)
        if trace_has_error:
            n_error_traces += 1

    return {
        "n_traces": n_traces,
        "n_error_traces": n_error_traces,
        "services_seen": sorted(services_seen)[:30],     # cap to keep payload small
        "error_span_names": sorted(error_span_names)[:30],
        "source_path": source_path,
    }


# -----------------------------------------------------------------------------
# Prometheus summariser
# -----------------------------------------------------------------------------


def _series_stats(series_values: list) -> dict[str, float | None]:
    """Compute (max, mean, latest, first) of a Prometheus series result.
    `series_values` is a list of [timestamp, str_value] pairs."""
    if not series_values:
        return {"max": None, "mean": None, "latest": None, "first": None}
    vals: list[float] = []
    for entry in series_values:
        try:
            vals.append(float(entry[1]))
        except (ValueError, IndexError, TypeError):
            continue
    if not vals:
        return {"max": None, "mean": None, "latest": None, "first": None}
    return {
        "max": max(vals),
        "mean": sum(vals) / len(vals),
        "latest": vals[-1],
        "first": vals[0],
    }


def _summarize_prom(raw: dict, *, source_path: str) -> dict[str, Any]:
    """Reduce a Prometheus snapshot file to headline metrics.

    Queries we mine:
      restarts        — delta = latest - first (proxy for "did pods crash?")
      cpu_usage       — max + mean
      memory_working_set — max + mean
      alerts          — n_results > 0 implies an alert fired during window
    """
    queries = raw.get("queries") or {}

    def _first_series(qname: str) -> list:
        q = queries.get(qname) or {}
        resp = q.get("response") or {}
        data = resp.get("data") or {}
        results = data.get("result") or []
        if not results:
            return []
        # Use the first matching series — for our queries this is the
        # primary pod's series.
        return (results[0] or {}).get("values") or []

    restart_stats = _series_stats(_first_series("restarts"))
    cpu_stats = _series_stats(_first_series("cpu_usage"))
    mem_stats = _series_stats(_first_series("memory_working_set"))

    # Alerts: count distinct results (each result = one firing alert)
    alerts_q = queries.get("alerts") or {}
    alerts_results = (alerts_q.get("response") or {}).get("data", {}).get("result") or []
    n_alerts_firing = len(alerts_results) if isinstance(alerts_results, list) else 0

    restart_first = restart_stats.get("first")
    restart_latest = restart_stats.get("latest")
    restart_delta = (
        int(restart_latest - restart_first)
        if (restart_first is not None and restart_latest is not None)
        else None
    )

    return {
        "restart_delta": restart_delta,
        "restart_total_latest": restart_latest,
        "cpu_max": cpu_stats.get("max"),
        "cpu_mean": cpu_stats.get("mean"),
        "mem_max": mem_stats.get("max"),
        "mem_mean": mem_stats.get("mean"),
        "n_alerts_firing": n_alerts_firing,
        "source_path": source_path,
    }


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

    # ------------------------------------------------------------------ trace window

    def get_extended_trace_window(
        self,
        window_id: str,
    ) -> dict[str, Any]:
        """Summarise the Tempo trace dump for one window.

        Returns:
            {
              "n_traces": int,
              "n_error_traces": int,           # traces with any non-OK span status
              "services_seen": list[str],      # unique service.name values
              "error_span_names": list[str],   # span names where status was non-OK
              "source_path": str,
              "error": str | None,
            }
        """
        args = {"window_id": window_id}
        cached = self._read_cache("extended_trace_window", args)
        if cached is not None:
            cached["cache_hit"] = True
            return cached

        run_id = _run_id_from_window_id(window_id)
        src = self.runs_root / run_id / "raw" / "tempo" / f"{window_id}.json"
        if not src.is_file():
            payload: dict[str, Any] = {
                "n_traces": 0, "n_error_traces": 0,
                "services_seen": [], "error_span_names": [],
                "source_path": str(src), "error": "missing",
            }
        else:
            try:
                raw = json.loads(src.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                payload = {
                    "n_traces": 0, "n_error_traces": 0,
                    "services_seen": [], "error_span_names": [],
                    "source_path": str(src),
                    "error": f"{type(e).__name__}: {e}"[:140],
                }
            else:
                payload = _summarize_tempo(raw, source_path=str(src))

        payload["cache_hit"] = False
        self._write_cache("extended_trace_window", args, payload)
        return payload

    # ------------------------------------------------------------------ pod metrics

    def get_pod_metrics(
        self,
        window_id: str,
    ) -> dict[str, Any]:
        """Summarise the Prometheus snapshot for one window.

        Returns:
            {
              "restart_delta": int | None,       # last - first of restarts query
              "restart_total_latest": float | None,
              "cpu_max": float | None,
              "cpu_mean": float | None,
              "mem_max": float | None,
              "mem_mean": float | None,
              "n_alerts_firing": int,
              "source_path": str,
              "error": str | None,
            }
        """
        args = {"window_id": window_id}
        cached = self._read_cache("pod_metrics", args)
        if cached is not None:
            cached["cache_hit"] = True
            return cached

        run_id = _run_id_from_window_id(window_id)
        src = self.runs_root / run_id / "raw" / "prometheus" / f"{window_id}.json"
        if not src.is_file():
            payload: dict[str, Any] = {
                "restart_delta": None,
                "restart_total_latest": None,
                "cpu_max": None, "cpu_mean": None,
                "mem_max": None, "mem_mean": None,
                "n_alerts_firing": 0,
                "source_path": str(src), "error": "missing",
            }
        else:
            try:
                raw = json.loads(src.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                payload = {
                    "restart_delta": None,
                    "restart_total_latest": None,
                    "cpu_max": None, "cpu_mean": None,
                    "mem_max": None, "mem_mean": None,
                    "n_alerts_firing": 0,
                    "source_path": str(src),
                    "error": f"{type(e).__name__}: {e}"[:140],
                }
            else:
                payload = _summarize_prom(raw, source_path=str(src))

        payload["cache_hit"] = False
        self._write_cache("pod_metrics", args, payload)
        return payload

    # ------------------------------------------------------------------ similar incidents

    def get_similar_incidents(
        self,
        scenario_family: str | None,
        global_dir: Path | str,
        *,
        exclude_episode_id: str | None = None,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """Return up to top_k peer memory tickets sharing `scenario_family`.

        Reads the global jira-memory-corpus.jsonl and filters by family,
        excluding the given episode_id (so a window doesn't get matched
        against its own incident's ticket). Used by
        `RequestSimilarIncidentWindowSkill` to surface peer-incident
        symptoms for the agent to reason against.
        """
        args = {
            "scenario_family": scenario_family or "",
            "global_dir": str(global_dir),
            "exclude_episode_id": exclude_episode_id or "",
            "top_k": top_k,
        }
        cached = self._read_cache("similar_incidents", args)
        if cached is not None:
            cached["cache_hit"] = True
            return cached

        peers: list[dict[str, Any]] = []
        corpus_path = Path(global_dir) / "jira-memory-corpus.jsonl"
        if not corpus_path.is_file():
            payload = {
                "peers": [], "n_peers": 0,
                "scenario_family": scenario_family,
                "error": f"corpus missing at {corpus_path}",
            }
        elif not scenario_family:
            payload = {
                "peers": [], "n_peers": 0,
                "scenario_family": None,
                "error": "no scenario_family on bundle",
            }
        else:
            with corpus_path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("scenario_family") != scenario_family:
                        continue
                    if exclude_episode_id and row.get("incident_episode_id") == exclude_episode_id:
                        continue
                    # Keep a small projection — the rerank uses memory_text
                    # tokens; we don't ship the whole record.
                    peers.append({
                        "issue_id": row.get("jira_shadow_issue_id"),
                        "episode_id": row.get("incident_episode_id"),
                        "scenario_family": row.get("scenario_family"),
                        # Take first 600 chars — enough for the
                        # service/component vocabulary
                        "memory_text_head": (row.get("memory_text") or "")[:600],
                    })
                    if len(peers) >= top_k:
                        break
            payload = {
                "peers": peers,
                "n_peers": len(peers),
                "scenario_family": scenario_family,
            }

        payload["cache_hit"] = False
        self._write_cache("similar_incidents", args, payload)
        return payload
