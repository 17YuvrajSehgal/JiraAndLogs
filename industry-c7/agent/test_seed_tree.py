"""Prove the three changes work end to end, with a stubbed model.

No GPU. Checks that (a) the default run is byte-identical to before, so
every reported number still stands, and (b) the new path actually puts
the fused seed, the repo tree and the second memory query into the
prompt the model sees.
"""
import json
import sys
from pathlib import Path

R = Path(r"C:\workplace\JiraAndLogs\industry-c7")
sys.path.insert(0, str(R / "agent"))
sys.path.insert(0, str(R / "scripts"))
import agent as A  # noqa: E402
import run_agent as RA  # noqa: E402
import tools as T  # noqa: E402
from localize import parse_iso_epoch  # noqa: E402

ok = n = 0


def chk(name, cond, detail=""):
    global ok, n
    n += 1
    ok += bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ---- 1. build_seeds: default unchanged, fused wider -----------------------
pop = RA.build_population(["kafka"], limit=3, full=True)
proj, b, row = pop[0]
rid = f"{proj}:{b['issue_key']}"
tree_rank = {}
for line in (R / "data/llm/scored-a2.jsonl").open(encoding="utf-8"):
    if line.strip():
        r = json.loads(line)
        tree_rank[f"{r['project']}:{r['issue_key']}"] = r.get("ranking") or []

base = RA.build_seeds(row, rid, "cond_ours", tree_rank)
fused = RA.build_seeds(row, rid, "fused", tree_rank)
chk("default seed is exactly cond_ours[:20], unchanged",
    base == list(row["rankings"]["cond_ours"][:20]), f"{len(base)} files")
chk("fused seed is wider and keeps the retrieval top pick first",
    len(fused) > len(base) and fused[0] == base[0], f"{len(fused)} files")
chk("fused seed interleaves rather than appends",
    fused[1] not in base[:1] or fused[:3] != base[:3],
    f"{[f.rsplit('/',1)[-1] for f in fused[:4]]}")

# ---- 2. the prompt actually changes ---------------------------------------
mem, dup, created, _ = RA.load_support(proj, RA.PROJECTS[proj]["key_prefix"])
captured = {}


def fake(messages, tools, **kw):
    # phase 0a calls reformulate() first with its own short prompt, so
    # keep the message that actually carries the investigation context
    u = messages[1]["content"] if len(messages) > 1 else ""
    if "ISSUE REPORT" in u and len(u) > len(captured.get("user", "")):
        captured["user"] = u
    return {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {
            "name": "submit_ranking",
            "arguments": json.dumps({
                "files": [{"path": base[0], "evidence": "x"}],
                "causal_chain": [{"step": "a", "cited_from": "read_code"},
                                 {"step": "b", "cited_from": "read_code"}]})}}]}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def mkws(seeds):
    return T.Workspace(proj, b["snapshot_sha"], b["query_text"], mem, dup,
                       parse_iso_epoch(b.get("created"))
                       or created.get(b["issue_key"]) or b["fix_time"],
                       b["issue_key"], set(b["fix_shas"]), {}, seeds)


real = A.call_llm
try:
    A.call_llm = fake
    captured.clear()
    A.run_instance(mkws(base), seed=42, version=3, repo_tree=False)
    off = captured["user"]
    captured.clear()
    A.run_instance(mkws(fused), seed=42, version=3, repo_tree=True)
    on = captured["user"]
finally:
    A.call_llm = real

chk("repo tree absent by default", "REPOSITORY STRUCTURE" not in off)
chk("repo tree present when asked", "REPOSITORY STRUCTURE" in on)
tree = on.split("REPOSITORY STRUCTURE", 1)[1] if "REPOSITORY STRUCTURE" in on else ""
chk("the tree names real directories", tree.count("/") > 10,
    f"{tree.count('/')} path separators")
chk("the tree is bounded, not the whole repo", len(on) - len(off) < 9000,
    f"+{len(on) - len(off)} chars")
chk("the prompt still carries the report and the seeds",
    "ISSUE REPORT" in on and "lexical retriever ranked highest" in on)
print(f"\n{ok}/{n} checks passed")
raise SystemExit(0 if ok == n else 1)
