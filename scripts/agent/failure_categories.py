"""RQ-C6 — categorical failure-mode distribution.

Reads EvaluationReport JSONs and bins every case into one of:

  - perfect_hit            — hit_at_1 = True AND triage + novelty correct
  - hit_at_5_only          — found gold at rank 2-5 (not top-1)
  - retrieval_miss         — gold present but not in top-5
  - empty_candidates       — agent returned no matches at all
  - false_positive_triage  — triage=ticket_worthy but gold_triage=noise
  - false_negative_triage  — triage=noise but gold_triage=ticket_worthy
  - false_novel            — is_novel=True but gold_is_novel=False
  - false_not_novel        — is_novel=False but gold_is_novel=True
  - no_retrieval_gold      — gold_matched_issue_ids empty (excluded from
                              retrieval metrics by §12 rule 4)

One case can fall into MULTIPLE categories (e.g. retrieval miss AND
false_negative_triage). The script reports both:
  - per-case PRIMARY category (highest-impact)
  - overlapping counts per dimension (retrieval / triage / novelty)

Pure analysis on case_results — runs in seconds on a 1008-case smoke.

Usage:
    PYTHONPATH=src python scripts/agent/failure_categories.py \\
        --reports data/agent_runs/ob-smoke-full.json \\
                  data/agent_runs/wol-smoke.json \\
        --output data/agent_runs/failure-categories.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _classify_case(c: dict) -> dict:
    """Return a dict of (category → True) flags for one case."""
    d = c.get("decision") or {}
    flags: dict[str, bool] = {}

    gold_matched = list(c.get("gold_matched_issue_ids") or [])
    has_gold = bool(gold_matched)
    matched = list(d.get("matched_issue_ids") or [])

    # Retrieval dimension
    if not has_gold:
        flags["no_retrieval_gold"] = True
    else:
        h5 = c.get("hit_at_5")
        h1 = c.get("hit_at_1")
        if not matched:
            flags["empty_candidates"] = True
            flags["retrieval_miss"] = True
        elif h5 is False:
            flags["retrieval_miss"] = True
        elif h1 is False and h5 is True:
            flags["hit_at_5_only"] = True
        elif h1 is True:
            flags["perfect_hit_retrieval"] = True

    # Triage dimension
    pred_triage = d.get("triage_decision")
    gold_triage = c.get("gold_triage")
    if gold_triage and pred_triage and pred_triage != gold_triage:
        if pred_triage == "ticket_worthy" and gold_triage == "noise":
            flags["false_positive_triage"] = True
        elif pred_triage == "noise" and gold_triage == "ticket_worthy":
            flags["false_negative_triage"] = True
        else:
            flags["triage_misclassified"] = True

    # Novelty dimension
    pred_novel = d.get("is_novel")
    gold_novel = c.get("gold_is_novel")
    if pred_novel is True and gold_novel is False:
        flags["false_novel"] = True
    elif pred_novel is False and gold_novel is True:
        flags["false_not_novel"] = True

    return flags


def _primary_category(flags: dict) -> str:
    """Pick the most descriptive single category for a case."""
    # Priority order: retrieval first (biggest deal for retrieval-heavy
    # paper), then triage, then novelty, then "perfect".
    if "empty_candidates" in flags:
        return "empty_candidates"
    if "retrieval_miss" in flags:
        return "retrieval_miss"
    if "hit_at_5_only" in flags:
        return "hit_at_5_only"
    if "false_positive_triage" in flags:
        return "false_positive_triage"
    if "false_negative_triage" in flags:
        return "false_negative_triage"
    if "triage_misclassified" in flags:
        return "triage_misclassified"
    if "false_novel" in flags:
        return "false_novel"
    if "false_not_novel" in flags:
        return "false_not_novel"
    if "no_retrieval_gold" in flags:
        # Successfully called noise on a noise window
        return "noise_correctly_dismissed"
    if "perfect_hit_retrieval" in flags:
        return "perfect_hit"
    return "uncategorized"


def _summarise(report_dict: dict) -> dict:
    cases = report_dict.get("case_results") or []
    if not cases:
        return {"warning": "no case_results"}

    primary_counts: Counter = Counter()
    overlapping_counts: Counter = Counter()

    n_with_gold = 0
    n_h1 = n_h5 = 0
    for c in cases:
        if c.get("gold_matched_issue_ids"):
            n_with_gold += 1
            if c.get("hit_at_1"):
                n_h1 += 1
            if c.get("hit_at_5"):
                n_h5 += 1

        flags = _classify_case(c)
        primary_counts[_primary_category(flags)] += 1
        for flag in flags:
            overlapping_counts[flag] += 1

    return {
        "n_cases": len(cases),
        "n_with_retrieval_gold": n_with_gold,
        "n_hit_at_1": n_h1,
        "n_hit_at_5": n_h5,
        "primary_categories": dict(primary_counts),
        "overlapping_dimensions": dict(overlapping_counts),
    }


def _print_section(label: str, summary: dict) -> None:
    print()
    print("=" * 86)
    print(f"  Failure analysis — {label}")
    print("=" * 86)
    if "warning" in summary:
        print(f"  {summary['warning']}")
        return

    n = summary["n_cases"]
    print(f"  n_cases:                  {n}")
    print(f"  n_with_retrieval_gold:    {summary['n_with_retrieval_gold']}")
    if summary["n_with_retrieval_gold"]:
        print(f"  Hit@1 (raw):              {summary['n_hit_at_1']} / "
              f"{summary['n_with_retrieval_gold']}")
        print(f"  Hit@5 (raw):              {summary['n_hit_at_5']} / "
              f"{summary['n_with_retrieval_gold']}")

    print()
    print(f"  Primary category distribution (one bucket per case):")
    print(f"    {'category':<30} {'n':>6}  {'%':>6}  {'bar':<30}")
    print("    " + "-" * 75)
    counts = summary["primary_categories"]
    for cat in sorted(counts, key=lambda c: -counts[c]):
        ncat = counts[cat]
        frac = ncat / n
        bar = "#" * int(frac * 30)
        print(f"    {cat:<30} {ncat:>6}  {frac*100:>5.1f}%  {bar:<30}")

    print()
    print(f"  Overlapping dimensions (a case may have multiple flags):")
    print(f"    {'dimension':<30} {'n':>6}  {'%':>6}")
    print("    " + "-" * 45)
    overlap = summary["overlapping_dimensions"]
    for flag in sorted(overlap, key=lambda f: -overlap[f]):
        nflag = overlap[flag]
        frac = nflag / n
        print(f"    {flag:<30} {nflag:>6}  {frac*100:>5.1f}%")
    print("=" * 86)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reports", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    combined: dict[str, dict] = {}
    for path in args.reports:
        if not path.exists():
            print(f"[failure_categories] skipping missing {path}")
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        name = d.get("name") or path.stem
        summary = _summarise(d)
        combined[name] = summary
        _print_section(name, summary)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(combined, indent=2, default=str),
                                encoding="utf-8")
        print(f"\n[failure_categories] wrote -> {args.output}")


if __name__ == "__main__":
    main()
