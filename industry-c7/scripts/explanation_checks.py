"""T16: mechanical checks on agent v3's explanations.

The challenge asks for an explanation linking symptom, log event and code.
v3 always produces one. This asks whether the things it points at actually
exist, with no judge and no model in the loop:

  path    does the cited file exist in the snapshot the agent was given?
  line    does a line number quoted in the evidence exist in that file?
  symbol  does an identifier quoted in the evidence occur in that file?

A failed check means the citation cannot be verified AT THE CITED LOCATION.
It does not by itself mean the reasoning is wrong: evidence legitimately
mentions symbols defined elsewhere, and prose like "around line 400" is not
a claim about an exact line. The symbol rate is therefore reported as
support, not as correctness. The path check is the strict one -- a cited
path that is not in the snapshot is a citation to a file the agent could
not have read.

NOTE on shas: a result row's `git_commit` is the REMEMBER repo's own commit,
not the code snapshot. The snapshot sha comes from the benchmark.

Usage:
    python industry-c7/scripts/explanation_checks.py [--workers 16] [--limit N]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from localize import FULL_REPOS  # noqa: E402
from localize import is_dead_row  # noqa: E402
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402

ROOT = HERE.parents[0]
AG, RES, BENCH = ROOT / "data/agent", ROOT / "data/results", ROOT / "data/benchmark"
TR = AG / "transcripts"
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark.
P = tuple(sorted(_ALL_PROJECTS))

LINE_RE = re.compile(r"\blines?\s+(\d+)(?:\s*[-–]\s*(\d+))?", re.I)
# A call or a qualified name: the things evidence actually quotes.
SYM_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
STOP = {"the", "and", "for", "this", "that", "with", "from", "line", "lines",
        "see", "not", "but", "its", "has", "was", "are", "when", "then"}

workers, limit = 16, 0
for i, a in enumerate(sys.argv):
    if a == "--workers" and i + 1 < len(sys.argv):
        workers = int(sys.argv[i + 1])
    if a == "--limit" and i + 1 < len(sys.argv):
        limit = int(sys.argv[i + 1])


def git(git_dir: Path, *args, binary=False, stdin=None):
    r = subprocess.run(["git", "--git-dir", str(git_dir), *args],
                       input=stdin, capture_output=True)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def tree(project: str, sha: str) -> set:
    """Every path at this revision, tests and non-source included: the
    question is whether the agent cited something real, not whether it is
    inside the ranking universe."""
    out = git(FULL_REPOS[project], "ls-tree", "-r", "--name-only", sha)
    return set(out.splitlines())


def contents(project: str, sha: str, paths: list) -> dict:
    """One cat-file batch for every cited path of one instance."""
    if not paths:
        return {}
    inp = "\n".join(f"{sha}:{p}" for p in paths).encode()
    out = git(FULL_REPOS[project], "cat-file", "--batch", binary=True, stdin=inp)
    res, pos = {}, 0
    for p in paths:
        end = out.find(b"\n", pos)
        if end < 0:
            break
        header = out[pos:end].split()
        if len(header) == 3 and header[1] == b"blob":
            size = int(header[2])
            res[p] = out[end + 1:end + 1 + size].decode("utf-8", "replace")
            pos = end + 1 + size + 1
        else:  # "missing" / "ambiguous": header only
            pos = end + 1
    return res


def submitted(tid: str) -> dict | None:
    """The submit_ranking call as it was actually made."""
    f = TR / f"{tid}.json"
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a truncated transcript is not a crash
        return None
    for e in reversed(d.get("events") or []):
        if e.get("type") == "tool" and e.get("name") == "submit_ranking":
            return e.get("args") or {}
    return None


def check_one(job) -> dict | None:
    project, key, sha, tid = job
    args = submitted(tid)
    if args is None:
        return None
    files = [f for f in (args.get("files") or []) if isinstance(f, dict)]
    cited = [str(f.get("path") or "") for f in files]
    cited = [c for c in cited if c]
    if not cited:
        return {"project": project, "issue_key": key, "n_cited": 0}

    paths = tree(project, sha)
    exists = [c for c in cited if c in paths]
    body = contents(project, sha, exists)

    n_line = n_line_ok = n_sym = n_sym_ok = 0
    for f in files:
        p, ev = str(f.get("path") or ""), str(f.get("evidence") or "")
        if p not in body or not ev:
            continue
        txt = body[p]
        n_lines = txt.count("\n") + 1
        for a, b in LINE_RE.findall(ev):
            for v in (a, b):
                if v:
                    n_line += 1
                    n_line_ok += int(int(v) <= n_lines)
        for s in set(SYM_RE.findall(ev)):
            if s.lower() in STOP:
                continue
            n_sym += 1
            n_sym_ok += int(s in txt)

    return {"project": project, "issue_key": key,
            "n_cited": len(cited), "n_path_ok": len(exists),
            "n_line": n_line, "n_line_ok": n_line_ok,
            "n_sym": n_sym, "n_sym_ok": n_sym_ok,
            "bad_paths": [c for c in cited if c not in paths][:5]}


def write_doc(a: dict) -> None:
    """Paper-facing numbers, generated so they cannot drift from the data."""
    proj = "\n".join(
        f"| {p} | {v['n']:,} | {v['path_rate'] * 100:.2f} | "
        f"{v['line_rate'] * 100:.2f} | {v['symbol_rate'] * 100:.1f} |"
        for p, v in a["by_project"].items())
    bad = a["cited_paths"] - a["cited_paths_that_exist"]
    doc = f"""# T16: mechanical checks on the explanations

Generated by `scripts/explanation_checks.py`. Nothing here is typed by hand.

The challenge asks for an explanation linking symptom, log event and code.
Agent v3 always produces one. Before asking whether an explanation is *good*,
this asks whether the things it points at exist. No judge, no model, no
human: three checks run against the exact snapshot the agent was given.

| check | what it asks |
|---|---|
| path | is the cited file in the snapshot at all? |
| line | does a line number quoted in the evidence exist in that file? |
| symbol | does an identifier quoted in the evidence occur in that file? |

## Results over {a['n_instances']:,} instances

| | count | rate |
|---|---|---|
| cited paths that exist | {a['cited_paths_that_exist']:,} / {a['cited_paths']:,} | **{a['path_rate'] * 100:.2f}%** |
| instances where every cited path exists | {a['instances_all_paths_exist']:,} / {a['n_with_citations']:,} | {a['instances_all_paths_exist'] / a['n_with_citations'] * 100:.1f}% |
| line references inside the file | {a['line_refs_in_range']:,} / {a['line_refs']:,} | **{a['line_rate'] * 100:.2f}%** |
| quoted symbols found in the cited file | {a['symbol_refs_found']:,} / {a['symbol_refs']:,} | {a['symbol_rate'] * 100:.1f}% |

| project | n | path % | line % | symbol % |
|---|---|---|---|---|
{proj}

## How to read these

**The path check is the strict one.** A cited path that is not in the
snapshot is a reference to a file the agent could not have opened, so it is
a fabrication rather than a judgement call. {bad} of {a['cited_paths']:,}
citations ({(1 - a['path_rate']) * 100:.2f}%) fail it. They are not random
strings: they are plausible paths with the wrong directory, such as
`src/widgets/widgets/qwidget.cpp` where Qt keeps that file in
`src/widgets/kernel/`. The paper should report the rate and the shape of the
failure, not round it to zero.

**The line check is nearly as strict.** {a['line_refs'] - a['line_refs_in_range']}
of {a['line_refs']:,} quoted line numbers fall outside the file.

**The symbol check is support, not correctness.** It is normal and correct
for evidence to name a symbol defined somewhere else -- "X calls Y, which is
declared in another file" is a true statement whose Y will not be found in
the cited file. {a['symbol_rate'] * 100:.1f}% is therefore a floor on
groundedness, not an error rate, and must never be reported as
"{(1 - a['symbol_rate']) * 100:.1f}% of symbols were hallucinated".

## What this does not show

These checks prove the citation points at something real. They say nothing
about whether the reasoning is right: an explanation can cite a file that
exists, quote a line that exists and name a symbol that occurs there, and
still be the wrong cause. That judgement is T17, and the share of correct
answers carrying a correct explanation is T18.
"""
    (ROOT / "paper" / "explanation-checks.md").write_text(doc, encoding="utf-8")


def main() -> int:
    if "--doc" in sys.argv:
        write_doc(json.loads((RES / "explanation-checks.json")
                             .read_text(encoding="utf-8")))
        print("wrote paper/explanation-checks.md")
        return 0
    bench = {}
    for p in P:
        for line in (BENCH / f"{p}.jsonl").open(encoding="utf-8"):
            if line.strip():
                b = json.loads(line)
                bench[(p, b["issue_key"])] = b["snapshot_sha"]

    jobs = []
    for line in (AG / "agent-v3-full.jsonl").open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if is_dead_row(r):
            continue
        k = (r["project"], r["issue_key"])
        if k in bench:
            jobs.append((r["project"], r["issue_key"], bench[k],
                         f"v3-full-{r['project']}_{r['issue_key']}"))
    if limit:
        jobs = jobs[:limit]
    print(f"checking {len(jobs):,} instances with {workers} workers ...")

    out = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(check_one, jobs), 1):
            if res:
                out.append(res)
            if i % 500 == 0:
                print(f"  {i:,}/{len(jobs):,}")

    tot = lambda k: sum(r.get(k, 0) for r in out)  # noqa: E731
    scored = [r for r in out if r.get("n_cited")]
    agg = {
        "n_instances": len(out),
        "n_with_citations": len(scored),
        "n_missing_transcript": len(jobs) - len(out),
        "cited_paths": tot("n_cited"),
        "cited_paths_that_exist": tot("n_path_ok"),
        "path_rate": round(tot("n_path_ok") / max(tot("n_cited"), 1), 4),
        "instances_all_paths_exist": sum(
            1 for r in scored if r["n_cited"] == r.get("n_path_ok", 0)),
        "line_refs": tot("n_line"),
        "line_refs_in_range": tot("n_line_ok"),
        "line_rate": round(tot("n_line_ok") / max(tot("n_line"), 1), 4),
        "symbol_refs": tot("n_sym"),
        "symbol_refs_found": tot("n_sym_ok"),
        "symbol_rate": round(tot("n_sym_ok") / max(tot("n_sym"), 1), 4),
        "by_project": {},
    }
    for p in P:
        g = [r for r in scored if r["project"] == p]
        if g:
            agg["by_project"][p] = {
                "n": len(g),
                "path_rate": round(sum(r["n_path_ok"] for r in g)
                                   / max(sum(r["n_cited"] for r in g), 1), 4),
                "line_rate": round(sum(r["n_line_ok"] for r in g)
                                   / max(sum(r["n_line"] for r in g), 1), 4),
                "symbol_rate": round(sum(r["n_sym_ok"] for r in g)
                                     / max(sum(r["n_sym"] for r in g), 1), 4)}
    bad = Counter()
    for r in scored:
        for b in r.get("bad_paths") or []:
            bad[b] += 1
    agg["most_common_nonexistent_paths"] = bad.most_common(10)

    (RES / "explanation-checks.json").write_text(
        json.dumps(agg, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in agg.items()
                      if k not in ("by_project", "most_common_nonexistent_paths")},
                     indent=1))
    print("\nby project:")
    for p, v in agg["by_project"].items():
        print(f"  {p:9s} n={v['n']:>5d}  path {v['path_rate']:.4f}  "
              f"line {v['line_rate']:.4f}  symbol {v['symbol_rate']:.4f}")
    if agg["most_common_nonexistent_paths"]:
        print("\nmost cited paths that do not exist in the snapshot:")
        for path, n in agg["most_common_nonexistent_paths"]:
            print(f"  {n:4d}x {path}")
    print(f"\nwrote {RES / 'explanation-checks.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
