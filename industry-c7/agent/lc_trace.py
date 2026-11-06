"""Complete capture of an agent run: every step, both sides of every call,
and what the model was NOT shown.

Why this exists
---------------
The hand-rolled transcript records each tool's FULL result. The model
often did not see that. Two layers cut it down first:

    dispatch        tool output is truncated to MAX_TOOL_CHARS (9,000)
                    before it is ever put in a message
    trim_history    older tool messages are replaced with a stub
                    ("[result of X omitted...]") once 6 newer ones exist

So a transcript can show evidence the model never read, and a reader
reconstructing "why did it rank that file" can reach a conclusion the run
does not support. That is a reproducibility problem, not a cosmetic one.

What is captured here, per run
------------------------------
  step      one row per graph super-step, from the checkpointer
  model     every model call: the exact messages sent, their token
            counts, which earlier messages were stubbed or dropped, the
            response, latency
  tool      every tool call: full input, FULL output, the truncated form
            the model actually received, and the delta between them
  context   per model call, bytes available vs bytes shown, so "how much
            got cut" is a number rather than an impression

Everything lands in two places that answer different questions:

  runs/<id>.jsonl      the event stream, grep-able, one JSON per line
  checkpoints.sqlite   LangGraph state at every super-step, which makes
                       `get_state_history` and time travel work -- you
                       can re-open the run at step 7 and look around
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from langchain.agents.middleware import wrap_model_call, wrap_tool_call

# C7_TRACE_RAW=1 keeps the exact message list of every model call, so a
# failing request can be replayed byte for byte instead of reconstructed
# from a flattened preview.
RAW = os.environ.get("C7_TRACE_RAW") == "1"


def _text(content: Any) -> str:
    """Message content is a str or a list of blocks; normalise for sizing."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict):
                out.append(str(b.get("text") or b.get("content") or ""))
            else:
                out.append(str(b))
        return "".join(out)
    return str(content or "")


def _approx_tokens(s: str) -> int:
    """Rough, and labelled as rough. The provider's own count is recorded
    whenever it comes back in usage_metadata; this exists so a dropped
    usage field does not leave a hole in the accounting."""
    return max(1, len(s) // 4)


def _reasoning(msg) -> str:
    """Providers disagree on where the thinking block lands: vLLM puts it
    in reasoning_content, others in reasoning, LangChain may fold it into
    additional_kwargs or a content block. Check all of them rather than
    silently recording nothing."""
    for attr in ("reasoning_content", "reasoning"):
        v = getattr(msg, attr, None)
        if isinstance(v, str) and v:
            return v
    extra = getattr(msg, "additional_kwargs", None) or {}
    for k in ("reasoning_content", "reasoning"):
        v = extra.get(k)
        if isinstance(v, str) and v:
            return v
    blocks = getattr(msg, "content", None)
    if isinstance(blocks, list):
        out = [str(b.get("thinking") or b.get("reasoning") or "")
               for b in blocks
               if isinstance(b, dict)
               and b.get("type") in ("thinking", "reasoning")]
        if any(out):
            return "".join(out)
    return ""


def _stubbed(s: str) -> bool:
    return s.startswith("[result of ") and "omitted" in s[:80]


class RunRecorder:
    """One recorder per instance. Append-only; safe to read while running."""

    def __init__(self, run_dir: Path, run_id: str, meta: dict | None = None):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.path = self.dir / f"{run_id}.jsonl"
        self.seq = 0
        self.t0 = time.time()
        # full tool outputs keyed by call id, so the event stream can hold
        # the complete result even when the model got a truncated one
        self.tool_outputs: dict[str, str] = {}
        self._emit("run_start", meta or {})

    def _emit(self, kind: str, payload: dict) -> None:
        self.seq += 1
        rec = {"run_id": self.run_id, "seq": self.seq, "kind": kind,
               "t": round(time.time() - self.t0, 3), **payload}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")

    # ---- the two middleware hooks ----------------------------------------
    def model_middleware(self):
        rec = self

        @wrap_model_call
        def capture_model(request, handler):
            msgs = list(getattr(request, "messages", []) or [])
            shown = []
            present: set = set()
            avail_chars = shown_chars = 0
            for i, m in enumerate(msgs):
                body = _text(getattr(m, "content", m))
                role = getattr(m, "type", None) or getattr(m, "role", "?")
                name = getattr(m, "name", None)
                shown_chars += len(body)
                entry = {"i": i, "role": role, "name": name,
                         "chars": len(body), "tokens_approx": _approx_tokens(body)}
                if role == "tool":
                    cid = getattr(m, "tool_call_id", None)
                    entry["tool_call_id"] = cid
                    present.add(cid)
                    if _stubbed(body):
                        # a placeholder: the real output is in tool_outputs
                        full = rec.tool_outputs.get(cid, "")
                        entry.update({"stubbed": True, "full_chars": len(full),
                                      "cut_chars": max(0, len(full) - len(body))})
                        avail_chars += len(full)
                    else:
                        avail_chars += len(body)
                else:
                    avail_chars += len(body)
                shown.append(entry)

            # A trimmed history DROPS stale exchanges rather than stubbing
            # them, so no marker is left in the message list to find. The
            # only honest way to price the gap is against the outputs this
            # recorder watched the tools produce.
            dropped = [(cid, out) for cid, out in rec.tool_outputs.items()
                       if cid not in present]
            avail_chars += sum(len(o) for _c, o in dropped)

            prompt_preview = "\n\n".join(
                f"[{e['role']}] {_text(getattr(m, 'content', m))[:4000]}"
                for e, m in zip(shown, msgs))

            t = time.time()
            resp = handler(request)
            dt = round(time.time() - t, 3)

            out_msg = getattr(resp, "result", None) or getattr(resp, "message", None)
            if isinstance(out_msg, list) and out_msg:
                out_msg = out_msg[0]
            content = _text(getattr(out_msg, "content", ""))
            tool_calls = [{"name": tc.get("name"), "args": tc.get("args"),
                           "id": tc.get("id")}
                          for tc in (getattr(out_msg, "tool_calls", None) or [])]
            usage = getattr(out_msg, "usage_metadata", None) or {}

            # what the model was ALLOWED to do, not just what it did. The
            # turn-budget middleware withdraws the tools at the hard stop,
            # and without this line a reader cannot tell a model that chose
            # not to call one from a model that had none to call.
            offered = [getattr(t, "name", None) or getattr(t, "__name__", str(t))
                       for t in (getattr(request, "tools", None) or [])]
            rec._emit("model_call", {
                "latency_s": dt,
                "n_messages_sent": len(msgs),
                "tools_offered": offered,
                "finish_reason": (getattr(out_msg, "response_metadata", {}) or {})
                                  .get("finish_reason"),
                "messages_sent": shown,
                "context": {
                    "chars_shown_to_model": shown_chars,
                    "chars_available": avail_chars,
                    "chars_cut": max(0, avail_chars - shown_chars),
                    "pct_cut": (round(100 * (avail_chars - shown_chars)
                                      / avail_chars, 1) if avail_chars else 0.0),
                    "n_stubbed_messages": sum(1 for e in shown if e.get("stubbed")),
                    "n_dropped_results": len(dropped),
                    "dropped_tool_call_ids": [c for c, _o in dropped],
                },
                "usage": {"input_tokens": usage.get("input_tokens"),
                          "output_tokens": usage.get("output_tokens"),
                          "total_tokens": usage.get("total_tokens")},
                # the exact messages, replayable. prompt_full flattens the
                # roles away and clips each message at 4,000 chars, which
                # is enough to read and not enough to re-send -- every
                # diagnosis so far has needed a separate capture script
                # for exactly this. Off by default: ~20KB per call, which
                # is fine for a pilot and 300MB for a 1,000-instance run.
                "request_messages": ([
                    {"role": getattr(m, "type", None) or getattr(m, "role", "?"),
                     "content": _text(getattr(m, "content", m)),
                     "tool_calls": [{"name": tc.get("name"),
                                     "args": tc.get("args"),
                                     "id": tc.get("id")}
                                    for tc in (getattr(m, "tool_calls", None) or [])],
                     "tool_call_id": getattr(m, "tool_call_id", None)}
                    for m in msgs] if RAW else None),
                # LangChain carries the system prompt OUTSIDE
                # request.messages, so a trace holding only the messages
                # is not the request. Replaying one without this answered
                # cleanly while the real call stalled, and the difference
                # was invisible in the trace. Same class of defect as the
                # transcript clipping this module was written to replace.
                "system_prompt": getattr(request, "system_prompt", None),
                # the reasoning block in FULL. On a tool-calling turn the
                # visible content is usually empty, so this is the only
                # record of why the model chose that move. The chat
                # template drops prior thinking, so it survives nowhere
                # else.
                "reasoning": _reasoning(out_msg),
                "response_text": content[:8000],
                "response_tool_calls": tool_calls,
                "prompt_full": prompt_preview,
            })
            return resp

        return capture_model

    def tool_middleware(self):
        rec = self

        @wrap_tool_call
        def capture_tool(request, handler):
            call = getattr(request, "tool_call", {}) or {}
            name = call.get("name")
            args = call.get("args")
            cid = call.get("id")
            t = time.time()
            result = handler(request)
            dt = round(time.time() - t, 3)

            full = _text(getattr(result, "content", result))
            if cid:
                rec.tool_outputs[cid] = full
            rec._emit("tool_call", {
                "tool": name, "tool_call_id": cid,
                "latency_s": dt,
                "input": args,
                "output_full": full,                     # never truncated here
                "output_chars": len(full),
                "output_preview": full[:2000],
            })
            return result

        return capture_tool

    def middleware(self) -> list:
        return [self.model_middleware(), self.tool_middleware()]

    # ---- closing out ------------------------------------------------------
    def finish(self, final_state: dict | None, graph=None, config=None) -> dict:
        """Write the answer, then the checkpointer's own view of every
        super-step so the run can be re-opened and walked afterwards."""
        steps = []
        if graph is not None and config is not None:
            try:
                for snap in graph.get_state_history(config):
                    steps.append({
                        "checkpoint_id": snap.config.get("configurable", {})
                                            .get("checkpoint_id"),
                        "parent": (snap.parent_config or {})
                                     .get("configurable", {}).get("checkpoint_id"),
                        "step": (snap.metadata or {}).get("step"),
                        "source": (snap.metadata or {}).get("source"),
                        "next": list(snap.next or ()),
                        "n_messages": len((snap.values or {}).get("messages", [])),
                        "created_at": snap.created_at,
                    })
            except Exception as e:  # noqa: BLE001 - never lose a run over its log
                self._emit("history_error", {"error": f"{type(e).__name__}: {e}"})
        sr = (final_state or {}).get("structured_response")
        self._emit("run_end", {
            "wall_s": round(time.time() - self.t0, 3),
            "n_events": self.seq,
            "checkpoint_steps": steps,
            "answer": sr.model_dump() if hasattr(sr, "model_dump") else sr,
        })
        return self.summary()

    def summary(self) -> dict:
        """Totals, read back from the file so the summary can never drift
        from the events it summarises."""
        model_calls = tool_calls = 0
        cut = shown = 0
        tin = tout = 0
        tools: dict[str, int] = {}
        for line in self.path.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            if r["kind"] == "model_call":
                model_calls += 1
                c = r.get("context", {})
                cut += c.get("chars_cut", 0)
                shown += c.get("chars_shown_to_model", 0)
                u = r.get("usage", {})
                tin += u.get("input_tokens") or 0
                tout += u.get("output_tokens") or 0
            elif r["kind"] == "tool_call":
                tool_calls += 1
                tools[r["tool"]] = tools.get(r["tool"], 0) + 1
        return {"run_id": self.run_id, "events": self.seq,
                "model_calls": model_calls, "tool_calls": tool_calls,
                "tools": tools,
                "input_tokens": tin, "output_tokens": tout,
                "chars_shown": shown, "chars_cut": cut,
                "pct_context_cut": round(100 * cut / (shown + cut), 1)
                                   if (shown + cut) else 0.0,
                "path": str(self.path)}


def replay(path: Path) -> list[dict]:
    """Read a captured run back. Plain JSONL on purpose: the record must
    outlive the library that produced it."""
    return [json.loads(l) for l in Path(path).open(encoding="utf-8") if l.strip()]
