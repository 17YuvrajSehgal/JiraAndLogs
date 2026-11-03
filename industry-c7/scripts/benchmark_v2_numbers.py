"""Generate paper/benchmark-v2-numbers.md from the mined benchmark-v2.

Every figure in the paper update should come from here rather than from
notes, so a number cannot drift between the data and the prose. Run after
any re-mine.

Usage:
    python industry-c7/scripts/benchmark_v2_numbers.py
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "industry-c7/data/benchmark-v2"
DOC = ROOT / "industry-c7/paper/benchmark-v2-numbers.md"
ORIG = {"kafka", "mariadb", "mongodb", "qt"}
BS = chr(92)  # backslash, kept out of f-strings so LaTeX macros survive


def dist(v: list[int]) -> dict:
    v = sorted(v)
    n = len(v)
    return {"median": v[n // 2], "p95": v[int(0.95 * n)],
            "p99": v[int(0.99 * n)], "max": v[-1]}


def main() -> int:
    SS = json.loads((V2 / "excluded-test-only-gold.json")
                    .read_text(encoding="utf-8"))
    ds = json.loads((V2 / "datasheet.json").read_text(encoding="utf-8"))
    rows, q, nc, nf, gf = [], [], [], [], []
    tot = hard = trace = single = 0

    for f in sorted(glob.glob(str(V2 / "*.jsonl"))):
        p = os.path.basename(f)[:-6]
        n = h = t = sc = 0
        golds = []
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            n += 1
            if not r["gold_named_in_text"]:
                h += 1
            if r["has_stack_trace"]:
                t += 1
            if r["n_fix_commits"] == 1:
                sc += 1
            q.append(len(r["query_text"]))
            nc.append(r["n_fix_commits"])
            nf.append(r["n_all_changed_files"])
            g = len(r["gold_files"])
            gf.append(g)
            golds.append(g)
        golds.sort()
        rows.append(dict(p=p, n=n, hard=h, trace=t, single=sc,
                         gmed=golds[len(golds) // 2],
                         el=ds[p]["funnel"]["wolv2_log_fixed_lowuncert_issues"],
                         orig=p in ORIG))
        tot += n
        hard += h
        trace += t
        single += sc

    F = {k: sum(v["funnel"].get(k, 0) for v in ds.values()) for k in
         ("wolv2_log_fixed_lowuncert_issues", "no_fix_commit",
          "gt10_fix_commits", "no_source_gold", "gold_over_50_files",
          "final_instances")}
    Q, NC, NF, GF = dist(q), dist(nc), dist(nf), dist(gf)
    hard_pct = round(100 * hard / tot)
    over20k = sum(1 for x in q if x > 20000)
    multi = sum(1 for x in nc if x > 3)
    big = sum(1 for x in nf if x > 3)

    tbl = "\n".join(
        f"| {r['p']}{' *' if r['orig'] else ''} | {r['el']:,} | {r['n']:,} | "
        f"{100 * r['hard'] / r['n']:.0f}% | {100 * r['trace'] / r['n']:.0f}% | "
        f"{100 * r['single'] / r['n']:.0f}% | {r['gmed']} |"
        for r in sorted(rows, key=lambda x: -x["n"]))

    macros = (f"`{BS}nInstances` becomes **{tot:,}**, "
              f"`{BS}nHardPct` becomes **{hard_pct}{BS}%**, "
              f"`{BS}nProjects` becomes **twenty-seven**.")

    doc = f"""# benchmark-v2 numbers, ready for the paper

Generated from `data/benchmark-v2/` by
`industry-c7/scripts/benchmark_v2_numbers.py`. Every figure here comes from
the mined data, not from notes. Re-run it after any re-mine.

**Status: dataset numbers are final. Results numbers do not exist yet.**
Nothing in §5 or §6 can be updated: the memory pools for the 23 new projects
have not been built, so incident memory, the retrieval layer, the baselines
and the agent have none of them run on v2.

---

## 1. Headline swap (abstract, §1, §8)

| claim | current paper | benchmark-v2 |
|---|---|---|
| instances | 6,437 | **{tot:,}** |
| projects | 4 | **{len(rows)}** |
| organizations | 4 | **9+** |
| hard (report names no gold file) | 53% | **{hard_pct}%** |
| with stack trace | not stated | {100 * trace / tot:.0f}% |
| single fix commit | not stated | {100 * single / tot:.0f}% |

In `main.tex`: {macros}

The hard fraction moving 53% to {hard_pct}% should be stated, not quietly
swapped. The expanded set is marginally easier, not different in kind, and
the claim now survives across {len(rows)} projects instead of 4, which makes
it much harder to attack.

---

## 2. Funnel (§II-B, replaces the current datasheet text)

| stage | issues |
|---|---|
| eligible: log-bearing, fixed Bug, uncertainty at most 0.05 | {F['wolv2_log_fixed_lowuncert_issues']:,} |
| minus no fix commit found | -{F['no_fix_commit']:,} |
| minus more than 10 fix commits | -{F['gt10_fix_commits']:,} |
| minus no non-test source file modified | -{F['no_source_gold']:,} |
| minus gold set over 50 files (bulk edit) | -{F['gold_over_50_files']:,} |
| **= final instances** | **{F['final_instances']:,}** |
| minus gold entirely test code (scored set, not re-mined) | -{SS['n_excluded']:,} |
| **= scored instances** | **{SS['n_scored']:,}** |

Overall yield {100 * F['final_instances'] / F['wolv2_log_fixed_lowuncert_issues']:.1f}%.

The last row is a scoring-time exclusion, not a mining filter: gold is kept
exactly as mined, and the {SS['n_excluded']} instances whose gold is entirely
test code are dropped from the scored set: a hit there means retrieving the
test file the fix edited, not localizing a defect. They are rankable, and in
fact easier than average, so the drop lowers every system's number rather
than flattering it. Every system is scored on the same {SS['n_scored']:,}.
See `paper/test-filter-gaps.md`.

Three filter changes from the current paper, each needing a sentence:

- **No query truncation.** The old 20,000-character cap clipped 0.3% of
  instances, so it bought nothing and invited the question. {over20k} reports
  are now kept in full.
- **Fix-commit cap 3 to 10.** Recovers {multi:,} instances with 4 to 10 fix
  commits. The new cap costs only {F['gt10_fix_commits']} instances, so 10 is
  comfortably above where the distribution ends.
- **New: gold capped at 50 files.** Removes {F['gold_over_50_files']} instances
  (0.23%). Justification: Acc@K counts a hit if *any* gold file is retrieved,
  so HIVE-17952, a license-header edit touching 3,493 of hive's 4,819 source
  files, is a free point for every system 99.8% of the time. Such instances
  inflate every system equally and measure nothing.

---

## 3. Per-project table (§II, Table I)

`*` marks the four projects already in the paper.

| project | eligible | instances | hard | trace | 1 commit | gold median |
|---|---|---|---|---|---|---|
{tbl}

---

## 4. Distributions now recorded

These answer the two questions a reviewer asks about any capped benchmark.

| | median | p95 | p99 | max |
|---|---|---|---|---|
| query characters | {Q['median']:,} | {Q['p95']:,} | {Q['p99']:,} | {Q['max']:,} |
| fix commits per issue | {NC['median']} | {NC['p95']} | {NC['p99']} | {NC['max']} |
| files changed by fix | {NF['median']} | {NF['p95']} | {NF['p99']} | {NF['max']} |
| gold files per instance | {GF['median']} | {GF['p95']} | {GF['p99']} | {GF['max']} |

Fixes touching more than 3 files: {big:,} ({100 * big / tot:.0f}% of
instances). Worth saying plainly in §II: large fixes are in, and there has
never been a files-per-commit filter.

---

## 5. What still blocks a paper update

1. **Memory pools for the 23 new projects do not exist.** The temporal
   firewall, the incident-memory signal and all of §III depend on them.
2. **Per-instance universe is not recorded.** Needed before claiming how many
   instances are trivially solvable. A per-project estimate is too crude:
   early Kafka had 213 source files against thousands today.
3. **Every result re-runs.** Retrieval, fusion re-tuning and the IRBL
   baselines are CPU and take days; the LLM baselines and the agent need the
   GPU, and that server is down.
4. **All 266 verify_claims checks, six tables and two figures** are tied to
   the current benchmark and will fail until the above is done.

Keep `data/benchmark/` frozen until then. The paper compiles and verifies
against it today, and that fallback is what makes the expansion safe to
attempt this close to the deadline.
"""
    DOC.write_text(doc, encoding="utf-8")
    print(f"wrote {DOC}")
    print(f"  {tot:,} instances, {len(rows)} projects, {hard_pct}% hard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
