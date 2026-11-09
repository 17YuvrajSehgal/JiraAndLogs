"""T25: \\sys{} against the two reimplemented agentic localizers.

`full_split_breakdown.py --subset` already scores both arms beside the
other 37 systems on identical instances. This adds what a ranking table
cannot carry and what the comparison actually turns on:

  * paired bootstrap against \\sys{}, on `all` and on `hard`, so a gap is
    reported with an interval rather than as two point estimates;
  * COST, which the pilot suggested is where the arms differ most --
    LocAgent-style matched us on ranking at roughly a third of the wall
    time, and an industry-track paper that argues about what accuracy
    costs cannot leave that out;
  * EMPTY RATE, which is CoSIL's own metric and the port's sanity check:
    reflective alignment exists to fix unparseable output, so CoSIL-style
    should show the lower rate. Reported either way;
  * TOOL USE, because the pilot measured LocAgent-style calling
    traverse_graph zero times in 30 runs, and multi-hop traversal is the
    property their Table 1 uses to distinguish LocAgent. If that holds at
    n=1,000 it is a finding about agent design, not a footnote.

Everything is scored on the instances all three systems completed, so no
arm is flattered by the ones it failed.

Usage:
    python industry-c7/scripts/agentic_baselines_compare.py
"""

from __future__ import annotations

import json
import random
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
AG, RES = ROOT / "data/agent", ROOT / "data/results"
sys.path.insert(0, str(HERE))
from localize import agent_run_rows  # noqa: E402
from localize import is_dead_row  # noqa: E402
SEED, N_BOOT = 20261104, 2000
ARMS = {"locagent": "LocAgent-style", "cosil": "CoSIL-style"}


def rows(f: Path) -> dict:
    out = {}
    if not f.exists():
        return out
    for line in f.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if is_dead_row(r):
            continue
        out[r["id"]] = r
    return out


def main() -> int:
    ours = {r["id"]: r for r in agent_run_rows(AG)}
    arms = {a: rows(AG / f"agent-{a}-eval.jsonl") for a in ARMS}
    missing = [a for a, d in arms.items() if not d]
    if missing:
        print(f"no results yet for: {', '.join(missing)}", file=sys.stderr)
        return 1
    sample = set(json.loads((RES / "baseline-sample.json")
                            .read_text(encoding="utf-8"))["ids"])

    # The instances EVERY system completed. Scoring each arm on its own
    # completions would let a system look better by failing on the hard
    # ones, which is the opposite of what a comparison is for.
    ids = sorted(sample & set(ours) & set.intersection(
        *(set(d) for d in arms.values())))
    if not ids:
        print("no common instances", file=sys.stderr)
        return 1
    hard = [i for i in ids if ours[i].get("hard")]

    def acc(d, keys, k):
        return st.fmean(d[i]["metrics"][f"acc@{k}"] for i in keys)

    def paired(d, keys, k):
        """ours minus theirs on `keys`, with a paired bootstrap interval.

        Resampling is over the INDICES of `keys`, not of `ids`, so the
        stratum and its interval come from the same rows. An earlier
        version resampled over `ids` and indexed back through a position
        map, which is two chances to be subtly wrong about which instance
        a difference belongs to.
        """
        diff = [ours[i]["metrics"][f"acc@{k}"] - d[i]["metrics"][f"acc@{k}"]
                for i in keys]
        if not diff:
            return None
        rs = random.Random(SEED + k)
        n = len(diff)
        samples = sorted(
            st.fmean([diff[rs.randrange(n)] for _ in range(n)])
            for _ in range(N_BOOT))
        lo, hi = samples[int(.025 * N_BOOT)], samples[int(.975 * N_BOOT)]
        return {"delta": round(st.fmean(diff), 4), "lo": round(lo, 4),
                "hi": round(hi, 4), "n": n, "significant": lo > 0 or hi < 0}

    out = {"n_common": len(ids), "n_hard": len(hard), "n_sample": len(sample),
           "seed": SEED, "n_bootstrap": N_BOOT,
           "completed": {a: len(d) for a, d in arms.items()},
           "systems": {}, "vs_ours": {}}

    for name, d in [("remember_v3", ours)] + [(a, arms[a]) for a in ARMS]:
        cost = [d[i]["cost"] for i in ids]
        ent = {"acc@1": round(acc(d, ids, 1), 4),
               "acc@5": round(acc(d, ids, 5), 4),
               "hard_acc@1": round(acc(d, hard, 1), 4) if hard else None,
               "hard_acc@5": round(acc(d, hard, 5), 4) if hard else None,
               "llm_calls": round(st.fmean(c["llm_calls"] for c in cost), 2),
               "wall_s": round(st.fmean(c["wall_s"] for c in cost), 1),
               "prompt_tokens": round(st.fmean(c["prompt_tokens"]
                                               for c in cost))}
        if name != "remember_v3":
            ent["empty"] = sum(1 for i in ids if d[i].get("empty"))
            ent["empty_rate"] = round(ent["empty"] / len(ids), 4)
            tools = Counter(t for i in ids for t in d[i].get("tools_used") or [])
            ent["tool_calls_per_run"] = {
                k: round(v / len(ids), 2) for k, v in tools.most_common()}
            ent["stop_reason"] = dict(Counter(d[i]["stop_reason"] for i in ids))
            out["vs_ours"][name] = {
                "all": {f"acc@{k}": paired(d, ids, k) for k in (1, 5)},
                "hard": {f"acc@{k}": paired(d, hard, k) for k in (1, 5)}
                        if hard else None}
        out["systems"][name] = ent

    # The port's own check: CoSIL-style should show the lower empty rate,
    # because reflective alignment exists to fix exactly that failure.
    el, ec = (out["systems"][a]["empty_rate"] for a in ("locagent", "cosil"))
    out["port_check"] = {
        "claim": "CoSIL-style should show the lower empty rate",
        "locagent_empty_rate": el, "cosil_empty_rate": ec,
        "holds": ec < el,
        "n_empty_total": out["systems"]["locagent"]["empty"]
                         + out["systems"]["cosil"]["empty"]}
    # LocAgent's signature tool. Zero calls at n=1,000 is a result.
    out["traverse_graph_calls_per_run"] = out["systems"]["locagent"][
        "tool_calls_per_run"].get("traverse_graph", 0.0)

    (RES / "agentic-baselines.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8")

    print(f"scored on {len(ids)} instances completed by all three "
          f"({len(hard)} hard)\n")
    hdr = f"{'system':22s}{'Acc@1':>8s}{'Acc@5':>8s}{'h@1':>7s}{'h@5':>7s}"
    print(hdr + f"{'calls':>8s}{'wall':>8s}{'empty':>7s}")
    print("-" * len(hdr + "        wall   empty"))
    for name in ("remember_v3", "locagent", "cosil"):
        e = out["systems"][name]
        lbl = "REMEMBER (ours)" if name == "remember_v3" else ARMS[name]
        print(f"{lbl:22s}{e['acc@1']:>8.3f}{e['acc@5']:>8.3f}"
              f"{e['hard_acc@1'] or 0:>7.3f}{e['hard_acc@5'] or 0:>7.3f}"
              f"{e['llm_calls']:>8.1f}{e['wall_s']:>7.0f}s"
              f"{e.get('empty_rate', 0) * 100:>6.1f}%")
    print("\nours minus theirs, paired bootstrap:")
    for a in ARMS:
        for stratum in ("all", "hard"):
            v = out["vs_ours"][a][stratum]
            if not v:
                continue
            for k in (1, 5):
                d = v[f"acc@{k}"]
                print(f"  {ARMS[a]:16s} {stratum:4s} acc@{k}  "
                      f"{d['delta']:+.4f} [{d['lo']:+.4f},{d['hi']:+.4f}]"
                      f"  {'SIG' if d['significant'] else 'ns'}")
    pc = out["port_check"]
    print(f"\nport check -- {pc['claim']}: "
          f"{'HOLDS' if pc['holds'] else 'DOES NOT HOLD'} "
          f"(locagent {pc['locagent_empty_rate']:.1%} vs "
          f"cosil {pc['cosil_empty_rate']:.1%}, "
          f"{pc['n_empty_total']} empty answers in total)")
    if pc["n_empty_total"] < 10:
        print("  too few empty answers for this to have power; inconclusive.")
    print(f"\ntraverse_graph calls per LocAgent-style run: "
          f"{out['traverse_graph_calls_per_run']}")
    print(f"\nwrote {RES / 'agentic-baselines.json'}")
    return 0


def selfcheck() -> int:
    """Synthetic data with a KNOWN answer, because a bootstrap that is
    subtly wrong still returns confident-looking intervals."""
    ok = n = 0

    def chk(name, cond, detail=""):
        nonlocal ok, n
        n += 1
        ok += bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))

    rs = random.Random(1)

    def boot_ci(diff):
        m = len(diff)
        samples = sorted(st.fmean([diff[rs.randrange(m)] for _ in range(m)])
                         for _ in range(N_BOOT))
        return (st.fmean(diff), samples[int(.025 * N_BOOT)],
                samples[int(.975 * N_BOOT)])

    # A constant +0.2 difference must be significant and centred on 0.2.
    d, lo, hi = boot_ci([0.2] * 200)
    chk("a constant difference is significant and centred",
        abs(d - 0.2) < 1e-9 and lo > 0, f"{d:.3f} [{lo:.3f},{hi:.3f}]")
    # A symmetric difference around zero must NOT be significant.
    d, lo, hi = boot_ci([1.0, -1.0] * 200)
    chk("a zero-centred difference is not significant",
        lo < 0 < hi, f"{d:.3f} [{lo:.3f},{hi:.3f}]")
    # The interval must narrow as n grows.
    _, l1, h1 = boot_ci([1.0, 0.0] * 25)
    _, l2, h2 = boot_ci([1.0, 0.0] * 500)
    chk("the interval narrows with more instances",
        (h2 - l2) < (h1 - l1), f"{h1 - l1:.3f} -> {h2 - l2:.3f}")
    # Acc@k is 0/1 per instance, so a mean over a stratum must stay in range.
    chk("a one-sided difference cannot straddle zero",
        boot_ci([1.0] * 50)[1] > 0)
    print(f"{ok}/{n} checks passed")
    return 0 if ok == n else 1


if __name__ == "__main__":
    raise SystemExit(selfcheck() if "--selfcheck" in sys.argv
                     else main())
