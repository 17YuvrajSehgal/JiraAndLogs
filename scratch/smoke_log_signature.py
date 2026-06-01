"""Diverse smoke test for the V2 log-signature pipeline.

Auto-discovers episodes from many run types (compact, new-families,
long-running, system-faults, control) so we don't over-engineer around
one scenario. For each unique scenario family seen, runs:

  * signature_for_episode  — top-level: diff + cross-service fallback
  * per-component diff stats — verifies the diff is dropping
    background-chatter templates that appear in both active and
    pre-fault baseline windows
  * (for baseline runs) extract_log_signature on observation_window —
    sanity check that baselines are quiet

Goal: confirm the V2 pipeline produces engineer-vocabulary lines that
are actually distinctive to the fault, not random noise and not
identical to pre-fault chatter.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from memorygraph.log_signatures import (
    extract_characteristic_signature,
    extract_log_signature,
    signature_for_episode,
)

RUNS = REPO / "data" / "runs"

SAMPLE_RUNS = [
    "2026-05-25-dataset-v5-large-compact-a-r01",
    "2026-05-25-dataset-v5-large-compact-a-r05",
    "2026-05-25-dataset-v5-large-compact-b-r01",
    "2026-05-25-dataset-v5-large-new-families-a-r01",
    "2026-05-25-dataset-v5-large-new-families-b-r01",
    "2026-05-25-dataset-v5-large-long-running-r01",
    "2026-05-25-dataset-v5-large-system-faults-r01",
    "2026-05-25-dataset-v5-large-control-r01",
]

PER_COMPONENT_CAP = 3


def bar(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def show(label: str, line: str, indent: str = "    ") -> None:
    if len(line) > 180:
        line = line[:177] + "..."
    print(f"{indent}{label}{line}")


def discover_episodes(run_id: str) -> list[dict]:
    ep_path = RUNS / run_id / "episodes.jsonl"
    if not ep_path.exists():
        return []
    out: list[dict] = []
    with ep_path.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append({
                "incident_episode_id": obj["incident_episode_id"],
                "scenario_id": obj.get("scenario_id", "?"),
                "affected_services": obj.get("affected_services") or [],
                "severity": obj.get("severity", "?"),
                "incident_type": obj.get("incident_type", "?"),
                "root_cause_category": obj.get("root_cause_category", "?"),
            })
    return out


def run_fault_episode(run_dir: Path, ep: dict) -> None:
    eid = ep["incident_episode_id"]
    svc_list = ep["affected_services"]
    header = (
        f"-- scenario={ep['scenario_id']}  sev={ep['severity']}  "
        f"root={ep['root_cause_category']}  services={svc_list}"
    )
    print(header)

    svc_used, sig, source = signature_for_episode(
        run_dir, eid, svc_list, top_k=5,
    )
    print(f"   [signature_for_episode] svc_used={svc_used}  source={source}  n={len(sig)}")
    if not sig:
        print("      (no signature from any component — empty ticket case)")
    else:
        for i, line in enumerate(sig, 1):
            show(f"{i}. ", line, "      ")

    # Per-component breakdown so we can see whether diff dropped
    # background-chatter templates that plain top-K would have kept.
    loki_dir = run_dir / "raw" / "loki"
    print(f"   [per-component diff vs plain]")
    for svc in svc_list[:PER_COMPONENT_CAP]:
        active = loki_dir / f"{eid}-active_fault-{svc}.json"
        baseline = loki_dir / f"{eid}-pre_fault_baseline-{svc}.json"
        if not active.exists():
            print(f"      {svc}: NO active dump")
            continue
        plain = extract_log_signature(active, top_k=5)
        diff: list = []
        if baseline.exists():
            diff = extract_characteristic_signature(
                active, baseline, top_k=5,
            )
        baseline_marker = "(no baseline)" if not baseline.exists() else ""
        print(
            f"      {svc}: plain={len(plain)}  diff={len(diff)} {baseline_marker}"
        )
        for t, score, a, b in diff:
            show(f"DIFF score={score:5.1f} a={a:>3d} b={b:>3d}: ", t, "        ")
        # Show plain templates that were DROPPED by the diff (background chatter)
        if baseline.exists():
            kept_templates = {t for t, _, _, _ in diff}
            dropped = [t for t in plain if t not in kept_templates]
            for t in dropped[:3]:
                show("PLAIN-but-DROPPED-by-diff: ", t, "        ")


def run_baseline_episode(run_dir: Path, ep: dict) -> None:
    """For baseline-normal-traffic: there's no active_fault. Just
    show observation_window signatures to confirm baselines are quiet."""
    eid = ep["incident_episode_id"]
    svc_list = ep["affected_services"]
    print(f"-- BASELINE scenario={ep['scenario_id']}  services={svc_list}")
    loki_dir = run_dir / "raw" / "loki"
    for svc in svc_list[:PER_COMPONENT_CAP]:
        obs = loki_dir / f"{eid}-observation_window-{svc}.json"
        if not obs.exists():
            print(f"      {svc}: NO observation dump")
            continue
        plain = extract_log_signature(obs, top_k=5)
        print(f"      {svc}: observation_window plain={len(plain)}")
        for t in plain[:3]:
            show("OBS: ", t, "        ")


def main() -> None:
    seen_scenarios: set[str] = set()
    for run_id in SAMPLE_RUNS:
        run_dir = RUNS / run_id
        if not run_dir.exists():
            continue
        episodes = discover_episodes(run_id)
        if not episodes:
            continue
        bar(f"{run_id}  ({len(episodes)} episodes)")
        for ep in episodes:
            sid = ep["scenario_id"]
            if sid in seen_scenarios:
                continue
            seen_scenarios.add(sid)
            if ep["incident_type"] == "baseline" or not ep["affected_services"]:
                run_baseline_episode(run_dir, ep)
            else:
                run_fault_episode(run_dir, ep)

    print(f"\n\n{len(seen_scenarios)} unique scenarios sampled across runs.")


if __name__ == "__main__":
    main()
