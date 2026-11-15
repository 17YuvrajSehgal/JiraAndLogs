# Bench4BL: Reproducibility Study on the Performance of IR-Based Bug Localization

**Lee, Kim, Bissyandé, Jung, Le Traon. ISSTA 2018, pp. 61–72. DOI 10.1145/3213846.3213856.**
PDF: `pdfs/bench4bl-issta2018.pdf` · Replication: github.com/exatoa/Bench4BL (also mirrored at TruX-DTF/Bench4BL)

## What it is

The reproducibility study for classic IR-based bug localization (IRBL). It
re-runs the six standard tools — BugLocator (2012), BLUiR (2013), BRTracer
(2014), AmaLgam (2014), BLIA (2015), Locus (2016) — on 46 NEW Java projects
(61,431 files, 9,459 fixed bug reports from Apache/Spring/JBoss Jira) plus
the 5 OLD literature subjects (AspectJ, JDT, PDE, SWT, ZXing; 558 reports).
All tools run with their authors' default parameters.

## Method details that matter for re-implementation

- **Ground truth**: Jira issues typed Bug + status FIXED with explicit file
  changes. Links are explicit only (issue key in commit message, or commit id
  in the issue); they deliberately reject learned link-recovery tools
  (ReLink, MLink, RCLinker) because those have precision 0.3–0.86 — too many
  false positives for ground truth. Multiple commit IDs on one report → they
  use the LATEST commit. (We instead keep 1–3 commits and union; their
  choice loses multi-commit fix files.)
- **Tool configurations** (what "default" means — needed to replicate):
  BugLocator = rVSM + SimiScore with α = 0.3 and logistic length function.
  BLUiR = TFIDF with k1 = 1.0, b = 0.3, Krovetz stemmer, structured fields,
  + similar reports. BRTracer = rVSM + similar reports + segmentation +
  trace boost. AmaLgam = BugLocator setup + history length k = 15, composer
  b = 0.3. BLIA: α = β = 0.2, k = 30. Locus: VSM, λ = 0.5.
- **Version matching**: "single" = rank files of the LATEST version for all
  reports (what the original papers did); "multiple" = rank files of the
  version the report names (its affected-version field; oldest if several;
  reports without a version field are DROPPED — note this selection bias).
- Test-file handling is a simple path/name filter (`/test/`, `*Test.java`),
  same spirit as ours.

## The numbers and what they mean

**Baseline (single version, test files included, old+new pooled):** mean
MAP 0.35–0.39, mean MRR 0.47–0.52 across the six tools. Aggregated-report
table (their Table 2, new subjects): BugLocator 0.305/0.422, BRTracer
0.333/0.469, BLUiR 0.288/0.387, AmaLgam 0.291/0.390, BLIA 0.301/0.416,
Locus 0.329/0.443 (MAP/MRR). Meaning: a user can expect roughly "first
relevant file around rank 2–2.3" from any of them, and **no tool
significantly dominates** — the paper's headline. For our paper this means
one or two classic baselines (BugLocator + BRTracer) represent the whole
family; adding all six buys nothing.

**RQ1 (old vs new subjects):** tools are NOT overfitted to the old
subjects; most score HIGHER on new ones (e.g., BugLocator MAP 0.269 → 0.305).
Their conjecture: newer projects use more user-facing vocabulary in
identifiers, so report and code tokens overlap more.

**RQ2 (version matching — the finding closest to our design):** evaluating
against the right snapshot instead of the latest version raises every tool
significantly: MAP +0.066 to +0.093, MRR +0.084 to +0.108 (BugLocator MAP
0.305 → 0.371; Locus 0.329 → 0.422). Meaning: ~0.07–0.09 MAP of reported
IRBL "improvement" can be wiped out or created purely by snapshot choice.
Our parent-of-fix snapshot is the strict version of their recommendation,
and this is the citation for it.

**RQ3 (test files):** excluding test files HURTS MRR for all six tools
(−0.040 to −0.051) and changes MAP by ±0.02 either way. Their reading: test
files share report vocabulary and are legitimate rank targets in their gold
(their gold includes test files). **Contrast with us**: we exclude test
files from gold AND from the universe, because Challenge #7 asks for
defective product code, not co-changed tests. Cite this difference
explicitly, or a reviewer who knows Bench4BL will ask.

**RQ4 (duplicates):** master+duplicate text concatenation raises MRR for
all tools (+0.013 to +0.031, n.s.); duplicates alone are WORSE than
masters (significantly for BLUiR/AmaLgam). Meaning: duplicate reports carry
complementary vocabulary. **This is the evidence that our firewall's
duplicate-cluster exclusion is removing real signal, i.e., that leaving
duplicates in the memory would inflate our S4.** Best single citation for
firewall rule 2.

**Execution time (their Table 9):** BugLocator/BRTracer median ~10 min per
subject (whole-project batch), Locus mean 373 min due to an implementation
issue. Useful as a cost anchor for our sub-second-per-issue claim — but
note their time covers indexing all versions of a subject.

## Weaknesses / things glossed over

- **Not time-aware.** Nothing stops SimiScore from using future reports;
  version matching fixes the code side, not the history side. The word
  "leakage" never appears. This is exactly the hole our firewall closes —
  and the hook for the reviewer-suggested experiment (SimiScore with vs
  without firewall).
- Multiple-version matching silently drops all reports lacking an
  affected-version field; the RQ2 population is therefore a biased subset,
  and they do not quantify how biased.
- Duplicate handling assumes a duplicate shares the master's fixed files
  (duplicates usually have no linked fix), an unvalidated assumption.
- Java only; all conclusions about tooling transfer to C/C++ are ours to
  establish.
- Mann-Whitney U on per-report values without multiple-test correction and
  without effect sizes.

## Use in our paper

- §Related work: the IRBL reproducibility anchor; "no significant
  differences among six tools" justifies our baseline choice (BugLocator +
  BRTracer).
- §Setup: cite for version matching (RQ2) and for including the Bench4BL
  default parameters when we re-implement (α = 0.3 etc.).
- §Approach/firewall: RQ4 duplicates finding = why duplicate-cluster
  exclusion is load-bearing.
- Their gold-building choices (latest commit only, explicit links only) are
  the baseline recipe ours refines (1–3 commits with union, revert/merge
  filters, per-filter yield datasheet).

## Thesis connection

Methodologically this is the same genre as our WoL measurement work:
re-running published systems under harmonized conditions and showing the
evaluation protocol (snapshot choice, population selection) moves results
as much as the methods do. Useful as a model citation when arguing
protocol-sensitivity in the performance-analysis parts of the thesis.
