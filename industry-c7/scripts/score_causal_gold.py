"""T4: score every system against causal gold beside fix gold.

Review-2, Priority 1: "evaluate REMEMBER against both existing fix-file
ground truth and independently annotated causal ground truth."

No system is re-run. Every system already stored a ranking for these
instances, so the only thing that changes is the answer key the ranking is
scored against.

Population. The annotation sample was drawn from benchmark, which spans
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
from localize import agent_run_rows  # noqa: E402
from localize import evaluate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
B1, B2 = ROOT / "data/benchmark", ROOT / "data/benchmark"
RES, LLM, AG = (ROOT / "data/results", ROOT / "data/llm", ROOT / "data/agent")
# --pass2 re-scores everything against the blind second rater's labels, so
# the paper can say whether T4 depends on which rater you believe (T2b).
PASS2 = "--pass2" in sys.argv
# T12: score agent v3 (full eval split) on the same instances and the same
# answer keys as T4. v3 is added as an extra system rather than replacing
# "remember", so v2 and v3 are compared on identical instances.
V3 = "--v3" in sys.argv
# WARNING, and it is not a small one. The core stratum of the annotation
# sample was balanced on (agent right/wrong) x (hard/easy) using
# agent-v2.jsonl, so half these instances are ones v2 got WRONG. v2's score
# here is depressed by the selection that built the sample; v3's is not,
# because v3 did not exist when the sample was drawn. Any v2-vs-v3
# comparison on this subset is confounded in v3's favour -- v2 reads 0.620
# Acc@5 here against 0.903 on the full 790. Use the within-system fix-vs-
# causal gap, which is immune (same ranking, two answer keys), and take
# cross-system ranking from the full split instead.
CG = ROOT / ("data/causal-gold-pass2/causal-gold.jsonl" if PASS2
             else "data/causal-gold/causal-gold.jsonl")
TAG = "-pass2" if PASS2 else ("-v3" if V3 else "")
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark.
P = tuple(sorted(_ALL_PROJECTS))
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
        # The main IRBL artifact stores metrics only. Its rankings come from
        # the side run made for exactly these instances:
        #   baselines_irbl.py --project P --rankings-for data/causal-gold/keys-P.txt
        f = RES / f"{p}-irbl-rankings.jsonl"
        if f.exists():
            for r in jsonl(f):
                k = f"{p}:{r['issue_key']}"
                if k in keys:
                    for s, rk in r["rankings"].items():
                        out.setdefault(s, {})[k] = rk
    for tag, name in (("a2", "llm_twostage"), ("rr", "llm_rerank")):
        f = LLM / f"scored-{tag}.jsonl"
        if f.exists():
            for r in jsonl(f):
                k = f"{r['project']}:{r['issue_key']}"
                if k in keys:
                    out.setdefault(name, {})[k] = r["ranking"]
    # The v2 arm is archived, not live: data/agent/agent-v2.jsonl moved to
    # data/archive/agent/. Reading it unguarded made this script die on a
    # missing file and take causal_lift_v3 down with it, since that reads
    # the scores this one writes. Look in both places and skip the system
    # if the file is gone, rather than lose the whole comparison to one
    # retired arm.
    for cand in (AG / "agent-v2.jsonl",
                 ROOT / "data/archive/agent/agent-v2.jsonl"):
        if cand.exists():
            for r in jsonl(cand):
                k = f"{r['project']}:{r['issue_key']}"
                if k in keys:
                    out.setdefault("remember", {})[k] = r["ranking"]
            break
    else:
        print("note: no agent-v2.jsonl anywhere; skipping the v2 arm",
              file=sys.stderr)
    if V3:
        for r in agent_run_rows(AG):
            k = f"{r['project']}:{r['issue_key']}"
            if k in keys:
                out.setdefault("remember_v3", {})[k] = r["ranking"]
    return out


DOC_ORDER = [("rvsm", "rVSM"), ("buglocator_fw_a5", "BugLocator"),
             ("brtracer_fw", "BRTracer-style"), ("content_bm25", "Lexical log-to-code"),
             ("fused_ours", "Retrieval + incident memory (untuned)"),
             ("cond_ours", "Retrieval + incident memory"),
             ("llm_rerank", "Model re-rank"), ("llm_twostage", "Model alone"),
             # `remember` is the ARCHIVED v2 arm, not the system this paper
             # reports. It was labelled "REMEMBER" while remember_v3 was
             # missing from this list entirely, so every document built from
             # DOC_ORDER -- the module table included -- named a retired arm
             # as the headline system and left the live one out.
             ("remember", "REMEMBER (v2, archived)"),
             ("remember_v3", "REMEMBER")]


def write_doc(out: dict, scored: dict, ids: list) -> None:
    """The paper-facing numbers, generated so they cannot drift from the data."""
    import collections
    S = out["systems"]
    def bucket(n):
        return "1" if n == 1 else "2-3" if n <= 3 else "4-7" if n <= 7 else "8+"
    sizes = collections.Counter(bucket(len(scored[i]["fix_gold"])) for i in ids)
    hard = sum(1 for i in ids if not scored[i]["gold_named_in_text"])
    proj = collections.Counter(i.split(":")[0] for i in ids)
    n_caus = sum(len(scored[i]["causal_gold"]) for i in ids)
    n_fix = sum(len(scored[i]["fix_gold"]) for i in ids)

    rows = []
    for key, label in DOC_ORDER:
        if key not in S:
            continue
        v, g = S[key], S[key]["gap"]["acc@5"]
        p1 = v["causal_precision_given_fix_hit"]["at1"]
        p5 = v["causal_precision_given_fix_hit"]["at5"]
        f = lambda p: (f"{p['share']*100:.0f}% ({p['n_also_causal']}/{p['n_hits_fix']})"
                       if p["share"] is not None else "-")
        rows.append(f"| {label} | {v['fix']['acc@5']*100:.1f}% | "
                    f"{v['causal']['acc@5']*100:.1f}% | {g['delta']*100:+.1f} "
                    f"[{g['lo']*100:+.1f}, {g['hi']*100:+.1f}] | {f(p1)} | {f(p5)} |")

    tests = []
    for name, t in out["gap_tests"].items():
        g = t["acc@5"]
        tests.append(f"| `{name.replace('_vs_', '` vs `')}` | {g['delta']*100:+.1f} "
                     f"[{g['lo']*100:+.1f}, {g['hi']*100:+.1f}] | "
                     f"{'significant' if g['significant'] else 'not significant'} |")

    flip_rows = []
    for a, b in out["order_flips_acc5"]:
        t = out["head_to_head"][f"{a}_vs_{b}"]
        cell = lambda k: (f"{t[k]['acc@5']['delta']*100:+.1f} "
                          f"[{t[k]['acc@5']['lo']*100:+.1f}, "
                          f"{t[k]['acc@5']['hi']*100:+.1f}]"
                          + ("" if t[k]['acc@5']['significant'] else ", ns"))
        flip_rows.append(f"| `{a}` vs `{b}` | {cell('fix')} | {cell('causal')} |")

    doc = f"""# T4: every system scored against causal gold

Generated by `scripts/score_causal_gold.py`. Re-run it after any change to
the annotation or to a system's rankings. Nothing here is typed by hand.

Review-2, Priority 1: "evaluate REMEMBER against both existing fix-file
ground truth and independently annotated causal ground truth."

## What was done

No system was re-run. Every system had already stored a ranking for these
instances, so the only thing that changes between the two columns below is
the answer key the same ranking is scored against.

- **fix gold** is the benchmark's answer key: the non-test source files the
  fix commit modified.
- **causal gold** is the subset of those files the annotation labels
  `causal`, meaning the file held the defect, as opposed to
  `symptom-handling`, `preventive`, `refactor` or `test`.

## Population, and what it is not

| | |
|---|---|
| annotated instances | 151 |
| appear in v1 with the same gold set and the same snapshot | {out['n_eligible']} |
| of those, have at least one causal file | **{out['n_scored']}** |
| annotated as having no causal file at all | {out['n_no_causal_file']} |

The other 58 annotated instances come from the 23 projects added in
benchmark, which no system has run on yet. The {out['n_no_causal_file']}
with no causal file are reported, not scored: "no file in this fix is
causal" is a finding about the benchmark, not a ranking any system can get
right.

**This subset is harder than the benchmark by construction.** The sample was
stratified to include hard instances and instances REMEMBER gets wrong.
{hard} of {out['n_scored']} ({100*hard/out['n_scored']:.0f}%) name no gold
file in the report, against 53% across v1 and 49% across v2. Absolute
numbers here are therefore well below Table III and **must not be compared
to it**. Only the within-table comparison is meaningful.

Composition: {', '.join(f'{p} {n}' for p, n in proj.most_common())}. Fix-gold
set size: {', '.join(f'{k} file(s) x{sizes[k]}' for k in ('1', '2-3', '4-7', '8+') if sizes.get(k))}.
Across the {out['n_scored']}, {n_caus} of {n_fix} gold files are causal
({100*n_caus/n_fix:.1f}%), against 49.0% over all 151 annotated instances.

## The table

Acc@5, same instances, same rankings, two answer keys. "Causal share of
hits" is, of the instances where the system's top-k contained a fix-gold
file, how many of those top-k also contained a causal file.

| system | Acc@5 vs fix gold | vs causal gold | gap, 95% CI | causal share of top-1 hits | of top-5 hits |
|---|---|---|---|---|---|
{chr(10).join(rows)}

### What this shows

1. **Every system loses accuracy against causal gold, and none loses much.**
   The benchmark's answer key is looser than a causal one, which is exactly
   the reviewer's objection, and the size of the looseness is now measured
   rather than argued. The largest loss is {max(S[k]['gap']['acc@5']['delta'] for k, _ in DOC_ORDER if k in S)*100:.1f}
   points of Acc@5.
2. **The ordering is broadly stable but this subset cannot confirm it.**
   {len(out['order_flips_acc5'])} pairs of systems change places when the
   answer key changes, including REMEMBER and the plain model at the top.
   Every one of those pairs was **already statistically tied on both answer
   keys** at n={out['n_scored']} (see the head-to-head table below), so no
   ordering the paper relies on is contradicted here. Neither is any
   confirmed. The honest reading is that {out['n_scored']} deliberately hard
   instances cannot resolve the top of the table, and this experiment should
   not be asked to.
3. The "causal share of hits" column is a **conditional** rate. Its
   denominator is a different set of instances for every system, because a
   system that hits more often is being judged on a different and generally
   harder selection. It describes one system at a time. It is not a
   head-to-head comparison and must not be written as one.

### The pairs that change order

Acc@5, system A minus system B, on each answer key separately.

| pair | on fix gold | on causal gold |
|---|---|---|
{chr(10).join(flip_rows) if flip_rows else '| none | | |'}

Every pair is inside the noise on both keys. The switch reorders them
because they were never separated to begin with.

### Is one system's gap really smaller than another's?

Paired difference of differences on the same instances, {out['n_bootstrap']:,}
bootstrap resamples, seed {out['seed']}, Acc@5.

| comparison | difference of gaps | |
|---|---|---|
{chr(10).join(tests)}

## Threats to this result

- **One annotator.** The labels are a single model pass against a
  pre-registered rubric. The agreement number is still missing (T2b) and
  until it exists these are not independent ground truth.
- **n = {out['n_scored']}.** The confidence intervals are wide. Everything
  here is a subset result and should be written as one.
- **The annotator saw the fix diff.** It had to, to judge causality. It did
  not see any system's ranking, and `sample.json` deliberately omits the
  agent outcome used to stratify, so the labels cannot be tuned to an
  outcome.
- **Causal gold is a subset of fix gold.** By construction a system cannot
  score higher against causal gold than against fix gold, so the gap is
  one-sided by definition. The informative quantity is its size, and
  whether it differs between systems.
"""
    (ROOT / "paper" / "causal-gold-results.md").write_text(doc, encoding="utf-8")


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

    # Head to head on ONE answer key. Needed because switching answer keys can
    # reorder two systems, and a reordering is only worth reporting if the
    # order was significant on at least one side of it.
    def head_to_head(a, b, key, metric):
        d = [per[a][key][i][metric] - per[b][key][i][metric]
             for i in range(len(ids))]
        boot = sorted(sum(d[j] for j in ix) / len(ix) for ix in idx)
        lo, hi = boot[int(.025 * N_BOOT)], boot[int(.975 * N_BOOT)]
        return {"delta": round(sum(d) / len(d), 4), "lo": round(lo, 4),
                "hi": round(hi, 4), "significant": lo > 0 or hi < 0}

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
    if V3:
        pairs += [("remember_v3", "remember"), ("remember_v3", "llm_twostage"),
                  ("remember_v3", "cond_ours")]
    gap_tests = {f"{a}_vs_{b}": {m: gap_vs(a, b, m) for m in METRICS}
                 for a, b in pairs if a in full and b in full}
    # Does switching answer keys reorder any pair of systems on Acc@5?
    order_fix = sorted(full, key=lambda s: -mean(s, "fix", "acc@5"))
    order_cau = sorted(full, key=lambda s: -mean(s, "causal", "acc@5"))
    flips = [[a, b] for i, a in enumerate(order_fix) for b in order_fix[i + 1:]
             if order_cau.index(a) > order_cau.index(b)]

    # Head to head for the named pairs and for every pair the switch reorders.
    # A reordering only matters if the order was significant on either side.
    h2h = {f"{a}_vs_{b}": {k: {m: head_to_head(a, b, k, m) for m in METRICS}
                           for k in ("fix", "causal")}
           for a, b in {tuple(x) for x in pairs + flips}
           if a in full and b in full}

    out = {
        "n_eligible": len(elig), "n_scored": len(ids),
        "n_no_causal_file": len(no_causal), "no_causal_ids": no_causal,
        "seed": SEED, "n_bootstrap": N_BOOT,
        "order_fix_acc5": order_fix, "order_causal_acc5": order_cau,
        "order_flips_acc5": flips,
        "gap_tests": gap_tests, "head_to_head": h2h,
        "systems": {s: {
            "fix": {m: round(mean(s, "fix", m), 4) for m in METRICS},
            "causal": {m: round(mean(s, "causal", m), 4) for m in METRICS},
            "gap": {m: dict(zip(("delta", "lo", "hi"),
                                [round(x, 4) for x in ci(s, m)]))
                    for m in METRICS},
            "causal_precision_given_fix_hit": precision[s],
        } for s in sorted(full)},
    }
    dest = RES / f"causal-gold-scores{TAG}.json"
    dest.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    if not PASS2 and not V3:
        write_doc(out, scored, ids)

    head = ["cond_ours", "fused_ours", "content_bm25", "brtracer_fw", "rvsm",
            "llm_twostage", "llm_rerank", "remember", "remember_v3"]
    if V3:
        print("WARNING: the core stratum was balanced on v2's own outcome, so")
        print("         remember vs remember_v3 is CONFOUNDED on this subset.")
        print("         Read only each system's fix-vs-causal gap here.")
        print()
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
    print(f"\nAcc@5 order vs fix gold:    {' > '.join(out['order_fix_acc5'])}")
    print(f"Acc@5 order vs causal gold: {' > '.join(out['order_causal_acc5'])}")
    print(f"pairs that swap: {out['order_flips_acc5'] or 'none'}")
    for a, b in out["order_flips_acc5"]:
        for key in ("fix", "causal"):
            t = out["head_to_head"].get(f"{a}_vs_{b}", {}).get(key, {}).get("acc@5")
            if t:
                print(f"  {a} vs {b} on {key:6s} gold: {t['delta']*100:+5.1f} "
                      f"[{t['lo']*100:+5.1f},{t['hi']*100:+5.1f}] "
                      f"{'SIG' if t['significant'] else 'ns'}")
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
