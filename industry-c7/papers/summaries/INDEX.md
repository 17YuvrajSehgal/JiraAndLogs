# Paper summaries index

One file per paper, written after a full read. Each summary: citation,
method mechanics (enough to re-implement), numbers explained, weaknesses,
use-in-our-paper, thesis connections.

## Done (15)

| Summary | Role for the C7 paper |
|---|---|
| `bench4bl-issta2018.md` | IRBL reproducibility anchor; baseline configs; version-matching & duplicates evidence |
| `pathidea-tse2022.md` | Closest log-bearing prior; benchmark-claim narrowing; symptom≠cause evidence |
| `rrf-sigir2009.md` | Fusion formula origin; k=60 insensitivity; diversity argument |
| `rcacopilot-eurosys2024.md` | Industrial similar-incident retrieval WITHOUT firewall; 93.8%/20-day recurrence |
| `agentless-2024.md` | De-facto LLM localization baseline; SWE-bench Lite audit (solution leakage) |
| `blaze-tse2025.md` | Dense+BM25 RRF precedent; hybrid Top5=0.37 on mention-free bugs; linkage-noise citation |
| `ablots-replication-2026.md` | THE firewall citation: author-confirmed cutoff-date leakage; composer study |
| `rafi-multiagent-fl-2024.md` | Challenge ref [1]; requires-execution family; order-sensitivity |
| `rcagent-cikm2024.md` | Challenge ref [2]; prose RCA, not code regions; detection-time constraint precedent |
| `swebenchplus-2024.md` | 32.67% solution leakage; 12.47→3.97 collapse |
| `swebench-illusion-2025.md` | 76-vs-53 memorization gap; "LLM = undisclosed memory" positioning |
| `locagent-acl2025.md` | Agent SOTA numbers; strict all-locations metric; hop analysis |
| `broccoli-2021.md` | Time-aware vs release benchmarking; search-engine strength |
| `mulocbench-2025.md` | 80→35 fresh-data collapse; non-code fix locations |
| `abb-industrial-bl-2026.md` | Industry-track genre precedent; TF-IDF beats transformers |

## Done, second batch (12 more; all downloaded PDFs covered)

swebenchplus-2024, swebench-illusion-2025, locagent-acl2025, broccoli-2021,
mulocbench-2025, abb-industrial-bl-2026, buglocator-icse2012 (ASSEMBLED
from full-read replication sources; original paywalled — provenance note
inside), leakage-linkpred-2022, finerbench4bl-2023, ahmed-icse2023-seip,
rafi-reformulate-2025 (survey misattribution corrected), fblbert-icse2022,
sbest-2024, longcodearena-2024, cosil-2025, orcaloca-2025, genloc-2025,
log-survey-csur2021.

## Done, third batch

deepirbl-survey-2025 — survey of record for the three IRBL generations;
consecutive-validation + before-fix-version endorsements (our §4 protocol
citations); the 0.0153-vs-0.0149 lexical-gap statistic.
irfl-llm-2024 — GPT-4 query construction + report-type conditioning; the
conditioning-precedent nuance for our regime-novelty sentence.

## Still to obtain (paywalled classics)

BRTracer (ICSME'14), BLUiR (ASE'13), Locus (ASE'16), Ye et al. LR
(FSE'14), AmaLgam (ICPC'14) + AmaLgam+ (JSEP'16), ABLoTS original
(MSR'18), SherLog (ASPLOS'10), CrashLocator (ISSTA'14), CraTer (JSS'19),
Dao et al. (ICPC'17), LogFaultFlagger (ICSE'19), OpenRCA (ICLR'25),
LLM-BL (ICPC'25), Sisman&Kak (MSR'12), Lobster (ICSME'14), BLIA
(APSEC'15). Strategy: the deep-IRBL survey + Bench4BL + ABLoTS
replication already carry their mechanics; assemble provenance-noted
summaries like buglocator-icse2012 where the paper needs them, and
request library access via the user for any we must quote verbatim.
