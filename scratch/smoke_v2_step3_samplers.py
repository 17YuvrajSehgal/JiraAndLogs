"""Distribution sanity check for V2 step 3 samplers.

Runs each sampler over 10,000 synthetic episode_ids and verifies the
realized distribution is within +/- 2% of the §13.1 TAWOS target.
Catches regression on the sampling logic before we burn LM Studio time.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jira_humanizer.timeline_generator import (  # noqa: E402
    _RESOLUTION_DISTRIBUTION,
    _RESOLUTION_TIME_BUCKETS,
    _sample_comment_count,
    _sample_resolution,
    _sample_resolution_time_s,
    _pick_report_persona,
    _build_step_sequence,
)


N = 10_000
TOLERANCE = 0.02


def check_resolution() -> bool:
    counter: Counter[str] = Counter()
    for i in range(N):
        counter[_sample_resolution(f"ep-{i}")] += 1
    print("\n[resolution outcome]")
    ok = True
    for outcome, target in _RESOLUTION_DISTRIBUTION.items():
        actual = counter[outcome] / N
        delta = actual - target
        flag = "ok" if abs(delta) < TOLERANCE else "FAIL"
        if abs(delta) >= TOLERANCE:
            ok = False
        print(f"  {flag:4s} {outcome:18s} actual={actual:.3f}  target={target:.3f}  delta={delta:+.3f}")
    return ok


def check_resolution_time() -> bool:
    buckets = Counter()
    for i in range(N):
        secs = _sample_resolution_time_s(f"ep-{i}")
        for low, high, prob in _RESOLUTION_TIME_BUCKETS:
            if low <= secs <= high:
                buckets[(low, high)] += 1
                break
    print("\n[resolution_time_s]")
    ok = True
    for low, high, target in _RESOLUTION_TIME_BUCKETS:
        actual = buckets[(low, high)] / N
        delta = actual - target
        flag = "ok" if abs(delta) < TOLERANCE else "FAIL"
        if abs(delta) >= TOLERANCE:
            ok = False
        print(f"  {flag:4s} {low:>9d}s - {high:>9d}s  actual={actual:.3f}  target={target:.3f}")
    return ok


def check_comment_count() -> bool:
    counts = Counter()
    for i in range(N):
        n = _sample_comment_count(f"ep-{i}")
        counts[n] += 1
    # Bucket per §13.1
    bucket_1 = counts[1] / N
    bucket_2_5 = sum(counts[i] for i in range(2, 6)) / N
    bucket_6_12 = sum(counts[i] for i in range(6, 13)) / N
    bucket_13_15 = sum(counts[i] for i in range(13, 16)) / N
    avg_count = sum(k * v for k, v in counts.items()) / N
    print("\n[comment_count]")
    print(f"  N=1:       actual={bucket_1:.3f}  target ~0.39")
    print(f"  N=2-5:     actual={bucket_2_5:.3f}  target ~0.43")
    print(f"  N=6-12:    actual={bucket_6_12:.3f}  target ~0.14 (clipped from 6-15)")
    print(f"  N=13-15:   actual={bucket_13_15:.3f}  target ~0.04 (clipped from 15+)")
    print(f"  avg: {avg_count:.2f}  min={min(counts)}  max={max(counts)}")
    ok = (
        abs(bucket_1 - 0.39) < TOLERANCE
        and abs(bucket_2_5 - 0.43) < TOLERANCE
        and abs(bucket_6_12 - 0.14) < TOLERANCE
        and abs(bucket_13_15 - 0.04) < TOLERANCE
    )
    return ok


def check_reporter_persona() -> bool:
    print("\n[reporter persona by severity]")
    targets = {
        "high":   {"oncall-sre": 0.70, "cs-agent": 0.30},
        "medium": {"oncall-sre": 0.50, "cs-agent": 0.50},
        "low":    {"oncall-sre": 0.20, "cs-agent": 0.80},
    }
    ok = True
    for sev, target_dist in targets.items():
        c: Counter[str] = Counter()
        for i in range(N):
            c[_pick_report_persona(f"ep-{i}-{sev}", sev)] += 1
        for role, target in target_dist.items():
            actual = c[role] / N
            delta = actual - target
            flag = "ok" if abs(delta) < TOLERANCE else "FAIL"
            if abs(delta) >= TOLERANCE:
                ok = False
            print(f"  {flag:4s} sev={sev:7s} role={role:11s} actual={actual:.3f}  target={target:.3f}")
    return ok


def check_step_sequences() -> bool:
    """Spot-check that _build_step_sequence produces sensible specs."""
    print("\n[step sequence builder]")
    cases = [
        ("ep-N1", 1, False, False, [], 0),       # minimum: no middle
        ("ep-N2", 2, False, False, [], 1),       # just ack
        ("ep-N3", 3, False, False, [], 2),       # ack + hypothesis
        ("ep-N4", 4, True, False, [], 3),        # ack + hyp + redirect
        ("ep-N4-noredir", 4, False, False, [], 3),  # ack + hyp + extra
        ("ep-N8", 8, False, False, [], 7),       # ack + hyp + 5 extras
        ("ep-N15", 15, True, True, ["redis-cart"], 14),  # max depth
    ]
    ok = True
    for episode_id, target_count, misattr, wrong_hyp, components, expected_middle in cases:
        specs = _build_step_sequence(
            episode_id=episode_id,
            comment_count=target_count,
            misattr_enabled=misattr,
            wrong_hyp_enabled=wrong_hyp,
            components_seen=components,
        )
        flag = "ok" if len(specs) == expected_middle else "FAIL"
        if len(specs) != expected_middle:
            ok = False
        roles = [s.persona_role for s in specs]
        print(f"  {flag:4s} N={target_count:2d} expected_mid={expected_middle:2d} got_mid={len(specs):2d}  roles={roles}")
    return ok


def main() -> int:
    all_ok = True
    all_ok &= check_resolution()
    all_ok &= check_resolution_time()
    all_ok &= check_comment_count()
    all_ok &= check_reporter_persona()
    all_ok &= check_step_sequences()
    print(f"\n=== overall: {'PASS' if all_ok else 'FAIL'} ===")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
