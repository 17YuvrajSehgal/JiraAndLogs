# GenLoc: Towards Explorative IRBL — Semantic Retrieval + LLM-Driven Iterative Code Exploration

**Moumita Asad, Rafed Muhammad Yasir, Sam Malek (UC Irvine). arXiv 2508.00253v3 (2026).**
PDF: `pdfs/genloc-2025.pdf`

## What it is

File-level IRBL that seeds an LLM with SEMANTIC (embedding) retrieval
candidates, then lets it iterate with code-exploration functions (ReAct-
style) to refine the ranking. Pitched as fixing three LLM-context failure
modes: fixed candidate sets (too narrow), repository-wide dumps (too
noisy), and reliance on explicit bug-report cues. Evaluated on recent
large Java datasets + SWE-bench Lite; claims superiority over traditional
IRBL, deep-learning IRBL, and recent LLM methods, including localizing
bugs others miss.

## Positioning notes for us

- Design-wise it is Agentless's retrieval route + LocAgent's exploration,
  packaged as "explorative IRBL" — in related work it groups with
  GenLoc/CoSIL/OrcaLoca as the 2025–26 LLM-IRBL wave (one group cite).
- Explicitly motivates against "reliance on explicit bug report cues" —
  another independent acknowledgment that cue-free (our hard-stratum)
  reports are the real challenge.
- Notes that historical bug-fix data "is not always available,
  particularly in new projects" — the cold-start caveat that our
  graceful-degradation sentence (§6 deployment) addresses: without
  memory, we fall back to baseline-strength log-to-code signals.

## Weaknesses / notes (from the parts read)

- Preprint with placeholder venue; results sections not transcribed here —
  pull exact numbers only if we end up citing them (we likely cite the
  family, not the figures).
- Java + SWE-bench Lite; usual contamination caveats apply.

## Use in our paper

- Related work LLM-IRBL group citation; optional cold-start sentence
  support in §6.
