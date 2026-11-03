"""T4: score every system against causal gold beside fix gold.

Review-2, Priority 1: "evaluate REMEMBER against both existing fix-file
ground truth and independently annotated causal ground truth."

No system is re-run. Every system already stored a ranking for these
instances, so the only thing that changes is the answer key the ranking is
scored against.

Population. The annotation sample was drawn from benchmark-v2, which spans
27 projects; the stored rankings exist only for the four v1 study projects.
An instance is eligible when it appears in v1 with the SAME gold set and the
SAME snapshot, so the ranking really was produced against this answer key.
Instances the annotation found to have no causal file at all are reported
separately rather than scored, because "no file in this fix is causal" is a
finding about the benchmark, not a ranking a system can get right.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import evaluate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
B1, B2 = ROOT / "data/benchmark", ROOT / "data/benchmark-v2"
RES, LLM, AG = (ROOT / "data/results", ROOT / "data/llm", ROOT / "data/agent")
CG = ROOT / "data/causal-gold/causal-gold.jsonl"
P = ("kafka", "mariadb", "mongodb", "qt")
SEED, N_BOOT = 20261102, 2000
METRICS = ("acc@1", "acc@5", "acc@10", "mrr")


def jsonl(p):
    return [json.loads(l) for l in Path(p).open(encoding="utf-8")]


def eligible() -> dict:
    """{id: causal-gold row} for instances whose v1 answer key matches v2."""
    v1 = {f"{p}:{r['issue_key']}": r for p in P for r in jsonl(B1 / f"{p}.jsonl")}
    v2 = {f"{p}:{r['issue_key']}": r for p in P for r in jsonl(B2 / f"{p}.jsonl")}
    out = {}
    for r in jsonl(CG):
        k = r["id"]
        a, b = v1.get(k), v2.get(k)
        if a and b and set(a["gold_files"]) == set(b["gold_files"]) \
                and a["snapshot_sha"] == b["snapshot_sha"]:
            out[k] = r
    return out


def rankings(keys: set) -> dict:
    """{system: {id: ranking}} from every stored run."""
    out = {}
    for p in P:
        for r in jsonl(RES / f"{p}-instances.jsonl"):
            k = f"{p}:{r['issue_key']}"
            if k in keys:
                for s, rk in r["rankings"].items():
                    out.setdefault(s, {})[k] = rk
        for r in jsonl(RES / f"{p}-irbl-instances.jsonl"):
            k = f"{p}:{r['issue_key']}"
            if k in keys and "rankings" in r:
                for s, rk in r["rankings"].items():
                    out.setdefault(s, {})[k] = rk
    for tag, name in (("a2", "llm_twostage"), ("rr", "llm_rerank")):
        f = LLM / f"scored-{tag}.jsonl"
        if f.exists():
            for r in jsonl(f):
                k = f"{r['project']}:{r['issue_key']}"
                if k in keys:
                    out.setdefault(name, {})[k] = r["ranking"]
    for r in jsonl(AG / "agent-v2.jsonl"):
        k = f"{r['project']}:{r['issue_key']}"
        if k in keys:
            out.setdefault("remember", {})[k] = r["ranking"]
    return out


def main() -> int:
    elig = eligible()
    scored = {k: r for k, r in elig.items() if r["causal_gold"]}
    no_causal = sorted(set(elig) - set(scored))
    rk = rankings(set(elig))
    # only systems with a ranking for every scored instance: anything less
    # would compare systems on different populations
    full = {s: m for s, m in rk.items() if set(scored) <= set(m)}
    ids = sorted(scored)

    per = {}
    for s, m in full.items():
        per[s] = {
            "fix": [evaluate(m[i], scored[i]["fix_gold"]) for i in ids],
            "causal": [evaluate(m[i], scored[i]["causal_gold"]) for i in ids],
        }

    def mean(s, key, metric):
        v = per[s][key]
        return sum(x[metric] for x in v) / len(v)

    # paired bootstrap on the fix - causal gap, shared resample indices
    rng = random.Random(SEED)
    idx = [[rng.randrange(len(ids)) for _ in range(len(ids))]
           for _ in range(N_BOOT)]

    def ci(s, metric):
        d = [per[s]["fix"][i][metric] - per[s]["causal"][i][metric]
             for i in range(len(ids))]
        boot = sorted(sum(d[j] for j in ix) / len(ix) for ix in idx)
        return (sum(d) / len(d), boot[int(.025 * N_BOOT)], boot[int(.975 * N_BOOT)])

    # "right file, wrong reason": of the answers that hit fix gold, how many
    # land on a file the annotation calls causal? Reported at k=1 and k=5.
    # Read it as a conditional rate: the denominator is a different set of
    # instances for every system, because a system that hits more often is
    # being judged on a different, generally harder, selection. It is not a
    # head-to-head comparison and must not be presented as one.
    precision = {}
    for s, m in full.items():
        precision[s] = {}
        for k in (1, 5):
            hit, caus = [], []
            for i in ids:
                top = set(m[i][:k])
                if top & set(scored[i]["fix_gold"]):
                    hit.append(i)
                    if top & set(scored[i]["causal_gold"]):
                        caus.append(i)
            precision[s][f"at{k}"] = {
                "n_hits_fix": len(hit), "n_also_causal": len(caus),
                "share": round(len(caus) / len(hit), 4) if hit else None}

    # Is one system's fix-to-causal gap really smaller than another's? Paired
    # difference of differences on the same instances, same resample indices.
    def gap_vs(a, b, metric):
        d = [(per[a]["fix"][i][metric] - per[a]["causal"][i][metric])
             - (per[b]["fix"][i][metric] - per[b]["causal"][i][metric])
             for i in range(len(ids))]
        boot = sorted(sum(d[j] for j in ix) / len(ix) for ix in idx)
        lo, hi = boot[int(.025 * N_BOOT)], boot[int(.975 * N_BOOT)]
        return {"delta": round(sum(d) / len(d), 4), "lo": round(lo, 4),
                "hi": round(hi, 4), "significant": lo > 0 or hi < 0}

    pairs = [("remember", "llm_twostage"), ("remember", "cond_ours"),
             ("llm_twostage", "cond_ours")]
    gap_tests = {f"{a}_vs_{b}": {m: gap_vs(a, b, m) for m in METRICS}
                 for a, b in pairs if a in full and b in full}

    out = {
        "n_eligible": len(elig), "n_scored": len(ids),
        "n_no_causal_file": len(no_causal), "no_causal_ids": no_causal,
        "seed": SEED, "n_bootstrap": N_BOOT,
        "gap_tests": gap_tests,
        "systems": {s: {
            "fix": {m: round(mean(s, "fix", m), 4) for m in METRICS},
            "causal": {m: round(mean(s, "causal", m), 4) for m in METRICS},
            "gap": {m: dict(zip(("delta", "lo", "hi"),
                                [round(x, 4) for x in ci(s, m)]))
                    for m in METRICS},
            "causal_precision_given_fix_hit": precision[s],
        } for s in sorted(full)},
    }
    dest = RES / "causal-gold-scores.json"
    dest.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")

    head = ["cond_ours", "fused_ours", "content_bm25", "brtracer_fw", "rvsm",
            "llm_twostage", "llm_rerank", "remember"]
    print(f"n={len(ids)} scored, {len(no_causal)} annotated as having no "
          f"causal file, {len(elig)} eligible of 151 annotated\n")
    print(f"{'system':16s} {'Acc@5 fix':>10s} {'causal':>8s} {'gap':>7s} "
          f"{'95% CI':>18s}   {'top-1 hits that':>16s}")
    print(f"{'':16s} {'':10s} {'':8s} {'':7s} {'':18s}   {'are causal':>16s}")
    for s in head:
        if s not in out["systems"]:
            continue
        v = out["systems"][s]
        g = v["gap"]["acc@5"]
        pr = v["causal_precision_given_fix_hit"]["at1"]
        sh = f"{pr['share']*100:.0f}% ({pr['n_also_causal']}/{pr['n_hits_fix']})" \
            if pr["share"] is not None else "-"
        print(f"{s:16s} {v['fix']['acc@5']*100:9.1f}% {v['causal']['acc@5']*100:7.1f}% "
              f"{g['delta']*100:+6.1f} [{g['lo']*100:+6.1f},{g['hi']*100:+6.1f}]   {sh:>16s}")
    print("\nis one system's gap really smaller than another's? "
          "(paired difference of differences, Acc@5)")
    for name, t in out["gap_tests"].items():
        g = t["acc@5"]
        print(f"  {name:28s} {g['delta']*100:+6.1f} "
              f"[{g['lo']*100:+6.1f},{g['hi']*100:+6.1f}]  "
              f"{'SIG' if g['significant'] else 'ns'}")
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
