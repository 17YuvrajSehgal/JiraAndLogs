"""Trace every number in the Challenge #7 paper to a result file.

Three kinds of check, each printed as PASS or FAIL with what was found:

  macros   every numeric \\newcommand in paper/main.tex against the file
           it is documented to come from
  tables   paper/tables/*.tex are byte-identical to a fresh run of
           paper_tables.py on the same rows (skip with --no-regen)
  text     the percentages and paired intervals quoted in the sections

Sources: data/results/c7-coverage-wf-seed42.json (wf paired with the
free loop), data/results/paper-numbers.json (pooled retrieval, function,
dense and per-project numbers), data/results/agentic-baselines.json,
paper/tables/sources.json, data/llm-27/results/llm-cp-summary.json,
paper/benchmark-numbers.md, data/benchmark/*-memory.jsonl and
data/results/*-summary.json.

Usage (from the repository root):
    python industry-c7/scripts/verify_paper.py --wf <rows> --loop <rows> [--no-regen]
"""
from __future__ import annotations

import argparse
import filecmp
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PAPER, RES = ROOT / "paper", ROOT / "data/results"
SEC = PAPER / "sections"

n_pass = n_fail = 0


def check(name: str, ok: bool, found="") -> None:
    global n_pass, n_fail
    n_pass += ok
    n_fail += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  [{found}]"))


def num(s: str) -> float:
    return float(re.sub(r"[{},\\% ]", "", s))


def tex(name: str) -> str:
    return (SEC / f"{name}.tex").read_text(encoding="utf-8")


def flat(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def has(name: str, needle: str, where: str) -> None:
    """The needle must occur in the section, with line breaks read as spaces."""
    check(f"{where}: {flat(needle)}", flat(needle) in flat(tex(where)), "not found")


def pm(x: float, k: int = 1) -> str:
    """+/-x.x in points, the way the sections print paired differences."""
    return f"{100 * x:+.{k}f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wf", required=True)
    ap.add_argument("--loop", required=True)
    ap.add_argument("--no-regen", action="store_true")
    a = ap.parse_args()

    main_tex = (PAPER / "main.tex").read_text(encoding="utf-8")
    M = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*(?:\{,\}[^}]*)*)\\xspace\}", main_tex))
    COV = json.loads((RES / "c7-coverage-wf-seed42.json").read_text(encoding="utf-8"))
    PN = json.loads((RES / "paper-numbers.json").read_text(encoding="utf-8"))
    AB = json.loads((RES / "agentic-baselines.json").read_text(encoding="utf-8"))
    SRC = json.loads((PAPER / "tables/sources.json").read_text(encoding="utf-8"))
    CP = json.loads((ROOT / "data/llm-27/results/llm-cp-summary.json").read_text(encoding="utf-8"))
    BN = (PAPER / "benchmark-numbers.md").read_text(encoding="utf-8")
    S, SW, SL, H = COV["summary"], COV["summary_run_paired"], COV["summary_base_paired"], COV["health"]
    n_eval = PN["retrieval_pooled"]["cond_ours"]["all"]["n"]
    scale = S["all"]["n"] / n_eval          # scored rows -> full population (misses count as 0)
    hard = PN["wf_by_difficulty"]["hard"]
    hscale = hard["n"] / PN["retrieval_pooled"]["cond_ours"]["hard"]["n"]

    # ---- macros -------------------------------------------------------------
    print("== macros (paper/main.tex)")
    bn = lambda pat: num(re.search(pat, BN).group(1))  # noqa: E731
    check("nInstances = final instances in benchmark-numbers.md",
          num(M["nInstances"]) == bn(r"\*\*= final instances\*\* \| \*\*([\d,]+)\*\*"), M["nInstances"])
    check("nScored = scored instances", num(M["nScored"]) == bn(r"\*\*= scored instances\*\* \| \*\*([\d,]+)\*\*"), M["nScored"])
    check("nProjects = number of <p>-instances.jsonl", num(M["nProjects"]) == len(glob.glob(str(RES / "*-instances.jsonl"))), M["nProjects"])
    check("nHardPct = benchmark-wide hard share", num(M["nHardPct"]) == bn(r"hard \(report names no gold file\) \| 53% \| \*\*(\d+)%\*\*"), M["nHardPct"])
    pool = sum(1 for f in glob.glob(str(ROOT / "data/benchmark/*-memory.jsonl"))
               for l in open(f, encoding="utf-8") if l.strip())
    check("nMemoryPool = entries in data/benchmark/*-memory.jsonl", num(M["nMemoryPool"]) == pool, f"{pool}")
    check("nEval = evaluation-split rows", num(M["nEval"]) == n_eval, n_eval)
    check("nEvalHard", num(M["nEvalHard"]) == PN["retrieval_pooled"]["cond_ours"]["hard"]["n"], M["nEvalHard"])
    exp = lambda v, k=1: round(100 * v, k)  # noqa: E731
    check("accOne = wf file Acc@1 on all 26,544 (misses as 0)", num(M["accOne"]) == exp(S["all"]["file_acc@1"] * scale), exp(S["all"]["file_acc@1"] * scale))
    check("accFive", num(M["accFive"]) == exp(S["all"]["file_acc@5"] * scale), exp(S["all"]["file_acc@5"] * scale))
    check("mrr", num(M["mrr"]) == round(S["all"]["file_mrr"] * scale, 3), round(S["all"]["file_mrr"] * scale, 3))
    check("hardOne", num(M["hardOne"]) == exp(hard["file_acc@1"] * hscale), exp(hard["file_acc@1"] * hscale))
    check("hardFive", num(M["hardFive"]) == exp(hard["file_acc@5"] * hscale), exp(hard["file_acc@5"] * hscale))
    check("modOne = module named by the agent", num(M["modOne"]) == exp(S["all"]["module_agent_acc@1"] * scale), exp(S["all"]["module_agent_acc@1"] * scale))
    check("nRegion", num(M["nRegion"]) == S["all"]["n_region_eligible"], S["all"]["n_region_eligible"])
    check("regOne", num(M["regOne"]) == exp(S["all"]["region_acc@1"]), exp(S["all"]["region_acc@1"]))
    check("regFive", num(M["regFive"]) == exp(S["all"]["region_acc@5"]), exp(S["all"]["region_acc@5"]))
    rp = PN["retrieval_pooled"]["cond_ours"]
    check("retrOne", num(M["retrOne"]) == exp(rp["all"]["acc@1"]), exp(rp["all"]["acc@1"]))
    check("retrFive", num(M["retrFive"]) == exp(rp["all"]["acc@5"]), exp(rp["all"]["acc@5"]))
    check("retrHardFive", num(M["retrHardFive"]) == exp(rp["hard"]["acc@5"]), exp(rp["hard"]["acc@5"]))
    check("loopOne = free loop on the paired rows", num(M["loopOne"]) == exp(SL["all"]["file_acc@1"]), exp(SL["all"]["file_acc@1"]))
    check("loopFive", num(M["loopFive"]) == exp(SL["all"]["file_acc@5"]), exp(SL["all"]["file_acc@5"]))
    check("loopRegOne", num(M["loopRegOne"]) == exp(SL["all"]["region_acc@1"]), exp(SL["all"]["region_acc@1"]))
    check("loopRegFive", num(M["loopRegFive"]) == exp(SL["all"]["region_acc@5"]), exp(SL["all"]["region_acc@5"]))
    check("calls = mean model calls per wf run", num(M["calls"]) == round(H["llm_calls"], 1), round(H["llm_calls"], 1))
    check("tokens = mean prompt tokens per wf run", M["tokens"].strip() == f"{round(H['prompt_tokens'] / 1000)}k", M["tokens"])
    check("nSample", num(M["nSample"]) == AB["n_common"], AB["n_common"])
    check("nSampleHard", num(M["nSampleHard"]) == AB["n_hard"], AB["n_hard"])
    votes = {}
    for f in glob.glob(str(RES / "*-summary.json")):
        b = os.path.basename(f)
        if any(x in b for x in ("dense", "functions", "irbl", "noise", "agent", "llm")):
            continue
        for k, v in json.loads(Path(f).read_text(encoding="utf-8")).get("memory_vote_stats", {}).items():
            votes[k] = votes.get(k, 0) + v
    fw = round(100 * votes["bm25_fw_resolved_later"] / sum(votes.values()))
    check("firewallPct = votes removed by the future-reports rule, pooled", num(M["firewallPct"]) == fw, fw)
    MM = json.loads((RES / "module-metrics.json").read_text(encoding="utf-8"))
    tot = sum(d["systems"]["cond_ours"]["acc@1"] * d["n_eval"] for p, d in MM.items() if not p.startswith("_"))
    nn = sum(d["n_eval"] for p, d in MM.items() if not p.startswith("_"))
    check("moduleRetr = retrieval layer module Acc@1 pooled", num(M["moduleRetr"]) == exp(tot / nn), exp(tot / nn))
    MB = json.loads((RES / "module-baselines.json").read_text(encoding="utf-8"))
    mps = [p for p in MB if not p.startswith("_")]
    nb = sum(MB[p]["n_eval"] for p in mps)
    freq = sum(MB[p]["most_frequent_live"]["acc@1"] * MB[p]["n_eval"] for p in mps) / nb
    check("moduleFreq = development-split frequency prior (live modules) pooled over 27 projects",
          len(mps) == 27 and num(M["moduleFreq"]) == exp(freq), f"{len(mps)} projects, {exp(freq)}")
    check("05-results: agent's margin over the module prior is 41 points",
          "margin over that prior, 41 points" in tex("05-results") and round(num(M["modOne"]) - num(M["moduleFreq"])) == 41,
          round(num(M["modOne"]) - num(M["moduleFreq"]), 1))

    # ---- tables -------------------------------------------------------------
    print("== tables (paper/tables/*.tex vs a fresh paper_tables.py run)")
    if a.no_regen:
        print("SKIP  --no-regen")
    else:
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, C7_TABLES_OUT=td)
            r = subprocess.run([sys.executable, str(HERE / "paper_tables.py"), "--wf", a.wf, "--loop", a.loop],
                               env=env, capture_output=True, text=True)
            check("paper_tables.py runs", r.returncode == 0, r.stderr[-300:])
            for f in ("all", "ablation", "retrieval", "functions", "modules"):
                same = filecmp.cmp(Path(td) / f"{f}.tex", PAPER / "tables" / f"{f}.tex", shallow=False)
                check(f"tables/{f}.tex is what the result files give", same, "differs: rerun paper_tables.py")

    # ---- text ---------------------------------------------------------------
    print("== text")
    P = SRC["headline"]["paired_wf_minus_loop"]
    iv = lambda d: f"$[{pm(d['lo'])}, {pm(d['hi'])}]$"  # noqa: E731
    has("05-results", f"${pm(P['all:file_acc@1']['delta'])}$ points {iv(P['all:file_acc@1'])}", "05-results")
    has("05-results", f"${pm(P['all:file_acc@5']['delta'])}$ {iv(P['all:file_acc@5'])}", "05-results")
    has("05-results", f"${pm(P['all:region_acc@1']['delta'])}$ points {iv(P['all:region_acc@1'])}", "05-results")
    has("05-results", f"${pm(P['all:region_acc@5']['delta'])}$ {iv(P['all:region_acc@5'])}", "05-results")
    has("05-results", f"${abs(100 * P['hard:file_acc@1']['delta']):.1f}$ points below the loop at Acc@1 {iv(P['hard:file_acc@1'])}", "05-results")
    has("05-results", f"${abs(100 * P['hard:file_acc@5']['delta']):.1f}$ below at Acc@5 {iv(P['hard:file_acc@5'])}", "05-results")
    has("05-results", f"${pm(P['hard:region_acc@1']['delta'])}$ {iv(P['hard:region_acc@1'])}", "05-results")
    has("05-results", f"${pm(P['hard:region_acc@5']['delta'])}$ {iv(P['hard:region_acc@5'])}", "05-results")
    B = COV["paired_run_minus_base"]
    for key, label in (("trace_file_acc@1", "trace"), ("logs_no_trace_file_acc@1", "logs"), ("prose_file_acc@1", "prose")):
        d, lo, hi = B[key][:3]
        has("05-results", f"${pm(d)}$ $[{pm(lo)}, {pm(hi)}]$", "05-results")
    for st_, key in (("trace", "trace"), ("logs_no_trace", "logs_no_trace"), ("prose", "prose")):
        has("05-results", f"{exp(S[st_]['file_acc@1'])}\\%", "05-results")
    has("05-results", f"{exp(S['all']['steps_citing_log'])}\\% of chain steps", "05-results")
    has("05-results", f"{exp(S['all']['log_cites_grounded'])}\\% of those", "05-results")
    pp = PN["per_project"]
    lo_p = min(pp, key=lambda p: pp[p]["wf_acc@1"]); hi_p = max(pp, key=lambda p: pp[p]["wf_acc@1"])
    has("05-results", f"{exp(pp[lo_p]['wf_acc@1'])}\\% ({lo_p.capitalize()})", "05-results")
    has("05-results", f"{exp(pp[hi_p]['wf_acc@1'])}\\% ({hi_p.capitalize()})", "05-results")
    ps = sorted(pp)
    rk = lambda key: {p: i for i, p in enumerate(sorted(ps, key=lambda q: -pp[q][key]))}  # noqa: E731
    rw, rl = rk("wf_acc@1"), rk("lexical_acc@1")
    rho = 1 - 6 * sum((rw[p] - rl[p]) ** 2 for p in ps) / (len(ps) * (len(ps) ** 2 - 1))
    has("05-results", f"Spearman $\\rho = {rho:.2f}$", "05-results")
    lo_h = min(pp, key=lambda p: pp[p]["hard_share"]); hi_h = max(pp, key=lambda p: pp[p]["hard_share"])
    has("02-benchmark", f"{round(100 * pp[lo_h]['hard_share'])}\\% ({'PDFBox' if lo_h == 'pdfbox' else lo_h.capitalize()}", "02-benchmark")
    has("02-benchmark", f"{round(100 * pp[hi_h]['hard_share'])}\\% ({hi_h.capitalize()})", "02-benchmark")
    V = AB["vs_ours"]
    f3 = lambda x: f"{x:+.3f}"  # noqa: E731
    la = V["locagent"]
    has("05-results", f"${f3(la['all']['acc@1']['delta'])}$ Acc@1\n$[{f3(la['all']['acc@1']['lo'])}, {f3(la['all']['acc@1']['hi'])}]$", "05-results")
    has("05-results", f"${f3(la['all']['acc@5']['delta'])}$ Acc@5 $[{f3(la['all']['acc@5']['lo'])}, {f3(la['all']['acc@5']['hi'])}]$", "05-results")
    has("05-results", f"${f3(la['hard']['acc@1']['delta'])}$ $[{f3(la['hard']['acc@1']['lo'])}, {f3(la['hard']['acc@1']['hi'])}]$", "05-results")
    has("05-results", f"${f3(la['hard']['acc@5']['delta'])}$ $[{f3(la['hard']['acc@5']['lo'])}, {f3(la['hard']['acc@5']['hi'])}]$", "05-results")
    co = V["cosil"]
    has("05-results", f"${f3(co['all']['acc@1']['delta'])}$ and\n${f3(co['all']['acc@5']['delta'])}$ overall and ${f3(co['hard']['acc@1']['delta'])}$\nand ${f3(co['hard']['acc@5']['delta'])}$ on the hard stratum", "05-results")
    E = SRC["agents"]["extra"]
    al, rr = E["llm_alone"], E["llm_rerank"]
    has("05-results", f"${f3(al['vs_wf_acc@1'][0])}$ Acc@1 $[{f3(al['vs_wf_acc@1'][1])}, {f3(al['vs_wf_acc@1'][2])}]$", "05-results")
    has("05-results", f"${f3(al['vs_wf_acc@5'][0])}$ Acc@5\n$[{f3(al['vs_wf_acc@5'][1])}, {f3(al['vs_wf_acc@5'][2])}]$", "05-results")
    has("05-results", f"${f3(rr['vs_wf_acc@1'][0])}$ $[{f3(rr['vs_wf_acc@1'][1])}, {f3(rr['vs_wf_acc@1'][2])}]$ and ${f3(rr['vs_wf_acc@5'][0])}$ $[{f3(rr['vs_wf_acc@5'][1])}, {f3(rr['vs_wf_acc@5'][2])}]$", "05-results")
    has("05-results", f"reaches {rr['acc@1']:.3f} Acc@1", "05-results")
    has("05-results", f"falls to {rr['hard_acc@1']:.3f} against\n\\sys{{}}'s {AB['systems']['ours']['hard_acc@1']:.3f}", "05-results")
    tc = AB["systems"]["locagent"]["tool_calls_per_run"]
    has("05-results", f"traversal tool {tc['traverse_graph']:.2f} times per run against {tc['search_entity']:.1f} keyword", "05-results")
    has("05-results", f"(LocAgent-style {100 * AB['systems']['locagent']['empty_rate']:.1f}\\%, CoSIL-style\n{100 * AB['systems']['cosil']['empty_rate']:.1f}\\%)", "05-results")
    cp = CP["by_variant"]
    has("05-results", f"scored {exp(cp['key']['all']['acc@5'])}\\% Acc@5", "05-results")
    has("05-results", f"claimed recall for {exp(cp['key_title']['claimed_recall_rate'])}\\% of instances and scored\n{exp(cp['key_title']['all']['acc@5'])}\\%", "05-results")
    R = PN["retrieval_pooled"]
    has("05-results", f"({exp(R['memory_bm25']['easy']['acc@5'])}\\% against {exp(R['memory_bm25']['hard']['acc@5'])}\\% Acc@5)", "05-results")
    has("05-results", f"from {exp(R['fused_no_memory']['hard']['acc@5'])}\\% to {exp(R['fused_ours']['hard']['acc@5'])}\\%", "05-results")
    has("05-results", f"from {exp(R['cond_no_memory']['hard']['acc@5'])}\\% to {exp(R['cond_ours']['hard']['acc@5'])}\\%", "05-results")
    F = PN["functions_pooled"]
    has("05-results", f"{exp(F['eligible_fraction_all_rows'])}\\% of instances yield", "05-results")
    has("05-results", f"reaches {exp(F['eval_eligible']['acc@1'])}\\%\nAcc@1 with a {exp(F['oracle_in_candidates'])}\\% ceiling", "05-results")
    has("05-results", f"{exp(hard['region_acc@1'])}\\% region Acc@1 and {exp(hard['region_acc@5'])}\\% Acc@5", "05-results")
    easy = PN["wf_by_difficulty"]["easy"]
    has("05-results", f"({exp(hard['module_agent_acc@1'])}\\% hard, {exp(easy['module_agent_acc@1'])}\\% easy)", "05-results")
    has("05-results", f"top-ranked file is correct for {exp(SW['all']['module_from_ranking_acc@1'])}\\%", "05-results")
    D, Wd = PN["dense_pooled"], PN["dense_wins_of_27"]
    has("05-results", f"({exp(D['content_bm25']['acc@5'])}\\% to {exp(D['content_dense']['acc@5'])}\\% mean Acc@5)", "05-results")
    has("05-results", f"wins on {Wd['s4_dense_beats_bm25']} of\n27 projects ({exp(D['memory_bm25']['acc@5'])}\\% to {exp(D['memory_dense']['acc@5'])}\\%)", "05-results")
    has("05-results", f"from {exp(D['cond_ours']['acc@5'])}\\% to\n{exp(D['cond_dense_s4']['acc@5'])}\\%", "05-results")
    has("05-results", f"{round(H['wall_s'])} seconds of wall time", "05-results")
    meds = [json.loads(Path(f).read_text(encoding="utf-8")).get("latency", {}).get("per_issue_median_s")
            for f in glob.glob(str(RES / "*-summary.json"))
            if not any(x in os.path.basename(f) for x in ("dense", "functions", "irbl", "noise", "agent", "llm"))]
    meds = [m for m in meds if m is not None]
    check("05-results: retrieval latency 'median of under 0.2 seconds' holds on every project",
          "under 0.2 seconds per issue on every project" in tex("05-results") and max(meds) < 0.2,
          f"medians {min(meds):.3f}..{max(meds):.3f}")
    has("05-results", f"against the loop's {H.get('llm_calls_loop', COV['health_base']['llm_calls']):.1f} and {round(COV['health_base']['prompt_tokens'] / 1000)}k", "05-results")
    for n_ in ("70{,}999", "18{,}661", "14{,}207", "$-$55", "$-$75", "$-$101", "37\\%", "30\\%", "85\\%"):
        plain = n_.replace("{,}", ",").replace("$-$", "-").replace("\\%", "%")
        check(f"02-benchmark funnel: {plain} is in benchmark-numbers.md", n_ in tex("02-benchmark") and plain.lstrip("-") in BN, plain)
    # median / p95 pairs come from the distribution table of benchmark-numbers.md
    check("02-benchmark: query length 902 / 6,577 (median / p95)",
          "902 / 6{,}577" in tex("02-benchmark") and "| query characters | 902 | 6,577 |" in BN, "")
    check("02-benchmark: gold files per instance 1 / 8 (median / p95)",
          "1 / 8" in tex("02-benchmark") and "| gold files per instance | 1 | 8 |" in BN, "")
    # run-to-run variation: the same 20 instances, same seed, run twice on
    # the cloud VM (check20, check20b) and once on the clusters (t07 rows)
    def rows_of(path):
        out = {}
        for line in Path(path).open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                out[r["id"]] = r
        return out
    V1 = rows_of(ROOT / "data/agent/vm/check20/agent-vm-check20.jsonl")
    V2 = rows_of(ROOT / "data/agent/vm/check20/agent-vm-check20b.jsonl")
    CL = {i: r for i, r in rows_of(ROOT / "data/agent/cluster/agent-wf-t07.jsonl").items() if i in V1}
    ids = sorted(set(V1) & set(V2) & set(CL))

    def agree(A, B, k):
        return sum(A[i]["ranking"][:k] == B[i]["ranking"][:k] for i in ids)
    same_mod = {n: sum(A[i].get("module") == B[i].get("module") for i in ids)
                for n, (A, B) in (("vm-vm", (V1, V2)), ("vm1-cluster", (V1, CL)), ("vm2-cluster", (V2, CL)))}
    acc1 = sorted(round(sum(R[i]["metrics"]["acc@1"] for i in ids) / len(ids), 2) for R in (V1, V2, CL))
    check("variation: 20 instances with all three runs", len(ids) == 20, len(ids))
    check("variation: same machine, top file agreed on 18", agree(V1, V2, 1) == 18, agree(V1, V2, 1))
    check("variation: same machine, top ten agreed on 12", agree(V1, V2, 10) == 12, agree(V1, V2, 10))
    cross = sorted((agree(V1, CL, 1), agree(V2, CL, 1)))
    check("variation: across machines, top file agreed on 14 to 15", cross == [14, 15], cross)
    check("variation: module agreed on all 20 in every pair", all(v == 20 for v in same_mod.values()), same_mod)
    check("variation: Acc@1 between 0.65 and 0.70", (acc1[0], acc1[-1]) == (0.65, 0.70), acc1)
    check("06-discussion: 'agrees across repeats in 70% to 90% of cases'", "70\\% to 90\\%" in tex("06-discussion")
          and (min(cross), agree(V1, V2, 1)) == (14, 18), "")

    print(f"\n{n_pass} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
