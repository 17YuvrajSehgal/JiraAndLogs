"""Separate what the cost saving MEASURES from what it MODELS.

Section VI-C says cost is "measured per window as wall-clock time and
language-model token usage". R2 flagged the cost evaluation as underspecified.
Inspecting the pipeline shows the claim is stronger than the evidence in a
specific, fixable way -- and also that the obvious fix (just measure wall-clock)
would be wrong.

What is actually measured, per window, in the saved traces:
  * which skills ran                      (skill_end events)
  * which skills a gate skipped           (skill_skipped_by_gate events)
  * how long each invocation took         (duration_ms, time.monotonic in runner.py)

What is modelled, in scripts/agent/cost_vs_cascade.py:
  * the per-call token count, wall time and dollar cost of each skill
    (PER_SKILL_COST, a hardcoded table)

The reported 40/63/78% comes from counts x modelled unit costs. The counts are
real; the unit costs are assumptions.

Crucially, the measured durations CANNOT simply replace the modelled ones. The
evaluation harness is predictions-backed: retrieval skills read precomputed
JSONL rather than embedding anything, so their measured duration is on the order
of 10 microseconds. That is the cost of replaying a cached decision, not the
cost of making it. Reporting it as a deployment saving would be far more
misleading than the current estimate.

So this script does three things:
  1. reports the measured quantities (counts, gate skips, replay durations)
  2. shows how little of the headline rests on them
  3. computes the saving's sensitivity to the modelled unit costs, so the paper
     can state how much the conclusion depends on the cost table

Usage:
    python scripts/v2/cost_measured_vs_modelled.py \
        --paper-results paper-results --out paper-results-v2/cost
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

#: The modelled unit costs the published figure depends on, copied from
#: scripts/agent/cost_vs_cascade.py so this analysis is self-contained.
#: (mean_wall_ms, mean_llm_tokens, usd_per_call)
MODELLED: dict[str, tuple[float, int, float]] = {
    "verify_with_llm":               (15400.0, 1969, 0.00050),
    "reformulate_query":             (300.0,    400, 0.00010),
    "extract_entities_llm":          (8000.0,  1500, 0.00040),
    "request_pod_events":            (5.0,       0, 0.0),
    "request_extended_trace_window": (10.0,      0, 0.0),
    "request_pod_metrics":           (5.0,       0, 0.0),
    "request_similar_incident_window": (3.0,     0, 0.0),
    "rerank_with_evidence":          (50.0,      0, 0.0),
}
CHEAP_DEFAULT = (1.0, 0, 0.0)


def scan_traces(trace_root: Path, limit: int | None = None):
    """Walk saved per-window traces; return measured counts and durations."""
    invoked = Counter()
    skipped = Counter()
    durations: dict[str, list[float]] = defaultdict(list)
    n_windows = 0

    files = sorted(trace_root.rglob("*.json"))
    if limit:
        files = files[:limit]
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        events = d.get("events") or []
        if not events:
            continue
        n_windows += 1
        for e in events:
            k, s = e.get("kind"), e.get("skill")
            if not s:
                continue
            if k == "skill_end":
                invoked[s] += 1
                ms = e.get("duration_ms")
                if ms is not None:
                    durations[s].append(float(ms))
            elif k == "skill_skipped_by_gate":
                skipped[s] += 1
    return n_windows, invoked, skipped, durations


def modelled_cost(skill: str) -> tuple[float, int, float]:
    return MODELLED.get(skill, CHEAP_DEFAULT)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paper-results", type=Path, default=Path("paper-results"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--datasets", nargs="+",
                    default=["wol-v3", "online-boutique", "otel-demo"])
    ap.add_argument("--limit", type=int, default=0,
                    help="cap trace files per dataset (0 = all)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    report = {}
    for ds in args.datasets:
        root = args.paper_results / "agent-end-to-end" / ds / "traces"
        if not root.is_dir():
            print(f"[skip] {ds}: no traces at {root}")
            continue
        n, invoked, skipped, durations = scan_traces(
            root, args.limit or None)
        if not n:
            print(f"[skip] {ds}: no parseable traces")
            continue

        print(f"\n{'='*74}\n{ds} -- {n:,} windows with traces\n{'='*74}")
        print(f"{'skill':<34}{'invoked':>9}{'skipped':>9}"
              f"{'measured ms':>13}{'modelled ms':>13}")
        all_skills = sorted(set(invoked) | set(skipped))
        rows = {}
        for s in all_skills:
            meas = statistics.mean(durations[s]) if durations.get(s) else None
            mod = modelled_cost(s)[0]
            rows[s] = {
                "invoked": invoked[s], "skipped_by_gate": skipped[s],
                "measured_ms_mean": meas, "modelled_ms": mod,
                "modelled_tokens": modelled_cost(s)[1],
            }
            print(f"{s:<34}{invoked[s]:>9,}{skipped[s]:>9,}"
                  f"{(f'{meas:.4f}' if meas is not None else '-'):>13}"
                  f"{mod:>13,.1f}")

        # The headline, recomputed from counts x modelled unit costs.
        def totals(use_actual: bool):
            wall = tok = 0.0
            for s in all_skills:
                runs = invoked[s] if use_actual else invoked[s] + skipped[s]
                w, t, _ = modelled_cost(s)
                wall += runs * w
                tok += runs * t
            return wall, tok

        aw, at = totals(True)
        cw, ct = totals(False)
        save_w = 100 * (1 - aw / cw) if cw else 0.0
        save_t = 100 * (1 - at / ct) if ct else 0.0

        # How much of the modelled saving is attributable to a single skill?
        contrib = []
        for s in all_skills:
            w, t, _ = modelled_cost(s)
            contrib.append((skipped[s] * w, s))
        contrib.sort(reverse=True)
        top_ms, top_skill = contrib[0] if contrib else (0.0, "-")
        total_saved_ms = sum(c for c, _ in contrib) or 1.0

        # Sensitivity: the verifier's 15.4s/call is the single largest
        # assumption. What happens to the saving if it is 2x or 0.5x?
        def saving_with_verifier(scale: float) -> float:
            w_a = w_c = 0.0
            for s in all_skills:
                w, _, _ = modelled_cost(s)
                if s == "verify_with_llm":
                    w *= scale
                w_a += invoked[s] * w
                w_c += (invoked[s] + skipped[s]) * w
            return 100 * (1 - w_a / w_c) if w_c else 0.0

        # The strongest check available without a re-run: recompute the saving
        # using each skill's MEASURED mean duration as its unit cost, for the
        # skills we have measurements for. This does not give a deployment cost
        # (the LLM-backed skills are replayed, so their measured cost is near
        # zero), but it answers a different and useful question: does the
        # headline depend on the cost table, or on the gating rates? If the two
        # agree, the saving is driven by how often gates close, and the table's
        # inaccuracy does not threaten the conclusion.
        def saving_measured_units() -> float | None:
            w_a = w_c = 0.0
            for s in all_skills:
                d = durations.get(s)
                if not d:
                    continue
                unit = statistics.mean(d)
                w_a += invoked[s] * unit
                w_c += (invoked[s] + skipped[s]) * unit
            return 100 * (1 - w_a / w_c) if w_c else None

        meas_saving = saving_measured_units()

        # Which skills is the cost table most wrong about?
        mispriced = []
        for s in all_skills:
            d = durations.get(s)
            if not d:
                continue
            meas = statistics.mean(d)
            mod = modelled_cost(s)[0]
            if meas > 0 and mod > 0:
                mispriced.append((max(meas / mod, mod / meas), s, meas, mod))
        mispriced.sort(reverse=True)

        measured_total_ms = sum(sum(v) for v in durations.values())
        print(f"\n  MEASURED  skill invocations {sum(invoked.values()):,}, "
              f"gate skips {sum(skipped.values()):,}")
        print(f"  MEASURED  total harness wall-clock {measured_total_ms:,.1f} ms "
              f"({measured_total_ms/max(1,n):.4f} ms/window)")
        print(f"            -- this is replay of cached predictions, NOT the cost "
              f"of computing them")
        print(f"  MODELLED  saving: wall {save_w:.1f}%  tokens {save_t:.1f}%")
        print(f"            {100*top_ms/total_saved_ms:.0f}% of the modelled "
              f"saving comes from one skill: {top_skill}")
        print(f"  SENSITIVITY to the verifier's assumed 15.4s/call:")
        for sc, lab in ((0.5, "0.5x"), (1.0, "1.0x"), (2.0, "2.0x")):
            print(f"            {lab:>5} -> saving {saving_with_verifier(sc):.1f}%")
        if meas_saving is not None:
            print(f"  CROSS-CHECK using measured durations as unit costs: "
                  f"{meas_saving:.1f}%  (modelled: {save_w:.1f}%)")
            if abs(meas_saving - save_w) < 5.0:
                print(f"            the two agree within {abs(meas_saving-save_w):.1f} pts, "
                      f"so the saving is driven by GATING RATES, not by the cost\n"
                      f"            table -- the table being wrong does not move the headline")
        if mispriced:
            print(f"  COST TABLE ACCURACY (worst first):")
            for ratio, s, meas, mod in mispriced[:4]:
                direction = "under" if meas > mod else "over"
                print(f"            {s:<32} measured {meas:9.4f} ms vs modelled "
                      f"{mod:7.1f} ms  ({ratio:,.0f}x {direction})")

        report[ds] = {
            "n_windows": n,
            "per_skill": rows,
            "measured": {
                "total_invocations": sum(invoked.values()),
                "total_gate_skips": sum(skipped.values()),
                "harness_wall_ms_total": measured_total_ms,
                "harness_wall_ms_per_window": measured_total_ms / max(1, n),
                "caveat": "predictions-backed replay; not deployment cost",
            },
            "modelled": {
                "saving_wall_pct": save_w,
                "saving_tokens_pct": save_t,
                "dominant_skill": top_skill,
                "dominant_share_of_saving": top_ms / total_saved_ms,
                "verifier_sensitivity": {
                    "0.5x": saving_with_verifier(0.5),
                    "1.0x": saving_with_verifier(1.0),
                    "2.0x": saving_with_verifier(2.0),
                },
            },
            "cross_check_measured_units": {
                "saving_wall_pct": meas_saving,
                "agrees_with_modelled_within_pts":
                    (abs(meas_saving - save_w) if meas_saving is not None else None),
            },
            "cost_table_accuracy": [
                {"skill": s, "measured_ms": meas, "modelled_ms": mod, "ratio": ratio}
                for ratio, s, meas, mod in mispriced
            ],
        }

    dest = args.out / "cost-measured-vs-modelled.json"
    dest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[write] {dest}")
    print("\nTakeaway for the paper: the invocation counts and gate skips are")
    print("measured; the per-call unit costs are assumptions. Report the saving")
    print("as counts x a published cost model, and give the sensitivity above")
    print("rather than calling it a measured wall-clock reduction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
