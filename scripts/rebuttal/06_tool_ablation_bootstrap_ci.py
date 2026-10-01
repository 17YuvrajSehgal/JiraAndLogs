"""R3-Q2: paired-bootstrap CIs for the tool ablation (paper Fig. 4b), the
treatment Fig. 3 already gets. 1000 resamples, seed 42, same as the paper."""
import json, random
from pathlib import Path

ROOT = Path("C:/workplace/JiraAndLogs/paper-results/agent-value")
B, SEED = 1000, 42

def load(ds, cell):
    d = json.load(open(ROOT/ds/"tool-cells"/f"{cell}-report.json", encoding="utf-8"))
    return {c["bundle_id"]: c for c in d["case_results"]}

def paired_boot(a, b, metric):
    """Paired bootstrap over the bundles evaluable in BOTH cells."""
    keys = [k for k in a if k in b
            and a[k].get(metric) is not None and b[k].get(metric) is not None]
    if not keys: return None
    da = [float(a[k][metric]) for k in keys]
    db = [float(b[k][metric]) for k in keys]
    obs = sum(db)/len(db) - sum(da)/len(da)
    rng = random.Random(SEED); n = len(keys); diffs = []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(db[i]-da[i] for i in idx)/n)
    diffs.sort()
    lo, hi = diffs[int(.025*B)], diffs[int(.975*B)]
    # two-sided bootstrap p: fraction of resamples on the other side of 0
    p = 2*min(sum(1 for x in diffs if x <= 0), sum(1 for x in diffs if x >= 0))/B
    return obs, lo, hi, min(1.0, p), len(keys)

CELLS = ["none","events","metrics","peers","trace","events+metrics","events+peers",
         "events+trace","metrics+peers","trace+metrics","trace+peers",
         "events+metrics+peers","events+trace+metrics","events+trace+peers",
         "trace+metrics+peers","events+trace+metrics+peers"]

for ds in ["online-boutique","otel-demo","wol-v3"]:
    print(f"\n{'='*78}\n{ds} - tool ablation vs the no-tool cell (paired bootstrap, 1000x, seed 42)\n{'='*78}")
    try: base = load(ds,"none")
    except FileNotFoundError: print("  (no cells)"); continue
    print(f"{'cell':<26}{'dHit@1':>9}{'95% CI':>20}{'p':>8}   {'dHit@5':>9}{'95% CI':>20}{'p':>8}")
    for c in CELLS:
        try: cur = load(ds,c)
        except FileNotFoundError: continue
        if c == "none": continue
        r1 = paired_boot(base, cur, "hit_at_1"); r5 = paired_boot(base, cur, "hit_at_5")
        if not r1: continue
        s1 = f"[{r1[1]:+.3f},{r1[2]:+.3f}]"; s5 = f"[{r5[1]:+.3f},{r5[2]:+.3f}]"
        star1 = "*" if (r1[1]>0 or r1[2]<0) else " "
        star5 = "*" if (r5[1]>0 or r5[2]<0) else " "
        print(f"{c:<26}{r1[0]:>+9.3f}{s1:>20}{r1[3]:>8.3f}{star1}  {r5[0]:>+9.3f}{s5:>20}{r5[3]:>8.3f}{star5}")
    print(f"  (n paired evaluable cases = {r1[4]};  * = 95% CI excludes 0)")

# The paper's specific claim: the extended-trace reader is net-harmful to Hit@1 (-0.018)
print(f"\n{'='*78}\nPaper's Fig-4b claim: 'extended-trace reader is net-harmful to top-1 (-0.018)'\n{'='*78}")
for ds in ["online-boutique"]:
    for withT, noT in [("events+trace+metrics+peers","events+metrics+peers"),
                       ("trace","none"),("events+trace","events"),
                       ("trace+metrics","metrics"),("trace+peers","peers")]:
        try: a, b = load(ds,noT), load(ds,withT)
        except FileNotFoundError: continue
        r = paired_boot(a, b, "hit_at_1")
        if r: print(f"  +trace: {noT:<22}->{withT:<26} dHit@1={r[0]:+.4f} "
                    f"CI[{r[1]:+.4f},{r[2]:+.4f}] p={r[3]:.3f} {'SIG' if (r[1]>0 or r[2]<0) else 'n.s.'}")
