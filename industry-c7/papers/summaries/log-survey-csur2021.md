# A Survey on Automated Log Analysis for Reliability Engineering

**Shilin He (MSR), Pinjia He (ETH), Zhuangbin Chen, Tianyi Yang, Yuxin Su, Michael R. Lyu (CUHK). ACM Computing Surveys 2021 (arXiv 2009.07237v2), 37 pages.**
PDF: `pdfs/log-survey-csur2021.pdf`

## What it is

The standard survey of the log-analysis pipeline: logging-statement
authoring → log compression → LOG PARSING (template extraction) → log
mining (anomaly detection, failure prediction, failure DIAGNOSIS), plus
open-source toolkits/datasets (the LogPai ecosystem). It is the umbrella
citation for "logs are semi-structured text produced by logging
statements," with the clean definitional framing (framework-determined
structured prefix + developer-written free text) our §3 log-template
discussion can lean on.

## What we actually use it for

- One umbrella citation in §1/related work for the log-analysis field,
  instead of five micro-citations.
- Its taxonomy clarifies our positioning in one line: the survey's
  "failure diagnosis" category operates on log STREAMS (which logs are
  anomalous, which failure type) — none of its surveyed diagnosis work
  outputs ranked SOURCE-CODE regions from an issue report. The log-to-code
  step (Pathidea, ours) sits outside this survey's pipeline, which is
  precisely the challenge's complaint about log-based RCA.
- The logging-statement ↔ log-message correspondence (their Fig. 1) is
  the formal basis of our S3's "logging statements that produced the
  reported log lines" matching and of Pathidea-style template mapping.

## Notes

- 2021 cutoff: pre-LLM; pair with a newer AIOps/LLM citation when
  describing the current landscape.
- Thesis connection: this survey's parsing/anomaly-detection sections are
  the standard background for the thesis's log-analysis chapters;
  LogPai/Loghub datasets referenced here are the anomaly-detection
  counterparts to WoL's context-rich logs (WoL's own intro contrasts
  itself against Loghub via this survey's lineage).
