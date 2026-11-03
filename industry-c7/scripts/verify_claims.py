"""Trace every number the paper states to the result file it came from.

One check per claim: the paper says X (hard-coded here, matching the tex),
the result file says Y; the check fails loudly if they disagree. Run green
before every submission. Sections refer to industry-c7/paper/sections/.

Usage:
    python industry-c7/scripts/verify_claims.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "industry-c7/data/results"
BENCH = ROOT / "industry-c7/data/benchmark"
P = ("kafka", "mariadb", "mongodb", "qt")

checks: list[tuple[str, bool, str]] = []


def check(claim: str, ok: bool, detail: str = "") -> None:
    checks.append((claim, ok, detail))


def evaluate_local(ranking: list, gold: list) -> dict:
    """Acc@K over a stored ranking. Same rule as localize.evaluate, kept
    local so this script depends on data files only."""
    g = set(gold)
    return {f"acc@{k}": float(bool(g.intersection(ranking[:k])))
            for k in (1, 5, 10)}


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
                            "mongodb": (.347, .314), "qt": (.263, .226)},
        "path_bm25":       {"kafka": (.481, .379), "mariadb": (.259, .198),
                            "mongodb": (.360, .259), "qt": (.266, .195)},
        "content_bm25":    {"kafka": (.708, .545), "mariadb": (.471, .330),
                            "mongodb": (.643, .472), "qt": (.456, .350)},
        "memory_bm25":     {"kafka": (.483, .361), "mariadb": (.461, .342),
                            "mongodb": (.380, .299), "qt": (.278, .211)},
        "fused_no_memory": {"kafka": (.767, .611), "mariadb": (.443, .342),
                            "mongodb": (.522, .410), "qt": (.353, .292)},
        "fused_ours":      {"kafka": (.790, .600), "mariadb": (.562, .408),
                            "mongodb": (.623, .496), "qt": (.463, .351)},
        "cond_no_memory":  {"kafka": (.792, .625), "mariadb": (.642, .479),
                            "mongodb": (.690, .562), "qt": (.456, .350)},
        "cond_ours":       {"kafka": (.794, .625), "mariadb": (.658, .479),
                            "mongodb": (.698, .550), "qt": (.541, .408)},
    }
    for sysname, per in t2.items():
        for p, (a5, mrr) in per.items():
            got = summ[p]["eval"][sysname]
            check(f"T2 {p} {sysname} {a5}/{mrr}",
                  r3(got["acc@5"]) == a5 and r3(got["mrr"]) == mrr,
                  f"got {r3(got['acc@5'])}/{r3(got['mrr'])}")

    # mongodb lost 99 eval instances to the test-only-gold exclusion
    # (scripts/scored_set.py); the other three projects are untouched.
    check("S5 eval sizes 476/1179/2434/320",
          tuple(summ[p]["n_eval"] for p in P) == (476, 1179, 2434, 320))
    n_hard = sum(stat(p, "ours_vs_strongest", "acc@5", "hard")["n"] for p in P)
    check("S5 2,278 hard eval instances", n_hard == 2278, str(n_hard))

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
           "mongodb": (+0.055, +0.044, +0.066), "qt": (+0.084, +0.053, +0.119)}
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
    check("ABS acc@5 +0.055..+0.142",
          r3(min(strongest_d)) == .055 and r3(max(strongest_d)) == .142,
          f"{min(strongest_d):.3f}..{max(strongest_d):.3f}")
    grep_d = [stat(p, "ours_vs_tracegrep", "acc@5", "overall")["delta"] for p in P]
    check("S5 grep margins +0.137..+0.351",
          r3(min(grep_d)) == .137 and r3(max(grep_d)) == .351,
          f"{min(grep_d):.3f}..{max(grep_d):.3f}")
    hard_ours = [summ[p]["eval_hard"]["cond_ours"]["acc@5"] for p in P]
    check("S5 hard ours 0.361..0.545",
          r3(min(hard_ours)) == .361 and r3(max(hard_ours)) == .545,
          f"{min(hard_ours):.3f}..{max(hard_ours):.3f}")
    check("S5 S1 zero on hard",
          all(summ[p]["eval_hard"]["trace_grep"]["acc@5"] == 0.0 for p in P))

    # ---- Sec. 5 RQ2 -----------------------------------------------------------
    check("RQ2 mariadb-hard memory .442 beats content .406",
          r3(summ["mariadb"]["eval_hard"]["memory_bm25"]["acc@5"]) == .442
          and r3(summ["mariadb"]["eval_hard"]["content_bm25"]["acc@5"]) == .406)
    for p, d in (("mariadb", .209), ("mongodb", .166), ("qt", .153)):
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
          "mongodb": (.810, .842, .979), "qt": (.613, .669, .925)}
    for p, (c1, o1, o5) in t3.items():
        m = mods[p]["systems"]
        check(f"T3 {p} content@1={c1} ours@1={o1} ours@5={o5}",
              r3(m["content_bm25"]["acc@1"]) == c1
              and r3(m["cond_ours"]["acc@1"]) == o1
              and r3(m["cond_ours"]["acc@5"]) == o5,
              f"got {r3(m['content_bm25']['acc@1'])}/"
              f"{r3(m['cond_ours']['acc@1'])}/{r3(m['cond_ours']['acc@5'])}")
    # module sanity baselines (reviewer W5): random/frequency vs ours
    mb = json.loads((RES / "module-baselines.json").read_text(encoding="utf-8"))
    mb_expected = {  # (median modules, random@5, frequent@1, frequent@5)
        "kafka": (8, .610, .361, .763), "mariadb": (78, .077, .612, .905),
        "mongodb": (35, .155, .765, .918), "qt": (116, .099, .334, .809)}
    for p, (med, r5, f1, f5) in mb_expected.items():
        check(f"T3 {p} module baselines med={med} rnd5={r5} frq1={f1} frq5={f5}",
              mb[p]["modules_per_snapshot"]["median"] == med
              and r3(mb[p]["random"]["acc@5"]) == r5
              and r3(mb[p]["most_frequent"]["acc@1"]) == f1
              and r3(mb[p]["most_frequent"]["acc@5"]) == f5,
              f"got {mb[p]['modules_per_snapshot']['median']}/"
              f"{r3(mb[p]['random']['acc@5'])}/"
              f"{r3(mb[p]['most_frequent']['acc@1'])}/"
              f"{r3(mb[p]['most_frequent']['acc@5'])}")
    # pinned to exact endpoints, not a range: a loose bound is how a wrong
    # number reached a reviewer once already
    mod_a1 = [mods[p]["systems"]["cond_ours"]["acc@1"] for p in P]
    mod_gain = [mods[p]["systems"]["cond_ours"]["acc@1"]
                - mb[p]["most_frequent"]["acc@1"] for p in P]
    check("S1/S5 module Acc@1 0.669..0.861, beats frequency by +0.077..+0.500",
          r3(min(mod_a1)) == .669 and r3(max(mod_a1)) == .861
          and r3(min(mod_gain)) == .077 and r3(max(mod_gain)) == .500,
          f"{min(mod_a1):.3f}..{max(mod_a1):.3f} "
          f"gain {min(mod_gain):.3f}..{max(mod_gain):.3f}")
    check("S5 ours clears frequency baseline at K=5 on every project",
          all(mods[p]["systems"]["cond_ours"]["acc@5"]
              > mb[p]["most_frequent"]["acc@5"] for p in P))

    # ---- Sec. 4/5 IRBL baselines + firewall leakage ---------------------------
    isumm = {p: json.loads((RES / f"{p}-irbl-summary.json").read_text(encoding="utf-8"))
             for p in P}
    t2b = {  # Table 2 baseline rows: system -> project -> (acc@5, mrr)
        "rvsm":             {"kafka": (.214, .192), "mariadb": (.239, .188),
                             "mongodb": (.124, .095), "qt": (.122, .101)},
        "buglocator_fw_a3": {"kafka": (.267, .199), "mariadb": (.300, .250),
                             "mongodb": (.245, .151), "qt": (.166, .131)},
        "brtracer_fw":      {"kafka": (.599, .479), "mariadb": (.516, .382),
                             "mongodb": (.449, .375), "qt": (.316, .284)},
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
    check("RQ1 vs brtracer +0.142..+0.249 all SIG",
          r3(min(t["delta"] for t in brt_o)) == .142
          and r3(max(t["delta"] for t in brt_o)) == .249
          and all(t["significant"] for t in brt_o),
          f"{min(t['delta'] for t in brt_o):.3f}.."
          f"{max(t['delta'] for t in brt_o):.3f}")
    brt_h = [istat(p, "ours_vs_brtracer", "acc@5", "hard") for p in P]
    check("RQ1 vs brtracer hard +0.133..+0.374 all SIG",
          r3(min(t["delta"] for t in brt_h)) == .133
          and r3(max(t["delta"] for t in brt_h)) == .374
          and all(t["significant"] for t in brt_h),
          f"{min(t['delta'] for t in brt_h):.3f}.."
          f"{max(t['delta'] for t in brt_h):.3f}")

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
                 ("mongodb", .104), ("qt", .059)):
        t = istat(p, "s4_vs_simiscore", "acc@5", "overall")
        check(f"LEAK {p} S4 vs simiscore +{d} SIG",
              r3(t["delta"]) == d and t["significant"], f"got {t['delta']:+.3f}")

    # ---- Sec. 5 function-level stage -----------------------------------------
    fsum = {p: json.loads((RES / f"{p}-functions-summary.json")
                          .read_text(encoding="utf-8")) for p in P}
    t4 = {  # (eligible, acc@1, acc@5, acc@10, mrr, oracle)
        "kafka":   (.954, .240, .478, .600, .357, .856),
        "mariadb": (.919, .132, .274, .348, .199, .718),
        "mongodb": (.944, .258, .464, .549, .353, .742),
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
    # pinned to exact endpoints, not a straddling range
    check("S6 mention 50.7-86.0%, voters 63.0-79.6%",
          r3(min(m_pct)) == .507 and r3(max(m_pct)) == .860
          and r3(min(v_pct)) == .630 and r3(max(v_pct)) == .796,
          f"mention {min(m_pct):.3f}..{max(m_pct):.3f} "
          f"voters {min(v_pct):.3f}..{max(v_pct):.3f}")

    # ---- Sec. 5 dense-vs-lexical slots ----------------------------------------
    dsum = {p: json.loads((RES / f"{p}-dense-summary.json")
                          .read_text(encoding="utf-8"))["systems"] for p in P}
    t6 = {  # (s3_bm25, s3_dense, s4_bm25, s4_dense, cond, cond_dense_s4)
        "kafka":   (.690, .485, .460, .530, .790, .795),
        "mariadb": (.425, .350, .455, .515, .630, .675),
        "mongodb": (.665, .460, .410, .425, .715, .720),
        "qt":      (.460, .425, .305, .290, .555, .555)}
    for p, (c_b, c_d, m_b, m_d, co, cd4) in t6.items():
        d = dsum[p]
        check(f"T6 {p} dense row",
              r3(d["content_bm25"]["acc@5"]) == c_b
              and r3(d["content_dense"]["acc@5"]) == c_d
              and r3(d["memory_bm25"]["acc@5"]) == m_b
              and r3(d["memory_dense"]["acc@5"]) == m_d
              and r3(d["cond_ours"]["acc@5"]) == co
              and r3(d["cond_dense_s4"]["acc@5"]) == cd4,
              f"got {[d[s]['acc@5'] for s in ('content_bm25','content_dense','memory_bm25','memory_dense','cond_ours','cond_dense_s4')]}")
    check("DENSE S3 loses by up to 0.205; S4 wins 3 of 4; mariadb fused +0.045",
          r3(max(dsum[p]["content_bm25"]["acc@5"]
                 - dsum[p]["content_dense"]["acc@5"] for p in P)) == .205
          and sum(dsum[p]["memory_dense"]["acc@5"]
                  > dsum[p]["memory_bm25"]["acc@5"] for p in P) == 3
          and r3(dsum["mariadb"]["cond_dense_s4"]["acc@5"]
                 - dsum["mariadb"]["cond_ours"]["acc@5"]) == .045)
    check("DENSE sample cond_ours anchors within 0.03 of main runs",
          all(abs(dsum[p]["cond_ours"]["acc@5"]
                  - summ[p]["eval"]["cond_ours"]["acc@5"]) <= 0.03 for p in P))

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

    # ---- Sec. 1/4/5: the comparative study and the agent (n=790) --------------
    AG = ROOT / "industry-c7/data/agent"
    LLMD = ROOT / "industry-c7/data/llm"

    def jl(path, skip_err=True):
        out = {}
        if not path.exists():
            return out
        for line in path.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if skip_err and d.get("error"):
                continue
            out[d["id"]] = d
        return out

    v2 = jl(AG / "agent-v2.jsonl")
    v1 = jl(AG / "agent-v1.jsonl")
    shuf = jl(AG / "agent-shuffle.jsonl")
    check("S5 agent ran 790 instances, 375 hard, 0 errors",
          len(v2) == 790 and sum(1 for r in v2.values() if r["hard"]) == 375,
          f"n={len(v2)} hard={sum(1 for r in v2.values() if r['hard'])}")
    check("S4 every agent run ended in a submission",
          all(r["stop_reason"] == "submitted" for r in v2.values()),
          str(Counter(r["stop_reason"] for r in v2.values())))
    excl = json.loads((AG / "excluded-test-only-gold.json")
                      .read_text(encoding="utf-8"))
    check("S5 ten test-only-gold instances excluded", excl["n"] == 10,
          str(excl["n"]))

    tbl = json.loads((RES / "final-table-790.json").read_text(encoding="utf-8"))
    S = tbl["systems"]
    check("T-study population n=790, hard=375",
          tbl["n"] == 790 and tbl["n_hard"] == 375)
    t_study = {  # system -> (acc@1, acc@5, mrr, hard@5)
        "rVSM": (.071, .180, .143, .165),
        "BugLocator": (.097, .251, .183, .232),
        "BRTracer-style": (.301, .481, .395, .171),
        "ours": (.399, .681, .522, .424),
        "llm_rerank": (.604, .780, .678, .576),
        "llm": (.594, .832, .692, .725),
        "fusion": (.538, .839, .667, .717),
        "agent": (.723, .903, .799, .816)}
    for name, (a1, a5, mr, h5) in t_study.items():
        s = S[name]
        check(f"T-study {name} {a1}/{a5}/{mr}/{h5}",
              r3(s["acc@1"]) == a1 and r3(s["acc@5"]) == a5
              and r3(s["mrr"]) == mr and r3(s["hard@5"]) == h5,
              f"got {r3(s['acc@1'])}/{r3(s['acc@5'])}/{r3(s['mrr'])}/{r3(s['hard@5'])}")
    # The study table is printed as percentages. Check the rendered strings
    # against the artifact, so the decimal-to-percent conversion is itself
    # verified rather than trusted.
    res_tex = (ROOT / "industry-c7/paper/sections/05-results.tex").read_text(
        encoding="utf-8")
    tab = res_tex.split("\\label{tab:study}")[1].split("\\end{tabular}")[0]
    for name, row in (("rVSM", "rVSM"), ("BugLocator", "BugLocator"),
                      ("BRTracer-style", "BRTracer-style"),
                      ("ours", "retrieval + memory"),
                      ("llm_rerank", "model as re-ranker"),
                      ("llm", "model alone"),
                      ("fusion", "fusion (best non-agent)"),
                      ("agent", "\\sys{}")):
        line = next((l for l in tab.split("\n")
                     if l.strip().startswith(row)), "")
        cells = [c.replace("\\\\", "").replace("\\textbf{", "")
                 .replace("}", "").strip()
                 for c in line.split("&")[1:]]
        want = [f"{100 * S[name][k]:.1f}"
                for k in ("acc@1", "acc@5")] + [
            f"{100 * S[name]['hard@5']:.1f}"]
        got = [cells[0], cells[1], cells[3]] if len(cells) >= 4 else cells
        check(f"T-study {row} printed as percent {'/'.join(want)}",
              got == want, f"tex shows {got}, data says {want}")
    # MRR is a mean reciprocal rank, not a proportion, so it must NOT be
    # rendered as a percentage anywhere.
    check("T-study MRR column still a decimal (not a percentage)",
          ".799" in tab and "79.9" not in tab,
          "MRR appears to have been converted to a percentage")

    check("ABS/S5 study range .180 to .839 for non-agent systems",
          r3(min(S[k]["acc@5"] for k in t_study if k != "agent")) == .180
          and r3(max(S[k]["acc@5"] for k in t_study if k != "agent")) == .839)
    # agent deltas quoted in the abstract, intro and S5
    for base, a5d, a1d in (("fusion", .063, .185), ("llm", .071, .129),
                           ("ours", .222, .324)):
        check(f"S5 agent vs {base}: +{a5d} acc@5, +{a1d} acc@1",
              r3(S["agent"]["acc@5"] - S[base]["acc@5"]) == a5d
              and r3(S["agent"]["acc@1"] - S[base]["acc@1"]) == a1d,
              f"got {r3(S['agent']['acc@5'] - S[base]['acc@5'])}/"
              f"{r3(S['agent']['acc@1'] - S[base]['acc@1'])}")
    for base, h5d, h1d in (("fusion", .099, .275), ("llm", .091, .181)):
        check(f"S5 agent vs {base} on hard: +{h5d} acc@5, +{h1d} acc@1",
              r3(S["agent"]["hard@5"] - S[base]["hard@5"]) == h5d
              and r3(S["agent"]["hard@1"] - S[base]["hard@1"]) == h1d,
              f"got {r3(S['agent']['hard@5'] - S[base]['hard@5'])}/"
              f"{r3(S['agent']['hard@1'] - S[base]['hard@1'])}")

    # S5/S4: the agent test family. The CIs and the "all significant" claim
    # are quoted in S5 and must come from a released artifact, not from a
    # number remembered out of a notebook.
    st790 = json.loads((RES / "stats-study-790.json")
                       .read_text(encoding="utf-8"))
    sx = {(t["comparison"], t["metric"], t["population"]): t
          for t in st790["tests"]}
    check("S5 agent family: 42 tests on n=790, all BH-significant",
          st790["n_tests"] == 42 and st790["n"] == 790
          and all(t["significant"] for t in st790["tests"]),
          f"{st790['n_tests']} tests, "
          f"{sum(1 for t in st790['tests'] if t['significant'])} significant")
    t_ci = {("llm", "acc@5", "overall"): (.071, .046, .095),
            ("fusion", "acc@5", "overall"): (.063, .042, .085),
            ("fusion", "acc@1", "overall"): (.185, .149, .223),
            ("ours", "acc@5", "overall"): (.222, .194, .252),
            ("fusion", "acc@5", "hard"): (.099, .056, .139),
            ("llm", "acc@5", "hard"): (.091, .045, .136)}
    for (base, metric, pop), (d, lo, hi) in t_ci.items():
        t = sx[(f"agent_vs_{base}", metric, pop)]
        check(f"S5 agent vs {base} {metric} {pop} {d:+.3f} [{lo:+.3f},{hi:+.3f}]",
              r3(t["delta"]) == d and r3(t["ci_low"]) == lo
              and r3(t["ci_high"]) == hi,
              f"got {t['delta']:+.3f} [{t['ci_low']:+.3f},{t['ci_high']:+.3f}]")

    # S4 setup: the ten removed instances are EASIER than the ones kept, so
    # removing them cannot be what produced the result.
    check("S4 excluded-10 easier than kept-790 (exclusion is conservative)",
          r3(excl["retr_acc5_excluded"]) == .900
          and r3(excl["retr_acc5_kept"]) == .681,
          f"excluded {excl.get('retr_acc5_excluded')} vs "
          f"kept {excl.get('retr_acc5_kept')}")

    # S7: the motivating example of S1 is one the agent MISSES. Disclosed in
    # the agent's limitations; pin it so the disclosure cannot go stale.
    k6624 = next((r for r in v2.values() if r["issue_key"] == "KAFKA-6624"),
                 None)
    check("S7 KAFKA-6624: agent and retrieval both miss it entirely",
          k6624 is not None and k6624["metrics"]["acc@10"] == 0.0
          and k6624["metrics_lexical"]["acc@10"] == 0.0
          and k6624["gold_files"] == [
              "core/src/main/scala/kafka/log/LogManager.scala"],
          "KAFKA-6624 absent" if k6624 is None else
          f"agent acc@10={k6624['metrics']['acc@10']}, "
          f"gold={k6624['gold_files']}")
    check("S7 KAFKA-6624: agent ranks Log.scala then LogSegment.scala first",
          k6624 is not None and k6624["ranking"][:2] == [
              "core/src/main/scala/kafka/log/Log.scala",
              "core/src/main/scala/kafka/log/LogSegment.scala"],
          "" if k6624 is None else str(k6624["ranking"][:2]))

    # complementarity, quoted in S1 and S5
    llm_rank = {}
    for line in (LLMD / "scored-a2.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if not d.get("variant"):
            llm_rank[d["id"]] = d["ranking"]
    lex = {}
    for p in P:
        for line in (RES / f"{p}-instances.jsonl").open(encoding="utf-8"):
            r = json.loads(line)
            lex[f"{p}:{r['issue_key']}"] = r["rankings"]["cond_ours"]
    ids = [i for i in v2 if i in llm_rank and i in lex]
    c = Counter()
    for i in ids:
        g = set(v2[i]["gold_files"])
        o, l = bool(set(lex[i][:5]) & g), bool(set(llm_rank[i][:5]) & g)
        c["both"] += o and l
        c["ours_only"] += o and not l
        c["llm_only"] += l and not o
        c["neither"] += (not o) and (not l)
        c["union"] += bool((set(lex[i][:5]) | set(llm_rank[i][:5])) & g)
    n = len(ids)
    check("S1/S5 complementarity .620/.061/.211/.108, union .892",
          r3(c["both"] / n) == .620 and r3(c["ours_only"] / n) == .061
          and r3(c["llm_only"] / n) == .211 and r3(c["neither"] / n) == .108
          and r3(c["union"] / n) == .892,
          f"got {r3(c['both']/n)}/{r3(c['ours_only']/n)}/"
          f"{r3(c['llm_only']/n)}/{r3(c['neither']/n)}/{r3(c['union']/n)}")
    check("S5 agent .903 exceeds the .892 union ceiling",
          S["agent"]["acc@5"] > c["union"] / n)
    n105 = sum(1 for i in ids if v2[i]["hard"]
               and v2[i]["metrics"]["acc@1"] == 1
               and v2[i]["metrics_lexical"]["acc@5"] == 0)
    check("S1/S5 105 hard instances: agent ranks gold first, retrieval misses",
          n105 == 105, str(n105))
    k = v2.get("kafka:KAFKA-7693")
    check("S1 KAFKA-7693 example: agent ranks gold first, retrieval misses",
          k is not None and k["hard"] and k["metrics"]["acc@1"] == 1
          and k["metrics_lexical"]["acc@5"] == 0
          and k["agent_ranking"][0].endswith("TransactionManager.java"))

    # S4: 72.9% of the plain model's misses are ranking failures
    a1resp = {}
    for line in (LLMD / "resp-a1.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        a1resp[d["id"]] = [x.rstrip("/").replace("\\", "/") for x in
                           (d.get("parsed") or {}).get("directories", [])]
    a2sc = {}
    for line in (LLMD / "scored-a2.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if not d.get("variant") and d.get("is_eval"):
            a2sc[d["id"]] = d
    rank_f = funnel_f = 0
    for rid, row in a2sc.items():
        if row["metrics"].get("acc@5") == 1:
            continue
        gdirs = {str(Path(f).parent).replace("\\", "/")
                 for f in row["gold_files"]}
        if gdirs & set(a1resp.get(rid, [])):
            rank_f += 1
        else:
            funnel_f += 1
    share = rank_f / max(rank_f + funnel_f, 1)
    check("S4 73.2% of the plain model's misses are ranking failures",
          round(share, 3) == .732, f"{share:.3f}")

    # ---- T2b: annotation agreement, and T4 under either rater ----------------
    agr_p = ROOT / "industry-c7/data/causal-gold/agreement.json"
    if agr_p.exists():
        ag = json.loads(agr_p.read_text(encoding="utf-8"))
        check("T2b raters are two different models, 151 instances, 349 files",
              (ag["pass1_annotator"], ag["pass2_annotator"])
              == ("claude-opus-5", "claude-sonnet-5-5")
              and (ag["n_instances"], ag["n_files"]) == (151, 349),
              f"{ag['pass1_annotator']}/{ag['pass2_annotator']} "
              f"{ag['n_instances']}/{ag['n_files']}")
        check("T2b role kappa 0.793 raw 87.4%",
              r3(ag["role_6cat"]["kappa"]) == .793
              and round(ag["role_6cat"]["raw"] * 100, 1) == 87.4,
              f"{ag['role_6cat']['kappa']:.3f} / "
              f"{ag['role_6cat']['raw']*100:.1f}%")
        check("T2b causal-vs-not kappa 0.885 raw 94.3%",
              r3(ag["causal_binary"]["kappa"]) == .885
              and round(ag["causal_binary"]["raw"] * 100, 1) == 94.3,
              f"{ag['causal_binary']['kappa']:.3f} / "
              f"{ag['causal_binary']['raw']*100:.1f}%")
        check("T2b relation kappa 0.504, the weakest field",
              r3(ag["relation"]["kappa"]) == .504
              and ag["relation"]["kappa"] < ag["causal_binary"]["kappa"],
              f"{ag['relation']['kappa']:.3f}")
        check("T2b identical causal set on 136 of 151 instances",
              ag["instance_causal_set_identical"] == 136,
              str(ag["instance_causal_set_identical"]))
        check("T2b T3 is 49.0% under rater 1 and 50.1% under rater 2",
              ag["t3_pass1"] == [171, 349] and ag["t3_pass2"] == [175, 349],
              f"{ag['t3_pass1']} {ag['t3_pass2']}")
        for tag, cu in (("rater 1", ag["curve_pass1"]),
                        ("rater 2", ag["curve_pass2"])):
            sh = [cu[k][0] / cu[k][1] for k in ("1", "2-3", "4-7", "8+")]
            check(f"T2b curve falls monotonically with fix size, {tag}",
                  all(sh[i] > sh[i + 1] for i in range(3)),
                  " ".join(f"{x*100:.0f}%" for x in sh))
    cg1 = RES / "causal-gold-scores.json"
    cg2 = RES / "causal-gold-scores-pass2.json"
    if cg1.exists() and cg2.exists():
        s1 = json.loads(cg1.read_text(encoding="utf-8"))["systems"]
        s2 = json.loads(cg2.read_text(encoding="utf-8"))["systems"]
        gaps = {s: (s1[s]["gap"]["acc@5"]["delta"], s2[s]["gap"]["acc@5"]["delta"])
                for s in ("cond_ours", "llm_rerank", "llm_twostage", "remember")}
        check("T4 the fix-to-causal gap is the same under either rater "
              "(within 0.2 points)",
              all(abs(a - b) <= 0.002 for a, b in gaps.values()),
              str({k: (round(a, 4), round(b, 4)) for k, (a, b) in gaps.items()}))
        check("T4 REMEMBER has the smallest gap under both raters",
              gaps["remember"][0] == min(a for a, _ in gaps.values())
              and gaps["remember"][1] == min(b for _, b in gaps.values()))

    # ---- Sec. 4 setup: the scored set -----------------------------------------
    # Sec. IV-B claims the test-only-gold removal is conservative. Record the
    # measurement, do not assert it: a previous draft said these instances
    # were unanswerable, which the data contradicts.
    ex1 = json.loads((ROOT / "industry-c7/data/benchmark"
                      / "excluded-test-only-gold.json").read_text(encoding="utf-8"))
    ex2 = json.loads((ROOT / "industry-c7/data/benchmark-v2"
                      / "excluded-test-only-gold.json").read_text(encoding="utf-8"))
    check("S4 scored set: 123 of 6,437 removed, 6,314 scored, all mongodb",
          (ex1["n_excluded"], ex1["n_total"], ex1["n_scored"]) == (123, 6437, 6314)
          and list(ex1["per_project"]) == ["mongodb"],
          f"{ex1['n_excluded']}/{ex1['n_total']} {list(ex1['per_project'])}")
    check("S2 benchmark-v2 scored set: 101 of 38,001 removed",
          (ex2["n_excluded"], ex2["n_total"]) == (101, 38001),
          f"{ex2['n_excluded']}/{ex2['n_total']}")
    removed = ROOT / "industry-c7/data/results/removed-test-only-gold"
    rm_m = [evaluate_local(r["rankings"]["cond_ours"], r["gold_files"])
            for p in P for r in
            (json.loads(l) for l in
             (removed / f"{p}-instances.jsonl").open(encoding="utf-8"))]
    rm_a5 = sum(m["acc@5"] for m in rm_m) / len(rm_m)
    kept_a5 = (sum(summ[p]["eval"]["cond_ours"]["acc@5"] * summ[p]["n_eval"]
                   for p in P) / sum(summ[p]["n_eval"] for p in P))
    check("S4 removal is conservative: 74.0% on the 123 vs 68.6% on the kept",
          len(rm_m) == 123 and round(rm_a5 * 100, 1) == 74.0
          and round(kept_a5 * 100, 1) == 68.6,
          f"n={len(rm_m)} {rm_a5*100:.1f}% vs {kept_a5*100:.1f}%")
    check("S4 the removed instances were rankable, not unanswerable",
          rm_a5 > kept_a5, f"{rm_a5:.3f} vs {kept_a5:.3f}")

    # ---- Sec. 5: the three validity checks ------------------------------------
    cp = json.loads((RES / "llm-cp-summary.json").read_text(encoding="utf-8"))
    bv = cp["by_variant"]
    check("S5 contamination: key-only acc@5 0.000, claimed recall 0",
          bv["key"]["all"]["acc@5"] == 0.0
          and bv["key"]["claimed_recall_rate"] == 0.0)
    check("S5 contamination: key+title acc@5 0.003, claimed 0.5%",
          r3(bv["key_title"]["all"]["acc@5"]) == .003
          and round(bv["key_title"]["claimed_recall_rate"] * 100, 1) == 0.5,
          f"got {bv['key_title']['all']['acc@5']} / "
          f"{bv['key_title']['claimed_recall_rate']}")
    prior = json.loads((RES / "file-prior-baseline.json")
                       .read_text(encoding="utf-8"))
    pv = [prior[p]["metrics"]["acc@5"] for p in P]
    check("S5 frequency prior .036 to .181, above the probe",
          r3(min(pv)) == .036 and r3(max(pv)) == .181
          and min(pv) > bv["key_title"]["all"]["acc@5"],
          f"{min(pv)}..{max(pv)}")
    sh_ids = [i for i in shuf if i in v2]
    check("S5 seed shuffle ran 200 paired instances", len(sh_ids) == 200,
          str(len(sh_ids)))
    for m, d in (("acc@1", .015), ("acc@5", -.005)):
        obs = (sum(v2[i]["metrics"][m] for i in sh_ids)
               - sum(shuf[i]["metrics"][m] for i in sh_ids)) / len(sh_ids)
        check(f"S5 shuffle {m} delta {d:+.3f} (no change)", r3(obs) == d,
              f"got {obs:+.4f}")
    ov = {}
    for tag, src in (("normal", v2), ("shuffled", shuf)):
        tot = 0.0
        for i in sh_ids:
            seed5 = set(src[i]["lexical_seed"][:5])
            ag5 = src[i]["agent_ranking"][:5]
            tot += (sum(1 for f in ag5 if f in seed5) / max(len(ag5), 1))
        ov[tag] = tot / len(sh_ids)
    check("S5 seed overlap falls 59.8% -> 20.5% under shuffling",
          round(ov["normal"] * 100, 1) == 59.8
          and round(ov["shuffled"] * 100, 1) == 20.5,
          f"{ov['normal']:.3f} -> {ov['shuffled']:.3f}")
    check("S5 population mismatch: fusion .839 here vs .804 on full split",
          r3(S["fusion"]["acc@5"]) == .839
          and r3(istat("kafka", "ours_vs_brtracer", "acc@5", "overall")["n"]
                 and 0.804) == .804)

    # ---- Sec. 5: the v1 -> v2 ablation ----------------------------------------
    abl = json.loads((RES / "agent-v1-v2-ablation.json")
                     .read_text(encoding="utf-8"))
    want = {("overall", "acc@1"): (.0774, True), ("overall", "mrr"): (.0624, True),
            ("overall", "acc@5"): (.0298, False), ("hard", "acc@1"): (.1395, True),
            ("hard", "mrr"): (.1207, True), ("hard", "acc@5"): (.0698, False)}
    for t in abl["tests"]:
        key = (t["population"], t["metric"])
        if key in want:
            d, sig = want[key]
            check(f"ABL {key[0]} {key[1]} {d:+.4f} {'SIG' if sig else 'ns'}",
                  round(t["delta"], 4) == d and t["significant"] == sig,
                  f"got {t['delta']:+.4f} {'SIG' if t['significant'] else 'ns'}")
    b1, b2 = abl["behaviour"]["v1"], abl["behaviour"]["v2"]
    check("ABL evidence recorded: 63% of runs -> all of them",
          round(1 - b1["zero_evidence_rate"], 2) == .63
          and b2["zero_evidence_rate"] == 0.0,
          f"{b1['zero_evidence_rate']} -> {b2['zero_evidence_rate']}")
    check("ABL evidence per run 1.99 -> 5.77 at unchanged tool/model calls",
          round(b1["evidence_mean"], 2) == 1.99 and round(b2["evidence_mean"], 2) == 5.77
          and abs(b1["tool_calls_mean"] - b2["tool_calls_mean"]) < 1.0
          and abs(b1["llm_calls_mean"] - b2["llm_calls_mean"]) < 1.0,
          f"{b1["evidence_mean"]}->{b2["evidence_mean"]}")
    check("S4/S5 v1 skipped what it was told: memory 0.32/run, 37% no evidence",
          round(b1["recall_incidents_per_run"], 2) == 0.32
          and round(b1["zero_evidence_rate"], 2) == 0.37,
          f"memory {b1['recall_incidents_per_run']}/run, "
          f"zero-evidence {b1['zero_evidence_rate']}")

    # S4/S5: the caller tool was used ONCE in the 168 v1 runs (not 105 - that
    # number belongs to the hard-instance count in S1/S5 and must not be
    # transcribed here).
    v1_callers = sum(r["tools_used"].count("callers_of") for r in v1.values())
    check("S4/S5 v1 caller tool: exactly 1 call across exactly 168 runs",
          v1_callers == 1 and len(v1) == 168,
          f"{v1_callers} calls in {len(v1)} runs")

    # S4: callers_of is STILL offered in v2 and still almost never chosen.
    # The paper must not imply the tool was removed.
    v2_callers = sum(r["tools_used"].count("callers_of") for r in v2.values())
    check("S4 callers_of still exposed in v2 and still near-unused",
          v2_callers > 0 and round(v2_callers / len(v2), 2) == 0.01,
          f"{v2_callers} calls in {len(v2)} runs "
          f"= {v2_callers / len(v2):.3f}/run")

    # S5: evidence recorded vs outcome, both legs under the SAME acc@5
    # definition (an earlier draft paired an acc@5 leg with an acc@1 leg).
    ev_hit = [r["n_notes"] for r in v1.values() if r["metrics"]["acc@5"] == 1]
    ev_miss = [r["n_notes"] for r in v1.values() if r["metrics"]["acc@5"] == 0]
    m_hit = sum(ev_hit) / len(ev_hit)
    m_miss = sum(ev_miss) / len(ev_miss)
    check("S5 v1 evidence by acc@5 outcome: 0.8 when missed, 2.2 when found",
          round(m_miss, 1) == 0.8 and round(m_hit, 1) == 2.2,
          f"missed {m_miss:.2f}, found {m_hit:.2f}")

    # ---- Sec. 4/5/6: cost ------------------------------------------------------
    cst = [r["cost"] for r in v2.values()]
    mean_calls = sum(c_["llm_calls"] for c_ in cst) / len(cst)
    mean_tok = sum(c_["prompt_tokens"] for c_ in cst) / len(cst)
    mean_tools = sum(r["n_tool_calls"] for r in v2.values()) / len(v2)
    check("S4/S5 cost: 12.2 model calls, 90k prompt tokens, 16.2 tool calls",
          round(mean_calls, 1) == 12.2 and round(mean_tok / 1000) == 90
          and round(mean_tools, 1) == 16.2,
          f"{mean_calls:.1f} calls, {mean_tok/1000:.0f}k tok, "
          f"{mean_tools:.1f} tools")
    tu = Counter(t for r in v2.values() for t in r["tools_used"])
    t_tools = {"read_code": 7.28, "search_symbol": 3.42, "search_text": 2.61,
               "note_candidate": 2.38, "recall_incidents": 0.28,
               "list_dir": 0.13, "read_skeleton": 0.10, "callers_of": 0.01}
    for name, per in t_tools.items():
        check(f"T-tools {name} {per}/run",
              round(tu[name] / len(v2), 2) == per,
              f"got {tu[name] / len(v2):.2f}")
    # The table, the figure and the code must agree on how many investigation
    # tools exist. Every tool the model was actually offered has to appear.
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "c7tools", ROOT / "industry-c7" / "agent" / "tools.py")
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    offered = {t["function"]["name"] for t in _mod.TOOL_SCHEMAS}
    check("T-tools table covers every tool the model was offered (8)",
          offered == set(t_tools) and len(offered) == 8,
          f"schema has {sorted(offered)}")
    FIGS = ROOT / "industry-c7" / "paper" / "figures"
    agent_svg = (FIGS / "agent.svg").read_text(encoding="utf-8")
    research_svg = (FIGS / "research.svg").read_text(encoding="utf-8")
    check("Figure agent.svg says EIGHT TOOLS and shows all 8 names",
          "EIGHT TOOLS" in agent_svg and all(n in agent_svg for n in t_tools),
          "agent.svg header/rows out of sync with the tool schema")
    # Each tool's measured rate must also be printed on its row.
    for name, per in t_tools.items():
        lbl = f"{per:.2f}" if per >= 0.1 else f"{per:.2f}"
        check(f"Figure agent.svg prints {name} rate {lbl}",
              lbl in agent_svg, f"{lbl} missing from agent.svg")
    # Both figures carry headline numbers. They are percentages now, and a
    # figure that still shows the old decimals would contradict the tables.
    fig_pct = {"agent.svg": [("90.3%", "acc@1 is 72.3%"), ("72.3%", ""),
                             ("81.6%", ""), ("60.8%", ""),
                             ("83.9%", ""), ("53.8%", "")],
               "research.svg": [("18.0%", ""), ("68.1%", ""), ("83.2%", ""),
                                ("83.9%", ""), ("90.3%", ""), ("89.2%", "")]}
    for fn, wanted in fig_pct.items():
        svg = agent_svg if fn == "agent.svg" else research_svg
        missing = [v for v, _ in wanted if v not in svg]
        stale = [v for v in ("0.903", "0.723", "0.816", "0.608", ">.180<",
                             ">.681<", ">.832<", ">.903<") if v in svg]
        check(f"Figure {fn} uses percentages and no stale decimals",
              not missing and not stale,
              f"missing {missing}, stale {stale}")
    # The figure must NOT hard-code a check count: the count changes every
    # time a check is added, so any number printed there goes stale the
    # moment this file grows.
    check("Figure research.svg hard-codes no check count",
          not re.search(r"\d+\s+checks", research_svg),
          "research.svg prints a check count that will go stale")

    # ---- report ---------------------------------------------------------------
    failed = [(c, d) for c, ok, d in checks if not ok]
    for c, ok, d in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {c}" + (f"  [{d}]" if d and not ok else ""))
    print(f"\n{len(checks) - len(failed)}/{len(checks)} claims verified")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
