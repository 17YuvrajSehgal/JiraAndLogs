# Localization agent: architecture and why each part exists

Written 2026-11-01, before any evaluation run. Every design choice below
is tied either to a measurement we made on this benchmark tonight, to a
documented failure in the user's earlier agent, or to a published result.
Nothing here is chosen by taste.

---

## 0. What the agent has to beat

Measured tonight on 4,508 evaluation instances, not assumed:

| system | Acc@5 | note |
|---|---|---|
| REMEMBER (ours, lexical) | 0.688 | CPU, sub-second |
| Qwen3.8-27B standalone (Agentless-style) | 0.775 | beats ours on all 4 projects |
| LLM rerank of our top-20 | 0.772 | |
| **RRF(ours + LLM)** | **0.804** | **the real bar** |
| oracle: union of all three top-5 | 0.884 | ceiling for selection-only methods |

The bar is **0.804**, not 0.775. Beating the plain LLM is not enough,
because a trivial fusion already does that.

---

## 1. The three measurements that dictated the design

### 1.1 The two systems fail differently (so combine, don't replace)

| | share of instances |
|---|---|
| both ours and LLM find it | 0.598 |
| **ours only** | **0.089** |
| **LLM only** | **0.177** |
| neither | 0.136 |

Union of the two top-5 lists = **0.864**. Our lexical pipeline is not
redundant: it alone finds the answer for 8.9% of instances. This is why
the agent *seeds* from our retrieval instead of starting from a blank
repository, and why the lexical ranking still votes at the end.

### 1.2 The LLM's failures are ranking failures, not search failures

Decomposing the plain LLM's 22.5% miss rate:

| failure type | share of all instances | share of its failures |
|---|---|---|
| right directory found, wrong file chosen | 0.164 | **72.9%** |
| directory never selected | 0.061 | 27.1% |

**73% of its misses are ranking.** The cause is structural: in the
Agentless-style setup the model only ever sees *path names*. It never
reads a line of code. This single number is why the tool set is built
around reading and resolving code rather than around better search.

### 1.3 Stage-1 recall is already high

Directory recall was 0.936. There is little left to win by searching
harder at the top level, which again points the effort at evidence and
ranking.

---

## 2. The architecture

```
Phase 0a QUERY REFORMULATION          (1 model call)        [R5]
         report -> behaviour sentence in code vocabulary
                 + identifiers + error strings
                 |
Phase 0b DETERMINISTIC SEEDING        (no model)
         our 5 lexical signals -> top-20 candidates
         report symbols, filtered to this snapshot          [R3]
         content search for the BEHAVIOUR, run unconditionally
                 |
Phase 1  INVESTIGATION                (model + 8 tools, <=14 turns)
         search_symbol | callers_of | search_text | list_dir
         read_skeleton | read_code  | recall_incidents
                 |
Phase 2  MANDATORY RECORDING          note_candidate(file, reason, conf)
                 |
Phase 3  COMMIT                       submit_ranking(files[10], rationale)
                 |
Phase 4  SAFETY NET                   RRF(agent list, lexical list)   [R7]
```

---

## 3. Why each component, and where it comes from

### Phase 0: seed from retrieval instead of a blank repo

**Why.** §1.1: our pipeline uniquely solves 8.9% of instances. Starting
the agent cold would throw that away.

**Source.** GenLoc [R19] builds exactly this shape —
semantic retrieval seeds, then LLM-driven exploration — and motivates it
against the two failure modes we would otherwise hit: *fixed candidate
sets are too narrow* and *repository-wide dumps are too noisy*. Seeding
plus exploration is the published answer to both. Our seeds are lexical
rather than dense because §1.1 measured our lexical candidates to be
complementary to the LLM's, and because our dense experiment showed dense
retrieval loses to full-text BM25 in the code slot (−0.205 at worst).

**Also:** we hand over the parsed symbols, not just files. A stack frame
names a symbol, not a file; giving the model the symbol list saves it a
turn and makes the first tool call useful.

### The seven tools

| tool | why it exists | source |
|---|---|---|
| `search_symbol` | **The central tool.** A trace frame names a class or function; the faulty file is often not the one named. Resolves a symbol to where it is *defined* and where it is *used* — the step from detection site to cause. Implemented with `git grep` over the whole snapshot (0.4–0.9 s). | [R1] `SearchEntity` over an entity index |
| `callers_of` | One hop of reverse structure: the code that CREATES a bad state usually sits one call above the code that reports it. | [R4] measured 78.3% of buggy methods within an average **0.34 calls** of the trace |
| `search_text` | BM25 over file **content** — exactly what the plain LLM lacks (§1.2). Verified on KAFKA-4131: a behaviour query returns the gold file at rank 2 while the report's own trace points at an innocent file. | [R2] whole-file; see §3.1 for the segmentation we rejected |
| `list_dir` | Cheap navigation, deliberately not the main route. | [R1] ablation: directory structure alone does **not** carry the signal; multi-hop entity structure does |
| `read_skeleton` | What a file declares, before paying for full code. | — |
| `read_code` | Real source lines. Without this the agent is back to guessing from names. | — |
| `recall_incidents` | The project's resolved history behind the paper's four firewall rules. §1.1 says this is the part the LLM cannot replicate. Votes are divided by the size of that past fix and decayed by age. | [R6] `sim/n_b` vote weighting; [R8] K=5 neighbours + recency |
| `note_candidate` | Mandatory evidence recording. | [R10] the user's own agent post-mortem |

Tool count is 8. LocAgent [R1] reaches SOTA with 3; CoSIL [R9] warns that
LLM localizers fail on *breadth/depth balance* and *direction control*.
We keep the set small and each tool single-purpose for that reason.

**Turn-budget protections**, both from documented failure modes rather
than invention: unresolvable paths return `did_you_mean` suggestions
instead of a dead turn, and a repeated identical call returns the cached
result with a note. [R9] and [R3] both identify malformed tool arguments
and hallucinated file keys as a primary engineering failure mode of LLM
localizers; [R3] repairs them with a reflection loop, we prevent them at
the tool boundary.

**Symbol filtering.** Report symbols are kept only if they exist in this
snapshot, ordered most-specific first, with a stoplist for language and
library names. Source: [R2] drops stack frames that are not in the
repository. Effect measured here: MariaDB symbol extraction 13.0 s → 5.9 s,
and the surfaced symbols changed from `NullPointerException` to
`handle_fatal_signal` / `my_print_stacktrace`.

### Phase 0a: query reformulation

**Why.** The raw report is symptom-shaped. Searching code with it finds
the detection site, which is the wrong file in 53% of our instances. One
model call restates the fault as a behaviour sentence in the vocabulary
the *code* would use, plus identifiers and error strings; the behaviour
sentence drives an unconditional content search before the agent loop
starts.

**Source.** [R5] reports up to **+36% MAP@1** from querying with
LLM-extracted structured fields instead of the raw description, and their
summary field is what carries the query *when the report contains no file
or identifier hints* — precisely our hard stratum. [R11] conditions the
query strategy on report type; we pass the observable mention-regime flag
for the same purpose.

**Measured locally:** on KAFKA-4131 a behaviour-style query ("regex topic
partition assignment returns null") ranks the gold file 2nd, while the
first 40 words of the raw report do not surface it at all. This is why
the step is unconditional rather than left to the model's discretion.

### Phase 2: recording is mandatory, not optional

**Why.** This is the single hardest-won lesson available to us, and it is
from the user's own earlier agent (`AGENT-V2-ARCHITECTURE.md` §3). In
that system a worker computed the deciding discriminator exactly right —
and never called `note_finding`, so the synthesiser, which has no tools,
answered "normal". The document's own conclusion:

> *"Anything a worker computes but does not write down is lost… Right now
> recording is voluntary, and the synthesiser cannot tell the difference
> between 'checked and found nothing' and 'never checked'."*

Our design closes that hole three ways: the skill instructs recording of
every seriously-considered file *including rejections*; notes carry
evidence and confidence; and if the model fails to submit a ranking at
all, the recorded notes become the ranking (ordered by confidence) rather
than the run returning nothing.

### Phase 4: deterministic safety net

**Why.** An agent can hallucinate a path, return an empty list, or die
mid-run. Without a floor, those become zeros and the mean collapses.
Fusing the agent's list with the lexical ranking (RRF, k=60) means the
worst case is roughly the baseline, not zero.

**Source.** RRF from Cormack et al. (SIGIR 2009), the same fusion the
paper already uses; k=60 is their reported insensitive default. The
agent gets the higher weight (1.0 vs 0.6) because §0 says it should lead.

### The skill file

The investigation method lives in `skills/fault-localization.md`, not
hard-coded in the prompt: frontmatter plus `## Problem signature`,
`## Investigation blueprint`, `## Resolution template`. This is the
user's own `skillreg.py` format, so skills stay swappable, versioned, and
lintable, and an ablation can remove the skill and re-run to measure what
the method itself is worth.

Its content encodes the paper's own finding: *the file named in the stack
trace is a weak candidate on its own* — which is our 53%-of-reports
statistic turned into an instruction. CoSIL reached the same conclusion
independently ("issue description usually describes the symptoms rather
than the essence of the problem").

---

## 3.1 One published technique we implemented and then rejected

**File segmentation** (score a file by its best-matching segment rather
than as one document) is well established: [R2] measures the useful range
at 400–800 tokens, and [R12] reports boundary-aware chunking beating
fixed windows by 5.5–16%. We implemented it — function-boundary segments
merged to a ~500-token target, with import and licence blocks dropped —
and A/B tested it against whole-file BM25 on 60 instances, 15 per project.

| project | whole-file Hit@8 | segmented Hit@8 | whole MRR | seg MRR |
|---|---|---|---|---|
| Kafka | 0.667 | **0.733** | 0.391 | **0.416** |
| MariaDB | **0.867** | 0.600 | **0.369** | 0.337 |
| MongoDB | 0.733 | 0.733 | **0.497** | 0.406 |
| Qt | **0.467** | 0.333 | **0.239** | 0.147 |

Whole-file wins on three of four projects, badly on MariaDB and Qt. The
explanation is principled rather than a tuning accident: segmentation
exists to correct the length bias of **rVSM/VSM**, which [R2] and [R6]
build on. BM25's `b` parameter already performs length normalisation, so
on our stack the correction is redundant and only the dilution remains —
a diffuse match spread over several segments scores lower than a tight
match in one small unrelated function.

**Kept anyway, but not for ranking:** the best-matching region is still
computed and reported per hit, because naming the function is useful
context for the agent. It no longer influences the score.

This is recorded because it is a result in its own right: a technique
that transfers from VSM-based IRBL to BM25-based IRBL *negatively*.

### Other techniques considered and not adopted

| technique | source | why not |
|---|---|---|
| Fine-tuned dense retriever (contrastive, hard negatives) | [R12] | Needs GPU fine-tuning; our own dense experiment already lost to BM25 by up to −0.205 in the code slot |
| Learned meta-ranker (decision tree / random forest over signals) | [R13] | [R13]'s composer study found trees and random forests *consistently worst*, below a single component score; linear/fixed-weight combination won. We keep weighted RRF |
| SBFL / coverage / failing-test signals | [R14] | Requires test execution. [R4] measured that only 2 of 60 crash bugs had a fault-triggering test at report time |
| Priority scheduling + distance-aware pruning | [R15] | Uses tracebacks from *reproduction tests*, so not a no-execution method; no isolated ablation of the scheduler |
| Full call-graph BFS path reconstruction | [R2] | Java-only machinery (JavaParser, fully-qualified logger names); the paper's own limitations call the C++ port a research task. Three of our four projects are C/C++. `callers_of` is the bounded substitute |
| Duplicate-report text concatenation | [R16] | Our firewall deliberately excludes duplicate clusters; adding them back is the leakage [R17] documents |
| Method-level repository transformation | [R18] | *Decreases* Acc@K by making documents sparser; improves only the effort story |
| Trajectory fine-tuning on agent traces | [R1] | Training, and contamination recurses into the fine-tune data |

---

## 4. Reproducibility, which an agent does not get for free

The user's requirement, and the honest weak point of every agent paper.

| mechanism | what it buys |
|---|---|
| temperature 0 + fixed seed on every call | removes sampling noise as far as the server allows |
| **tools are pure functions of the snapshot** | a transcript replays to byte-identical tool results; the only nondeterminism left is the model |
| full transcript per instance (system prompt, every response, every tool call + result) | the artifact is auditable; following `transcript.py`, the transcript is itself the proof the agent never saw gold |
| gold unreachable from any tool | no tool takes a path that could read the answer; `recall_incidents` applies the four firewall rules |
| restart-safe batch runner | a killed run resumes without duplicating work |
| **multi-seed repeats, variance reported** | we measure run-to-run spread instead of claiming determinism |
| deterministic fallback (Phase 4) | bounds the damage of a bad run |

On multi-seed: LocAgent aggregates reciprocal ranks across sampled
iterations to produce confidence. We will report mean and spread across
seeds rather than a single lucky run, because that is the claim a
reviewer can check.

---

## 5. What we expect, and how it could fail

**Expected gain.** The agent should clear 0.804 by converting ranking
failures (§1.2, 73% of the LLM's misses) into hits, using evidence the
plain LLM never had. The selection-only ceiling is 0.884; the agent can
exceed it, because it can find files that appear in no baseline's list.

**Honest failure modes to watch for:**

1. *The agent ignores the tools* and answers from the seed list. Detected
   by `stop_reason` and tool-call counts per run.
2. *Format failures* — CoSIL names these explicitly. Mitigated by schema
   tool-calls, a nudge turn, and path resolution with reported
   exact/basename/suffix/dropped counts.
3. *The safety net carries the result* rather than the agent. Detected by
   reporting agent-only ranking alongside the fused one. If agent-only is
   worse than fused, we say so.
4. *Cost.* Each run is many LLM calls versus one. Cost per instance will
   be reported next to accuracy, because the paper's industrial argument
   is about cost, not only accuracy.

**Pre-commitment:** the comparison is on the same 200/project evaluation
sample as the dense and noise experiments, scored by the same
`evaluate()`, tested with the same paired bootstrap and BH correction.
If the agent does not beat 0.804, that is the result we report.

**Required validity check — seed-order shuffle.** [R14] found that the
initial ordering handed to an agent moves Top-1 by up to **22%**, even
though the agent eventually visits every candidate. We feed our lexical
top-12 in rank order. So before crediting the agent with any gain we
re-run one arm with the seed order shuffled. If accuracy barely moves,
the agent is reasoning; if it collapses, the agent is echoing our
retrieval and we would be measuring the lexical pipeline with extra
steps. That is failure mode 1 above, and this is the measurement that
detects it.

---

## 6. References

Full summaries of every item live in `industry-c7/papers/summaries/`.

| tag | work | file |
|---|---|---|
| [R1] | Chen et al., *LocAgent: Graph-Guided LLM Agents for Code Localization*, ACL 2025 (arXiv 2503.09089) | `locagent-acl2025.md` |
| [R2] | *Pathidea*: log-aware bug localization, TSE 2022 | `pathidea-tse2022.md` |
| [R3] | Wang et al., *RCAgent*, CIKM 2024 | `rcagent-cikm2024.md` |
| [R4] | *SBEST*: stack-trace-based localization, 2024 | `sbest-2024.md` |
| [R5] | Caumartin & Melo, *Reformulate, Retrieve, Localize*, BoatSE 2026 | `rafi-reformulate-2025.md` |
| [R6] | Zhou, Zhang & Lo, *BugLocator*, ICSE 2012 | `buglocator-icse2012.md` |
| [R7] | Cormack, Clarke & Büttcher, *Reciprocal Rank Fusion*, SIGIR 2009 | `rrf-sigir2009.md` |
| [R8] | Chen et al., *RCACopilot*, EuroSys 2024 | `rcacopilot-eurosys2024.md` |
| [R9] | Jiang et al., *CoSIL*, arXiv 2503.22424 (2025) | `cosil-2025.md` |
| [R10] | *Agent v2 architecture*, this project's earlier agent | `microservice-trace-dataset/Blueprint/agent/AGENT-V2-ARCHITECTURE.md` |
| [R11] | Shao & Yu, *LLmiRQ / LLmiRQ+*, 2024 | `irfl-llm-2024.md` |
| [R12] | *BLAZE*: dynamic chunking + hard-example learning, TSE 2025 | `blaze-tse2025.md` |
| [R13] | *ABLoTS replication*, 2026 | `ablots-replication-2026.md` |
| [R14] | Rafi et al., *multi-agent fault localization*, 2024 (challenge ref [1]) | `rafi-multiagent-fl-2024.md` |
| [R15] | Yu et al., *OrcaLoca*, ICML 2025 | `orcaloca-2025.md` |
| [R16] | *Bench4BL*, ISSTA 2018 | `bench4bl-issta2018.md` |
| [R17] | *Leakage in link prediction*, 2022 | `leakage-linkpred-2022.md` |
| [R18] | *FinerBench4BL*, 2023 | `finerbench4bl-2023.md` |
| [R19] | *GenLoc: Towards Explorative IRBL*, arXiv 2508.00253 (2026) | `genloc-2025.md` |

Phase 0b seeding follows [R19]; the two failure modes it names (fixed
candidate sets too narrow, repository-wide dumps too noisy) are the ones
seeding-plus-exploration is designed to avoid.
