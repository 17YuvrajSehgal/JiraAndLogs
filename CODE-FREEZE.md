# Research Code Freeze — fresh-run reference

**Frozen commit:** `fb908f223c1daa4f45d2fb95404fdf7214174015`
**Short hash:** `fb908f2`
**Frozen at (UTC):** `2026-06-13T05:21:10Z`
**Frozen branch:** `agent-build`

---

## Why this exists

`TODO.md` describes a single-pass fresh run to close every research
question with no caveats. The cleanup that preceded the run wiped:

- All cascade output (`comparison/`, `tch-lite-refit/`, `training_runs/`, `embeddings/`)
- All v2-resplit manifests on OB and WoL
- All agent artifacts (`data/agent_runs/`, `data/agent_traces/`, `data/skill_cache/`, `data/llm_telemetry/`)
- The Neo4j database (recreated fresh)

The **frozen commit above is the research code state at the moment
the fresh run began**. Any commits stacked on top during the run are
tooling-only (the 10 missing scripts in `TODO.md §1`); they don't
change agent logic, cascade math, or evaluation methodology.

---

## Use in the paper

The artifact-availability statement should cite this hash:

> *Reproduction.* The agent code, eval harness, and analysis scripts
> are at `git@<repo>:agent-build` commit
> `fb908f223c1daa4f45d2fb95404fdf7214174015` (tooling commits up to
> the data-run completion preserve the same agent semantics). Raw
> datasets, humanized memory corpora, memory-side LLM extractions,
> and v2-resplit manifests are committed alongside; final numbers
> regenerate from the README's `Section 7` commands.

---

## Cleanup state at freeze

Per `TODO.md` Appendix A — verified 2026-06-13:

```
OB (data/derived/global/2026-05-25-dataset-v5-large-global/):
  Kept:    global-triage-examples.jsonl, jira-memory-corpus.jsonl,
           jira-shadow-humanized-{v1,v2,v2-distractors}/,
           v2_kg_extractions/all_extractions.jsonl (347 tickets) + ticket/,
           triage-feature-columns.json, triage-split-manifest.json,
           dataset-metadata.json, text-leakage-report/, family-coverage.json,
           leakage-canary-summary.json, validate-dataset-run-summary.json,
           global-triage-build-manifest.json, jira-memory-build-manifest.json,
           window-memory-matchings.jsonl
  Gone:    comparison/, training_runs/, embeddings/, v2_logseq/,
           v2_kg_extractions_rules/, v2_kg_extractions_windows/,
           v2_kg_extractions/window/  (also removed — leftover from an
                                       older pipeline that conflicted
                                       with the new flow),
           triage-split-manifest-v2-resplit.json

OTel Demo (data/derived/global/2026-06-09-otel-demo-v1-global/):
  Kept:    all build outputs intact, plus v2-resplit manifest (Phase 2.4)
  Note:    v2_kg_extractions/ doesn't exist yet — §5.1 generates it.

WoL (data/derived/global/2026-06-11-wol-real-global/):
  Kept:    global-triage-examples.jsonl, jira-memory-corpus.jsonl,
           jira-shadow-humanized-v2/, novelty-queries/, distractors/,
           v2_kg_extractions/all_extractions.jsonl (2000 tickets) + ticket/,
           window-memory-matchings.jsonl, window-memory-matchings-strong.jsonl,
           dataset-metadata.json, source-mapping.csv, triage-feature-columns.json,
           triage-split-manifest.json, gold-relations-debug.json,
           wol-extraction-manifest.json, wol-priority-mapping.json, README.md
  Gone:    tch-lite-refit/, v2_logseq/, distractor_curve_wol_pool_300.json,
           mode2_novelty_lowerbound.json, mode2_per_query.jsonl,
           triage-split-manifest-v2-resplit.json

Agent caches (data/):
  Gone:    agent_runs/, agent_traces/, skill_cache/, llm_telemetry/,
           smoke-otel-pilot-global/, neo4j-snapshots/ (was never present)
  Kept:    README.md, runs/, otel-demo-runs/, wol/

Neo4j: fresh instance, zero nodes, same credentials (URI/user/password/database).

LM Studio: qwen/qwen3.6-35b-a3b loaded on http://localhost:1234.
```

---

## Pre-flight checks passed (§0 of TODO.md)

| Check | Result |
|---|---|
| 0.1 Cleanup inventory | ✓ matches Appendix A |
| 0.2 Neo4j reachable + empty | ✓ 0 nodes, no GraphMetadata |
| 0.3 LM Studio + Qwen3.6-35B-A3B | ✓ model loaded |
| 0.4 Memory-side LLM extractions intact | ✓ OB 347 / WoL 2000 / OTel missing-as-expected |
| 0.5 Git branch + clean tree | ✓ agent-build @ fb908f2 |
| 0.6 Disk space | ✓ 104 GB free, ~5 GB budgeted |
