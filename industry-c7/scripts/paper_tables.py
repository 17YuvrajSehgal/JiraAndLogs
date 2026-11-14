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
from decimal import Decimal, ROUND_HALF_UP
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
    """Percent with d decimals, ties rounded up as a reader would (0.5385 -> 53.9);
    f-string formatting sees 53.849999... and prints 53.8."""
    return "--" if x is None else str((Decimal(repr(x)) * 100).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def f3(x):
    """Three decimals, same tie rule (MRR columns)."""
    return str(Decimal(repr(x)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


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

    # paired wf minus the loop, file and region, all / hard
    pair = {}
    for k in ("all", "hard"):
        keep = [i for i in ids if i in S_wf[k]]
        for grp, m in (("file", "acc@1"), ("file", "acc@5"), ("region", "acc@1"), ("region", "acc@5"), ("region", "acc@10")):
            ok = [i for i in keep if grp in s_wf[i] and grp in s_lp[i]]
            d, lo, hi = boot([s_wf[i][grp][m] - s_lp[i][grp][m] for i in ok], (len(grp) * 7 + int(m[-1])) % 97)
            pair[f"{k}:{grp}_{m}"] = {"delta": round(d, 4), "lo": round(lo, 4), "hi": round(hi, 4), "n": len(ok)}
    src["headline"]["paired_wf_minus_loop"] = pair
    for d, sc, rows_ in ((W, s_wf, wf), (L, s_lp, lp)):   # Acc@10s, which summarise() leaves out
        reg = [s["region"]["acc@10"] for s in sc.values() if "region" in s]
        d["all"]["region_acc@10"] = st.fmean(reg)
        d["all"]["file_acc@10"] = st.fmean(r["metrics"]["acc@10"] for r in rows_.values())
    # the ablation table compares the two arms on the instances both ran, the
    # population the text's paired deltas and \loop* macros use
    P = set(ids)
    Wp = {k: summ(s_wf, [i for i in v if i in P]) for k, v in S_wf.items()}
    Lp = {k: summ(s_lp, [i for i in v if i in P]) for k, v in S_lp.items()}
    for d, sc, rows_ in ((Wp, s_wf, wf), (Lp, s_lp, lp)):
        d["all"]["region_acc@10"] = st.fmean(s["region"]["acc@10"] for i, s in sc.items() if i in P and "region" in s)
        d["all"]["file_acc@10"] = st.fmean(r["metrics"]["acc@10"] for i, r in rows_.items() if i in P)
    src["headline"]["Wp"], src["headline"]["Lp"] = Wp, Lp

    # ---- ablation: the unconstrained loop against the staged workflow ------
    cite = lambda d: "--" if d["all"]["steps_citing_log"] is None else pct(d["all"]["steps_citing_log"])  # noqa: E731
    abl = [
        f"unconstrained loop & {pct(Lp['all']['file_acc@1'])} & {pct(Lp['all']['file_acc@5'])} & {pct(Lp['hard']['file_acc@1'])} & "
        f"{pct(Lp['all']['region_acc@1'])} & {pct(Lp['all']['region_acc@5'])} & {pct(Lp['all']['region_acc@10'])} & "
        f"{cite(Lp)} & {cl[0]:.1f} / {cl[1]:.0f}k \\\\",
        f"\\sys{{}} & {pct(Wp['all']['file_acc@1'])} & {pct(Wp['all']['file_acc@5'])} & {pct(Wp['hard']['file_acc@1'])} & "
        f"{pct(Wp['all']['region_acc@1'])} & {pct(Wp['all']['region_acc@5'])} & {pct(Wp['all']['region_acc@10'])} & "
        f"{cite(Wp)} & {cw[0]:.1f} / {cw[1]:.0f}k \\\\",
        "\\midrule",
        "\\sys{} minus loop, paired & "
        + " & ".join(f"{100 * pair[k]['delta']:+.1f} [{100 * pair[k]['lo']:+.1f}, {100 * pair[k]['hi']:+.1f}]"
                     for k in ("all:file_acc@1", "all:file_acc@5", "hard:file_acc@1",
                               "all:region_acc@1", "all:region_acc@5", "all:region_acc@10"))
        + f" & {100 * ((Wp['all']['steps_citing_log'] or 0) - (Lp['all']['steps_citing_log'] or 0)):+.1f} & -- \\\\",
    ]
    (TAB / "ablation.tex").write_text("\n".join(abl) + "\n", encoding="utf-8", newline="\n")

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
    lines.append(f"\\sys{{}} & {f3(sysr['acc@1'])} & {f3(sysr['acc@5'])} & {f3(sysr['hard_acc@1'])} & "
                 f"{f3(sysr['hard_acc@5'])} & {sysr['llm_calls']:.1f} & {sysr['prompt_tokens'] / 1000:.0f}k \\\\")
    for key, name in (("locagent", "LocAgent-style"), ("cosil", "CoSIL-style")):
        e = AB["systems"][key]
        lines.append(f"{name} & {f3(e['acc@1'])} & {f3(e['acc@5'])} & {f3(e['hard_acc@1'])} & {f3(e['hard_acc@5'])} & "
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
        lines.append(f"{name} & {f3(acc(common, 1))} & {f3(acc(common, 5))} & {f3(acc(hk, 1))} & {f3(acc(hk, 5))} & "
                     f"{calls:.1f} & {toks:.0f}k \\\\")
        src["agents"]["extra"][key] = {"file": path, "n": len(common), "n_hard": len(hk),
                                       "prompt_tokens_k": round(toks, 2),
                                       "acc@1": round(acc(common, 1), 4), "acc@5": round(acc(common, 5), 4),
                                       "hard_acc@1": round(acc(hk, 1), 4), "hard_acc@5": round(acc(hk, 5), 4),
                                       "vs_wf_acc@1": [round(x, 4) for x in delta],
                                       "vs_wf_acc@5": [round(x, 4) for x in paired_vs_wf(d, common, 5)]}
    # ---- every system and every metric in one table ------------------------
    # Two blocks: the full evaluation split and the 1,000-instance sample. In
    # each column the best value of a block is bold; when it is ours it is
    # also set in the win colour (\win, defined in main.tex). Module is the
    # module of the top-ranked file for every row. Cost is not scored.
    import module_metrics as MM
    sys.path.insert(0, str(HERE))
    from localize import is_dead_row  # noqa: E402

    def gold_mods(r):
        return {MM.module_of(f, MM.DEPTH.get(r["project"], 1)) for f in r["gold_files"]}

    def block_rows(systems, keep):
        """systems: list of (name, rows dict, scored dict, is_ours, calls, tokens, region_override).
        A system given as (name, None, None, False, None, None, vals) is
        precomputed (the retrieval layer, pooled from the instances files).
        Returns rows of cell values (None = not available) and the names."""
        out = []
        for name, rows_, sc, ours, calls, toks, reg_over in systems:
            if rows_ is None:
                out.append((name, ours, list(reg_over), calls, toks, len(keep)))
                continue
            ks = [i for i in keep if i in rows_]
            hk = [i for i in ks if wf[i].get("hard")]
            S = CC.summarise({i: sc[i] for i in ks})["all"]
            Sh = CC.summarise({i: sc[i] for i in hk})["all"]
            # only our agent names regions; the ports carry a lexical fill
            # that is not their output, and the model baselines rank files
            has_regions = ours
            vals = [S["file_acc@1"], S["file_acc@5"], st.fmean(rows_[i]["metrics"]["acc@10"] for i in ks), S["file_mrr"],
                    Sh["file_acc@1"], Sh["file_acc@5"], S["module_from_ranking_acc@1"],
                    (S["region_acc@1"] if has_regions else (reg_over or (None, None))[0]),
                    (S["region_acc@5"] if has_regions else (reg_over or (None, None))[1]),
                    S["steps_citing_log"]]
            out.append((name, ours, vals, calls, toks, len(ks)))
        return out

    def render_block(title, rows_):
        lines_ = [f"\\multicolumn{{12}}{{@{{}}l}}{{\\emph{{{title}}}}} \\\\"]
        ncol = len(rows_[0][2])
        best = [max((r[2][c] for r in rows_ if r[2][c] is not None), default=None) for c in range(ncol)]
        for name, ours, vals, calls, toks, n in rows_:
            cells = []
            for c, v in enumerate(vals):
                if v is None:
                    cells.append("--"); continue
                s = f"{f3(v)}" if c == 3 else pct(v)
                if best[c] is not None and abs(v - best[c]) < 1e-9:
                    s = f"\\win{{{s}}}" if ours else f"\\textbf{{{s}}}"
                cells.append(s)
            cells.append("0 / 0" if calls is None else f"{calls:.1f} / {toks:.0f}k")
            lines_.append(f"{name} & " + " & ".join(cells) + " \\\\")
        return lines_

    # the retrieval layer, pooled from the instances files at full ranking
    # depth (paper_numbers.py), the same source as the retrieval table
    PNJ = json.loads((TMP / "paper-numbers.json").read_text(encoding="utf-8"))
    fp_, rpc, rmod, rsm = PNJ["functions_pooled"], PNJ["retrieval_pooled"]["cond_ours"], \
        PNJ["retrieval_module_top_file"], PNJ["retrieval_sample"]
    retr_full = [rpc["all"]["acc@1"], rpc["all"]["acc@5"], rpc["all"]["acc@10"], rpc["all"]["mrr"],
                 rpc["hard"]["acc@1"], rpc["hard"]["acc@5"], rmod["all"]["acc@1"],
                 fp_["eval_eligible"]["acc@1"], fp_["eval_eligible"]["acc@5"], None]
    retr_sample = [rsm["all"]["acc@1"], rsm["all"]["acc@5"], rsm["all"]["acc@10"], rsm["all"]["mrr"],
                   rsm["hard"]["acc@1"], rsm["hard"]["acc@5"], rsm["all"]["module_acc@1"], None, None, None]
    csw = (PNJ["wf_sample_cost"]["llm_calls"], PNJ["wf_sample_cost"]["prompt_tokens"] / 1000)
    full_sys = [("retrieval layer (no model)", None, None, False, None, None, retr_full),
                ("\\sys{}", wf, s_wf, True, cw[0], cw[1], None)]
    full = block_rows(full_sys, sorted(wf))
    arms = {}
    for key, name in (("locagent", "LocAgent-style"), ("cosil", "CoSIL-style")):
        rows_ = {}
        for line in (ROOT / "data/agent" / f"agent-{key}-eval.jsonl").open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                if r["id"] in sample and not is_dead_row(r):
                    rows_[r["id"]] = r
        arms[key] = (name, rows_, {i: CC.score_row(r) for i, r in rows_.items()},
                     AB["systems"][key]["llm_calls"], AB["systems"][key]["prompt_tokens"] / 1000)
    sample_sys = [("retrieval layer (no model)", None, None, False, None, None, retr_sample)]
    for key in ("locagent", "cosil"):
        name, rows_, sc, calls, toks = arms[key]
        sample_sys.append((name, rows_, sc, False, calls, toks, None))
    for key, (name, d, path) in extra.items():
        sc = {i: CC.score_row(r) for i, r in d.items()}
        calls = 2.0 if key == "llm_alone" else 1.0
        toks = src["agents"]["extra"][key].get("prompt_tokens_k") or 0.0
        sample_sys.append((name, d, sc, False, calls, toks, None))
    sample_sys.append(("\\sys{}", sw, {i: s_wf[i] for i in sw}, True, csw[0], csw[1], None))
    samp = block_rows(sample_sys, sorted(sample))
    # the population counts (the four unanswered instances count as misses)
    npop = json.loads((TMP / "paper-numbers.json").read_text(encoding="utf-8"))["retrieval_pooled"]["cond_ours"]
    alltab = render_block(f"evaluation split, {npop['all']['n']:,} instances ({npop['hard']['n']:,} hard)", full)
    alltab.append("\\midrule")
    alltab += render_block(f"stratified sample, {len(sample):,} instances ({len(hard):,} hard)", samp)
    (TAB / "all.tex").write_text("\n".join(alltab) + "\n", encoding="utf-8", newline="\n")
    src["all"] = {"full": [(r[0], r[5]) for r in full], "sample": [(r[0], r[5]) for r in samp]}

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
        lines.append(f"{name} & {pct(d['all']['acc@1'])} & {pct(d['all']['acc@5'])} & {f3(d['all']['mrr'])} & "
                     f"{pct(d['hard']['acc@1'])} & {pct(d['hard']['acc@5'])} & {pct(d['easy']['acc@5'])} \\\\")
    (TAB / "retrieval.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    src["retrieval"] = {"file": str(TMP / "paper-numbers.json"), "n": rp["cond_ours"]["all"]["n"],
                        "n_hard": rp["cond_ours"]["hard"]["n"]}

    # ---- function level -----------------------------------------------------
    fp = PN["functions_pooled"]
    e = fp["eval_eligible"]
    lines = [f"BM25 over the layer's top-10 files & {fp['n_eval_eligible']:,} & {pct(e['acc@1'])} & {pct(e['acc@5'])} & "
             f"{pct(e['acc@10'])} & {f3(e['mrr'])} & {pct(fp['oracle_in_candidates'])} \\\\"]
    for name, d in (("unconstrained loop (ablation)", Lp), ("\\sys{}", Wp)):
        x = d["all"]
        lines.append(f"{name} & {x['n_region_eligible']:,} & {pct(x['region_acc@1'])} & {pct(x['region_acc@5'])} & "
                     f"{pct(x.get('region_acc@10'))} & {f3(x['region_mrr'])} & -- \\\\")
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
    lines.append(f"unconstrained loop (module of the top file) & {pct(Lp['all']['module_from_ranking_acc@1'])} & -- \\\\")
    lines.append(f"\\sys{{}} (module named by the agent) & {pct(W['all']['module_agent_acc@1'])} & -- \\\\")
    (TAB / "modules.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    src["modules"] = {"file": str(RES / "module-metrics.json"), "n": N,
                      "baselines_file": str(RES / "module-baselines.json") if mb else None}

    (TAB / "sources.json").write_text(json.dumps(src, indent=1, default=str), encoding="utf-8")
    for f in ("all", "ablation", "retrieval", "functions", "modules"):
        print(f"--- {f}.tex"); print((TAB / f"{f}.tex").read_text(encoding="utf-8"))
    print("paired wf minus free loop:", json.dumps(pair))
    return 0


if __name__ == "__main__":
    sys.exit(main())
