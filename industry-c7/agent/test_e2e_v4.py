"""The v4 arms end to end, through the real runner and the real scorer.

No model, no GPU. A scripted chat model drives the real graph through
run_agent.main() for the three arm shapes the T38 job runs (log layer on,
off, and a noise condition), then c7_coverage scores them. It exists so a
runner or scorer bug costs a minute here and not a queue wait on a
cluster.

The script the stub follows, per instance:
  turn 1  two tool calls (dependencies, and match_log when it is offered)
  turn 2  prose, no tool call   -> the commit check must send it back
  turn 3  the structured answer -> module, two regions in ONE file, a
                                   chain that cites E1 and an invented line

Usage:
    python industry-c7/agent/test_e2e_v4.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "scripts"))

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402

import agent as A  # noqa: E402
import c7_coverage as COV  # noqa: E402
import run_agent as RA  # noqa: E402
from localize import OUT  # noqa: E402

ok = n = 0


def chk(name, cond, detail=""):
    global ok, n
    n += 1
    ok += bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class Stub(BaseChatModel):
    """Stateless: what to say is read off the conversation, so 2 workers
    can share one instance the way the real client is shared."""
    model_name: str = "stub"

    @property
    def _llm_type(self) -> str:
        return "stub"

    def bind_tools(self, tools, **kw):
        names = [getattr(t, "name", None) or (t.get("function") or {}).get("name")
                 or t.get("name") for t in tools]
        return self.bind(offered=names)

    def _generate(self, messages, stop=None, run_manager=None, offered=(), **kw):
        brief = next(str(m.content) for m in messages if m.type == "human")
        turn = sum(m.type == "ai" for m in messages)
        answer_tool = next((t for t in offered
                            if t in ("Shortlist", "Verdict", "Ranking")), "")
        if answer_tool:
            return ChatResult(generations=[ChatGeneration(
                message=self._wf(brief, turn, offered, answer_tool))])
        seed = re.search(r"^  1\. (\S+)$", brief, re.M).group(1)
        if turn == 0:
            calls = [{"name": "dependencies", "args": {"path": seed},
                      "id": "t1", "type": "tool_call"}]
            ev = re.search(r"^  E1[^:]*: (.+)$", brief, re.M)
            if "match_log" in offered and ev:
                calls.append({"name": "match_log", "args": {"line": ev.group(1)},
                              "id": "t2", "type": "tool_call"})
            msg = AIMessage(content="", tool_calls=calls)
        elif turn == 1:
            msg = AIMessage(content="I think it is the first file.")
        else:
            mod = re.search(r"=== MODULES .*===\n(\S+) \(", brief).group(1)
            answer = next(t for t in offered if t not in RA.LC.AGENT_TOOLS)
            msg = AIMessage(content="", tool_calls=[{
                "name": answer, "id": "t3", "type": "tool_call", "args": {
                    "module": mod,
                    "files": [{"path": seed, "symbol": "a", "evidence": "x"},
                              {"path": seed, "symbol": "b", "evidence": "y"}],
                    "causal_chain": [
                        {"step": "s1", "cited_from": "match_log", "file": seed,
                         "log_event": "E1"},
                        {"step": "s2", "cited_from": "read_code", "file": "",
                         "log_event": "a line nobody ever wrote in this report"},
                        {"step": "s3", "cited_from": "read_code", "file": seed,
                         "log_event": ""}]}}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


    def _wf(self, brief, turn, offered, answer_tool):
        """The workflow arm's three steps, told apart by the form offered."""
        def call(name, args):
            return AIMessage(content="", tool_calls=[
                {"name": name, "args": args, "id": f"w{turn}", "type": "tool_call"}])
        if answer_tool == "Shortlist":
            if turn == 0:
                return call("search_text", {"query": "state is not updated"})
            paths = re.findall(r"^  C\d+  (\S+)$", brief, re.M)
            return call("Shortlist", {"paths": paths[3:5] + ["not/a/real/File.java"],
                                      "reason": "r"})
        if answer_tool == "Verdict":
            path = re.search(r"THE FILE TO JUDGE: (\S+) ===", brief).group(1)
            if turn == 0:
                return call("read_code", {"line": 1})
            if turn == 1:
                return AIMessage(content="It looks like the cause.")   # prose
            # copied the way the real model copies them: WITH the @line
            fns = re.findall(r"([^@,\s][^@,]*@\d+)", re.search(
                r"answer with names from this list\): (.*)", brief).group(1))
            # the first seed only DETECTS, so walk back must fire
            first = "why it is a candidate: retrieval rank 1;" in brief + ";"
            return call("Verdict", {
                "role": "detects" if first else "cause",
                "functions": [f.strip() for f in fns[:2]] + ["notAFunctionHere"],
                "evidence": "line 1", "walk_back": ""})
        # RANK: list the cards in the order shown, REVERSED, so the tier
        # rule has something to correct
        paths = re.findall(r"^  (\S+)\n      role: ", brief, re.M)
        mod = re.search(r"=== MODULES .*===\n(\S+) \(", brief).group(1)
        return call("Ranking", {
            "module": mod,
            "order": list(reversed(paths)),
            "causal_chain": [
                {"step": "s1", "cited_from": "read_code", "file": paths[0],
                 "log_event": "E1"},
                {"step": "s2", "cited_from": "read_code", "file": paths[0],
                 "log_event": ""}]})


def run(tag: str, subset: Path, *extra: str) -> list[dict]:
    sys.argv = ["run_agent.py", "--arm", "lc", "--full", "--project", "kafka",
                "--subset", str(subset), "--workers", "2", "--tag", tag, *extra]
    rc = RA.main()   # a later --arm in `extra` wins, as it does in the sbatch
    path = RA.AGENT_OUT / f"agent-{tag}.jsonl"
    rows = [json.loads(l) for l in path.open(encoding="utf-8")] if path.exists() else []
    chk(f"{tag}: the runner exits 0 and writes one row per instance",
        rc == 0 and len(rows) == 3, f"rc={rc}, {len(rows)} rows")
    return rows


def main() -> int:
    import lc_agent as LC
    RA.LC = LC
    stub = Stub()
    RA.lc_model = lambda seed: stub
    A.reformulate = lambda *a, **k: {}      # no server: the report's own words

    # three kafka instances that have log events AND a noise dump
    import logs
    from localize import load_bench
    bench = {b["issue_key"]: b for b in load_bench("kafka")}
    dumped = {json.loads(l)["id"] for l in
              (OUT / "kafka-noise-dump.jsonl").open(encoding="utf-8")}
    ids = [i for i in sorted(dumped)
           if logs.select_events(bench[i.split(":")[1]]["query_text"], k=1)][:3]
    tmp = Path(tempfile.mkdtemp())
    subset = tmp / "ids.json"
    subset.write_text(json.dumps({"ids": ids}), encoding="utf-8")
    tags = ["e2e-selftest-on", "e2e-selftest-off", "e2e-selftest-noise",
            "e2e-selftest-wf"]
    made = []
    try:
        on = run(tags[0], subset)
        off = run(tags[1], subset, "--no-log-layer")
        noise = run(tags[2], subset, "--noise", "cascade_x2")

        chk("every arm answers (the commit check sent the prose turn back)",
            all(r["stop_reason"] == "submitted" for r in on + off + noise),
            str({r["stop_reason"] + " " + r.get("stop_detail", "")[:80]
                 for r in on + off + noise}))
        chk("an answered run is not sent back to answer again (3 calls: tools, prose, answer)",
            all(r["cost"]["llm_calls"] == 3 for r in on),
            str([r["cost"]["llm_calls"] for r in on]))
        chk("rows are version 4 and say which arm they are",
            all(r["version"] == 4 and r["log_layer"] for r in on)
            and not any(r["log_layer"] for r in off))
        chk("ON: log events are in the row", all(r["log_events"] for r in on))
        chk("OFF: no events, and match_log was never offered",
            not any(r["log_events"] for r in off)
            and not any("match_log" in r["tools_used"] for r in off))
        chk("ON: match_log was called and counted",
            all("match_log" in r["tools_used"] for r in on),
            str([r["tools_used"] for r in on]))
        chk("the module resolves to one this snapshot has",
            all(r["module"] and r["module"] == r["module_raw"] for r in on))
        chk("a cited id is grounded, an invented line is not, empty is None",
            all([s["log_event_grounded"] for s in r["causal_chain"]]
                == [True, False, None] for r in on),
            str([s["log_event_grounded"] for s in on[0]["causal_chain"]]))
        chk("OFF: E1 is not grounded, because no event list was shown",
            all(r["causal_chain"][0]["log_event_grounded"] is False for r in off))
        # the stub names functions `a` and `b`, which no file contains
        def top_file(r):
            return [g for g in r["regions"] if g["path"] == r["ranking"][0]]
        chk("two regions in one file are both recorded",
            all(sum(g["source"] == "agent" for g in top_file(r)) == 2 for r in on))
        chk("a name the file does not contain never outranks a real function",
            all([g["source"] for g in top_file(r)][:LC.LEX_PER_FILE]
                == ["lexical"] * LC.LEX_PER_FILE
                and not any(g["resolved"] for g in top_file(r) if g["source"] == "agent")
                for r in on),
            str([(g["source"], g["resolved"]) for g in top_file(on[0])]))
        chk("fusion-only files get a region marked lexical",
            all(any(g["source"] == "lexical" for g in r["regions"]) for r in on))
        chk("noise: the row records its condition and a report that differs",
            all(r["noise"] == "cascade_x2" for r in noise)
            and all(r["noise"] == "" for r in on))
        by_on = {r["id"]: r for r in on}
        chk("noise: seeds come from the dump, not the clean ranking",
            all(r["lexical_seed"][:10] == [json.loads(l) for l in
                (OUT / "kafka-noise-dump.jsonl").open(encoding="utf-8")
                if json.loads(l)["id"] == r["id"]
                and json.loads(l)["noise"] == "cascade_x2"][0]["seeds"][:10]
                for r in noise))
        chk("the same instances ran in every arm",
            {r["id"] for r in off} == set(by_on) == {r["id"] for r in noise})

        # ---- the staged workflow arm, same instances ----------------------
        wf = run(tags[3], subset, "--arm", "wf")
        chk("wf: every run answers", all(r["stop_reason"] == "submitted" for r in wf),
            str({r["stop_reason"] + " " + r.get("stop_detail", "")[:200] for r in wf}))
        chk("wf: rows say arm=wf and carry the route and the table",
            all(r["arm"] == "wf" and r["wf_route"] in ("trace", "logs", "prose")
                and r["wf_table"] for r in wf))
        chk("wf: the top two seeds are examined though the model did not pick them",
            all(set(r["lexical_seed"][:2]) <= {c["path"] for c in r["wf_cards"]}
                for r in wf),
            str([[c["path"][-30:] for c in r["wf_cards"]] for r in wf][:1]))
        chk("wf: a path that is not in the table is never examined",
            not any("not/a/real" in c["path"] for r in wf for c in r["wf_cards"]))
        chk("wf: every examined file has an answered verdict (prose was sent back)",
            all(c["answered"] for r in wf for c in r["wf_cards"]))
        chk("wf: no file is examined twice",
            all(len({c["path"] for c in r["wf_cards"]}) == len(r["wf_cards"]) for r in wf))
        chk("wf: at most EXAMINE_MAX verdict steps",
            all(len(r["wf_cards"]) <= RA.WF.EXAMINE_MAX for r in wf))
        chk("wf: a `detects` verdict triggers the walk-back stage",
            all(any(d["stage"] == "walk_back" for d in r["wf_decisions"]) for r in wf))

        def roles_in_order(r):
            role = {c["path"]: c["role"] for c in r["wf_cards"]}
            return [role[f] for f in r["agent_ranking"] if f in role]
        chk("wf: the tier rule puts cause before detects, whatever RANK said",
            all(roles_in_order(r) == sorted(roles_in_order(r),
                                            key=lambda x: RA.WF.TIER[x]) for r in wf)
            and any(d.get("moved_by_tier_rule") for r in wf for d in r["wf_decisions"]),
            str(roles_in_order(wf[0])))
        chk("wf: a function the file does not contain is dropped from the card",
            not any("notAFunctionHere" in c["functions_resolved"]
                    for r in wf for c in r["wf_cards"])
            and all("notAFunctionHere" in c["functions"] for r in wf for c in r["wf_cards"]))
        chk("wf: a name copied as name@line still resolves",
            all(c["functions_resolved"] for r in wf for c in r["wf_cards"]
                if any("@" in f for f in c["functions"])),
            str([(c["functions"], c["functions_resolved"]) for c in wf[0]["wf_cards"]][:2]))
        chk("wf: the model was shown whole code, not windows",
            all(c["shown"]["mode"] in ("whole", "functions")
                and c["shown"]["functions_shown"] >= 1 for r in wf for c in r["wf_cards"]),
            str([c["shown"] for c in wf[0]["wf_cards"]][:2]))
        chk("wf: a file whose card names two functions carries two agent regions",
            all(sum(g["source"] == "agent" and g["path"] == r["ranking"][0]
                    for g in r["regions"]) >= 2
                for r in wf
                if len(next(c for c in r["wf_cards"]
                            if c["path"] == r["ranking"][0])["functions_resolved"]) >= 2),
            str([(g["source"], g["resolved"]) for g in wf[0]["regions"][:5]]))
        chk("wf: the stages run in the designed order",
            all([d["stage"] for d in r["wf_decisions"]][:2] == ["route", "shortlist"]
                and r["wf_decisions"][-1]["stage"] == "rank" for r in wf))
        chk("wf: no step answers twice: at most 2 + 3 per card + 1 calls",
            all(r["cost"]["llm_calls"] <= 2 + 3 * len(r["wf_cards"]) + 1 for r in wf),
            str([(r["cost"]["llm_calls"], len(r["wf_cards"])) for r in wf]))
        chk("wf: cost is counted (model calls and tool calls)",
            all(r["cost"]["llm_calls"] >= 5 and "read_code" in r["tools_used"]
                and "search_text" in r["tools_used"] for r in wf),
            str(wf[0]["cost"]))
        chk("wf: module and grounded citation go through the same checks",
            all(r["module"] and r["causal_chain"][0]["log_event_grounded"] is True
                for r in wf))

        h = COV.health(RA.AGENT_OUT / f"agent-{tags[3]}.jsonl")["wf"]
        chk("wf: the scorer reports where gold is lost, stage by stage",
            h["n"] == 3 and h["gold_in_table"] is not None
            and h["verdict_unanswered"] == 0 and h["rank_answered"] == 1, str(h)[:300])

        # resume: a second identical call must do nothing
        before = (RA.AGENT_OUT / f"agent-{tags[0]}.jsonl").read_text(encoding="utf-8")
        sys.argv = ["run_agent.py", "--arm", "lc", "--full", "--project", "kafka",
                    "--subset", str(subset), "--workers", "2", "--tag", tags[0]]
        RA.main()
        chk("resume adds no rows",
            (RA.AGENT_OUT / f"agent-{tags[0]}.jsonl").read_text(encoding="utf-8")
            == before)

        # the scorer, on what the runner wrote
        sys.argv = ["c7_coverage.py",
                    "--run", str(RA.AGENT_OUT / f"agent-{tags[0]}.jsonl"),
                    "--base", str(RA.AGENT_OUT / f"agent-{tags[1]}.jsonl")]
        rc = COV.main()
        cov_path = OUT / f"c7-coverage-agent-{tags[0]}.json"
        made.append(cov_path)
        cov = json.loads(cov_path.read_text(encoding="utf-8"))
        s = cov["summary"]["all"]
        chk("the scorer runs on ON vs OFF", rc == 0 and cov["paired_run_minus_base"]["n_paired"] == 3)
        chk("scorer: health sees 3 answered runs",
            cov["health"]["live"] == 3 and cov["health"]["no_answer_rate"] == 0)
        chk("scorer: 1 of 3 steps cites a real event (2 cite, 1 grounded)",
            s["steps_citing_log"] == round(2 / 3, 4) and s["log_cites_grounded"] == 0.5,
            f"{s['steps_citing_log']} / {s['log_cites_grounded']}")
        chk("scorer: the agent module is scored, not skipped",
            s["module_agent_acc@1"] is not None and s["module_agent_invalid"] == 0)
        chk("scorer: strata add up",
            sum(cov["summary"][st]["n"] for st in COV.STRATA) == 3)
    finally:
        for t in tags:
            for f in [RA.AGENT_OUT / f"agent-{t}.jsonl",
                      *RA.AGENT_OUT.glob(f"transcripts/{t}-*.json")]:
                f.unlink(missing_ok=True)
            shutil.rmtree(RA.AGENT_OUT / "runs" / t, ignore_errors=True)
        for f in made:
            f.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{ok}/{n} checks passed")
    return 0 if ok == n else 1


if __name__ == "__main__":
    sys.exit(main())
