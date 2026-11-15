"""Preflight for the full-split agent run. Everything that can be checked
without the GPU, checked before the GPU is spent.

The run is one 24 h job against a queue we wait hours for, so a defect
found here costs minutes and the same defect found at hour 15 costs the
submission. Exits non-zero if anything fails.

Usage:
    python industry-c7/scripts/preflight_full_run.py [--tag v3-full]
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "agent"))

ROOT = HERE.parents[0]
AG = ROOT / "data/agent"
TAG = "v3-full"
for i, a in enumerate(sys.argv):
    if a == "--tag" and i + 1 < len(sys.argv):
        TAG = sys.argv[i + 1]

ok = fail = 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global ok, fail
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))
    ok += bool(cond)
    fail += (not cond)
    return bool(cond)


print("=== population ===")
import agent as A  # noqa: E402
import run_agent as R  # noqa: E402
import tools as T  # noqa: E402

P = list(R.P)
full = R.build_population(P, full=True)
samp = R.build_population(P)
ids = lambda pop: {f"{p}:{b['issue_key']}" for p, b, _ in pop}
check("full split is 26,544 instances", len(full) == 26544, str(len(full)))
per = {}
for p, b, _ in full:
    per[p] = per.get(p, 0) + 1
check("the split spans all 27 projects", len(per) == 27, f"{len(per)} projects")
# Pinning 27 hand-copied counts would go stale the first time anything is
# re-mined. The invariant is exact and cannot: the eval split of a project
# is its scored set minus its own dev prefix. A project silently dropping
# out, or a boundary moving, breaks this.
from localize import load_bench  # noqa: E402
mismatch = []
for q in sorted(per):
    n_scored = len(load_bench(q))
    nd = json.load((ROOT / f"data/results/{q}-summary.json").open())["n_dev"]
    if per[q] != n_scored - nd:
        mismatch.append(f"{q}: eval={per[q]} but scored-dev={n_scored - nd}")
check("every project's eval count is its scored set minus its dev prefix",
      not mismatch, "; ".join(mismatch[:3]))
# The population the agentic baselines are measured on must be reachable
# from the population the agent runs, or the paired comparison has nothing
# to pair on. This is the check that would have caught the sample being
# drawn from the whole scored set instead of the eval split.
for name in ("sample", "pilot"):
    sub = set(json.loads((ROOT / f"data/results/baseline-{name}.json")
                         .read_text(encoding="utf-8"))["ids"])
    outside = sub - ids(full)
    check(f"the baseline {name} sits inside the full split",
          not outside, f"{len(outside)} of {len(sub)} outside")
leak = 0
for p in P:
    raw = sorted((json.loads(l) for l in
                  (ROOT / f"data/benchmark/{p}.jsonl").open(encoding="utf-8")),
                 key=lambda b: b["fix_time"])
    s = json.load((ROOT / f"data/results/{p}-summary.json").open())
    nd = (s.get("pre_scored_set") or s)["n_dev"]
    dev = {b["issue_key"] for b in raw[:nd]}
    leak += len({b["issue_key"] for q, b, _ in full if q == p} & dev)
check("no dev instance in the eval population", leak == 0, f"{leak} leaked")

print("\n=== agent v3 ===")
check("run_instance accepts a version", "version" in
      A.run_instance.__code__.co_varnames)
v3p = A.SUBMIT_V3["function"]["parameters"]
check("v3 requires files AND causal_chain",
      v3p["required"] == ["files", "causal_chain"], str(v3p["required"]))
check("v2 schema untouched", A.SUBMIT["function"]["parameters"]["required"]
      == ["files"])
check("v3 offers data_flow_back",
      "data_flow_back" in [t["function"]["name"] for t in T.V3_TOOL_SCHEMAS])
check("every offered tool dispatches",
      all(t["function"]["name"] in T._DISPATCH
          for t in T.TOOL_SCHEMAS + T.V3_TOOL_SCHEMAS))
check("Workspace defaults to the v2 firewall",
      T.Workspace.__init__.__defaults__ is not None)

print("\n=== snapshots, memory, repos ===")
for p in P:
    g = ROOT.parents[0] / f"data/c7-repos"
    from localize import FULL_REPOS, PROJECTS, load_support
    check(f"{p} git dir present", FULL_REPOS[p].exists(), str(FULL_REPOS[p]))
for p in P:
    from localize import PROJECTS, load_support
    mem, dup, created, _ = load_support(p, PROJECTS[p]["key_prefix"])
    check(f"{p} memory pool loaded", len(mem) > 0, f"{len(mem)} incidents")

print("\n=== output, resume, disk ===")
out = AG / f"agent-{TAG}.jsonl"
done = 0
if out.exists():
    done = sum(1 for _ in out.open(encoding="utf-8"))
check(f"output path is writable ({out.name})",
      AG.exists() and (AG / "transcripts").exists(), str(AG))
print(f"      rows already in {out.name}: {done} (run resumes over these)")
src = (ROOT / "agent/run_agent.py").read_text(encoding="utf-8")
# This used to grep run_agent.py for the literal predicate text. The text
# was there and the check passed, while the lc arm wrote "error:<Class>",
# which that predicate does not match -- so the thing being checked was the
# spelling, not the behaviour. It now calls the predicate on the two row
# shapes that actually occur, which is what has to hold.
from localize import is_dead_row  # noqa: E402
check("resume retries errored rows instead of counting them done",
      is_dead_row({"error": None, "stop_reason": "error:OpenAIInvalidRequestError"})
      and is_dead_row({"error": None, "stop_reason": "llm_error"})
      and is_dead_row({"error": "JSONDecodeError: x"})
      and not is_dead_row({"error": None, "stop_reason": "submitted"})
      and not is_dead_row({"error": None, "stop_reason": "max_turns"})
      and "is_dead_row(r)" in src and "dropped += 1" in src,
      "a server that dies at walltime, or one 400 from the model, would "
      "otherwise bank a lexical fallback ranking as a finished result")
check("the run aborts rather than burning the population on a dead server",
      "_ABORT" in src and "ABORT_AFTER" in src)
tdir = AG / "transcripts"
# This globbed "v2-*.json" and nothing has ever been named that: transcripts
# are "<tag>-<project>_<KEY>.json". sizes came back empty, mean_kb was 0,
# need_gb was 0, and "free disk covers the transcripts" could not fail. It
# also multiplied by a hardcoded 4409 rather than the population actually
# queued. A check that cannot fail is worse than no check.
# Every transcript, not the first 400: glob order is roughly alphabetical,
# so a prefix is all "cosil-*" and those are far smaller than the agent's
# own traces. Thinking is on for this run, which the thinking-off history
# here cannot see, so treat the result as a floor.
sizes = [f.stat().st_size for f in tdir.glob("*.json")]
# MEAN_KB_FLOOR is the measured mean over the 6,409 transcripts of the
# 4-project run, now in data/archive/agent-4project/. A first run has no
# transcripts to measure, and the old code answered that case with 0 KB,
# which made the disk check unfailable. Falling back to a measured constant
# keeps it a real check on an empty directory. It is a FLOOR: those runs
# had thinking off, and reasoning traces are larger.
MEAN_KB_FLOOR = 49
mean_kb = (sum(sizes) / len(sizes) / 1024) if sizes else MEAN_KB_FLOOR
need_gb = mean_kb * len(full) / 1024 / 1024
freeb = shutil.disk_usage(str(AG)).free / 1024 ** 3
check("free disk covers the transcripts", freeb > need_gb * 2,
      f"{mean_kb:.0f} KB each x {len(full):,} = ~{need_gb:.1f} GB, "
      f"free {freeb:.0f} GB"
      + ("" if sizes else f" (no transcripts yet; floor of {MEAN_KB_FLOOR} KB)"))

print("\n=== transport ===")
spool = AG / "spool"
import time as _t
now = _t.time()
live = [f for f in (list(spool.glob("req-*.json"))
                    + list(spool.glob("resp-*.json"))
                    + list(spool.glob(".busy-*")))] if spool.exists() else []
# Files younger than 10 min belong to a run that is happening right now.
# Only older ones are leftovers that a new run would trip over.
stale = [f for f in live if now - f.stat().st_mtime > 600]
check("no STALE spool files (in-flight ones are fine)", not stale,
      f"{len(stale)} stale, {len(live) - len(stale)} in flight")
check("model name matches what the server serves",
      A.MODEL == "qwen3.8-27b", A.MODEL)
check("agent.py holds no hardcoded compute node",
      not hasattr(A, "NODE"))

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
