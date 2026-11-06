"""Does the capture actually capture everything? No model, no GPU.

The claim is that a reader can reconstruct exactly what the model saw at
every step, including what it was NOT shown. A logging layer that is
merely plausible is worse than none, because it invites conclusions the
run does not support -- which is the defect this replaces.

Usage:
    python industry-c7/agent/test_lc_trace.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "scripts"))

from langchain.agents import create_agent  # noqa: E402
from langchain.tools import tool  # noqa: E402
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from lc_trace import RunRecorder, replay  # noqa: E402


class ToolCapableFake(GenericFakeChatModel):
    """GenericFakeChatModel does not implement bind_tools, which the agent
    factory calls on every model call. Binding is a no-op here: the replies
    are scripted, so there is nothing for the tool schemas to change."""

    def bind_tools(self, tools, **kwargs):
        return self

ok = n = 0


def chk(name, cond, detail=""):
    global ok, n
    n += 1
    ok += bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


BIG = "X" * 50_000          # a tool result far larger than any context budget


@tool
def big_search(query: str) -> str:
    """Return a deliberately huge result, like a real grep over MongoDB."""
    return f"HITS for {query}\n" + BIG


@tool
def small_read(path: str) -> str:
    """Return a small result."""
    return f"contents of {path}: line 1\nline 2"


tmp = Path(tempfile.mkdtemp(prefix="c7trace-"))
try:
    rec = RunRecorder(tmp, "test-run", {"instance": "kafka:KAFKA-1", "arm": "test"})

    # a scripted model: two tool calls, then an answer
    scripted = iter([
        AIMessage(content="", tool_calls=[
            {"name": "big_search", "args": {"query": "null partition"},
             "id": "c1", "type": "tool_call"}]),
        AIMessage(content="", tool_calls=[
            {"name": "small_read", "args": {"path": "A.java"},
             "id": "c2", "type": "tool_call"}]),
        AIMessage(content="The cause is A.java line 1."),
    ])
    model = ToolCapableFake(messages=scripted)

    saver = InMemorySaver()
    agent = create_agent(model=model, tools=[big_search, small_read],
                         middleware=rec.middleware(), checkpointer=saver)
    cfg = {"configurable": {"thread_id": "t1"}}
    state = agent.invoke(
        {"messages": [{"role": "user", "content": "find the null partition bug"}]},
        cfg)
    summary = rec.finish(state, graph=agent, config=cfg)
    events = replay(rec.path)

    kinds = [e["kind"] for e in events]
    chk("the run is bracketed by start and end",
        kinds[0] == "run_start" and kinds[-1] == "run_end")
    chk("every model call is recorded",
        kinds.count("model_call") == 3, f"{kinds.count('model_call')} of 3")
    chk("every tool call is recorded",
        kinds.count("tool_call") == 2, f"{kinds.count('tool_call')} of 2")

    tools = [e for e in events if e["kind"] == "tool_call"]
    chk("tool INPUT is captured",
        tools[0]["input"] == {"query": "null partition"}, str(tools[0]["input"]))
    chk("tool OUTPUT is captured in FULL, not truncated",
        len(tools[0]["output_full"]) > 50_000,
        f"{tools[0]['output_chars']} chars")
    chk("each tool call keeps its id, so it can be joined to the message",
        tools[0]["tool_call_id"] == "c1" and tools[1]["tool_call_id"] == "c2")
    chk("tool latency is recorded", "latency_s" in tools[0])

    mcalls = [e for e in events if e["kind"] == "model_call"]
    chk("the exact messages sent are listed per call",
        all("messages_sent" in m for m in mcalls)
        and len(mcalls[-1]["messages_sent"]) > len(mcalls[0]["messages_sent"]),
        f"{len(mcalls[0]['messages_sent'])} -> {len(mcalls[-1]['messages_sent'])}")
    chk("the full prompt text is kept for every call",
        all(m.get("prompt_full") for m in mcalls))
    chk("the response and its tool calls are kept",
        mcalls[0]["response_tool_calls"][0]["name"] == "big_search")
    chk("the tools the model was ALLOWED to call are recorded",
        all("tools_offered" in m for m in mcalls)
        and set(mcalls[0]["tools_offered"]) == {"big_search", "small_read"},
        str(mcalls[0]["tools_offered"]))
    chk("the provider finish_reason is kept, so a cap is not read as a choice",
        all("finish_reason" in m for m in mcalls))
    chk("context accounting is present on every model call",
        all("chars_shown_to_model" in m["context"] for m in mcalls))
    chk("the huge tool result reaches the model's context and is counted",
        max(m["context"]["chars_shown_to_model"] for m in mcalls) > 50_000,
        f"max {max(m['context']['chars_shown_to_model'] for m in mcalls)} chars")

    end = events[-1]
    chk("the final answer is recorded", "answer" in end)
    chk("every graph super-step is recorded from the checkpointer",
        len(end["checkpoint_steps"]) >= 3, f"{len(end['checkpoint_steps'])} steps")
    chk("checkpoints carry parent links, so the path can be walked",
        any(s.get("parent") for s in end["checkpoint_steps"]))
    chk("the run can be re-opened at any step (time travel)",
        len(list(agent.get_state_history(cfg))) >= 3)

    chk("the summary is derived from the file, not kept in memory",
        summary["model_calls"] == 3 and summary["tool_calls"] == 2
        and summary["tools"] == {"big_search": 1, "small_read": 1},
        str(summary["tools"]))

    # the point of the whole exercise: a stubbed message is identified as
    # such, and the bytes withheld are counted rather than lost
    rec2 = RunRecorder(tmp, "stub-run", {})
    rec2.tool_outputs["c9"] = "F" * 10_000
    from langchain_core.messages import ToolMessage

    class Req:
        messages = [ToolMessage(content="[result of grep omitted to save "
                                        "context; it was already used]",
                                tool_call_id="c9", name="grep")]
    captured = {}

    def handler(_req):
        class R:
            result = AIMessage(content="ok")
        return R()

    rec2.model_middleware().wrap_model_call(Req(), handler)
    ev = [e for e in replay(rec2.path) if e["kind"] == "model_call"][0]
    m0 = ev["messages_sent"][0]
    chk("a stubbed tool result is flagged as stubbed", m0.get("stubbed") is True)
    chk("the withheld bytes are counted, not silently lost",
        m0.get("cut_chars") == 10_000 - m0["chars"],
        f"cut {m0.get('cut_chars')} of {m0.get('full_chars')}")
    chk("the run-level context accounting reports what was cut",
        ev["context"]["chars_cut"] > 9_000 and ev["context"]["pct_cut"] > 90,
        f"{ev['context']['chars_cut']} chars, {ev['context']['pct_cut']}%")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{ok}/{n} checks passed")
raise SystemExit(0 if ok == n else 1)
