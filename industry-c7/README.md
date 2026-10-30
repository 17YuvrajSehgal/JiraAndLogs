# ICSE 2027 Industry Challenge #7 — complete project home

Solution for *"Log-Guided Root-Cause Code Localization from Production
Issues"* (`docs/problem-7-industry-track-icse.pdf`). Deadline **Nov 13,
2026 AoE**, HotCRP `icse2027-industry-challenge.hotcrp.com`, 5–10 pages
IEEE, double-anonymous.

Everything specific to this project lives here. The parent repo's earlier
ARISE work is untouched; copies were taken 2026-10-30.

## Layout

| Path | Contents | In git? |
|---|---|---|
| `paper/` | LaTeX sources (IEEEtran, sections, refs) | yes |
| `scripts/` | The five pipeline scripts (see below) | yes |
| `docs/` | Challenge PDF, plan, running results log, reviewer-coverage table | yes |
| `data/benchmark/` | **The publishable dataset** (per-project jsonl + datasheets) | no (Zenodo) |
| `data/results/` | Rankings, summaries, stats, module metrics | no |
| `data/jira_*.json` | PJD field/linktype definitions (provenance) | no |

## Pipeline (run in this order)

```
python scripts/mine_benchmark.py --project kafka|mariadb|mongodb|qt
python scripts/build_memory_pools.py --project kafka mariadb mongodb qt
python scripts/localize.py --project <p>        # per project
python scripts/stats.py                         # paired bootstrap + BH
python scripts/module_metrics.py                # module-level Acc@K
```

All stages are deterministic (fixed seeds, greedy everything): re-runs
reproduce every table bit-identically.

## Shared infrastructure (big, regenerable — NOT copied here)

- Bare git clones in `<repo-root>/data/c7-repos/`:
  `git clone --bare https://github.com/{apache/kafka,MariaDB/server,mongodb/mongo,qt/qtbase}.git <name>-full.git`
- MongoDB container `c7-mongo` (port 27017) holding:
  - `JiraReposAnon` = The Public Jira Dataset v7 (zenodo 15719919, CC-BY-4.0),
    restored with `mongorestore --archive=... --gzip`
  - `WoL_v2_gh_so` = World of Logs v2 (zenodo 17569722, CC-BY-4.0 + MIT)
- Blob-token caches in `data/results/*.pkl` (regenerated on demand).

## Dataset definition (one rule for all four projects)

An instance is a tracker issue that satisfies ALL of:
1. log-bearing per WoL v2 (`has_log_msg` or `log_msg_count > 0`),
   extraction `pred_uncertainty <= 0.05` (WoL authors' guidance);
2. `issuetype = Bug`, `resolution in {Fixed, Done}` (from PJD fields);
3. linked to 1–3 non-revert, non-merge commits on the repo's default
   branch (subject key for KAFKA/MDEV/SERVER; `Fixes:` trailer for QTBUG);
4. the fix modified at least one non-test source file.

Gold = modified non-test source files of the fix commit(s).
Snapshot = parent of the (first) fix commit.
Query text = issue summary + description (max 20,000 chars).
Strata per instance: `gold_named_in_text` (easy/hard), `has_stack_trace`.
Memory pool (per project) = every fixed, fix-linked PJD issue (logs not
required), with true creation/resolution timestamps and duplicate clusters
from typed issue links.

Every filter's yield is counted in `data/benchmark/datasheet.json`.

## Licenses / release

Sources are CC-BY-4.0 (PJD; WoL v2 dual CC-BY-4.0/MIT) — the mined
benchmark is redistributable with attribution. Release via Zenodo with
this README's dataset definition as the datasheet core. Double-anonymous
note: cite the datasets, never the authors' relationship to them.
