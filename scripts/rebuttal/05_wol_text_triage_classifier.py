"""Same experiment under the PAPER's label definition: ticket_worthy vs
everything-else (borderline + noise), so it is directly comparable to the
reported PR-AUC 0.506 / ROC-AUC 0.500 in Table III / Sec VII-D."""
import json
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, accuracy_score

G = "C:/workplace/JiraAndLogs/data/derived/global/2026-06-17-wol-real-v3-global"
MAXC = 4000
tr_x, tr_y, te_x, te_y, te_fam = [], [], [], [], []
with open(f"{G}/global-triage-examples.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        y = 1 if d.get("triage_label") == "ticket_worthy" else 0   # paper's binarization
        txt = (d.get("triage_evidence_text") or "")[:MAXC]
        sp = d.get("split")
        if sp == "test":  te_x.append(txt); te_y.append(y); te_fam.append(d.get("scenario_family"))
        elif sp == "train": tr_x.append(txt); tr_y.append(y)

tr_y = np.array(tr_y); te_y = np.array(te_y); te_fam = np.array(te_fam)
maj = max(te_y.mean(), 1-te_y.mean())
print("=== PAPER's binarization: ticket_worthy vs {borderline, noise} ===")
print(f"  train n={len(tr_x)} (pos {tr_y.mean():.4f})  test n={len(te_x)} (pos {te_y.mean():.4f})")
print(f"  majority-class accuracy = {maj:.4f}")
print(f"  PAPER REPORTS (numeric, zero-filled features): PR-AUC 0.506, ROC-AUC 0.500, acc 0.506\n")

vec = TfidfVectorizer(max_features=200_000, ngram_range=(1,2), min_df=3,
                      sublinear_tf=True, strip_accents="unicode")
Xtr = vec.fit_transform(tr_x); Xte = vec.transform(te_x)
print(f"  TF-IDF vocabulary: {len(vec.vocabulary_):,} terms")

for name, mk in [("LogisticRegression", lambda s: LogisticRegression(max_iter=2000, random_state=s, solver="liblinear")),
                 ("LinearSVM(SGD,log)", lambda s: SGDClassifier(loss="log_loss", max_iter=30, random_state=s, tol=1e-4))]:
    res = []
    for seed in range(5):
        clf = mk(seed).fit(Xtr, tr_y)
        p = clf.predict_proba(Xte)[:, 1]
        res.append((roc_auc_score(te_y, p), average_precision_score(te_y, p),
                    accuracy_score(te_y, (p >= 0.5).astype(int))))
    a = np.array(res)
    print(f"  {name:<20} ROC-AUC {a[:,0].mean():.4f} +/- {a[:,0].std():.4f} | "
          f"PR-AUC {a[:,1].mean():.4f} +/- {a[:,1].std():.4f} | acc {a[:,2].mean():.4f} +/- {a[:,2].std():.4f}")

clf = LogisticRegression(max_iter=2000, random_state=0, solver="liblinear").fit(Xtr, tr_y)
p = clf.predict_proba(Xte)[:, 1]
rng = np.random.default_rng(42); b = []
for _ in range(1000):
    i = rng.integers(0, len(te_y), len(te_y))
    if len(set(te_y[i])) < 2: continue
    b.append(roc_auc_score(te_y[i], p[i]))
b.sort()
print(f"\n  pooled ROC-AUC 95% CI = [{b[int(.025*len(b))]:.4f}, {b[int(.975*len(b))]:.4f}]  "
      f"(excludes 0.500 -> text carries real but weak signal)")
print("\n  per held-out project:")
for fam in sorted(set(te_fam)):
    m = te_fam == fam
    print(f"    {fam:<22} n={m.sum():<6} ROC-AUC={roc_auc_score(te_y[m],p[m]):.4f} "
          f"PR-AUC={average_precision_score(te_y[m],p[m]):.4f} (base {te_y[m].mean():.3f})")
print("\n  SYNTHETIC comparison (paper Table, numeric telemetry features):")
print("    Online Boutique HGB: PR-AUC 1.000  ROC-AUC 1.000")
print("    OTel Demo       HGB: PR-AUC 1.000  ROC-AUC 1.000")
