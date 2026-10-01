"""5-seed variance decomposition: seed vs query-sampling."""
import json, pathlib, random, statistics
R = pathlib.Path("paper-results-v2/multiseed")

def preds(p):
    out = {}
    for line in open(p, encoding="utf-8"):
        d = json.loads(line)
        g = set(d.get("gold_matched_issue_ids") or [])
        if not g: continue
        top = list(d.get("matched_issue_ids") or [])[:5]
        out[d["window_id"]] = 1.0 if any(m in g for m in top) else 0.0
    return out

for ds in sorted(x.name for x in R.iterdir() if x.is_dir()):
    seeds = sorted((R/ds).glob("seed*"), key=lambda p: int(p.name[4:]))
    h5, per = {}, {}
    for s in seeds:
        f = s/"biencoder-mode3-results.json"
        if not f.exists(): continue
        h5[s.name] = json.loads(f.read_text())["coarse"]["hit_at_5"]
        pf = s/"biencoder-predictions.jsonl"
        if pf.exists(): per[s.name] = preds(pf)
    if len(h5) < 2: continue
    v = list(h5.values())
    sd_seed = statistics.stdev(v)

    # query-sampling SD for one run
    k = next(iter(per))
    keys = sorted(per[k])
    rng = random.Random(42); n = len(keys); b = []
    for _ in range(1000):
        idx = [rng.randrange(n) for _ in range(n)]
        b.append(sum(per[k][keys[i]] for i in idx)/n)
    sd_samp = statistics.stdev(b)
    tot = (sd_seed**2 + sd_samp**2) ** 0.5
    print(f"\n{ds}  ({len(v)} seeds, n={n} queries)")
    print(f"  Hit@5 mean={statistics.mean(v):.4f}  seed sd={sd_seed:.4f}  range={max(v)-min(v):.4f}")
    print(f"  query-sampling sd={sd_samp:.4f}")
    print(f"  combined sd={tot:.4f};  seed contributes {sd_seed**2/tot**2*100:.0f}% of variance")
