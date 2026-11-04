"""Self-check for the two agentic baselines (T25).

Everything here runs WITHOUT the model server: the tool surface, the
free-text parser both papers rely on, and the code graph on a real
snapshot. A broken graph does not crash the arm, it quietly returns no
neighbours and the baseline looks weak for the wrong reason, which would
be a fabricated result. Run this before spending GPU time.

Usage:
    python industry-c7/agent/test_baselines.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import baselines as B  # noqa: E402
import run_agent as R  # noqa: E402
import tools as T  # noqa: E402
from codegraph import Graph  # noqa: E402
from localize import parse_iso_epoch  # noqa: E402

ok = n = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, n
    n += 1
    ok += bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"   [{detail}]" if detail else ""))


# ---- tool surface matches the papers ---------------------------------------
loc = [t["function"]["name"] for t in B.LOCAGENT_TOOLS]
cos = [t["function"]["name"] for t in B.COSIL_TOOLS]
check("LocAgent offers exactly its three unified APIs (their Table 2)",
      loc == ["search_entity", "traverse_graph", "retrieve_entity"], str(loc))

# vLLM 400s on `"tools": []` ("must not be an empty array"), so an empty
# list has to be OMITTED, not sent. CoSIL-style passes no tools on six
# staged calls (preselect, expand, two reflections, summarise, prune) and
# every one of them failed until call_llm dropped the field. Caught by a
# live probe minutes before the pilot; checked here so it cannot come back.
import json as _json  # noqa: E402

import agent as _A  # noqa: E402

_sent = {}
_real_bridge = _A._bridge_call
try:
    _A._bridge_call = lambda body, timeout: (
        _sent.update(_json.loads(body)) or '{"choices":[{"message":{}}]}')
    _A.call_llm([{"role": "user", "content": "x"}], [], retries=1)
    check("call_llm OMITS tools when the list is empty (vLLM 400s on [])",
          "tools" not in _sent and "tool_choice" not in _sent,
          str(sorted(_sent)))
    _sent.clear()
    _A.call_llm([{"role": "user", "content": "x"}],
                [{"type": "function", "function": {"name": "t"}}], retries=1)
    check("call_llm still sends tools when there are any",
          _sent.get("tools") and _sent.get("tool_choice") == "auto")
finally:
    _A._bridge_call = _real_bridge
check("CoSIL offers exactly its four search tools (their Table I)",
      cos == ["search_class_node", "search_class_function_node",
              "search_file_function_node", "exit"], str(cos))
check("traverse_graph takes direction, hops and both type filters",
      {"start_entities", "direction", "traverse_hops", "entity_type_filter",
       "dependency_type_filter"}
      <= set(B.LOCAGENT_TOOLS[1]["function"]["parameters"]["properties"]))

# The isolation that makes the comparison mean anything.
ours = {t["function"]["name"] for t in T.TOOL_SCHEMAS}
check("neither baseline is given incident memory",
      "recall_incidents" in ours
      and "recall_incidents" not in set(loc) | set(cos))
check("neither baseline is given a structured submit tool",
      not any("submit" in x for x in loc + cos))
# The seed ranking is cond_ours = retrieval PLUS memory, and search_text
# prepends it to its pool. Left on, our memory signal reaches an arm whose
# entire point is not having one. Measured on the pilot before this was
# fixed: 15.3% of search_entity calls hit that seeded tier.
check("both baseline arms opt out of the memory-seeded search pool",
      bsrc_isolate := ("ws.seed_search_pool = False" in
                       Path(__file__).with_name("baselines.py")
                       .read_text(encoding="utf-8")))
check("the main agent still uses the seeded pool (unchanged behaviour)",
      "self.seed_search_pool = True" in
      Path(__file__).with_name("tools.py").read_text(encoding="utf-8"))
check("both arms are reachable from run_agent --arm",
      set(B.ARMS) == {"locagent", "cosil"}
      and "ours" not in B.ARMS, str(sorted(B.ARMS)))

# ---- the free-text parser both papers depend on ----------------------------
LOC_ANSWER = """Looking at the trace, the fault is in the herder.

```
connect/runtime/src/main/java/org/apache/kafka/connect/runtime/distributed/DistributedHerder.java
line: 10
class: DistributedHerder
function: tick

core/src/main/scala/kafka/server/KafkaApis.scala
line: 76
function: handleFetchRequest
```
"""


class _FakeWS:
    """Just enough Workspace for the resolver: every path exists."""

    def __init__(self, files):
        self.snap = type("S", (), {"blob_of": {f: "x" for f in files},
                                   "files": list(files)})()


fw = _FakeWS(["connect/runtime/src/main/java/org/apache/kafka/connect/"
              "runtime/distributed/DistributedHerder.java",
              "core/src/main/scala/kafka/server/KafkaApis.scala"])
got = B.parse_locations(LOC_ANSWER, fw)
check("parser keeps the paper's output format, in order",
      len(got) == 2 and got[0].endswith("DistributedHerder.java")
      and got[1].endswith("KafkaApis.scala"), str(len(got)))
check("parser prefers the fenced block over surrounding prose",
      all("Looking" not in g for g in got))
check("an answer naming no path parses as EMPTY, not as a silent zero",
      B.parse_locations("I could not determine the location.", fw) == [])
# Regression: alternation is leftmost-first, so `c` ahead of `cpp` used to
# truncate every C++ path and score the answer EMPTY. Three of four
# projects are C/C++, so this quietly made both baselines look far worse
# than they are -- and it looked just like the empty rate the papers
# report, which is the way a strawman gets published.
for ext in ("cpp", "cc", "hpp", "h", "c", "java", "scala", "mm", "inl",
            "ic", "qml", "idl", "yy"):
    p = f"src/mongo/db/repl/replication_coordinator_impl.{ext}"
    check(f"a .{ext} path survives parsing whole",
          B.parse_locations(f"```\n{p}\nline: 1\n```", _FakeWS([p])) == [p],
          str(B.parse_locations(f"```\n{p}\n```", _FakeWS([p]))))
check("prose outside a fence is still parsed when there is no fence",
      B.parse_locations(
          "The bug is in core/src/main/scala/kafka/server/KafkaApis.scala.",
          fw) == ["core/src/main/scala/kafka/server/KafkaApis.scala"])

# ---- the code graph, on a real snapshot ------------------------------------
pop = R.build_population(["kafka"], limit=1)
if not pop:
    print("\nSKIP graph checks: no kafka population on this machine")
else:
    proj, b, row = pop[0]
    mem, dup, created, _ = R.load_support(proj, R.PROJECTS[proj]["key_prefix"])
    ws = T.Workspace(proj, b["snapshot_sha"], b["query_text"], mem, dup,
                     parse_iso_epoch(b.get("created"))
                     or created.get(b["issue_key"]) or b["fix_time"],
                     b["issue_key"], set(b["fix_shas"]), {},
                     list(row["rankings"]["cond_ours"][:20]))
    g = Graph(ws)
    probe = next((f for f in ws.seed_candidates if f.endswith(".java")),
                 ws.seed_candidates[0] if ws.seed_candidates else None)
    check("a probe file was found in the snapshot", probe is not None, str(probe))
    if probe:
        ents = g.entities_of(probe)
        fns = [e for e in ents if e["type"] == "function"]
        cls = [e for e in ents if e["type"] == "class"]
        check("the file parses into entities", bool(ents),
              f"{len(cls)} classes, {len(fns)} functions in {probe}")
        check("entity ids use LocAgent's path:QualifiedName form",
              all(e["id"].startswith(probe + ":") for e in ents)
              and all("." in e["id"].split(":", 1)[1] or not e.get("owner")
                      for e in fns), str(ents[0]["id"]) if ents else "")
        check("a member function is qualified by its class",
              not fns or not cls
              or any(e["id"].split(":", 1)[1].count(".") >= 1
                     for e in fns if e.get("owner")),
              next((e["id"] for e in fns if e.get("owner")), "no owned fn"))
        check("every entity resolves back from its own id",
              all(g.resolve(e["id"]) is not None for e in ents[:20]))
        imps = g.imports_of(probe)
        check("import edges resolve inside the snapshot",
              all(i in ws.snap.blob_of for i in imps), f"{len(imps)} edges")
        if fns:
            tr = g.traverse([fns[0]["id"]], {"contain", "invoke"},
                            "both", 2, set())
            check("traverse_graph returns hop levels, not a flat list",
                  "levels" in tr and tr["levels"][0]["entities"]
                  == [fns[0]["id"]],
                  f"{tr.get('n_reached')} entities over {tr.get('hops')} hops")
        tree = g.repo_tree()
        check("the repo structure tree is bounded for a prompt",
              0 < len(tree) < 12000, f"{len(tree)} chars")
        check("the file structure tree names classes and members",
              bool(g.file_tree([probe]).strip()))

    # ---- both loops end to end, against a stubbed model --------------------
    # The server is not always up, and a plumbing bug in either loop costs a
    # whole GPU job to discover. This drives the real loops with canned
    # responses: one tool call, then a final answer in the paper's format.
    import agent as A  # noqa: E402

    gold_file = probe or (b["gold_files"][0] if b["gold_files"] else "")
    answer = f"```\n{gold_file}\nline: 1\nfunction: f\n```"
    script = {"tool": 0, "prune": 0}

    def _call(fn, args):
        return {"choices": [{"message": {"content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": fn,
                          "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    def fake_llm(messages, tools, seed=42, max_tokens=1500, **kw):
        names = [t["function"]["name"] for t in tools]
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        if not names:
            # The pruner is the only stage that asks for a bare True/False.
            if "True or False" in (messages[-1].get("content") or ""):
                script["prune"] += 1
                # accept the first, reject the second: both branches run
                return {"choices": [{"message": {
                    "content": "True" if script["prune"] == 1 else "False"}}],
                    "usage": usage}
            return {"choices": [{"message": {"content": answer}}],
                    "usage": usage}
        script["tool"] += 1
        if "traverse_graph" in names:          # LocAgent-style
            return (_call("traverse_graph",
                          {"start_entities": [probe], "direction": "both",
                           "traverse_hops": 1}) if script["tool"] == 1
                    else {"choices": [{"message": {"content": answer}}],
                          "usage": usage})
        # CoSIL-style: inspect two real nodes, then exit. This drives node
        # resolution, both pruner branches and neighbour expansion before
        # the early stop, so none of those can be silently dead.
        if script["tool"] <= 2:
            ent = next((e for e in g.entities_of(probe)
                        if e["type"] == "function"), None)
            ents = [e for e in g.entities_of(probe) if e["type"] == "function"]
            pick = ents[script["tool"] - 1] if len(ents) >= script["tool"] else ent
            return _call("search_class_function_node", {"node": pick["id"]})
        return _call("exit", {})

    real = A.call_llm
    try:
        A.call_llm = fake_llm
        for arm in ("locagent", "cosil"):
            script.update(tool=0, prune=0)
            ws2 = T.Workspace(proj, b["snapshot_sha"], b["query_text"], mem,
                              dup, b["fix_time"], b["issue_key"],
                              set(b["fix_shas"]), {},
                              list(row["rankings"]["cond_ours"][:20]))
            res = B.ARMS[arm](ws2, seed=42)
            check(f"{arm}: the loop completes and returns a ranking",
                  isinstance(res.get("ranking"), list),
                  f"stop={res.get('stop_reason')} n_calls="
                  f"{res['usage']['calls']}")
            check(f"{arm}: the result has every field run_agent writes out",
                  {"ranking", "agent_ranking", "ranking_fused", "empty",
                   "lexical_seed", "usage", "events", "stop_reason", "arm",
                   "notes", "tool_calls", "resolver", "causal_chain"}
                  <= set(res), str(sorted(set(res))))
            check(f"{arm}: it parsed the model's answer, not the lexical seed",
                  res["ranking"] and res["ranking"][0] == gold_file,
                  f"got {res['ranking'][:2]}")
            check(f"{arm}: empty is False when a location was parsed",
                  res["empty"] is False)
            check(f"{arm}: the fused ranking exists and starts the same way",
                  res["ranking_fused"][:1] == res["ranking"][:1])
            if arm == "cosil":
                check("cosil: the iterative search exits early via its own "
                      "exit tool, as the paper's step II allows",
                      res["stop_reason"] == "exit", res["stop_reason"])
                check("cosil: the pruner ran and BOTH branches were taken",
                      script["prune"] >= 2 and res["n_pruned"] == 1,
                      f"{script['prune']} prune calls, "
                      f"{res['n_pruned']} rejected")
                check("cosil: accepted nodes entered the context",
                      res["n_iter"] - res["n_pruned"] >= 1,
                      f"n_iter={res['n_iter']}")
                check("cosil: the file stage produced a search space",
                      bool(res["file_stage"]), str(len(res["file_stage"])))
    finally:
        A.call_llm = real

    # An answer with no parseable path must surface as empty, not as a
    # silent fallback to our lexical ranking. CoSIL's empty rate is a
    # reported metric, so this path has to be real.
    try:
        A.call_llm = lambda *a, **k: {
            "choices": [{"message": {"content": "I cannot tell."}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        ws3 = T.Workspace(proj, b["snapshot_sha"], b["query_text"], mem, dup,
                          b["fix_time"], b["issue_key"], set(b["fix_shas"]),
                          {}, list(row["rankings"]["cond_ours"][:20]))
        res = B.run_locagent(ws3, seed=42)
        check("locagent: an unparseable answer is recorded as EMPTY",
              res["empty"] is True and res["ranking"] == [],
              str(res["ranking"][:2]))
        check("locagent: the fused arm still falls back, so both are reported",
              bool(res["ranking_fused"]))
    finally:
        A.call_llm = real

print(f"\n{ok}/{n} checks passed")
raise SystemExit(0 if ok == n else 1)
