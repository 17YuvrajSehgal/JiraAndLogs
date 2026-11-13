"""Build the LaTeX table bodies of the Challenge #7 paper from result files.

Nothing in paper/tables/ is typed by hand. Each table names its sources.

  headline.tex   wf vs the free-loop agent vs the retrieval layer on the
                 full evaluation split (file, module, region, cost)
  agents.tex     wf vs LocAgent-style, CoSIL-style and, when their scored
                 rows exist, the model alone and the model re-ranker, on
                 the 1,000-instance sample, with paired bootstrap intervals
  retrieval.tex  the retrieval layer's signals pooled over 27 projects
  functions.tex  function level: BM25 stage vs the two agents
  modules.tex    module level with the random / frequency sanity baselines

Usage:
    python industry-c7/scripts/paper_tables.py --wf <rows> --loop <rows>
Rows files: one row per instance (c7_coverage.load_rows drops dead rows).
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "agent"))
import c7_coverage as CC  # noqa: E402

import os  # noqa: E402

ROOT = HERE.parent
RES = ROOT / "data/results"
# verify_paper.py regenerates the tables into a scratch directory and diffs
TAB = Path(os.environ.get("C7_TABLES_OUT") or ROOT / "paper/tables")
TMP = RES   # paper-numbers.json lives with the other result files
SEED, N_BOOT = 20261104, 2000


def pct(x, d=1):
    return "--" if x is None else f"{100 * x:.{d}f}"


def boot(diff, k):
    rs = random.Random(SEED + k)
    n = len(diff)
    s = sorted(st.fmean(diff[rs.randrange(n)] for _ in range(n)) for _ in range(N_BOOT))
    return st.fmean(diff), s[int(.025 * N_BOOT)], s[int(.975 * N_BOOT)]


def strata(rows):
    return {"all": set(rows), "hard": {i for i, r in rows.items() if r.get("hard")},
            "easy": {i for i, r in rows.items() if not r.get("hard")}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wf", required=True)
    ap.add_argument("--loop", required=True)
    a = ap.parse_args()
    TAB.mkdir(exist_ok=True)
    src = {}

    wf, lp = CC.load_rows(Path(a.wf)), CC.load_rows(Path(a.loop))
    ids = sorted(set(wf) & set(lp))
    print(f"wf {len(wf)} rows, free loop {len(lp)} rows, paired {len(ids)}")
    s_wf = {i: CC.score_row(wf[i]) for i in wf}
    s_lp = {i: CC.score_row(lp[i]) for i in lp}
    S_wf, S_lp = strata(wf), strata(lp)

    def summ(sc, keep):
        return CC.summarise({i: s for i, s in sc.items() if i in keep})["all"]

    W = {k: summ(s_wf, v) for k, v in S_wf.items()}
    L = {k: summ(s_lp, v) for k, v in S_lp.items()}
    # the retrieval layer on the identical instances (metrics_lexical)
    R = {}
    for k, keep in S_wf.items():
        rs = [wf[i]["metrics_lexical"] for i in keep]
        R[k] = {f"file_acc@{j}": st.fmean(r[f"acc@{j}"] for r in rs) for j in (1, 5)}
        R[k]["file_mrr"] = st.fmean(r["mrr"] for r in rs)
        R[k]["n"] = len(rs)
    cost = lambda rows: (st.fmean(r["cost"]["llm_calls"] for r in rows.values()),  # noqa: E731
                         st.fmean(r["cost"]["prompt_tokens"] for r in rows.values()) / 1000)
    cw, cl = cost(wf), cost(lp)
    src["headline"] = {"wf": a.wf, "loop": a.loop, "n_wf": len(wf), "n_loop": len(lp),
                       "W": W, "L": L, "R": R, "cost_wf": cw, "cost_loop": cl}

    def row(name, d, mod, reg, c):
        return (f"{name} & {pct(d['all']['file_acc@1'])} & {pct(d['all']['file_acc@5'])} & "
                f"{d['all']['file_mrr']:.3f} & {pct(d['hard']['file_acc@1'])} & {pct(d['hard']['file_acc@5'])} & "
                f"{mod} & {reg} & {c} \\\\")
    regs = lambda d: f"{pct(d['all']['region_acc@1'])} / {pct(d['all']['region_acc@5'])}"  # noqa: E731
    body = [
        row("retrieval layer (no model)", R, "--", "--", "0 / 0"),
        row("unconstrained loop (ablation)", L, pct(L["all"]["module_from_ranking_acc@1"]), regs(L),
            f"{cl[0]:.1f} / {cl[1]:.0f}k"),
        row("\\sys{} (staged workflow)", W, pct(W["all"]["module_agent_acc@1"]), regs(W),
            f"{cw[0]:.1f} / {cw[1]:.0f}k"),
    ]
    (TAB / "headline.tex").write_text("\n".join(body) + "\n", encoding="utf-8", newline="\n")

    # paired wf minus free loop, file and region, all / hard
    pair = {}
    for k in ("all", "hard"):
        keep = [i for i in ids if i in S_wf[k]]
        for grp, m in (("file", "acc@1"), ("file", "acc@5"), ("region", "acc@1"), ("region", "acc@5")):
            ok = [i for i in keep if grp in s_wf[i] and grp in s_lp[i]]
            d, lo, hi = boot([s_wf[i][grp][m] - s_lp[i][grp][m] for i in ok], (len(grp) * 7 + int(m[-1])) % 97)
            pair[f"{k}:{grp}_{m}"] = {"delta": round(d, 4), "lo": round(lo, 4), "hi": round(hi, 4), "n": len(ok)}
    src["headline"]["paired_wf_minus_loop"] = pair
    for d, sc in ((W, s_wf), (L, s_lp)):   # region Acc@10, which summarise() leaves out
        reg = [s["region"]["acc@10"] for s in sc.values() if "region" in s]
        d["all"]["region_acc@10"] = st.fmean(reg)

    # ---- agents on the 1,000 sample ---------------------------------------
    AB = json.loads((RES / "agentic-baselines.json").read_text(encoding="utf-8"))
    sample = set(json.loads((RES / "baseline-sample.json").read_text(encoding="utf-8"))["ids"])
    sw = {i: wf[i] for i in wf if i in sample}
    hard = {i for i in sw if sw[i].get("hard")}

    def arm_rows(path):
        out = {}
        for line in Path(path).open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("is_eval", True) and not r.get("variant") and r["id"] in sample:
                out[r["id"]] = r
        return out

    extra = {}
    for key, name, fn in (("llm_alone", "model alone", "scored-a2.jsonl"),
                          ("llm_rerank", "model as re-ranker", "scored-rr.jsonl")):
        # only the 27-project run (data/llm-27). data/llm holds the old
        # 4-project rows, which overlap the sample on 36 ids and must never
        # be mixed in.
        cand = ROOT / "data/llm-27" / fn
        if cand.exists():
            extra[key] = (name, arm_rows(cand), str(cand))

    def paired_vs_wf(d, keys, k):
        diff = [sw[i]["metrics"][f"acc@{k}"] - d[i]["metrics"][f"acc@{k}"] for i in keys]
        return boot(diff, k) if diff else (None, None, None)

    lines, src["agents"] = [], {"file": str(RES / "agentic-baselines.json"), "extra": {}}
    sysr = AB["systems"]["ours"]
    # seven columns; the paired intervals go in the text, from sources.json
    lines.append(f"\\sys{{}} & {sysr['acc@1']:.3f} & {sysr['acc@5']:.3f} & {sysr['hard_acc@1']:.3f} & "
                 f"{sysr['hard_acc@5']:.3f} & {sysr['llm_calls']:.1f} & {sysr['prompt_tokens'] / 1000:.0f}k \\\\")
    for key, name in (("locagent", "LocAgent-style"), ("cosil", "CoSIL-style")):
        e = AB["systems"][key]
        lines.append(f"{name} & {e['acc@1']:.3f} & {e['acc@5']:.3f} & {e['hard_acc@1']:.3f} & {e['hard_acc@5']:.3f} & "
                     f"{e['llm_calls']:.1f} & {e['prompt_tokens'] / 1000:.0f}k \\\\")
    for key, (name, d, path) in extra.items():
        common = sorted(set(d) & set(sw))
        acc = lambda keys, k: st.fmean(d[i]["metrics"][f"acc@{k}"] for i in keys)  # noqa: E731
        hk = [i for i in common if i in hard]
        delta = paired_vs_wf(d, common, 1)
        calls = 2.0 if key == "llm_alone" else 1.0
        # prompt tokens per issue from the raw responses: both Agentless
        # stages for the model alone, the one re-rank call otherwise
        toks = 0.0
        for stage in (("a1", "a2") if key == "llm_alone" else ("rr",)):
            us = [json.loads(l).get("usage") or {} for l in (ROOT / "data/llm-27" / f"resp-{stage}.jsonl").open(encoding="utf-8")]
            toks += st.fmean(u.get("prompt_tokens", 0) for u in us) / 1000
        lines.append(f"{name} & {acc(common, 1):.3f} & {acc(common, 5):.3f} & {acc(hk, 1):.3f} & {acc(hk, 5):.3f} & "
                     f"{calls:.1f} & {toks:.0f}k \\\\")
        src["agents"]["extra"][key] = {"file": path, "n": len(common), "n_hard": len(hk),
                                       "acc@1": round(acc(common, 1), 4), "acc@5": round(acc(common, 5), 4),
                                       "hard_acc@1": round(acc(hk, 1), 4), "hard_acc@5": round(acc(hk, 5), 4),
                                       "vs_wf_acc@1": [round(x, 4) for x in delta],
                                       "vs_wf_acc@5": [round(x, 4) for x in paired_vs_wf(d, common, 5)]}
    (TAB / "agents.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    # ---- retrieval signals pooled -------------------------------------------
    PN = json.loads((TMP / "paper-numbers.json").read_text(encoding="utf-8"))
    rp = PN["retrieval_pooled"]
    order = [("trace_grep", "S1 trace mentions"), ("path_bm25", "S2 path BM25"),
             ("content_bm25", "S3 content BM25"), ("memory_bm25", "S4 incident memory"),
             ("fused_no_memory", "fusion, no memory"), ("fused_ours", "fusion + memory"),
             ("cond_no_memory", "cond., no memory"), ("cond_ours", "cond.\\,+\\,memory (the layer)")]
    lines = []
    for k, name in order:
        d = rp[k]
        lines.append(f"{name} & {pct(d['all']['acc@1'])} & {pct(d['all']['acc@5'])} & {d['all']['mrr']:.3f} & "
                     f"{pct(d['hard']['acc@1'])} & {pct(d['hard']['acc@5'])} & {pct(d['easy']['acc@5'])} \\\\")
    (TAB / "retrieval.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    src["retrieval"] = {"file": str(TMP / "paper-numbers.json"), "n": rp["cond_ours"]["all"]["n"],
                        "n_hard": rp["cond_ours"]["hard"]["n"]}

    # ---- function level -----------------------------------------------------
    fp = PN["functions_pooled"]
    e = fp["eval_eligible"]
    lines = [f"BM25 over the layer's top-10 files & {fp['n_eval_eligible']:,} & {pct(e['acc@1'])} & {pct(e['acc@5'])} & "
             f"{pct(e['acc@10'])} & {e['mrr']:.3f} & {pct(fp['oracle_in_candidates'])} \\\\"]
    for name, d in (("unconstrained loop (ablation)", L), ("\\sys{}", W)):
        x = d["all"]
        lines.append(f"{name} & {x['n_region_eligible']:,} & {pct(x['region_acc@1'])} & {pct(x['region_acc@5'])} & "
                     f"{pct(x.get('region_acc@10'))} & {x['region_mrr']:.3f} & -- \\\\")
    (TAB / "functions.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    # ---- module level -------------------------------------------------------
    MM = json.loads((RES / "module-metrics.json").read_text(encoding="utf-8"))
    tot, N = {}, 0
    for p, d in MM.items():
        if p.startswith("_"):
            continue
        n = d["n_eval"]; N += n
        for s, m in d["systems"].items():
            t = tot.setdefault(s, [0.0, 0.0]); t[0] += m["acc@1"] * n; t[1] += m["acc@5"] * n
    mb = None
    if (RES / "module-baselines.json").exists():
        mb = json.loads((RES / "module-baselines.json").read_text(encoding="utf-8"))
    lines = []
    # sanity baselines from module_baselines.py, pooled over the projects it
    # covers; the file must cover every project in module-metrics.json
    projects = [p for p in MM if not p.startswith("_")]
    if mb and all(p in mb for p in projects):
        # `most_frequent_live`: the frequency prior restricted to modules that
        # still exist in the evaluation snapshot (a module that was renamed
        # away cannot be ranked); the fairer, stronger baseline
        for key, name in (("random", "random module ranking (expected)"),
                          ("most_frequent_live", "development-split defect frequency")):
            a1 = sum(mb[p][key]["acc@1"] * mb[p]["n_eval"] for p in projects)
            a5 = sum(mb[p][key]["acc@5"] * mb[p]["n_eval"] for p in projects)
            nb = sum(mb[p]["n_eval"] for p in projects)
            lines.append(f"{name} & {pct(a1 / nb)} & {pct(a5 / nb)} \\\\")
            src.setdefault("modules_baselines", {})[key] = {"acc@1": round(a1 / nb, 4), "acc@5": round(a5 / nb, 4), "n": nb}
        lines.append("\\midrule")
    lines.append(f"\\retr{{}} (module of the top file) & {pct(tot['cond_ours'][0] / N)} & {pct(tot['cond_ours'][1] / N)} \\\\")
    lines.append(f"unconstrained loop (module of the top file) & {pct(L['all']['module_from_ranking_acc@1'])} & -- \\\\")
    lines.append(f"\\sys{{}} (module named by the agent) & {pct(W['all']['module_agent_acc@1'])} & -- \\\\")
    (TAB / "modules.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    src["modules"] = {"file": str(RES / "module-metrics.json"), "n": N,
                      "baselines_file": str(RES / "module-baselines.json") if mb else None}

    (TAB / "sources.json").write_text(json.dumps(src, indent=1, default=str), encoding="utf-8")
    for f in ("headline", "agents", "retrieval", "functions", "modules"):
        print(f"--- {f}.tex"); print((TAB / f"{f}.tex").read_text(encoding="utf-8"))
    print("paired wf minus free loop:", json.dumps(pair))
    return 0


if __name__ == "__main__":
    sys.exit(main())
