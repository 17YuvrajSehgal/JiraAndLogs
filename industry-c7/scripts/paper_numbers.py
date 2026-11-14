"""Pooled numbers over the 27 projects that no result file holds yet.

  retrieval   every retrieval system, eval split, all / hard / easy,
              pooled over projects (from <p>-instances.jsonl)
  functions   BM25 function stage pooled over projects
  dense       dense-vs-lexical pooled over the 27 x 200 samples
  wf_regions  wf region metrics split by hard / easy (c7_coverage.score_row)

  per_project  wf and the retrieval layer per project (n, hard share,
              Acc@1, Acc@5), the range quoted in the results text

Writes industry-c7/data/results/paper-numbers.json.
Usage (from the repository root):
    python industry-c7/scripts/paper_numbers.py --wf <one-row-per-instance wf rows>
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

R = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, f"{R}/scripts")
sys.path.insert(0, f"{R}/agent")
import c7_coverage as CC  # noqa: E402
from localize import is_dead_row  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--wf", required=True)
A = ap.parse_args()
OUTF = f"{R}/data/results/paper-numbers.json"
out = {}

# ---- retrieval systems, pooled, eval split --------------------------------
import module_metrics as MM  # noqa: E402

sample = set(json.load(open(f"{R}/data/results/baseline-sample.json"))["ids"])
acc = {}    # system -> stratum -> [sum acc1, acc5, acc10, mrr, n]
accS = {}   # the same on the 1,000-instance sample, cond_ours only
mod = {}    # cond_ours module of the top-ranked file, per stratum, [hits, n]
modS = {}
projects = sorted(os.path.basename(f)[:-len("-instances.jsonl")]
                  for f in glob.glob(f"{R}/data/results/*-instances.jsonl"))
for p in projects:
    n_dev = json.load(open(f"{R}/data/results/{p}-summary.json"))["n_dev"]
    rows = [json.loads(l) for l in open(f"{R}/data/results/{p}-instances.jsonl", encoding="utf-8")]
    rows.sort(key=lambda r: r["fix_time"])
    depth = MM.DEPTH.get(p, 1)
    for r in rows[n_dev:]:
        strata = ["all", "easy" if r["strata"]["easy"] else "hard",
                  "trace" if r["strata"].get("trace") else "no_trace"]
        in_sample = f"{p}:{r['issue_key']}" in sample
        for s, m in r["metrics"].items():
            for st in strata:
                a = acc.setdefault(s, {}).setdefault(st, [0.0, 0.0, 0.0, 0.0, 0])
                a[0] += m["acc@1"]; a[1] += m["acc@5"]; a[2] += m["acc@10"]; a[3] += m["mrr"]; a[4] += 1
                if in_sample and s == "cond_ours":
                    b = accS.setdefault(st, [0.0, 0.0, 0.0, 0.0, 0])
                    b[0] += m["acc@1"]; b[1] += m["acc@5"]; b[2] += m["acc@10"]; b[3] += m["mrr"]; b[4] += 1
        top = (r["rankings"].get("cond_ours") or [""])[0]
        gm = {MM.module_of(f, depth) for f in r["gold_files"]}
        hit = float(bool(top) and MM.module_of(top, depth) in gm)
        for st in strata:
            t = mod.setdefault(st, [0.0, 0]); t[0] += hit; t[1] += 1
            if in_sample:
                t = modS.setdefault(st, [0.0, 0]); t[0] += hit; t[1] += 1
out["retrieval_pooled"] = {
    s: {st: {"n": a[4], "acc@1": round(a[0] / a[4], 6), "acc@5": round(a[1] / a[4], 6),
             "acc@10": round(a[2] / a[4], 6), "mrr": round(a[3] / a[4], 6)} for st, a in d.items()}
    for s, d in acc.items()}
out["retrieval_module_top_file"] = {st: {"n": t[1], "acc@1": round(t[0] / t[1], 6)} for st, t in mod.items()}
out["retrieval_sample"] = {
    st: {"n": b[4], "acc@1": round(b[0] / b[4], 6), "acc@5": round(b[1] / b[4], 6),
         "acc@10": round(b[2] / b[4], 6), "mrr": round(b[3] / b[4], 6),
         "module_acc@1": round(modS[st][0] / modS[st][1], 6)} for st, b in accS.items()}
print("retrieval module (top file):", out["retrieval_module_top_file"]["all"], "sample:", out["retrieval_sample"]["all"])
print("retrieval: projects", len(projects), "n all", acc["cond_ours"]["all"][3],
      "hard", acc["cond_ours"]["hard"][3])
for s in ("cond_ours", "cond_no_memory", "fused_ours", "fused_no_memory",
          "content_bm25", "trace_grep", "memory_bm25", "path_bm25"):
    d = out["retrieval_pooled"][s]
    print(f"  {s:16} all {d['all']['acc@1']:.3f}/{d['all']['acc@5']:.3f}"
          f"  hard {d['hard']['acc@1']:.3f}/{d['hard']['acc@5']:.3f}"
          f"  easy {d['easy']['acc@1']:.3f}/{d['easy']['acc@5']:.3f}")

# ---- function stage pooled ------------------------------------------------
fs = {"n": 0, "n_rows": 0, "eligible_sum": 0, "all": [0.0] * 4, "hard": [0.0] * 4, "hard_n": 0,
      "oracle": 0.0, "oracle_hard": 0.0}
for p in projects:
    d = json.load(open(f"{R}/data/results/{p}-functions-summary.json"))
    n = d["n_eval_eligible"]; e = d["eval_eligible"]; h = d["eval_eligible_hard"]
    fs["n"] += n; fs["n_rows"] += d["n_rows"]; fs["eligible_sum"] += d["eligible_fraction_all"] * d["n_rows"]
    for i, k in enumerate(("acc@1", "acc@5", "acc@10", "mrr")):
        fs["all"][i] += e[k] * n
    fs["oracle"] += e["oracle_in_candidates"] * n
    # hard eligible count is not stored; weight hard by n (approximation flagged)
    for i, k in enumerate(("acc@1", "acc@5", "acc@10", "mrr")):
        fs["hard"][i] += h[k] * n
    fs["oracle_hard"] += h["oracle_in_candidates"] * n; fs["hard_n"] += n
out["functions_pooled"] = {
    "n_eval_eligible": fs["n"], "eligible_fraction_all_rows": round(fs["eligible_sum"] / fs["n_rows"], 6),
    "eval_eligible": dict(zip(("acc@1", "acc@5", "acc@10", "mrr"), [round(x / fs["n"], 6) for x in fs["all"]])),
    "oracle_in_candidates": round(fs["oracle"] / fs["n"], 6),
    "eval_eligible_hard_weighted_by_n_eligible(approx)": dict(zip(("acc@1", "acc@5", "acc@10", "mrr"), [round(x / fs["hard_n"], 6) for x in fs["hard"]])),
}
print("functions pooled:", out["functions_pooled"])

# ---- dense pooled (200 per project, simple mean) ----------------------------
ds = {}
for p in projects:
    d = json.load(open(f"{R}/data/results/{p}-dense-summary.json"))
    for s, m in d["systems"].items():
        a = ds.setdefault(s, [0.0, 0.0, 0]); a[0] += m["acc@5"]; a[1] += m["mrr"]; a[2] += 1
wins = {}
for p in projects:
    d = json.load(open(f"{R}/data/results/{p}-dense-summary.json"))["systems"]
    wins.setdefault("s3_dense_beats_bm25", 0); wins.setdefault("s4_dense_beats_bm25", 0); wins.setdefault("cond_dense_s4_beats_cond", 0)
    wins["s3_dense_beats_bm25"] += d["content_dense"]["acc@5"] > d["content_bm25"]["acc@5"]
    wins["s4_dense_beats_bm25"] += d["memory_dense"]["acc@5"] > d["memory_bm25"]["acc@5"]
    wins["cond_dense_s4_beats_cond"] += d["cond_dense_s4"]["acc@5"] > d["cond_ours"]["acc@5"]
out["dense_pooled"] = {s: {"acc@5": round(a[0] / a[2], 6), "mrr": round(a[1] / a[2], 6), "projects": a[2]} for s, a in ds.items()}
out["dense_wins_of_27"] = wins
print("dense pooled:", {s: v["acc@5"] for s, v in out["dense_pooled"].items()}, wins)

# ---- wf regions by hard / easy --------------------------------------------
wf = CC.load_rows(CC.Path(A.wf))
sc = {i: CC.score_row(r) for i, r in wf.items()}
hard_ids = {i for i, r in wf.items() if r.get("hard")}
out["wf_by_difficulty"] = {
    "hard": CC.summarise({i: s for i, s in sc.items() if i in hard_ids})["all"],
    "easy": CC.summarise({i: s for i, s in sc.items() if i not in hard_ids})["all"],
}
for k, v in out["wf_by_difficulty"].items():
    print("wf", k, {m: v[m] for m in ("n", "file_acc@1", "file_acc@5", "module_agent_acc@1",
                                     "n_region_eligible", "region_acc@1", "region_acc@5", "region_mrr")})

# ---- per project: wf and the retrieval layer on the same rows ---------------
byp = {}
for i, r in wf.items():
    byp.setdefault(r["project"], []).append(r)
out["per_project"] = {}
for p, rs in byp.items():
    n = len(rs)
    out["per_project"][p] = {
        "n": n, "hard_share": round(sum(bool(r.get("hard")) for r in rs) / n, 4),
        "wf_acc@1": round(sum(r["metrics"]["acc@1"] for r in rs) / n, 6),
        "wf_acc@5": round(sum(r["metrics"]["acc@5"] for r in rs) / n, 6),
        "lexical_acc@1": round(sum(r["metrics_lexical"]["acc@1"] for r in rs) / n, 6),
        "lexical_acc@5": round(sum(r["metrics_lexical"]["acc@5"] for r in rs) / n, 6)}
lo = min(out["per_project"].items(), key=lambda kv: kv[1]["wf_acc@1"])
hi = max(out["per_project"].items(), key=lambda kv: kv[1]["wf_acc@1"])
print("per project wf acc@1: min", lo, "max", hi)

# ---- the ported agents on the instances where they returned a location ----
# A port that leaves an answer unparseable scores a miss there. This scores
# each port, and wf, on the instances the port did answer, so the margin
# can be read with and without the parse failures.
import random
import statistics as st


def boot(diff, seed, n_boot=2000):
    """Mean of `diff` with its 95% paired bootstrap interval over instances."""
    rs = random.Random(seed)
    n = len(diff)
    s = sorted(st.fmean(diff[rs.randrange(n)] for _ in range(n)) for _ in range(n_boot))
    return [round(st.fmean(diff), 6), round(s[int(.025 * n_boot)], 6), round(s[int(.975 * n_boot)], 6)]


out["parsed_only"] = {}
for arm in ("locagent", "cosil"):
    rows = [json.loads(l) for l in open(f"{R}/data/agent/agent-{arm}-eval.jsonl", encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r["id"] in wf and not is_dead_row(r)]
    ok = [r for r in rows if not r.get("empty")]
    m = lambda rs, k, src=None: sum((src[r["id"]] if src else r)["metrics"][k] for r in rs) / len(rs)  # noqa: E731
    out["parsed_only"][arm] = {
        "n_all": len(rows), "n_parsed": len(ok), "n_empty": len(rows) - len(ok),
        "arm_acc@1": round(m(ok, "acc@1"), 6), "arm_acc@5": round(m(ok, "acc@5"), 6),
        "wf_acc@1": round(m(ok, "acc@1", wf), 6), "wf_acc@5": round(m(ok, "acc@5", wf), 6),
        "wf_minus_arm_acc@1": boot([wf[r["id"]]["metrics"]["acc@1"] - r["metrics"]["acc@1"] for r in ok], 20261104),
        "wf_minus_arm_acc@5": boot([wf[r["id"]]["metrics"]["acc@5"] - r["metrics"]["acc@5"] for r in ok], 20261105)}
    print("parsed-only", arm, out["parsed_only"][arm])

# ---- the headline with the pilot instances removed -------------------------
# The prompts and step budgets were settled on two pilots drawn from the
# evaluation split (30 + 81 instances). This scores wf on the split without
# them, so the headline can be read either way.
pilot = set()
for f in ("baseline-pilot.json", "keepfull-pilot.json"):
    pilot |= set(json.load(open(f"{R}/data/results/{f}"))["ids"])
keep = {i for i in wf if i not in pilot}
S_np = CC.summarise({i: s for i, s in sc.items() if i in keep})["all"]
out["without_pilots"] = {"n_pilot_ids": len(pilot), "n_pilot_in_wf": len(pilot & set(wf)), "n": S_np["n"],
                         "file_acc@1": S_np["file_acc@1"], "file_acc@5": S_np["file_acc@5"],
                         "module_agent_acc@1": S_np["module_agent_acc@1"],
                         "region_acc@1": S_np["region_acc@1"], "region_acc@5": S_np["region_acc@5"]}
print("without pilots:", out["without_pilots"])

# ---- the sample's own wf cost, for the sample block of the big table ------
sw = [r for i, r in wf.items() if i in sample]
out["wf_sample_cost"] = {"n": len(sw),
                         "llm_calls": round(sum(r["cost"]["llm_calls"] for r in sw) / len(sw), 2),
                         "prompt_tokens": round(sum(r["cost"]["prompt_tokens"] for r in sw) / len(sw))}

json.dump(out, open(OUTF, "w"), indent=1)
print("->", OUTF)
