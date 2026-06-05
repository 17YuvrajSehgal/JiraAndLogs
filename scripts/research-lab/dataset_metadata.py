#!/usr/bin/env python3
"""Paper-ready dataset metadata for v5-quick / v5-large / future corpora.

Walks every run that matches a prefix, plus the global derived dataset if
provided, and emits a structured snapshot of everything a research paper
typically needs to characterise the corpus:

  * collection scale (runs, families, services, time span, raw bytes)
  * telemetry windows (counts, label distribution, hard/novel/orphan
    counts, train/val/test split sizes, family stratification)
  * Jira memory corpus (size, prose statistics, component/label/severity
    distributions, time coverage, retrieval ground-truth coverage)
  * logs / metrics / traces (file counts, line counts, byte totals,
    per-service breakdown, sampling distribution)
  * statistical sanity (class balance, family count, replicate counts)

Output:
  1. A human-readable summary to stdout (so you can paste it into a doc).
  2. A machine-readable JSON written to the global derived directory (or
     to --output if you'd rather pin it somewhere else) — paste-able into
     a paper's appendix or fed into LaTeX tables.

Usage:
    python scripts/research-lab/dataset_metadata.py \
        --runs-prefix 2026-05-25-dataset-v5-quick

    # Once v5-large is collected:
    python scripts/research-lab/dataset_metadata.py \
        --runs-prefix 2026-05-25-dataset-v5-large \
        --global-id 2026-05-25-dataset-v5-large-global

Performance note: Loki log-line counting opens every per-window JSON dump.
On 1,182 files (~44 GB) that is the slow path. Multiprocessing keeps it
to roughly one minute on the laptop; the rest of the script is seconds.
Pass --fast to skip exact log-line counts and use file-size-based
extrapolation from a 5-file sample instead — useful when you're iterating
on the report shape and don't need exact line totals yet.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import statistics
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _repo_root_from_script() -> Path:
    """scripts/research-lab/dataset_metadata.py -> repo root."""
    return Path(__file__).resolve().parent.parent.parent


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8-sig", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


# ---------------------------------------------------------------------------
# Slow-path: count Loki log lines per file
# ---------------------------------------------------------------------------

def _count_loki_lines(path_str: str) -> tuple[int, int]:
    """Return (line_count, byte_size) for one Loki JSON file.

    `export-telemetry-window.ps1` wraps each window's Loki dump as

        {
          "fetched_at": ..., "window": ..., "service_query": ...,
          "service_window":  {"ok": ..., "response": <loki-response>},
          "service_context": {"ok": ..., "response": <loki-response>},
          "namespace_context": {"ok": ..., "response": <loki-response>}
        }

    where each `<loki-response>` is a standard Loki query response
    (`{"status": "success", "data": {"resultType": "streams",
    "result": [{"stream": {...}, "values": [[ts, line], ...]}]}}`).

    Line count = sum of `len(values)` across every `result[*]` of every
    `<sub>.response` we can find. We sum the *service* (per-service)
    window/context — the namespace_context is intentionally excluded to
    avoid double-counting (it overlaps with the per-service exports of
    the other services on the same window).
    """
    p = Path(path_str)
    if not p.exists():
        return 0, 0
    size = p.stat().st_size

    def _sum_streams(response: Any) -> int:
        if not isinstance(response, dict):
            return 0
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        result = data.get("result") or []
        return sum(len(stream.get("values") or []) for stream in result)

    try:
        with p.open(encoding="utf-8", errors="ignore") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        # Fallback: newline-delimited JSON. Older / future variants.
        try:
            with p.open(encoding="utf-8", errors="ignore") as fh:
                return sum(1 for _ in fh), size
        except OSError:
            return 0, size

    if isinstance(data, dict):
        # Preferred: the per-window wrapper shape this builder writes.
        total = 0
        for sub_key in ("service_window", "service_context"):
            sub = data.get(sub_key)
            if isinstance(sub, dict):
                total += _sum_streams(sub.get("response"))
        if total > 0:
            return total, size
        # Legacy shape: single `{"data": {"result": [...]}}` Loki response.
        legacy = _sum_streams(data)
        if legacy:
            return legacy, size
    if isinstance(data, list):
        return len(data), size
    return 0, size


# ---------------------------------------------------------------------------
# Slow-path: count Prometheus + Tempo samples
# ---------------------------------------------------------------------------

def _count_prom_samples(path_str: str) -> tuple[int, int, int]:
    """Return (sample_count, unique_metric_names_in_file, byte_size).

    These files bundle multiple PromQL queries per file:
        {"queries": {"<query_name>": {"response":
            {"data": {"result": [{"metric": {"__name__": ...},
                                  "values": [[ts, val], ...]} ...]}}}}}
    We walk every query in the bundle and accumulate samples + names.
    """
    p = Path(path_str)
    if not p.exists():
        return 0, 0, 0
    size = p.stat().st_size
    try:
        with p.open(encoding="utf-8-sig", errors="ignore") as fh:
            data = json.load(fh)
        samples = 0
        names: set[str] = set()
        queries = data.get("queries") or {}
        for q in queries.values():
            response = (q or {}).get("response") or {}
            result = (response.get("data") or {}).get("result") or []
            for series in result:
                samples += len(series.get("values") or [])
                metric = series.get("metric") or {}
                name = metric.get("__name__")
                if name:
                    names.add(str(name))
        # Fallback: old single-query shape (kept for forward-compat with
        # future builders that may write the simpler structure).
        if not samples:
            for series in (data.get("data", {}) or {}).get("result", []) or []:
                samples += len(series.get("values") or [])
                name = (series.get("metric") or {}).get("__name__")
                if name:
                    names.add(str(name))
        return samples, len(names), size
    except (json.JSONDecodeError, OSError):
        return 0, 0, size


def _count_tempo_spans(path_str: str) -> tuple[int, int, int]:
    """Return (span_count, unique_service_count, byte_size).

    Schema is `{"traces": {trace_id: {"response": {"batches": [...]}}}}`.
    Each batch carries `resource.attributes` (with service.name in
    OTLP key/value shape) and `scopeSpans[*].spans` (or the legacy
    `instrumentationLibrarySpans`). We accumulate spans + unique services.
    """
    p = Path(path_str)
    if not p.exists():
        return 0, 0, 0
    size = p.stat().st_size
    try:
        with p.open(encoding="utf-8-sig", errors="ignore") as fh:
            data = json.load(fh)
        spans = 0
        services: set[str] = set()
        traces_field = data.get("traces") if isinstance(data, dict) else None
        # Accept dict-of-trace-id, list-of-traces, or top-level list
        if isinstance(traces_field, dict):
            trace_envelopes = list(traces_field.values())
        elif isinstance(traces_field, list):
            trace_envelopes = traces_field
        elif isinstance(data, list):
            trace_envelopes = data
        else:
            trace_envelopes = [data] if isinstance(data, dict) else []
        for envelope in trace_envelopes:
            if not isinstance(envelope, dict):
                continue
            # Real-span payload lives under .response.batches when present.
            payload = envelope.get("response", envelope)
            for batch in (payload.get("batches") or []):
                resource = batch.get("resource") or {}
                for attr in resource.get("attributes") or []:
                    if attr.get("key") in ("service.name", "app", "k8s.deployment.name"):
                        val = attr.get("value", {}) or {}
                        svc = val.get("stringValue") or val.get("string_value")
                        if svc:
                            services.add(str(svc))
                scopes = batch.get("scopeSpans") or batch.get("instrumentationLibrarySpans") or []
                for scope in scopes:
                    spans += len(scope.get("spans") or [])
        return spans, len(services), size
    except (json.JSONDecodeError, OSError):
        return 0, 0, size


# ---------------------------------------------------------------------------
# Dataclasses for the structured report
# ---------------------------------------------------------------------------


@dataclass
class CollectionStats:
    run_count: int = 0
    run_ids: list[str] = field(default_factory=list)
    scenario_families: list[str] = field(default_factory=list)
    services_seen: list[str] = field(default_factory=list)
    episode_count: int = 0
    earliest_event: str | None = None
    latest_event: str | None = None
    raw_bytes_total: int = 0


@dataclass
class WindowStats:
    total: int = 0
    by_split: dict[str, int] = field(default_factory=dict)
    label_distribution: dict[str, int] = field(default_factory=dict)
    n_hard: int = 0
    n_novel: int = 0
    n_with_matched_memory: int = 0
    n_orphan: int = 0
    per_family: dict[str, int] = field(default_factory=dict)
    per_service: dict[str, int] = field(default_factory=dict)
    per_window_type: dict[str, int] = field(default_factory=dict)
    feature_column_count: int = 0


@dataclass
class JiraStats:
    issue_count: int = 0
    summary_words_mean: float = 0.0
    summary_words_median: float = 0.0
    description_words_mean: float = 0.0
    description_words_median: float = 0.0
    comments_count_mean: float = 0.0
    comments_words_mean: float = 0.0
    component_distribution: dict[str, int] = field(default_factory=dict)
    label_distribution: dict[str, int] = field(default_factory=dict)
    severity_distribution: dict[str, int] = field(default_factory=dict)
    earliest_created: str | None = None
    latest_created: str | None = None


@dataclass
class LogStats:
    file_count: int = 0
    line_count_total: int = 0
    bytes_total: int = 0
    files_sampled_for_extrapolation: int = 0
    lines_per_file_mean: float = 0.0
    bytes_per_file_mean: float = 0.0
    per_service_file_count: dict[str, int] = field(default_factory=dict)


@dataclass
class MetricStats:
    file_count: int = 0
    sample_count_total: int = 0
    unique_metric_names: int = 0
    bytes_total: int = 0
    samples_per_file_mean: float = 0.0
    metric_name_examples: list[str] = field(default_factory=list)
    # M0-M5 supplement files (raw/prometheus_supplement/) — emitted by
    # scripts/research-lab/export_m05_supplement.py with the rich RED /
    # business / runtime queries that feed `triage_feature_m05_*`. Treated
    # as a separate stream so the base Prom export numbers don't shift.
    supplement_file_count: int = 0
    supplement_bytes_total: int = 0
    supplement_unique_queries: int = 0
    supplement_value_count_total: int = 0
    supplement_query_examples: list[str] = field(default_factory=list)


@dataclass
class TraceStats:
    file_count: int = 0
    span_count_total: int = 0
    services_in_traces: list[str] = field(default_factory=list)
    bytes_total: int = 0
    spans_per_file_mean: float = 0.0


@dataclass
class DatasetMetadata:
    dataset_id: str
    runs_prefix: str
    generated_at: str
    collection: CollectionStats
    windows: WindowStats
    jira: JiraStats
    logs: LogStats
    metrics: MetricStats
    traces: TraceStats


# ---------------------------------------------------------------------------
# Word-count + distribution helpers
# ---------------------------------------------------------------------------


def _word_count(text: Any) -> int:
    if isinstance(text, str):
        return len(text.split())
    if isinstance(text, list):
        return sum(_word_count(item) for item in text)
    return 0


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.mean(values) if values else 0.0


def _median(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.median(values) if values else 0.0


def _top_n(counter: Counter, n: int = 25) -> dict[str, int]:
    return dict(counter.most_common(n))


def _min_max_iso(values: Iterable[str]) -> tuple[str | None, str | None]:
    vals = [v for v in values if isinstance(v, str) and v]
    if not vals:
        return None, None
    try:
        return min(vals), max(vals)
    except ValueError:
        return None, None


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_collection_stats(
    runs_root: Path, run_dirs: list[Path]
) -> tuple[CollectionStats, list[dict[str, Any]]]:
    """Walk every run's episodes.jsonl + raw/ to summarize collection scale.

    Episode schema: `scenario_id` is the leaf scenario (e.g.
    "cart-redis-flake"), `scenario_family` is derived elsewhere (we recover
    it from the global derived windows in collect_window_stats). Episode
    time fields are `start_time` / `end_time`."""
    scenarios: set[str] = set()
    incident_types: set[str] = set()
    services: set[str] = set()
    event_times: list[str] = []
    episode_count = 0
    raw_bytes = 0
    all_episodes: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        episodes = _read_jsonl(run_dir / "episodes.jsonl")
        episode_count += len(episodes)
        for ep in episodes:
            sid = ep.get("scenario_id")
            if sid:
                scenarios.add(str(sid))
            it = ep.get("incident_type")
            if it:
                incident_types.add(str(it))
            for svc in ep.get("affected_services", []) or []:
                services.add(str(svc))
            for k in ("start_time", "end_time"):
                ts = ep.get(k)
                if ts:
                    event_times.append(ts)
            all_episodes.append(ep)
        raw_dir = run_dir / "raw"
        if raw_dir.exists():
            for p in raw_dir.rglob("*"):
                if p.is_file():
                    raw_bytes += p.stat().st_size
    earliest, latest = _min_max_iso(event_times)
    # `scenario_families` here is the SCENARIO-ID set (e.g.
    # "cart-redis-flake"). The higher-level family is recovered via
    # WindowStats.per_family from the global derived dataset.
    return CollectionStats(
        run_count=len(run_dirs),
        run_ids=[d.name for d in run_dirs],
        scenario_families=sorted(scenarios),
        services_seen=sorted(services),
        episode_count=episode_count,
        earliest_event=earliest,
        latest_event=latest,
        raw_bytes_total=raw_bytes,
    ), all_episodes


# ---------------------------------------------------------------------------
# Windows + splits + matchings (from the derived global dataset)
# ---------------------------------------------------------------------------


def collect_window_stats(global_dir: Path | None) -> WindowStats:
    stats = WindowStats()
    if global_dir is None:
        return stats
    examples_path = global_dir / "global-triage-examples.jsonl"
    matchings_path = global_dir / "window-memory-matchings.jsonl"
    split_path = global_dir / "triage-split-manifest.json"
    cols_path = global_dir / "triage-feature-columns.json"

    rows = _read_jsonl(examples_path)
    stats.total = len(rows)
    label_counter: Counter[str] = Counter()
    family_counter: Counter[str] = Counter()
    service_counter: Counter[str] = Counter()
    window_type_counter: Counter[str] = Counter()
    split_counter: Counter[str] = Counter()
    for r in rows:
        label = r.get("triage_label", "unknown")
        label_counter[str(label)] += 1
        family_counter[str(r.get("scenario_family", "unknown"))] += 1
        service_counter[str(r.get("service_name", "unknown"))] += 1
        window_type_counter[str(r.get("window_type", "unknown"))] += 1
        split_counter[str(r.get("split", "unknown"))] += 1
        if r.get("is_hard_case"):
            stats.n_hard += 1
        if r.get("is_novel"):
            stats.n_novel += 1

    stats.label_distribution = dict(label_counter)
    stats.per_family = _top_n(family_counter, 30)
    stats.per_service = _top_n(service_counter, 30)
    stats.per_window_type = _top_n(window_type_counter, 10)
    stats.by_split = dict(split_counter)

    if matchings_path.exists():
        for m in _read_jsonl(matchings_path):
            matched = m.get("matched_memory_issue_ids") or []
            if matched:
                stats.n_with_matched_memory += 1
            else:
                if m.get("triage_label") == "ticket_worthy":
                    stats.n_orphan += 1

    if split_path.exists():
        # Split manifest exposes group ids per split; row-level split tags
        # in global-triage-examples.jsonl may not be populated, so prefer
        # the manifest counts when available.
        try:
            manifest = json.loads(split_path.read_text(encoding="utf-8-sig"))
            for key in ("train", "validation", "test"):
                ids = manifest.get(key)
                if isinstance(ids, list) and ids:
                    stats.by_split[key] = len(ids)
        except (json.JSONDecodeError, OSError):
            pass

    if cols_path.exists():
        try:
            contract = json.loads(cols_path.read_text(encoding="utf-8-sig"))
            cols = contract.get("feature_columns") or []
            stats.feature_column_count = len(cols)
        except (json.JSONDecodeError, OSError):
            pass

    return stats


# ---------------------------------------------------------------------------
# Jira
# ---------------------------------------------------------------------------


def collect_jira_stats(run_dirs: list[Path]) -> JiraStats:
    summary_words: list[int] = []
    desc_words: list[int] = []
    comment_counts: list[int] = []
    comment_words: list[int] = []
    component_counter: Counter[str] = Counter()
    label_counter: Counter[str] = Counter()
    severity_counter: Counter[str] = Counter()
    created_times: list[str] = []
    issue_count = 0

    for run_dir in run_dirs:
        for issue in _read_jsonl(run_dir / "jira_shadow_issues.jsonl"):
            issue_count += 1
            meta = issue.get("metadata") or {}
            summary_words.append(_word_count(meta.get("summary")))
            desc_words.append(_word_count(meta.get("description")))
            raw_comments = meta.get("comments_body") or ""
            if isinstance(raw_comments, str):
                chunks = [c for c in raw_comments.split("\n---\n") if c.strip()]
            elif isinstance(raw_comments, list):
                chunks = [str(c) for c in raw_comments if c]
            else:
                chunks = []
            comment_counts.append(len(chunks))
            comment_words.append(sum(_word_count(c) for c in chunks))
            for c in meta.get("components", []) or []:
                component_counter[str(c)] += 1
            for l in meta.get("labels", []) or []:
                label_counter[str(l)] += 1
            sev = (issue.get("severity") or meta.get("severity")
                   or meta.get("priority") or "unknown")
            severity_counter[str(sev).lower()] += 1
            ts = meta.get("created_at") or issue.get("created_at")
            if ts:
                created_times.append(ts)

    earliest, latest = _min_max_iso(created_times)
    return JiraStats(
        issue_count=issue_count,
        summary_words_mean=round(_mean(summary_words), 2),
        summary_words_median=round(_median(summary_words), 2),
        description_words_mean=round(_mean(desc_words), 2),
        description_words_median=round(_median(desc_words), 2),
        comments_count_mean=round(_mean(comment_counts), 2),
        comments_words_mean=round(_mean(comment_words), 2),
        component_distribution=_top_n(component_counter, 25),
        label_distribution=_top_n(label_counter, 25),
        severity_distribution=dict(severity_counter),
        earliest_created=earliest,
        latest_created=latest,
    )


# ---------------------------------------------------------------------------
# Logs, metrics, traces (raw walks)
# ---------------------------------------------------------------------------


# Service set we care about — matches the Online Boutique app names.
_KNOWN_SERVICES = {
    "frontend", "checkoutservice", "cartservice", "productcatalogservice",
    "paymentservice", "shippingservice", "currencyservice",
    "recommendationservice", "adservice", "emailservice", "loadgenerator",
    "redis-cart",
}


def _service_from_filename(name: str) -> str:
    """Files are named '<run>-<scenario>-<ts>-<window-type>-<service>.json'.

    Naive last-hyphen split breaks on suffixed window-types like
    `observation_window-<svc>` where `<svc>` may itself contain hyphens
    (e.g. `redis-cart`). Scan tokens right-to-left and return the longest
    suffix that matches a known service name."""
    stem = Path(name).stem
    parts = stem.split("-")
    for join_n in (2, 1):
        if len(parts) >= join_n:
            candidate = "-".join(parts[-join_n:])
            if candidate in _KNOWN_SERVICES:
                return candidate
    return parts[-1] if parts else stem


def collect_log_stats(run_dirs: list[Path], *, fast: bool, workers: int) -> LogStats:
    paths: list[str] = []
    per_service: Counter[str] = Counter()
    for run_dir in run_dirs:
        loki = run_dir / "raw" / "loki"
        if loki.exists():
            for p in loki.glob("*.json"):
                paths.append(str(p))
                svc = _service_from_filename(p.name)
                # Buckets that aren't known services (timestamp suffixes,
                # context.json metadata files, etc.) get collapsed into
                # `_other` so the per-service breakdown stays readable.
                per_service[svc if svc in _KNOWN_SERVICES else "_other"] += 1
    if not paths:
        return LogStats()
    if fast:
        sample = paths[:5]
        with mp.Pool(min(workers, len(sample))) as pool:
            results = pool.map(_count_loki_lines, sample)
        line_mean = _mean(r[0] for r in results)
        bytes_mean = _mean(r[1] for r in results)
        return LogStats(
            file_count=len(paths),
            line_count_total=int(line_mean * len(paths)),
            bytes_total=int(bytes_mean * len(paths)),
            files_sampled_for_extrapolation=len(sample),
            lines_per_file_mean=round(line_mean, 2),
            bytes_per_file_mean=round(bytes_mean, 2),
            per_service_file_count=_top_n(per_service, 30),
        )
    with mp.Pool(workers) as pool:
        results = pool.map(_count_loki_lines, paths)
    line_total = sum(r[0] for r in results)
    byte_total = sum(r[1] for r in results)
    return LogStats(
        file_count=len(paths),
        line_count_total=line_total,
        bytes_total=byte_total,
        files_sampled_for_extrapolation=0,
        lines_per_file_mean=round(line_total / len(paths), 2),
        bytes_per_file_mean=round(byte_total / len(paths), 2),
        per_service_file_count=_top_n(per_service, 30),
    )


def _scan_supplement_files(paths: list[str]) -> tuple[int, int, set[str]]:
    """Return (total_value_count, total_bytes, unique_query_keys) for the
    M0-M5 supplement files (raw/prometheus_supplement/<window>.json).

    Schema (from export_m05_supplement.py):
        {
          "window_start": ..., "window_end": ..., "service_name": ...,
          "queries": {<query_key>: <promql_string>, ...},
          "values":  {<query_key>: <scalar>, ...}
        }
    """
    total_values = 0
    total_bytes = 0
    query_keys: set[str] = set()
    for ps in paths:
        p = Path(ps)
        if not p.exists():
            continue
        total_bytes += p.stat().st_size
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig", errors="ignore"))
        except (json.JSONDecodeError, OSError):
            continue
        values = data.get("values") if isinstance(data, dict) else None
        if isinstance(values, dict):
            total_values += len(values)
            query_keys.update(values.keys())
        queries = data.get("queries") if isinstance(data, dict) else None
        if isinstance(queries, dict):
            query_keys.update(queries.keys())
    return total_values, total_bytes, query_keys


def collect_metric_stats(run_dirs: list[Path], *, fast: bool, workers: int) -> MetricStats:
    paths: list[str] = []
    supplement_paths: list[str] = []
    for run_dir in run_dirs:
        prom = run_dir / "raw" / "prometheus"
        if prom.exists():
            for p in prom.rglob("*.json"):
                paths.append(str(p))
        sup_dir = run_dir / "raw" / "prometheus_supplement"
        if sup_dir.exists():
            for p in sup_dir.rglob("*.json"):
                supplement_paths.append(str(p))
    if not paths and not supplement_paths:
        return MetricStats()

    # --- base prometheus exports (queries-bundle shape) ----
    sample_paths = paths[:5] if fast else paths
    if sample_paths:
        with mp.Pool(workers) as pool:
            results = pool.map(_count_prom_samples, sample_paths)
        sample_total = sum(r[0] for r in results)
        bytes_total = sum(r[2] for r in results)
    else:
        sample_total = 0
        bytes_total = 0
    if fast and paths:
        ratio = len(paths) / max(len(sample_paths), 1)
        sample_total = int(sample_total * ratio)
        bytes_total = int(bytes_total * ratio)
    name_set: set[str] = set()
    for p in paths[:30]:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8-sig", errors="ignore"))
            for q in (data.get("queries") or {}).values():
                response = (q or {}).get("response") or {}
                for series in (response.get("data") or {}).get("result") or []:
                    name = (series.get("metric") or {}).get("__name__")
                    if name:
                        name_set.add(str(name))
        except (json.JSONDecodeError, OSError):
            continue

    # --- M0-M5 supplement files (separate stream) ----
    sup_total_values = 0
    sup_bytes = 0
    sup_keys: set[str] = set()
    if supplement_paths:
        sup_sample = supplement_paths[:5] if fast else supplement_paths
        # Single-process here — supplement files are tiny (<5 KB each),
        # the IO dominates. mp.Pool overhead isn't worth it.
        sup_total_values, sup_bytes, sup_keys = _scan_supplement_files(sup_sample)
        if fast:
            ratio = len(supplement_paths) / max(len(sup_sample), 1)
            sup_total_values = int(sup_total_values * ratio)
            sup_bytes = int(sup_bytes * ratio)

    return MetricStats(
        file_count=len(paths),
        sample_count_total=sample_total,
        unique_metric_names=len(name_set),
        bytes_total=bytes_total,
        samples_per_file_mean=round(sample_total / max(len(paths), 1), 2),
        metric_name_examples=sorted(name_set)[:50],
        supplement_file_count=len(supplement_paths),
        supplement_bytes_total=sup_bytes,
        supplement_unique_queries=len(sup_keys),
        supplement_value_count_total=sup_total_values,
        supplement_query_examples=sorted(sup_keys)[:50],
    )


def collect_trace_stats(run_dirs: list[Path], *, fast: bool, workers: int) -> TraceStats:
    paths: list[str] = []
    for run_dir in run_dirs:
        tempo = run_dir / "raw" / "tempo"
        if tempo.exists():
            for p in tempo.rglob("*.json"):
                paths.append(str(p))
    if not paths:
        return TraceStats()
    sample_paths = paths[:5] if fast else paths
    with mp.Pool(workers) as pool:
        results = pool.map(_count_tempo_spans, sample_paths)
    span_total = sum(r[0] for r in results)
    bytes_total = sum(r[2] for r in results)
    # Walk the same nested `traces[*].response.batches[*].resource.attributes`
    # path as the span counter to collect service names from a 30-file sample.
    services_union: set[str] = set()
    for p in paths[:30]:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8-sig", errors="ignore"))
            envelopes = (
                list(data.get("traces", {}).values())
                if isinstance(data, dict) and isinstance(data.get("traces"), dict)
                else (data.get("traces") if isinstance(data, dict) else data)
            ) or []
            for envelope in envelopes:
                if not isinstance(envelope, dict):
                    continue
                payload = envelope.get("response", envelope)
                for batch in (payload.get("batches") or []):
                    for attr in (batch.get("resource") or {}).get("attributes") or []:
                        if attr.get("key") in ("service.name", "app", "k8s.deployment.name"):
                            val = attr.get("value", {}) or {}
                            svc = val.get("stringValue") or val.get("string_value")
                            if svc:
                                services_union.add(str(svc))
        except (json.JSONDecodeError, OSError):
            continue
    if fast:
        ratio = len(paths) / max(len(sample_paths), 1)
        span_total = int(span_total * ratio)
        bytes_total = int(bytes_total * ratio)
    return TraceStats(
        file_count=len(paths),
        span_count_total=span_total,
        services_in_traces=sorted(services_union),
        bytes_total=bytes_total,
        spans_per_file_mean=round(span_total / max(len(paths), 1), 2),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.2f} {u}"
        f /= 1024
    return f"{n} B"


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _render_dict(d: dict[str, Any], indent: str = "    ", max_rows: int = 25) -> str:
    if not d:
        return f"{indent}(none)"
    rows = list(d.items())[:max_rows]
    extra = "" if len(d) <= max_rows else f"\n{indent}... ({len(d)-max_rows} more)"
    return "\n".join(f"{indent}{k:<35} {v}" for k, v in rows) + extra


def render_summary(report: DatasetMetadata) -> str:
    out: list[str] = []
    out.append(f"=== Dataset metadata: {report.dataset_id} ===")
    out.append(f"runs prefix: {report.runs_prefix}")
    out.append(f"generated:   {report.generated_at}")

    c = report.collection
    out.append("")
    out.append("[1] Collection")
    out.append(f"    runs:                {_fmt_int(c.run_count)}")
    out.append(f"    unique scenarios:    {len(c.scenario_families)}")
    out.append(f"    services covered:    {len(c.services_seen)}")
    out.append(f"    episodes:            {_fmt_int(c.episode_count)}")
    out.append(f"    raw on disk:         {_fmt_bytes(c.raw_bytes_total)}")
    out.append(f"    earliest event:      {c.earliest_event}")
    out.append(f"    latest event:        {c.latest_event}")
    out.append(f"    scenarios (sample): {', '.join(c.scenario_families[:8])}"
               + (f" (+{len(c.scenario_families)-8} more)" if len(c.scenario_families) > 8 else ""))
    out.append(f"    higher-level families derived from windows: see section [2] per_family")

    w = report.windows
    out.append("")
    out.append("[2] Telemetry windows (the unit of triage)")
    out.append(f"    total windows:       {_fmt_int(w.total)}")
    out.append(f"    feature columns:     {w.feature_column_count}")
    out.append(f"    splits: {w.by_split}")
    out.append(f"    label distribution:")
    out.append(_render_dict(w.label_distribution, "        "))
    out.append(f"    is_hard_case:        {_fmt_int(w.n_hard)}")
    out.append(f"    is_novel:            {_fmt_int(w.n_novel)}")
    out.append(f"    with memory match:   {_fmt_int(w.n_with_matched_memory)}")
    out.append(f"    orphan ticket-worthy:{_fmt_int(w.n_orphan)}")
    out.append(f"    windows by family (top):")
    out.append(_render_dict(w.per_family, "        "))
    out.append(f"    windows by service (top):")
    out.append(_render_dict(w.per_service, "        "))
    out.append(f"    windows by window_type:")
    out.append(_render_dict(w.per_window_type, "        "))

    j = report.jira
    out.append("")
    out.append("[3] Jira memory corpus")
    out.append(f"    issues:                  {_fmt_int(j.issue_count)}")
    out.append(f"    summary words (mean/med):    {j.summary_words_mean} / {j.summary_words_median}")
    out.append(f"    description words (mean/med):{j.description_words_mean} / {j.description_words_median}")
    out.append(f"    comments per ticket (mean):  {j.comments_count_mean}")
    out.append(f"    comments words (mean):       {j.comments_words_mean}")
    out.append(f"    earliest created:        {j.earliest_created}")
    out.append(f"    latest created:          {j.latest_created}")
    out.append(f"    component distribution (top 10):")
    out.append(_render_dict(dict(list(j.component_distribution.items())[:10]), "        "))
    out.append(f"    label distribution (top 10):")
    out.append(_render_dict(dict(list(j.label_distribution.items())[:10]), "        "))
    out.append(f"    severity distribution:")
    out.append(_render_dict(j.severity_distribution, "        "))

    l = report.logs
    out.append("")
    out.append("[4] Logs (Loki)")
    out.append(f"    files:                   {_fmt_int(l.file_count)}")
    out.append(f"    log lines total:         {_fmt_int(l.line_count_total)}"
               + (" (extrapolated from sample)" if l.files_sampled_for_extrapolation else ""))
    out.append(f"    bytes:                   {_fmt_bytes(l.bytes_total)}")
    out.append(f"    avg lines / file:        {l.lines_per_file_mean:,.0f}")
    out.append(f"    files per service (top):")
    out.append(_render_dict(l.per_service_file_count, "        "))

    m = report.metrics
    out.append("")
    out.append("[5] Metrics (Prometheus)")
    out.append(f"    base export files:       {_fmt_int(m.file_count)}")
    out.append(f"    base samples total:      {_fmt_int(m.sample_count_total)}")
    out.append(f"    base unique metric names:{m.unique_metric_names}")
    out.append(f"    base avg samples / file: {m.samples_per_file_mean:,.0f}")
    out.append(f"    base bytes:              {_fmt_bytes(m.bytes_total)}")
    if m.metric_name_examples:
        out.append(f"    base example metric names ({len(m.metric_name_examples)}):")
        for name in m.metric_name_examples[:20]:
            out.append(f"        - {name}")
        if len(m.metric_name_examples) > 20:
            out.append(f"        ... (+{len(m.metric_name_examples)-20})")
    out.append("")
    out.append("    M0-M5 supplement (raw/prometheus_supplement/, written by export_m05_supplement.py):")
    out.append(f"      supplement files:      {_fmt_int(m.supplement_file_count)}")
    out.append(f"      supplement values:     {_fmt_int(m.supplement_value_count_total)}")
    out.append(f"      unique m05 queries:    {m.supplement_unique_queries}")
    out.append(f"      supplement bytes:      {_fmt_bytes(m.supplement_bytes_total)}")
    if m.supplement_query_examples:
        out.append(f"      m05 query keys (first 12):")
        for q in m.supplement_query_examples[:12]:
            out.append(f"        - {q}")
        if len(m.supplement_query_examples) > 12:
            out.append(f"        ... (+{len(m.supplement_query_examples)-12} more)")

    t = report.traces
    out.append("")
    out.append("[6] Traces (Tempo)")
    out.append(f"    files:                   {_fmt_int(t.file_count)}")
    out.append(f"    spans total:             {_fmt_int(t.span_count_total)}")
    out.append(f"    services in traces:      {len(t.services_in_traces)}")
    out.append(f"    avg spans / file:        {t.spans_per_file_mean:,.0f}")
    out.append(f"    bytes:                   {_fmt_bytes(t.bytes_total)}")

    out.append("")
    out.append("Paper-ready totals:")
    out.append(f"  - {c.run_count} controlled dataset runs across {len(c.scenario_families)} scenario families")
    out.append(f"  - {c.episode_count:,} incident episodes, {w.total:,} 60s telemetry windows")
    out.append(f"  - {j.issue_count} synthetic Jira tickets ({j.description_words_mean:.0f} words avg)")
    out.append(f"  - {l.line_count_total:,} log lines across {l.file_count:,} per-window Loki dumps")
    out.append(f"  - {m.sample_count_total:,} Prometheus samples across {m.unique_metric_names} unique metric names")
    out.append(f"  - {t.span_count_total:,} OpenTelemetry spans across {len(t.services_in_traces)} services")
    out.append(f"  - {_fmt_bytes(c.raw_bytes_total)} total on-disk raw telemetry")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-prefix",
        required=True,
        help="Glob prefix for runs under data/runs/, e.g. 2026-05-25-dataset-v5-quick",
    )
    parser.add_argument(
        "--global-id",
        default=None,
        help="Global derived dataset id (under data/derived/global/). "
             "If omitted, attempts auto-detect from runs-prefix (suffix -global).",
    )
    parser.add_argument("--runs-root", default=None, help="Override data/runs root.")
    parser.add_argument("--derived-root", default=None, help="Override data/derived/global root.")
    parser.add_argument("--output", default=None, help="Override metadata JSON output path.")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use file-size-based extrapolation instead of exact line counts (much faster).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, mp.cpu_count() - 1),
        help="Worker processes for log/metric/trace parsing.",
    )
    args = parser.parse_args()

    repo_root = _repo_root_from_script()
    runs_root = Path(args.runs_root) if args.runs_root else (repo_root / "data" / "runs")
    derived_root = (
        Path(args.derived_root)
        if args.derived_root
        else (repo_root / "data" / "derived" / "global")
    )

    run_dirs = sorted(p for p in runs_root.glob(f"{args.runs_prefix}*") if p.is_dir())
    if not run_dirs:
        print(f"warning: no runs matched {args.runs_prefix!r} under {runs_root}", file=sys.stderr)

    # Try to find the global derived dataset
    global_dir: Path | None = None
    candidates: list[Path] = []
    if args.global_id:
        candidates.append(derived_root / args.global_id)
    else:
        # Heuristic: look for any directory under derived_root that starts
        # with runs-prefix.
        for d in derived_root.glob(f"{args.runs_prefix}*"):
            if d.is_dir() and (d / "global-triage-examples.jsonl").exists():
                candidates.append(d)
    for c in candidates:
        if (c / "global-triage-examples.jsonl").exists():
            global_dir = c
            break

    print(f"runs: {len(run_dirs)} matching {args.runs_prefix!r}", file=sys.stderr)
    print(f"global dataset: {global_dir}", file=sys.stderr)
    print(f"workers: {args.workers}, fast: {args.fast}", file=sys.stderr)

    coll, _ = collect_collection_stats(runs_root, run_dirs)
    windows = collect_window_stats(global_dir)
    jira = collect_jira_stats(run_dirs)
    print("counting logs...", file=sys.stderr)
    logs = collect_log_stats(run_dirs, fast=args.fast, workers=args.workers)
    print("counting metrics...", file=sys.stderr)
    metrics = collect_metric_stats(run_dirs, fast=args.fast, workers=args.workers)
    print("counting traces...", file=sys.stderr)
    traces = collect_trace_stats(run_dirs, fast=args.fast, workers=args.workers)

    report = DatasetMetadata(
        dataset_id=(global_dir.name if global_dir else args.runs_prefix),
        runs_prefix=args.runs_prefix,
        generated_at=datetime.now(timezone.utc).isoformat(),
        collection=coll,
        windows=windows,
        jira=jira,
        logs=logs,
        metrics=metrics,
        traces=traces,
    )

    print(render_summary(report))

    if args.output:
        out_path = Path(args.output)
    elif global_dir:
        out_path = global_dir / "dataset-metadata.json"
    else:
        out_path = repo_root / f"{args.runs_prefix}-metadata.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    print(f"\nWrote metadata JSON to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
