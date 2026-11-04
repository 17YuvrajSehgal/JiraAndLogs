"""LocAgent-style and CoSIL-style agentic baselines (T25, Mahsa's point 3).

Neither published system runs on this benchmark. Both parse Python with the
`ast` module and both are driven by the SWE-bench harness; every project
here is Java, Scala, C or C++, and every instance is a Jira ticket with a
log bundle rather than a GitHub issue. So this module re-implements their
SEARCH STRATEGIES on our tree-sitter graph layer, exactly as the paper
already says "BRTracer-style" for a reimplemented IR baseline. They are
named LocAgent-style and CoSIL-style throughout and are never claimed to be
the published systems. BASELINES.md records every deviation.

What is held constant against \\sys{}: the model (one served Qwen3.8-27B),
temperature 0, the seed, the snapshot, and the issue report WITH its logs.
What differs is only what each system does with them.

What the baselines deliberately do NOT get, because neither design has it:

  * `recall_incidents`. Resolved-incident memory is the thing being
    isolated. LocAgent and CoSIL have no history signal at all.
  * the phase-0 pre-searches and the pre-walked backward hop. That
    scaffolding is ours; handing it over would measure our harness twice.
  * a structured `submit_ranking` tool. Both papers parse a free-text
    answer, and CoSIL's Table II reports LocAgent's EMPTY RATE at 13-22%
    with Qwen models for exactly that reason. Giving them our tool-call
    submission would repair a weakness the literature measures. CoSIL gets
    its own fix for it (reflective alignment); LocAgent does not, because
    it does not have one. If this port is faithful we should see the same
    ordering of empty rates, which is a free check that it is not broken.

Both arms return the same dict shape as agent.run_instance, so scoring,
transcript storage and the resume logic need no changes.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent as A  # noqa: E402
import tools as T  # noqa: E402
from codegraph import Graph  # noqa: E402

LIST_LEN = A.LIST_LEN
MAX_TOOL_CHARS = A.MAX_TOOL_CHARS

# LocAgent reports 6-9 interaction rounds (their Table 5). We give it our own
# MAX_TURNS so a loss can never be blamed on a smaller budget.
LOCAGENT_TURNS = A.MAX_TURNS
# CoSIL's own tuned value (their Table V sweeps maxIter over {1,3,5,7,10}).
COSIL_MAX_ITER = 10

CODE_BLOCK_RE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.S)
# Alternation is leftmost-first in Python, NOT longest-match, so a bare `c`
# ahead of `cpp` truncates "foo.cpp" to "foo.c" -- which then fails to
# resolve and the whole answer is scored EMPTY. That silently crippled both
# baselines on mongodb, mariadb and qt, i.e. 89% of the benchmark, and it
# looked exactly like the empty rate the literature reports. Longest
# extensions first, and \b so a prefix can never win on its own.
PATH_RE = re.compile(
    r"([\w./+-]+\.(?:scala|java|hpp|cpp|qml|idl|inl|yy|mm|cc|ic|h|c)\b)")


# ---------------------------------------------------------------------------
# shared plumbing
# ---------------------------------------------------------------------------
def _chat(messages, tools, usage, events, seed, label, max_tokens=1500):
    """One model call, with usage and transcript accounting."""
    resp = A.call_llm(messages, tools, seed=seed, max_tokens=max_tokens)
    if "error" in resp:
        events.append({"type": "error", "stage": label,
                       "error": resp["error"]})
        return None
    usage["calls"] += 1
    u = resp.get("usage") or {}
    usage["in"] += u.get("prompt_tokens", 0) or 0
    usage["out"] += u.get("completion_tokens", 0) or 0
    msg = resp["choices"][0].get("message", {}) or {}
    events.append({"type": "assistant", "stage": label,
                   "content": (msg.get("content") or "")[:1500],
                   "tool_calls": [{"name": (tc.get("function") or {}).get("name"),
                                   "args": A._args_of(tc)}
                                  for tc in A._tool_calls_of(msg)]})
    return msg


def parse_locations(text: str, ws) -> list[str]:
    """Pull file paths out of a free-text answer, in the order given.

    Both papers parse an unstructured final answer. We prefer a fenced code
    block when there is one, as their prompts ask for, and fall back to the
    whole message. A message with no parseable path is an EMPTY result and
    is scored as a miss, which is how CoSIL defines its empty rate.
    """
    blocks = CODE_BLOCK_RE.findall(text or "")
    hay = "\n".join(blocks) if blocks else (text or "")
    out, stats = [], {}
    for raw in PATH_RE.findall(hay):
        f = A._resolve(raw, ws, stats)
        if f and f not in out:
            out.append(f)
    return out[:LIST_LEN]


def _finish(ws, arm, agent_list, events, usage, stop, extra=None):
    """Common return shape. The baseline's OWN ranking is the headline.

    `ranking_fused` applies the same lexical fallback \\sys{} gets, so a
    reviewer can check that our safety net is not what produced the gap.
    It is reported beside the faithful number, never instead of it.
    """
    agent_list = agent_list[:LIST_LEN]
    fused = (A.fuse(agent_list, ws.seed_candidates)[:LIST_LEN]
             if agent_list else list(ws.seed_candidates[:LIST_LEN]))
    return {"ranking": agent_list, "agent_ranking": agent_list,
            "ranking_fused": fused,
            "lexical_seed": ws.seed_candidates[:LIST_LEN],
            "empty": not agent_list,
            "notes": ws.notes, "tool_calls": ws.calls, "stop_reason": stop,
            "rationale": "", "usage": usage, "resolver": {},
            "events": events, "seed": usage.get("seed", 42),
            "version": 0, "arm": arm, "causal_chain": [],
            "prewalk_symbols": [], **(extra or {})}


# ---------------------------------------------------------------------------
# LocAgent-style
# ---------------------------------------------------------------------------
LOCAGENT_TOOLS = [
    {"type": "function", "function": {
        "name": "search_entity",
        "description": ("Search the codebase by keyword and return matching "
                        "entities (files, classes, functions) with their code "
                        "snippets. Entity ids have the form "
                        "path/to/File.java:Class.method."),
        "parameters": {"type": "object", "properties": {
            "keywords": {"type": "array", "items": {"type": "string"},
                         "description": "Terms, symbol names or identifiers."}},
            "required": ["keywords"]}}},
    {"type": "function", "function": {
        "name": "traverse_graph",
        "description": ("Breadth-first traversal of the code graph from one "
                        "or more entities. Choose the direction, the number "
                        "of hops, and which entity and relation types to "
                        "follow. One call can cover several hops."),
        "parameters": {"type": "object", "properties": {
            "start_entities": {"type": "array", "items": {"type": "string"}},
            "direction": {"type": "string",
                          "enum": ["upstream", "downstream", "both"]},
            "traverse_hops": {"type": "integer"},
            "entity_type_filter": {"type": "array",
                                   "items": {"type": "string"}},
            "dependency_type_filter": {"type": "array",
                                       "items": {"type": "string"}}},
            "required": ["start_entities"]}}},
    {"type": "function", "function": {
        "name": "retrieve_entity",
        "description": ("Full attributes of entities by id: file path, line "
                        "numbers and complete code."),
        "parameters": {"type": "object", "properties": {
            "entity_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["entity_ids"]}}},
]

# Their Figure 8, with the Python-specific wording replaced by this
# benchmark's. The four CoT steps and the output format are unchanged.
LOCAGENT_SYSTEM = """You are a software maintenance assistant doing code localization.

## Step 1: Categorize and Extract Key Problem Information
- Classify the issue: bug report, feature request, performance issue or security issue.
- Extract keywords: error messages, symbol names, stack frames, file names.
- Use extracted keywords and line numbers to search for relevant code references for additional context.

## Step 2: Locate Referenced Modules
- Accurately determine specific modules.
  - Explore the repo to familiarize yourself with its structure.
  - Analyze the described execution flow to identify specific modules or components being referenced.
- Pay special attention to distinguishing between modules with similar names using context and described execution flow.
- Output Format for collected relevant modules:
  - Use the format 'file_path:QualifiedName'.
  - E.g. for a method `tick` in the `DistributedHerder` class located in
    `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/distributed/DistributedHerder.java`,
    represent it as that path followed by ':DistributedHerder.tick'.

## Step 3: Analyze and Reproduce the Problem
- Clarify the purpose of the issue.
  - If expanding capabilities: identify where and how to incorporate new behavior.
  - If addressing unexpected behavior: focus on localizing modules containing potential bugs.
- Reconstruct the execution flow.
  - Identify main entry points triggering the issue.
  - Trace function calls, class interactions, and sequences of events.
  - Identify potential breakpoints causing the issue.
  Important: keep the reconstructed flow focused on the problem.

## Step 4: Locate Areas for Modification
- Locate specific files, functions, or lines of code requiring changes.
- Consider upstream and downstream dependencies that may affect or be affected by the issue.
- Think thoroughly: list multiple potential solutions and consider edge cases.

## Output Format for Final Results:
Your final output should list the locations requiring modification, wrapped with triple backticks ```
Each location should include the file path, class name (if applicable), function name, or line numbers, ordered by importance.
Your answer would better include about 5 files.

### Examples:
```
full_path1/file1.java
line: 10
class: MyClass1
function: my_function1

full_path2/file2.cpp
line: 76
function: MyClass2::my_function2
```

Return just the location(s)."""


def _locagent_dispatch(g: Graph, ws, name: str, args: dict) -> dict:
    if name == "search_entity":
        kws = args.get("keywords") or []
        if isinstance(kws, str):
            kws = [kws]
        found, seen = [], set()
        for kw in [str(k) for k in kws][:6]:
            for f, lno, _t in ws._grep(kw.strip())[:8]:
                ent = next((e for e in g.entities_of(f)
                            if e["line"] <= lno <= e["end"]), None)
                ent = ent or {"id": f, "type": "file", "file": f,
                              "name": f.rsplit("/", 1)[-1], "line": 1}
                if ent["id"] in seen:
                    continue
                seen.add(ent["id"])
                found.append({"entity_id": ent["id"], "type": ent["type"],
                              "file": ent["file"], "line": ent["line"],
                              "preview": _preview(g, ws, ent)})
        if not found:
            # LocAgent's lowest index tier is BM25 over entity contents.
            for h in ws.search_text(" ".join(str(k) for k in kws),
                                    k=8).get("hits", []):
                found.append({"entity_id": f"{h['file']}:{h['best_region']}",
                              "type": "function", "file": h["file"],
                              "line": 0, "preview": "",
                              "matched_terms": h.get("matched_terms", [])})
        return {"keywords": kws, "n_found": len(found), "entities": found[:20]}
    if name == "traverse_graph":
        start = args.get("start_entities") or []
        if isinstance(start, str):
            start = [start]
        rels = {str(r).lower() for r in
                (args.get("dependency_type_filter") or
                 ["contain", "import", "invoke", "inherit"])}
        types = {str(t).lower() for t in (args.get("entity_type_filter") or [])}
        return g.traverse([str(s) for s in start], rels,
                          str(args.get("direction") or "downstream").lower(),
                          args.get("traverse_hops") or 1, types)
    if name == "retrieve_entity":
        ids = args.get("entity_ids") or []
        if isinstance(ids, str):
            ids = [ids]
        out = []
        for eid in [str(i) for i in ids][:6]:
            ent = g.resolve(eid)
            if ent is None:
                out.append({"entity_id": eid, "error": "no such entity"})
                continue
            out.append({"entity_id": ent["id"], "type": ent["type"],
                        "file": ent["file"], "start_line": ent["line"],
                        "end_line": ent["end"],
                        "code": g.body_of(ent)[:2600]})
        return {"entities": out}
    return {"error": f"unknown tool {name}"}


def _preview(g: Graph, ws, ent: dict) -> str:
    if ent["type"] == "file":
        return ", ".join(e["name"] for e in g.entities_of(ent["file"])[:12])
    return g.body_of(ent)[:400]


def run_locagent(ws: T.Workspace, seed: int = 42,
                 max_turns: int = LOCAGENT_TURNS) -> dict:
    """LocAgent's graph-guided loop: three tools, four-step CoT, free text."""
    g = Graph(ws)
    usage = {"in": 0, "out": 0, "calls": 0, "seed": seed}
    user = (f"Project: {ws.project}\n\n"
            f"=== ISSUE REPORT (with logs) ===\n{ws.query_text[:18000]}\n\n"
            f"Please localize the code that must change to resolve this "
            f"issue. Source files in this repository end in "
            f"{', '.join(T.PROJECTS[ws.project]['src_ext'])}.")
    messages = [{"role": "system", "content": LOCAGENT_SYSTEM},
                {"role": "user", "content": user}]
    events = [{"type": "system", "content": LOCAGENT_SYSTEM},
              {"type": "user", "content": user}]
    answer, stop = "", "max_turns"

    for turn in range(max_turns):
        if turn == max_turns - 1:
            messages.append({"role": "user", "content":
                             "Stop searching. Give the final locations now, "
                             "in the output format, wrapped in triple "
                             "backticks."})
        msg = _chat(A.trim_history(messages), LOCAGENT_TOOLS, usage, events,
                    seed, f"turn{turn}")
        if msg is None:
            stop = "llm_error"
            break
        tcs = A._tool_calls_of(msg)
        content = msg.get("content") or ""
        if not tcs:
            answer = content
            stop = "answered"
            break
        messages.append({"role": "assistant", "content": content,
                         "tool_calls": tcs})
        for tc in tcs:
            name = (tc.get("function") or {}).get("name") or ""
            args = A._args_of(tc)
            res = _locagent_dispatch(g, ws, name, args)
            ws.calls.append({"tool": name, "args": args, "result": res})
            payload = json.dumps(res, default=str)[:MAX_TOOL_CHARS]
            events.append({"type": "tool", "turn": turn, "name": name,
                           "args": args, "result": payload[:2500]})
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                             "name": name, "content": payload})
    else:
        answer = ""

    if not answer:
        # the loop ended on the budget: the last assistant message is the
        # answer if it had one, which is how a free-text system degrades.
        answer = next((e.get("content") or "" for e in reversed(events)
                       if e.get("type") == "assistant"), "")
    ranked = parse_locations(answer, ws)
    return _finish(ws, "locagent", ranked, events, usage, stop,
                   {"final_text": answer[:2000]})


# ---------------------------------------------------------------------------
# CoSIL-style
# ---------------------------------------------------------------------------
COSIL_TOOLS = [
    {"type": "function", "function": {
        "name": "search_class_node",
        "description": "Get the code snippet of a class node.",
        "parameters": {"type": "object", "properties": {
            "node": {"type": "string"}}, "required": ["node"]}}},
    {"type": "function", "function": {
        "name": "search_class_function_node",
        "description": "Get the code snippet of a class member function node.",
        "parameters": {"type": "object", "properties": {
            "node": {"type": "string"}}, "required": ["node"]}}},
    {"type": "function", "function": {
        "name": "search_file_function_node",
        "description": "Get the code snippet of a static function node.",
        "parameters": {"type": "object", "properties": {
            "node": {"type": "string"}}, "required": ["node"]}}},
    {"type": "function", "function": {
        "name": "exit",
        "description": ("Terminate the iterative search and go to the "
                        "summary phase. Call this once you have enough "
                        "context to decide."),
        "parameters": {"type": "object", "properties": {}}}},
]


def _ask_text(messages, usage, events, seed, label, max_tokens=1200):
    msg = _chat(messages, [], usage, events, seed, label, max_tokens)
    return (msg.get("content") or "") if msg else ""


def _reflect(issue: str, last: str, ws, usage, events, seed, label) -> list[str]:
    """CoSIL's reflective alignment: one short independent query that
    reranks and reformats the previous answer. Their ablation puts it at
    6-10% of the system's accuracy, entirely by rescuing unparseable
    output."""
    out = _ask_text(
        [{"role": "system", "content":
          "You reformat localization results. Output ONLY file paths, one "
          "per line, most suspicious first, wrapped in triple backticks. "
          "No prose, no line numbers, no explanation."},
         {"role": "user", "content":
          f"Issue:\n{issue[:3000]}\n\nPrevious answer:\n{last[:6000]}\n\n"
          f"Rerank the candidate locations it names and output the file "
          f"paths only."}],
        usage, events, seed, label, max_tokens=600)
    return parse_locations(out, ws)


def run_cosil(ws: T.Workspace, seed: int = 42,
              max_iter: int = COSIL_MAX_ITER) -> dict:
    """CoSIL's two-stage search: file level over the module call graph, then
    iterative function-level search with a pruner, reflection at each end."""
    g = Graph(ws)
    usage = {"in": 0, "out": 0, "calls": 0, "seed": seed}
    events: list = []
    issue = ws.query_text[:14000]

    # --- Stage 1: module call graph enhanced search space reduction --------
    tree = g.repo_tree()
    pre = _ask_text(
        [{"role": "system", "content":
          "You localize issues in a code repository. Given the repository "
          "structure, name the files most likely to need changing."},
         {"role": "user", "content":
          f"Issue:\n{issue}\n\nRepository structure:\n{tree}\n\n"
          f"List up to 8 candidate file paths, one per line, in triple "
          f"backticks."}],
        usage, events, seed, "cosil.preselect")
    related = parse_locations(pre, ws)[:8]
    # first-order subgraph of the module call graph, starting from those files
    mcg = []
    for f in related:
        imps = g.imports_of(f)
        if imps:
            mcg.append(f"file: {f}\n  imports: {', '.join(imps[:12])}")
    expand = _ask_text(
        [{"role": "system", "content":
          "You refine a file-level search space using import dependencies."},
         {"role": "user", "content":
          f"Issue:\n{issue}\n\nCandidate files:\n"
          + "\n".join(related or ["(none found)"])
          + "\n\nModule call graph (import relations):\n"
          + ("\n".join(mcg) or "(no import edges resolved)")
          + "\n\nReselect and rerank the suspicious files, adding any "
            "imported module that the issue implicates. Output up to 10 "
            "file paths, one per line, in triple backticks."}],
        usage, events, seed, "cosil.expand")
    files = _reflect(issue, expand, ws, usage, events, seed,
                     "cosil.reflect_file") or parse_locations(expand, ws)
    files = (files or related)[:10]
    if not files:
        return _finish(ws, "cosil", [], events, usage, "no_file_stage",
                       {"file_stage": [], "n_iter": 0, "n_pruned": 0})

    # --- Stage 2: iterative function call graph search ----------------------
    ftree = g.file_tree(files)
    start_txt = _ask_text(
        [{"role": "system", "content":
          "You pick starting points for a call-graph search."},
         {"role": "user", "content":
          f"Issue:\n{issue}\n\nStructure of the suspicious files:\n{ftree}\n\n"
          f"Name up to 4 starting nodes as path:Class.function (or "
          f"path:function), one per line, in triple backticks."}],
        usage, events, seed, "cosil.startpoints")
    visible, context, n_pruned = [], [], 0
    for line in re.findall(r"[^\s`]+:[\w.:]+", start_txt):
        ent = g.resolve(line.strip())
        if ent and ent not in visible:
            visible.append(ent)
    if not visible:
        for f in files[:3]:
            visible.extend(e for e in g.entities_of(f)[:4])

    stop = "max_iter"
    for it in range(max_iter):
        if not visible:
            stop = "exhausted"
            break
        menu = "\n".join(f"  {e['id']}  ({e['type']})" for e in visible[:25])
        got = "\n".join(f"  {e['id']}" for e in context[:15]) or "  (none yet)"
        msg = _chat(
            [{"role": "system", "content":
              "You search a function call graph to localize an issue. Each "
              "step, select ONE accessible node to inspect using the "
              "matching tool, or call exit when you have enough context."},
             {"role": "user", "content":
              f"Issue:\n{issue[:6000]}\n\nAlready inspected:\n{got}\n\n"
              f"Accessible nodes:\n{menu}\n\nIteration {it + 1} of "
              f"{max_iter}. Select one node, or exit."}],
            COSIL_TOOLS, usage, events, seed, f"cosil.iter{it}", 400)
        if msg is None:
            stop = "llm_error"
            break
        tcs = A._tool_calls_of(msg)
        if not tcs:
            stop = "no_tool_call"
            break
        name = (tcs[0].get("function") or {}).get("name") or ""
        if name == "exit":
            stop = "exit"
            break
        target = str(A._args_of(tcs[0]).get("node") or "").strip()
        ent = g.resolve(target) or next(
            (e for e in visible if e["name"].lower() in target.lower()), None)
        if ent is None:
            # their post-processing step: ask again rather than burn the turn
            events.append({"type": "tool", "stage": f"cosil.iter{it}",
                           "name": name, "args": {"node": target},
                           "result": "unresolved node; reselect"})
            continue
        snippet = g.body_of(ent)[:2200]
        ws.calls.append({"tool": name, "args": {"node": ent["id"]},
                         "result": {"len": len(snippet)}})
        # --- pruner: one boolean call, its own short context ---------------
        verdict = _ask_text(
            [{"role": "system", "content":
              "Answer with exactly one word: True or False."},
             {"role": "user", "content":
              f"Issue:\n{issue[:2500]}\n\nCode:\n{snippet}\n\nIs this code "
              f"related to the issue? Answer True or False."}],
            usage, events, seed, f"cosil.prune{it}", 10)
        accepted = "true" in verdict.lower()[:20]
        events.append({"type": "prune", "stage": f"cosil.iter{it}",
                       "node": ent["id"], "accepted": accepted})
        visible = [v for v in visible if v["id"] != ent["id"]]
        if not accepted:
            n_pruned += 1
            continue
        context.append({**ent, "code": snippet})
        for nb in g.neighbours(ent, {"invoke", "contain", "inherit"}, "both"):
            if nb["id"] not in {v["id"] for v in visible} | \
                    {c["id"] for c in context}:
                visible.append(nb)

    # --- Step III: summarise, then reflective alignment --------------------
    ctx = "\n\n".join(f"### {c['id']}\n{c['code'][:1200]}"
                      for c in context[:10]) or "(no context collected)"
    summary = _ask_text(
        [{"role": "system", "content":
          "You give the final localization for an issue."},
         {"role": "user", "content":
          f"Issue:\n{issue}\n\nCollected context:\n{ctx}\n\nFile-level "
          f"candidates from the first stage:\n" + "\n".join(files)
          + "\n\nList the most suspicious locations, most likely first, as "
            "file paths, one per line, in triple backticks."}],
        usage, events, seed, "cosil.summary")
    ranked = _reflect(issue, summary, ws, usage, events, seed,
                      "cosil.reflect_func") or parse_locations(summary, ws)
    # CoSIL's function-level answer maps onto files; the first-stage
    # file ranking fills the tail, as its own pipeline does.
    for f in files:
        if len(ranked) >= LIST_LEN:
            break
        if f not in ranked:
            ranked.append(f)
    return _finish(ws, "cosil", ranked, events, usage, stop,
                   {"file_stage": files, "n_iter": len(context) + n_pruned,
                    "n_pruned": n_pruned, "final_text": summary[:2000]})


ARMS = {"locagent": run_locagent, "cosil": run_cosil}
