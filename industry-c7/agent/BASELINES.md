# Agentic baselines: what was ported, and what was changed (T25)

Reviewer-2's point 3 (Mahsa): *"Add an existing localization agent with
access to the same reports and snapshots, using the same model where
supported and a comparable inference budget."*

This file is the honest record of how that was done. Every deviation from
the published systems is listed here, and §5 is written to be copied into
threats to validity.

---

## 1. Why the released code cannot be run on this benchmark

Both repositories were read before deciding to reimplement.

| | LocAgent (ACL 2025, `gersteinlab/LocAgent`) | CoSIL (arXiv 2503.22424v3, `ZJU-CTAG/CoSIL`) |
|---|---|---|
| Parser | Python `ast`, recursively, to build the node set | Python `import` statements, parsed statically |
| Stated scope | §3.1: *"we focus our study on Python repositories and leave codebases with other programming languages as future work"*; Limitations repeats it | Threats, External Validity: *"It remains uncertain whether CoSIL can generalize to other programming languages"* |
| Harness | SWE-bench instance (repo, `base_commit`, issue text) | SWE-bench Lite / Verified only |
| Input | GitHub issue body | GitHub issue body |

Our four projects are **Java, Scala, C and C++** (`mine_benchmark.py`:
`src_ext`). There is not one Python repository in the benchmark. Our
instances are Jira tickets carrying a log bundle, against a git snapshot
SHA.

So the blocker is not an input adapter. It is that the graph construction
layer *is* the contribution in both papers, and it is Python-only in both.
Replacing it is the port. Running their code as released would localize
nothing, in every instance, on every project.

**Decision: reimplement the search strategies on our tree-sitter layer**,
and name the arms **LocAgent-style** and **CoSIL-style** — the same
convention `07-related.tex` already uses for "BRTracer-style". Neither is
ever called LocAgent or CoSIL.

## 2. What is identical to the papers

**LocAgent-style** (`baselines.run_locagent`)

- The three unified APIs of their Table 2, with those names and those
  parameters: `search_entity`, `traverse_graph` (direction, hop count,
  entity-type filter, relation-type filter), `retrieve_entity`.
- Entity identifiers in their format: `path:QualifiedName`.
- All four relation types of their Table 1: contain, import, invoke,
  inherit. Their table marks this the distinguishing property of LocAgent
  against CodexGraph, RepoGraph, RepoUnderstander and OrcaLoca.
- The four-step chain-of-thought prompt of their Figure 8, verbatim except
  that Python file extensions and the worked example are replaced with
  ones from this benchmark.
- The free-text final answer, in a fenced block, parsed for locations.
- `search_entity` falls back to BM25 over content when the name index
  misses, which is the bottom tier of their hierarchical index.

**CoSIL-style** (`baselines.run_cosil`)

- Two stages: module-call-graph-enhanced file-level reduction, then
  iterative function-level call graph search.
- The four search tools of their Table I, with those names:
  `search_class_node`, `search_class_function_node`,
  `search_file_function_node`, `exit`.
- The pruner: a separate boolean call in its own short context, which
  gates whether a node enters the context and whether its neighbours
  become visible.
- Reflective alignment: an independent short-context query at the end of
  each stage that reranks and reformats. Their ablation attributes 6-10%
  of the system's accuracy to it.
- `maxIter = 10`, their own tuned value (their Table V sweeps 1/3/5/7/10).
- The post-processing reselect when the agent names a node that does not
  exist, rather than burning the iteration.
- Their textual call-graph representation (`file: … imports: [...]`).

## 3. Fairness controls

Held constant across `ours`, `locagent` and `cosil`:

- the same served model (`qwen3.8-27b`), `temperature=0`, the same seed;
- the same snapshot, and the same issue report **including its logs**;
- the same turn budget. LocAgent-style gets `MAX_TURNS = 14`, which is our
  own budget and more than the 6-9 rounds their Table 5 reports, so a loss
  can never be attributed to a smaller budget;
- the same evaluation population and the same metric, scored by the same
  `evaluate()`.

Withheld from both baselines, because neither design has it:

- **`recall_incidents`.** Resolved-incident memory is the signal under
  test. Neither paper has any history or time-awareness.
- **The phase-0 pre-searches and the pre-walked backward hop.** That
  scaffolding is ours.
- **A structured `submit_ranking` tool.** Both papers parse free text.
  This matters: CoSIL's Table II reports LocAgent's **empty rate at
  13-22%** with Qwen models, precisely because of unparseable output.
  Handing LocAgent our tool-call submission would repair a weakness the
  literature measures, and would make the comparison meaningless.
  CoSIL-style keeps its own fix for it (reflective alignment); LocAgent
  does not get one, because LocAgent does not have one.

Granted to both baselines, slightly in their favour and noted here so it
is not mistaken for a hidden advantage of ours: `search_text`'s candidate
pool is seeded with our lexical ranking, because it is the same
`Workspace` method all arms use. It only affects LocAgent's fallback tier.

## 4. The port's own sanity check

If the reimplementation is faithful, it should reproduce the *ordering* of
a published result it was not tuned to match:

> **CoSIL-style should show a lower empty rate than LocAgent-style**,
> because reflective alignment exists to fix exactly that failure.

`empty` is recorded per instance for both arms. This is a free check that
the port is not silently broken. It is a check on the port, not a finding.

## 5. Deviations — copy this into threats to validity

1. **The graph is materialised on demand, not precomputed.** LocAgent
   reports whole-repository indexing in "a few seconds" for Python repos.
   There is no few-second whole-graph build for MongoDB or Qt. The edge
   *relations* are the same; only when they are computed differs. This
   changes cost, not reachability.
2. **Callee resolution is syntactic.** An identifier followed by `(`,
   resolved by `git grep` to a defining function. No type inference, so
   C++ overloads and virtual dispatch are over-approximated and some
   callees are missed. CoSIL asks the *LLM* to infer the call graph from
   source text, so a syntactic candidate list is close to their input; it
   is further from LocAgent's Python AST `invoke` edges.
3. **The repository structure tree is elided at 8,000 characters.** CoSIL
   feeds the whole tree. A SWE-bench Python repo has a few hundred source
   files; MongoDB and Qt have thousands. Directories past the budget are
   reported by file count instead of being listed.
4. **LocAgent's confidence-by-consistency is not implemented.** They
   aggregate reciprocal ranks across several sampled iterations. We run
   one deterministic pass at `temperature=0`, which is what every other
   arm in this paper gets. Implementing it would multiply this arm's GPU
   cost by the sample count, and would give it repeated sampling that no
   other arm has.
5. **No fine-tuned localization model.** LocAgent's headline open-source
   results use Qwen2.5 fine-tuned on 433+335 trajectories. Every arm here
   uses the same off-the-shelf served model, which is the fairness
   control; it also means these numbers are not an evaluation of their
   fine-tuned checkpoints.
6. **Metric.** We score every arm with our any-gold Acc@K. CoSIL's Top-N
   is defined the same way ("counts how often at least one bug location
   appears within the top N"). **LocAgent's own metric is stricter** — all
   gold locations must appear in the top k. Our LocAgent-style numbers are
   therefore measured more generously than their paper's.
7. **Nothing here is comparable to the published numbers.** Different
   languages, different benchmark, different issue genre (Jira + logs, not
   GitHub issues), different model, and for LocAgent a different metric.
   The only valid comparison is *within* this table, against our arms, on
   this population.

## 6. Running it

```bash
# self-check first; it needs no model server
python industry-c7/agent/test_baselines.py

# then, against a live vLLM job
python industry-c7/agent/run_agent.py --arm locagent --tag locagent-eval --workers 8
python industry-c7/agent/run_agent.py --arm cosil    --tag cosil-eval    --workers 8
```

Per instance, measured on warm caches: a 2-hop traversal costs 8-20 s of
CPU (MongoDB slowest), so LocAgent-style adds roughly a minute of CPU on
top of its LLM time. CoSIL-style is the expensive arm: up to 10 search
iterations, each with a pruner call, plus 4 staged calls and 2 reflection
calls — about 26 LLM calls against our 14 turns. Budget accordingly, and
report both arms' measured `cost` block rather than assuming parity.

**Whatever population is chosen, every other system must be rescored on
exactly those instances** (`feedback-same-population-comparisons`).

## 7. Run plan and cost — measured, not estimated

The anchor is our own full-split run, not a guess. Transcript timestamps
for the 4,409 `v3-full` runs span **01:13 to 12:25 on 2026-11-03, so 11.2 h
elapsed**, at 12.1 LLM calls and 94k prompt tokens per instance.

| arm | LLM calls / instance | 4,409 | ~1,000 |
|---|---|---|---|
| ours (done) | 12.1 measured | 11.2 h | — |
| LocAgent-style | ~12–14, same budget | ~11 h | ~2.5 h |
| CoSIL-style | ~26, but shorter contexts | ~20–28 h | ~5–6 h |

Both arms on the full split is 31–39 h, or three to four overnight jobs.
Both arms on a stratified 1,000 is about 8 h: **one job**.

**The subsample costs nothing in validity, because the rescore is free.**
Every system already stores per-instance results keyed by `issue_key`
(`{project}-instances.jsonl` holds rankings for 11 systems,
`{project}-irbl-instances.jsonl` holds per-instance metrics, the agent and
LLM arms hold their own rankings). Restricting to a subsample is therefore
a metric recomputation, not a re-run. Measured:
`full_split_breakdown.py --subset=... ` rescores **all 37 systems in 6.4
seconds**. The argument for running the full split was that a subsample
would force everything else to be re-run. It does not.

The sample is drawn once by `scripts/baseline_sample.py`, written to
`data/results/baseline-sample.json`, so the population is fixed before any
GPU time is spent. It is proportionally allocated over project x hard/easy
and matches the full split closely on every stratum (hard 0.5160 vs 0.5167;
mongodb 0.5520 vs 0.5521). Restricted to those 1,000 instances the headline
barely moves: REMEMBER Acc@1 0.667 / Acc@5 0.885 against 0.687 / 0.888 on
all 4,409, and the best baseline is the same system. That is evidence the
subsample is representative, measured before any baseline was run on it.

`baseline-pilot.json` holds a separate 30 instances, **drawn disjoint from
the 1,000**. A pilot instance is one we will have looked at before fixing
anything, so leaving it in the measurement sample would let a tuning
decision leak into the reported number.

Both files come from ONE invocation, pilot first and the sample from what
is left, so the pair regenerates byte for byte. The first version drew them
in separate runs, each reading the other to avoid overlap, which made each
draw depend on what was already on disk: re-running it produced a different
1,000. `verify_claims` now pins both id digests, so a population that moves
fails there instead of inside a reported number.

### Order of operations

1. **Pilot, 30 instances, both arms, ~20 min.** Two specific risks it
   catches. First, the model may not call the baselines' tools at all —
   the `qwen3_xml` parser failure happened once already, and
   "instructed-but-optional gets skipped" has now been measured three
   times. Second, the port's own sanity check from §4: CoSIL-style should
   show the lower empty rate. Both are worth seeing on 30 instances before
   spending 8 hours.
2. Read the pilot. Fix anything the pilot exposes.
3. **Measurement run, 1,000 instances, both arms, ~8 h.**
4. `full_split_breakdown.py --subset=data/results/baseline-sample.json
   --tag=sample1000`, which scores both new arms beside all 37 existing
   systems on exactly those instances.

```bash
python industry-c7/scripts/baseline_sample.py     # writes both, already drawn

python industry-c7/agent/run_agent.py --arm locagent --tag locagent-pilot \
    --subset data/results/baseline-pilot.json --workers 6
python industry-c7/agent/run_agent.py --arm cosil --tag cosil-pilot \
    --subset data/results/baseline-pilot.json --workers 6
```
