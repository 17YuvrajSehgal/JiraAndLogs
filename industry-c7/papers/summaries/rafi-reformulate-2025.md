# Reformulate, Retrieve, Localize: Agents for Repository-Level Bug Localization

**Geneviève Caumartin (Concordia), Glaucia Melo (Toronto Metropolitan U). BoatSE workshop 2026 (arXiv 2512.07022).**
PDF: `pdfs/rafi-reformulate-2025.pdf`
**Correction to the survey doc:** the survey attributed this to "the same
group as Rafi et al." — the authors are Caumartin & Melo (Rafi's LLM4FL is
only CITED here). Fix before citing.

## What it is

A lightweight study of UPSTREAM QUERY REFORMULATION for file-level bug
localization: a non-fine-tuned open LLM (Qwen3-30B, temp 0) extracts a
structured JSON from each bug report — summary/explanation, file
paths/names, identifiers, code snippets, stack traces, error messages —
which becomes the BM25 (Pyserini) query; optionally a small agent
(Qwen2.5-32B / Qwen3-30B) uses BM25-as-tool plus file preview to rank.
Evaluated on Long Code Arena and SWE-bench Lite.

## Findings

- LLM-extracted structured queries beat raw-description BM25 by **up to
  +36% MAP@1**; the agent on top adds up to +22% over SWE-agent and +35%
  better first-file ranking vs their BM25 baseline.
- The reformulation targets exactly the "localization hints" literature
  (identifiers, traces, snippets) — when hints are absent, the summary
  field carries the query (their fallback mirrors our S1-explicit vs
  stem-fallback split).

## Relevance to us

- This is the published version of a cheap upgrade we could make: our
  query tokenization is raw text; an extraction step that ISOLATES
  identifiers/log templates from prose before BM25 is exactly their RQ1
  — no fine-tuning, local model, CPU-adjacent cost. If we ever add one
  LLM call per instance, reformulation is likely better value than
  re-ranking (their +36% MAP@1 at one small-model call).
- Conversely, it validates our design: hint extraction (S1) + lexical
  retrieval (S2/S3) is their whole recipe minus memory; the regex version
  we use is the zero-cost approximation.
- Related-work nugget: BLIZZARD (Rahman et al.) classifies report quality
  and reformulates accordingly — the query-quality-conditioned lineage
  that our regime conditioning extends to FUSION WEIGHTS (the survey's
  "no prior IRBL switches fusion on an observable property" point).

## Weaknesses / notes

- Workshop-scale: two datasets, no significance testing visible in what
  we read; agent comparisons use different models across rows.
- Python-centric datasets; no history signal; no time-awareness.

## Use in our paper

- Related work (query reformulation, one clause) + §6 upgrade path: LLM
  reformulation as the cheapest LLM insertion point, citing their +36%
  MAP@1.
