"""Self-check for the LangGraph rebuild. No model, no GPU.

The whole claim of this rebuild is that the mandatory steps are
STRUCTURE rather than instructions. A claim like that is worth nothing
unless something fails when the structure is removed, so these checks
drive the real graph with a stubbed model and assert on what reached it.

Usage:
    python industry-c7/agent/test_lc_agent.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "scripts"))

import lc_agent as LA  # noqa: E402
import run_agent as RA  # noqa: E402
import tools as T  # noqa: E402
from lc_store import Incident, IncidentStore  # noqa: E402
from localize import parse_iso_epoch  # noqa: E402

ok = n = 0


def chk(name, cond, detail=""):
    global ok, n
    n += 1
    ok += bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ---- the firewall, on synthetic data with a known answer -----------------
def mkinc(key, resolved, files, shas=(), toks=None):
    from collections import Counter
    return Incident(key=key, resolved=resolved, fix_shas=frozenset(shas),
                    gold_files=tuple(files),
                    toks=toks or Counter("null pointer partition".split()))


NOW = 1_000_000.0
store = IncidentStore("t", {
    "OLD-1": mkinc("OLD-1", NOW - 86400 * 10, ["a.java"]),
    "OLD-2": mkinc("OLD-2", NOW - 86400 * 400, ["b.java"]),
    "FUTURE": mkinc("FUTURE", NOW + 86400, ["leak.java"]),
    "SELF": mkinc("SELF", NOW - 10, ["self.java"]),
    "DUP": mkinc("DUP", NOW - 20, ["dup.java"]),
    "SHARED": mkinc("SHARED", NOW - 30, ["shared.java"], shas=["deadbeef"]),
})
ctx = {"cutoff": NOW, "this_key": "SELF", "this_fix_shas": frozenset(["deadbeef"]),
       "dup_cluster": "C1", "dup_of": {"DUP": "C1"}}
got = {r.incident for r in store.search("null pointer partition", limit=10, **ctx)}
chk("firewall excludes incidents resolved AFTER the report", "FUTURE" not in got)
chk("firewall excludes the issue itself", "SELF" not in got)
chk("firewall excludes a duplicate of it", "DUP" not in got)
chk("firewall excludes anything sharing a fix commit", "SHARED" not in got)
chk("admissible history survives", got == {"OLD-1", "OLD-2"}, str(sorted(got)))

res = store.search("null pointer partition", limit=10, **ctx)
by = {r.incident: r for r in res}
chk("recency weighting prefers the newer of two equal matches",
    by["OLD-1"].weight > by["OLD-2"].weight,
    f"{by['OLD-1'].weight:.4f} vs {by['OLD-2'].weight:.4f}")

big = IncidentStore("t", {
    "SMALL": mkinc("SMALL", NOW - 100, ["one.java"]),
    "REFACTOR": mkinc("REFACTOR", NOW - 100, [f"f{i}.java" for i in range(40)]),
})
w = {r.incident: r.weight for r in big.search("null pointer partition", limit=5,
                                              cutoff=NOW, this_key="X")}
chk("a one-file fix outweighs a 40-file refactor",
    w.get("SMALL", 0) > w.get("REFACTOR", 1) * 10,
    f"{w.get('SMALL', 0):.4f} vs {w.get('REFACTOR', 0):.4f}")
chk("the namespace is keyed on TIME, not identity",
    store.namespace(NOW) != store.namespace(NOW + 1))

# ---- the submission schema cannot be satisfied without evidence ----------
from pydantic import ValidationError  # noqa: E402

try:
    LA.Localization(files=[], causal_chain=[])
    chk("an empty submission is rejected", False)
except ValidationError:
    chk("an empty submission is rejected", True)
try:
    LA.Localization(files=[LA.RankedFile(path="a.java", evidence="x")],
                    causal_chain=[LA.ChainStep(step="a", cited_from="read_code")])
    chk("a one-step chain is rejected (2-6 required)", False)
except ValidationError:
    chk("a one-step chain is rejected (2-6 required)", True)
good = LA.Localization(
    files=[LA.RankedFile(path="a.java", evidence="line 42 sets it to null")],
    causal_chain=[LA.ChainStep(step="a", cited_from="read_code"),
                  LA.ChainStep(step="b", cited_from="recall_incidents")])
chk("a complete submission validates", len(good.files) == 1)

# ---- the graph itself, against a real snapshot and a stubbed model -------
pop = RA.build_population(["kafka"], limit=1, full=True)
if not pop:
    print("\nSKIP graph checks: no kafka population here")
else:
    proj, b, row = pop[0]
    mem, dup, created, _ = RA.load_support(proj, RA.PROJECTS[proj]["key_prefix"])
    ws = T.Workspace(proj, b["snapshot_sha"], b["query_text"], mem, dup,
                     parse_iso_epoch(b.get("created"))
                     or created.get(b["issue_key"]) or b["fix_time"],
                     b["issue_key"], set(b["fix_shas"]), {},
                     list(row["rankings"]["cond_ours"][:20]))
    istore = IncidentStore.from_pool(proj, mem)
    rctx = {"cutoff": ws.cutoff, "this_key": ws.issue_key,
            "this_fix_shas": frozenset(ws.fix_shas),
            "dup_cluster": dup.get(ws.issue_key), "dup_of": dup}

    gather = LA.make_preamble(ws, istore, rctx, ws.seed_candidates,
                              repo_tree="src/  (12 files)")
    import agent as A
    real = A.reformulate
    try:
        A.reformulate = lambda *a, **k: {"behaviour": "partition assignment "
                                         "returns null", "identifiers": []}
        # the decorator returns a middleware OBJECT and the hook is a
        # method on it. Calling it directly is the only way to assert on
        # what the model actually receives, which is the whole claim here.
        upd = gather.before_agent({"messages": []}, None)
    finally:
        A.reformulate = real

    chk("the preamble is registered as a before_agent hook",
        callable(getattr(gather, "before_agent", None)), str(type(gather)))
    if upd is None:
        chk("the preamble returned state updates", False, "got None")
    else:
        p = upd["prepared"]
        brief = upd["messages"][0]["content"]
        chk("preamble resolves report symbols against the snapshot",
            isinstance(p["symbols"], list))
        chk("preamble queries memory unconditionally",
            isinstance(p["recalls"], list))
        chk("preamble runs BOTH a behaviour and a title search",
            "content_hits" in p and "title_hits" in p)
        chk("preamble walks one hop back from the frames", "backward" in p)
        chk("the briefing carries the report", "ISSUE REPORT" in brief)
        chk("the briefing carries the repo structure when supplied",
            "REPOSITORY STRUCTURE" in brief)
        chk("the briefing names the seed candidates",
            "retrieval layer ranked highest" in brief)
        chk("tool calls made during the preamble are not charged to the agent",
            len(ws.calls) == 0, f"{len(ws.calls)} calls recorded")

    names = [t.name for t in LA.build_tools(ws)]
    chk("the tool surface matches the hand-rolled agent",
        set(names) == {"search_symbol", "search_text", "read_code",
                       "read_skeleton", "list_dir", "callers_of",
                       "data_flow_back", "recall_incidents"}, str(sorted(names)))

print(f"\n{ok}/{n} checks passed")
raise SystemExit(0 if ok == n else 1)
