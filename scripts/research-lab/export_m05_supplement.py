#!/usr/bin/env python3
"""Re-export M0-M5 Prometheus metrics for an already-collected dataset run
prefix and write supplement files alongside the existing raw exports.

The original export-telemetry-window.ps1 only fires 5 Prometheus queries
(pod_info, restarts, cpu_usage, memory_working_set, alerts). The M4 phase
of the telemetry upgrade added many more metrics (RED, per-dependency
client, business counters, runtime gauges) that are scraped by Prometheus
via the M4.1f ServiceMonitor — but they are NOT extracted into the
per-window raw exports.

This script back-fills those metrics for an existing collection by
re-querying Prometheus at each window's end_time, using PromQL aggregations
to summarise the metric over the window's duration. The output goes into
`raw/prometheus_supplement/<window_id>.json` (a sibling of the existing
`raw/prometheus/<window_id>.json` file) so the original exports are
untouched.

Usage (with Prom port-forwarded to localhost:19099):

    kubectl -n observability port-forward \\
      pod/prometheus-kube-prometheus-stack-prometheus-0 19099:9090 &
    .venv/Scripts/python.exe scripts/research-lab/export_m05_supplement.py \\
      --run-prefix 2026-05-25-dataset-v5-quick \\
      --prometheus-url http://127.0.0.1:19099

Build pipeline integration:

    triage_labels.numeric_features_from_raw() also reads the supplement
    file via `_safe_read_json(raw / 'prometheus_supplement' / f'{window_id}.json')`
    when present. New triage_feature_m05_* columns are emitted alongside the
    existing 28 v4 columns; build_global_triage_dataset.py already does
    dynamic key discovery so the global aggregate picks them up
    automatically.

Expected runtime: ~5-15 minutes for 1000 windows on a healthy cluster.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Metric catalog — what we extract from each window
#
# Naming convention: triage_feature_m05_<area>_<dim>_<reduction>
#   area:      payments | cart_operations | orders_placed | recommendations |
#              catalog_lookups | rpc_server | runtime
#   dim:       optional label dimension (success / error / add / get / etc.)
#   reduction: per_sec (counter rate over window) | max (gauge peak) | rate
#
# Every entry is a (output_feature_key, PromQL fragment). The fragment is
# templated with <DURATION> (window length in seconds) and is evaluated as
# an instant query at the window's end_time. {{NS}} is filled with the
# online-boutique-research namespace selector. {{POD}} is filled with the
# per-service pod regex selector (only used by per-service queries).
# ---------------------------------------------------------------------------

NS = 'namespace="online-boutique-research"'

# Per-language metric-name dispatch (added 2026-05-26 after per-service
# coverage discovery showed only Go services emit `rpc_server_*`):
#
#   "go-rpc"  : checkout/productcatalog/shipping — emit rpc_server_* via the
#               shared hipstershop/rpclog interceptor (M2.1 / M4.2).
#   "go-http" : frontend — gRPC-client-side only for downstream calls
#               (rpc_client_*), HTTP server side via the otelhttp middleware
#               (http_server_request_duration_seconds_*).
#   "dotnet"  : cartservice — Kestrel + AspNetCore middleware emit
#               http_server_request_duration_seconds_* (with
#               http_response_status_code label). Runtime via
#               process_runtime_dotnet_gc_*.
#   "node"    : paymentservice, currencyservice — NO server-side RED metrics
#               scraped today (the OTel Grpc/Node SDK isn't wired into a
#               Prom exporter that lands in our ServiceMonitor). Business
#               counter `payments_total` is cluster-wide and works.
#   "python"  : recommendationservice, emailservice — NO server-side RED
#               metrics, but python_gc_* runtime is exposed.
#   "java"    : adservice — NO server-side RED, NO runtime metrics scraped
#               (the OTel Java agent's Prometheus exporter doesn't appear in
#               our ServiceMonitor scrape config). Future M0-M5 follow-up.
#
# Services not in this map fall through to language=unknown which emits 0
# for every per-service query (same behavior as missing metric).
SERVICE_LANG_MAP: dict[str, str] = {
    "frontend": "go-http",
    "checkoutservice": "go-rpc",
    "productcatalogservice": "go-rpc",
    "shippingservice": "go-rpc",
    "cartservice": "dotnet",
    "paymentservice": "node",
    "currencyservice": "node",
    "recommendationservice": "python",
    "emailservice": "python",
    "adservice": "java",
}

# Templates use percent-style placeholders so they don't collide with the
# {label="value"} curly braces inside PromQL. %(ns)s and %(pod)s are filled
# at query time; %(dur)s is the window duration in seconds.
_CLUSTER_QUERIES: list[tuple[str, str]] = [
    # Business counters
    ("m05_payments_success_per_sec",
     'sum(rate(payments_total{%(ns)s,result="success"}[%(dur)ss])) or vector(0)'),
    ("m05_payments_error_per_sec",
     'sum(rate(payments_total{%(ns)s,result!="success"}[%(dur)ss])) or vector(0)'),
    ("m05_cart_operations_success_per_sec",
     'sum(rate(cart_operations_total{%(ns)s,result="success"}[%(dur)ss])) or vector(0)'),
    ("m05_cart_operations_error_per_sec",
     'sum(rate(cart_operations_total{%(ns)s,result!="success"}[%(dur)ss])) or vector(0)'),
    ("m05_orders_placed_per_sec",
     'sum(rate(orders_placed_total{%(ns)s}[%(dur)ss])) or vector(0)'),
    ("m05_recommendations_served_per_sec",
     'sum(rate(recommendations_served_total{%(ns)s}[%(dur)ss])) or vector(0)'),
    ("m05_catalog_lookups_hit_per_sec",
     'sum(rate(catalog_lookups_total{%(ns)s,result="hit"}[%(dur)ss])) or vector(0)'),
    ("m05_catalog_lookups_miss_per_sec",
     'sum(rate(catalog_lookups_total{%(ns)s,result="miss"}[%(dur)ss])) or vector(0)'),
    # RED metrics across the fleet
    ("m05_rpc_server_requests_per_sec",
     'sum(rate(rpc_server_requests_total{%(ns)s}[%(dur)ss])) or vector(0)'),
    ("m05_rpc_server_errors_per_sec",
     'sum(rate(rpc_server_requests_total{%(ns)s,status!="OK"}[%(dur)ss])) or vector(0)'),
    # Latency: p95 across all RPCs via histogram_quantile
    ("m05_rpc_server_duration_p95_seconds",
     'histogram_quantile(0.95, sum by (le) (rate(rpc_server_duration_seconds_bucket{%(ns)s}[%(dur)ss]))) or vector(0)'),
]

# Per-service metrics — keyed by output column name. Each entry maps
# language -> PromQL template (or None when that language doesn't emit
# this metric). At query time we look up SERVICE_LANG_MAP[service_name]
# and pick the right template, falling back to 0 when the entry is None
# or the service isn't mapped.
#
# Column names use the legacy "rpc_server"/"rpc_client" prefixes (the names
# already exist in the build pipeline + derived data), but for HTTP-emitting
# services (frontend/cartservice) they're filled by http_server_* queries —
# semantically still "server-side request rate", just the wire protocol
# differs. Same logic for memory_rss_max which is general-purpose.
_PER_SERVICE_QUERIES: dict[str, dict[str, str | None]] = {
    "m05_svc_rpc_server_requests_per_sec": {
        "go-rpc": 'sum(rate(rpc_server_duration_seconds_count{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "go-http": 'sum(rate(http_server_request_duration_seconds_count{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "dotnet": 'sum(rate(http_server_request_duration_seconds_count{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "node": None,
        "python": None,
        "java": None,
    },
    "m05_svc_rpc_server_errors_per_sec": {
        "go-rpc": 'sum(rate(rpc_server_duration_seconds_count{%(ns)s,pod=~"%(pod)s",status!="OK"}[%(dur)ss])) or vector(0)',
        "go-http": 'sum(rate(http_server_request_duration_seconds_count{%(ns)s,pod=~"%(pod)s",http_response_status_code=~"5.."}[%(dur)ss])) or vector(0)',
        "dotnet": 'sum(rate(http_server_request_duration_seconds_count{%(ns)s,pod=~"%(pod)s",http_response_status_code=~"5.."}[%(dur)ss])) or vector(0)',
        "node": None,
        "python": None,
        "java": None,
    },
    "m05_svc_rpc_client_requests_per_sec": {
        "go-rpc": 'sum(rate(rpc_client_duration_seconds_count{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "go-http": 'sum(rate(rpc_client_duration_seconds_count{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        # cartservice has only Redis client calls (StackExchange.Redis) which
        # don't emit rpc_client_*. Future: extract from db.* span attrs.
        "dotnet": None,
        "node": None,
        "python": None,
        "java": None,
    },
    "m05_svc_rpc_client_errors_per_sec": {
        "go-rpc": 'sum(rate(rpc_client_errors_total{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "go-http": 'sum(rate(rpc_client_errors_total{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "dotnet": None,
        "node": None,
        "python": None,
        "java": None,
    },
    "m05_svc_process_memory_rss_max": {
        "go-rpc": 'max(max_over_time(process_resident_memory_bytes{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "go-http": 'max(max_over_time(process_resident_memory_bytes{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        # .NET emits memory via process_runtime_dotnet_total_allocated_bytes
        # which is cumulative — not directly comparable to RSS. Use the
        # GC committed bytes as a proxy when needed; for now leave at 0
        # rather than mix dimensions.
        "dotnet": None,
        # Node/Python: no process_resident_memory_bytes scraped today.
        "node": None,
        "python": None,
        "java": None,
    },
    "m05_svc_go_goroutines_max": {
        "go-rpc": 'max(max_over_time(go_goroutines{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "go-http": 'max(max_over_time(go_goroutines{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "dotnet": None,
        "node": None,
        "python": None,
        "java": None,
    },
    "m05_svc_dotnet_gc_per_sec": {
        "go-rpc": None,
        "go-http": None,
        "dotnet": 'sum(rate(process_runtime_dotnet_gc_collections_count_total{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "node": None,
        "python": None,
        "java": None,
    },
    "m05_svc_python_gc_per_sec": {
        "go-rpc": None,
        "go-http": None,
        "dotnet": None,
        "node": None,
        "python": 'sum(rate(python_gc_objects_collected_total{%(ns)s,pod=~"%(pod)s"}[%(dur)ss])) or vector(0)',
        "java": None,
    },
}


def _parse_iso(value: str) -> float:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).timestamp()


def _instant_query(
    prom_url: str,
    query: str,
    at_time: float,
    timeout: float = 30.0,
) -> float:
    """Run an instant query, return a scalar (first sample), 0.0 if empty."""
    encoded = urllib.parse.urlencode({"query": query, "time": f"{at_time:.3f}"})
    url = f"{prom_url}/api/v1/query?{encoded}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, json.JSONDecodeError):
        return 0.0
    if data.get("status") != "success":
        return 0.0
    result = data.get("data", {}).get("result", [])
    if not result:
        return 0.0
    # vector format: [{metric:{}, value:[ts, "val"]}, ...]
    first = result[0]
    val = first.get("value", [None, None])
    if val[1] is None:
        return 0.0
    try:
        v = float(val[1])
        return 0.0 if v != v else v  # NaN -> 0
    except (TypeError, ValueError):
        return 0.0


def _supplement_for_window(
    prom_url: str,
    service_name: str,
    start_iso: str,
    end_iso: str,
    min_duration: int = 30,
) -> dict[str, Any]:
    start_sec = _parse_iso(start_iso)
    end_sec = _parse_iso(end_iso)
    duration_s = max(int(end_sec - start_sec), min_duration)
    pod_regex = f"{service_name}-.*"

    out: dict[str, Any] = {
        "window_start": start_iso,
        "window_end": end_iso,
        "duration_seconds": duration_s,
        "service_name": service_name,
        "prom_url": prom_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "queries": {},
        "values": {},
    }
    subs = {"ns": NS, "dur": duration_s, "pod": pod_regex}
    lang = SERVICE_LANG_MAP.get(service_name, "unknown")
    out["language"] = lang
    for key, query_template in _CLUSTER_QUERIES:
        q = query_template % subs
        out["queries"][key] = q
        out["values"][key] = _instant_query(prom_url, q, end_sec)
    for key, lang_dispatch in _PER_SERVICE_QUERIES.items():
        query_template = lang_dispatch.get(lang) if lang_dispatch else None
        if query_template is None:
            # This language doesn't emit the metric (or the service isn't
            # in SERVICE_LANG_MAP) — zero is the correct value, not noise.
            out["queries"][key] = None
            out["values"][key] = 0.0
        else:
            q = query_template % subs
            out["queries"][key] = q
            out["values"][key] = _instant_query(prom_url, q, end_sec)
    return out


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _discover_runs(runs_root: Path, prefix: str) -> list[Path]:
    return sorted(d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith(prefix))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-prefix",
        required=True,
        help="Dataset run prefix (e.g. 2026-05-25-dataset-v5-quick)",
    )
    parser.add_argument("--runs-root", default=str(REPO_ROOT / "data" / "runs"))
    parser.add_argument(
        "--prometheus-url",
        default="http://127.0.0.1:19099",
        help="Prometheus base URL (use port-forward)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-export windows that already have a supplement file",
    )
    parser.add_argument(
        "--limit-runs",
        type=int,
        default=0,
        help="Only process the first N matching runs (for smoke test); 0 = all",
    )
    args = parser.parse_args()

    runs_root = Path(args.runs_root)
    runs = _discover_runs(runs_root, args.run_prefix)
    if not runs:
        print(f"No runs matching prefix {args.run_prefix!r} under {runs_root}", file=sys.stderr)
        return 2
    if args.limit_runs > 0:
        runs = runs[: args.limit_runs]
    print(f"Found {len(runs)} runs matching {args.run_prefix!r}", file=sys.stderr)

    total_windows = 0
    skipped = 0
    written = 0
    failures = 0
    t0 = time.time()
    for run_dir in runs:
        windows_path = run_dir / "telemetry_windows.jsonl"
        if not windows_path.exists():
            print(f"  WARN: no telemetry_windows.jsonl in {run_dir.name}", file=sys.stderr)
            continue
        windows = _read_jsonl(windows_path)
        out_dir = run_dir / "raw" / "prometheus_supplement"
        out_dir.mkdir(parents=True, exist_ok=True)
        run_written = 0
        run_skipped = 0
        run_failed = 0
        for w in windows:
            total_windows += 1
            window_id = w.get("window_id") or w.get("telemetry_window_id")
            service_name = w.get("service_name") or ""
            start_time = w.get("start_time")
            end_time = w.get("end_time")
            if not window_id or not start_time or not end_time:
                run_failed += 1
                continue
            out_path = out_dir / f"{window_id}.json"
            if out_path.exists() and not args.overwrite:
                skipped += 1
                run_skipped += 1
                continue
            try:
                supplement = _supplement_for_window(
                    args.prometheus_url, service_name, start_time, end_time
                )
                with out_path.open("w", encoding="utf-8") as f:
                    json.dump(supplement, f, indent=2)
                written += 1
                run_written += 1
            except Exception as exc:  # noqa: BLE001
                failures += 1
                run_failed += 1
                print(f"    FAIL window {window_id}: {exc}", file=sys.stderr)
        elapsed = time.time() - t0
        print(
            f"  {run_dir.name}: written={run_written} skipped={run_skipped} failed={run_failed} "
            f"[total={written + skipped + failures}/{total_windows}, elapsed={elapsed:.1f}s]",
            file=sys.stderr,
        )

    print(
        f"\nDone. windows={total_windows} written={written} skipped={skipped} failed={failures} "
        f"({time.time() - t0:.1f}s)",
        file=sys.stderr,
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
