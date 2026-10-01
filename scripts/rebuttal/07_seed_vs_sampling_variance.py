"""R3-Q1: how large is seed-to-seed variation relative to query-sampling
variation? Uses the 3 retrained bi-encoder seeds we already have."""
import json, random, statistics
from pathlib import Path
P = Path("C:/workplace/JiraAndLogs/paper-results")

def load_pred(p):
    out = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            gold = set(d.get("gold_matched_issue_ids") or [])
            if not gold: continue
            top = list(d.get("matched_issue_ids") or [])
            out[d["window_id"]] = (1.0 if any(m in gold for m in top[:5]) else 0.0,
                                   1.0 if (top[:1] and top[0] in gold) else 0.0)
    return out

for ds, seed42 in [("online-boutique", P/"retrieval-cascades/online-boutique/biencoder-predictions.jsonl"),
                   ("otel-demo",       P/"retrieval-cascades/otel-demo/biencoder-predictions.jsonl")]:
    runs = {"42": load_pred(seed42)}
    for s in ("seed1","seed2"):
        q = P/f"robustness/multiseed/{ds}/{s}/biencoder-predictions.jsonl"
        if q.exists(): runs[s] = load_pred(q)
    keys = sorted(set.intersection(*(set(r) for r in runs.values())))
    print(f"\n=== {ds}  (n={len(keys)} queries with gold, {len(runs)} retrained seeds) ===")
    h5 = {}
    for s, r in runs.items():
        h5[s] = sum(r[k][0] for k in keys)/len(keys)
        print(f"   seed {s:<6} Hit@5 = {h5[s]:.4f}")
    vals = list(h5.values())
    seed_sd = statistics.stdev(vals)
    print(f"   seed-to-seed SD          = {seed_sd:.4f}   (range {max(vals)-min(vals):.4f})")

    # query-sampling SD for a single run, same n
    rng = random.Random(42); base = runs["42"]; n = len(keys); boots = []
    for _ in range(1000):
        idx = [rng.randrange(n) for _ in range(n)]
        boots.append(sum(base[keys[i]][0] for i in idx)/n)
    samp_sd = statistics.stdev(boots); boots.sort()
    print(f"   query-sampling SD (boot) = {samp_sd:.4f}   95% CI "
          f"[{boots[25]:.4f}, {boots[975]:.4f}]")
    print(f"   -> sampling uncertainty is {samp_sd/seed_sd:.1f}x the seed uncertainty")
    # combined
    tot = (seed_sd**2 + samp_sd**2) ** 0.5
    print(f"   combined SD (seed + sampling) = {tot:.4f}; seed contributes "
          f"{seed_sd**2/tot**2*100:.1f}% of the variance")
