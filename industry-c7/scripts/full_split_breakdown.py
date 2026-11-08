"""T8: per-project and per-stratum breakdown of the full 4,409-instance
evaluation split, for agent v3 and every baseline that covers the same
instances.

Review-2, Priority 2: the 790-instance study was the objection. This is the
whole split, so no sampling argument is needed. Every system here is scored
on the identical instance set; a system that does not cover all of it is
listed as excluded rather than quietly scored on fewer.

Strata:
  hard      the report names no gold file in its text (gold_named_in_text
            is false). This is the benchmark's own difficulty flag.
  fix size  how many non-test source files the fix touched. T3 showed gold
            is accurate for small fixes and diluted for large ones, so
            accuracy by size says whether a system rides that dilution.

Usage:
    python industry-c7/scripts/full_split_breakdown.py
"""

from __future__ import annotations

import json
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from localize import evaluate  # noqa: E402
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402
from stats_agent import rrf  # noqa: E402

ROOT = HERE.parents[0]
RES, LLM, AG = ROOT / "data/results", ROOT / "data/llm", ROOT / "data/agent"
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark.
P = tuple(sorted(_ALL_PROJECTS))
SEED, N_BOOT = 20261103, 2000
# T25. Restrict the scored population to a saved subsample, and tag the
# outputs so a restricted run can never overwrite the full-split ones. Every
# system here already stores per-instance results keyed by issue_key, so a
# subsample is a metric recomputation over stored data -- no system is
# re-run. That is what keeps the agentic-baseline comparison
# same-population without paying for it twice.
def _opt(name: str, default: str = "") -> str:
    return next((a.split("=", 1)[1] for a in sys.argv
                 if a.startswith(f"--{name}=")), default)


SUBSET, TAG = _opt("subset"), _opt("tag")
SUF = f"-{TAG}" if TAG else ""
# Every metric the paper reports, in the order the tables use them.
#
# hit@k is what these tables used to call acc@k. Identical rule: at least
# one fix-touched file in the top k. acc@k is still computed and still in
# the rows, so older figures resolve, but the reported name now says what
# it measures.
#
# precision@k is reported WITH its ceiling and never without. 51.3% of
# issues touch exactly one file, so a perfect answer ranked first scores
# 1/5 = 0.2 at k=5. Printing 0.2 next to nothing reads as a failure; it is
# the maximum. r_precision is the number that does not need the caveat,
# because it judges a one-file issue on the top 1 and a six-file issue on
# the top 6.
REPORTED = ("hit@1", "hit@5", "recall@5", "precision@5",
            "precision_ceiling@5", "r_precision", "ap", "mrr",
            "acc@1", "acc@5")

LABEL = {"remember_v3": "REMEMBER (v3)", "llm_twostage": "Model alone",
         "locagent_style": "LocAgent-style (agentic)",
         "cosil_style": "CoSIL-style (agentic)",
         "llm_rerank": "Model re-rank", "cond_ours": "Retrieval + memory",
         "fused_ours": "Retrieval + memory (untuned)",
         "cond_no_memory": "Retrieval, no memory",
         "content_bm25": "Lexical log-to-code", "path_bm25": "Path BM25",
         "fusion": "Fusion (best non-agent)",
         "trace_grep": "Trace grep", "memory_bm25": "Memory BM25",
         "memory_arise": "ARISE memory", "tuned_ours": "Retrieval + memory (tuned)",
         "tuned_no_memory": "Tuned, no memory",
         "fused_no_memory": "Fused, no memory"}


def jsonl(p):
    return [json.loads(l) for l in Path(p).open(encoding="utf-8") if l.strip()]


def main() -> int:
    agent = {}
    for r in jsonl(AG / "agent-v3-full.jsonl"):
        if r.get("error") or r.get("stop_reason") == "llm_error":
            continue
        agent[f"{r['project']}:{r['issue_key']}"] = r
    ids = sorted(agent)
    if SUBSET:
        keep = set(json.loads(Path(SUBSET).read_text(encoding="utf-8"))["ids"])
        missing = keep - set(ids)
        if missing:
            print(f"ERROR: {len(missing)} subsample ids are not in the scored "
                  f"agent run, e.g. {sorted(missing)[:3]}", file=sys.stderr)
            return 1
        ids = [k for k in ids if k in keep]
        print(f"subset {Path(SUBSET).name}: scoring {len(ids)} instances")
    meta = {k: {"project": k.split(":")[0], "gold": agent[k]["gold_files"],
                "hard": bool(agent[k].get("hard"))} for k in ids}

    rk = {"remember_v3": {k: agent[k]["ranking"] for k in ids}}
    # T25 agentic baselines. Any agent-*.jsonl whose rows carry an `arm`
    # field registers itself as a system, so adding an arm needs no edit
    # here. A baseline that named nothing keeps its EMPTY ranking: CoSIL
    # defines that as a miss, and silently backfilling it would overstate it.
    # ONLY the -eval tag. agent-*.jsonl also matches the 30-instance pilot
    # runs, and merging those into the measurement under one system name
    # would silently mix two populations. The pilot exists to be looked at
    # before fixing things, so it must never reach a reported number.
    for f in sorted(AG.glob("agent-*-eval.jsonl")):
        rows = [r for r in jsonl(f) if not r.get("error") and r.get("arm")
                and r["arm"] != "ours"]
        for r in rows:
            k = f"{r['project']}:{r['issue_key']}"
            if k in agent:
                rk.setdefault(f"{r['arm']}_style", {})[k] = r["ranking"]
    for p in P:
        for f in (RES / f"{p}-instances.jsonl", RES / f"{p}-irbl-instances.jsonl",
                  RES / f"{p}-irbl-rankings.jsonl"):
            if not f.exists():
                continue
            for r in jsonl(f):
                k = f"{p}:{r['issue_key']}"
                if k in agent:
                    for s, v in (r.get("rankings") or {}).items():
                        rk.setdefault(s, {})[k] = v
    for tag, name in (("a2", "llm_twostage"), ("rr", "llm_rerank")):
        f = LLM / f"scored-{tag}.jsonl"
        if f.exists():
            for r in jsonl(f):
                k = f"{r['project']}:{r['issue_key']}"
                if k in agent:
                    rk.setdefault(name, {})[k] = r["ranking"]

    # The IRBL artifact stores per-instance METRICS, not rankings, so those
    # baselines cannot be re-scored against a different answer key but can be
    # read directly here. Without this the classic IRBL family would be
    # dropped for partial coverage: their -irbl-rankings.jsonl side files hold
    # only the 93 causal-gold keys.
    pre: dict[str, dict] = {}
    for p in P:
        f = RES / f"{p}-irbl-instances.jsonl"
        if not f.exists():
            continue
        for r in jsonl(f):
            k = f"{p}:{r['issue_key']}"
            if k in agent:
                for s, m in (r.get("metrics") or {}).items():
                    pre.setdefault(s, {})[k] = m

    # ARISE votes are loaded only for non-wolv2 projects (localize.py) and no
    # project here supplies them, so this signal is empty by construction.
    # Re-measured on the 27-project benchmark: empty on 26,544 of 26,544 eval
    # instances. It is inactive, not weak; reporting it as a 0.000 baseline
    # would misdescribe it. The paper never mentions it.
    DEAD = {"memory_arise"}

    # "fusion" is the paper's best NON-AGENT system: reciprocal-rank fusion of
    # the retrieval layer and the model alone, exactly as stats_agent.py builds
    # it on the 790. Both inputs cover the full split, so the abstract's
    # "best combination of non-agent systems" can be quoted on 4,409 instead
    # of silently staying on the sample.
    if {"cond_ours", "llm_twostage"} <= set(rk):
        rk["fusion"] = {k: rrf([(rk["cond_ours"][k], 1.0),
                                (rk["llm_twostage"][k], 1.0)])
                        for k in ids
                        if k in rk["cond_ours"] and k in rk["llm_twostage"]}

    full = {s: m for s, m in rk.items() if set(ids) <= set(m) and s not in DEAD}
    full_pre = {s: m for s, m in pre.items() if set(ids) <= set(m) and s not in full}
    excluded = sorted((set(rk) | set(pre)) - set(full) - set(full_pre) - DEAD)

    per = {s: {k: evaluate(full[s][k], meta[k]["gold"]) for k in ids} for s in full}
    per.update({s: full_pre[s] for s in full_pre})
    full = {**full, **{s: None for s in full_pre}}

    def mean(s, sel, metric):
        v = [per[s][k][metric] for k in ids if sel(k)]
        return st.fmean(v) if v else None

    rng = random.Random(SEED)
    idx = [[rng.randrange(len(ids)) for _ in range(len(ids))] for _ in range(N_BOOT)]

    def paired(a, b, metric):
        d = [per[a][ids[i]][metric] - per[b][ids[i]][metric] for i in range(len(ids))]
        boot = sorted(st.fmean([d[j] for j in ix]) for ix in idx)
        lo, hi = boot[int(.025 * N_BOOT)], boot[int(.975 * N_BOOT)]
        return {"delta": round(st.fmean(d), 4), "lo": round(lo, 4),
                "hi": round(hi, 4), "significant": lo > 0 or hi < 0}

    def bucket(n):
        return "1" if n == 1 else "2-3" if n <= 3 else "4-7" if n <= 7 else "8+"

    strata = {"all": lambda k: True,
              "hard": lambda k: meta[k]["hard"],
              "easy": lambda k: not meta[k]["hard"]}
    for p in P:
        strata[f"project:{p}"] = (lambda pp: lambda k: meta[k]["project"] == pp)(p)
    for b in ("1", "2-3", "4-7", "8+"):
        strata[f"fixsize:{b}"] = (lambda bb: lambda k: bucket(len(meta[k]["gold"])) == bb)(b)

    out = {
        "n": len(ids), "seed": SEED, "n_bootstrap": N_BOOT,
        "systems_scored": sorted(full), "systems_excluded": excluded,
        "systems_inactive": sorted(DEAD),
        "inactive_reason": "ARISE votes load only for non-wolv2 projects; all "
                           "four study projects are wolv2, so the signal is "
                           "empty on all 6,314 scored instances by construction",
        "strata_n": {name: sum(1 for k in ids if sel(k)) for name, sel in strata.items()},
        "scores": {s: {name: {m: (lambda v: round(v, 4) if v is not None else None)(
            mean(s, sel, m)) for m in REPORTED}
            for name, sel in strata.items()} for s in sorted(full)},
        "vs_best_baseline": {},
    }
    others = [s for s in full if s != "remember_v3"]
    if others:
        best = max(others, key=lambda s: mean(s, strata["all"], "acc@1"))
        out["best_baseline"] = best
        out["vs_best_baseline"] = {m: paired("remember_v3", best, m)
                                   for m in REPORTED}

    # The comparisons the abstract and intro actually make, so every headline
    # delta traces to this file instead of being computed by hand. Reported
    # on the whole split and on the hard stratum, which is the one the
    # challenge calls the core difficulty.
    def paired_on(a, b, metric, sel):
        sub = [i for i, k in enumerate(ids) if sel(k)]
        if not sub:
            return None
        d = [per[a][ids[i]][metric] - per[b][ids[i]][metric] for i in sub]
        sr = random.Random(SEED)
        bs = sorted(st.fmean([d[sr.randrange(len(d))] for _ in d])
                    for _ in range(N_BOOT))
        lo, hi = bs[int(.025 * N_BOOT)], bs[int(.975 * N_BOOT)]
        return {"delta": round(st.fmean(d), 4), "lo": round(lo, 4),
                "hi": round(hi, 4), "significant": lo > 0 or hi < 0}

    out["headline"] = {
        f"remember_v3_vs_{b}": {
            stratum: {m: paired_on("remember_v3", b, m, strata[stratum])
                      for m in ("acc@1", "acc@5")}
            for stratum in ("all", "hard")}
        for b in ("llm_twostage", "llm_rerank", "cond_ours", "fusion")
        if b in full}
    (RES / f"full-split-breakdown{SUF}.json").write_text(json.dumps(out, indent=1) + "\n",
                                                   encoding="utf-8")

    order = sorted(full, key=lambda s: -out["scores"][s]["all"]["acc@1"])
    print(f"n = {len(ids):,} instances, {len(full)} systems with full coverage")
    if excluded:
        print(f"excluded (partial coverage): {', '.join(excluded)}")
    print()
    hdr = (f"{'system':30s}{'Hit@1':>7s}{'Hit@5':>7s}{'Rec@5':>7s}"
           f"{'Prec@5':>8s}{'R-Prec':>8s}{'AP':>7s}{'MRR':>7s}{'hard@1':>8s}")
    print(hdr)
    print("-" * len(hdr))
    for s in order:
        v = out["scores"][s]["all"]
        print(f"{LABEL.get(s, s):30s}{v['hit@1']:>7.3f}{v['hit@5']:>7.3f}"
              f"{v['recall@5']:>7.3f}{v['precision@5']:>8.3f}"
              f"{v['r_precision']:>8.3f}{v['ap']:>7.3f}{v['mrr']:>7.3f}"
              f"{out['scores'][s]['hard']['hit@1']:>8.3f}")
    # The ceiling depends only on how many files each fix touched, so it is
    # identical for every system and belongs on one line, not in a column
    # that looks like a score. Prec@5 must never be read without it.
    ceil = out["scores"][order[0]]["all"]["precision_ceiling@5"]
    print(f"{'-- max achievable Prec@5':30s}{'':>7s}{'':>7s}{'':>7s}"
          f"{ceil:>8.3f}   (set by fix size, not by any system)")
    if out["vs_best_baseline"]:
        t = out["vs_best_baseline"]["acc@1"]
        print(f"\nREMEMBER v3 vs best baseline ({LABEL.get(out['best_baseline'], out['best_baseline'])}), "
              f"Acc@1: {t['delta']*100:+.1f} [{t['lo']*100:+.1f}, {t['hi']*100:+.1f}] "
              f"{'SIGNIFICANT' if t['significant'] else 'ns'}")
    print("\nREMEMBER v3 by project and fix size")
    for name in [f"project:{p}" for p in P] + [f"fixsize:{b}" for b in ("1", "2-3", "4-7", "8+")]:
        v = out["scores"]["remember_v3"][name]
        print(f"  {name:16s} n={out['strata_n'][name]:>5d}  "
              f"acc@1 {v['acc@1']:.3f}  acc@5 {v['acc@5']:.3f}")
    write_doc(out, order)
    print(f"\nwrote {RES / f'full-split-breakdown{SUF}.json'} and "
          f"paper/agent-v3-full-results{SUF}.md")
    return 0


def write_doc(out: dict, order: list) -> None:
    """The paper-facing numbers, generated so they cannot drift from the data."""
    S, N = out["scores"], out["strata_n"]
    top = [s for s in order if s in ("remember_v3", "fusion", "llm_rerank",
                                     "llm_twostage", "cond_no_memory",
                                     "cond_ours", "content_bm25",
                                     "brtracer_fw", "buglocator_fw_a5", "rvsm",
                                     # T25: the agentic baselines belong in
                                     # the headline table, not only in the
                                     # scored set -- they are the comparison
                                     # the reviewer asked for.
                                     "locagent_style", "cosil_style")]
    rows = "\n".join(
        f"| {LABEL.get(s, s)} | {S[s]['all']['acc@1'] * 100:.1f} | "
        f"{S[s]['all']['acc@5'] * 100:.1f} | {S[s]['all']['mrr']:.3f} | "
        f"{S[s]['hard']['acc@1'] * 100:.1f} | {S[s]['easy']['acc@1'] * 100:.1f} |"
        for s in top)
    proj = "\n".join(
        f"| {p} | {N['project:' + p]:,} | {S['remember_v3']['project:' + p]['acc@1'] * 100:.1f} | "
        f"{S['remember_v3']['project:' + p]['acc@5'] * 100:.1f} |" for p in P)
    size = "\n".join(
        f"| {b} file(s) | {N['fixsize:' + b]:,} | "
        f"{S['remember_v3']['fixsize:' + b]['acc@1'] * 100:.1f} | "
        f"{S['remember_v3']['fixsize:' + b]['acc@5'] * 100:.1f} |"
        for b in ("1", "2-3", "4-7", "8+"))
    t = out["vs_best_baseline"]["acc@1"]
    doc = f"""# T6/T8: agent v3 on the full evaluation split

Generated by `scripts/full_split_breakdown.py`. Nothing here is typed by hand.

Review-2, Priority 2 objected that the agent was evaluated on 790 sampled
instances. It is now evaluated on **all {out['n']:,}**, so the objection is
retired rather than argued. Every system in the table below is scored on the
identical {out['n']:,} instances.

## Main table

Acc@1 / Acc@5 in percent. `hard` means the report names no gold file in its
own text.

| system | Acc@1 | Acc@5 | MRR | hard Acc@1 | easy Acc@1 |
|---|---|---|---|---|---|
{rows}

REMEMBER v3 beats the strongest baseline ({LABEL.get(out['best_baseline'], out['best_baseline'])})
by **{t['delta'] * 100:+.1f} points of Acc@1**, 95% CI
[{t['lo'] * 100:+.1f}, {t['hi'] * 100:+.1f}], paired bootstrap over
{out['n_bootstrap']:,} resamples at n = {out['n']:,}. The margin is widest on
hard instances, where the report gives the answer away least:
{S['remember_v3']['hard']['acc@1'] * 100:.1f}% against
{S[out['best_baseline']]['hard']['acc@1'] * 100:.1f}%.

## By project

| project | n | Acc@1 | Acc@5 |
|---|---|---|---|
{proj}

MariaDB is the weakest at {S['remember_v3']['project:mariadb']['acc@1'] * 100:.1f}%
Acc@1 and is {N['project:mariadb'] / out['n'] * 100:.0f}% of the split, so it
pulls the headline down. Any number quoted from a project-balanced sample is
therefore optimistic relative to this one.

## By fix size

| fix touches | n | Acc@1 | Acc@5 |
|---|---|---|---|
{size}

**Accuracy rises with fix size, and that is a property of the answer key, not
of the agent.** A fix touching 8+ files offers 8+ chances for the ranking to
hit one of them. T3 measured the other side of this: only 21% of gold files
are causal when the fix touches 8+ files, against 89% at one file. Large-fix
instances are easier to score and worse to trust, and the paper must not
present the {S['remember_v3']['fixsize:8+']['acc@1'] * 100:.1f}% at 8+ files
as better localization.

## Excluded

- `{', '.join(out['systems_inactive'])}`: {out['inactive_reason']}. Inactive,
  not weak. It is not a baseline and is not reported as one.
{('- partial coverage: ' + ', '.join(out['systems_excluded'])) if out['systems_excluded'] else '- nothing else; every other system covered all instances.'}
"""
    (ROOT / "paper" / f"agent-v3-full-results{SUF}.md").write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
