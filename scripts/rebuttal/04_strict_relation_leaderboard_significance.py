"""R2-Q1: full leaderboard + paired-bootstrap significance under the STRICT
relevance relation (coarse + symptom-Jaccard>0.15), which the reviewers ask for."""
import json, random
from pathlib import Path
P = Path("C:/workplace/JiraAndLogs/paper-results")
G = Path("C:/workplace/JiraAndLogs/data/derived/global/2026-06-17-wol-real-v3-global")

strong = {}
with open(G/"window-memory-matchings-strong.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        ids = d.get("matched_memory_issue_ids") or []
        if ids: strong[d["window_id"]] = set(ids)
print(f"queries with >=1 STRICT gold match: {len(strong)}")

def load(p):
    out = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            wid = d["window_id"]
            if wid not in strong: continue
            top = list(d.get("matched_issue_ids") or [])[:5]
            g = strong[wid]
            r = next((i+1 for i, m in enumerate(top) if m in g), None)
            out[wid] = (1.0 if (top and top[0] in g) else 0.0,
                        1.0 if r else 0.0, 1.0/r if r else 0.0)
    return out

SYS = {
  "Hybrid fusion (ours)": P/"retrieval-cascades/wol-v3/hybrid-rrf-predictions.jsonl",
  "Dense bi-encoder (ours)": P/"retrieval-cascades/wol-v3/biencoder-predictions.jsonl",
  "Knowledge graph (ours)": P/"retrieval-cascades/wol-v3/kg-retrieval-predictions.jsonl",
  "BGE (zero-shot)": P/"baselines/sota-dense/wol-v3/bge-predictions.jsonl",
  "E5 (zero-shot)": P/"baselines/sota-dense/wol-v3/e5-predictions.jsonl",
  "Cross-encoder rerank": P/"baselines/cross-encoder-rerank/wol-v3/ce-predictions.jsonl",
  "BM25 (raw corpus)": P/"retrieval-cascades/wol-v3/bm25-predictions.jsonl",
}
R = {k: load(v) for k, v in SYS.items() if v.exists()}
common = sorted(set.intersection(*(set(v) for v in R.values())))
print(f"queries scored by every system: {len(common)}\n")
print(f"{'method':<26}{'Hit@1':>8}{'Hit@5':>8}{'MRR@5':>8}")
for k, v in R.items():
    print(f"{k:<26}{sum(v[q][0] for q in common)/len(common):>8.4f}"
          f"{sum(v[q][1] for q in common)/len(common):>8.4f}"
          f"{sum(v[q][2] for q in common)/len(common):>8.4f}")

def boot(a, b, i, B=1000, seed=42):
    rng = random.Random(seed); n = len(common)
    da = [a[q][i] for q in common]; db = [b[q][i] for q in common]
    obs = sum(db)/n - sum(da)/n
    ds = []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        ds.append(sum(db[j]-da[j] for j in idx)/n)
    ds.sort()
    p = 2*min(sum(1 for x in ds if x <= 0), sum(1 for x in ds if x >= 0))/B
    return obs, ds[int(.025*B)], ds[int(.975*B)], min(1.0, p)

H = R["Hybrid fusion (ours)"]
print(f"\nPaired bootstrap, Hybrid - X, STRICT relation (1000x, seed 42):")
raw = []
for k, v in R.items():
    if k == "Hybrid fusion (ours)": continue
    for nm, i in [("Hit@1",0),("Hit@5",1),("MRR@5",2)]:
        o, lo, hi, p = boot(v, H, i)
        raw.append((k, nm, o, lo, hi, p))
# Benjamini-Hochberg across the family
m = len(raw); order = sorted(range(m), key=lambda j: raw[j][5]); q = [0.0]*m; prev = 1.0
for rank, j in enumerate(reversed(order), start=1):
    prev = min(prev, raw[j][5]*m/(m-rank+1)); q[j] = prev
print(f"{'vs.':<26}{'metric':<8}{'delta':>9}{'95% CI':>20}{'p':>8}{'q(BH)':>8}  sig")
for j, (k, nm, o, lo, hi, p) in enumerate(raw):
    print(f"{k:<26}{nm:<8}{o:>+9.4f}{f'[{lo:+.4f},{hi:+.4f}]':>20}{p:>8.3f}{q[j]:>8.3f}"
          f"   {'YES' if q[j] < 0.05 else 'no'}")
