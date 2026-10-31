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
    # Per-project strongest baseline: S3 on kafka/mongodb/qt, BRTracer on mariadb.
    stats_irbl = json.loads((RES / "stats-irbl.json").read_text(encoding="utf-8"))

    def istat(project, comparison, metric, population):
        for t in stats_irbl["tests"]:
            if (t["project"], t["comparison"], t["metric"],
                    t["population"]) == (project, comparison, metric, population):
                return t
        raise KeyError((project, comparison, metric, population))

    rq1 = {"kafka": (+0.086, +0.055, +0.118),
           "mongodb": (+0.057, +0.046, +0.067), "qt": (+0.084, +0.053, +0.119)}
    for p, (d, lo, hi) in rq1.items():
        t = stat(p, "ours_vs_strongest", "acc@5", "overall")
        check(f"RQ1 {p} acc@5 {d:+.3f} [{lo:+.3f},{hi:+.3f}] SIG",
              r3(t["delta"]) == d and r3(t["ci_low"]) == lo
              and r3(t["ci_high"]) == hi and t["significant"],
              f"got {t['delta']:+.3f} [{t['ci_low']:+.3f},{t['ci_high']:+.3f}]")
        tm = stat(p, "ours_vs_strongest", "mrr", "overall")
        check(f"RQ1 {p} mrr SIG", tm["significant"])
    tb = istat("mariadb", "ours_vs_brtracer", "acc@5", "overall")
    check("RQ1 mariadb vs brtracer +0.142 [+0.119,+0.167] SIG",
          r3(tb["delta"]) == .142 and r3(tb["ci_low"]) == .119
          and r3(tb["ci_high"]) == .167 and tb["significant"],
          f"got {tb['delta']:+.3f} [{tb['ci_low']:+.3f},{tb['ci_high']:+.3f}]")
    tbm = istat("mariadb", "ours_vs_brtracer", "mrr", "overall")
    check("RQ1 mariadb vs brtracer mrr SIG", tbm["significant"])
    mrr_d = [stat(p, "ours_vs_strongest", "mrr", "overall")["delta"]
             for p in ("kafka", "mongodb", "qt")] + [tbm["delta"]]
    check("RQ1 mrr +0.058..+0.097 (vs per-project strongest)",
          r3(min(mrr_d)) == .058 and r3(max(mrr_d)) == .097,
          f"{min(mrr_d):.3f}..{max(mrr_d):.3f}")
    ts = stat("mariadb", "ours_vs_strongest", "acc@5", "overall")
    check("RQ1 mariadb vs S3 alone +0.187", r3(ts["delta"]) == .187)
    # abstract/intro range: per-project strongest acc@5 deltas
    strongest_d = [stat(p, "ours_vs_strongest", "acc@5", "overall")["delta"]
                   for p in ("kafka", "mongodb", "qt")] + [tb["delta"]]
    check("ABS acc@5 +0.057..+0.142",
          r3(min(strongest_d)) == .057 and r3(max(strongest_d)) == .142,
          f"{min(strongest_d):.3f}..{max(strongest_d):.3f}")
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
    # module sanity baselines (reviewer W5): random/frequency vs ours
    mb = json.loads((RES / "module-baselines.json").read_text(encoding="utf-8"))
    mb_expected = {  # (median modules, random@5, frequent@1, frequent@5)
        "kafka": (8, .610, .361, .763), "mariadb": (79, .076, .612, .905),
        "mongodb": (36, .153, .756, .894), "qt": (116, .099, .334, .809)}
    for p, (med, r5, f1, f5) in mb_expected.items():
        check(f"T3 {p} module baselines med={med} rnd5={r5} frq1={f1} frq5={f5}",
              mb[p]["modules_per_snapshot"]["median"] == med
              and r3(mb[p]["random"]["acc@5"]) == r5
              and r3(mb[p]["most_frequent"]["acc@1"]) == f1
              and r3(mb[p]["most_frequent"]["acc@5"]) == f5)
    check("S1/S5 module Acc@1 67-86% beats frequency by +0.08..+0.50",
          all(mods[p]["systems"]["cond_ours"]["acc@1"]
              - mb[p]["most_frequent"]["acc@1"] >= 0.08 for p in P)
          and 0.66 <= min(mods[p]["systems"]["cond_ours"]["acc@1"] for p in P)
          and max(mods[p]["systems"]["cond_ours"]["acc@1"] for p in P) <= 0.87)
    check("S5 ours clears frequency baseline at K=5 on every project",
          all(mods[p]["systems"]["cond_ours"]["acc@5"]
              > mb[p]["most_frequent"]["acc@5"] for p in P))

    # ---- Sec. 4/5 IRBL baselines + firewall leakage ---------------------------
    isumm = {p: json.loads((RES / f"{p}-irbl-summary.json").read_text(encoding="utf-8"))
             for p in P}
    t2b = {  # Table 2 baseline rows: system -> project -> (acc@5, mrr)
        "rvsm":             {"kafka": (.214, .192), "mariadb": (.239, .188),
                             "mongodb": (.127, .097), "qt": (.122, .101)},
        "buglocator_fw_a3": {"kafka": (.267, .199), "mariadb": (.300, .250),
                             "mongodb": (.245, .152), "qt": (.166, .131)},
        "brtracer_fw":      {"kafka": (.599, .479), "mariadb": (.516, .382),
                             "mongodb": (.456, .380), "qt": (.316, .284)},
    }
    for sysname, per in t2b.items():
        for p, (a5, mrr) in per.items():
            got = isumm[p]["eval"][sysname]
            check(f"T2 {p} {sysname} {a5}/{mrr}",
                  r3(got["acc@5"]) == a5 and r3(got["mrr"]) == mrr,
                  f"got {r3(got['acc@5'])}/{r3(got['mrr'])}")
    check("RQ1 mariadb brtracer .516 tops S3 .471; S3 strongest elsewhere",
          isumm["mariadb"]["eval"]["brtracer_fw"]["acc@5"]
          > summ["mariadb"]["eval"]["content_bm25"]["acc@5"]
          and all(summ[p]["eval"]["content_bm25"]["acc@5"]
                  > isumm[p]["eval"]["brtracer_fw"]["acc@5"]
                  for p in ("kafka", "mongodb", "qt")))
    brt_o = [istat(p, "ours_vs_brtracer", "acc@5", "overall") for p in P]
    check("RQ1 vs brtracer +0.142..+0.245 all SIG",
          r3(min(t["delta"] for t in brt_o)) == .142
          and r3(max(t["delta"] for t in brt_o)) == .245
          and all(t["significant"] for t in brt_o))
    brt_h = [istat(p, "ours_vs_brtracer", "acc@5", "hard") for p in P]
    check("RQ1 vs brtracer hard +0.133..+0.371 all SIG",
          r3(min(t["delta"] for t in brt_h)) == .133
          and r3(max(t["delta"] for t in brt_h)) == .371
          and all(t["significant"] for t in brt_h))

    leak = {"kafka": .044, "mariadb": .031, "mongodb": .058, "qt": .094}
    rels = []
    for p, d in leak.items():
        t = istat(p, "leak_simiscore", "acc@5", "overall")
        check(f"LEAK {p} simiscore +{d} SIG",
              r3(t["delta"]) == d and t["significant"], f"got {t['delta']:+.3f}")
        rels.append(t["delta"] / isumm[p]["eval"]["simiscore_fw"]["acc@5"])
    check("LEAK relative 9%..43%",
          round(100 * min(rels)) == 9 and round(100 * max(rels)) == 43,
          f"{100 * min(rels):.1f}%..{100 * max(rels):.1f}%")
    check("LEAK kafka noR4 0.368 = leaky 0.368",
          r3(isumm["kafka"]["eval"]["simiscore_noR4"]["acc@5"]) == .368
          and r3(isumm["kafka"]["eval"]["simiscore_leaky"]["acc@5"]) == .368)
    near = sum(1 for p in P
               if abs(isumm[p]["eval"]["simiscore_noR4"]["acc@5"]
                      - isumm[p]["eval"]["simiscore_leaky"]["acc@5"]) < 0.002)
    check("LEAK noR4 reproduces leaky on 3 projects", near == 3, str(near))
    check("LEAK noR2/noR3 recover nothing",
          all(abs(isumm[p]["eval"][c]["acc@5"]
                  - isumm[p]["eval"]["simiscore_fw"]["acc@5"]) < 0.001
              for p in P for c in ("simiscore_noR2", "simiscore_noR3")))
    for p, d, sig in (("kafka", .019, True), ("mariadb", .014, True),
                      ("mongodb", None, False), ("qt", None, False)):
        t = istat(p, "leak_buglocator", "acc@5", "overall")
        ok = t["significant"] == sig and (d is None or r3(t["delta"]) == d)
        check(f"LEAK {p} buglocator "
              f"{'+' + format(d, '.3f') + ' SIG' if sig else 'ns'}", ok,
              f"got {t['delta']:+.3f} {'SIG' if t['significant'] else 'ns'}")
    for p, d in (("kafka", .160), ("mariadb", .122),
                 ("mongodb", .109), ("qt", .059)):
        t = istat(p, "s4_vs_simiscore", "acc@5", "overall")
        check(f"LEAK {p} S4 vs simiscore +{d} SIG",
              r3(t["delta"]) == d and t["significant"], f"got {t['delta']:+.3f}")

    # ---- Sec. 5 function-level stage -----------------------------------------
    fsum = {p: json.loads((RES / f"{p}-functions-summary.json")
                          .read_text(encoding="utf-8")) for p in P}
    t4 = {  # (eligible, acc@1, acc@5, acc@10, mrr, oracle)
        "kafka":   (.954, .240, .478, .600, .357, .856),
        "mariadb": (.919, .132, .274, .348, .199, .718),
        "mongodb": (.944, .259, .467, .550, .355, .747),
        "qt":      (.868, .140, .288, .345, .211, .576)}
    for p, (el, a1, a5, a10, mrr, orc) in t4.items():
        f, e = fsum[p], fsum[p]["eval_eligible"]
        check(f"T4 {p} functions {el}/{a1}/{a5}/{a10}/{mrr}/{orc}",
              r3(f["eligible_fraction_all"]) == el and r3(e["acc@1"]) == a1
              and r3(e["acc@5"]) == a5 and r3(e["acc@10"]) == a10
              and r3(e["mrr"]) == mrr and r3(e["oracle_in_candidates"]) == orc,
              f"got {f['eligible_fraction_all']}/{e}")
    check("FUNC eligible 87-95%, acc@5 27-48%",
          round(min(fsum[p]["eligible_fraction_all"] for p in P), 2) == .87
          and round(max(fsum[p]["eligible_fraction_all"] for p in P), 2) == .95
          and round(min(fsum[p]["eval_eligible"]["acc@5"] for p in P), 2) == .27
          and round(max(fsum[p]["eval_eligible"]["acc@5"] for p in P), 2) == .48)

    # ---- Sec. 5 noise robustness ----------------------------------------------
    nsum = {p: json.loads((RES / f"{p}-noise-summary.json")
                          .read_text(encoding="utf-8")) for p in P}
    t5 = {  # (clean, dup1, dup5, gen1, gen5, for1, for5, drop)
        "kafka":   (.800, .790, .770, .780, .725, .535, .285, .730),
        "mariadb": (.635, .590, .580, .590, .575, .285, .125, .470),
        "mongodb": (.700, .710, .675, .595, .465, .555, .260, .565),
        "qt":      (.555, .545, .510, .470, .420, .420, .200, .405)}
    keys = ("clean", "dup_x1", "dup_x5", "generic_x1", "generic_x5",
            "foreign_x1", "foreign_x5", "drop")
    for p, vals in t5.items():
        a = nsum[p]["acc@5"]
        check(f"T5 {p} noise row", all(r3(a[k]) == v for k, v in zip(keys, vals)),
              f"got {[a[k] for k in keys]}")
        check(f"NOISE {p} clean anchor within 0.025 of main run",
              abs(a["clean"] - nsum[p]["clean_main_run_acc5"]) <= 0.025,
              f"{a['clean']} vs {nsum[p]['clean_main_run_acc5']}")
    check("NOISE dup x5 costs at most 0.06",
          all(nsum[p]["acc@5"]["clean"] - nsum[p]["acc@5"]["dup_x5"] <= 0.06
              for p in P))
    check("NOISE drop costs 0.07..0.17",
          all(0.07 <= round(nsum[p]["acc@5"]["clean"]
                            - nsum[p]["acc@5"]["drop"], 3) <= 0.17 for p in P))
    check("NOISE foreign x5 cuts to at most 37% of clean",
          max(nsum[p]["acc@5"]["foreign_x5"] / nsum[p]["acc@5"]["clean"]
              for p in P) <= 0.375)
    f1 = [nsum[p]["regime_flips"]["foreign_x1"] / 200 for p in P]
    f5max = max(nsum[p]["regime_flips"]["foreign_x5"] / 200 for p in P)
    check("NOISE foreign flips third..half at x1, up to 63% at x5",
          1 / 3 <= min(f1) and max(f1) <= 0.52 and 0.62 < f5max <= 0.63,
          f"x1 {min(f1):.3f}..{max(f1):.3f}, x5 max {f5max:.3f}")
    check("NOISE mongodb generic x5 costs 0.235; others 0.06-0.14",
          r3(nsum["mongodb"]["acc@5"]["clean"]
             - nsum["mongodb"]["acc@5"]["generic_x5"]) == .235
          and all(0.06 <= r3(nsum[p]["acc@5"]["clean"]
                             - nsum[p]["acc@5"]["generic_x5"]) <= 0.14
                  for p in ("kafka", "mariadb", "qt")))

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

    # ---- Sec. 2/5/6 review-response analyses ----------------------------------
    roll = json.loads((RES / "rolling-origin.json").read_text(encoding="utf-8"))
    deltas = [roll[p]["delta"] for p in P]
    check("S6 rolling-origin delta -0.007..+0.021",
          r3(min(deltas)) == -.007 and r3(max(deltas)) == .021,
          f"{min(deltas)}..{max(deltas)}")
    sv2 = json.loads((RES / "stratum-v2.json").read_text(encoding="utf-8"))
    check("S2 stratum def2 hard 14/33/38/38",
          tuple(sv2[p]["hard2_pct"] for p in P) == (14, 33, 38, 38),
          str({p: sv2[p]["hard2_pct"] for p in P}))

    # kafka-hard fusion-loss anatomy (honest negatives)
    krows = [json.loads(l) for l in
             (RES / "kafka-instances.jsonl").open(encoding="utf-8")]
    krows.sort(key=lambda r: r["fix_time"])
    khard = [r for r in krows[summ["kafka"]["n_dev"]:] if not r["strata"]["easy"]]
    lost = [r for r in khard if r["metrics"]["content_bm25"]["acc@5"] == 1
            and r["metrics"]["cond_ours"]["acc@5"] == 0]
    won = [r for r in khard if r["metrics"]["content_bm25"]["acc@5"] == 0
           and r["metrics"]["cond_ours"]["acc@5"] == 1]
    check("NEG kafka-hard anatomy: 8 lost, 0 won, 8/8 trace file in top5",
          len(lost) == 8 and len(won) == 0
          and all(any(f in r["rankings"]["trace_grep"][:5]
                      for f in r["rankings"]["cond_ours"][:5]) for r in lost),
          f"lost={len(lost)} won={len(won)}")

    # provenance citation coverage (Sec. 6 explanation)
    m_pct, v_pct = [], []
    for p in P:
        rows_p = [json.loads(l) for l in
                  (RES / f"{p}-instances.jsonl").open(encoding="utf-8")]
        rows_p.sort(key=lambda r: r["fix_time"])
        hits = cites = men = vot = 0
        for r in rows_p[summ[p]["n_dev"]:]:
            gset = set(r["gold_files"])
            g = next((f for f in r["rankings"]["cond_ours"][:5] if f in gset), None)
            if g is None:
                continue
            hits += 1
            e = r["provenance"].get(g, {})
            cites += any(k in e for k in ("mention", "content_terms",
                                          "path_terms", "voted_by"))
            men += "mention" in e
            vot += "voted_by" in e
        check(f"S6 {p} provenance citation on 100% of top-5 gold hits",
              cites == hits, f"{cites}/{hits}")
        m_pct.append(men / hits)
        v_pct.append(vot / hits)
    check("S6 mention 52-86%, voters 63-80%",
          .515 <= min(m_pct) and max(m_pct) <= .86
          and .625 <= min(v_pct) and max(v_pct) <= .80,
          f"mention {min(m_pct):.3f}..{max(m_pct):.3f} "
          f"voters {min(v_pct):.3f}..{max(v_pct):.3f}")

    # ---- Sec. 4/6 protocol + misc --------------------------------------------
    check("S4 64-test BH family", stats["n_tests"] == 64)
    check("S4 96-test baseline/leakage BH family", stats_irbl["n_tests"] == 96)
    check("S4 bootstrap 2,000 resamples", stats["n_bootstrap"] == 2000
          and stats_irbl["n_bootstrap"] == 2000)
    lat_expected = {"kafka": .07, "qt": .22, "mariadb": .41, "mongodb": .41}
    for p, med in lat_expected.items():
        lat = summ[p]["latency"]
        check(f"S6 {p} latency median {med}s, p95<0.7s, index<=0.1s",
              round(lat["per_issue_median_s"], 2) == med
              and lat["per_issue_p95_s"] < 0.7
              and round(lat["mem_index_build_s"], 1) <= 0.1,
              f"got {lat}")
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
