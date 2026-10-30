"""Trace every number the paper states to the result file it came from.

One check per claim: the paper says X (hard-coded here, matching the tex),
the result file says Y; the check fails loudly if they disagree. Run green
before every submission. Sections refer to industry-c7/paper/sections/.

Usage:
    python industry-c7/scripts/verify_claims.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "industry-c7/data/results"
BENCH = ROOT / "industry-c7/data/benchmark"
P = ("kafka", "mariadb", "mongodb", "qt")

checks: list[tuple[str, bool, str]] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    checks.append((claim, ok, detail))


def r3(x: float) -> float:
    return round(x, 3)


def main() -> int:
    ds = json.loads((BENCH / "datasheet.json").read_text(encoding="utf-8"))
    mp = json.loads((BENCH / "memory-pools-datasheet.json").read_text(encoding="utf-8"))
    summ = {p: json.loads((RES / f"{p}-summary.json").read_text(encoding="utf-8"))
            for p in P}
    stats = json.loads((RES / "stats.json").read_text(encoding="utf-8"))
    mods = json.loads((RES / "module-metrics.json").read_text(encoding="utf-8"))

    def stat(project, comparison, metric, population):
        for t in stats["tests"]:
            if (t["project"], t["comparison"], t["metric"],
                    t["population"]) == (project, comparison, metric, population):
                return t
        raise KeyError((project, comparison, metric, population))

    # ---- Sec. 1 + 2, Table 1 (datasheet) -------------------------------------
    expected_funnel = {  # eligible, linked, final
        "kafka": (1172, 827, 680), "mariadb": (3004, 2010, 1683),
        "mongodb": (6407, 5093, 3618), "qt": (7412, 713, 456)}
    expected_pct = {  # hard%, trace%, single-commit%, gold median
        "kafka": (28, 47, 91, 1), "mariadb": (44, 57, 83, 1),
        "mongodb": (60, 10, 80, 2), "qt": (68, 24, 96, 1)}
    expected_pool = {"kafka": 4033, "mariadb": 6014, "mongodb": 19820, "qt": 2315}
    total = hard_total = 0
    for p in P:
        f, s = ds[p]["funnel"], ds[p]["strata"]
        el, li, fi = expected_funnel[p]
        check(f"T1 {p} funnel {el}/{li}/{fi}",
              (f["wolv2_log_fixed_lowuncert_issues"], f["linked_1_to_3_commits"],
               f["final_instances"]) == (el, li, fi),
              str(f))
        hp, tp, sc, gm = expected_pct[p]
        check(f"T1 {p} hard {hp}%",
              round(100 * s["hard_gold_not_named"] / f["final_instances"]) == hp)
        check(f"T1 {p} trace {tp}%",
              round(100 * s["trace_present"] / f["final_instances"]) == tp)
        check(f"T1 {p} single-commit {sc}%",
              round(100 * s["single_commit"] / f["final_instances"]) == sc)
        check(f"T1 {p} gold median {gm}", ds[p]["gold_files_median"] == gm)
        check(f"T1 {p} memory pool {expected_pool[p]}",
              mp[p]["memory_with_gold"] == expected_pool[p])
        ratio = mp[p]["memory_with_gold"] / f["final_instances"]
        check(f"S2 {p} pool 3-6x benchmark", 3.0 <= ratio <= 6.0, f"{ratio:.2f}x")
        total += f["final_instances"]
        hard_total += s["hard_gold_not_named"]
    check("S1/S2 total 6,437 instances", total == 6437, str(total))
    check("S1/S2 53% hard", round(100 * hard_total / total) == 53,
          f"{100 * hard_total / total:.1f}%")

    # ---- Sec. 5, Table 2 (file-level eval) ------------------------------------
    t2 = {  # system -> project -> (acc@5, mrr)
        "trace_grep":      {"kafka": (.658, .477), "mariadb": (.442, .327),
                            "mongodb": (.354, .319), "qt": (.263, .226)},
        "path_bm25":       {"kafka": (.481, .379), "mariadb": (.259, .198),
                            "mongodb": (.370, .268), "qt": (.266, .195)},
        "content_bm25":    {"kafka": (.708, .545), "mariadb": (.471, .330),
                            "mongodb": (.644, .473), "qt": (.456, .350)},
        "memory_bm25":     {"kafka": (.483, .361), "mariadb": (.461, .342),
                            "mongodb": (.377, .296), "qt": (.278, .211)},
        "fused_no_memory": {"kafka": (.767, .611), "mariadb": (.443, .342),
                            "mongodb": (.530, .420), "qt": (.353, .292)},
        "fused_ours":      {"kafka": (.790, .600), "mariadb": (.562, .408),
                            "mongodb": (.629, .499), "qt": (.463, .351)},
        "cond_no_memory":  {"kafka": (.792, .625), "mariadb": (.642, .479),
                            "mongodb": (.693, .566), "qt": (.456, .350)},
        "cond_ours":       {"kafka": (.794, .625), "mariadb": (.658, .479),
                            "mongodb": (.700, .552), "qt": (.541, .408)},
    }
    for sysname, per in t2.items():
        for p, (a5, mrr) in per.items():
            got = summ[p]["eval"][sysname]
            check(f"T2 {p} {sysname} {a5}/{mrr}",
                  r3(got["acc@5"]) == a5 and r3(got["mrr"]) == mrr,
                  f"got {r3(got['acc@5'])}/{r3(got['mrr'])}")

    check("S5 eval sizes 476/1179/2533/320",
          tuple(summ[p]["n_eval"] for p in P) == (476, 1179, 2533, 320))
    n_hard = sum(stat(p, "ours_vs_strongest", "acc@5", "hard")["n"] for p in P)
    check("S5 2,318 hard eval instances", n_hard == 2318, str(n_hard))

    # ---- Sec. 1/5 RQ1 deltas, CIs, significance -------------------------------
    rq1 = {"kafka": (+0.086, +0.055, +0.118), "mariadb": (+0.187, +0.160, +0.215),
           "mongodb": (+0.057, +0.046, +0.067), "qt": (+0.084, +0.053, +0.119)}
    for p, (d, lo, hi) in rq1.items():
        t = stat(p, "ours_vs_strongest", "acc@5", "overall")
        check(f"RQ1 {p} acc@5 {d:+.3f} [{lo:+.3f},{hi:+.3f}] SIG",
              r3(t["delta"]) == d and r3(t["ci_low"]) == lo
              and r3(t["ci_high"]) == hi and t["significant"],
              f"got {t['delta']:+.3f} [{t['ci_low']:+.3f},{t['ci_high']:+.3f}]")
        tm = stat(p, "ours_vs_strongest", "mrr", "overall")
        check(f"RQ1 {p} mrr SIG", tm["significant"])
    mrr_d = [stat(p, "ours_vs_strongest", "mrr", "overall")["delta"] for p in P]
    check("RQ1 mrr +0.058..+0.148", r3(min(mrr_d)) == .058 and r3(max(mrr_d)) == .148,
          f"{min(mrr_d):.3f}..{max(mrr_d):.3f}")
    grep_d = [stat(p, "ours_vs_tracegrep", "acc@5", "overall")["delta"] for p in P]
    check("S5 grep margins +0.137..+0.347",
          r3(min(grep_d)) == .137 and r3(max(grep_d)) == .347)
    hard_ours = [summ[p]["eval_hard"]["cond_ours"]["acc@5"] for p in P]
    check("S5 hard ours 0.361..0.544",
          r3(min(hard_ours)) == .361 and r3(max(hard_ours)) == .544)
    check("S5 S1 zero on hard",
          all(summ[p]["eval_hard"]["trace_grep"]["acc@5"] == 0.0 for p in P))

    # ---- Sec. 5 RQ2 -----------------------------------------------------------
    check("RQ2 mariadb-hard memory .442 beats content .406",
          r3(summ["mariadb"]["eval_hard"]["memory_bm25"]["acc@5"]) == .442
          and r3(summ["mariadb"]["eval_hard"]["content_bm25"]["acc@5"]) == .406)
    for p, d in (("mariadb", .209), ("mongodb", .165), ("qt", .153)):
        t = stat(p, "memory_unweighted", "acc@5", "hard")
        check(f"RQ2 {p} hard unweighted +{d} SIG",
              r3(t["delta"]) == d and t["significant"], f"got {t['delta']:+.3f}")
    tk = stat("kafka", "memory_unweighted", "acc@5", "hard")
    check("RQ2 kafka hard +0.081 q=0.068 ns n=124",
          r3(tk["delta"]) == .081 and round(tk["q_bh"], 3) == .068
          and not tk["significant"] and tk["n"] == 124,
          f"got {tk['delta']:+.3f} q={tk['q_bh']:.3f} n={tk['n']}")
    for p, d in (("mariadb", .016), ("mongodb", .008), ("qt", .084)):
        t = stat(p, "memory_cond", "acc@5", "overall")
        check(f"RQ2 {p} cond increment +{d} SIG",
              r3(t["delta"]) == d and t["significant"], f"got {t['delta']:+.3f}")
    check("RQ2 qt cond_no_memory .456 = content .456; ours .541",
          r3(summ["qt"]["eval"]["cond_no_memory"]["acc@5"]) == .456
          and r3(summ["qt"]["eval"]["content_bm25"]["acc@5"]) == .456
          and r3(summ["qt"]["eval"]["cond_ours"]["acc@5"]) == .541)

    # ---- Sec. 3/5 RQ3: firewall share + Q1 minima -----------------------------
    for p in P:
        vs = summ[p]["memory_vote_stats"]
        share = vs["bm25_fw_resolved_later"] / (vs["bm25_fw_resolved_later"]
                                                + vs["bm25_voted"])
        check(f"S3/RQ3 {p} firewall blocks 67-71%", .67 <= round(share, 2) <= .71,
              f"{share:.0%}")
    q1_min = 0
    for p in P:
        rows = [json.loads(l) for l in
                (RES / f"{p}-instances.jsonl").open(encoding="utf-8")]
        rows.sort(key=lambda r: r["fix_time"])
        ev = rows[summ[p]["n_dev"]:]
        qs = []
        for i in range(4):
            sub = ev[i * len(ev) // 4:(i + 1) * len(ev) // 4]
            qs.append(sum(r["metrics"]["memory_bm25"]["acc@5"] for r in sub) / len(sub))
        q1_min += int(qs[0] == min(qs))
    check("RQ3 memory weakest in Q1 for 3 of 4 projects", q1_min == 3, str(q1_min))

    # ---- Sec. 5 Table 3 + module claims ---------------------------------------
    t3 = {"kafka": (.830, .861, .998), "mariadb": (.771, .843, .983),
          "mongodb": (.808, .841, .979), "qt": (.613, .669, .925)}
    for p, (c1, o1, o5) in t3.items():
        m = mods[p]["systems"]
        check(f"T3 {p} content@1={c1} ours@1={o1} ours@5={o5}",
              r3(m["content_bm25"]["acc@1"]) == c1
              and r3(m["cond_ours"]["acc@1"]) == o1
              and r3(m["cond_ours"]["acc@5"]) == o5)
    check("S1 module top-5 at least 92% everywhere",
          min(mods[p]["systems"]["cond_ours"]["acc@5"] for p in P) >= 0.92)

    # ---- Sec. 5 honest negatives ---------------------------------------------
    tn = stat("kafka", "ours_vs_strongest", "acc@5", "hard")
    check("NEG kafka hard -0.065 [-0.113,-0.024] SIG",
          r3(tn["delta"]) == -.065 and r3(tn["ci_low"]) == -.113
          and r3(tn["ci_high"]) == -.024 and tn["significant"])
    for p in ("mariadb", "mongodb", "qt"):
        check(f"NEG {p} hard ours-vs-content tie (ns)",
              not stat(p, "ours_vs_strongest", "acc@5", "hard")["significant"])
    check("NEG qt easy .654/.904/.913",
          r3(summ["qt"]["eval_easy"]["cond_no_memory"]["acc@5"]) == .654
          and r3(summ["qt"]["eval_easy"]["fused_no_memory"]["acc@5"]) == .904
          and r3(summ["qt"]["eval_easy"]["cond_ours"]["acc@5"]) == .913)

    # ---- Sec. 4/6 protocol + misc --------------------------------------------
    check("S4 64-test BH family", stats["n_tests"] == 64)
    check("S4 bootstrap 2,000 resamples", stats["n_bootstrap"] == 2000)
    check("S6 90% of MongoDB reports traceless",
          round(100 * (1 - ds["mongodb"]["strata"]["trace_present"]
                       / ds["mongodb"]["funnel"]["final_instances"])) == 90)
    # provenance coverage (Sec. 3/6 explanation output)
    for p in P:
        rows = [json.loads(l) for l in
                (RES / f"{p}-instances.jsonl").open(encoding="utf-8")]
        with_prov = sum(1 for r in rows if r.get("provenance"))
        check(f"PROV {p} provenance on every non-empty ranking",
              all(bool(r.get("provenance")) == bool(r["rankings"]["cond_ours"])
                  for r in rows),
              f"{with_prov}/{len(rows)} rows carry provenance")

    # ---- report ---------------------------------------------------------------
    failed = [(c, d) for c, ok, d in checks if not ok]
    for c, ok, d in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {c}" + (f"  [{d}]" if d and not ok else ""))
    print(f"\n{len(checks) - len(failed)}/{len(checks)} claims verified")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
