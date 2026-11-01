"""The localization agent: a tool-using investigator over one instance.

Shape of a run (one issue in, a ranked file list out):

    Phase 0  deterministic seeding   no model. The lexical pipeline's
             own candidates and the symbols parsed out of the report are
             handed to the agent as a starting point, so the agent never
             begins from a blank repository.
    Phase 1  investigation           the model works with seven tools
             (tools.py). It reads code, resolves symbols, and queries
             firewalled incident history.
    Phase 2  mandatory recording     every file seriously considered must
             be written down with its evidence via note_candidate. A
             file that was never recorded cannot be ranked.
    Phase 3  commit                  submit_ranking closes the run.
    Phase 4  deterministic safety net  the agent's list is fused with the
             lexical ranking, so a bad or empty agent run degrades to a
             known-good baseline instead of to zero.

Reproducibility, which an agent does not get for free:
  * temperature 0 and a fixed seed on every call;
  * every tool is a pure function of the snapshot (tools.py), so a
    transcript replays to identical tool results;
  * the full transcript of every run is persisted: system prompt, tool
    schemas, each raw response, each tool call and its result;
  * the harness is restart-safe and records the git commit and model id;
  * run-to-run variation is measured by repeating seeds, not assumed away.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tools as T  # noqa: E402
from localize import RRF_K  # noqa: E402

HERE = Path(__file__).resolve().parent
SKILL = (HERE / "skills" / "fault-localization.md")
MODEL = "qwen3.8-27b"
NODE = "trig0051"
MAX_TURNS = 14
MAX_TOOL_CHARS = 9000
LIST_LEN = 10

# Evidence is a REQUIRED field of the submission rather than a separate
# optional note_candidate call. Measured on v1: 37% of runs recorded no
# evidence at all, and those runs averaged 0.8 notes against 2.3 for runs
# that found the fault. Making evidence structural removes the model's
# option to skip it.
SUBMIT = {"type": "function", "function": {
    "name": "submit_ranking",
    "description": "Commit the final ranked list, most likely first. Call "
                   "this exactly once, at the end. Every file must carry "
                   "the evidence that put it on the list.",
    "parameters": {"type": "object", "properties": {
        "files": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "properties": {
                "path": {"type": "string"},
                "evidence": {"type": "string",
                             "description": "what you SAW that implicates "
                                            "this file: the symbol, the line, "
                                            "the past incident, the call"},
                "confidence": {"type": "number"}},
            "required": ["path", "evidence"]}},
        "rationale": {"type": "string",
                      "description": "one or two sentences on what decided "
                                     "the top choice"}},
        "required": ["files"]}}}


def skill_text() -> str:
    raw = SKILL.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.S)
    return (m.group(2) if m else raw).strip()


SYSTEM = (
    "You are a senior maintainer doing root-cause fault localization on a "
    "real production issue. You are given the issue report with its logs, "
    "and tools to investigate the source tree exactly as it was when the "
    "issue was filed.\n\n"
    "The logs show where the failure was DETECTED. Your job is to find the "
    "file that CAUSED it, which is usually a different file.\n\n"
    "Use the tools. Do not answer from file names alone. When you have "
    "evidence, record it with note_candidate. Finish by calling "
    "submit_ranking exactly once.\n\n"
    "=== INVESTIGATION METHOD ===\n" + skill_text())


# ---- LLM transport ---------------------------------------------------------
def call_llm(messages: list, tools: list, seed: int = 42,
             max_tokens: int = 1500, timeout: int = 420,
             retries: int = 3, force_tool: str | None = None) -> dict:
    """One chat completion through the cluster SSH channel.

    The payload goes over stdin, never the command line, so nothing is
    mangled by shell quoting.
    """
    choice = ({"type": "function", "function": {"name": force_tool}}
              if force_tool else "auto")
    messages = [{k: v for k, v in m.items() if not k.startswith("_")}
                for m in messages]
    body = json.dumps({"model": MODEL, "messages": messages, "tools": tools,
                       "tool_choice": choice, "temperature": 0, "seed": seed,
                       "max_tokens": max_tokens,
                       "chat_template_kwargs": {"enable_thinking": False}})
    cmd = ["wsl", "-d", "Ubuntu", "ssh", "trillium",
           f"ssh trig-login01 'curl -s -m {timeout - 30} "
           f"http://{NODE}:8000/v1/chat/completions "
           f"-H \"Content-Type: application/json\" -d @-'"]
    last = ""
    for attempt in range(1, retries + 1):
        try:
            r = subprocess.run(cmd, input=body.encode(), capture_output=True,
                               timeout=timeout)
            out = r.stdout.decode("utf-8", "replace").strip()
            if not out:
                last = f"empty stdout; stderr={r.stderr.decode()[:200]}"
            else:
                d = json.loads(out)
                if "choices" in d:
                    return d
                last = f"no choices: {out[:200]}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(4 * attempt)
    return {"error": last}


REFORMULATE = {"type": "function", "function": {
    "name": "describe_fault",
    "description": "Summarise what the report says, as retrieval terms.",
    "parameters": {"type": "object", "properties": {
        "behaviour": {"type": "string",
                      "description": "One sentence describing the faulty "
                                     "BEHAVIOUR in the vocabulary the source "
                                     "code would use, not the error text. "
                                     "E.g. 'partition assignment returns null "
                                     "for a regex subscription'."},
        "identifiers": {"type": "array", "maxItems": 10,
                        "items": {"type": "string"},
                        "description": "Class, function, field or config "
                                       "names named in the report."},
        "error_messages": {"type": "array", "maxItems": 5,
                           "items": {"type": "string"}}},
        "required": ["behaviour"]}}}


def reformulate(query_text: str, seed: int = 42) -> dict:
    """One call that turns a raw report into retrieval terms.

    Caumartin & Melo (BoatSE 2026) report up to +36% MAP@1 from querying
    with LLM-extracted structured fields instead of the raw description,
    and their summary field is what carries the query when the report
    names no file. That is exactly our hard stratum, so this runs for
    every instance rather than only when the model thinks to do it.
    """
    msgs = [{"role": "system",
             "content": "You turn bug reports into search terms for finding "
                        "the faulty source file. The report describes a "
                        "SYMPTOM; express the underlying behaviour in the "
                        "words the code itself would use."},
            {"role": "user", "content": query_text[:12000]
             + "\n\nCall describe_fault."}]
    r = call_llm(msgs, [REFORMULATE], seed=seed, max_tokens=500)
    if "error" in r:
        return {"error": r["error"]}
    msg = (r.get("choices") or [{}])[0].get("message", {}) or {}
    for tc in (msg.get("tool_calls") or []):
        a = _args_of(tc)
        if a.get("behaviour"):
            return {"behaviour": str(a["behaviour"])[:300],
                    "identifiers": [str(x) for x in (a.get("identifiers") or [])
                                    if isinstance(x, str)][:10],
                    "error_messages": [str(x) for x in
                                       (a.get("error_messages") or [])][:5],
                    "usage": r.get("usage")}
    return {"error": "no describe_fault call"}


def trim_history(messages: list, keep_full: int = 6) -> list:
    """Keep the newest `keep_full` tool results verbatim; replace older ones
    with a stub naming the tool.

    The whole thread is re-sent every turn, so cost grows quadratically with
    turns. The first smoke run spent 117k-131k prompt tokens on a single
    instance. The user's earlier agent handles this the same way (keep the
    newest 40 KB of tool output, stub the rest) and the stub keeps the model
    aware that the call happened.
    """
    idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for i in idx[:-keep_full] if len(idx) > keep_full else []:
        m = messages[i]
        if not m.get("_stubbed"):
            m["content"] = (f"[result of {m.get('name', 'tool')} omitted to "
                            f"save context; it was already used]")
            m["_stubbed"] = True
    return messages


def _tool_calls_of(msg: dict) -> list:
    return msg.get("tool_calls") or []


def _args_of(tc: dict) -> dict:
    raw = (tc.get("function") or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            return json.loads(m.group(0)) if m else {}
        except Exception:  # noqa: BLE001
            return {}


def fuse(agent_list: list[str], lexical: list[str]) -> list[str]:
    """Safety net: BACKFILL, not blending.

    The first design RRF-blended the agent's ranking with the lexical one
    at weight 0.6. Measured on v1 that was a net loss: agent-only scored
    >= fused on every checkpoint, and on KAFKA-4131 blending pushed a gold
    file the agent had ranked 2nd out of the top five entirely. The
    lexical votes were displacing correct answers to insure against a
    failure that never occurred (zero empty agent rankings in 150+ runs).

    So the agent's order is preserved exactly, and the lexical ranking is
    appended only to fill remaining slots. That keeps the protection
    against an empty or short agent answer while removing the demotion.
    """
    out = list(dict.fromkeys(agent_list))
    for f in lexical:
        if f not in out:
            out.append(f)
    return out


def run_instance(ws: T.Workspace, seed: int = 42,
                 max_turns: int = MAX_TURNS,
                 behaviour_query: str | None = None) -> dict:
    """Investigate one instance. Returns the ranking plus a transcript."""
    # Phase 0a: one call turns the report into retrieval terms. The raw
    # report is symptom-shaped; searching code with it finds the detection
    # site. Falls back to the report's own words if the call fails.
    rf = {} if behaviour_query else reformulate(ws.query_text, seed=seed)
    behaviour = (behaviour_query or rf.get("behaviour")
                 or " ".join(ws.query_text.split()[:60]))
    # symbols, filtered to what actually exists in THIS snapshot, so turns
    # are not spent resolving library names like NullPointerException
    syms = ws.symbols_in_snapshot(
        list(dict.fromkeys(list(rf.get("identifiers") or [])
                           + T.raw_report_symbols(ws.query_text))))
    # Two searches run BEFORE the loop so they happen unconditionally rather
    # than only when the model thinks of them. v1 measured recall_incidents
    # at 0.4 calls/run: the project's own resolved history, which is the one
    # signal a plain LLM cannot replicate, was being consulted in well under
    # half of runs. Handing it over as evidence removes that dependence.
    pre = ws.search_text(behaviour, k=8).get("hits", [])
    past = ws.recall_incidents(behaviour, k=5).get("admissible_matches", [])
    ws.calls.clear()  # pre-searches are harness setup, not agent actions
    user = (
        f"Project: {ws.project}\n\n=== ISSUE REPORT (with logs) ===\n"
        f"{ws.query_text[:18000]}\n\n"
        f"=== STARTING POINTS (unverified; verify before trusting) ===\n"
        + (f"behaviour, restated in code vocabulary: {behaviour}\n\n"
           if behaviour else "")
        + f"symbols from the report that exist in this snapshot: "
          f"{', '.join(syms) or 'none'}\n\n"
        f"files a lexical retriever ranked highest:\n"
        + "\n".join(f"  {i + 1}. {f}" for i, f in
                    enumerate(ws.seed_candidates[:12]))
        + "\n\nfiles whose CODE matches the described behaviour:\n"
        + "\n".join("  - {}  (best match in {}, terms: {})".format(
            h["file"], h["best_region"], ", ".join(h["matched_terms"]))
            for h in pre[:8])
        + ("\n\npast incidents in this project that read like this one, and "
           "the files their fixes touched (only incidents resolved before "
           "this report existed):\n"
           + "\n".join("  - {} (weight {}, that fix touched {} file(s)): {}"
                       .format(m["incident"], m["weight"],
                               m["n_files_in_that_fix"],
                               ", ".join(m["fixed_files"][:4]))
                       for m in past[:5])
           if past else "\n\npast incidents: none admissible for this report.")
        + "\n\nInvestigate, then submit a ranked list of up to 10 files "
          "that may contain the ROOT CAUSE. A file that a similar past "
          "incident was fixed in is strong evidence, especially when the "
          "report names no file.")
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user}]
    events = [{"type": "system", "content": SYSTEM},
              {"type": "user", "content": user}]
    submitted, rationale, stop = [], "", "max_turns"
    usage = {"in": 0, "out": 0, "calls": 0}

    for turn in range(max_turns):
        left = max_turns - turn
        # Turn-budget pressure. Without it the model explores until the
        # budget runs out and never commits: the first smoke test spent
        # 21-26 tool calls and submitted nothing on all three instances.
        if left == 3:
            messages.append({"role": "user", "content":
                             "3 turns left. Record the files you are "
                             "considering with note_candidate now, then "
                             "call submit_ranking."})
        # Last turn: force the commit rather than hoping for it.
        force = left <= 1
        tools_arg = [SUBMIT] if force else T.TOOL_SCHEMAS + [SUBMIT]
        resp = call_llm(trim_history(messages), tools_arg, seed=seed,
                        force_tool="submit_ranking" if force else None)
        if "error" in resp:
            events.append({"type": "error", "turn": turn,
                           "error": resp["error"]})
            stop = "llm_error"
            break
        usage["calls"] += 1
        u = resp.get("usage") or {}
        usage["in"] += u.get("prompt_tokens", 0) or 0
        usage["out"] += u.get("completion_tokens", 0) or 0
        msg = resp["choices"][0].get("message", {}) or {}
        events.append({"type": "assistant", "turn": turn,
                       "content": (msg.get("content") or "")[:1500],
                       "tool_calls": [
                           {"name": (tc.get("function") or {}).get("name"),
                            "args": _args_of(tc)}
                           for tc in _tool_calls_of(msg)]})
        tcs = _tool_calls_of(msg)
        if not tcs:
            # no tool call: nudge once, then stop
            if turn >= max_turns - 1 or stop == "nudged":
                stop = "no_tool_call"
                break
            messages.append({"role": "assistant",
                             "content": msg.get("content") or ""})
            messages.append({"role": "user",
                             "content": "Continue investigating with the "
                                        "tools, or call submit_ranking now."})
            stop = "nudged"
            continue
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": tcs})
        done = False
        for tc in tcs:
            name = (tc.get("function") or {}).get("name") or ""
            args = _args_of(tc)
            if name == "submit_ranking":
                # accept both shapes: [{path, evidence}] (current schema) and
                # a bare list of strings (older schema / degraded output)
                submitted, evidence = [], []
                for f in (args.get("files") or []):
                    if isinstance(f, dict) and f.get("path"):
                        submitted.append(str(f["path"]))
                        evidence.append({"file": str(f["path"]),
                                         "reason": str(f.get("evidence") or "")[:400],
                                         "confidence": float(f.get("confidence") or 0.5),
                                         "in_snapshot": str(f["path"]) in ws.snap.blob_of})
                    elif isinstance(f, str):
                        submitted.append(f)
                ws.notes.extend(evidence)
                rationale = str(args.get("rationale") or "")[:600]
                stop, done = "submitted", True
                result = {"accepted": len(submitted)}
            else:
                result = T.dispatch(ws, name, args)
            payload = json.dumps(result, default=str)[:MAX_TOOL_CHARS]
            events.append({"type": "tool", "turn": turn, "name": name,
                           "args": args, "result": payload[:2500]})
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                             "name": name, "content": payload})
        if done:
            break

    # resolve model paths onto real snapshot files, then apply the safety net
    resolver_stats: dict = {}
    resolved = []
    for raw in submitted:
        f = _resolve(raw, ws, resolver_stats)
        if f and f not in resolved:
            resolved.append(f)
    noted = [n["file"] for n in sorted(ws.notes,
                                       key=lambda x: -x["confidence"])
             if n["in_snapshot"]]
    agent_list = resolved or noted
    final = fuse(agent_list, ws.seed_candidates)[:LIST_LEN] \
        if agent_list else list(ws.seed_candidates[:LIST_LEN])
    return {"ranking": final, "agent_ranking": agent_list[:LIST_LEN],
            "lexical_seed": ws.seed_candidates[:LIST_LEN],
            "notes": ws.notes, "tool_calls": ws.calls,
            "stop_reason": stop, "rationale": rationale, "usage": usage,
            "resolver": resolver_stats, "events": events, "seed": seed}


def _resolve(raw: str, ws: T.Workspace, stats: dict) -> str | None:
    """Map a model-written path onto a real file in this snapshot."""
    if not isinstance(raw, str) or not raw.strip():
        stats["dropped"] = stats.get("dropped", 0) + 1
        return None
    s = raw.strip().replace("\\", "/").lstrip("./").lstrip("/")
    if s in ws.snap.blob_of:
        stats["exact"] = stats.get("exact", 0) + 1
        return s
    for cut in (1, 2):
        t = "/".join(s.split("/")[cut:])
        if t and t in ws.snap.blob_of:
            stats["prefix_strip"] = stats.get("prefix_strip", 0) + 1
            return t
    base = s.rsplit("/", 1)[-1]
    hits = [f for f in ws.snap.files if f.rsplit("/", 1)[-1] == base]
    if len(hits) == 1:
        stats["basename"] = stats.get("basename", 0) + 1
        return hits[0]
    suf = [f for f in ws.snap.files if f.endswith(s)]
    if len(suf) == 1:
        stats["suffix"] = stats.get("suffix", 0) + 1
        return suf[0]
    stats["dropped"] = stats.get("dropped", 0) + 1
    return None
