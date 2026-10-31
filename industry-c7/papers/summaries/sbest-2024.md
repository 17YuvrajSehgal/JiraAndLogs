# SBEST: Spectrum-Based Fault Localization Without Fault-Triggering Tests

**Md Nakhla Rafi, Lorena Barreto Simedo Pacheco, An Ran Chen, Jinqiu Yang, Tse-Hsun (Peter) Chen (Concordia/Alberta — SPEAR again). arXiv 2405.00565v2 (2025).**
PDF: `pdfs/sbest-2024.pdf`

## What it is

SBFL without failing tests: use the CRASH STACK TRACE as a proxy for the
fault-triggering test's coverage, integrate with existing passing-test
coverage, rank methods. Grounded in an empirical study of 60 crash-report
bugs in Defects4J.

## The statistics (quote-grade, with their exact numbers)

- **Only 3.33% of crash-report bugs had a fault-triggering test available
  at bug-report creation time** — the single sharpest number for the
  challenge's premise (and ours) that execution evidence is absent at
  report time, measured on the very benchmark test-based FL lives on.
- 98.3% of fixes directly address the exception in the trace; **78.3% of
  buggy methods are reachable within an average of 0.34 method calls from
  the trace**.
- SBEST: +32.22% MAP, +17.43% MRR over baselines in the no-failing-test
  scenario.

## The nuance that protects us from overclaiming

The 78.3%-near-the-trace figure might look like it contradicts our hard
stratum — it does not, and the distinction is worth a careful sentence:
their population is CRASH reports (exception + trace present, Defects4J,
Java). Ours spans all log-bearing fixed bugs, where 37–90% of reports per
project carry NO trace at all, and "hard" means no GOLD FILE is NAMED —
a file can be unnamed yet near the trace's neighborhood (which is exactly
what Pathidea's path analysis and our S3-over-candidates exploit). So:
traces, when present, are highly informative about the NEIGHBORHOOD
(SBEST, Pathidea, CraTer); our claim is only that the named files
themselves are frequently not the fix site, and that many reports have no
trace — both consistent with their data.

## Weaknesses / notes

- n=60 crash bugs, Defects4J, Java, method level; the 3.33% figure's
  denominator is small (2/60) — cite as "only 2 of 60".
- Requires passing-test coverage infrastructure — still execution-bound
  on the passing side; our setting has neither.
- Same lab as LLM4FL/Pathidea (SPEAR) — the challenge's lineage again.

## Use in our paper

- §1/related work: the 3.33% statistic as the measured form of
  "execution evidence is unavailable at report time."
- §6 symptom-vs-cause paragraph: pair the 78.3%-neighborhood figure with
  our hard-stratum definition to preempt a reviewer wielding SBEST
  against us.
