"""v1 vs v2 of the agent, paired on the instances BOTH versions ran.

v1 and v2 differ by four design changes, all made because v1 measurements
showed the behaviour the design depended on was being skipped:

  1. incident recall pre-run in setup      (v1: 0.4 tool calls/run)
  2. callers folded into search_symbol     (v1: 1 use in 105 runs)
  3. evidence required by the submit schema(v1: 37% of runs recorded none)
  4. safety net backfills instead of blending
     (v1: blending demoted a gold file from rank 2 out of the top five)

This script measures what those four changes bought, on the SAME
instances, with a paired bootstrap. Unpaired comparison would confound
the change with which instances each version happened to reach.

Usage:
    python industry-c7/scripts/ablate_agent_versions.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "industry-c7/scripts"))
from localize import is_dead_row  # noqa: E402
from localize import OUT  # noqa: E402

AGENT = ROOT / "industry-c7/data/agent"
METRICS = ("acc@1", "acc@5", "mrr")
B, SEED = 2000, 42


def load(tag):
    p = AGENT / f"agent-{tag}.jsonl"
    out = {}
    if not p.exists():
        return out
    for line in p.open(encoding="utf-8"):
        d = json.loads(line)
        if not is_dead_row(d):
            out[d["id"]] = d
    return out


def paired_boot(da, db, idx):
    n = len(da)
    obs = sum(da) / n - sum(db) / n
    ds = sorted(sum(da[i] - db[i] for i in s) / n for s in idx)
    p = 2 * min(sum(1 for x in ds if x <= 0),
                sum(1 for x in ds if x >= 0)) / len(ds)
    return {"delta": round(obs, 4), "ci_low": round(ds[int(.025 * B)], 4),
            "ci_high": round(ds[int(.975 * B)], 4), "p": min(1.0, p), "n": n}


def main() -> int:
    v1, v2 = load("v1"), load("v2")
    shared = sorted(set(v1) & set(v2))
    print(f"v1={len(v1)}  v2={len(v2)}  shared={len(shared)}")
    if len(shared) < 30:
        print("not enough shared instances yet")
        return 1

    hard = [r for r in shared if v1[r].get("hard")]
    rows = {"overall": shared, "hard": hard}
    out = {"n_shared": len(shared), "n_hard": len(hard), "tests": [],
           "means": {}, "behaviour": {}}

    for pop, ids in rows.items():
        if len(ids) < 30:
            continue
        for ver, data in (("v1", v1), ("v2", v2)):
            out["means"][f"{ver}:{pop}"] = {
                m: round(sum(data[r]["metrics"][m] for r in ids) / len(ids), 4)
                for m in METRICS}

    print(f"\n{'':<10}" + "".join(f"{m:>9}" for m in METRICS))
    for pop in rows:
        if f"v1:{pop}" not in out["means"]:
            continue
        for ver in ("v1", "v2"):
            mm = out["means"][f"{ver}:{pop}"]
            print(f"{ver + ' ' + pop:<10}" + "".join(f"{mm[m]:>9.3f}"
                                                     for m in METRICS))

    rng = random.Random(SEED)
    for pop, ids in rows.items():
        if len(ids) < 30:
            continue
        n = len(ids)
        idx = [[rng.randrange(n) for _ in range(n)] for _ in range(B)]
        for m in METRICS:
            da = [v2[r]["metrics"][m] for r in ids]
            db = [v1[r]["metrics"][m] for r in ids]
            out["tests"].append({"population": pop, "metric": m,
                                 "comparison": "v2_minus_v1",
                                 **paired_boot(da, db, idx)})
    t = out["tests"]
    m_ = len(t)
    order = sorted(range(m_), key=lambda j: t[j]["p"])
    prev = 1.0
    for rank, j in enumerate(reversed(order), start=1):
        prev = min(prev, t[j]["p"] * m_ / (m_ - rank + 1))
        t[j]["q_bh"] = round(prev, 4)
        t[j]["significant"] = prev < 0.05
    print()
    for x in t:
        print(f"{x['population']:<9}{x['metric']:<7}v2-v1 {x['delta']:+.4f} "
              f"[{x['ci_low']:+.4f},{x['ci_high']:+.4f}] n={x['n']} "
              f"q={x['q_bh']:.4f} {'SIG' if x['significant'] else 'ns'}")

    # did the four behavioural fixes actually change behaviour?
    for ver, data in (("v1", v1), ("v2", v2)):
        sub = [data[r] for r in shared]
        tools = [t_ for r in sub for t_ in r["tools_used"]]
        out["behaviour"][ver] = {
            "zero_evidence_rate": round(
                sum(1 for r in sub if r["n_notes"] == 0) / len(sub), 3),
            "evidence_mean": round(
                sum(r["n_notes"] for r in sub) / len(sub), 2),
            "tool_calls_mean": round(
                sum(r["n_tool_calls"] for r in sub) / len(sub), 1),
            "recall_incidents_per_run": round(
                tools.count("recall_incidents") / len(sub), 2),
            "prompt_tokens_mean": int(
                sum(r["cost"]["prompt_tokens"] for r in sub) / len(sub)),
            "llm_calls_mean": round(
                sum(r["cost"]["llm_calls"] for r in sub) / len(sub), 1)}
    print("\nbehaviour on shared instances:")
    for ver in ("v1", "v2"):
        print(f"  {ver}: {json.dumps(out['behaviour'][ver])}")
    (OUT / "agent-v1-v2-ablation.json").write_text(json.dumps(out, indent=2),
                                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
