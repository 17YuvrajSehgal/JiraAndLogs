# A Multi-Agent Approach to Fault Localization via Graph-Based Retrieval and Reflexion (LLM4FL)

**Md Nakhla Rafi, Dong Jae Kim, Tse-Hsun (Peter) Chen, Shaowei Wang (SPEAR lab, Concordia / DePaul / Manitoba). arXiv 2409.13642v2 (2025).**
PDF: `pdfs/rafi-multiagent-fl-2024.pdf`
**This is the challenge PDF's own reference [1]** — its authors are close
to the challenge's provenance; know it cold.

## What it is

LLM4FL: three-agent, METHOD-level fault localization on Defects4J v2
(675 faults, 14 Java projects):
1. **Context Extraction Agent** — splits the methods covered by FAILING
   TESTS into token-sized groups (ordered by an SBFL formula / DepGraph),
   reasons over test code + failure messages, prioritizes suspicious
   methods per group.
2. **Debugger Agent** — Graph-RAG navigation: iteratively follows the
   inter-procedural CALL GRAPH (get_CallGraph, method-body retrieval
   tools) from prioritized methods to rank suspects.
3. **Reviewer Agent** — Reflexion-style "verbal reinforcement learning":
   self-critiques and re-ranks until stable.

## Numbers and what they mean (Table 3, 675 faults, method level)

| technique | Top-1 | Top-3 | Top-5 | Top-10 |
|---|---|---|---|---|
| Ochiai (SBFL) | 121 | 260 | 340 | 413 |
| DeepFL | 257 | 353 | 427 | 468 |
| Grace | 298 | 416 | 486 | 541 |
| DepGraph | **359** | **481** | **541** | **597** |
| AutoFL | 275 | 393 | 423 | 457 |
| SoapFL/AgentFL | 311 | 414 | 455 | 478 |
| LLM4FL | 326 | 425 | 474 | 496 |

So LLM4FL beats the LLM-based rivals (+18.55% Top-1 over AutoFL, +4.82%
over SoapFL) at $0.05/fault, but the SUPERVISED graph-based DepGraph still
beats it across every K (they acknowledge this; DepGraph needs training +
change history). Top-1 326/675 = 48% at method level WITH failing tests
and full coverage. Their ordering finding is interesting: the initial
method ordering fed to the agents changes Top-1 by up to 22% even though
the LLM eventually visits all methods — LLMs are strongly anchored by
input order (relevant to any LLM re-ranker we might add: feed it OUR
fused order).

## The structural fact that matters for our paper

Every input to LLM4FL's pipeline presupposes EXECUTION: fault-triggering
tests (1.4K of them), Gzoltar coverage, SBFL ordering. The challenge text
itself says this evidence "is unavailable when an issue is first
reported". So the challenge's own reference [1] is a method for a
different evidence regime — it belongs in our related work's
"requires execution" paragraph, not in our baseline table. The fair
LLM-family baselines for report-time localization are Agentless-style
(issue + code only) — a distinction worth one explicit sentence since the
challenge cites this paper.

## Weaknesses / gloss-overs

- Defects4J only: single-language, old faults, known LLM training-data
  contamination (unaddressed beyond a brief mention).
- No time dimension at all; no use of project history or past incidents.
- Method-level Top-N counts without statistical tests; GPT variance
  handled by... (not clearly reported in what we read).
- Agent cost is low ($0.05) but depends on coverage collection
  infrastructure that is itself expensive.

## Use in our paper

- Related work (test-based LLM FL): cite with AutoFL/SoapFL as the
  "requires failing tests/coverage" family, explicitly noting it is the
  challenge's ref [1] and why the input regime differs.
- If we add an LLM re-ranker: their order-sensitivity finding justifies
  seeding it with our fused ranking rather than an unordered pool.
- SPEAR lab connection: same group as Pathidea — the challenge's
  intellectual lineage favors log-aware, retrieval-grounded methods.
