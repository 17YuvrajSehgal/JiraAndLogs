# An Empirical Study on Data Leakage and Generalizability of Link Prediction Models for Issues and Commits (LinkFormer)

**Maliheh Izadi, Pooya Rostami Mazrae, Tom Mens, Arie van Deursen (TU Delft / UMons). EMSE; arXiv 2211.00381v2 (2023).**
PDF: `pdfs/leakage-linkpred-2022.pdf`

## What it is

Two things: (1) LinkFormer, a RoBERTa-based issue↔commit link recovery
model using text + metadata; (2) — the part we care about — a controlled
comparison of **random vs temporal splits** for link-prediction models on
20 projects, plus transfer-learning settings (intermediate fine-tuning,
cross-project).

## The split finding (our citation)

All four systems (DeepLink, Hybrid-Linker, T-BERT, LinkFormer) perform
WORSE under a temporal 80/10/10 split than under a random split, with
**F1 declines of 7% to 25%** depending on the model (T-BERT suffers most;
LinkFormer least, average F1 0.90 ± 0.10 temporal). Their framing:
"splitting a time-aware dataset randomly can result in data leakage
between training and testing sets, potentially leading to the
overestimation of a model's accuracy and its failure to generalize to
real-world settings."

Meaning for us: even for the LINKAGE task itself (the thing our benchmark
construction relies on), random splits inflate results. Together with
Broccoli (snapshot side) and the ABLoTS replication (history-cutoff side),
this completes the protocol-citation set for §4: time must govern the
split, the snapshot, and the memory.

## Secondary observations

- Project-level variance is large; model reliability (std across projects)
  is itself a differentiator — supports our per-project reporting.
- Rath et al.'s five SEOSS projects "occasionally contain tags" that
  inflate learned-model performance — data idiosyncrasies leak into
  learned linkers; explicit-key linkage (ours/Bench4BL's) avoids this
  class of problem at the cost of recall.
- Their task could someday IMPROVE our benchmark: learned link recovery
  could recover issues whose fixes lack explicit keys (the no_fix_commit
  funnel bucket, 340–1,804 per project) — at the price of gold noise;
  worth one future-work sentence.

## Weaknesses / notes

- Link recovery, not localization — cite only for the split methodology.
- The temporal decline conflates leakage with genuine concept drift; the
  paper does not separate the two (neither do we need it to).
- Baseline replication hiccups (T-BERT NA on Cassandra).

## Use in our paper

- §4.1 time-split paragraph: third leg of the protocol citations.
- §2: optional future-work sentence on recovering unlinked fixes.
