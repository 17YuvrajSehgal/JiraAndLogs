# RCACopilot: Automatic Root Cause Analysis via Large Language Models for Cloud Incidents

**Yinfang Chen, Huaibing Xie, Minghua Ma, et al. (Microsoft / UIUC / PKU / HUST / NUS). EuroSys 2024, pp. 674–688. DOI 10.1145/3627703.3629553.** (arXiv 2305.15778v4)
PDF: `pdfs/rcacopilot-eurosys2024.pdf`

## What it is

An on-call system at Microsoft with two stages: (1) **diagnostic
collection** — per alert type, OCE-authored "incident handlers" (decision
trees of reusable scope-switch / query / mitigation actions) gather
multi-source evidence (logs, exception stacks, metrics); (2) **root-cause
prediction** — an LLM (GPT-4) classifies the incident's root-cause
CATEGORY and writes an explanation, using few-shot chain-of-thought with
the most similar PAST incidents as demonstrations. The collection stage
has run for 4+ years across 30+ Microsoft teams; prediction was deployed
on one email service (Transport, 150B messages/day).

## The history-retrieval mechanics (the part that touches our S4)

- Embedding: **FastText trained on their own incident history** — notably,
  GPT embeddings performed far worse as a variant (Micro-F1 0.257 vs
  0.766); domain text beats generic embeddings at this scale.
- Similarity: `1/(1+||a−b||₂) · e^(−α·|T(a)−T(b)|)` with α = 0.3 — a
  **time-DECAY**, not a firewall: older incidents are down-weighted but
  **future incidents are not excluded** (train/test is a 75/25 split; the
  paper never states the split is chronological). Top K = 5 neighbors from
  different categories become CoT demonstrations.
- Their Insight 2 is our memory premise, with data: **93.8% of recurring
  incidents reappear within 20 days** — recurrence is short-horizon. Also
  Insight 3: 24.96% of incidents (163/653) have a brand-new root-cause
  category — the memory-miss rate in a mature service.

## Numbers and what they mean

- Table 2 (653 incidents, 75/25, 3 rounds): RCACopilot GPT-4 Micro-F1
  **0.766** / Macro-F1 0.533; GPT-3.5 nearly equal (0.761/0.505 — the
  prompt design, not the model, carries it). Baselines collapse: FastText
  0.076, XGBoost 0.022, fine-tuned GPT-3.5 0.103, GPT-4 without
  demonstrations 0.026. Meaning: with 653 long-tail-distributed incidents,
  classification lives or dies on retrieved-neighbor demonstrations —
  standalone classifiers and even fine-tuning have too little data. The
  gap (0.026 → 0.766) is the value of retrieved history in their setting.
- Table 3 (context ablation): summarized diagnostic info alone is best
  (0.766); ADDING alert info or action outputs HURTS (down to 0.44–0.53).
  "An excess of information can negatively impact the LLM" — useful
  precedent for why our provenance-style compact evidence beats dumping
  everything into a prompt.
- Sensitivity: K = 5, α = 0.3 optimal; more demonstrations do not help.
- Inference cost ~4.2 s/incident; handler execution 15–841 s per incident
  depending on team.

## Weaknesses / gloss-overs

- **No temporal firewall**: time-decay similarity plus a (probably random)
  75/25 split means neighbors can postdate the query. Nothing like our
  rule 4; duplicates are not excluded either. Under our protocol their
  headline would likely drop — same story the reviewer wants us to tell
  about SimiScore.
- Output granularity is a **category label** for one service with
  OCE-curated labels; no code, no files, no modules. The 100%-coverage
  claim holds only when a handler exists for the alert type.
- Single service, 653 incidents, private data — nothing reproducible; the
  three-round "trustworthiness" check is variance of the LLM, not of the
  data.
- Generator/judge-style circularity avoided only because labels are human;
  but labels were made by the same org's OCEs who built the handlers.

## Use in our paper

- Related work §5 (AIOps RCA): the flagship "retrieve similar past
  incidents" precedent at category level. One positioning sentence:
  RCACopilot retrieves history to name the root-cause *category* with
  time-decay weighting; we retrieve history to rank *source files* under a
  strict past-only firewall, on public data.
- §3 memory motivation: their 93.8%-within-20-days recurrence statistic is
  independent industrial evidence that incident memory is fresh and dense.
- §6: their Table 3 (more context hurts) supports provenance-style compact
  evidence over raw dumps.

## Thesis connection

The handler/action architecture (reusable evidence-gathering workflows per
alert type) is structurally the "AI skills + investigation blueprints"
layer of the user's parent RCA framework; RCACopilot is the closest
published industrial analogue of that design and should be cited there.
