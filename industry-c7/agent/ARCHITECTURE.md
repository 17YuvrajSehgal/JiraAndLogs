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
Phase 0  DETERMINISTIC SEEDING        (no model)
         our 5 lexical signals -> top-20 candidates + provenance
         report -> symbols (stack frames, CamelCase, snake_case, files)
                 |
Phase 1  INVESTIGATION                (model + 7 tools, <=14 turns)
         search_symbol | search_text | list_dir
         read_skeleton | read_code | recall_incidents
                 |
Phase 2  MANDATORY RECORDING          note_candidate(file, reason, conf)
                 |
Phase 3  COMMIT                       submit_ranking(files[10], rationale)
                 |
Phase 4  SAFETY NET                   RRF(agent list, lexical list)
```

---

## 3. Why each component, and where it comes from

### Phase 0: seed from retrieval instead of a blank repo

**Why.** §1.1: our pipeline uniquely solves 8.9% of instances. Starting
the agent cold would throw that away.

**Source.** GenLoc (arXiv 2508.00253) builds exactly this shape —
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

| tool | why it exists |
|---|---|
| `search_symbol` | **The central tool.** A trace frame names a class or function; the faulty file is often not the one named. This resolves a symbol to where it is *defined* and where it is *mentioned*, which is the step from detection site to cause. Mirrors LocAgent's `SearchEntity` over its entity index. |
| `search_text` | BM25 over file **content**. This is precisely what the plain LLM lacks (§1.2). Verified on KAFKA-4131: searching the *behaviour* ("regex topic partition assignment null") returns the gold file at rank 2, while the report's own stack trace points at an innocent file. |
| `list_dir` | Cheap navigation. Deliberately not the main route: LocAgent's ablation found directory structure alone does **not** carry the signal; multi-hop entity structure does. |
| `read_skeleton` | What a file declares, cheaply, before paying for full code. |
| `read_code` | Real source lines around a symbol. Without this the agent is back to guessing from names. |
| `recall_incidents` | The project's resolved history, behind the paper's four firewall rules. This is our contribution carried into the agent, and §1.1 says it is the part the LLM cannot replicate. |
| `note_candidate` | Mandatory evidence recording. See below. |

Tool count is 7. LocAgent reaches SOTA with 3; CoSIL warns that LLM
localizers fail on *breadth/depth balance* and *direction control*. We
keep the set small and each tool single-purpose for that reason.

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
