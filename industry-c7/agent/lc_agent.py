"""REMEMBER on LangChain/LangGraph.

Same idea as agent.py -- log-guided root-cause localization with incident
memory -- rebuilt so the things our failure analysis says MUST happen are
graph structure rather than prompt text.

Why the framework earns its place here specifically
---------------------------------------------------
This project has measured the same failure four times: behaviour that is
instructed but optional gets skipped. v1 left evidence optional and 37%
of runs recorded none. v2 asked the model to walk backwards and it did so
in 1 run of 168. memory is asked for and called 0.23 times per run.
callers_of 0.01, data_flow_back 0.00.

agent.py fixes this by hand-coding a phase 0 inside run_instance. That
works but puts policy inside one 200-line function. `create_agent`
middleware makes the same guarantee declarative:

    @before_agent   runs ONCE per instance, before any model call
    @after_model    runs after EVERY model response
    response_format the submission schema, enforced by the framework

What the measurements say each piece has to do
-----------------------------------------------
GATHERING is deterministic (before_agent). Ranked by how often each
probe surfaces a gold file the current agent never finds, over the 427
it misses entirely:

    memory keyed on symbols        18.3%   <- the single best probe
    exhaustive symbol resolution   11.7%
    title search                    6.7%
    callers_of                      4.2%
    data_flow_back                  1.7%   <- not worth a turn
    read_skeleton of top-5          0.0%

    union of the top three         28.3%   (only 7.5% overlap)

JUDGING stays free. The 953 ordering failures already opened a gold file
in 63.3% of cases: they do not need more probes, they need to commit.
Failing runs already probe MORE than winning ones (search_text 4.32 vs
2.23, turn ceiling 34.4% vs 14.5%). So after_model adds a commit check,
not another search.

SEEDING is diversified. The agent's starting candidates came from one
retrieval signal covering 0.8009 of instances (0.6383 hard). Interleaving
the file-tree LLM and the memory ranking takes that to 0.9161 / 0.8420;
taking the same signal 30 deep instead of 20 changes nothing, which is
the proof that the gap is diversity rather than depth.

This module defines the agent. Running it against the benchmark is
lc_run.py, so that this file stays readable as a design.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any, Callable

from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "scripts"))

from langchain.agents import AgentState, create_agent  # noqa: E402
from langchain.agents.structured_output import ToolStrategy  # noqa: E402
from langchain.agents.middleware import (  # noqa: E402
    after_model, before_agent, wrap_model_call,
)
from langchain.tools import tool  # noqa: E402
from langchain_core.messages import HumanMessage, ToolMessage  # noqa: E402

import tools as T  # noqa: E402
from lc_store import IncidentStore  # noqa: E402

MAX_TURNS = 14
TOP_FOR_COMMIT = 3
# tool results kept verbatim before the older ones are stubbed;
# the same number agent.py uses, so the two see the same history
KEEP_FULL = 6
# the investigation tools by name. The hard stop withdraws exactly these
# and leaves whatever tool the structured-output strategy injected, so
# the model is left with one thing it can do: answer.
AGENT_TOOLS = frozenset({"search_symbol", "search_text", "read_code",
                         "read_skeleton", "list_dir", "callers_of",
                         "data_flow_back", "recall_incidents"})


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------
class TriageState(AgentState):
    """What the graph carries besides the conversation.

    `prepared` holds the deterministic evidence so a later node can check
    it was gathered, rather than trusting that it was.
    """
    prepared: dict
    commit_checked: bool


# ---------------------------------------------------------------------------
# the answer, enforced by the framework rather than by a hand-written parser
# ---------------------------------------------------------------------------
# No OPTIONAL fields anywhere in the submission schema. This is not a
# style preference, it is the difference between an answer and no answer.
#
# ToolStrategy turns these models into a tool schema, and the server
# constrains decoding to that schema. With `confidence` on RankedFile,
# `file` here and `rationale` on Localization -- all optional, all with
# defaults -- the model never produced a tool call at all: it generated
# to the token cap and stopped, at 4,000 tokens and again at 16,000.
# Dropping the three turned that into a valid call in 899 tokens.
#
# Measured on the captured failing request, same messages and same
# system prompt, one variable changed at a time:
#
#   generated schema as-is            NOTHING, finish=length,  4,000 tok
#   same, cap raised to 16,000        NOTHING, finish=length, 16,000 tok
#   same, all descriptions removed    NOTHING, finish=length,  4,000 tok
#   same, numeric bounds removed      NOTHING, finish=length,  4,000 tok
#   same, OPTIONAL FIELDS removed     CALLED,  finish=tool_calls, 899 tok
#
# It is cumulative: either property on its own is fine, both plus their
# optional members is not. None of the three was ever read by run_lc,
# which is why removing them costs nothing.
class ChainStep(BaseModel):
    step: str = Field(description="One step from symptom toward the cause.")
    cited_from: str = Field(
        description="Which tool result supports this step: search_symbol, "
                    "search_text, read_code, recall_incidents, callers_of.")


class RankedFile(BaseModel):
    path: str = Field(description="Repository-relative path.")
    symbol: str = Field(
        description="The function or method inside THIS file that holds the "
                    "fault, named exactly as it appears in the code. Not the "
                    "class, not the file. Use read_code to confirm the name "
                    "before you write it.")
    evidence: str = Field(
        description="Why THIS file. Quote what you read: a line number, a "
                    "symbol, a past incident. Not a restatement of the title.")


class Localization(BaseModel):
    """The submission. Every field here was optional once and got skipped,
    so each is required now."""
    files: list[RankedFile] = Field(
        description="Up to 10 candidate root-cause files, most likely first.",
        min_length=1, max_length=10)
    causal_chain: list[ChainStep] = Field(
        description="2-6 ordered steps from the reported symptom to the "
                    "named cause, each citing a tool result.",
        min_length=2, max_length=6)


# ---------------------------------------------------------------------------
# tools: thin wrappers over the deterministic layer agent.py already uses
# ---------------------------------------------------------------------------
def build_tools(ws: T.Workspace) -> list:
    """The same tool semantics as the hand-rolled agent, so a difference in
    results is a difference in ORCHESTRATION and not in what the tools can
    see. data_flow_back is kept available but is not promoted: it rescued
    1.7% of hard failures, and a tool the model may choose is cheaper than
    a step every run must pay for.

    Everything goes through T.dispatch, never ws.<method> directly. The
    first version called the methods, which looked equivalent and was not:
    dispatch is where ws.calls is appended (so cost is counted) and where
    a repeated identical call comes back with "identical call already
    made; try a different symbol, query, or file". Without it the first
    pilot ran the same search twice and read one file three times inside
    eleven turns, then died at the recursion limit with no answer.
    """

    @tool
    def search_symbol(name: str) -> dict:
        """Find where a class, function or identifier is DEFINED and used.
        A stack frame names a symbol, not the file that caused the fault."""
        return T.dispatch(ws, "search_symbol", {"name": name})

    @tool
    def search_text(query: str, k: int = 12) -> dict:
        """BM25 over file CONTENT. Describe the BEHAVIOUR that went wrong
        rather than quoting the error message."""
        return T.dispatch(ws, "search_text", {"query": query, "k": k})

    @tool
    def read_code(path: str, around: str = "", line: int = 0, n: int = 50) -> dict:
        """Read real source lines, optionally centred on a symbol or line."""
        return T.dispatch(ws, "read_code", {"path": path, "around": around,
                                          "line": line, "n": n})

    @tool
    def read_skeleton(path: str) -> dict:
        """List the functions and classes a file declares."""
        return T.dispatch(ws, "read_skeleton", {"path": path})

    @tool
    def list_dir(path: str = "") -> dict:
        """List source files and subdirectories."""
        return T.dispatch(ws, "list_dir", {"path": path})

    @tool
    def callers_of(symbol: str) -> dict:
        """Which functions call or reference a symbol. One hop back toward
        the code that created the bad state."""
        return T.dispatch(ws, "callers_of", {"symbol": symbol})

    @tool
    def data_flow_back(symbol: str) -> dict:
        """Where a symbol's value is SET, as opposed to where it is read."""
        return T.dispatch(ws, "data_flow_back", {"symbol": symbol})

    @tool
    def recall_incidents(query: str, k: int = 5) -> dict:
        """Past incidents in this project that read like this one, and the
        files their fixes touched. Only incidents resolved before this
        report existed."""
        return T.dispatch(ws, "recall_incidents", {"query": query, "k": k})

    return [search_symbol, search_text, read_code, read_skeleton,
            list_dir, callers_of, data_flow_back, recall_incidents]


# ---------------------------------------------------------------------------
# middleware 1: the mandatory evidence pass
# ---------------------------------------------------------------------------
def make_preamble(ws: T.Workspace, store: IncidentStore, ctx: dict,
                  seed_candidates: list[str], repo_tree: str = ""):
    """Everything the failure analysis says must happen on EVERY run.

    This is the piece that cannot be left to the model. Each probe below
    is here because it was measured, and the two that were not measured
    to help (data_flow_back, read_skeleton of the top 5) are absent.
    """

    @before_agent
    def gather(state: TriageState, runtime) -> dict[str, Any]:
        rf = ws_reformulate(ws)
        behaviour = rf.get("behaviour") or " ".join(ws.query_text.split()[:60])
        syms = ws.symbols_in_snapshot(list(dict.fromkeys(
            list(rf.get("identifiers") or []) + T.raw_report_symbols(ws.query_text))))

        # 1. memory, twice: on the restated behaviour AND on the symbols.
        #    The symbol-keyed query is the highest-value probe available
        #    (18.3% of otherwise-lost instances) and the model asks for it
        #    0.23 times per run when left to choose.
        recalls = store.search(behaviour, limit=5, in_snapshot=ws.snap.blob_of,
                               **ctx)
        seen = {r.incident for r in recalls}
        if syms:
            for r in store.search(" ".join(syms[:6]), limit=5,
                                  in_snapshot=ws.snap.blob_of, **ctx):
                if r.incident not in seen:
                    seen.add(r.incident)
                    recalls.append(r)
        recalls.sort(key=lambda r: -r.weight)

        # 2. resolve EVERY report symbol, not the ones the model fancies
        resolved = {}
        for s in syms[:6]:
            res = ws.search_symbol(s)
            hits = [h["file"] for h in (res.get("defined_in") or [])][:3]
            if hits:
                resolved[s] = hits

        # 3. behaviour search and title search: different queries, and the
        #    title rescues instances the behaviour restatement misses
        pre = ws.search_text(behaviour, k=8).get("hits", [])
        title = " ".join(ws.query_text.split("\n")[0].split()[:18])
        title_hits = ws.search_text(title, k=6).get("hits", []) if title else []

        # 4. one hop back from the stack frames, walked rather than offered
        back = []
        for s in ws.symbols_in_snapshot(T.frame_symbols(ws.query_text))[:3]:
            hits = (ws.callers_of(s) or {}).get("callers") or []
            if hits:
                back.append((s, hits[:6]))
            if len(back) == 2:
                break

        ws.calls.clear()        # preamble is harness setup, not agent action
        prepared = {"behaviour": behaviour, "symbols": syms,
                    "recalls": [r.as_dict() for r in recalls],
                    "resolved": resolved,
                    "content_hits": [h["file"] for h in pre[:8]],
                    "title_hits": [h["file"] for h in title_hits[:6]],
                    "backward": [(s, [c["file"] for c in cs]) for s, cs in back],
                    "seed": seed_candidates[:12]}
        return {"prepared": prepared, "commit_checked": False,
                "messages": [{"role": "user",
                              "content": render_briefing(ws, prepared, repo_tree)}]}

    return gather


def ws_reformulate(ws: T.Workspace) -> dict:
    """Symptom language into code vocabulary. Imported lazily so this
    module can be read, tested and reviewed without a live model."""
    import agent as A
    try:
        return A.reformulate(ws.query_text)
    except Exception:  # noqa: BLE001 - the fallback is the report's own words
        return {}


def render_briefing(ws: T.Workspace, p: dict, repo_tree: str) -> str:
    """One page of gathered evidence. Ordering is deliberate: memory first
    when it is strong, because on hard instances a past one-file fix is
    the single best piece of evidence available."""
    L = [f"Project: {ws.project}",
         "", "=== ISSUE REPORT (with logs) ===", ws.query_text[:18000], ""]
    L.append("=== PREPARED EVIDENCE (unverified; verify before trusting) ===")
    if p["behaviour"]:
        L.append(f"behaviour in code vocabulary: {p['behaviour']}")
    L.append(f"report symbols present in this snapshot: "
             f"{', '.join(p['symbols']) or 'none'}")
    if p["resolved"]:
        L.append("\nwhere those symbols are declared:")
        L += [f"  {s}: {', '.join(f)}" for s, f in p["resolved"].items()]
    if p["recalls"]:
        L.append("\npast incidents that read like this one (resolved BEFORE "
                 "this report), and the files their fixes touched:")
        L += [f"  - {m['incident']} (weight {m['weight']}, that fix touched "
              f"{m['n_files_in_that_fix']} file(s)): "
              f"{', '.join(m['fixed_files'][:4])}" for m in p["recalls"][:6]]
    else:
        L.append("\npast incidents: none admissible for this report.")
    L.append("\nfiles a retrieval layer ranked highest:")
    L += [f"  {i + 1}. {f}" for i, f in enumerate(p["seed"])]
    if p["content_hits"]:
        L.append("\nfiles whose CODE matches the described behaviour:")
        L += [f"  - {f}" for f in p["content_hits"]]
    if p["title_hits"]:
        L.append("\nfiles matching the report title:")
        L += [f"  - {f}" for f in p["title_hits"]]
    if p["backward"]:
        L.append("\none hop BACK from the stack frames, already walked (the "
                 "bad state may be created here, not where it was detected):")
        L += [f"  {s} is called from: {', '.join(fs)}" for s, fs in p["backward"]]
    if repo_tree:
        L.append("\n=== REPOSITORY STRUCTURE (the fault may be in an area "
                 "the report never names) ===")
        L.append(repo_tree)
    L.append("\nInvestigate, then return the ranked files with evidence and "
             "the causal chain. A file a similar past incident was fixed in "
             "is strong evidence, especially when the report names no file.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# middleware 2: the commit check (for the ordering failures)
# ---------------------------------------------------------------------------
@after_model
def commit_check(state: TriageState, runtime) -> dict[str, Any] | None:
    """The 953 near-misses do not need another search.

    63.3% of them opened a gold file with read_code and still ranked
    something else first, and they already search MORE than runs that
    succeed. So this does not gather: it asks, once, for the ordering of
    the top candidates to be justified against evidence already in hand.
    Fires at most once per run; the model is free to keep its order.
    """
    if state.get("commit_checked"):
        return None
    msgs = state.get("messages") or []
    if not msgs:
        return None
    last = msgs[-1]
    # only when the model is about to finish, i.e. it stopped calling tools
    if getattr(last, "tool_calls", None):
        return None
    if len(msgs) < 4:
        return None
    return {"commit_checked": True,
            "messages": [{"role": "user", "content":
                          f"Before you answer: name your top "
                          f"{TOP_FOR_COMMIT} candidates and say, for each, "
                          f"the strongest piece of evidence you actually "
                          f"read that puts it above the next one. If the "
                          f"evidence does not separate them, reorder. Then "
                          f"give the final answer."}]}


@wrap_model_call
def turn_budget(request, handler):
    """Budget pressure, and then a hard stop.

    The nudge alone was not enough. On the first real pilot the model
    searched for eleven turns, never answered, and the graph died at its
    recursion limit -- the run cost 11 calls and 77,558 prompt tokens and
    produced nothing, so the row scored entirely on the lexical fallback.
    agent.py never had this failure because its last turn forces
    submit_ranking with tool_choice.

    The structural equivalent here is to take the tools away. With none
    offered the model cannot search again, and the only thing left to
    produce is the structured answer.
    """
    n = len([m for m in request.state.get("messages", [])
             if getattr(m, "type", "") == "ai"])
    if n >= MAX_TURNS:
        # as a USER turn, not a system-prompt suffix. Measured: with the
        # same context and the instruction appended to the system prompt,
        # the conversation still ended on a tool result, the model had
        # nothing to reply to, and it reasoned to finish_reason=length
        # twice (3,000 and then 10,000 tokens) writing nothing. Replayed
        # with the identical text as a closing user message it answered
        # in 2,255 tokens, finish_reason=stop. The budget was never the
        # problem; having no turn to speak into was.
        keep = [t for t in (request.tools or [])
                if (getattr(t, "name", None) or "") not in AGENT_TOOLS]
        return handler(request.override(
            tools=keep,
            messages=list(request.messages or []) + [HumanMessage(
                content="Your turn budget is spent. Answer NOW from what "
                        "you already read. No further investigation is "
                        "possible.")]))
    if n >= MAX_TURNS - 3:
        request = request.override(system_prompt=(
            (request.system_prompt or "") +
            "\n\nYou are near your turn budget. Commit to an answer now."))
    return handler(request)


@wrap_model_call
def trim_history(request, handler):
    """Drop the older tool exchanges. Do NOT stub them.

    agent.py replaces an old tool result with "[result of X omitted to
    save context; it was already used]" and keeps the message. Dropping
    the exchange outright is preferred here for two reasons that are
    about coherence, not about the stall: a stub is an assistant turn
    that called a tool paired with a reply saying the answer is gone,
    and the shorter history reads the same to a human.

    Honest note on provenance: this was first written believing the
    stubs caused the agent to stop answering. They did not -- that
    comparison was run against a different instance than the one that
    failed, and the real cause was the submission schema (see
    ChainStep). The change is kept because dropping is cleaner, not
    because it fixed anything.

    A dropped message still has to be COUNTED -- that is the whole point
    of the capture -- so lc_trace prices the gap against the tool
    outputs it recorded, rather than looking for stub markers.
    """
    msgs = list(request.messages or [])
    idx = [i for i, m in enumerate(msgs) if getattr(m, "type", "") == "tool"]
    if len(idx) <= KEEP_FULL:
        return handler(request)
    stale = {getattr(msgs[i], "tool_call_id", None) for i in idx[:-KEEP_FULL]}
    stale.discard(None)
    out = []
    for m in msgs:
        kind = getattr(m, "type", "")
        if kind == "tool" and getattr(m, "tool_call_id", None) in stale:
            continue
        if kind == "ai":
            tcs = getattr(m, "tool_calls", None) or []
            # an assistant turn goes only when EVERY call it made is
            # going too; a half-removed turn leaves a tool_call with no
            # reply, which is an invalid conversation
            if tcs and all(tc.get("id") in stale for tc in tcs):
                continue
        out.append(m)
    return handler(request.override(messages=out))


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
SYSTEM = """You are a senior maintainer doing root-cause fault localization on a
real production issue. You have the issue report with its logs, and tools to
investigate the source tree exactly as it was when the issue was filed.

The logs show where the failure was DETECTED. Your job is to find the file that
CAUSED it, which is usually a different file.

Evidence has already been gathered for you: report symbols resolved to code,
content and title searches, one hop back from the stack frames, and past
incidents from this project with the files their fixes touched. Weigh it before
exploring further rather than after.

Rank by evidence quality: code that CREATES the bad state beats code that
observes it; a file a similar past incident was fixed in is strong, especially
when the report names no file; a file whose CONTENT matches the behaviour beats
one whose PATH matches a word in the title; the file in the stack trace is weak
on its own.

For EVERY file you rank you must also name the function or method inside it that holds the fault. That is the code region, and it is what the answer is really about: a file can be a thousand lines. Name it exactly as it appears in the code, not the class and not the file. read_code takes a symbol, so open the function and read it before you name it. If you have not read it, you are guessing."""


def build_agent(model, ws: T.Workspace, store: IncidentStore, ctx: dict,
                seed_candidates: list[str], repo_tree: str = "",
                checkpointer=None, recorder=None):
    """The whole design in one call.

    Every element is here because something was measured, and the
    commentary in this module says which. Swap `model` for any provider
    LangChain supports; swap `store` for a dense implementation to test
    whether BM25 is actually the right choice for incident matching,
    which is currently assumed rather than shown.
    """
    return create_agent(
        model=model,
        tools=build_tools(ws),
        system_prompt=SYSTEM,
        state_schema=TriageState,
        # ToolStrategy, not the provider default: it makes the answer a
        # TOOL the model calls, which is exactly how agent.py forces
        # submit_ranking and the reason that path never stalls. With a
        # free-text answer the model, handed a history full of tool calls
        # and no tools, reasoned to finish_reason=length three times in a
        # row (3,000 then 10,000 then 4,000 tokens) and wrote nothing.
        response_format=ToolStrategy(Localization),
        # the recorder goes LAST so it is innermost: it sees the request
        # after turn_budget has trimmed it, i.e. what the model actually got
        middleware=[make_preamble(ws, store, ctx, seed_candidates, repo_tree),
                    turn_budget, trim_history, commit_check,
                    *(recorder.middleware() if recorder is not None else [])],
        checkpointer=checkpointer,
    )


# ---------------------------------------------------------------------------
# the runner entry point
# ---------------------------------------------------------------------------
def run_lc(ws: T.Workspace, seed: int = 42, *, model=None, repo_tree: bool = False,
           trace_dir=None) -> dict:
    """One instance through the LangGraph agent, in the shape run_agent
    already writes.

    Returning agent.run_instance's dict is deliberate: the harness, the
    evaluation and every downstream script stay untouched, so this arm is
    scored on exactly the same population by exactly the same code. An
    arm that needed its own scoring path could not be compared with the
    others.
    """
    import agent as A
    from lc_trace import RunRecorder
    from langgraph.checkpoint.memory import InMemorySaver

    rid = f"{ws.project}:{ws.issue_key}"
    store = IncidentStore.from_pool(ws.project, ws.memory)
    ctx = {"cutoff": ws.cutoff, "this_key": ws.issue_key,
           "this_fix_shas": frozenset(ws.fix_shas),
           "dup_cluster": ws.dupclusters.get(ws.issue_key),
           "dup_of": ws.dupclusters}
    tree = A._repo_tree_for(ws) if repo_tree else ""

    rec = RunRecorder(trace_dir, rid.replace(":", "_"),
                      {"instance": rid, "arm": "lc", "seed": seed,
                       "model": getattr(model, "model_name", str(model))}) \
        if trace_dir else None
    graph = build_agent(model, ws, store, ctx, ws.seed_candidates, tree,
                        checkpointer=InMemorySaver(), recorder=rec)
    # Two super-steps per turn (model, then tools), plus the preamble, the
    # commit check and the structured-response step. At +6 the graph died
    # at 36 steps having made only 11 model calls, so turn_budget's hard
    # stop at MAX_TURNS was never reached -- the limit cut the run off
    # before the thing designed to end it could fire.
    cfg = {"configurable": {"thread_id": rid},
           "recursion_limit": MAX_TURNS * 2 + 20}

    stop, answer, stop_detail = "submitted", None, ""
    try:
        state = graph.invoke({"messages": []}, cfg)
        answer = state.get("structured_response")
    except Exception as e:  # noqa: BLE001 - a dead run must still write a row
        # The class name alone is not diagnosable. Five pilot rows read
        # "error:OpenAIInvalidRequestError" and the reason turned out to be
        # the server refusing the prompt on context size, which the message
        # says outright and the class name does not. Keep the text.
        stop, state = f"error:{type(e).__name__}", {}
        stop_detail = str(e)[:600]
    if answer is None and stop == "submitted":
        stop = "no_answer"

    # the model writes paths; they have to land on real files in THIS
    # snapshot before they can be scored. Same resolver as the main agent.
    resolver: dict = {}
    resolved: list[str] = []
    for rf in (answer.files if answer else []):
        f = A._resolve(rf.path, ws, resolver)
        if f and f not in resolved:
            resolved.append(f)
    final = (A.fuse(resolved, ws.seed_candidates)[:A.LIST_LEN] if resolved
             else list(ws.seed_candidates[:A.LIST_LEN]))

    # The submitted region, checked against the file it names. A symbol the
    # file does not contain resolves to "" and is scored as a miss, which is
    # the point: this field exists to make the model commit to a region, and
    # a name nobody can find is not a region.
    notes = []
    for rf in (answer.files if answer else []):
        hit = ws.resolve_symbol(rf.path, rf.symbol)
        notes.append({"file": rf.path, "why": rf.evidence, "confidence": 1.0,
                      "symbol": rf.symbol,
                      "symbol_resolved": hit[0] if hit else "",
                      "symbol_lines": [hit[1], hit[2]] if hit else [],
                      "in_snapshot": rf.path in ws.snap.blob_of})

    summary = rec.finish(state, graph=graph, config=cfg) if rec else {}
    usage = {"calls": summary.get("model_calls", 0),
             "in": summary.get("input_tokens", 0),
             "out": summary.get("output_tokens", 0)}
    return {"ranking": final, "agent_ranking": resolved[:A.LIST_LEN],
            "lexical_seed": ws.seed_candidates[:A.LIST_LEN],
            "notes": notes,
            "tool_calls": ws.calls, "stop_reason": stop,
            "stop_detail": stop_detail,
            "rationale": "; ".join(c.step for c in answer.causal_chain)
                         if answer else "",
            "usage": usage, "resolver": resolver, "events": [], "seed": seed,
            "version": 3, "arm": "lc",
            "causal_chain": [c.model_dump() for c in answer.causal_chain]
                            if answer else [],
            "prewalk_symbols": [], "trace": summary.get("path", "")}
