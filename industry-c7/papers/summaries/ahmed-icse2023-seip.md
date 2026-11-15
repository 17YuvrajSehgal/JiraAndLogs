# Recommending Root-Cause and Mitigation Steps for Cloud Incidents using Large Language Models

**Toufique Ahmed (UC Davis), Supriyo Ghosh, Chetan Bansal, Thomas Zimmermann, Xuchao Zhang, Saravan Rajmohan (Microsoft). ICSE 2023 SEIP (arXiv 2301.03797v2).**
PDF: `pdfs/ahmed-icse2023-seip.pdf`

## What it is

The first large-scale LLM-for-incident-RCA study: **44,340 Microsoft
incidents from 1,759 services**, fine-tuning six GPT-3.x-era models
(RoBERTa, CodeBERT, Curie, Codex-cushman, Davinci, Code-davinci-002) to
generate free-text ROOT CAUSES and MITIGATION STEPS from only the
incident's title and summary at creation time. Evaluated with lexical
(BLEU-4, ROUGE-L, METEOR) and semantic metrics plus a human study with
the ORIGINAL incident owners.

## Findings that matter

- Fine-tuning is essential (zero-shot GPT-3.x fails on private incident
  data); Davinci/Code-davinci-002 best; NL-vs-code model families show no
  clear winner.
- Giving the model the true root cause improves mitigation generation
  (RQ5) — evidence for staged pipelines.
- **The methodological finding we cite:** Pearson correlation between
  lexical metrics and the incident owners' correctness/readability scores
  ranges **−0.42 to +0.62** — "automatic metrics may not be coherent with
  human perception for resolving cloud incidents." This is the published
  justification for not judging RCA output by text similarity — exactly
  the trap our own extrinsic WoL eval fell into (circularity aside), and
  a reason our C7 evaluation uses externally-verifiable gold (fix files)
  instead of text-match scoring.
- Incident owners worried about RARE incidents — the long tail is where
  generation-from-title/summary is weakest; RCACopilot (successor work)
  addressed this with retrieved neighbors; our memory signal is the
  retrieval-grounded answer at code level.

## Weaknesses / notes

- Inputs are title+summary only — no logs, no code; output is prose at
  incident level. Granularity gap to us is maximal.
- Private data; human study small (acknowledged "difficult to achieve
  statistical significance").
- This is RCACopilot's cited predecessor ("Ahmed et al." in that paper's
  motivation): fine-tuning costs and staleness motivated RCACopilot's
  retrieval design — a nice one-sentence arc for related work: fine-tune
  (Ahmed) → retrieve neighbors (RCACopilot) → retrieve + vote on CODE
  (ours).

## Use in our paper

- Related work §5 (AIOps): one sentence in the arc above.
- §4/§6: the −0.42..+0.62 metric-human correlation as justification for
  fix-commit gold over text-similarity judging.
