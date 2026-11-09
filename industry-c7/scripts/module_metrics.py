"""Module-level Acc@K / MRR (challenge output (i): "the affected module").

Module = first D path components of a file (D per project -- a single
top-level dir is meaningless where everything lives under src/):
  kafka 1 (clients, core, streams...), mariadb 2 (sql, storage/innobase...),
  mongodb 3 (src/mongo/db, src/mongo/s...), qt 2 (src/corelib, src/network...).

A system's module ranking is its file ranking collapsed by first occurrence.
Gold modules are recomputed from gold_files with the same rule. Eval split
replicated from each summary's n_dev (as in stats.py). Uses the stored
top-20 file rankings -- ample for Acc@{1,3,5}.

Usage:
    python scripts/c7/module_metrics.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "industry-c7/data/results"
# Module depth is a JUDGEMENT PER REPOSITORY, not a derivable number: it is
# how many leading path components name a unit an on-call engineer would
# recognise. It cannot be auto-filled, and the dataset's own gold_modules
# field is no help -- mine_benchmark uses f.split("/")[0], depth 1 for
# everything, which is exactly the "meaningless where everything lives under
# src/" case this docstring warns about.
#
# Only these four are decided. The benchmark has 27. Rather than report
# module metrics over whichever subset happens to be filled in, the guard
# below refuses, because a four-project module table printed next to a
# 27-project file table is the kind of thing that reaches a paper.
DEPTH = {
    "ambari": 1,       # 11 mods, major 0.81, rand 0.091, agree 0.81
    "beam": 2,         # 30 mods, major 0.36, rand 0.033, agree 0.62
    "camel": 2,        # 422 mods, major 0.29, rand 0.002, agree 0.70
    "cassandra": 6,    # 90 mods, major 0.39, rand 0.011
    "derby": 7,        # 103 mods, major 0.39, rand 0.010, agree 0.70
    "drill": 2,        # 40 mods, major 0.88, rand 0.025, agree 0.90
    "flink": 1,        # 39 mods, major 0.35, rand 0.026, agree 0.74
    "geode": 1,        # 32 mods, major 0.75, rand 0.031, agree 0.97
    "groovy": 6,       # 269 mods, major 0.23, rand 0.004, agree 0.00
    "hadoop": 2,       # 41 mods, major 0.31, rand 0.024, agree 0.39
    "hbase": 1,        # 29 mods, major 0.61, rand 0.035, agree 1.00
    "hive": 1,         # 38 mods, major 0.67, rand 0.026, agree 0.91
    "ignite": 2,       # 48 mods, major 0.85, rand 0.021, agree 0.96
    "impala": 4,       # 53 mods, major 0.40, rand 0.019, agree 0.60
    "infinispan": 1,   # 34 mods, major 0.67, rand 0.029, agree 0.78
    "kafka": 1,        # 15 mods, major 0.49, rand 0.067, agree 1.00
    "keycloak": 1,     # 19 mods, major 0.45, rand 0.053, agree 0.59
    "mariadb": 2,      # 90 mods, major 0.62, rand 0.011, agree 0.98
    "mongodb": 4,      # 140 mods, major 0.18, rand 0.007, agree 0.92
    "pdfbox": 1,       # 7 mods, major 0.76, rand 0.143, agree 1.00
    "phoenix": 1,      # 7 mods, major 0.95, rand 0.143, agree 1.00
    "pig": 5,          # 35 mods, major 0.41, rand 0.029, agree 0.00
    "qt": 2,           # 125 mods, major 0.31, rand 0.008, agree 0.68
    "sakai": 2,        # 283 mods, major 0.12, rand 0.004, agree 0.58
    "solr": 2,         # 8 mods, major 0.75, rand 0.125, agree 0.86
    "spark": 2,        # 32 mods, major 0.31, rand 0.031, agree 0.55
    "wildfly": 1,      # 42 mods, major 0.18, rand 0.024, agree 0.57
}

# Projects where module accuracy cannot carry a claim: one module holds
# most of the faults, so a constant answer already scores this well, at
# EVERY depth 1-7 (module_depth_study.py). Reported, never claimed.
TRIVIAL_MAJORITY = {
    "phoenix": 0.95, "drill": 0.88, "ignite": 0.86, "pdfbox": 0.76,
    "solr": 0.75, "hive": 0.67, "geode": 0.63, "mariadb": 0.62,
    "hbase": 0.61,
}


def require_depths(projects) -> None:
    """Refuse unless every project asked for has a decided depth."""
    missing = sorted(set(projects) - set(DEPTH))
    if missing:
        raise SystemExit(
            f"REFUSING: module depth is undecided for {len(missing)} of "
            f"{len(set(projects))} projects: {', '.join(missing)}. "
            "Module depth is a per-repository judgement (see DEPTH above). "
            "Decide each one by looking at that repo's top-level layout, add "
            "it to DEPTH, then re-run. Module metrics stay unreported until "
            "then rather than covering a silent subset.")


SYSTEMS =("trace_grep", "path_bm25", "content_bm25", "memory_bm25",
           "fused_no_memory", "fused_ours", "cond_no_memory", "cond_ours")
KS = (1, 3, 5)


def module_of(path: str, depth: int) -> str:
    parts = path.split("/")
    return "/".join(parts[:max(1, min(depth, len(parts) - 1))])


def metrics_of(ranked_mods: list, gold_mods: set) -> dict:
    hit = next((i for i, m in enumerate(ranked_mods) if m in gold_mods), None)
    m = {f"acc@{k}": float(any(x in gold_mods for x in ranked_mods[:k]))
         for k in KS}
    m["mrr"] = 1.0 / (hit + 1) if hit is not None else 0.0
    return m


def study_agent() -> dict:
    """Module metrics for EVERY system on the instances the agent ran.

    Challenge output (i) is "the affected module", so this table is a
    required result, not a supplement.

    The population is the agent's own run, read through agent_run_rows so
    C7_AGENT_GLOB picks the seed. It used to be data/agent/agent-v2.jsonl,
    the archived 790-instance v2 arm: the table therefore reported a
    retired system under the name REMEMBER on a population 33x smaller
    than the one the paper reports, and the live arm (remember_v3) was not
    in DOC_ORDER at all, so it never appeared. Both are fixed.

    Every system is scored on the identical id set, the intersection of
    the ids all of them stored a ranking for, because comparing across
    populations is the mistake this project has already made once.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from score_causal_gold import DOC_ORDER, rankings  # noqa: E402
    from localize import agent_run_rows  # noqa: E402

    ag = agent_run_rows(RES.parent / "agent")
    gold = {f"{r['project']}:{r['issue_key']}": r["gold_files"] for r in ag}
    hard = {f"{r['project']}:{r['issue_key']}": bool(r.get("hard")) for r in ag}
    rk = rankings(set(gold))
    names = [n for n, _ in DOC_ORDER if n in rk]
    # The IRBL baselines stored rankings only for the causal-gold subset, so
    # an intersection over every system collapses to a fraction of the run.
    # Report both: the systems that ran everything, and the wider comparison
    # on the smaller set. Never one population silently standing in for the
    # other.
    full = [n for n in names if not set(gold) - set(rk[n])]
    groups = {"full_agent": full, "with_irbl": names}

    out = {"population_size": len(gold),
           "coverage": {n: len(rk[n]) for n in names},
           "systems_missing_from_doc_order":
               sorted(set(rk) - {n for n, _ in DOC_ORDER}),
           "populations": {}}
    for gname, gnames in groups.items():
        ids = sorted(set.intersection(*(set(rk[n]) for n in gnames)))
        res = {"n": len(ids), "n_hard": sum(hard[i] for i in ids),
               "systems": {}}
        for name, label in DOC_ORDER:
            if name not in gnames:
                continue
            acc = {pop: {f"acc@{k}": 0.0 for k in KS} | {"mrr": 0.0}
                   for pop in ("overall", "hard")}
            n_pop = {"overall": 0, "hard": 0}
            for i in ids:
                depth = DEPTH[i.split(":")[0]]
                g = {module_of(f, depth) for f in gold[i]}
                mods = list(dict.fromkeys(
                    module_of(f, depth) for f in rk[name][i]))
                m = metrics_of(mods, g)
                for pop in ("overall", "hard") if hard[i] else ("overall",):
                    n_pop[pop] += 1
                    for key, v in m.items():
                        acc[pop][key] += v
            res["systems"][name] = {
                "label": label,
                **{pop: {k: round(v / max(n_pop[pop], 1), 4)
                         for k, v in acc[pop].items()} for pop in acc}}
        out["populations"][gname] = res
    return out


def main() -> int:
    if "--agent" in sys.argv or "--study790" in sys.argv:
        res = study_agent()
        (RES / "module-metrics-agent.json").write_text(
            json.dumps(res, indent=2), encoding="utf-8")
        print(f"agent population: {res['population_size']} instances")
        if res["systems_missing_from_doc_order"]:
            print("  NOT REPORTED, absent from DOC_ORDER: "
                  + ", ".join(res["systems_missing_from_doc_order"]))
        for gname, g in res["populations"].items():
            print(f"\n=== {gname}: n={g['n']} ({g['n_hard']} hard) ===")
            print(f"{'system':<38}{'acc@1':>8}{'acc@5':>8}{'mrr':>8}"
                  f"{'hard acc@1':>12}")
            for name, d in g["systems"].items():
                print(f"{d['label']:<38}{d['overall']['acc@1']:>8.3f}"
                      f"{d['overall']['acc@5']:>8.3f}"
                      f"{d['overall']['mrr']:>8.3f}"
                      f"{d['hard']['acc@1']:>12.3f}")
        return 0
    # Refuse by default. This writes module-metrics.json, and a file holding
    # four projects is indistinguishable from a benchmark-wide one once it is
    # on disk and something else reads it. --only-decided is the explicit
    # opt-in, and it stamps the coverage into the artifact.
    from localize import PROJECTS as _ALL  # noqa: E402
    only = "--only-decided" in sys.argv
    if not only:
        require_depths(sorted(_ALL))
    out = {"_coverage": {"projects_reported": sorted(DEPTH),
                         "projects_in_benchmark": len(_ALL),
                         "undecided_depth": sorted(set(_ALL) - set(DEPTH)),
                         "benchmark_wide": len(DEPTH) == len(_ALL)}}
    for proj, depth in DEPTH.items():
        rows = [json.loads(l) for l in
                (RES / f"{proj}-instances.jsonl").open(encoding="utf-8")]
        n_dev = json.load((RES / f"{proj}-summary.json").open())["n_dev"]
        rows.sort(key=lambda r: r["fix_time"])
        ev = rows[n_dev:]
        # instances carry file rankings for the five SIGNALS; fused systems
        # were persisted in metrics only, so rebuild them the same way the
        # localizer did is NOT possible from top-20 alone -- instead collapse
        # every stored ranking (signals) and the fused top-20s if present.
        agg = {}
        for sys_name in SYSTEMS:
            ms = {f"acc@{k}": 0.0 for k in KS}
            ms["mrr"] = 0.0
            n = 0
            for r in ev:
                files = r["rankings"].get(sys_name)
                if files is None:
                    n = 0
                    break
                gold = {module_of(f, depth) for f in r["gold_files"]}
                mods = list(dict.fromkeys(module_of(f, depth) for f in files))
                hit = next((i for i, m in enumerate(mods) if m in gold), None)
                ms["mrr"] += 1.0 / (hit + 1) if hit is not None else 0.0
                for k in KS:
                    ms[f"acc@{k}"] += float(any(m in gold for m in mods[:k]))
                n += 1
            if n:
                agg[sys_name] = {m: round(v / n, 4) for m, v in ms.items()}
        out[proj] = {"n_eval": len(ev), "module_depth": depth, "systems": agg}

    if not out["_coverage"]["benchmark_wide"]:
        print(f"\n*** PARTIAL: {len(DEPTH)} of "
              f"{out['_coverage']['projects_in_benchmark']} projects. "
              "Not a benchmark-wide result; module depth is undecided for "
              f"{len(out['_coverage']['undecided_depth'])}. ***")
    (RES / "module-metrics.json").write_text(json.dumps(out, indent=2),
                                             encoding="utf-8")
    for proj, res in out.items():
        if proj.startswith("_"):      # _coverage is metadata, not a project
            continue
        maj = TRIVIAL_MAJORITY.get(proj)
        warn = ("  <-- constant answer already scores %.2f: report, do not "
                "claim" % maj) if maj else ""
        print(f"\n--- {proj} (module depth {res['module_depth']}, "
              f"n={res['n_eval']}){warn} ---")
        print(f"{'system':<17}{'acc@1':>8}{'acc@3':>8}{'acc@5':>8}{'mrr':>8}")
        for s, m in res["systems"].items():
            print(f"{s:<17}{m['acc@1']:>8.3f}{m['acc@3']:>8.3f}"
                  f"{m['acc@5']:>8.3f}{m['mrr']:>8.3f}")
        if maj:
            print(f"{'majority baseline':<17}{maj:>8.3f}{maj:>8.3f}"
                  f"{maj:>8.3f}{'-':>8}")
    if TRIVIAL_MAJORITY:
        print(f"\n{len(TRIVIAL_MAJORITY)} of {len(DEPTH)} projects have a "
              "majority baseline above 0.60 at every depth 1-7, so module "
              "accuracy there measures the repository's shape, not the "
              "system. See scripts/module_depth_study.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
