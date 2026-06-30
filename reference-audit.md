# Reference Audit — ICSE 2027 submission

**Paper:** *Capability-Aware Incident Retrieval from Telemetry to Real-World Incident Reports* (system: REMEDY)
**Audited:** 2026-06-30
**Scope:** every `\cite{}` in `ICSE/sections/*.tex` (46 citation occurrences → 36 unique `refs.bib` entries) checked against the downloaded PDFs in `referenced-research-papers/` (and, for the 5 entries with no PDF, against the publisher/arXiv/repo pages on the web).

**Method:** 31 PDFs were each read end-to-end by a dedicated agent that (a) confirmed the PDF *is* the paper the BibTeX entry describes, (b) checked every metadata field (title, authors+order, venue, year, pages, DOI) against the PDF, and (c) verified that each claim the paper makes where that key is cited is actually supported by the PDF's content. The 5 non-PDF entries (BM25, Qwen, 3 GitHub repos) were verified against their official sources.

---

## Headline result

- **All 31 downloaded PDFs match their cited entry.** No reference points to the wrong paper; no author/title misattribution that inverts meaning.
- **1 must-fix metadata error → ✅ FIXED (2026-06-30):** `shetty2022softner` listed an author not on the cited journal version; corrected in `refs.bib`.
- **1 must-verify prose discrepancy → ✅ FIXED (2026-06-30):** Online Boutique counts corrected to **11 services / 5 languages** in §Datasets (both the comparison table and the prose).
- **A few precision / completeness items → ✅ all resolved (2026-06-30):** SBERT/DPR loss attribution [17], `he2021survey` AIOps pairing [1] (added `notaro2021aiops`), loghub pages/DOI [7], Qwen key rename [29], OTel Demo counts [35].
- **2 of the bib's own "camera-ready re-check" TODO comments are now resolved** (see bottom).

PDF ↔ reference mapping note: the numbering in `referenced-research-papers/links.txt` is the paper's **citation order**. Slots **22 (BM25)** and **29 (Qwen)** are blank — those two PDFs were never downloaded (verified on the web instead). Slots **34/35/36** are the GitHub `@misc` repos (no PDF needed). PDF `22.pdf` is correctly absent.

---

## ACTION ITEMS

### ✅ Fixed (was: must-fix factual error)

**[30] `shetty2022softner` — 6th author "Thomas Zimmermann" removed.**
The BibTeX cites the **journal** version (*Empirical Software Engineering*, vol. 27, no. 4, art. 93, 2022, DOI `10.1007/s10664-022-10159-w`). That EMSE article has **five** authors — Manish Shetty, Chetan Bansal, Sumit Kumar, Nikitha Rao, Nachiappan Nagappan — confirmed both on `30.pdf` (title + affiliations pages) and by the publisher's RIS export from the Springer page. Thomas Zimmermann was an author of the **earlier ICSE-SEIP 2021 conference version**, not this journal version.
*Applied 2026-06-30:* removed `and Zimmermann, Thomas` from the `author` field and added `number = {4}` (issue confirmed by the RIS; article number is 93). Title, journal, volume, year, DOI, and the "SoftNER mines knowledge graphs from cloud incidents" claim were already correct.

### ✅ Fixed (was: must-verify prose vs. source)

**[34] `googleboutique` (Online Boutique) — service & language counts corrected.**
The `@misc` bib entry was already fine; the problem was the prose. The paper said *"Online Boutique is a **twelve-service** e-commerce demo spanning **six languages**"* and the comparison table (`tab:datasets`) listed *"12 services"*. The official repo (`GoogleCloudPlatform/microservices-demo`, the source the entry cites) states **"11 microservices written in 5 languages"** (Go, C#, Node.js, Python, Java) — confirmed from the live README. "Six languages" was impossible (only 5 distinct languages exist in the app).
*Applied 2026-06-30, both occurrences in `sections/04-datasets.tex`:*
- table `Scale` row: `12 services` → `11 services`;
- prose: `a twelve-service … spanning six languages` → `an eleven-service … spanning five languages`.
All other Online Boutique mentions (intro, related work, results tables) name the dataset only and make no count claims. **Update (2026-06-30):** the OTel Demo counts were subsequently corrected as well — see **[35]** below (now 17 services / 12 languages, matching the official docs).

### 🟡 Should consider (citation precision)

**[17] `reimers2019sbert` — "multiple-negatives ranking objective" attribution → ✅ FIXED (2026-06-30).**
Approach §, line ~120 previously attributed the *multiple-negatives ranking (MNR)* training objective to `reimers2019sbert` (co-cited with `wang2020minilm`). Verified by reading the SBERT PDF (Sec. 3): the 2019 paper defines only **Classification** (softmax over `(u,v,|u−v|)`, cross-entropy), **Regression** (cosine + MSE), and **Triplet** objectives, and trains on NLI with a 3-way softmax classifier — it does **not** describe an MNR/in-batch-negatives loss. MiniLM is a distillation paper and also doesn't define it. (MNR is a later `sentence-transformers` addition; the in-batch-negatives-with-BM25-hard-negatives recipe described in the paper is essentially DPR's.)
*Applied:* reworded to *"We fine-tune a compact ($384$-dimensional) MiniLM bi-encoder~\cite{wang2020minilm,reimers2019sbert} with a multiple-negatives ranking loss: …"*. The two citations now attach to the **MiniLM bi-encoder** (MiniLM = encoder model; SBERT = the bi-encoder sentence-embedding paradigm — both correct), and the loss is described operationally (positive vs. in-batch negatives + 2 BM25 hard negatives + 1 random negative) rather than being attributed to those papers. The separate related-work cite (`reimers2019sbert` for "dense bi-encoders build on Sentence-BERT", line 34) was already correct and is unchanged.
*Loss now sourced (2026-06-30):* added `~\cite{karpukhin2020dpr}` after "multiple-negatives ranking loss". Verified from the DPR PDF (§3.2): *"Our best model uses gold passages from the same mini-batch and one BM25 negative passage"* and it uses three negative types — Random, BM25, Gold (in-batch) — exactly the positive + in-batch + BM25-hard + random recipe the sentence describes. So the final sentence reads: *"… MiniLM bi-encoder~\cite{wang2020minilm,reimers2019sbert} with a multiple-negatives ranking loss~\cite{karpukhin2020dpr}: …"* — architecture cites on the bi-encoder, objective cite on the loss.

**[1] `he2021survey` — AIOps / incident-triage framing → ✅ FIXED (2026-06-30).**
`he2021survey` is *"A Survey on Automated Log Analysis for Reliability Engineering"* — a flawless log-analysis survey, but it never uses "AIOps," "incident," "triage," or "on-call," and at Related Work line 7 it *alone* was cited for *"a large AIOps literature."*
*Applied:* added a genuine, on-point AIOps survey — **`notaro2021aiops`** (Notaro, Cardoso & Gerndt, *"A Survey of AIOps Methods for Failure Management,"* ACM TIST 12(6), art. 81, pp. 1–45, 2021, DOI `10.1145/3483424`; metadata verified via the ACM DL, Semantic Scholar, and the IR Anthology) — and changed the cite to `\cite{notaro2021aiops,he2021survey}`. The AIOps claim is now sourced to an AIOps survey, while `he2021survey` stays as the complementary log-analysis survey. The other two `he2021survey` sites are fine as-is: intro line 7 ("signal vs noise") rests on the survey's anomaly-detection coverage, and intro line 20 groups it with `chen2019triage` (incident triage) + `ghosh2022incidents`. *Optional:* add `notaro2021aiops` to the intro line 20 group too for full symmetry — say the word.
*Note:* this adds a **37th** reference (`notaro2021aiops`) beyond the original 36. PDF since downloaded (`3483424.pdf`, 13 pp.) and read directly: title, authors + order, venue (ACM TIST 12(6), Art. 81, Nov 2021), and DOI `10.1145/3483424` all match the entry exactly — confirmed against the PDF's own ACM reference line. It genuinely supports "a large AIOps literature": it reviews **100** AIOps failure-management solutions across 5 categories / 14 subcategories, and explicitly defines AIOps.

### 🟢 Optional (completeness / cosmetic — not errors)

- **[7] `zhu2023loghub`** — ✅ **DONE (2026-06-30):** added `pages = {355--366}` (PDF footers run 355–366; corroborated by IEEE CSDL article id `159400a355`) and `doi = {10.1109/ISSRE59848.2023.00071}` (read from the PDF's first page).
- **[29] `qwen2025` → `qwen2024`** — ✅ **DONE (2026-06-30):** the report is a 2024 arXiv technical report (submitted 19 Dec 2024), so the `2025` key was misleading. Renamed the key to `qwen2024`, updated both `\cite` sites (`05-setup.tex`, `09-related.tex`), and converted the entry to the project's arXiv `@article` style (`journal = {arXiv preprint arXiv:2412.15115}`, `year = {2024}`). Verified on arXiv: title *"Qwen2.5 Technical Report"*, collective author (kept as `{Qwen Team}` — standard for large-team reports), id `2412.15115`. Full individual author list is the alternative if you prefer it.
- **[35] `oteldemo`** — ✅ **DONE (2026-06-30):** corrected to **17 services / 12 languages** (matching the official OpenTelemetry Demo docs) in both the prose (`eighteen services in ten languages` → `seventeen services in twelve languages`) and the table cell (`18 svc.\ + Kafka` → `17 svc.\ + Kafka`). The earlier "ten languages" contradicted both the project's own June-2026 notes (12+) and the current docs (12). Kafka message bus unchanged — confirmed correct. (User chose to align to the official docs over the as-written deployment count.)

---

## Soft/grouped claims that are FINE (documented so they don't resurface)

- **[4] `ahmed2023rootcause`** — used (intro line 37) in a *grouped* cite for "designing retrieval/reasoning pipelines for telemetry-rich settings." This particular paper is an LLM *generation* task using only incident title+summary, not a telemetry retrieval pipeline — but it's grouped with `chen2024rcacopilot` and `zhou2024dbot`, which do fit. Acceptable.
- **[10] `wang2026worldoflogs`** — "Apache Jira issues from **distributed-systems projects**" and the **38,642 reports / 24 projects** slice are the *authors' own derivation* from WoL, not figures stated in the WoL paper. The PDF confirms WoL contains Apache JIRA issues + logs from online sources; the project-type characterization and slice counts are REMEDY's, which the paper already states ("we derive an evaluation slice"). Acceptable — just don't imply the counts come from the WoL paper.
- **[2] `ghosh2022incidents`** — "genuine incident vs noise" (intro line 7) is partially literal; the paper studies detection/monitor failures rather than signal-vs-noise framing. Fine as motivation.
- **[24] `nogueira2019passage`** — re-ranks BM25 (sparse) candidates in the original; REMEDY applies the same cross-encoder "over the dense candidates" (its own pipeline). The cross-encoder-reranker attribution is correct.

---

## Per-reference status (citation order = links.txt number)

| # | Key | PDF | Match | Verdict | Note |
|---|-----|-----|-------|---------|------|
| 1 | he2021survey | 1 | ✓ | ✅ fixed | paired with AIOps survey `notaro2021aiops` for the "AIOps literature" claim (2026-06-30) |
| + | notaro2021aiops | 3483424 | ✓ | ✅ added | NEW AIOps survey (ACM TIST 12(6), Art. 81, 2021, DOI 10.1145/3483424); **PDF-verified**; reviews 100 AIOps FM solutions (2026-06-30) |
| 2 | ghosh2022incidents | 2 | ✓ | OK | |
| 3 | chen2019triage | 3 | ✓ | OK | 9-author order **confirmed correct** |
| 4 | ahmed2023rootcause | 4 | ✓ | OK | preprint of ICSE'23; grouped claim soft but fine |
| 5 | chen2024rcacopilot | 5 | ✓ | OK | all 18 authors, pages, DOI correct |
| 6 | chen2025aiopslab | 6 | ✓ | OK | |
| 7 | zhu2023loghub | 7 | ✓ | ✅ fixed | added pages 355--366 + DOI (2026-06-30) |
| 8 | montgomery2022jira | 8 | ✓ | OK | |
| 9 | zhou2024dbot | 9 | ✓ | OK | preprint; PVLDB vol/issue/pages/DOI all correct |
| 10 | wang2026worldoflogs | 10 | ✓ | OK | slice counts are authors' own (fine) |
| 11 | he2017drain | 11 | ✓ | OK | **all fields exact** |
| 12 | du2017deeplog | 12 | ✓ | OK | **all fields exact** |
| 13 | meng2019loganomaly | 13 | ✓ | OK | 11 authors verified |
| 14 | guo2021logbert | 14 | ✓ | OK | |
| 15 | zhu2019logparsing | 15 | ✓ | OK | **all fields exact** |
| 16 | he2016experience | 16 | ✓ | OK | **all fields exact** |
| 17 | reimers2019sbert | 17 | ✓ | ✅ fixed | cites re-anchored to bi-encoder; loss described, not misattributed (2026-06-30) |
| 18 | wang2020minilm | 18 | ✓ | OK | |
| 19 | song2020mpnet | 19 | ✓ | OK | |
| 20 | wang2022e5 | 20 | ✓ | OK | arXiv (v2 file; bib cites 2022 id — fine) |
| 21 | xiao2024cpack | 21 | ✓ | OK | BGE = C-Pack, confirmed |
| 22 | robertson2009bm25 | — | n/a | OK | no PDF; web-verified (FnTIR v3(4) 333–389, 2009, DOI 10.1561/1500000019) |
| 23 | formal2021splade | 23 | ✓ | OK | |
| 24 | nogueira2019passage | 24 | ✓ | OK | arXiv (v5 file; bib year 2019 — fine) |
| 25 | cormack2009rrf | 25 | ✓ | OK | RRF formula + k=60 confirmed in source |
| 26 | karpukhin2020dpr | 26 | ✓ | OK | |
| 27 | lewis2020rag | 27 | ✓ | OK | 12 authors verified |
| 28 | yao2023react | 28 | ✓ | OK | preprint of ICLR'23 |
| 29 | qwen2024 | — | n/a | ✅ fixed | key renamed 2025→2024; arXiv @article form; cites updated (2026-06-30) |
| 30 | shetty2022softner | 30 | ✓ | ✅ fixed | removed author Zimmermann; added no. 4 (2026-06-30) |
| 31 | runeson2007duplicate | 31 | ✓ | OK | pages/DOI not printed in PDF but standard values |
| 32 | sun2010duplicate | 32 | ✓ | OK | |
| 33 | he2020dccnn | 33 | ✓ | OK | pages 117–127 + DOI **confirmed correct** |
| 34 | googleboutique | — | n/a | ✅ fixed | counts corrected to 11 services / 5 langs, table + prose (2026-06-30) |
| 35 | oteldemo | — | n/a | ✅ fixed | corrected to 17 svc / 12 langs per official docs (2026-06-30) |
| 36 | chaosmesh | — | n/a | OK | K8s chaos platform; NetworkChaos = partition/loss/DNS |

---

## Resolved camera-ready TODOs (from the comment block at the top of `refs.bib`)

The bib header lists two items flagged for camera-ready re-check. Both are now resolved against the PDFs:

1. *"middle-author order of chen2019triage (IEEE doc 8952483)"* — **resolved, no change needed.** `3.pdf` shows the 9-author order exactly as in the bib: Chen, He, Lin, Zhang, Hao, Gao, Xu, Dang, Zhang.
2. *"exact pages/DOI of he2020dccnn (ACM DL)"* — **resolved, no change needed.** `33.pdf` confirms pages **117–127** and DOI **`10.1145/3387904.3389263`**.
