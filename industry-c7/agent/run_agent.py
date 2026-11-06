"""Batch runner for the localization agent.

Restart-safe: ids already in the output file are skipped, so a killed run
resumes without repeating work.Each instance writes one result row and one
full transcript, so every reported number can be traced to the exact
conversation that produced it.

Cost is recorded per instance (LLM calls, prompt/completion tokens, wall
seconds, tool calls), because the paper's industrial argument is about
what accuracy costs, not accuracy alone.

Scoring population: the evaluation split loaded through
localize.load_bench, so the agent runs on exactly the scored set every
baseline is scored on (scripts/scored_set.py owns the rule). Default is
the seeded 200/project sample used by the dense and noise experiments;
--full runs the whole split.

Instances whose gold is only test files are already gone by then. They are
dropped because a hit there means retrieving the test file the fix edited,
not localizing a defect -- NOT because they are unanswerable. They sit in
the ranking universe and are in fact easier than average, so removing them
moves our own numbers down.

Usage:
    python industry-c7/agent/run_agent.py --workers 14
    python industry-c7/agent/run_agent.py --workers 20 --full
    python industry-c7/agent/run_agent.py --project kafka --limit 20
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import threading
from itertools import zip_longest
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent as A  # noqa: E402
import tools as T  # noqa: E402
from baselines import ARMS  # noqa: E402
from localize import (BENCH, OUT, PROJECTS, evaluate,  # noqa: E402
                      load_bench, load_support, parse_iso_epoch)

P = ("kafka", "mariadb", "mongodb", "qt")
AGENT_OUT = Path(__file__).resolve().parents[1] / "data/agent"
ROOT_LLM = Path(__file__).resolve().parents[1] / "data/llm"
SEED_SAMPLE, SAMPLE_N = 42, 200
# --arm lc only. Built once and shared: the client is thread-safe and a
# per-instance one would open a new connection pool for every issue.
_LC_MODEL = None


def lc_model(seed: int):
    """The chat model for the LangGraph arm, from C7_LLM_URL.

    Any OpenAI-compatible server: the cluster vLLM, or LM Studio on this
    laptop for a pilot. max_tokens is the per-response cap, NOT the
    context -- a local server with a large reasoning budget will spend it
    here, which is why the pilot pins it.
    """
    global _LC_MODEL
    if _LC_MODEL is None:
        from langchain_openai import ChatOpenAI
        base = os.environ.get("C7_LLM_URL")
        if not base:
            raise SystemExit("--arm lc needs C7_LLM_URL "
                             "(e.g. http://localhost:1235/v1)")
        _LC_MODEL = ChatOpenAI(
            model=A.MODEL, base_url=base,
            api_key=os.environ.get("C7_LLM_KEY") or "not-needed",
            temperature=0, seed=seed, timeout=1200, max_retries=2,
            # the same thinking switch agent.py uses, so the two arms are
            # not quietly served under different settings
            extra_body={"chat_template_kwargs":
                        {"enable_thinking": A.ENABLE_THINKING}},
            max_completion_tokens=int(os.environ.get("C7_MAX_TOKENS")
                                      or 1500 + A.THINK_HEADROOM))
    return _LC_MODEL

_lock = threading.Lock()
_done = 0
# Circuit breaker. Once the server is gone every instance fails in about a
# second and writes a lexical-fallback row, so 24 workers can burn through
# the whole remaining population in minutes. Resume would retry them all,
# but there is nothing to be gained by producing them: stop instead.
_consec_llm_err = 0
_ABORT = threading.Event()
ABORT_AFTER = 20


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _sample_keys(project, rng):
    """The seeded 200/project draw, reproduced exactly as first run.

    The draw predates the scored set, so it is taken on the unfiltered
    benchmark at the original dev boundary and only then intersected with
    the scored set. Drawing on the filtered list instead would change the
    list length, hence the indices, hence the sample -- it moves 213 of the
    790 already-run instances. The sample must not shift under results that
    are already reported.
    """
    raw = sorted((json.loads(l) for l in
                  (BENCH / f"{project}.jsonl").open(encoding="utf-8")),
                 key=lambda b: b["fix_time"])
    summary = json.load((OUT / f"{project}-summary.json").open())
    n_dev = (summary.get("pre_scored_set") or summary)["n_dev"]
    ev = raw[n_dev:]
    idx = sorted(rng.sample(range(len(ev)), min(SAMPLE_N, len(ev))))
    return {ev[i]["issue_key"] for i in idx}



def build_seeds(row: dict, rid: str, source: str, tree_rank: dict) -> list:
    """The candidate files the agent starts from.

    `cond_ours` is the retrieval layer alone and is what every reported
    number so far used. `fused` interleaves three signals that fail on
    DIFFERENT instances:

      retrieval (cond_ours)   lexical + memory over file content
      file-tree LLM           reasons about where code belongs, and finds
                              a gold file in 37% of the instances the
                              agent misses entirely
      memory ranking          past incidents, 12.6% of those same misses

    Measured seed recall over 4,409: 0.801 -> 0.918, and on hard
    instances 0.638 -> 0.845. Taking cond_ours 30 deep instead of 20
    changes nothing (0.801 -> 0.801), which is why this is a diversity
    fix and not a depth one.

    Interleaved rather than concatenated: the agent reads the list in
    order and its attention falls off, so a signal appended at position
    21 would be seen far less than one at position 3.
    """
    base = list(row["rankings"]["cond_ours"][:20])
    if source != "fused":
        return base
    tree = [f for f in (tree_rank.get(rid) or [])][:10]
    mem = list((row["rankings"].get("memory_bm25") or [])[:10])
    out, seen = [], set()
    for group in zip_longest(base, tree, mem):
        for f in group:
            if f and f not in seen:
                seen.add(f)
                out.append(f)
    return out[:30]

def build_population(projects, limit=0, full=False):
    """The evaluation split, drawn from the scored set.

    Rows come from localize.load_bench, so the exclusion rule and the
    dev/eval boundary are the ones every other system uses. Slicing the
    UNFILTERED benchmark with the adjusted n_dev walks the boundary
    backwards and pulls dev instances into eval -- 24 of them on mongodb.
    """
    rng = random.Random(SEED_SAMPLE)
    pop = []
    for p in projects:
        bench = {b["issue_key"]: b for b in load_bench(p)}
        rows = [json.loads(l) for l in
                (OUT / f"{p}-instances.jsonl").open(encoding="utf-8")]
        rows.sort(key=lambda r: r["fix_time"])
        n_dev = json.load((OUT / f"{p}-summary.json").open())["n_dev"]
        ev_bench = sorted(bench.values(), key=lambda b: b["fix_time"])[n_dev:]
        if full:
            keys = {b["issue_key"] for b in ev_bench}
        else:
            keys = _sample_keys(p, rng) & {b["issue_key"] for b in ev_bench}
        by_key = {r["issue_key"]: r for r in rows}
        for k in sorted(keys):
            b, r = bench[k], by_key.get(k)
            if r is None:
                continue
            pop.append((p, b, r))
    rng2 = random.Random(7)
    rng2.shuffle(pop)          # interleave projects for even partial coverage
    return pop[:limit] if limit else pop


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", action="append", choices=list(P))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--full", action="store_true",
                    help="run the whole evaluation split instead of the "
                         "seeded %d/project sample" % SAMPLE_N)
    ap.add_argument("--version", type=int, default=2, choices=(2, 3),
                    help="3 requires a causal_chain in the submission and "
                         "walks the backward hop in phase 0 (T10/T11). "
                         "Default stays 2 so an unflagged re-run cannot "
                         "silently change what the reported numbers mean.")
    ap.add_argument("--arm", default="ours",
                    choices=["ours", "lc"] + sorted(ARMS),
                    help="T25. 'locagent' and 'cosil' are reimplementations "
                         "of the two published agentic localizers on our "
                         "graph layer; neither runs on this benchmark as "
                         "released (both are Python-AST only). They get the "
                         "same model, snapshot, report and turn budget, and "
                         "no incident memory. See agent/BASELINES.md. "
                         "'lc' is our own agent rebuilt on LangGraph, with "
                         "the full run capture of agent/lc_trace.py.")
    ap.add_argument("--repo-tree", action="store_true",
                    help="Put the repository structure in phase 0. The "
                         "agent calls list_dir 0.07 times per run, so it "
                         "never sees the codebase as a shape; a plain LLM "
                         "given only the file tree finds a gold file in "
                         "37%% of the instances the agent misses entirely.")
    ap.add_argument("--seed-source", default="cond_ours",
                    choices=("cond_ours", "fused"),
                    help="What the agent's starting candidates are built "
                         "from. 'cond_ours' is the retrieval layer alone, "
                         "the original behaviour. 'fused' adds the "
                         "file-tree LLM pass and the memory ranking, which "
                         "lifts seed recall 0.801 -> 0.918 (hard 0.638 -> "
                         "0.845) because they fail on different instances; "
                         "taking cond_ours 30 deep instead gains nothing, "
                         "so the gap is signal diversity, not depth.")
    ap.add_argument("--subset", default="",
                    help="JSON file with an 'ids' list of project:issue_key, "
                         "from scripts/baseline_sample.py. Restricts the run "
                         "to that fixed population so the baselines and every "
                         "existing system are scored on identical instances.")
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tag", default="main")
    ap.add_argument("--shuffle-seeds", action="store_true",
                    help="validity check: randomise the lexical seed order "
                         "handed to the agent (LLM4FL report up to 22%% Top-1 "
                         "sensitivity to initial ordering)")
    args = ap.parse_args()
    projects = args.project or list(P)
    AGENT_OUT.mkdir(parents=True, exist_ok=True)
    (AGENT_OUT / "transcripts").mkdir(exist_ok=True)
    out_path = AGENT_OUT / f"agent-{args.tag}.jsonl"

    pop = build_population(projects, args.limit, args.full)
    if args.subset:
        # The population is fixed on disk before any GPU time is spent, so a
        # later edit to the sampler cannot silently move the instances a
        # reported number was measured on.
        keep = set(json.loads(Path(args.subset).read_text(
            encoding="utf-8"))["ids"])
        pop = [x for x in pop if f"{x[0]}:{x[1]['issue_key']}" in keep]
        missing = len(keep) - len(pop)
        if missing:
            print(f"WARNING: {missing} of {len(keep)} subset ids are not in "
                  f"this population (wrong --project or --full flag?)",
                  flush=True)

    # Resume keeps only instances that SUCCEEDED. An errored row used to
    # count as done, so anything in flight when the server hit its walltime
    # was skipped forever on resume -- the one failure mode that a
    # restart-safe runner exists to prevent. Errored rows are dropped here
    # (the file is rewritten through a temp + rename, with a .bak kept) so
    # the ids stay unique and those instances are retried.
    done, kept, dropped = set(), [], 0
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            # "llm_error" is a DEAD SERVER, not an agent outcome. On that
            # path run_instance does not raise: it breaks out of the loop
            # and returns a ranking built from the lexical seed, so the row
            # carries error=None and looks finished. Keeping it would bank
            # a fallback ranking as a real result and never retry it --
            # exactly what happens to everything in flight when the vLLM
            # job hits its walltime. max_turns and no_tool_call are real
            # agent outcomes and are kept.
            if r.get("error") or r.get("stop_reason") == "llm_error":
                dropped += 1
                continue
            if r["id"] in done:        # belt and braces: never double count
                continue
            done.add(r["id"])
            kept.append(line.rstrip("\n"))
        if dropped:
            out_path.replace(out_path.with_suffix(".jsonl.bak"))
            tmp = out_path.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""),
                           encoding="utf-8")
            tmp.replace(out_path)
            print(f"resume: dropped {dropped} errored row(s) for retry; "
                  f"previous file kept as {out_path.name}.bak", flush=True)
    todo = [x for x in pop if f"{x[0]}:{x[1]['issue_key']}" not in done]
    print(f"population={len(pop)} full={args.full} arm={args.arm} "
          f"v{args.version} "
          f"done={len(done)} todo={len(todo)} workers={args.workers} "
          f"seed={args.seed} shuffle_seeds={args.shuffle_seeds}", flush=True)

    support = {p: load_support(p, PROJECTS[p]["key_prefix"]) for p in projects}
    # The file-tree LLM pass, keyed by instance. It scores 0.558 Acc@1 on
    # its own against the agent's 0.687, but it finds a gold file in 37% of
    # the instances the agent misses ENTIRELY, because it reasons over the
    # repository structure while the agent searches lexically. Loaded only
    # for --seed-source=fused so the default run is byte-identical.
    tree_rank: dict = {}
    if args.seed_source == "fused":
        f = ROOT_LLM / "scored-a2.jsonl"
        if not f.exists():
            print(f"--seed-source=fused needs {f}", file=sys.stderr)
            return 1
        for line in f.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            tree_rank[f"{r['project']}:{r['issue_key']}"] = r.get("ranking") or []
        print(f"seed source: fused (file-tree LLM for {len(tree_rank)} instances)")
    trace_dir = AGENT_OUT / "runs" / args.tag if args.arm == "lc" else None
    if args.arm == "lc":
        import lc_agent as LC  # noqa: F841 - local: langchain_openai is
        globals()["LC"] = LC   # not installed on the cluster side
        trace_dir.mkdir(parents=True, exist_ok=True)
        print(f"full run capture -> {trace_dir}")
    fcaches = {p: {} for p in projects}
    commit = git_commit()
    fh = out_path.open("a", encoding="utf-8")
    t0 = time.time()
    agg = {"calls": 0, "in": 0, "out": 0}

    def work(item):
        global _done, _consec_llm_err
        if _ABORT.is_set():
            return
        proj, b, row = item
        rid = f"{proj}:{b['issue_key']}"
        mem, dup, created, _preds = support[proj]
        started = time.time()
        try:
            seeds = build_seeds(row, rid, args.seed_source, tree_rank)
            if args.shuffle_seeds:
                random.Random(hash(rid) & 0xffff).shuffle(seeds)
            ws = T.Workspace(
                proj, b["snapshot_sha"], b["query_text"], mem, dup,
                parse_iso_epoch(b.get("created")) or created.get(b["issue_key"])
                or b["fix_time"], b["issue_key"], set(b["fix_shas"]),
                fcaches[proj], seeds)
            if args.arm == "ours":
                res = A.run_instance(ws, seed=args.seed, version=args.version,
                                     repo_tree=args.repo_tree)
            elif args.arm == "lc":
                res = LC.run_lc(ws, seed=args.seed, model=lc_model(args.seed),
                                repo_tree=args.repo_tree, trace_dir=trace_dir)
            else:
                res = ARMS[args.arm](ws, seed=args.seed)
            err = None
        except Exception as e:  # noqa: BLE001 - one bad instance must not stop the run
            res, err = None, f"{type(e).__name__}: {e}"
        wall = round(time.time() - started, 1)
        with _lock:
            if res is not None and res.get("stop_reason") == "llm_error":
                _consec_llm_err += 1
                if _consec_llm_err >= ABORT_AFTER and not _ABORT.is_set():
                    _ABORT.set()
                    print(f"\nABORT: {_consec_llm_err} consecutive LLM "
                          f"failures. The server is gone (walltime, or the "
                          f"tunnel dropped). Completed work is safe; rerun "
                          f"the same command against a new job to resume.",
                          flush=True)
            elif res is not None:
                _consec_llm_err = 0
        if _ABORT.is_set() and res is not None \
                and res.get("stop_reason") == "llm_error":
            return                      # do not bank a fallback ranking
        gold = b["gold_files"]
        if res is None:
            rowout = {"id": rid, "project": proj, "issue_key": b["issue_key"],
                      "error": err, "wall_s": wall}
        else:
            rowout = {
                "id": rid, "project": proj, "issue_key": b["issue_key"],
                "hard": not b["gold_named_in_text"], "gold_files": gold,
                "ranking": res["ranking"], "agent_ranking": res["agent_ranking"],
                "lexical_seed": res["lexical_seed"],
                "metrics": evaluate(res["ranking"], gold),
                "metrics_agent_only": evaluate(res["agent_ranking"], gold),
                "metrics_lexical": evaluate(res["lexical_seed"], gold),
                "stop_reason": res["stop_reason"], "rationale": res["rationale"],
                "n_notes": len(res["notes"]), "n_tool_calls": len(res["tool_calls"]),
                "tools_used": [c["tool"] for c in res["tool_calls"]],
                "cost": {"llm_calls": res["usage"]["calls"],
                         "prompt_tokens": res["usage"]["in"],
                         "completion_tokens": res["usage"]["out"],
                         "wall_s": wall},
                "resolver": res.get("resolver", {}),
                "arm": res.get("arm", "ours"),
                # Baselines only. `empty` is CoSIL's own metric: a run that
                # names no candidate at all. `ranking_fused` applies the
                # lexical fallback \sys{} gets, so nobody can argue the gap
                # is our safety net rather than the search strategy.
                **({"empty": res["empty"],
                    "ranking_fused": res["ranking_fused"],
                    "metrics_fused": evaluate(res["ranking_fused"], gold),
                    # Arm-specific diagnostics. Without these a stage that
                    # silently did nothing is indistinguishable from one
                    # that ran and found nothing, which is how a crippled
                    # baseline gets reported as a weak one.
                    **{k: res[k] for k in
                       ("file_stage", "n_iter", "n_pruned", "final_text")
                       if k in res}}
                   if "empty" in res else {}),
                "version": res.get("version", 2),
                "causal_chain": res.get("causal_chain", []),
                "prewalk_symbols": res.get("prewalk_symbols", []),
                "seed": args.seed, "shuffled_seeds": args.shuffle_seeds,
                "seed_source": args.seed_source, "repo_tree": args.repo_tree,
                "git_commit": commit, "model": A.MODEL, "error": None}
            (AGENT_OUT / "transcripts" /
             f"{args.tag}-{rid.replace(':', '_')}.json").write_text(
                json.dumps({"id": rid, "gold_files": gold,
                            "events": res["events"], "notes": res["notes"],
                            "tool_calls": [{"tool": c["tool"], "args": c["args"]}
                                           for c in res["tool_calls"]]},
                           indent=1, default=str), encoding="utf-8")
        with _lock:
            fh.write(json.dumps(rowout, default=str) + "\n")
            fh.flush()
            _done += 1
            if res:
                agg["calls"] += res["usage"]["calls"]
                agg["in"] += res["usage"]["in"]
                agg["out"] += res["usage"]["out"]
            if _done % 10 == 0 or _done == len(todo):
                el = time.time() - t0
                rate = _done / el * 60
                print(f"  {_done}/{len(todo)}  {el / 60:.1f}min  "
                      f"{rate:.1f}/min  eta={(len(todo) - _done) / max(rate, .01):.0f}min"
                      f"  tok_in={agg['in'] / 1e6:.1f}M", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    el = time.time() - t0
    print(f"finished {_done} in {el / 60:.1f} min; "
          f"calls={agg['calls']} in={agg['in'] / 1e6:.2f}M out={agg['out'] / 1e6:.2f}M",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
