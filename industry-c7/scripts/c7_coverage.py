"""Score the challenge outputs the file metrics do not cover (P6, T29-T35).

  module     T29  agent's own module vs the module of its top file
                  (module_metrics.module_of at the project's DEPTH)
  log cites  T32  how many chain steps cite a log event, and how many of
                  those citations exist in the report
  regions    T33  region Acc@K / MRR against the fix's gold functions
                  ({p}-functions.jsonl), keyed path::function@start_line
  strata     T35  every metric on: stack trace / log lines, no trace / prose
  paired          --base: a second run (e.g. --no-log-layer) on the same
                  ids, paired bootstrap on the difference

  --log-sites     CPU only, no agent run needed. For each eval instance with
                  log events, is the code that PRINTED them a gold file?
                  This measures the challenge's third difficulty directly:
                  how often the detection site is not the cause.

Usage:
    python industry-c7/scripts/c7_coverage.py --run data/agent/agent-v4.jsonl \
        [--base data/agent/agent-v4-nolog.jsonl]
    python industry-c7/scripts/c7_coverage.py --log-sites --limit 300
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "agent"))
from localize import OUT, PROJECTS, load_bench  # noqa: E402
import module_metrics as MM  # noqa: E402

KS = (1, 5, 10)
STRATA = ("trace", "logs_no_trace", "prose")


def stratum(text: str, has_trace: bool) -> str:
    import logs
    if has_trace:
        return "trace"
    return "logs_no_trace" if logs.select_events(text, k=1) else "prose"


def rank_metrics(ranked: list, gold: set) -> dict:
    hit = next((i for i, x in enumerate(ranked) if x in gold), None)
    m = {f"acc@{k}": float(any(x in gold for x in ranked[:k])) for k in KS}
    m["mrr"] = 1.0 / (hit + 1) if hit is not None else 0.0
    return m


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def boot(diffs: list[float], n: int = 2000, seed: int = 0):
    rng = random.Random(seed)
    k = len(diffs)
    s = sorted(sum(diffs[rng.randrange(k)] for _ in range(k)) / k
               for _ in range(n))
    return round(sum(diffs) / k, 4), round(s[int(.025 * n)], 4), round(s[int(.975 * n)], 4)


def load_rows(path: Path) -> dict:
    out = {}
    for line in path.open(encoding="utf-8"):
        r = json.loads(line)
        if not r.get("error") and not str(r.get("stop_reason", "")).startswith("error"):
            out[r["id"]] = r
    return out


def health(path: Path) -> dict:
    """What to look at FIRST after a pilot: did the run answer at all, and
    was each new piece actually used. Counts every row, dead ones included,
    because load_rows drops those silently."""
    from collections import Counter
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    live = [r for r in rows if r.get("ranking")]
    n = max(1, len(live))
    stops = Counter(str(r.get("stop_reason") or r.get("error"))[:40] for r in rows)
    used = Counter(t for r in live for t in set(r.get("tools_used") or []))
    comp = [r["report_compression"] for r in live if r.get("report_compression")]
    wf = [r for r in live if r.get("wf_cards") is not None and "wf_table" in r]
    return {
        "rows": len(rows), "live": len(live), "stop_reasons": dict(stops),
        "no_answer_rate": round(stops.get("no_answer", 0) / max(1, len(rows)), 4),
        "runs_using_tool": {t: round(used[t] / n, 4) for t in
                            ("match_log", "dependencies", "callers_of",
                             "data_flow_back", "recall_incidents")},
        "module_empty_raw": round(sum(not (r.get("module_raw") or "").strip()
                                      for r in live) / n, 4),
        "module_not_in_snapshot": round(sum(bool((r.get("module_raw") or "").strip())
                                            and not r.get("module")
                                            for r in live) / n, 4),
        "runs_with_log_events": round(sum(bool(r.get("log_events")) for r in live) / n, 4),
        "runs_with_printing_site": round(sum(bool(r.get("log_printed_by"))
                                             for r in live) / n, 4),
        "regions_per_run": mean([float(len(r.get("regions") or [])) for r in live]),
        "llm_calls": mean([float(r["cost"]["llm_calls"]) for r in live]),
        "prompt_tokens": mean([float(r["cost"]["prompt_tokens"]) for r in live]),
        "wall_s": mean([float(r["cost"]["wall_s"]) for r in live]),
        "report_chars_in": mean([float(c["chars_in"]) for c in comp]),
        "report_chars_collapsed": mean([float(c["chars_collapsed"]) for c in comp]),
        # the staged workflow arm: where a gold file is lost, stage by stage
        **({"wf": {
            "n": len(wf),
            "route": dict(Counter(r.get("wf_route") for r in wf)),
            "gold_in_table": mean([float(bool(set(r["gold_files"]) & set(r["wf_table"])))
                                   for r in wf]),
            "gold_examined": mean([float(bool(set(r["gold_files"])
                                              & {c["path"] for c in r["wf_cards"]}))
                                   for r in wf]),
            "verdict_on_gold": dict(Counter(c["role"] for r in wf for c in r["wf_cards"]
                                            if c["path"] in r["gold_files"])),
            "verdict_on_non_gold": dict(Counter(c["role"] for r in wf for c in r["wf_cards"]
                                                if c["path"] not in r["gold_files"])),
            "verdict_unanswered": mean([float(not c["answered"]) for r in wf
                                        for c in r["wf_cards"]]),
            "function_resolves": mean([float(bool(c["function_resolved"])) for r in wf
                                       for c in r["wf_cards"] if c["role"] != "unrelated"]),
            "cards_per_run": mean([float(len(r["wf_cards"])) for r in wf]),
            "walk_back_added": mean([float(bool(d.get("added"))) for r in wf
                                     for d in r["wf_decisions"] if d["stage"] == "walk_back"]),
            "shortlist_answered": mean([float(d["answered"]) for r in wf
                                        for d in r["wf_decisions"] if d["stage"] == "shortlist"]),
            "rank_answered": mean([float(d["answered"]) for r in wf
                                   for d in r["wf_decisions"] if d["stage"] == "rank"]),
            "rank_moved_by_tier_rule": mean([float(bool(d["moved_by_tier_rule"])) for r in wf
                                             for d in r["wf_decisions"] if d["stage"] == "rank"]),
        }} if wf else {}),
    }


_bench: dict = {}
_funcs: dict = {}


def bench_row(project: str, key: str) -> dict:
    if project not in _bench:
        _bench[project] = {b["issue_key"]: b for b in load_bench(project)}
    return _bench[project].get(key, {})


def gold_functions(project: str, key: str):
    if project not in _funcs:
        f = OUT / f"{project}-functions.jsonl"
        _funcs[project] = {}
        if f.exists():
            for line in f.open(encoding="utf-8"):
                r = json.loads(line)
                if r.get("eligible"):
                    _funcs[project][r["issue_key"]] = set(r["gold_functions"])
    return _funcs[project].get(key)


def score_row(r: dict) -> dict:
    p, key = r["project"], r["issue_key"]
    b = bench_row(p, key)
    d = MM.DEPTH.get(p, 1)
    gold_mods = {MM.module_of(f, d) for f in r["gold_files"]}
    out = {"stratum": stratum(b.get("query_text", ""),
                              bool(r.get("has_stack_trace",
                                         b.get("has_stack_trace")))),
           "file": {k: r["metrics"][k] for k in ("acc@1", "acc@5", "mrr")}}
    # T29
    top_mod = MM.module_of(r["ranking"][0], d) if r.get("ranking") else ""
    out["module_from_ranking"] = float(top_mod in gold_mods)
    out["module_agent"] = (float(r["module"] in gold_mods)
                           if "module" in r else None)
    out["module_invalid"] = (float(not r["module"]) if "module" in r else None)
    # T32
    steps = r.get("causal_chain") or []
    cited = [s for s in steps if (s.get("log_event") or "").strip()]
    out["steps"] = len(steps)
    out["steps_citing_log"] = len(cited)
    out["cites_grounded"] = sum(1 for s in cited if s.get("log_event_grounded"))
    out["has_events"] = bool(r.get("log_events"))
    # T33
    gf = gold_functions(p, key)
    if gf:
        keys = []
        for g in r.get("regions") or []:
            if g.get("resolved") and g.get("lines"):
                keys.append(f"{g['path']}::{g['resolved']}@{g['lines'][0]}")
            else:
                keys.append(f"{g.get('path')}::<unresolved>")
        out["region"] = rank_metrics(keys, gf)
        # the same list without the lexical fill: what the model itself named
        out["region_agent"] = rank_metrics(
            [k for k, g in zip(keys, r.get("regions") or [])
             if g.get("source", "agent") == "agent"], gf)
        out["region_agent_share"] = mean(
            [float(g.get("source", "agent") == "agent")
             for g in (r.get("regions") or [])[:5]])
    return out


def summarise(scored: dict) -> dict:
    S = list(scored.values())

    def block(rows):
        res = {"n": len(rows)}
        for k in ("acc@1", "acc@5", "mrr"):
            res[f"file_{k}"] = mean([s["file"][k] for s in rows])
        res["module_from_ranking_acc@1"] = mean([s["module_from_ranking"] for s in rows])
        res["module_agent_acc@1"] = mean([s["module_agent"] for s in rows])
        res["module_agent_invalid"] = mean([s["module_invalid"] for s in rows])
        reg = [s["region"] for s in rows if "region" in s]
        res["n_region_eligible"] = len(reg)
        for k in ("acc@1", "acc@5", "mrr"):
            res[f"region_{k}"] = mean([m[k] for m in reg])
        steps = sum(s["steps"] for s in rows)
        cited = sum(s["steps_citing_log"] for s in rows)
        rega = [s["region_agent"] for s in rows if "region_agent" in s]
        for k in ("acc@1", "acc@5", "mrr"):
            res[f"region_agent_only_{k}"] = mean([m[k] for m in rega])
        res["chain_steps"] = steps
        res["steps_citing_log"] = round(cited / steps, 4) if steps else None
        res["log_cites_grounded"] = (round(sum(s["cites_grounded"] for s in rows)
                                           / cited, 4) if cited else None)
        with_ev = [s for s in rows if s["has_events"]]
        res["runs_with_events_that_cite_one"] = mean(
            [float(s["steps_citing_log"] > 0) for s in with_ev])
        return res

    out = {"all": block(S)}
    for st in STRATA:
        out[st] = block([s for s in S if s["stratum"] == st])
    return out


def paired(run: dict, base: dict, s_run: dict, s_base: dict) -> dict:
    ids = sorted(set(run) & set(base))
    res = {"n_paired": len(ids)}
    for k in ("acc@1", "acc@5", "mrr"):
        res[f"file_{k}"] = boot([s_run[i]["file"][k] - s_base[i]["file"][k]
                                 for i in ids])
    for st in STRATA:
        sub = [i for i in ids if s_run[i]["stratum"] == st]
        if sub:
            res[f"{st}_file_acc@1"] = boot([s_run[i]["file"]["acc@1"]
                                            - s_base[i]["file"]["acc@1"]
                                            for i in sub]) + (len(sub),)
    reg = [i for i in ids if "region" in s_run[i] and "region" in s_base[i]]
    for k in ("acc@1", "acc@5", "mrr"):
        if reg:
            res[f"region_{k}"] = boot([s_run[i]["region"][k]
                                       - s_base[i]["region"][k] for i in reg])
    return res


def log_sites(projects: list[str], limit: int) -> dict:
    """Detection site vs cause, measured with no model in the loop."""
    import logs
    import tools as T
    res = {}
    for p in projects:
        bench = sorted(load_bench(p), key=lambda b: b["fix_time"])
        n_dev = json.load((OUT / f"{p}-summary.json").open())["n_dev"]
        ev = bench[n_dev:]
        random.Random(42).shuffle(ev)
        c = defaultdict(int)
        for b in ev[:limit] if limit else ev:
            c["n"] += 1
            events = logs.select_events(b["query_text"])
            if not events:
                continue
            c["with_events"] += 1
            ws = T.Workspace(p, b["snapshot_sha"], b["query_text"], {}, {}, 0,
                             b["issue_key"], set(), {}, [])
            idx = ws.log_index()
            sites = [m["file"] for e in sorted(events, key=lambda e: -e["score"])[:6]
                     for m in idx.match(e["line"], k=2)]
            if not sites:
                continue
            gold = set(b["gold_files"])
            c["matched"] += 1
            c["site_is_gold"] += bool(gold & set(sites))
            c["top_site_is_gold"] += sites[0] in gold
            if not b["gold_named_in_text"]:
                c["hard_matched"] += 1
                c["hard_site_is_gold"] += bool(gold & set(sites))
        c = dict(c)
        if c.get("matched"):
            c["share_site_is_gold"] = round(c["site_is_gold"] / c["matched"], 4)
            c["share_site_not_gold"] = round(1 - c["share_site_is_gold"], 4)
        res[p] = c
        print(p, c, flush=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run")
    ap.add_argument("--base", default="")
    ap.add_argument("--log-sites", action="store_true")
    ap.add_argument("--project", action="append")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.log_sites:
        projects = args.project or ["kafka", "mariadb", "mongodb", "qt"]
        res = log_sites(projects, args.limit)
        path = OUT / "c7-log-sites.json"
        path.write_text(json.dumps({"limit": args.limit, "seed": 42,
                                    "per_project": res}, indent=1),
                        encoding="utf-8")
        print(f"-> {path}")
        return 0
    if not args.run:
        ap.error("--run is required unless --log-sites")

    run = load_rows(Path(args.run))
    s_run = {i: score_row(r) for i, r in run.items()}
    out = {"run": args.run, "health": health(Path(args.run)),
           "summary": summarise(s_run)}
    print(json.dumps(out["health"], indent=1))
    if args.base:
        base = load_rows(Path(args.base))
        s_base = {i: score_row(r) for i, r in base.items()}
        ids = set(run) & set(base)
        out["base"] = args.base
        out["health_base"] = health(Path(args.base))
        out["summary_run_paired"] = summarise({i: s_run[i] for i in ids})
        out["summary_base_paired"] = summarise({i: s_base[i] for i in ids})
        out["paired_run_minus_base"] = paired(run, base, s_run, s_base)
    path = OUT / f"c7-coverage-{Path(args.run).stem}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["summary"]["all"], indent=1))
    if args.base:
        print(json.dumps(out["paired_run_minus_base"], indent=1))
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
