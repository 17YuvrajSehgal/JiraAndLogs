"""Score the agent against every baseline on the SAME population.

The agent runs on the seeded 200/project sample minus test-only-gold
instances. That population is easier than the full evaluation split, so
every baseline is RESCORED on exactly these instances rather than being
quoted from its own run. Comparing the agent's number against baselines
measured on a different population would flatter the agent by several
points.

Comparisons (paired bootstrap, 2,000 resamples, shared indices per
population, Benjamini-Hochberg over the whole family):

  agent_vs_fusion   agent - RRF(ours + LLM standalone)   <- the real bar
  agent_vs_llm      agent - LLM standalone
  agent_vs_ours     agent - REMEMBER (lexical)
  agentonly_vs_fused  agent list alone - after the safety net
                      (if the safety net is doing the work, this is
                      negative and we say so)

Also reports cost per instance, because the industrial claim is about
what accuracy costs.

Usage:
    python industry-c7/scripts/stats_agent.py
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "industry-c7/scripts"))
from localize import OUT, RRF_K, evaluate  # noqa: E402

LLM = ROOT / "industry-c7/data/llm"
AGENT = ROOT / "industry-c7/data/agent"
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark.
P = tuple(sorted(_ALL_PROJECTS))
METRICS = ("acc@1", "acc@5", "acc@10", "mrr")
B, SEED = 2000, 42


def rrf(lists, k=RRF_K):
    s: dict[str, float] = defaultdict(float)
    for lst, w in lists:
        for i, f in enumerate(lst):
            s[f] += w / (k + i + 1)
    return [f for f, _ in sorted(s.items(), key=lambda x: (-x[1], x[0]))]


def paired_boot(da, db, idx):
    n = len(da)
    obs = sum(da) / n - sum(db) / n
    ds = sorted(sum(da[i] - db[i] for i in s) / n for s in idx)
    p = 2 * min(sum(1 for x in ds if x <= 0),
                sum(1 for x in ds if x >= 0)) / len(ds)
    return {"delta": round(obs, 4), "ci_low": round(ds[int(.025 * B)], 4),
            "ci_high": round(ds[int(.975 * B)], 4), "p": min(1.0, p), "n": n}


def main() -> int:
    agent_rows = {}
    for line in (AGENT / "agent-main.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if not d.get("error"):
            agent_rows[d["id"]] = d
    if not agent_rows:
        print("no agent rows yet")
        return 1

    # LLM standalone rankings, scored on these instances
    llm = {}
    sp = LLM / "scored-a2.jsonl"
    if sp.exists():
        for line in sp.open(encoding="utf-8"):
            d = json.loads(line)
            if not d.get("variant"):
                llm[d["id"]] = d["ranking"]

    ours = {}
    for p in P:
        for line in (OUT / f"{p}-instances.jsonl").open(encoding="utf-8"):
            r = json.loads(line)
            ours[f"{p}:{r['issue_key']}"] = r["rankings"]["cond_ours"]

    systems: dict[str, dict] = {k: {} for k in
                                ("ours", "llm", "fusion", "agent", "agent_only")}
    gold = {}
    for rid, row in agent_rows.items():
        if rid not in ours:
            continue
        gold[rid] = row["gold_files"]
        systems["ours"][rid] = ours[rid]
        systems["agent"][rid] = row["ranking"]
        systems["agent_only"][rid] = row["agent_ranking"]
        if rid in llm:
            systems["llm"][rid] = llm[rid]
            systems["fusion"][rid] = rrf([(ours[rid], 1.0), (llm[rid], 1.0)])

    common = [r for r in gold if all(r in systems[s] for s in systems)]
    print(f"agent rows={len(agent_rows)}  scored on common population "
          f"n={len(common)}  (missing LLM rankings for "
          f"{len(gold) - len(common)})\n")

    summary = {"n": len(common), "by_system": {}, "by_project": {}}
    print(f"{'system':<12}" + "".join(f"{m:>9}" for m in METRICS))
    for name in ("ours", "llm", "fusion", "agent_only", "agent"):
        ms = [evaluate(systems[name][r], gold[r]) for r in common]
        agg = {m: round(sum(x[m] for x in ms) / len(ms), 4) for m in METRICS}
        summary["by_system"][name] = agg
        print(f"{name:<12}" + "".join(f"{agg[m]:>9.3f}" for m in METRICS))

    for p in P:
        sub = [r for r in common if r.startswith(p + ":")]
        if not sub:
            continue
        summary["by_project"][p] = {
            "n": len(sub),
            **{name: round(sum(evaluate(systems[name][r], gold[r])["acc@5"]
                               for r in sub) / len(sub), 4)
               for name in ("ours", "llm", "fusion", "agent")}}

    # hard stratum
    hard = [r for r in common if agent_rows[r].get("hard")]
    if hard:
        summary["hard"] = {
            "n": len(hard),
            **{name: round(sum(evaluate(systems[name][r], gold[r])["acc@5"]
                               for r in hard) / len(hard), 4)
               for name in ("ours", "llm", "fusion", "agent")}}

    # ---- significance ------------------------------------------------------
    rng = random.Random(SEED)
    pairs = [("agent_vs_fusion", "agent", "fusion"),
             ("agent_vs_llm", "agent", "llm"),
             ("agent_vs_ours", "agent", "ours"),
             ("agentonly_vs_fused", "agent_only", "agent")]
    tests = []
    pops = {"overall": common, "hard": hard}
    for pop_name, pop in pops.items():
        if len(pop) < 30:
            continue
        n = len(pop)
        idx = [[rng.randrange(n) for _ in range(n)] for _ in range(B)]
        for cname, a, b in pairs:
            for metric in ("acc@1", "acc@5", "mrr"):
                da = [evaluate(systems[a][r], gold[r])[metric] for r in pop]
                db = [evaluate(systems[b][r], gold[r])[metric] for r in pop]
                tests.append({"population": pop_name, "comparison": cname,
                              "metric": metric, **paired_boot(da, db, idx)})
    m = len(tests)
    order = sorted(range(m), key=lambda j: tests[j]["p"])
    prev = 1.0
    for rank, j in enumerate(reversed(order), start=1):
        prev = min(prev, tests[j]["p"] * m / (m - rank + 1))
        tests[j]["q_bh"] = round(prev, 4)
        tests[j]["significant"] = prev < 0.05

    print()
    for t in tests:
        if t["metric"] in ("acc@1", "acc@5"):
            print(f"{t['population']:<9}{t['metric']:<7}{t['comparison']:<22}"
                  f"{t['delta']:+.3f} [{t['ci_low']:+.3f},{t['ci_high']:+.3f}]"
                  f" n={t['n']:<5} q={t['q_bh']:.4f} "
                  f"{'SIG' if t['significant'] else 'ns'}")

    # ---- cost --------------------------------------------------------------
    rows = [agent_rows[r] for r in common]
    cost = {
        "llm_calls_mean": round(sum(r["cost"]["llm_calls"] for r in rows) / len(rows), 1),
        "prompt_tokens_mean": int(sum(r["cost"]["prompt_tokens"] for r in rows) / len(rows)),
        "completion_tokens_mean": int(sum(r["cost"]["completion_tokens"] for r in rows) / len(rows)),
        "wall_s_mean": round(sum(r["cost"]["wall_s"] for r in rows) / len(rows), 1),
        "tool_calls_mean": round(sum(r["n_tool_calls"] for r in rows) / len(rows), 1),
        "notes_mean": round(sum(r["n_notes"] for r in rows) / len(rows), 1),
        "pct_zero_notes": round(sum(1 for r in rows if r["n_notes"] == 0) / len(rows), 3),
    }
    summary["cost_per_instance"] = cost
    summary["tests"] = tests
    print("\ncost per instance:", json.dumps(cost))
    (OUT / "agent-summary.json").write_text(json.dumps(summary, indent=2),
                                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
