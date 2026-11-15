"""Strict-relation leaderboard with the COMPLETE panel (task #7).

The earlier version could not include TF-IDF or MPNet in the paired tests: their
strict metrics existed in the result JSONs but their per-query predictions had
not been retained, so there was nothing to pair on. The v2 rerun regenerated all
five baselines with predictions, so every row of the table can now enter the
significance family and the paper can drop its "every system we could test
pairwise" hedge.
"""
from __future__ import annotations
import json, random, sys
from pathlib import Path

G = Path("data/derived/global/2026-06-17-wol-real-v3-global")
B = Path("errors")  # placeholder, set below

SYS = {
    "Hybrid fusion (ours)":    Path("paper-results/retrieval-cascades/wol-v3/hybrid-rrf-predictions.jsonl"),
    "Dense bi-encoder (ours)": Path("paper-results/retrieval-cascades/wol-v3/biencoder-predictions.jsonl"),
    "Knowledge graph (ours)":  Path("paper-results/retrieval-cascades/wol-v3/kg-retrieval-predictions.jsonl"),
    "BM25 (raw corpus)":       Path("paper-results/retrieval-cascades/wol-v3/bm25-predictions.jsonl"),
    "BGE (zero-shot)":         Path("paper-results-v2/baselines/wol-v3/bge-predictions.jsonl"),
    "E5 (zero-shot)":          Path("paper-results-v2/baselines/wol-v3/e5-predictions.jsonl"),
    "MPNet (zero-shot)":       Path("paper-results-v2/baselines/wol-v3/mpnet-predictions.jsonl"),
    "TF-IDF (lexical)":        Path("paper-results-v2/baselines/wol-v3/tfidf-predictions.jsonl"),
    "Cross-encoder rerank":    Path("paper-results-v2/baselines/wol-v3/ce-predictions.jsonl"),
}
B_BOOT, SEED = 1000, 42


def load_gold(name):
    g = {}
    with (G / name).open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            ids = d.get("matched_memory_issue_ids") or []
            if ids:
                g[d["window_id"]] = set(ids)
    return g


def score(path, gold):
    out = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            w = d["window_id"]
            if w not in gold:
                continue
            top = list(d.get("matched_issue_ids") or [])[:5]
            gs = gold[w]
            r = next((i + 1 for i, m in enumerate(top) if m in gs), None)
            out[w] = (1.0 if (top and top[0] in gs) else 0.0,
                      1.0 if r else 0.0, 1.0 / r if r else 0.0)
    return out


def boot(a, b, keys, i):
    rng = random.Random(SEED)
    n = len(keys)
    da = [a[k][i] for k in keys]; db = [b[k][i] for k in keys]
    obs = sum(db) / n - sum(da) / n
    ds = []
    for _ in range(B_BOOT):
        idx = [rng.randrange(n) for _ in range(n)]
        ds.append(sum(db[j] - da[j] for j in idx) / n)
    ds.sort()
    p = 2 * min(sum(1 for x in ds if x <= 0), sum(1 for x in ds if x >= 0)) / B_BOOT
    return obs, ds[int(.025 * B_BOOT)], ds[int(.975 * B_BOOT)], min(1.0, p)


def run(rel_file, label):
    gold = load_gold(rel_file)
    R = {k: score(v, gold) for k, v in SYS.items() if v.exists()}
    missing = [k for k, v in SYS.items() if not v.exists()]
    if missing:
        print(f"  !! missing predictions: {missing}")
    keys = sorted(set.intersection(*(set(v) for v in R.values())))
    print(f"\n{'='*72}\n{label}  (n={len(keys)} queries scored by ALL {len(R)} systems)\n{'='*72}")
    print(f"{'method':<26}{'Hit@1':>8}{'Hit@5':>8}{'MRR@5':>8}")
    for k, v in sorted(R.items(), key=lambda kv: -sum(kv[1][q][1] for q in keys)):
        print(f"{k:<26}{sum(v[q][0] for q in keys)/len(keys):>8.4f}"
              f"{sum(v[q][1] for q in keys)/len(keys):>8.4f}"
              f"{sum(v[q][2] for q in keys)/len(keys):>8.4f}")

    H = R["Hybrid fusion (ours)"]
    raw = []
    for k, v in R.items():
        if k == "Hybrid fusion (ours)":
            continue
        for nm, i in (("Hit@1", 0), ("Hit@5", 1), ("MRR@5", 2)):
            o, lo, hi, p = boot(v, H, keys, i)
            raw.append((k, nm, o, lo, hi, p))
    m = len(raw)
    order = sorted(range(m), key=lambda j: raw[j][5])
    q = [0.0] * m; prev = 1.0
    for rank, j in enumerate(reversed(order), start=1):
        prev = min(prev, raw[j][5] * m / (m - rank + 1)); q[j] = prev
    print(f"\nPaired bootstrap (hybrid minus X), BH across {m} tests:")
    print(f"{'vs.':<26}{'metric':<7}{'delta':>9}{'95% CI':>20}{'q(BH)':>8}  sig")
    nsig = 0
    for j, (k, nm, o, lo, hi, p) in enumerate(raw):
        sig = q[j] < 0.05
        nsig += sig
        print(f"{k:<26}{nm:<7}{o:>+9.4f}{f'[{lo:+.4f},{hi:+.4f}]':>20}{q[j]:>8.3f}"
              f"   {'YES' if sig else 'no'}")
    print(f"\n  significant: {nsig}/{m}")
    return {"n": len(keys), "n_systems": len(R),
            "table": {k: {"hit1": sum(v[x][0] for x in keys)/len(keys),
                          "hit5": sum(v[x][1] for x in keys)/len(keys),
                          "mrr":  sum(v[x][2] for x in keys)/len(keys)} for k, v in R.items()},
            "tests": [{"vs": k, "metric": nm, "delta": o, "ci": [lo, hi],
                       "p": p, "q_bh": q[j], "significant": q[j] < 0.05}
                      for j, (k, nm, o, lo, hi, p) in enumerate(raw)]}


if __name__ == "__main__":
    out = {
        "strict": run("window-memory-matchings-strong.jsonl", "STRICT relation"),
        "coarse": run("window-memory-matchings.jsonl", "COARSE relation"),
    }
    dest = Path("paper-results-v2/strict-leaderboard.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[write] {dest}")
