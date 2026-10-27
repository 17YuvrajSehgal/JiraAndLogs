"""Check every headline number in the manuscript against the file that produced it.

Task #24. The submitted paper carried a claim built on an all-zero feature
matrix, and a second false claim was later propagated from a draft without
anyone checking the scoring path. Both were plausible, unverified, and repeated
until they looked settled. This is the guard against that: each claim names its
source file and JSON path, and the check fails if the manuscript and the result
file disagree.

Run before every submission. A claim that cannot be traced gets cut, not hedged.

    python scripts/v2/verify_claims.py

ponytail: a flat list of assertions, not a framework. Add a row when you add a
claim; delete a row when you delete one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PR = Path("paper-results")
P2 = Path("paper-results-v2")


def jget(path: Path, *keys):
    """Fetch a nested key; returns a sentinel string if the file/key is absent."""
    if not path.exists():
        return f"<missing file {path}>"
    d = json.loads(path.read_text(encoding="utf-8"))
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return f"<missing key {'/'.join(map(str, keys))} in {path.name}>"
    return d


def _ds(name: str, *keys):
    """escalation-headroom.json stores datasets as a list, keyed by a field."""
    blob = jget(P2 / "escalation/escalation-headroom.json", "datasets")
    if not isinstance(blob, list):
        return blob
    for d in blob:
        if d.get("dataset") == name:
            for k in keys:
                if not isinstance(d, dict) or k not in d:
                    return f"<missing {'/'.join(keys)} for {name}>"
                d = d[k]
            return d
    return f"<no dataset {name}>"


#: (claim, value in manuscript, tolerance, actual)
#: Tolerance covers the paper rounding its numbers; 0 means exact.
CHECKS: list[tuple[str, float, float, object]] = [
    # ---- RQ1 retrieval, coarse relation -------------------------------
    ("WoL hybrid coarse Hit@5", 0.970, 0.001,
     jget(PR / "retrieval-cascades/wol-v3/hybrid-rrf-mode3-results.json", "coarse", "hit_at_5")),
    ("WoL dense coarse Hit@5 (published single seed)", 0.905, 0.001,
     jget(PR / "retrieval-cascades/wol-v3/biencoder-mode3-results.json", "coarse", "hit_at_5")),

    # ---- RQ1 retrieval, strict relation (v2 full panel) ---------------
    ("strict: hybrid Hit@5", 0.744, 0.001,
     jget(P2 / "strict-leaderboard.json", "strict", "table", "Hybrid fusion (ours)", "hit5")),
    ("strict: hybrid Hit@1", 0.511, 0.001,
     jget(P2 / "strict-leaderboard.json", "strict", "table", "Hybrid fusion (ours)", "hit1")),
    ("strict: dense bi-encoder Hit@5 (degrades most)", 0.523, 0.001,
     jget(P2 / "strict-leaderboard.json", "strict", "table", "Dense bi-encoder (ours)", "hit5")),
    ("strict: knowledge graph Hit@5 (worst)", 0.036, 0.001,
     jget(P2 / "strict-leaderboard.json", "strict", "table", "Knowledge graph (ours)", "hit5")),
    ("strict: n queries scored by all systems", 4362, 0,
     jget(P2 / "strict-leaderboard.json", "strict", "n")),

    # ---- RQ4 triage on text (replaces the zero-feature claim) ---------
    ("text triage, paper binarization, best ROC-AUC", 0.601, 0.002,
     max((v["roc_auc"]["mean"] for k, v in
          jget(P2 / "triage-text/wol-v3/wol-text-triage-paper.json", "summary").items()
          if k != "majority_baseline"), default=None)),
    ("text triage, strict binarization, best ROC-AUC", 0.704, 0.002,
     max((v["roc_auc"]["mean"] for k, v in
          jget(P2 / "triage-text/wol-v3/wol-text-triage-strict.json", "summary").items()
          if k != "majority_baseline"), default=None)),
    ("zero-filled rows (the defect): must be 0", 0, 0,
     jget(P2 / "triage-text/wol-v3/wol-text-triage-paper.json",
          "published_feature_audit", "n_rows_with_any_nonzero_feature")),

    # ---- LLM judge with hard negatives --------------------------------
    ("judge: system top-1 mean", 3.65, 0.01,
     jget(P2 / "gold-validation/wol-v3/judge-v2-results.json", "conditions", "system", "mean")),
    ("judge: hard same-project mean", 3.10, 0.01,
     jget(P2 / "gold-validation/wol-v3/judge-v2-results.json", "conditions", "hard", "mean")),
    ("judge: uniform control mean", 1.32, 0.01,
     jget(P2 / "gold-validation/wol-v3/judge-v2-results.json", "conditions", "easy", "mean")),

    # ---- cost (modelled counterfactual) -------------------------------
    ("cost saving WoL", 78.09, 0.5,
     jget(PR / "agent-value/wol-v3/cost-vs-cascade.json", "summary", "savings_pct", "wall")),
    ("cost saving Online Boutique", 39.97, 0.5,
     jget(PR / "agent-value/online-boutique/cost-vs-cascade.json", "summary", "savings_pct", "wall")),
    ("cost saving OTel Demo", 63.37, 0.5,
     jget(PR / "agent-value/otel-demo/cost-vs-cascade.json", "summary", "savings_pct", "wall")),

    # ---- escalation headroom / threshold ------------------------------
    ("escalation never-escalate Hit@5 (WoL)", 0.9041, 0.001,
     _ds("wol-v3", "hit_at_5", "never_escalate")),
    ("escalation always-escalate Hit@5 (WoL)", 0.9633, 0.001,
     _ds("wol-v3", "hit_at_5", "always_escalate")),
    ("oracle escalation rate (WoL)", 0.0617, 0.001,
     _ds("wol-v3", "escalation_rate", "oracle_only_where_it_helps")),
]

#: Claims with NO stored artifact — recomputed on the fly by a rebuttal script.
#: These are traceable but not re-checkable here; storing their output is the fix.
UNSTORED = [
    ("component coverage 75.3%, dropped queries 23.9%",
     "scripts/rebuttal/01_component_metadata_and_gold_stats.py"),
    ("random-ranker Hit@5 0.036 coarse / 0.0044 strict",
     "scripts/rebuttal/02_random_baseline_and_kg_vocab_overlap.py"),
    ("KG/gold vocabulary overlap 9.9%",
     "scripts/rebuttal/02_random_baseline_and_kg_vocab_overlap.py"),
    ("indexed corpus Components leakage 0/3000, 34.6%, 15.9%",
     "scripts/rebuttal/03_indexed_corpus_leakage_check.py"),
    ("seed variance decomposition (28% OB, 1% OTel)",
     "scripts/v2/seed_variance_decomposition.py"),
]


def main() -> int:
    width = max(len(c[0]) for c in CHECKS) + 2
    bad = []
    print(f"{'claim':<{width}}{'paper':>10}{'actual':>12}  status")
    for claim, stated, tol, actual in CHECKS:
        if not isinstance(actual, (int, float)):
            print(f"{claim:<{width}}{stated:>10}{'—':>12}  UNRESOLVED: {actual}")
            bad.append(claim)
            continue
        ok = abs(actual - stated) <= tol
        print(f"{claim:<{width}}{stated:>10}{actual:>12.4f}  {'ok' if ok else 'MISMATCH'}")
        if not ok:
            bad.append(claim)

    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} verified against their source files")
    if bad:
        print("FAILED:")
        for b in bad:
            print(f"  - {b}")

    print(f"\nTraceable but not stored as an artifact ({len(UNSTORED)}):")
    for claim, script in UNSTORED:
        print(f"  {claim}\n      -> {script}")
    print("\nFix: have those scripts write their output to paper-results-v2/ so they"
          "\nbecome checkable here instead of needing a re-run to confirm.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
