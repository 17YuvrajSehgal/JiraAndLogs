# Enhancing IR-based Fault Localization using Large Language Models (LLmiRQ / LLmiRQ+)

**Shuai Shao, Tingting Yu (UConn). arXiv 2412.03754 (2024).**
PDF: `pdfs/irfl-llm-2024.pdf` (bonus find during the BRTracer hunt)

## What it is

LLM-assisted QUERY CONSTRUCTION for classical IRFL, plus learning-to-rank:
GPT-4 CATEGORIZES each bug report by its dominant evidence (programming
entities / stack traces / natural-language text) and applies a tailored
query strategy per category; LLmiRQ+ adds conversational, user-feedback
query reformulation; a learning-to-rank layer combines features including
class-name match score and call-graph score. Evaluated on the Bench4BL
population (46 projects, 6,340 reports): **MRR 0.6770, MAP 0.5118**,
beating seven IRFL baselines (BugLocator…Locus family).

## Why it matters to us

- **Independent instantiation of our regime idea**: they classify reports
  by evidence type (entities vs traces vs prose) and CHANGE THE QUERY
  STRATEGY per class — we classify by observable mention-presence and
  change FUSION WEIGHTS per class. Same insight, different lever. Cite
  next to BLIZZARD when claiming regime-conditioned fusion is new "to our
  knowledge" — conditioning retrieval strategy exists; conditioning
  fusion weights appears not to.
- Their MRR 0.677 on the Bench4BL population (vs classic tools' ~0.42–
  0.52) shows how much headroom query quality alone carries — consistent
  with Caumartin & Melo's +36% MAP@1 and with our S1-extraction design.
- Learning-to-rank layer echoes Ye et al. (their citation too); the
  ABLoTS-replication composer lesson (linear beats trees) applies.

## Weaknesses / notes

- GPT-4 in the loop for every query: cost, privacy, reproducibility
  (non-versioned model) — the industrial constraints ABB/RCAgent flag.
- LLmiRQ+ requires USER feedback mid-loop — not comparable to automated
  baselines without caveats.
- Bench4BL population inherits its linkage noise and non-time-aware
  protocol; no history/memory signal.
- Preprint; venue placeholder.

## Use in our paper

- Related work (query reformulation group, with BLIZZARD and Caumartin &
  Melo): one clause + the conditioning-precedent nuance for our novelty
  sentence.
