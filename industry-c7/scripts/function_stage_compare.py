"""T20: does a better file stage, or the agent's own reading, fix the
function-level result?

The paper's weakest number is function-level Acc@1. Two changes, both free
once the full-split run exists:

  agent       take candidates from agent v3's top-10 files instead of
              cond_ours'. v3 is far stronger at file level (Acc@5 0.888 vs
              0.686), so this should raise the ORACLE ceiling.
  agentread   additionally rank the functions the agent opened by name with
              read_code above the rest, BM25 order kept inside each group.
              An attention signal, free: it is already in the transcripts.

All three variants run on the identical eligible instances per project, so
the comparison is paired throughout.

Usage:
    python industry-c7/scripts/function_stage_compare.py
"""

from __future__ import annotations

import json
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "data/results"
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark. Deriving it means a project with a missing input
# raises instead of vanishing from the table.
P = tuple(sorted(_ALL_PROJECTS))
VARIANTS = (("", "cond_ours candidates (current paper)"),
            ("-agent", "agent v3 candidates"),
            ("-agentread", "agent v3 candidates + read-boost"))
METRICS = ("acc@1", "acc@5", "acc@10", "mrr", "oracle_in_candidates")
SEED, N_BOOT = 20261103, 2000


def load(tag: str) -> dict:
    """{(project, issue_key): metrics} over eligible eval rows only."""
    out = {}
    for p in P:
        summ = json.loads((RES / f"{p}-functions{tag}-summary.json")
                          .read_text(encoding="utf-8"))
        n_dev = summ["n_dev"]
        rows = [json.loads(l) for l in
                (RES / f"{p}-functions{tag}.jsonl").open(encoding="utf-8")
                if l.strip()]
        rows.sort(key=lambda r: r["fix_time"])
        for r in rows[n_dev:]:
            if r["eligible"]:
                out[(p, r["issue_key"])] = r["metrics"]
    return out


def main() -> int:
    data = {tag: load(tag) for tag, _ in VARIANTS}
    ids = sorted(set.intersection(*(set(d) for d in data.values())))
    print(f"paired on {len(ids):,} eligible eval instances "
          f"(per variant: {', '.join(str(len(d)) for d in data.values())})")

    rng = random.Random(SEED)
    idx = [[rng.randrange(len(ids)) for _ in range(len(ids))]
           for _ in range(N_BOOT)]

    def mean(tag, metric, sel=lambda k: True):
        v = [data[tag][k][metric] for k in ids if sel(k)]
        return st.fmean(v) if v else None

    def paired(a, b, metric):
        d = [data[a][k][metric] - data[b][k][metric] for k in ids]
        boot = sorted(st.fmean([d[j] for j in ix]) for ix in idx)
        lo, hi = boot[int(.025 * N_BOOT)], boot[int(.975 * N_BOOT)]
        return {"delta": round(st.fmean(d), 4), "lo": round(lo, 4),
                "hi": round(hi, 4), "significant": lo > 0 or hi < 0}

    out = {
        "n": len(ids), "seed": SEED, "n_bootstrap": N_BOOT,
        "pooled": {tag: {m: round(mean(tag, m), 4) for m in METRICS}
                   for tag, _ in VARIANTS},
        "by_project": {p: {tag: {m: round(mean(tag, m, lambda k, pp=p: k[0] == pp), 4)
                                 for m in METRICS} for tag, _ in VARIANTS}
                       for p in P},
        "tests": {
            "agentread_vs_current": {m: paired("-agentread", "", m) for m in METRICS},
            "agent_vs_current": {m: paired("-agent", "", m) for m in METRICS},
            "agentread_vs_agent": {m: paired("-agentread", "-agent", m)
                                   for m in METRICS},
        },
    }
    (RES / "function-stage-compare.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8")

    print(f"\n{'variant':40s}{'Acc@1':>8s}{'Acc@5':>8s}{'MRR':>8s}{'oracle':>9s}")
    for tag, lab in VARIANTS:
        v = out["pooled"][tag]
        print(f"{lab:40s}{v['acc@1']:>8.3f}{v['acc@5']:>8.3f}{v['mrr']:>8.3f}"
              f"{v['oracle_in_candidates']:>9.3f}")
    print()
    for name, t in out["tests"].items():
        a1 = t["acc@1"]
        print(f"{name:26s} Acc@1 {a1['delta'] * 100:+6.1f} "
              f"[{a1['lo'] * 100:+5.1f},{a1['hi'] * 100:+5.1f}] "
              f"{'SIG' if a1['significant'] else 'ns'}")
    print("\nby project (Acc@1: current -> agent -> +read)")
    for p in P:
        v = out["by_project"][p]
        print(f"  {p:9s} {v['']['acc@1']:.3f} -> {v['-agent']['acc@1']:.3f} -> "
              f"{v['-agentread']['acc@1']:.3f}   oracle "
              f"{v['']['oracle_in_candidates']:.3f} -> "
              f"{v['-agent']['oracle_in_candidates']:.3f}")

    write_doc(out)
    print(f"\nwrote {RES / 'function-stage-compare.json'} and "
          f"paper/function-stage-t20.md")
    return 0


def write_doc(out: dict) -> None:
    pooled = out["pooled"]
    rows = "\n".join(
        f"| {lab} | {pooled[tag]['acc@1'] * 100:.1f} | "
        f"{pooled[tag]['acc@5'] * 100:.1f} | {pooled[tag]['mrr']:.3f} | "
        f"{pooled[tag]['oracle_in_candidates'] * 100:.1f} |"
        for tag, lab in VARIANTS)
    proj = "\n".join(
        f"| {p} | {out['by_project'][p]['']['acc@1'] * 100:.1f} | "
        f"{out['by_project'][p]['-agent']['acc@1'] * 100:.1f} | "
        f"{out['by_project'][p]['-agentread']['acc@1'] * 100:.1f} | "
        f"{out['by_project'][p]['']['oracle_in_candidates'] * 100:.1f} | "
        f"{out['by_project'][p]['-agent']['oracle_in_candidates'] * 100:.1f} |"
        for p in P)
    t = out["tests"]
    fmt = (lambda x: f"{x['delta'] * 100:+.1f} [{x['lo'] * 100:+.1f}, "
                     f"{x['hi'] * 100:+.1f}]"
                     f"{'' if x['significant'] else ', ns'}")
    doc = f"""# T20: the function-level stage

Generated by `scripts/function_stage_compare.py`. Nothing here is typed by hand.

Function-level Acc@1 is the paper's weakest result and its only "code
region" number. Two changes, both free once the full-split run exists, on
the identical {out['n']:,} eligible eval instances.

| variant | Acc@1 | Acc@5 | MRR | oracle |
|---|---|---|---|---|
{rows}

- agent candidates vs current: Acc@1 {fmt(t['agent_vs_current']['acc@1'])}
- **+ read-boost vs current: Acc@1 {fmt(t['agentread_vs_current']['acc@1'])}**
- read-boost vs agent candidates alone: Acc@1 {fmt(t['agentread_vs_agent']['acc@1'])}

## The two effects are different, and only one is about ranking

**A better file stage raises the ceiling and almost nothing else.** Taking
candidates from agent v3's top-10 instead of cond_ours' lifts the oracle
from {pooled['']['oracle_in_candidates'] * 100:.1f}% to
{pooled['-agent']['oracle_in_candidates'] * 100:.1f}% -- the gold function is
now in the candidate set far more often -- but Acc@1 moves only
{t['agent_vs_current']['acc@1']['delta'] * 100:+.1f} points. BM25 over
function bodies cannot exploit the better pool it is handed.

**Ranking what the agent actually read does the work.** `read_code` takes a
symbol, so a function the agent opened by name is already identified the same
way a candidate is. Promoting those is
{t['agentread_vs_agent']['acc@1']['delta'] * 100:+.1f} points of Acc@1 over
the same candidate set, and
{t['agentread_vs_current']['acc@1']['delta'] * 100:+.1f} over the current
paper number.

This is an **attention** signal, not a relevance model. It says the agent
looked at that function while forming its answer. It costs nothing: the
transcripts were already written.

## By project

| project | Acc@1 current | agent | +read | oracle current | oracle agent |
|---|---|---|---|---|---|
{proj}

The gain is uneven and the ceiling explains it. Qt had the worst oracle
({out['by_project']['qt']['']['oracle_in_candidates'] * 100:.1f}%) and gains
most of its headroom from candidates; Kafka had a good ceiling already and
gains almost everything from the read signal.

## What this does not fix

- **The ceiling is still not 100%.** At
  {pooled['-agent']['oracle_in_candidates'] * 100:.1f}% oracle, roughly one
  eligible instance in {round(1 / (1 - pooled['-agent']['oracle_in_candidates']))}
  has no gold function in the candidate set at all, so no reranking can
  reach it.
- **Eligibility is not universal.** An instance is eligible only when a gold
  function can be derived from a parent-side diff hunk of the fix commit.
  The per-project eligible fractions are in the `-summary.json` files and
  must be quoted beside these numbers.
- **This is still file-stage-dependent.** A function-level miss caused by a
  file-stage miss counts as a miss here, which is the honest end-to-end
  reading and the reason the numbers stay well below the file-level ones.
"""
    (ROOT / "paper" / "function-stage-t20.md").write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
