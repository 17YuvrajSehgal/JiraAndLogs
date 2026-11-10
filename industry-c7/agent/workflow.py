"""The staged workflow: code owns the procedure, the model decides inside it.

Why this exists
---------------
lc_agent.py gathers evidence with code and validates the answer with code,
but the investigation between the two is a free loop: one model, ten
tools, fourteen turns, any order. scripts/trace_analysis.py measured what
that loop does on all 26,541 answered instances of the main run:

  it does not stop      83.2% of runs end because the budget took the tools
                        away. Runs that stop themselves are right 95.8% of
                        the time, forced ones 62.2%.
  it re-reads           10.0 read_code calls per run over 2.7 distinct
                        files: 72.7% of reads go to a file already read.
  it searches too long  a gold file is named by a tool on turn 1 in 82.8%
                        of runs; turns 4-14 together add 5.1 points. Runs
                        that end right still spend a median 13 turns after
                        first reading the gold file.
  it ranks by attention 4,763 failures have the gold file in the list but
                        not first (55.8% of all failures). 79.2% of them
                        READ the gold file. The file ranked first was read
                        more (5.0 vs 3.2 reads) and, in 67.7% of them,
                        read LATER than the gold file (33.9% in runs that
                        end right).
  it forgets            at the answering call a median 55.7% of all tool
                        output is no longer in context.
  it skips candidates   890 failures had the gold file in the seed list
                        and never listed it; only 22.4% of them opened it.
                        In 2,877 more the gold file is in neither list,
                        yet a tool NAMED it in 44.6% and it was opened in
                        13.5%.
  it names few files    2.8 to 3.7 files per answer, so recall@5 is 0.32
                        when a fix touches four or more.

Each stage below removes one of those, by structure and not by prompt:

  1 GATHER     code     the same evidence pass as lc_agent (prepare)
  2 ROUTE      code     report type picks which evidence is examined first
  3 SHORTLIST  model    picks candidates from a closed table; may run a few
                        searches first. <- "searches too long": the search
                        budget is 2 turns, where the yield is.
  4 EXAMINE    model    ONE candidate per step, fresh context, equal
                        budget, the function pre-read by code, a fixed-form
                        verdict. <- "re-reads", "ranks by attention",
                        "skips candidates": every candidate is opened once
                        and judged alone, so none is judged by how often
                        or how recently it was read.
  5 WALK BACK  code     a file judged to DETECT the failure sends its
                        callers into EXAMINE, once. The free loop called
                        callers_of in 3.8% of runs.
  6 RANK       model    sees only the verdict cards, never raw tool
                        output. <- "forgets": the cards are small, so all
                        of them are in context when the order is decided.
  7 CHECK      code     lc_agent.package: the same validation and fusion
                        as the free-loop arm.

The model makes three kinds of decision (which candidates, what a file's
role is, the order among files with the same role) and every one of them
is written to the trace as a `decision` event.

The free loop stays available as `--arm lc`; this is `--arm wf`. Same
model, same evidence pass, same validation, so the difference between the
two arms is the procedure and nothing else.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "scripts"))

from langchain.agents import create_agent  # noqa: E402
from langchain.agents.middleware import after_model, wrap_model_call  # noqa: E402
from langchain.agents.structured_output import ToolStrategy  # noqa: E402
from langchain.tools import tool  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

import lc_agent as LC  # noqa: E402
import tools as T  # noqa: E402
from lc_store import IncidentStore  # noqa: E402

# Budgets, each set from the measurements in the module docstring.
TABLE_MAX = 30          # candidates shown to SHORTLIST
PICK_MAX = 5            # candidates the model may pick
EXAMINE_MAX = 8         # hard cap on EXAMINE steps per run, walk-back included
WALK_BACK_MAX = 2       # callers added by WALK BACK
SHORTLIST_CALLS = 3     # model calls: 2 search turns, then the pick
EXAMINE_CALLS = 3       # model calls: 2 reads, then the verdict
REPORT_CHARS = 6000     # report digest carried into each step
# How much of a file EXAMINE is shown at once. The free loop read code in
# 80-line windows: 3.7 windows per opened file, 12.1% of files in 8 or
# more, 26.1% paged through by line number -- and never held more than
# about 7,000 tokens of a 65,536 window. In 32.0% of the runs that had the
# right file and the wrong function, the gold function was never on screen
# at all. So the unused window is spent here: the whole file when it fits,
# else whole FUNCTIONS in order of relevance until the budget is full.
FILE_CHARS = int(os.environ.get("C7_WF_FILE_CHARS") or 24000)
# Chosen on the DEVELOPMENT split (scripts/view_tuning.py, 1,153 gold files
# of 27 projects, evidence-named functions not available there so every
# rate is a lower bound). Share of files that do NOT fit whole in which a
# gold function is on screen, at the same 24,000-character budget:
#   every function capped at 6,000 chars, BM25 order        0.851
#   + functions the report names outright go first          0.864
#   + first 2 in full, the rest by their first 1,500 chars  0.910
#   + all by their first 1,500 chars                        0.925
# The third row is used: it keeps the two most relevant functions whole,
# which the last row gives up for 1.5 points.
FUNC_FULL_CHARS = 6000  # a function shown in full gets at most this
FUNC_CHARS = 1500       # every later function: its head
FULL_FIRST = 2
FUNCS_PER_CARD = 3
# Verdicts are judged in isolation; RANK orders within a role. Set to 0 to
# let RANK order freely across roles (an ablation of the tier rule).
TIER_SORT = (os.environ.get("C7_WF_TIER") or "1") != "0"
TIER = {"cause": 0, "detects": 1, "unrelated": 2}
NUDGE = "Submit your answer with the answer tool now."


# ---------------------------------------------------------------------------
# the three decisions, as forms. Required fields only: see ChainStep in
# lc_agent.py for what optional fields did to constrained decoding.
# ---------------------------------------------------------------------------
class Shortlist(BaseModel):
    paths: list[str] = Field(
        description=f"Up to {PICK_MAX} candidate files to examine, most "
                    "promising first, copied from the candidate table or "
                    "from a search result.",
        min_length=1, max_length=PICK_MAX)
    reason: str = Field(description="One sentence: what made you pick these.")


class Verdict(BaseModel):
    role: Literal["cause", "detects", "unrelated"] = Field(
        description="cause: code in this file CREATES the bad state the "
                    "report describes. detects: it only reports, logs or "
                    "checks a bad state created elsewhere. unrelated: "
                    "neither.")
    functions: list[str] = Field(
        description="Up to three functions or methods of THIS file that "
                    "hold the fault (or the check, when the role is "
                    "detects), most likely first, each copied exactly from "
                    "the function list. A fix often touches more than one. "
                    "Empty list when unrelated.",
        max_length=3)
    evidence: str = Field(
        description="The line number and code you read that supports the "
                    "role. Quote it.")
    walk_back: str = Field(
        description="When the role is detects: the function whose CALLERS "
                    "should be examined next. Empty string otherwise.")


class Ranking(BaseModel):
    """RANK's answer. It used to be lc_agent.Localization, which also asks
    for a function and an evidence quote per file -- text the cards already
    hold and the code threw away. That answer ran to 1,018 output tokens
    and 69 seconds, a third of a run's model time, and twice hit the token
    cap."""
    module: str = Field(description="The affected module, copied from the "
                                    "module list.")
    order: list[str] = Field(
        description="The file paths from the verdict cards, most likely "
                    "root cause first.",
        min_length=1, max_length=10)
    causal_chain: list[LC.ChainStep] = Field(
        description="2-6 ordered steps from the reported symptom to the "
                    "named cause.",
        min_length=2, max_length=6)


# ---------------------------------------------------------------------------
# one bounded model step
# ---------------------------------------------------------------------------
def _budget(max_calls: int, names: frozenset):
    """lc_agent.turn_budget for a step: on the last allowed call the step's
    tools are withdrawn and the order to answer arrives as a user turn."""
    @wrap_model_call
    def step_budget(request, handler):
        n = len([m for m in request.state.get("messages", [])
                 if getattr(m, "type", "") == "ai"])
        if n >= max_calls - 1:
            keep = [t for t in (request.tools or [])
                    if (getattr(t, "name", None) or "") not in names]
            return handler(request.override(
                tools=keep, messages=list(request.messages or []) + [HumanMessage(
                    content="This step's budget is spent. Answer NOW from "
                            "what you already read.")]))
        return handler(request)
    return step_budget


@after_model(can_jump_to=["model"])
def _must_answer(state, runtime):
    """A prose reply ends a create_agent graph with no structured answer.
    Send it back, at most twice."""
    msgs = state.get("messages") or []
    # Only a model turn with no tool call is prose. After a structured
    # answer the last message is the framework's ToolMessage, which also
    # has no tool_calls: treating that as prose sent every answered step
    # back twice (first login pilot: 36 calls per run, each answer given
    # three times).
    if (not msgs or getattr(msgs[-1], "type", "") != "ai"
            or getattr(msgs[-1], "tool_calls", None)):
        return None
    if sum(1 for m in msgs if getattr(m, "content", "") == NUDGE) >= 2:
        return None
    return {"jump_to": "model", "messages": [{"role": "user", "content": NUDGE}]}


def llm_step(model, system: str, user: str, tools: list, schema, max_calls: int,
             rec=None):
    """One stage's model work: at most `max_calls` calls, only `tools`, and
    it ends in `schema`. Returns None when the model never answered."""
    names = frozenset(t.name for t in tools)
    agent = create_agent(
        model=model, tools=tools, system_prompt=system,
        response_format=ToolStrategy(schema),
        middleware=[_budget(max_calls, names), _must_answer,
                    *(rec.middleware() if rec is not None else [])])
    state = agent.invoke({"messages": [{"role": "user", "content": user}]},
                         {"recursion_limit": max_calls * 3 + 12})
    return state.get("structured_response")


# ---------------------------------------------------------------------------
# stage 2: ROUTE, and the candidate table SHORTLIST chooses from
# ---------------------------------------------------------------------------
def route(ws: T.Workspace, p: dict) -> str:
    """Which evidence leads. Decided by what the report contains: stack
    frames, else log lines that match a statement in the code, else prose."""
    if T.frame_symbols(ws.query_text):
        return "trace"
    return "logs" if p.get("printed_by") else "prose"


def build_table(ws: T.Workspace, p: dict) -> tuple[list[dict], list[str]]:
    """Every file any evidence channel named, with WHY, in one table.

    Returns (table, forced). `forced` is examined whether or not the model
    picks it: the top two seeds always (890 failures had the gold file in
    the seeds and never opened it), plus the lead of the route.
    """
    why: dict[str, list[str]] = {}

    def add(path, reason):
        if path in ws.snap.blob_of:
            why.setdefault(path, [])
            if reason not in why[path]:
                why[path].append(reason)

    for i, f in enumerate(p["seed"]):
        add(f, f"retrieval rank {i + 1}")
    for s, fs in p["resolved"].items():
        for f in fs:
            add(f, f"declares {s}")
    for m in p.get("printed_by", []):
        add(m["file"], f"prints log event {m['event']} in {m['function']}")
    for fn, fs in p.get("log_back", []):
        for f in fs:
            add(f, f"calls the code that prints a log event ({fn.rsplit('::', 1)[-1]})")
    for s, fs in p["backward"]:
        for f in fs:
            add(f, f"calls {s} (one hop back from a stack frame)")
    for m in p["recalls"][:6]:
        for f in m["fixed_files"][:4]:
            add(f, f"fixed in past incident {m['incident']} (weight {m['weight']})")
    for f in p["content_hits"]:
        add(f, "code matches the described behaviour")
    for f in p["title_hits"]:
        add(f, "matches the report title")

    seed_rank = {f: i for i, f in enumerate(p["seed"])}
    order = sorted(why, key=lambda f: (-len(why[f]), seed_rank.get(f, 99)))[:TABLE_MAX]
    table = [{"id": f"C{i + 1}", "path": f, "why": why[f]} for i, f in enumerate(order)]

    r = p["route"]
    lead = []
    if r == "trace":
        lead = [f for _s, fs in p["backward"] for f in fs[:1]][:1] \
            or [fs[0] for fs in p["resolved"].values() if fs][:1]
    elif r == "logs":
        lead = [fs[0] for _fn, fs in p.get("log_back", []) if fs][:1] \
            or [m["file"] for m in p["printed_by"]][:1]
    else:
        lead = [f for m in p["recalls"][:1] for f in m["fixed_files"][:1]]
    forced = list(dict.fromkeys([f for f in p["seed"][:2] + lead if f in why]))
    return table, forced


def files_in(result) -> list[str]:
    """Every repository path a tool result names, in order."""
    out = []

    def walk(v, key=""):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and key in ("file", "fixed_files"):
            out.append(v)
    walk(result)
    return list(dict.fromkeys(out))


def digest(ws: T.Workspace, p: dict) -> str:
    """The report as each step sees it: compressed, with the event list."""
    if p.get("log_layer"):
        import logs
        text, p["compression"] = logs.compress_report(ws.query_text, REPORT_CHARS)
    else:
        text = ws.query_text[:REPORT_CHARS]
    L = ["=== ISSUE REPORT ===", text]
    if p.get("events"):
        L.append("\n=== SELECTED LOG EVENTS ===")
        L += [f"  {e['id']}{' [generic]' if e['generic'] else ''}: {e['line'][:240]}"
              for e in p["events"]]
    if p["behaviour"]:
        L.append(f"\nbehaviour in code vocabulary: {p['behaviour']}")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# the prompts. Short on purpose: the procedure is in the graph.
# ---------------------------------------------------------------------------
SYS_SHORTLIST = """You are triaging a production issue. A table lists every file the evidence
points at and why. Pick the files worth opening.

The logs show where the failure was DETECTED; the cause is usually a different
file. A file a similar past incident was fixed in is strong evidence. A file
named by several kinds of evidence is stronger than one named by a single kind.

If the table clearly misses the behaviour the report describes, run a search
first (at most two). Otherwise pick straight away."""

SYS_EXAMINE = """You are judging ONE file for ONE production issue. Decide its role:

  cause      code here CREATES the bad state the report describes
  detects    code here only reports, logs or checks a bad state made elsewhere
  unrelated  neither

The code that printed a log line or sits in a stack trace usually DETECTS.
Code that sets, computes or forgets to update the state usually is the CAUSE.
You are shown the whole file, or its most relevant functions in full. Read the
code before you decide; use read_code only for a part you were not shown, and
callers_of or data_flow_back to see where a bad value comes from.

Then name the functions that hold the fault: up to three, most likely first,
copied from the function list. A fix often changes more than one function, so
name a second when two share the faulty logic. Quote the line your verdict
rests on."""

SYS_RANK = """You are finishing a root-cause localization. Each candidate file was examined
on its own and has a verdict card. Order the candidates, most likely root
cause first, using only the cards and the report.

Files judged `cause` come before `detects`, and those before `unrelated`.
Among files with the same role, prefer the one whose quoted evidence explains
the reported symptom most directly; when that does not separate them, prefer
the one more kinds of evidence pointed at (a past incident fixed there, a high
retrieval rank, a symbol or log line from the report). Rank only files that have a card, by path.

Then write the causal chain from the reported symptom to the cause, each step
in one sentence. `file` is the path the step is about. `log_event` is ONLY an
id from the SELECTED LOG EVENTS list (like E2) or a line copied word for word
from the report; write an empty string when there is none. Never put a
sentence of your own in `log_event`. Name the affected module, copied from the
module list."""


# ---------------------------------------------------------------------------
# the graph
# ---------------------------------------------------------------------------
class WFState(TypedDict, total=False):
    prepared: dict
    table: list
    forced: list
    queue: list          # paths waiting for EXAMINE
    cards: list          # verdict cards, in examination order
    walked: bool
    answer: object
    decisions: list      # every model decision, for the trace and the row


def build_graph(model, ws: T.Workspace, store: IncidentStore, ctx: dict,
                log_layer: bool, rec=None):
    import agent as A

    def log(stage, **kw):
        if rec is not None:
            rec._emit("decision", {"stage": stage, **kw})
        return {"stage": stage, **kw}

    def gather(state: WFState) -> dict:
        p = LC.prepare(ws, store, ctx, ws.seed_candidates, log_layer)
        p["route"] = route(ws, p)
        table, forced = build_table(ws, p)
        return {"prepared": p, "table": table, "forced": forced, "cards": [],
                "decisions": [log("route", route=p["route"], n_table=len(table),
                                  forced=forced)]}

    def shortlist(state: WFState) -> dict:
        p, table = state["prepared"], state["table"]
        known = {c["path"]: c for c in table}
        found: dict[str, str] = {}

        def note(res, label):
            for f in files_in(res):
                if f in ws.snap.blob_of and f not in known:
                    found.setdefault(f, label)
            return res

        @tool
        def search_symbol(name: str) -> dict:
            """Find where a class, function or identifier is DEFINED and used."""
            return note(T.dispatch(ws, "search_symbol", {"name": name}),
                        f"your search for {name}")

        @tool
        def search_text(query: str) -> dict:
            """BM25 over file CONTENT. Describe the behaviour that went wrong."""
            return note(T.dispatch(ws, "search_text", {"query": query, "k": 8}),
                        "your behaviour search")

        @tool
        def recall_incidents(query: str) -> dict:
            """Past incidents in this project that read like this one, and
            the files their fixes touched."""
            return note(T.dispatch(ws, "recall_incidents", {"query": query, "k": 5}),
                        "your incident search")

        @tool
        def match_log(line: str) -> dict:
            """Find the logging statement that printed this log line."""
            return note(T.dispatch(ws, "match_log", {"line": line}),
                        "prints a log line you matched")

        tools_ = [search_symbol, search_text, recall_incidents] \
            + ([match_log] if log_layer else [])
        user = "\n".join([
            digest(ws, p), "",
            f"=== CANDIDATE TABLE ({len(table)} files; route: {p['route']}) ===",
            *[f"  {c['id']}  {c['path']}\n        {'; '.join(c['why'][:4])}"
              for c in table], "",
            f"Pick up to {PICK_MAX} files to examine."])
        ans = llm_step(model, SYS_SHORTLIST, user, tools_, Shortlist,
                       SHORTLIST_CALLS, rec)
        picked = []
        for raw in (ans.paths if ans else []):
            f = A._resolve(raw, ws, {})
            if f and (f in known or f in found) and f not in picked:
                picked.append(f)
        # code, not the model, guarantees coverage: forced files are
        # examined even when the model did not pick them, and an unanswered
        # step falls back to the table order
        if not picked:
            picked = [c["path"] for c in table[:PICK_MAX]]
        queue = list(dict.fromkeys(picked + state["forced"]))[:EXAMINE_MAX - WALK_BACK_MAX]
        table = table + [{"id": f"S{i + 1}", "path": f, "why": [w]}
                         for i, (f, w) in enumerate(found.items())]
        return {"queue": queue, "table": table,
                "decisions": state["decisions"] + [log(
                    "shortlist", picked=picked, answered=ans is not None,
                    reason=ans.reason if ans else "", n_found_by_search=len(found),
                    queue=queue)]}

    def examine(state: WFState) -> dict:
        p = state["prepared"]
        why = {c["path"]: c["why"] for c in state["table"]}
        report = digest(ws, p)
        cards, decisions = list(state["cards"]), list(state["decisions"])
        for path in state["queue"]:
            if len(cards) >= EXAMINE_MAX or any(c["path"] == path for c in cards):
                continue
            view, shown = file_view(ws, path, p)
            skeleton = ws.read_skeleton(path).get("declares", [])

            @tool
            def read_code(around: str = "", line: int = 0, n: int = 60) -> dict:
                """Read more of THIS file, centred on a function name or a line."""
                return T.dispatch(ws, "read_code", {"path": path, "around": around,
                                                    "line": line, "n": n})

            @tool
            def callers_of(symbol: str) -> dict:
                """Which functions call a symbol: one hop back toward the
                code that created the bad state."""
                return T.dispatch(ws, "callers_of", {"symbol": symbol})

            @tool
            def data_flow_back(symbol: str) -> dict:
                """Where a symbol's value is SET, as opposed to read."""
                return T.dispatch(ws, "data_flow_back", {"symbol": symbol})

            user = "\n".join([
                report, "", f"=== THE FILE TO JUDGE: {path} ===",
                "why it is a candidate: " + "; ".join(why.get(path, ["picked"])[:5]),
                "FUNCTION LIST (name@line; answer with names from this list): "
                + ", ".join(f"{d['symbol']}@{d['line']}" for d in skeleton),
                "", view])
            v = llm_step(model, SYS_EXAMINE, user,
                         [read_code, callers_of, data_flow_back], Verdict,
                         EXAMINE_CALLS, rec)
            # every name is checked against the file; one it does not
            # contain is dropped, never repaired
            raw = [f for f in (v.functions if v else []) if f.strip()][:FUNCS_PER_CARD]
            hits = list({h[1]: h for f in raw
                         for h in LC.resolve_region(ws, path, f)}.values())
            good = list(dict.fromkeys(h[0] for h in hits))
            card = {"path": path,
                    "role": v.role if v else "unrelated",
                    "function": raw[0].partition("@")[0] if raw else "",
                    "function_resolved": good[0] if good else "",
                    "functions": raw, "functions_resolved": good,
                    "functions_at": [f"{h[0]}@{h[1]}" for h in hits],
                    "shown": shown,
                    # carried to RANK: when two files are both judged cause,
                    # what pointed at each one is the tie-break it lacked
                    # (2 of the 4 file misses of the fourth pilot were a
                    # gold `cause` card ranked second behind another one)
                    "why": why.get(path, [])[:4],
                    "evidence": (v.evidence if v else "")[:400],
                    "walk_back": v.walk_back if v else "",
                    "answered": v is not None}
            cards.append(card)
            decisions.append(log("examine", **card))
        return {"cards": cards, "queue": [], "decisions": decisions}

    def walk_back(state: WFState) -> dict:
        """Code, not the model, decides to walk back: a file judged to only
        DETECT the failure sends its callers into EXAMINE, once."""
        have = {c["path"] for c in state["cards"]}
        ranked = [c["path"] for c in state["table"]]
        new: list[str] = []
        for c in state["cards"]:
            if c["role"] != "detects":
                continue
            sym = (c["walk_back"] or c["function_resolved"] or c["function"]).strip()
            # the model writes the name the way it saw it: `name@208` (3 of 9
            # detect cards in the Qwen pilots) or in quotes (the local run).
            # Neither matches a call site, so the walk back silently found
            # nothing. Keep the bare identifier.
            sym = sym.partition("@")[0].split("(")[0].strip(" 	\"'`")
            sym = sym.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
            if len(sym) < 3:
                continue
            callers = [h["file"] for h in
                       (ws.callers_of(sym) or {}).get("callers") or []]
            # callers some other evidence already named come first
            callers.sort(key=lambda f: ranked.index(f) if f in ranked else 999)
            for f in callers:
                if f not in have and f not in new and f != c["path"]:
                    new.append(f)
                    break
        new = new[:WALK_BACK_MAX]
        table = state["table"] + [{"id": f"W{i + 1}", "path": f,
                                   "why": ["calls a function judged to only "
                                           "detect the failure"]}
                                  for i, f in enumerate(new)
                                  if f not in {c["path"] for c in state["table"]}]
        return {"queue": new, "walked": True, "table": table,
                "decisions": state["decisions"] + [log("walk_back", added=new)]}

    def rank(state: WFState) -> dict:
        p, cards = state["prepared"], state["cards"]
        mods = p.get("modules") or []
        user = "\n".join([
            digest(ws, p), "", f"=== VERDICT CARDS ({len(cards)} files examined) ===",
            *[f"  {c['path']}\n      role: {c['role']}   functions: "
              f"{', '.join(c['functions_resolved'] or c['functions']) or '-'}\n      evidence: "
              f"{c['evidence']}\n      why it was a candidate: "
              f"{'; '.join(c.get('why') or ['-'])}"
              for c in sorted(cards, key=lambda c: TIER[c["role"]])],
            "", f"=== MODULES ({len(mods)}; pick `module` from this list) ===",
            ", ".join(f"{m} ({n})" for m, n in mods[:60]), "",
            "Return the file order, the causal chain and the module."])
        ans = llm_step(model, SYS_RANK, user, [], Ranking, 2, rec)
        by_path = {c["path"]: c for c in cards}
        order = []
        for raw in (ans.order if ans else []):
            f = A._resolve(raw, ws, {})
            if f in by_path and f not in order:
                order.append(f)
        # cards the model left out still count: a `cause` verdict is not
        # lost because the last step forgot it
        order += [c["path"] for c in cards
                  if c["path"] not in order and c["role"] != "unrelated"]
        moved = 0
        if TIER_SORT:
            idx = sorted(range(len(order)), key=lambda i: TIER[by_path[order[i]]["role"]])
            moved = sum(i != j for i, j in enumerate(idx))
            order = [order[i] for i in idx]
        # RANK orders FILES. The regions inside a file are the card's own
        # functions, in the order EXAMINE gave them while the code was on
        # screen: two for each of the first three files, one after that.
        # `name@line` is passed on so package() lands on the exact function.
        files = []
        for i, f in enumerate(order):
            c = by_path[f]
            fns = c["functions_at"] or [x.partition("@")[0] for x in c["functions"]] or [""]
            for fn in fns[:2 if i < 3 else 1]:
                files.append(LC.RankedFile(path=f, symbol=fn, evidence=c["evidence"]))
        answer = None
        if files:
            # RANK did not answer: the cards still give an order and a chain
            chain = list(ans.causal_chain) if ans else [
                LC.ChainStep(step=f"{by_path[f]['role']}: {by_path[f]['evidence'][:200]}",
                             cited_from="read_code", file=f, log_event="")
                for f in (order * 2)[:max(2, min(len(order), 6))]]
            answer = LC.Localization(module=ans.module if ans else "",
                                     files=files[:10], causal_chain=chain[:6])
        return {"answer": answer,
                "decisions": state["decisions"] + [log(
                    "rank", answered=ans is not None, order=order,
                    moved_by_tier_rule=moved)]}

    g = StateGraph(WFState)
    for name, fn in [("gather", gather), ("shortlist", shortlist),
                     ("examine", examine), ("walk_back", walk_back), ("rank", rank)]:
        g.add_node(name, fn)
    g.add_edge(START, "gather")
    g.add_edge("gather", "shortlist")
    g.add_edge("shortlist", "examine")
    # EXAMINE -> WALK BACK once; WALK BACK -> EXAMINE only if it added files
    g.add_conditional_edges("examine", lambda s: "rank" if s.get("walked") else "walk_back",
                            {"rank": "rank", "walk_back": "walk_back"})
    g.add_conditional_edges("walk_back", lambda s: "examine" if s.get("queue") else "rank",
                            {"examine": "examine", "rank": "rank"})
    g.add_edge("rank", END)
    return g.compile()


def file_view(ws: T.Workspace, path: str, p: dict, file_chars: int | None = None,
              func_chars: int | None = None, name_boost: bool = True,
              full_first: int | None = None) -> tuple[str, dict]:
    """What EXAMINE sees of a file: all of it when it fits FILE_CHARS, else
    whole functions, most relevant first, until the budget is full.

    Relevance: functions the evidence names (a printing site, a report
    symbol), then BM25 of the body against the report. A function is shown
    whole or not at all, so a verdict never rests on half a function.
    """
    from localize import tokenize
    file_chars = FILE_CHARS if file_chars is None else file_chars
    func_chars = FUNC_CHARS if func_chars is None else func_chars
    full_first = FULL_FIRST if full_first is None else full_first
    text = ws._text_of(path)
    lines = text.splitlines()

    def numbered(a, b):
        return "\n".join(f"{i + 1}: {lines[i]}" for i in range(a, min(b, len(lines))))

    whole = numbered(0, len(lines))
    funcs = ws._funcs_of(path)
    if len(whole) <= file_chars:
        return (f"=== WHOLE FILE ({len(lines)} lines) ===\n{whole}",
                {"mode": "whole", "lines": len(lines), "functions": len(funcs),
                 "functions_shown": len(funcs)})
    named = [n for n, _c in focus_functions(ws, path, p)]
    ranked = LC.rank_functions(ws, path, tokenize(ws.query_text), len(funcs))
    # a function the report names outright goes before the BM25 order
    words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", ws.query_text)) if name_boost else set()
    in_report = [f for f in funcs if f[0].rsplit("::", 1)[-1] in words]
    order = list({f[1]: f for f in [f for f in funcs if f[0] in named]
                  + in_report + ranked}.values())
    parts, used, n = [], 0, 0
    for name, a, b in order:
        # the few most relevant functions in full, the rest by their head,
        # so more of a large file is on screen for the same budget
        cap = FUNC_FULL_CHARS if n < full_first else func_chars
        body = numbered(max(0, a - 1), b)
        if len(body) > cap:
            body = body[:cap] + f"\n... ({name} continues to line {b}; read_code shows it)"
        if used + len(body) > file_chars and parts:
            continue
        parts.append(f"--- {name} (lines {a}-{b}) ---\n{body}")
        used += len(body)
        n += 1
    head = (f"=== THE {n} MOST RELEVANT OF {len(funcs)} FUNCTIONS, each whole "
            f"(the file has {len(lines)} lines; read_code shows any other part) ===")
    return (head + "\n" + "\n\n".join(parts) if parts
            else head + "\n" + numbered(0, 120),
            {"mode": "functions", "lines": len(lines), "functions": len(funcs),
             "functions_shown": n})


def focus_functions(ws: T.Workspace, path: str, p: dict) -> list[tuple[str, str]]:
    """Up to two functions of `path`, read by code before the model sees
    the file: one the evidence names, else the one closest to the described
    behaviour. So a verdict never rests on a file nobody opened."""
    from localize import tokenize
    names: list[str] = []
    for m in p.get("printed_by", []):
        if m["file"] == path:
            names.append(m["function"].rsplit("::", 1)[-1].rsplit(".", 1)[-1])
    for s in p.get("symbols", []):
        hit = ws.resolve_symbol(path, s)
        if hit:
            names.append(hit[0])
    b = LC.best_function(ws, path, set(tokenize(p.get("behaviour") or ws.query_text[:4000])))
    if b:
        names.append(b[0])
    out = []
    for name in list(dict.fromkeys(n for n in names if n and n != "(file scope)"))[:2]:
        code = ws.read_code(path, around=name.rsplit("::", 1)[-1], n=60).get("code", "")
        if code:
            out.append((name, code[:3500]))
    if not out:
        out.append(("top of file", ws.read_code(path, n=60).get("code", "")[:3500]))
    return out


# ---------------------------------------------------------------------------
# the runner entry point: same signature and same row as lc_agent.run_lc
# ---------------------------------------------------------------------------
def run_wf(ws: T.Workspace, seed: int = 42, *, model=None, trace_dir=None,
           log_layer: bool = True, **_ignored) -> dict:
    from lc_trace import RunRecorder
    rid = f"{ws.project}:{ws.issue_key}"
    store = IncidentStore.from_pool(ws.project, ws.memory)
    ctx = {"cutoff": ws.cutoff, "this_key": ws.issue_key,
           "this_fix_shas": frozenset(ws.fix_shas),
           "dup_cluster": ws.dupclusters.get(ws.issue_key),
           "dup_of": ws.dupclusters}
    rec = RunRecorder(trace_dir, rid.replace(":", "_"),
                      {"instance": rid, "arm": "wf", "seed": seed,
                       "model": getattr(model, "model_name", str(model))}) \
        if trace_dir else None
    graph = build_graph(model, ws, store, ctx, log_layer, rec)
    stop, stop_detail, state = "submitted", "", {}
    try:
        state = graph.invoke({}, {"recursion_limit": 20})
    except Exception as e:  # noqa: BLE001 - a dead run must still write a row
        stop, stop_detail = f"error:{type(e).__name__}", str(e)[:600]
    answer = state.get("answer")
    if answer is None and stop == "submitted":
        stop = "no_answer"
    summary = rec.finish({"structured_response": answer}) if rec else {}
    p = state.get("prepared") or {}
    cards = state.get("cards") or []
    return LC.package(ws, answer, stop, stop_detail, summary, seed, log_layer,
                      arm="wf", extra={
                          "wf_route": p.get("route", ""),
                          "wf_table": [c["path"] for c in state.get("table") or []],
                          "wf_cards": cards,
                          "wf_decisions": state.get("decisions") or []})
