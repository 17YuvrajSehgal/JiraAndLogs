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

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--wf", required=True)
A = ap.parse_args()
OUTF = f"{R}/data/results/paper-numbers.json"
out = {}

# ---- retrieval systems, pooled, eval split --------------------------------
acc = {}   # system -> stratum -> [sum acc1, sum acc5, sum mrr, n]
projects = sorted(os.path.basename(f)[:-len("-instances.jsonl")]
                  for f in glob.glob(f"{R}/data/results/*-instances.jsonl"))
hard_n = 0
for p in projects:
    n_dev = json.load(open(f"{R}/data/results/{p}-summary.json"))["n_dev"]
    rows = [json.loads(l) for l in open(f"{R}/data/results/{p}-instances.jsonl", encoding="utf-8")]
    rows.sort(key=lambda r: r["fix_time"])
    for r in rows[n_dev:]:
        strata = ["all", "easy" if r["strata"]["easy"] else "hard",
                  "trace" if r["strata"].get("trace") else "no_trace"]
        for s, m in r["metrics"].items():
            for st in strata:
                a = acc.setdefault(s, {}).setdefault(st, [0.0, 0.0, 0.0, 0])
                a[0] += m["acc@1"]; a[1] += m["acc@5"]; a[2] += m["mrr"]; a[3] += 1
out["retrieval_pooled"] = {
    s: {st: {"n": a[3], "acc@1": round(a[0] / a[3], 4), "acc@5": round(a[1] / a[3], 4),
             "mrr": round(a[2] / a[3], 4)} for st, a in d.items()}
    for s, d in acc.items()}
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
    "n_eval_eligible": fs["n"], "eligible_fraction_all_rows": round(fs["eligible_sum"] / fs["n_rows"], 4),
    "eval_eligible": dict(zip(("acc@1", "acc@5", "acc@10", "mrr"), [round(x / fs["n"], 4) for x in fs["all"]])),
    "oracle_in_candidates": round(fs["oracle"] / fs["n"], 4),
    "eval_eligible_hard_weighted_by_n_eligible(approx)": dict(zip(("acc@1", "acc@5", "acc@10", "mrr"), [round(x / fs["hard_n"], 4) for x in fs["hard"]])),
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
out["dense_pooled"] = {s: {"acc@5": round(a[0] / a[2], 4), "mrr": round(a[1] / a[2], 4), "projects": a[2]} for s, a in ds.items()}
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
        "wf_acc@1": round(sum(r["metrics"]["acc@1"] for r in rs) / n, 4),
        "wf_acc@5": round(sum(r["metrics"]["acc@5"] for r in rs) / n, 4),
        "lexical_acc@1": round(sum(r["metrics_lexical"]["acc@1"] for r in rs) / n, 4),
        "lexical_acc@5": round(sum(r["metrics_lexical"]["acc@5"] for r in rs) / n, 4)}
lo = min(out["per_project"].items(), key=lambda kv: kv[1]["wf_acc@1"])
hi = max(out["per_project"].items(), key=lambda kv: kv[1]["wf_acc@1"])
print("per project wf acc@1: min", lo, "max", hi)

json.dump(out, open(OUTF, "w"), indent=1)
print("->", OUTF)
