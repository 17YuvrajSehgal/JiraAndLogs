"""T17: is the explanation actually right, not just well formed?

T16 checks the explanation MECHANICALLY: do the cited paths exist, do the
quoted line numbers fall inside the file, do the named symbols occur in it.
All of that can pass while the reasoning is wrong, so T16's numbers are a
floor on groundedness and say nothing about correctness.

This asks the harder question: does the account actually run from the
symptom in the report, through the log evidence, to the code region it
names, without a gap? A model other than the one under test answers it on
a rubric, and about fifty of the same instances are rated by a human so
the judge can be calibrated rather than trusted.

Two raters, deliberately. The agent is Qwen, so a Qwen judge is grading
its own work, and self-preference is well documented. The second rater is
a different model family, exactly as the annotation study did for T2b.

The judge is BLIND: it never sees the gold files, whether the ranking was
correct, or which system produced the explanation. Correctness is joined
on afterwards, which is what makes T18 ("right answer, wrong reason")
meaningful rather than circular.

Usage:
    python industry-c7/scripts/judge_explanations.py --packets   # for a human
    python industry-c7/scripts/judge_explanations.py --rate      # LLM judge
    python industry-c7/scripts/judge_explanations.py --agreement # calibrate
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "agent"))
from explanation_checks import submitted  # noqa: E402
from localize import load_bench  # noqa: E402
from localize import agent_run_rows  # noqa: E402
from localize import is_dead_row  # noqa: E402

_REPORTS: dict[str, str] = {}


def report_of(rid: str) -> str:
    """The issue report with its logs, as the agent was given it.

    It is NOT on the agent result row, only the ranking and the metrics
    are. Grading a chain without the report in front of you is grading
    prose, so this is loaded from the benchmark rather than skipped.
    """
    project = rid.split(":")[0]
    if project not in _REPORTS:
        _REPORTS[project] = "loaded"
        for b in load_bench(project):
            _REPORTS[f"{project}:{b['issue_key']}"] = b["query_text"]
    return _REPORTS.get(rid, "")

ROOT = HERE.parents[0]
AG, RES = ROOT / "data/agent", ROOT / "data/results"
JUDGE_DIR = RES / "judge"
SEED = 20261104
N_JUDGE = 400          # enough for a +/-3 point rate on the T18 subset
N_HUMAN = 50           # the calibration set, drawn from the judged ones

VERDICTS = ("sound", "partial", "unsound")

RUBRIC = """You are grading one engineer's written explanation of where a
production bug comes from. You are NOT asked whether the file is correct.
You are asked whether the EXPLANATION HOLDS TOGETHER.

Grade the chain from the reported symptom to the named code region:

  sound    every step follows from the one before it and from something
           the report or the logs actually say. No step is asserted
           without support, and there is no gap between the last step and
           the code region named.
  partial  the direction is right and most steps follow, but at least one
           step is asserted rather than supported, or there is a jump that
           a reader would have to fill in themselves.
  unsound  the chain does not connect the reported symptom to the named
           code, restates the symptom without explaining it, or rests on
           something the report and logs do not say.

Judge only what is written. Do not reward confident phrasing, length, or
plausible-sounding file names. An explanation that names the right area
for the wrong reason is `unsound`, not `sound`."""

SCHEMA = {"type": "function", "function": {
    "name": "grade_explanation",
    "description": "Grade one explanation against the rubric.",
    "parameters": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "weakest_step": {"type": "string",
                         "description": "Quote the least supported step, or "
                                        "'none' if every step is supported."},
        "reason": {"type": "string",
                   "description": "One sentence. Why that grade."}},
        "required": ["verdict", "weakest_step", "reason"]}}}


def rows() -> list[dict]:
    return agent_run_rows(AG)


def sample() -> list[dict]:
    """A fixed sample, drawn once from the scored full-split run."""
    rs = sorted(rows(), key=lambda r: r["id"])
    rng = random.Random(SEED)
    return sorted(rng.sample(rs, min(N_JUDGE, len(rs))),
                  key=lambda r: r["id"])


def prompt_for(r: dict) -> str | None:
    """The blind grading prompt.

    Takes the report, the top-ranked file, its evidence and the causal
    chain. It must never take r["gold_files"] or r["metrics"]: a judge that
    can see whether the answer was right is not grading the explanation.
    """
    args = submitted(f"v3-full-{r['id'].replace(':', '_')}")
    if not args:
        return None
    files = [f for f in (args.get("files") or []) if isinstance(f, dict)]
    if not files:
        return None
    chain = [c for c in (r.get("causal_chain") or []) if c.get("step")]
    if not chain:
        return None
    top = files[0]
    ev = "\n".join(
        f"  {i + 1}. {str(f.get('path') or '')}\n     {str(f.get('evidence') or '')[:400]}"
        for i, f in enumerate(files[:3]))
    steps = "\n".join(
        f"  {i + 1}. {str(c['step'])[:300]}"
        + (f"   [file: {c['file']}]" if c.get("file") else "")
        + (f"   [from: {c['cited_from']}]" if c.get("cited_from") else "")
        for i, c in enumerate(chain))
    rep = report_of(r["id"])
    if not rep:
        return None
    return (f"=== ISSUE REPORT (with logs) ===\n{rep[:6000]}\n\n"
            f"=== THE ENGINEER'S CHAIN, SYMPTOM TO CAUSE ===\n{steps}\n\n"
            f"=== THE CODE REGIONS NAMED, WITH THEIR EVIDENCE ===\n{ev}\n\n"
            f"The region the explanation commits to is "
            f"{str(top.get('path') or '')}.\n\n"
            f"Grade the explanation with grade_explanation.")


def blind(text: str, r: dict) -> bool:
    """Does the ANSWER KEY reach the prompt?

    Not a textual search for gold paths: a report legitimately names the
    gold file on the easy stratum, and the agent legitimately names it when
    it is right. The judge sees the same report the engineer saw, and the
    same answer the agent gave. Neither is a leak.

    What would be a leak is this script passing `gold_files` or `metrics`
    into the prompt. So test that directly: rebuild the prompt with the
    answer key replaced by a sentinel and check the sentinel never lands.
    """
    probe = dict(r)
    probe["gold_files"] = [f"__ANSWER_KEY_{i}__" for i in range(4)]
    probe["metrics"] = {"acc@1": "__ANSWER_KEY_ACC__"}
    probe["metrics_agent_only"] = probe["metrics"]
    rebuilt = prompt_for(probe)
    return rebuilt is None or "__ANSWER_KEY" not in rebuilt


def main() -> int:
    JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    samp = sample()
    jobs = [(r, prompt_for(r)) for r in samp]
    jobs = [(r, p) for r, p in jobs if p]
    bad = [r["id"] for r, p in jobs if not blind(p, r)]
    if bad:
        print(f"REFUSING TO RUN: the answer key leaks into {len(bad)} "
              f"prompts, e.g. {bad[:3]}", file=sys.stderr)
        return 1
    print(f"{len(jobs)} of {len(samp)} sampled instances have a chain and "
          f"evidence to grade; all prompts blind")

    if "--packets" in sys.argv:
        d = JUDGE_DIR / "packets"
        d.mkdir(exist_ok=True)
        rng = random.Random(SEED + 1)
        for r, p in rng.sample(jobs, min(N_HUMAN, len(jobs))):
            (d / f"{r['id'].replace(':', '_')}.md").write_text(
                f"# Grade this explanation\n\n{RUBRIC}\n\n"
                f"Write your verdict into "
                f"`{JUDGE_DIR.name}/human/{r['id'].replace(':', '_')}.json` as "
                f'`{{"verdict": "sound|partial|unsound", "reason": "..."}}`\n\n'
                f"---\n\n{p}\n", encoding="utf-8")
        (JUDGE_DIR / "human").mkdir(exist_ok=True)
        print(f"wrote {min(N_HUMAN, len(jobs))} packets to {d}")
        return 0

    if "--agreement" in sys.argv:
        return agreement()

    if "--rate" not in sys.argv:
        print("nothing to do: pass --packets, --rate or --agreement")
        return 0

    import agent as A  # noqa: E402 - only needed for --rate, needs a server
    rater = next((a.split("=", 1)[1] for a in sys.argv
                  if a.startswith("--rater=")), "qwen")
    out_f = JUDGE_DIR / f"verdicts-{rater}.jsonl"
    done = set()
    if out_f.exists():
        done = {json.loads(l)["id"] for l in out_f.open(encoding="utf-8")
                if l.strip()}
    todo = [(r, p) for r, p in jobs if r["id"] not in done]
    print(f"rating {len(todo)} ({len(done)} already done) -> {out_f.name}")

    def one(job):
        r, p = job
        resp = A.call_llm(
            [{"role": "system", "content": RUBRIC},
             {"role": "user", "content": p}], [SCHEMA],
            seed=42, max_tokens=400, force_tool="grade_explanation")
        if "error" in resp:
            return {"id": r["id"], "error": resp["error"][:200]}
        msg = resp["choices"][0].get("message", {}) or {}
        tcs = A._tool_calls_of(msg)
        if not tcs:
            return {"id": r["id"], "error": "no tool call"}
        a = A._args_of(tcs[0])
        v = str(a.get("verdict") or "").lower()
        return {"id": r["id"], "rater": rater,
                "verdict": v if v in VERDICTS else "unparsed",
                "weakest_step": str(a.get("weakest_step") or "")[:300],
                "reason": str(a.get("reason") or "")[:300]}

    with out_f.open("a", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=8) as ex:
        for i, res in enumerate(ex.map(one, todo), 1):
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
    print(f"wrote {out_f}")
    return 0


def agreement() -> int:
    """Judge against human on the calibration set, and the T18 rate."""
    from annotation_agreement import kappa  # noqa: E402
    human = {}
    hd = JUDGE_DIR / "human"
    for f in sorted(hd.glob("*.json")) if hd.exists() else []:
        d = json.loads(f.read_text(encoding="utf-8"))
        human[f.stem.replace("_", ":", 1)] = str(d.get("verdict") or "").lower()
    out: dict = {"n_human": len(human), "raters": {}}
    by_id = {r["id"]: r for r in rows()}
    for vf in sorted(JUDGE_DIR.glob("verdicts-*.jsonl")):
        rater = vf.stem.split("-", 1)[1]
        v = {}
        for l in vf.open(encoding="utf-8"):
            if not l.strip():
                continue
            d = json.loads(l)
            if d.get("verdict") and d["verdict"] != "unparsed":
                v[d["id"]] = d["verdict"]
        ent = {"n_rated": len(v), "dist": dict(Counter(v.values()))}
        pairs = [(human[k], v[k]) for k in sorted(set(human) & set(v))]
        if pairs:
            k3, p3 = kappa(pairs, VERDICTS)
            bin_pairs = [("sound" if a == "sound" else "not",
                          "sound" if b == "sound" else "not") for a, b in pairs]
            k2, p2 = kappa(bin_pairs, ("sound", "not"))
            ent["vs_human"] = {"n": len(pairs), "raw_3cat": round(p3, 4),
                               "kappa_3cat": round(k3, 4),
                               "raw_sound": round(p2, 4),
                               "kappa_sound": round(k2, 4)}
        # T18: of correct top-1 rankings, how many have a sound explanation?
        corr = [k for k in v if by_id.get(k, {}).get("metrics", {})
                .get("acc@1") == 1.0]
        wrong = [k for k in v if k in by_id and k not in corr]
        if corr:
            ent["t18"] = {
                "n_correct_top1": len(corr),
                "sound_given_correct": round(
                    sum(v[k] == "sound" for k in corr) / len(corr), 4),
                "n_wrong_top1": len(wrong),
                "sound_given_wrong": round(
                    sum(v[k] == "sound" for k in wrong) / len(wrong), 4)
                if wrong else None}
        out["raters"][rater] = ent
    (RES / "judge-agreement.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
