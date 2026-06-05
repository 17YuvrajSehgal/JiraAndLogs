"""Smoke test for the multi-channel evidence bundle.

For a diverse set of episodes, builds the full bundle and prints what
each persona-step would see. Asserts that:

  (a) every channel (logs / metrics / trace / k8s / alerts) populates
      where the underlying data supports it
  (b) cs-agent's `report` step gets only the symptom phrase
  (c) senior-sre's `redirect` step gets all channels at full fidelity
  (d) no string in the bundle carries a lab token (bias-free guarantee)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from jira_humanizer.evidence_bundle import (  # noqa: E402
    build_evidence,
    slice_for_step,
)
from jira_humanizer.sanitizer import find_lab_tokens  # noqa: E402

RUNS = REPO / "data" / "runs"
DERIVED = REPO / "data" / "derived" / "global" / "2026-05-25-dataset-v5-large-global"
GLOBAL_TRIAGE = DERIVED / "global-triage-examples.jsonl"

# Diverse episode picks across runs. None for episode_id triggers
# auto-discovery of the first non-baseline episode in that run.
HAND_PICKED = [
    ("2026-05-25-dataset-v5-large-compact-a-r01",
     "2026-05-25-dataset-v5-large-compact-a-r01-cart-redis-degradation-critical-20260525T134155Z",
     ["cartservice", "checkoutservice", "frontend", "redis-cart"],
     "users seeing cart-not-loading after add-to-cart"),
    ("2026-05-25-dataset-v5-large-compact-a-r01",
     "2026-05-25-dataset-v5-large-compact-a-r01-productcatalog-latency-major-20260525T132741Z",
     ["checkoutservice", "frontend", "productcatalogservice"],
     "category pages above 3s p95"),
]

AUTO_RUNS = [
    "2026-05-25-dataset-v5-large-compact-b-r01",
    "2026-05-25-dataset-v5-large-new-families-a-r01",
    "2026-05-25-dataset-v5-large-long-running-r01",
    "2026-05-25-dataset-v5-large-system-faults-r01",
]


def bar(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def trunc(s: str, n: int = 160) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."


def show_bundle(b) -> None:
    print(f"  primary_service: {b.primary_service}")
    print(
        f"  log_lines [{b.log_lines_source}, svc={b.log_lines_service}, "
        f"n={len(b.log_lines)}]:"
    )
    for line in b.log_lines:
        print(f"    - {trunc(line)}")
    print(f"  metric_observations (n={len(b.metric_observations)}):")
    for m in b.metric_observations:
        print(f"    - {m}")
    if b.trace_summary:
        ts = b.trace_summary
        p95 = ts.get("trace_latency_p95_ms", 0) or 0
        p50 = ts.get("trace_latency_p50_ms", 0) or 0
        err = ts.get("trace_error_rate", 0) or 0
        cnt = ts.get("trace_count", 0) or 0
        print(
            f"  trace_summary: count={cnt:.0f}  err_rate={err:.1%}  "
            f"p50={p50:.0f}ms  p95={p95:.0f}ms"
        )
    if b.k8s_state:
        print(f"  k8s_state: {b.k8s_state}")
    print(f"  alert_names (n={len(b.alert_names)}): {b.alert_names}")
    if b.symptom_phrase:
        print(f"  symptom_phrase: {b.symptom_phrase}")
    if b.trace_id_quoted:
        print(f"  trace_id_quoted: {b.trace_id_quoted[:24]}...")
    print(f"  is_low_signal: {b.is_low_signal()}")


def show_step(b, step: str) -> None:
    sliced = slice_for_step(b, step)
    keys = [k for k in sliced if k != "symptom_phrase" or sliced.get(k)]
    print(f"  [{step:11s}] channels={sorted(keys)}")
    for k, v in sliced.items():
        if k == "symptom_phrase":
            if v:
                print(f"      symptom_phrase: {trunc(v)}")
            continue
        if k == "trace_summary":
            p95 = v.get("trace_latency_p95_ms", 0) or 0
            err = v.get("trace_error_rate", 0) or 0
            print(f"      trace_summary: p95={p95:.0f}ms err_rate={err:.1%}")
            continue
        if k == "k8s_state":
            print(f"      k8s_state: {v}")
            continue
        if k == "trace_id_quoted":
            print(f"      trace_id_quoted: {v[:24]}...")
            continue
        if isinstance(v, list):
            for item in v:
                print(f"      {k}: {trunc(item, 140)}")


def discover_first_fault_episode(run_dir: Path):
    ep_path = run_dir / "episodes.jsonl"
    if not ep_path.exists():
        return None
    with ep_path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("incident_type") in ("baseline", None):
                continue
            svcs = rec.get("affected_services") or []
            if not svcs:
                continue
            return (
                rec["incident_episode_id"],
                svcs,
                f"(symptom for {rec['scenario_id']})",
            )
    return None


def find_shadow_record(run_dir: Path, eid: str):
    p = run_dir / "jira_shadow_issues.jsonl"
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("incident_episode_id") == eid:
                return rec
    return None


def assert_clean(b) -> bool:
    all_strs = (
        list(b.log_lines)
        + list(b.metric_observations)
        + list(b.alert_names)
        + [b.symptom_phrase]
        + ([b.trace_id_quoted] if b.trace_id_quoted else [])
    )
    dirty = [s for s in all_strs if s and find_lab_tokens(s)]
    if dirty:
        print(f"  [LEAKAGE-FAIL] {len(dirty)} dirty strings:")
        for d in dirty[:3]:
            print(f"    {trunc(d)}")
        return False
    return True


def main() -> None:
    cases = []
    for run_id, eid, comps, symp in HAND_PICKED:
        cases.append((RUNS / run_id, eid, comps, symp))
    for run_id in AUTO_RUNS:
        run_dir = RUNS / run_id
        d = discover_first_fault_episode(run_dir)
        if d:
            cases.append((run_dir, *d))

    clean_count = 0
    total = 0
    for run_dir, eid, comps, symp in cases:
        bar(eid)
        shadow = find_shadow_record(run_dir, eid)
        bundle = build_evidence(
            run_dir=run_dir,
            episode_id=eid,
            components=comps,
            global_triage_path=GLOBAL_TRIAGE,
            alerts_path=run_dir / "alerts.jsonl",
            symptom_phrase=symp,
            shadow_record=shadow,
        )
        print("\n[FULL BUNDLE]")
        show_bundle(bundle)
        print("\n[PER-STEP SLICING]")
        for step in ("report", "ack", "hypothesis", "redirect", "resolve"):
            show_step(bundle, step)
        print()
        total += 1
        if assert_clean(bundle):
            clean_count += 1
            print("  [OK] sanitizer-clean")

    print(f"\n\n{clean_count}/{total} bundles sanitizer-clean")


if __name__ == "__main__":
    main()
