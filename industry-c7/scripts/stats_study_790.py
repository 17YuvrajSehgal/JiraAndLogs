"""Paired bootstrap for the comparative study and the agent, on the 790.

Section 6 quotes confidence intervals and significance for every row of
Table I. Those tests did not exist as an artifact: only the point
estimates in final-table-790.json did. This script rebuilds the whole
table from per-instance records, checks it against that file, and then
runs the paired bootstrap the protocol section promises.

Every system is scored on exactly the 790 instances the agent ran.

Usage:
    python industry-c7/scripts/stats_study_790.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "industry-c7"
RES = ROOT / "data/results"
AG = ROOT / "data/agent"
LLM = ROOT / "data/llm"
P = ("kafka", "mariadb", "mongodb", "qt")

N_BOOT = 2000
SEED = 20260601
RRF_K = 60


def jsonl(path):
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if line:
            yield json.loads(line)


def metrics_for(ranking, gold):
    """Acc@K / MRR for one ranked list against one gold set."""
    gold = set(gold)
    out = {}
    for k in (1, 5, 10):
        out[f"acc@{k}"] = float(any(f in gold for f in ranking[:k]))
    rr = 0.0
    for i, f in enumerate(ranking, 1):
        if f in gold:
            rr = 1.0 / i
            break
    out["mrr"] = rr
    return out


def rrf(lists):
    """Reciprocal rank fusion, k=60, as used for the fusion row."""
    score = {}
    for lst in lists:
        for r, f in enumerate(lst, 1):
            score[f] = score.get(f, 0.0) + 1.0 / (RRF_K + r)
    return [f for f, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))]


def main() -> int:
    # ---- the population: exactly what the agent ran -----------------------
    agent = {r["id"]: r for r in jsonl(AG / "agent-v2.jsonl")
             if not r.get("error")}
    ids = sorted(agent)
    hard = {i for i in ids if agent[i]["hard"]}
    assert len(ids) == 790 and len(hard) == 375, (len(ids), len(hard))

    # ---- per-instance records for every other system ----------------------
    retr_rank, gold = {}, {}
    for p in P:
        for r in jsonl(RES / f"{p}-instances.jsonl"):
            i = f"{p}:{r['issue_key']}"
            if i in agent:
                retr_rank[i] = r["rankings"]["cond_ours"]
                gold[i] = r["gold_files"]

    irbl = {}
    for p in P:
        for r in jsonl(RES / f"{p}-irbl-instances.jsonl"):
            i = f"{p}:{r['issue_key']}"
            if i in agent:
                irbl[i] = r["metrics"]

    llm_rank, llm_m, rr_m = {}, {}, {}
    for r in jsonl(LLM / "scored-a2.jsonl"):
        if r["id"] in agent:
            llm_rank[r["id"]] = r["ranking"]
            llm_m[r["id"]] = r["metrics"]
    for r in jsonl(LLM / "scored-rr.jsonl"):
        if r["id"] in agent:
            rr_m[r["id"]] = r["metrics"]

    missing = [n for n, d in (("retrieval", retr_rank), ("irbl", irbl),
                              ("llm", llm_m), ("llm_rerank", rr_m))
               if set(d) != set(ids)]
    if missing:
        print(f"FATAL: incomplete per-instance coverage for {missing}")
        return 2

    # ---- assemble the eight systems, per instance -------------------------
    sysm: dict[str, dict[str, dict]] = {
        "rVSM": {i: irbl[i]["rvsm"] for i in ids},
        "BugLocator": {i: irbl[i]["buglocator_fw_a3"] for i in ids},
        "BRTracer-style": {i: irbl[i]["brtracer_fw"] for i in ids},
        # recomputed from the full retrieval ranking, not from the agent's
        # truncated seed list (the seed stops at 10 files and so clips MRR)
        "ours": {i: metrics_for(retr_rank[i], gold[i]) for i in ids},
        "llm_rerank": {i: rr_m[i] for i in ids},
        "llm": {i: llm_m[i] for i in ids},
        "fusion": {i: metrics_for(rrf([retr_rank[i], llm_rank[i]]), gold[i])
                   for i in ids},
        "agent": {i: agent[i]["metrics"] for i in ids},
    }

    def agg(name, metric, pop=None):
        pool = ids if pop is None else [i for i in ids if i in pop]
        return sum(sysm[name][i][metric] for i in pool) / len(pool)

    # ---- check the rebuild against the published table --------------------
    pub = json.loads((RES / "final-table-790.json").read_text(encoding="utf-8"))
    bad = []
    for name, want in pub["systems"].items():
        got = {"acc@1": agg(name, "acc@1"), "acc@5": agg(name, "acc@5"),
               "mrr": agg(name, "mrr"), "hard@5": agg(name, "acc@5", hard),
               "hard@1": agg(name, "acc@1", hard)}
        for k, v in got.items():
            if k in want and round(v, 3) != round(want[k], 3):
                bad.append(f"{name}.{k}: rebuilt {v:.4f} vs published {want[k]:.4f}")
    if bad:
        print("FATAL: rebuild does not reproduce final-table-790.json")
        for b in bad:
            print("   " + b)
        return 2
    print(f"rebuild reproduces final-table-790.json on all "
          f"{len(pub['systems'])} systems")

    # ---- is the test-only-gold exclusion self-serving? --------------------
    # Section IV-B claims it is not. Record the evidence in the artifact
    # rather than asserting it: score the retrieval layer on the ten removed
    # instances and on the 790 kept.
    # The 790 sample dropped 10 such instances before the run; the benchmark
    # now drops all 123 (scripts/scored_set.py), and their rows live in
    # data/results/removed-test-only-gold/. Score every one of them, which is
    # a stronger version of the same evidence than the original ten.
    exc_path = AG / "excluded-test-only-gold.json"
    exc = json.loads(exc_path.read_text(encoding="utf-8"))
    exc_keys = {(r["project"], r["issue_key"]) for r in exc["rows"]}
    removed_dir = RES / "removed-test-only-gold"
    exc_m, exc_all_m = [], []
    for p in P:
        for src in (RES / f"{p}-instances.jsonl",
                    removed_dir / f"{p}-instances.jsonl"):
            if not src.exists():
                continue
            for r in jsonl(src):
                if src.parent == removed_dir:
                    exc_all_m.append(metrics_for(r["rankings"]["cond_ours"],
                                                 r["gold_files"]))
                if (p, r["issue_key"]) in exc_keys:
                    exc_m.append(metrics_for(r["rankings"]["cond_ours"],
                                             r["gold_files"]))
    exc["n_excluded_benchmark_wide"] = len(exc_all_m)
    exc["retr_acc5_excluded_all"] = (
        sum(m["acc@5"] for m in exc_all_m) / len(exc_all_m)) if exc_all_m else None
    assert len(exc_m) == exc["n"], (len(exc_m), exc["n"])
    exc["retr_acc5_excluded"] = sum(m["acc@5"] for m in exc_m) / len(exc_m)
    exc["retr_acc5_kept"] = agg("ours", "acc@5")
    exc_path.write_text(json.dumps(exc, indent=1), encoding="utf-8")
    print(f"excluded {exc['n']}: retrieval Acc@5 "
          f"{exc['retr_acc5_excluded']:.3f} vs {exc['retr_acc5_kept']:.3f} "
          f"on the kept 790 (exclusion is conservative)")
    if exc_all_m:
        print(f"benchmark-wide {len(exc_all_m)} excluded: retrieval Acc@5 "
              f"{exc['retr_acc5_excluded_all']:.3f}")

    # ---- paired bootstrap, shared resample indices ------------------------
    rng = random.Random(SEED)
    idx_overall = [[rng.randrange(790) for _ in range(790)]
                   for _ in range(N_BOOT)]
    hard_ids = [i for i in ids if i in hard]
    rng_h = random.Random(SEED + 1)
    nh = len(hard_ids)
    idx_hard = [[rng_h.randrange(nh) for _ in range(nh)] for _ in range(N_BOOT)]

    def test(a, b, metric, pop):
        pool, idxs = ((ids, idx_overall) if pop == "overall"
                      else (hard_ids, idx_hard))
        da = [sysm[a][i][metric] - sysm[b][i][metric] for i in pool]
        obs = sum(da) / len(da)
        boot = sorted(sum(da[j] for j in ix) / len(ix) for ix in idxs)
        lo, hi = boot[int(.025 * N_BOOT)], boot[int(.975 * N_BOOT) - 1]
        # two-sided p from the bootstrap distribution, centred on the null
        c = sum(1 for v in boot if (v - obs) * (1 if obs >= 0 else -1) <= -abs(obs))
        p = min(1.0, 2.0 * c / N_BOOT)
        return {"comparison": f"agent_vs_{b}", "metric": metric,
                "population": pop, "n": len(pool), "delta": obs,
                "ci_low": lo, "ci_high": hi, "p": p}

    tests = []
    for b in ("rVSM", "BugLocator", "BRTracer-style", "ours",
              "llm_rerank", "llm", "fusion"):
        for metric in ("acc@1", "acc@5", "mrr"):
            for pop in ("overall", "hard"):
                tests.append(test("agent", b, metric, pop))

    # ---- Benjamini-Hochberg within this family ----------------------------
    m = len(tests)
    order = sorted(range(m), key=lambda j: tests[j]["p"])
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        j = order[rank]
        prev = min(prev, tests[j]["p"] * m / (rank + 1))
        tests[j]["q_bh"] = prev
        tests[j]["significant"] = prev < 0.05

    out = {"n": 790, "n_hard": 375, "n_bootstrap": N_BOOT, "seed": SEED,
           "n_tests": m, "family": "agent vs every system in Table I",
           "tests": tests}
    (RES / "stats-study-790.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")

    nsig = sum(1 for t in tests if t["significant"])
    print(f"\n{m} tests, {nsig} significant at BH q<0.05\n")
    for t in tests:
        flag = "SIG" if t["significant"] else "ns "
        print(f"  {t['comparison']:24s} {t['metric']:6s} {t['population']:8s} "
              f"{t['delta']:+.3f} [{t['ci_low']:+.3f},{t['ci_high']:+.3f}] "
              f"q={t['q_bh']:.4f} {flag}")
    print(f"\nwrote {RES / 'stats-study-790.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
