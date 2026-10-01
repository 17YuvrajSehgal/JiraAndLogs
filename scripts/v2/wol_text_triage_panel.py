"""WoL triage panel over TEXT — replaces the degenerate zero-feature result.

Why this script exists
----------------------
The ICSE submission reported, for World of Logs, that every standard triage
classifier scores ROC-AUC 0.500 / PR-AUC 0.506, and concluded that real-incident
triage "collapses to chance". That conclusion is not supported by the
experiment that produced it.

`build_wol_real_corpus_v3.py` emits the 94 `triage_feature_*` columns
unconditionally as `0.0` for every WoL row (it is a text-only corpus; there is
no telemetry to populate them). So the classifiers were fitted on a constant
all-zero design matrix and ROC-AUC 0.500 is *forced*, not learned. The saved
artifact even reports the bootstrap CI as exactly [0.5000, 0.5000].

This script re-runs the question with the input the corpus actually has — the
ticket text — under the identical leave-domain-out protocol, so the paper can
state a measured number instead of an artifact.

Protocol
--------
  split        leave-domain-out, from triage-split-manifest.json
               train = 21 projects, validation = Ambari, test = Kafka + MariaDB
  label        paper's binarization: ticket_worthy vs {borderline, noise}
               (`--labels strict` restricts to ticket_worthy vs noise instead)
  input        `triage_evidence_text` (log lines, or summary+description when
               the issue has no log block), truncated to --max-chars
  models       majority baseline, TF-IDF+LogReg, TF-IDF+LinearSVM, TF-IDF+HGB
  seeds        --seeds (default 5); we report mean +/- SD, never a single run
  metrics      ROC-AUC, PR-AUC, accuracy, ECE, + bootstrap CI on pooled ROC

Everything is fit on train only. Validation is reported but never selected on;
no hyperparameter is tuned against test.

Usage
-----
    PYTHONPATH=src python scripts/v2/wol_text_triage_panel.py \
        --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
        --out paper-results-v2/triage-text/wol-v3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    roc_auc_score,
)

LABEL_POSITIVE = "ticket_worthy"


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def load_rows(global_dir: Path, max_chars: int, labels: str):
    """Stream the corpus into per-split (text, label, family) lists.

    `labels="paper"`  -> ticket_worthy vs {borderline, noise}  (what the paper did)
    `labels="strict"` -> ticket_worthy vs noise, dropping borderline
    """
    splits: dict[str, dict[str, list]] = {
        s: {"x": [], "y": [], "fam": []} for s in ("train", "validation", "test")
    }
    n_feat_nonzero = 0
    n_rows = 0
    feat_cols: list[str] | None = None

    path = global_dir / "global-triage-examples.jsonl"
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            label = d.get("triage_label")
            if labels == "strict" and label not in (LABEL_POSITIVE, "noise"):
                continue

            if feat_cols is None:
                feat_cols = [k for k in d if k.startswith("triage_feature_")]
            n_rows += 1
            if any(float(d.get(c) or 0.0) != 0.0 for c in feat_cols):
                n_feat_nonzero += 1

            split = d.get("split")
            if split not in splits:
                continue
            splits[split]["x"].append((d.get("triage_evidence_text") or "")[:max_chars])
            splits[split]["y"].append(1 if label == LABEL_POSITIVE else 0)
            splits[split]["fam"].append(d.get("scenario_family") or "")

    return splits, {
        "n_feature_columns": len(feat_cols or []),
        "n_rows_scanned": n_rows,
        "n_rows_with_any_nonzero_feature": n_feat_nonzero,
    }


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Standard equal-width ECE. The paper reports ECE, so we match it."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p > lo) & (p <= hi) if lo > 0 else (p >= lo) & (p <= hi)
        if not m.any():
            continue
        ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)


def score(y: np.ndarray, p: np.ndarray) -> dict:
    return {
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "accuracy": float(accuracy_score(y, (p >= 0.5).astype(int))),
        "ece": expected_calibration_error(y, p),
    }


def bootstrap_ci(y: np.ndarray, p: np.ndarray, n: int, seed: int, metric):
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        if len(np.unique(y[idx])) < 2:
            continue
        vals.append(metric(y[idx], p[idx]))
    vals.sort()
    if not vals:
        return (float("nan"), float("nan"))
    return (float(vals[int(0.025 * len(vals))]), float(vals[int(0.975 * len(vals))]))


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

def build_models(seed: int, svd_dim: int):
    """Each entry: (name, needs_dense, factory)."""
    return [
        ("logreg_tfidf", False,
         lambda: LogisticRegression(max_iter=2000, C=1.0, solver="liblinear",
                                    random_state=seed)),
        ("linear_svm_tfidf", False,
         lambda: SGDClassifier(loss="log_loss", max_iter=30, tol=1e-4,
                               random_state=seed)),
        ("hist_gradient_boosting_tfidf_svd", True,
         lambda: HistGradientBoostingClassifier(random_state=seed)),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--max-chars", type=int, default=4000)
    ap.add_argument("--max-features", type=int, default=200_000)
    ap.add_argument("--svd-dim", type=int, default=256,
                    help="dense projection for the tree model")
    ap.add_argument("--n-bootstrap", type=int, default=1000)
    ap.add_argument("--labels", choices=("paper", "strict"), default="paper",
                    help="'paper' = TW vs {borderline,noise} (matches the "
                         "submission); 'strict' = TW vs noise")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(f"[load] {args.global_dir}  labels={args.labels}")
    splits, feat_audit = load_rows(args.global_dir, args.max_chars, args.labels)

    # ---- the audit that justifies this whole script -----------------------
    print("\n=== Audit: what the PUBLISHED classifiers were given ===")
    print(f"  numeric triage_feature_* columns : {feat_audit['n_feature_columns']}")
    print(f"  rows scanned                     : {feat_audit['n_rows_scanned']:,}")
    print(f"  rows with ANY non-zero feature   : "
          f"{feat_audit['n_rows_with_any_nonzero_feature']:,}")
    if feat_audit["n_rows_with_any_nonzero_feature"] == 0:
        print("  => constant all-zero design matrix; ROC-AUC 0.500 is FORCED,")
        print("     not a measurement of learnability. Hence this panel.")

    tr, te = splits["train"], splits["test"]
    ytr, yte = np.array(tr["y"]), np.array(te["y"])
    fam_te = np.array(te["fam"])
    majority = float(max(yte.mean(), 1 - yte.mean()))
    print(f"\n=== Text triage, leave-domain-out ===")
    print(f"  train n={len(tr['x']):,} (pos {ytr.mean():.4f})")
    print(f"  test  n={len(te['x']):,} (pos {yte.mean():.4f})")
    print(f"  majority-class test accuracy = {majority:.4f}")

    results: dict[str, dict] = {}
    per_seed_probs: dict[str, np.ndarray] = {}

    for seed in range(args.seeds):
        vec = TfidfVectorizer(max_features=args.max_features, ngram_range=(1, 2),
                              min_df=3, sublinear_tf=True, strip_accents="unicode")
        Xtr = vec.fit_transform(tr["x"])
        Xte = vec.transform(te["x"])
        if seed == 0:
            print(f"  TF-IDF vocabulary: {len(vec.vocabulary_):,} terms")

        Xtr_d = Xte_d = None
        for name, needs_dense, factory in build_models(seed, args.svd_dim):
            if needs_dense:
                if Xtr_d is None:
                    svd = TruncatedSVD(n_components=args.svd_dim, random_state=seed)
                    Xtr_d = svd.fit_transform(Xtr)
                    Xte_d = svd.transform(Xte)
                A, B = Xtr_d, Xte_d
            else:
                A, B = Xtr, Xte
            clf = factory().fit(A, ytr)
            p = clf.predict_proba(B)[:, 1]
            results.setdefault(name, {"per_seed": []})["per_seed"].append(score(yte, p))
            if seed == 0:
                per_seed_probs[name] = p
        print(f"  [seed {seed}] done ({time.time() - t0:.0f}s)")

    # ---- aggregate --------------------------------------------------------
    print(f"\n{'model':<34}{'ROC-AUC':>18}{'PR-AUC':>18}{'acc':>16}{'ECE':>9}")
    summary: dict[str, dict] = {
        "majority_baseline": {
            "accuracy": majority, "roc_auc": 0.5, "pr_auc": float(yte.mean()),
        },
    }
    for name, d in results.items():
        arr = {k: np.array([s[k] for s in d["per_seed"]]) for k in d["per_seed"][0]}
        row = {k: {"mean": float(v.mean()), "std": float(v.std())}
               for k, v in arr.items()}
        p = per_seed_probs[name]
        row["roc_auc"]["ci95"] = bootstrap_ci(yte, p, args.n_bootstrap, 42, roc_auc_score)
        row["n_seeds"] = args.seeds
        summary[name] = row
        print(f"{name:<34}"
              f"{row['roc_auc']['mean']:>9.4f} +/-{row['roc_auc']['std']:<6.4f}"
              f"{row['pr_auc']['mean']:>9.4f} +/-{row['pr_auc']['std']:<6.4f}"
              f"{row['accuracy']['mean']:>9.4f} +/-{row['accuracy']['std']:<5.4f}"
              f"{row['ece']['mean']:>9.4f}")
    print(f"{'majority baseline':<34}{0.5:>9.4f}{'':<9}{yte.mean():>9.4f}"
          f"{'':<9}{majority:>9.4f}")

    best = max(summary.items(),
               key=lambda kv: kv[1].get("roc_auc", {}).get("mean", 0)
               if isinstance(kv[1].get("roc_auc"), dict) else 0)
    lo, hi = best[1]["roc_auc"]["ci95"]
    print(f"\n  best: {best[0]} ROC-AUC {best[1]['roc_auc']['mean']:.4f} "
          f"95% CI [{lo:.4f}, {hi:.4f}]")
    print(f"  => CI {'EXCLUDES' if lo > 0.5 else 'includes'} 0.500 — text carries "
          f"{'real but weak' if lo > 0.5 else 'no detectable'} signal.")

    # ---- per held-out project --------------------------------------------
    print("\n  per held-out project:")
    per_project = {}
    for name, p in per_seed_probs.items():
        per_project[name] = {}
        for fam in sorted(set(fam_te)):
            m = fam_te == fam
            if len(np.unique(yte[m])) < 2:
                continue
            per_project[name][fam] = {
                "n": int(m.sum()),
                "roc_auc": float(roc_auc_score(yte[m], p[m])),
                "pr_auc": float(average_precision_score(yte[m], p[m])),
                "base_rate": float(yte[m].mean()),
            }
        for fam, v in per_project[name].items():
            print(f"    {name:<30} {fam:<22} n={v['n']:<6} "
                  f"ROC={v['roc_auc']:.4f} PR={v['pr_auc']:.4f} "
                  f"(base {v['base_rate']:.3f})")

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "global_dir": str(args.global_dir),
        "protocol": {
            "split": "leave-domain-out (train 21 projects / test Kafka+MariaDB)",
            "labels": args.labels,
            "input_field": "triage_evidence_text",
            "max_chars": args.max_chars,
            "seeds": args.seeds,
            "n_bootstrap": args.n_bootstrap,
        },
        "published_feature_audit": feat_audit,
        "n_train": len(tr["x"]),
        "n_test": len(te["x"]),
        "test_positive_rate": float(yte.mean()),
        "majority_accuracy": majority,
        "summary": summary,
        "per_project": per_project,
        "elapsed_s": time.time() - t0,
    }
    dest = args.out / f"wol-text-triage-{args.labels}.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[write] {dest}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
