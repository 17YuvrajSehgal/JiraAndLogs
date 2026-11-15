# An Extensive Replication Study of the ABLoTS Approach for Bug Localization

**Feifei Niu, Enshuo Zhang, Christoph Mayr-Dorn, Wesley Assunção, Liguo Huang, Jidong Ge, Bin Luo, Alexander Egyed. arXiv 2605.11790 (2026); extension of their earlier replication.**
PDF: `pdfs/ablots-replication-2026.pdf` · Replication: github.com/feifeiniu-se/Replication2

## Why this paper is load-bearing for us

It documents, with the original authors' confirmation, **exactly the
leakage our firewall exists to prevent** — in a celebrated IRBL system. It
is the single best citation for firewall rule 4 and for the planned
"SimiScore with vs. without firewall" experiment.

## What it replicates

ABLoTS (Rath et al., MSR 2018) = AmaLgam's frame with TraceScore replacing
SimiScore: suspiciousness from (a) BugCache version history, (b) similar
reports via issue-trace links (TraceScore), (c) BLUiR structure, combined
by a decision tree. Original paper reported it "greatly outperforms
AmaLgam". Datasets: original 11 Java projects (8,494 reports), extended 16
Java (25,893), extended 12 Python (1,289) — note the extended Java set
includes KAFKA, CASSANDRA, HBASE, HIVE, FLINK, SPARK, ZooKeeper (overlaps
our ecosystem).

## The leakage finding (the detail to cite precisely)

BugCache (the history component, reused verbatim from AmaLgam) computed
"bug-fixing commits within k=15 days prior to the bug's **FIXED date**" —
which includes the commits that fixed THIS very bug. Their worked example
(HORNETQ-1301): the two commits fixing the bug land between creation and
fixed date, so BugCache recommends exactly the fix's files, and the
decision-tree composer learns to trust it (feature importance 0.377 vs
0.037 BLUiR, 0.018 TraceScore). **AmaLgam's authors confirmed the wrong
date; ABLoTS's authors confirmed they reused the implementation.** With
the cut-off corrected to the CREATION date, ABLoTS's reported performance
is unreproducible — replication MAP ≈ 0.055, Top-10 ≈ 0.199 on the
original dataset (Table 7), versus the fixed-weight AmaLgam composer at
MAP 0.298 / Top-5 0.563 / Top-10 0.640 (Table 8). A second, unexplained
discrepancy: the original evaluation scored only ~60–70 candidate files
per bug instead of the full file universe, with no documented filter.

Meaning for us: (1) a history-based signal evaluated without a creation-
time cutoff can fabricate most of its reported advantage; (2) this
happened silently through CODE REUSE across papers; (3) our rule-4 cutoff
(memory resolved before query creation) is precisely the corrected
protocol, applied to the similar-reports signal rather than BugCache.

## Other results worth keeping

- TraceScore itself (relations between bug reports and feature requests)
  IS replicable and generalizable under a relaxed cutoff — the similar-
  reports idea survives; the composer and history leaked.
- Composer study (10 combiners over 3 score components): Logistic
  Regression, CombSUM, and FIXED WEIGHTS are consistently best; decision
  trees and random forests are consistently WORST (worse than the single
  TraceScore). "Contributions of different component scores are linear."
  Supports our choice of simple weighted fusion over learned combiners —
  and warns against a learned meta-ranker as a quick upgrade.
- Fixed-weight composer on their extended Java set: MAP 0.344 / Top-5
  0.621 / Top-10 0.714 average; on KAFKA specifically MAP 0.474 / Top-1
  0.516 / Top-5 0.742 — a rough external anchor for what classic
  multi-component IRBL achieves on Kafka (population differs from ours:
  all linked bugs, not log-bearing only).
- Python projects score higher than Java ones across all composers; no
  significant correlation between project size and accuracy (Pearson,
  p>0.05) — useful when discussing our per-project differences.

## Weaknesses / notes

- The replication's own population: reports with explicit version info and
  trace links; selection effects not deeply analyzed.
- K-S tests and Pearson used descriptively; no multiple-test control.
- Python dataset is small (1,289 across 12 projects).

## Use in our paper

- §3 firewall paragraph and §4 protocol: cite for "using the fixed date
  instead of the creation date leaks data", with AmaLgam-authors-confirmed
  provenance.
- §Related work (history/similar reports): position TraceScore as the
  issue-link sibling of our memory signal; its survival under honest
  cutoffs is encouraging for S4.
- Planned firewall-leakage experiment: this paper shows the leakage effect
  for BugCache; ours would show it for the similar-report signal — a
  complementary, novel measurement.
- Fusion design: their composer finding justifies weighted-RRF over
  tree-based combiners in one sentence.
