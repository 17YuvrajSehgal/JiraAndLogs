"""Does trim_history drop the right messages, in both modes?

Two properties matter and neither is obvious from reading the function:

1. COUNT MODE (the default, C7_CTX_CHARS unset) must behave exactly as it
   did before the budget mode existed. The 26,544-instance run is in
   flight under it; if this drifts, the headline number comes from two
   different agents.

2. Either mode must never leave a tool_call with no matching tool result.
   That is an invalid conversation and the server rejects it. An assistant
   turn goes only when EVERY call it made is going too.

Run: python industry-c7/agent/test_trim_history.py
"""
from __future__ import annotations

import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))


class Msg:
    """Minimal stand-in for a LangChain message."""

    def __init__(self, type_, content="", tool_calls=None, tool_call_id=None):
        self.type = type_
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_call_id = tool_call_id


class Req:
    def __init__(self, messages):
        self.messages = messages
        self.sent = None

    def override(self, messages):
        self.sent = messages
        r = Req(messages)
        r.sent = messages
        return r


def convo(n_pairs, result_chars=1000):
    """human, then n_pairs of (ai calling tool k, tool result k)."""
    msgs = [Msg("human", "x" * 500)]
    for k in range(n_pairs):
        msgs.append(Msg("ai", "", tool_calls=[{"id": f"c{k}"}]))
        msgs.append(Msg("tool", "r" * result_chars, tool_call_id=f"c{k}"))
    return msgs


def run(mod, msgs):
    """Call the middleware and return what it would have sent."""
    captured = {}

    def handler(request):
        captured["msgs"] = list(request.messages or [])
        return "ok"

    # @wrap_model_call turns the function into a middleware object; the
    # wrapped function is reached through its wrap_model_call method.
    mod.trim_history.wrap_model_call(Req(msgs), handler)
    return captured["msgs"]


def counts(out):
    return (sum(1 for m in out if m.type == "tool"),
            sum(1 for m in out if m.type == "ai"))


def check_pairing(out, label):
    """Every tool_call id present must have its result, and vice versa."""
    called = {tc["id"] for m in out if m.type == "ai" for tc in m.tool_calls}
    answered = {m.tool_call_id for m in out if m.type == "tool"}
    assert called == answered, (
        f"{label}: dangling calls {called ^ answered}")


def main() -> int:
    fails = []

    # ---- count mode, the default the live run uses -----------------------
    os.environ.pop("C7_KEEP_FULL", None)
    os.environ.pop("C7_CTX_CHARS", None)
    for m in ("lc_agent",):
        sys.modules.pop(m, None)
    import lc_agent as L
    assert L.KEEP_FULL == 6 and L.CTX_CHARS == 0, "defaults moved"

    for pairs, want_tools in ((3, 3), (6, 6), (10, 6), (25, 6)):
        out = run(L, convo(pairs))
        got, _ = counts(out)
        ok = got == want_tools
        print(f"{'ok  ' if ok else 'FAIL'} count mode, {pairs:>2} pairs -> "
              f"{got} tool results kept (want {want_tools})")
        fails.append(not ok)
        check_pairing(out, f"count/{pairs}")

    # ---- budget mode -----------------------------------------------------
    os.environ["C7_KEEP_FULL"] = "6"
    os.environ["C7_CTX_CHARS"] = "12000"
    sys.modules.pop("lc_agent", None)
    import lc_agent as B
    assert B.CTX_CHARS == 12000

    # 25 pairs x 1000 chars = 25,500 chars. Budget 12,000 keeps roughly 12
    # results, which is far more than the count mode's 6 and still bounded.
    out = run(B, convo(25, 1000))
    kept, _ = counts(out)
    total = sum(len(m.content) for m in out)
    ok = 6 <= kept < 25 and total <= 12000 + 1000
    print(f"{'ok  ' if ok else 'FAIL'} budget mode, 25 pairs, 12k budget -> "
          f"{kept} kept, {total} chars (want 6..24 and <=13000)")
    fails.append(not ok)
    check_pairing(out, "budget/25")

    # under budget: nothing is dropped at all
    out = run(B, convo(8, 100))
    kept, _ = counts(out)
    ok = kept == 8
    print(f"{'ok  ' if ok else 'FAIL'} budget mode, small history -> "
          f"{kept} kept (want 8, nothing dropped)")
    fails.append(not ok)
    check_pairing(out, "budget/8")

    # huge results: the floor holds, it never cuts below KEEP_FULL
    out = run(B, convo(20, 50000))
    kept, _ = counts(out)
    ok = kept == 6
    print(f"{'ok  ' if ok else 'FAIL'} budget mode, oversized results -> "
          f"{kept} kept (want 6, the floor)")
    fails.append(not ok)
    check_pairing(out, "budget/floor")

    n = len(fails)
    print(f"\n{n} checks, {sum(fails)} failed")
    return 1 if any(fails) else 0


if __name__ == "__main__":
    sys.exit(main())
