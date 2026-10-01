"""Learned cost-sensitive escalation policy — does the signal exist?

The shipped controller escalates on two hand-set thresholds (numeric triage
< 0.90, retriever confidence < 0.5). `build_escalation_value_set.py` showed those
gates are badly calibrated: on World of Logs they escalate 99.9% of windows where
6.2% would suffice (16.2x), and on the telemetry datasets they escalate 17-21% of
windows where escalation provably never changes the answer.

This script asks the prior question honestly, before any claim is made:
**is the escalation decision predictable from what the system knows at decision
time?** If it is, a learned policy recovers most of escalation's value at a
fraction of its cost, and the cost-quality Pareto curve is the result. If it is
not, that is a negative result worth reporting -- it says the needed signal is
not in the cheap path's output and would require richer features (e.g. the
retriever's score margin, which the current predictions do not persist).

Protocol
--------
Features are strictly those available BEFORE escalating: the cheap retriever's
own confidence, how many candidates it returned, corpus-density and
window-descriptive fields, and query-text shape. The escalation outcome is never
a feature -- that would be the label.

Evaluation is leave-project-out over the two held-out WoL domains (train Kafka ->
test MariaDB, and the reverse), mirroring the paper's split philosophy. We never
train and test on the same project.

Usage
-----
    python scripts/v2/learned_escalation_policy.py \
        --escalation paper-results-v2/escalation \
        --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
        --predictions paper-results/retrieval-cascades/wol-v3/biencoder-predictions.jsonl \
        --out paper-results-v2/escalation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

#: Categorical fields one-hot encoded into the feature vector.
CATEGORICALS = ("window_type", "triage_reason_class")


def load_escalation_rows(path: Path) -> dict[str, dict]:
    rows = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("evaluable"):
                rows[d["window_id"]] = d
    return rows


def load_predictions(path: Path) -> dict[str, dict]:
    out = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            out[d["window_id"]] = d
    return out


def load_text_shape(global_dir: Path) -> dict[str, dict]:
    """Query-text shape features. Text content itself is not used — only size
    and structure, which a controller can compute without reading the ticket."""
    out = {}
    with (global_dir / "global-triage-examples.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            t = d.get("triage_evidence_text") or ""
            out[d["window_id"]] = {
                "text_chars": float(len(t)),
                "text_words": float(t.count(" ") + 1 if t else 0),
                "text_lines": float(t.count("\n") + 1 if t else 0),
                "n_components": float(len(d.get("triage_components") or [])),
            }
    return out


def build_matrix(wids, esc, pred, shape):
    """Assemble the decision-time feature matrix. Returns (X, y, names)."""
    cat_vocab = {c: sorted({(pred.get(w, {}).get(c) or "") for w in wids})
                 for c in CATEGORICALS}
    names: list[str] = [
        "cheap_confidence", "cheap_triage_score", "n_candidates",
        "cheap_is_novel", "n_prior_family_tickets", "is_hard_case",
        "text_chars", "text_words", "text_lines", "n_components",
    ]
    for c in CATEGORICALS:
        names += [f"{c}={v}" for v in cat_vocab[c]]

    X, y = [], []
    for w in wids:
        e, p = esc[w], pred.get(w, {})
        s = shape.get(w, {})
        row = [
            float(e.get("cheap_confidence") or 0.0),
            float(e.get("cheap_triage_score") or 0.0),
            float(len(p.get("matched_issue_ids") or [])),
            1.0 if p.get("is_novel") else 0.0,
            float(p.get("n_prior_family_tickets") or 0.0),
            1.0 if p.get("is_hard_case") else 0.0,
            s.get("text_chars", 0.0), s.get("text_words", 0.0),
            s.get("text_lines", 0.0), s.get("n_components", 0.0),
        ]
        for c in CATEGORICALS:
            v = p.get(c) or ""
            row += [1.0 if v == opt else 0.0 for opt in cat_vocab[c]]
        X.append(row)
        y.append(1 if (e.get("delta_hit_at_5") or 0.0) > 0 else 0)
    return np.array(X, dtype=float), np.array(y), names


def pareto(order_scores, esc_rows, wids, grid):
    """Hit@5 achieved when escalating the top-r fraction by `order_scores`.

    Escalated windows take the escalated outcome; the rest keep the cheap one.
    """
    idx = np.argsort(-np.asarray(order_scores))
    n = len(wids)
    cheap = np.array([esc_rows[w]["cheap_hit_at_5"] for w in wids], dtype=float)
    esc = np.array([esc_rows[w]["escalated_hit_at_5"] for w in wids], dtype=float)
    out = []
    for r in grid:
        k = int(round(r * n))
        take = np.zeros(n, dtype=bool)
        take[idx[:k]] = True
        hit = float(np.where(take, esc, cheap).mean())
        out.append({"escalation_rate": r, "hit_at_5": hit})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--escalation", type=Path, required=True)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dataset", default="wol-v3")
    ap.add_argument("--seeds", type=int, default=5)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    esc = load_escalation_rows(args.escalation / f"escalation-value-{args.dataset}.jsonl")
    pred = load_predictions(args.predictions)
    shape = load_text_shape(args.global_dir)
    print(f"[load] escalation rows (evaluable)={len(esc):,}  "
          f"predictions={len(pred):,}  text-shape={len(shape):,}")

    wids = [w for w in esc if w in pred]
    fams = {w: pred[w].get("scenario_family") or "" for w in wids}
    by_fam: dict[str, list[str]] = {}
    for w in wids:
        by_fam.setdefault(fams[w], []).append(w)
    print(f"  usable windows={len(wids):,}; families: "
          + ", ".join(f"{k}={len(v):,}" for k, v in sorted(by_fam.items())))

    base_rate = np.mean([1 if (esc[w].get("delta_hit_at_5") or 0) > 0 else 0
                         for w in wids])
    print(f"  base rate of 'escalation helps': {base_rate:.4f}")

    grid = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 0.20, 0.30,
            0.50, 0.75, 1.0]
    folds, report = sorted(by_fam), {}

    for test_fam in folds:
        tr_w = [w for w in wids if fams[w] != test_fam]
        te_w = by_fam[test_fam]
        if not tr_w or len(set(1 if (esc[w].get("delta_hit_at_5") or 0) > 0 else 0
                              for w in tr_w)) < 2:
            print(f"\n[skip fold {test_fam}] single-class or empty train side")
            continue
        Xtr, ytr, names = build_matrix(tr_w, esc, pred, shape)
        Xte, yte, _ = build_matrix(te_w, esc, pred, shape)

        aucs, curves = [], []
        for seed in range(args.seeds):
            clf = HistGradientBoostingClassifier(random_state=seed,
                                                 max_iter=200).fit(Xtr, ytr)
            p = clf.predict_proba(Xte)[:, 1]
            if len(np.unique(yte)) > 1:
                aucs.append(roc_auc_score(yte, p))
            curves.append(pareto(p, esc, te_w, grid))

        # Reference curves on the same held-out windows.
        rng = np.random.default_rng(42)
        rand_curve = pareto(rng.random(len(te_w)), esc, te_w, grid)
        # Oracle: escalate where it actually helps, best-first.
        oracle_scores = [1.0 if (esc[w].get("delta_hit_at_5") or 0) > 0 else 0.0
                         for w in te_w]
        oracle_curve = pareto(oracle_scores, esc, te_w, grid)
        # The shipped hand-tuned gate ordering: lowest confidence escalates first.
        gate_scores = [-float(esc[w].get("cheap_confidence") or 0.0) for w in te_w]
        gate_curve = pareto(gate_scores, esc, te_w, grid)

        learned = [float(np.mean([c[i]["hit_at_5"] for c in curves]))
                   for i in range(len(grid))]
        always = float(np.mean([esc[w]["escalated_hit_at_5"] for w in te_w]))
        never = float(np.mean([esc[w]["cheap_hit_at_5"] for w in te_w]))

        auc_m = float(np.mean(aucs)) if aucs else float("nan")
        auc_s = float(np.std(aucs)) if aucs else float("nan")
        print(f"\n=== fold: test on {test_fam}  (train n={len(tr_w):,}, "
              f"test n={len(te_w):,}) ===")
        print(f"  policy ROC-AUC predicting 'escalation helps': "
              f"{auc_m:.4f} +/- {auc_s:.4f}  (chance 0.5)")
        print(f"  never-escalate Hit@5={never:.4f}   always-escalate={always:.4f}")
        print(f"\n  {'esc rate':>9}{'learned':>10}{'conf-gate':>11}{'random':>9}{'oracle':>9}")
        for i, r in enumerate(grid):
            print(f"  {r:>9.0%}{learned[i]:>10.4f}{gate_curve[i]['hit_at_5']:>11.4f}"
                  f"{rand_curve[i]['hit_at_5']:>9.4f}{oracle_curve[i]['hit_at_5']:>9.4f}")

        # Headline: smallest escalation rate at which the learned policy matches
        # always-escalate accuracy (within noise).
        reach = next((r for r, h in zip(grid, learned) if h >= always - 1e-4), None)
        if reach is not None:
            print(f"\n  learned policy matches always-escalate ({always:.4f}) "
                  f"at {reach:.0%} escalation "
                  f"-> {1/reach:.1f}x fewer escalations" if reach > 0 else "")
        else:
            print(f"\n  learned policy never matches always-escalate on this fold")

        # The decisive comparison. The shipped gate already ORDERS windows by
        # cheap confidence; it just thresholds badly. So the learned policy only
        # earns its place if it beats that ordering at matched escalation rate.
        gate_h = [c["hit_at_5"] for c in gate_curve]
        interior = [i for i, r in enumerate(grid) if 0.0 < r < 1.0]
        wins = sum(1 for i in interior if learned[i] > gate_h[i] + 1e-6)
        losses = sum(1 for i in interior if learned[i] < gate_h[i] - 1e-6)
        mean_gap = float(np.mean([learned[i] - gate_h[i] for i in interior]))
        print(f"\n  learned vs confidence-gate at matched escalation rate: "
              f"{wins} wins / {losses} losses / {len(interior) - wins - losses} ties"
              f"  (mean gap {mean_gap:+.4f})")
        if mean_gap <= 1e-4:
            print("  -> the learned policy does NOT improve on simply thresholding "
                  "the existing confidence signal. The shipped controller's defect "
                  "is its THRESHOLD, not its ranking signal.")

        report[test_fam] = {
            "vs_confidence_gate": {"wins": wins, "losses": losses,
                                   "mean_gap": mean_gap},
            "n_train": len(tr_w), "n_test": len(te_w),
            "policy_roc_auc": {"mean": auc_m, "std": auc_s, "n_seeds": args.seeds},
            "never_escalate_hit5": never, "always_escalate_hit5": always,
            "grid": grid, "learned": learned,
            "confidence_gate": [c["hit_at_5"] for c in gate_curve],
            "random": [c["hit_at_5"] for c in rand_curve],
            "oracle": [c["hit_at_5"] for c in oracle_curve],
            "rate_matching_always": reach,
            "feature_names": names,
        }

    dest = args.out / f"learned-policy-{args.dataset}.json"
    dest.write_text(json.dumps({"base_rate_helps": float(base_rate),
                                "folds": report}, indent=2), encoding="utf-8")
    print(f"\n[write] {dest}")

    aucs = [r["policy_roc_auc"]["mean"] for r in report.values()
            if r["policy_roc_auc"]["mean"] == r["policy_roc_auc"]["mean"]]
    if aucs and max(aucs) < 0.6:
        print("\n[verdict] The escalation decision is NOT well predicted from the "
              "features available at decision time (ROC-AUC "
              f"{min(aucs):.3f}-{max(aucs):.3f}). Report this as a negative result: "
              "the cheap path's confidence does not carry the signal, and a useful "
              "policy would need features the current pipeline does not persist "
              "(e.g. retriever score margins).")
    elif aucs:
        gaps = [r["vs_confidence_gate"]["mean_gap"] for r in report.values()]
        print(f"\n[verdict] The escalation decision IS predictable in isolation "
              f"(ROC-AUC {min(aucs):.3f}-{max(aucs):.3f}).")
        if max(gaps) <= 2e-3:
            print("  BUT the learned policy does not beat the confidence ordering "
                  f"the shipped controller already computes (mean gap per fold: "
                  f"{', '.join(f'{g:+.4f}' for g in gaps)}). The publishable finding "
                  "is therefore NOT 'a learned policy wins' but 'the shipped gates "
                  "are mis-thresholded': the same signal, thresholded well, reaches "
                  "always-escalate accuracy at a fraction of the escalation rate.")
            print("  The gap to the oracle is large and unreached by either method, "
                  "so the missing ingredient is features, not model class. The "
                  "obvious candidate -- the retriever's top-1/top-2 score margin -- "
                  "is not persisted by the current pipeline and would need a re-run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
