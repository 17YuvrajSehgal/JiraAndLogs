"""Build the per-window escalation-value table — prerequisite for the learned controller.

The controller's central decision is binary: for this window, do we stay on the
cheap path (dense retrieval + composition), or do we escalate to the expensive
one (sparse + graph fusion, reformulation, evidence re-ranking)?

The submission answered that with two hand-set thresholds (numeric triage < 0.90,
retriever confidence < 0.5). This script builds the data needed to answer it with
a learned policy instead, by extracting the *counterfactual* that the existing
ablation cells already contain but never exposed:

    cheap outcome      = `dense_only` cell   (escalation gate never opens)
    escalated outcome  = `baseline` cell     (escalation gate always opens)
    escalation value   = escalated - cheap,  per window, per metric

`dense_only` skips exactly the skills the escalation gate controls
(retrieve_hybrid_fusion, retrieve_knowledge_graph, retrieve_log_sequence,
verify_with_llm, triage_numeric — see scripts/agent/skill_ablation.py), so the
pairing is the right one.

The headline this produces is the *headroom*: what fraction of windows does
escalation actually help, hurt, or leave unchanged? A large "unchanged" mass is
not a disappointment — it is precisely the budget a well-targeted policy can
reclaim, and it is the go/no-go evidence for whether the learned controller is
worth building.

Outputs
-------
  escalation-value-<dataset>.jsonl   one row per window (the training set)
  escalation-headroom.json           aggregate headroom + oracle ceiling

Usage
-----
    python scripts/v2/build_escalation_value_set.py \
        --paper-results paper-results --out paper-results-v2/escalation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CHEAP_CELL = "dense_only"
ESCALATED_CELL = "baseline"

#: Skills that only run once an escalation gate opens. Used to measure how often
#: the *shipped* hand-tuned controller actually escalates, which is the baseline
#: a learned policy has to beat on cost.
EXPENSIVE_SKILLS = frozenset({
    "retrieve_hybrid_fusion", "retrieve_hybrid_fusion_llm",
    "retrieve_knowledge_graph", "retrieve_log_sequence",
    "verify_with_llm", "reformulate_query", "rerank_with_evidence",
})

#: Metrics we carry through; hit_at_5 is the paper's headline, hit_at_1 the one
#: the evidence tools were supposed to move.
METRICS = ("hit_at_1", "hit_at_5", "reciprocal_rank")


def load_cell(root: Path, dataset: str, cell: str) -> dict[str, dict] | None:
    p = root / "agent-value" / dataset / "skill-cells" / f"{cell}-report.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return {c["bundle_id"]: c for c in d.get("case_results", [])}


def cost_of(case: dict) -> dict:
    c = (case.get("decision") or {}).get("cost") or {}
    return {
        "llm_tokens": float(c.get("llm_tokens") or 0.0),
        "wall_seconds": float(c.get("wall_seconds") or 0.0),
        "usd": float(c.get("usd") or 0.0),
        "n_calls": float(c.get("n_calls") or 0.0),
    }


def build(root: Path, dataset: str) -> tuple[list[dict], dict] | None:
    cheap = load_cell(root, dataset, CHEAP_CELL)
    esc = load_cell(root, dataset, ESCALATED_CELL)
    if cheap is None or esc is None:
        print(f"[skip] {dataset}: missing {CHEAP_CELL} or {ESCALATED_CELL} cell")
        return None

    rows: list[dict] = []
    for wid, c in cheap.items():
        e = esc.get(wid)
        if e is None:
            continue
        # Retrieval metrics are None for windows with no gold match; those
        # windows cannot inform an escalation-value label, but they still carry
        # cost, so we keep them flagged rather than dropping them silently.
        evaluable = c.get("hit_at_5") is not None and e.get("hit_at_5") is not None

        row: dict = {
            "window_id": wid,
            "dataset": dataset,
            "evaluable": evaluable,
            "gold_triage": c.get("gold_triage"),
            "cheap_confidence": (c.get("decision") or {}).get("confidence"),
            "cheap_triage_score": (c.get("decision") or {}).get("triage_score"),
            "escalated_confidence": (e.get("decision") or {}).get("confidence"),
            "cheap_skills": (c.get("decision") or {}).get("skills_invoked") or [],
            "escalated_skills": (e.get("decision") or {}).get("skills_invoked") or [],
        }
        for m in METRICS:
            cv, ev = c.get(m), e.get(m)
            row[f"cheap_{m}"] = cv
            row[f"escalated_{m}"] = ev
            row[f"delta_{m}"] = (ev - cv) if (cv is not None and ev is not None) else None

        cc, ec = cost_of(c), cost_of(e)
        row["cheap_cost"] = cc
        row["escalated_cost"] = ec
        row["delta_cost"] = {k: ec[k] - cc[k] for k in cc}

        # The policy label: does escalating change the headline metric, and how?
        d5 = row["delta_hit_at_5"]
        row["escalation_label"] = (
            None if d5 is None else "helps" if d5 > 0 else "hurts" if d5 < 0 else "no_change"
        )
        rows.append(row)

    ev_rows = [r for r in rows if r["evaluable"]]
    n = len(ev_rows) or 1
    counts = {k: sum(1 for r in ev_rows if r["escalation_label"] == k)
              for k in ("helps", "hurts", "no_change")}

    def mean(key):
        vals = [r[key] for r in ev_rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    # Oracle ceiling: escalate only where it helps. This is the upper bound any
    # policy could reach, and the honest ceiling to quote when motivating one.
    oracle_hit5 = sum(max(r["cheap_hit_at_5"], r["escalated_hit_at_5"]) for r in ev_rows) / n
    always_hit5 = mean("escalated_hit_at_5")
    never_hit5 = mean("cheap_hit_at_5")
    esc_frac_oracle = counts["helps"] / n

    # Cost is measured over ALL windows, not just the evaluable ones, since a
    # policy pays for every window it escalates.
    tok_always = sum(r["escalated_cost"]["llm_tokens"] for r in rows)
    tok_never = sum(r["cheap_cost"]["llm_tokens"] for r in rows)

    # How often does the SHIPPED hand-tuned controller actually escalate? This
    # is the number a learned policy must beat, and it is not 100% — the gates
    # already suppress some escalation. Measured from the baseline cell's
    # recorded skill invocations.
    shipped_escalations = sum(
        1 for r in rows if set(r["escalated_skills"]) & EXPENSIVE_SKILLS
    )
    shipped_rate = shipped_escalations / max(1, len(rows))

    summary = {
        "dataset": dataset,
        "n_windows": len(rows),
        "n_evaluable": len(ev_rows),
        "label_counts": counts,
        "label_fractions": {k: v / n for k, v in counts.items()},
        "hit_at_5": {
            "never_escalate": never_hit5,
            "always_escalate": always_hit5,
            "oracle": oracle_hit5,
            "headroom_over_always": oracle_hit5 - always_hit5,
            "value_of_escalating_at_all": always_hit5 - never_hit5,
        },
        "escalation_rate": {
            "shipped_hand_tuned_gates": shipped_rate,
            "oracle_only_where_it_helps": esc_frac_oracle,
            "reduction_factor": (shipped_rate / esc_frac_oracle)
            if esc_frac_oracle > 0 else None,
        },
        "llm_tokens": {
            "always_escalate": tok_always,
            "never_escalate": tok_never,
            "oracle_if_only_helpful": tok_never
            + (tok_always - tok_never) * esc_frac_oracle,
        },
    }
    return rows, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paper-results", type=Path, default=Path("paper-results"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--datasets", nargs="+",
                    default=["online-boutique", "otel-demo", "wol-v3"])
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    summaries = []
    for ds in args.datasets:
        got = build(args.paper_results, ds)
        if not got:
            continue
        rows, summary = got
        dest = args.out / f"escalation-value-{ds}.jsonl"
        with dest.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        summaries.append(summary)

        f = summary["label_fractions"]
        h = summary["hit_at_5"]
        e = summary["escalation_rate"]
        print(f"\n=== {ds} ===")
        print(f"  windows={summary['n_windows']:,}  evaluable={summary['n_evaluable']:,}")
        print(f"  escalation changes Hit@5:  helps {f['helps']:.3%}   "
              f"hurts {f['hurts']:.3%}   no change {f['no_change']:.3%}")
        print(f"  Hit@5  never={h['never_escalate']:.4f}  "
              f"always={h['always_escalate']:.4f}  oracle={h['oracle']:.4f}")
        print(f"  value of escalating at all : {h['value_of_escalating_at_all']:+.4f}")
        print(f"  accuracy headroom of a perfect policy over always-escalate: "
              f"{h['headroom_over_always']:+.4f}")
        print(f"  escalation rate — shipped gates {e['shipped_hand_tuned_gates']:.1%}"
              f"  vs oracle {e['oracle_only_where_it_helps']:.1%}"
              + (f"  ({e['reduction_factor']:.1f}x reducible)"
                 if e["reduction_factor"] else "  (oracle: never escalate)"))
        print(f"  -> wrote {dest.name} ({len(rows):,} rows)")

    dest = args.out / "escalation-headroom.json"
    dest.write_text(json.dumps({"datasets": summaries}, indent=2), encoding="utf-8")
    print(f"\n[write] {dest}")

    print("\n--- what this means for a learned policy ---")
    for s in summaries:
        h, e = s["hit_at_5"], s["escalation_rate"]
        acc_gain = h["headroom_over_always"]
        if e["oracle_only_where_it_helps"] == 0:
            print(f"  {s['dataset']}: escalation NEVER changes the answer, yet the "
                  f"shipped gates escalate {e['shipped_hand_tuned_gates']:.1%} of "
                  f"windows. That spend is entirely reclaimable at zero accuracy cost.")
        else:
            print(f"  {s['dataset']}: escalation is worth "
                  f"{h['value_of_escalating_at_all']:+.4f} Hit@5 overall, but only "
                  f"{e['oracle_only_where_it_helps']:.1%} of windows need it. The "
                  f"shipped gates escalate {e['shipped_hand_tuned_gates']:.1%} — "
                  f"{e['reduction_factor']:.1f}x more than necessary. A learned policy's "
                  f"win is cost at iso-accuracy ({acc_gain:+.4f} accuracy headroom), "
                  f"not accuracy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
