# ARISE — Code/Artifact Findings for the ICSE Rebuttal

**Compiled:** 2026-09-25
**Scope:** Answers to 10 fact-check questions against the codebase, configs, and saved
results. Every claim below is sourced to a file path + line numbers.
**Method:** Read-only. No new experiments were run. Aggregations reported here are reads
over already-saved prediction/trace/dataset files in `paper-results/` and
`data/derived/global/`.

> Conventions: ⚠️ marks a place where the code does something different from what the
> paper says, or where a claim is unsupported by the artifacts.

---

## 1. MAXCONF(R)

**a. Which function computes it** — `make_reformulation_gate` in
`src/agent/controller/rule.py:343-376`:

```python
# rule.py:364-373
        # Inspect the L2 retriever set's max confidence.
        max_conf = 0.0
        for r in (CHEAP_RETRIEVER, *EXPENSIVE_RETRIEVERS):
            out = trace.latest_output(r)
            if out is None or out.triage_score is None:
                continue
            max_conf = max(max_conf, float(out.triage_score))

        # Below the floor → consensus failed → open the gate.
        return max_conf < confidence_floor
```

**b. What it compares with 0.5 — answer (iii), something else.** It is **not** the fused
RRF score from Eq. 2, and **not** dense cosine similarity. It is the **max `triage_score`
(ticket-worthiness probability) over the retriever skills** — the output of each
pipeline's calibrated triage head, read from cached per-window predictions.

The retrievers are `PredictionsBackedSkill`s that read `triage_score` straight out of a
saved JSONL (`src/agent/skills/predictions_backed.py:230-238`):

```python
        triage_score = pred.get("triage_score")
        return SkillOutput(
            ...
            triage_score=float(triage_score) if triage_score is not None else None,
```

The set iterated is `CHEAP_RETRIEVER` + `EXPENSIVE_RETRIEVERS` (`rule.py:55-64`) —
`retrieve_dense`, `retrieve_log_sequence`, `retrieve_hybrid_fusion`,
`retrieve_hybrid_fusion_llm`, `retrieve_knowledge_graph`. It iterates over **retriever
skills**, not over the candidates in `R`.

⚠️ **This contradicts Algorithm 1.** Line 84 writes `MaxConf(R)` where `R` was just
assigned `RRF(Dense, Sparse, Graph; …)` on line 83, so the notation says "max confidence
of the fused result set." The code never touches the fused ranking or any per-candidate
score. Reviewer R2 already flagged the Eq. 2 collision, and `response-R2.md:112` concedes
it is "a decision, not a fused rank score."

**c. Range** — `[0,1]`, a probability. Measured on the 13,388 WoL test windows
(`paper-results/retrieval-cascades/wol-v3/hybrid-rrf-predictions.jsonl`): min 0.177,
p25 0.487, median 0.510, p75 0.574, max 0.862; 74.27% ≥ 0.5. Confirms the figures quoted
in `response-R2.md:115-117` exactly.

**d. Does reformulation run for every escalated window? No.** Because it is a calibrated
probability, not a raw RRF score, the gate discriminates normally. From the saved traces:

| dataset | reformulate_query fired | of n windows |
|---|---|---|
| wol-v3 | 2,810 | 13,388 (20.99%) |
| online-boutique | 179 | 1,008 (17.76%) |
| otel-demo | 25 | 247 (10.12%) |

The gate was re-derived independently from the prediction files:
`max(dense, hybrid) triage_score < 0.5` predicts gate-open on 2,810/13,376 windows and
agrees with the actual `skills_invoked` on **13,376/13,376 = 100.00%** of windows,
0 mismatches.

⚠️ **Two further gaps before defending this line:**

1. **Reformulation is a no-op on the results.** `src/agent/skills/reformulate_query.py:22-27`:
   > "For v1 the predictions-backed retrievers don't actually re-query on the reformulated
   > text (they look up by window_id), so the loop's value is mostly an instrumentation
   > hook… v2's live-retrieval mode will close the loop fully."

   So `R ← Reformulate(w, M_<t)` (Alg. 1 line 84) does not change `R` in the reported numbers.

2. **No LLM was involved.** `src/agent/harness_builder.py:356-358`:
   ```python
       # Reformulation — deterministic stub by default (use_llm=False).
       if ReformulateQuerySkill.name not in skip:
           reg.register(ReformulateQuerySkill(use_llm=False))
   ```
   Consistent with the measured run: `paper-results/agent-end-to-end/wol-v3/agent-eval.json`
   records `total_cost: {"llm_tokens": 0, "usd": 0.0, …}`. `verify_with_llm` never appears
   in any trace on any dataset. This contradicts `03-approach.tex:99-100` ("Language-model
   calls are therefore limited to gated verification and reformulation steps") — in the
   reported runs there were **zero** LLM calls at decision time.

---

## 2. Thresholds 0.90 and 0.5

**a. Hard-coded**, in `src/agent/controller/rule.py`:

```python
# rule.py:36
DEFAULT_TRIAGE_HIGH_CONFIDENCE = 0.90
# rule.py:75
DEFAULT_REFORMULATION_CONFIDENCE_FLOOR = 0.5
```

0.90 is mirrored (not sourced) in `agent-config.yaml:66` — `triage_high_confidence: 0.90`.
There is no config entry for the 0.5 floor; `agent-config.yaml` only carries
`novelty_threshold: 0.4` (line 121) and an unrelated `max_usd_per_window: 0.50` (line 51).

**b. Tuning evidence: NOT FOUND.** No notebook, log, or saved result shows either
threshold being tuned.

- A sweep script exists — `scripts/agent/agent_hp_sensitivity.py`, documenting
  `cheap_path_threshold (default 0.9)` and `reformulation_confidence_floor (default 0.5)`
  at lines 8-9 — but **there is no saved output anywhere**. Searched the whole repo for
  `*hp-sensitivity*` and any `agent_runs/` directory: nothing. The script's own `--output`
  target (`data/agent_runs/…`) does not exist.
- Had it been run, it would have swept on **test**:
  `load_ob_cases(args.global_dir, split="test", …)` at lines 224, 232, 245. No validation
  split is used.
- It also disables the mechanism it measures: line 175,
  `max_reformulation_retries=0,  # gate-only measurement; not actually retrying`.

⚠️ **Flag for the rebuttal:** `response-R2.md:122` currently promises "we will also report
the sensitivity sweep we have but did not show." There is no sweep output in the repo.
Either run it (on validation) or drop that sentence — as written it asserts an artifact
that does not exist.

The accurate framing is what `response-R2.md:119-121` already says: both are the
pipelines' own decision thresholds (0.5 = ticket-worthy/noise boundary; 0.90 =
numeric classifier's high-confidence commit point), carried over untuned.

⚠️ **One mechanism correction.** `response-R2.md:123` says "on WoL the 0.90 cheap-path gate
is never satisfied (0.0% of windows reach 0.90)." The 0.0% is true for the hybrid score
(measured: 0/13,388 ≥ 0.90), but that is not why the gate opens. On WoL `triage_numeric`
**never runs at all** — absent from `skills_invoked` in all 13,388 traces, because WoL has
no numeric features. The gate escalates on the missing-signal branch (`rule.py:311-313`):
"If triage_numeric didn't run or didn't produce a score, we have no triage signal —
escalate." State it that way; it is the stronger, correct claim.

---

## 3. Triage classifiers on World of Logs

**a. Input features: numeric telemetry columns only — no text, no TF-IDF, no embeddings,
no Jira metadata.** All three classifiers subclass `_NumericClassifierPipeline` and
consume `ds.feature_columns`, read from `triage-feature-columns.json`.

**b. The feature builder is `_build_feature_matrix`, `src/comparison/pipelines.py:62-72`:**

```python
def _build_feature_matrix(
    windows: list[Any], feature_columns: list[str]
) -> list[list[float]]:
    """Pull the numeric feature vector out of each TriageWindow.raw dict.
    Missing columns zero-fill; that matches NumericFeaturizer behaviour and
    is what the contract documents."""
    return [
        [float(w.raw.get(col, 0.0) or 0.0) for col in feature_columns]
        for w in windows
    ]
```

Registrations: `hist_gradient_boosting_numeric` (`pipelines.py:257`),
`calibrated_random_forest_numeric` (`pipelines.py:296`),
`logistic_numeric_sklearn` (`pipelines.py:338`).

⚠️ **CONFIRMED DEFECT — the WoL design matrix is all zeros.** Verified directly against
`data/derived/global/2026-06-17-wol-real-v3-global/`:

- 94 feature columns in `triage-feature-columns.json`
- 78,140 rows in `global-triage-examples.jsonl`
- all 94 keys **present** on every row, and **0 rows have any non-zero value** —
  0 distinct non-zero columns

So the zero-fill path is not even reached; the columns exist and are literally zero. The
reported ROC-AUC 0.500 / PR-AUC 0.506 is **forced by a constant-feature input, not
learned.** The saved leaderboard corroborates it —
`paper-results/triage-leaderboard/SUMMARY.md` shows all three classifiers at identical
PR-AUC 0.506 / ROC-AUC 0.500 with `R@FPR5 = 1.000`, the signature of a constant predictor.

"Triage classification collapses to chance on real data" is therefore not supported by
this experiment. `scripts/rebuttal/05_wol_text_triage_classifier.py` is the re-run on
ticket text (TF-IDF 1-2 grams over `triage_evidence_text`, LogisticRegression / SGD,
5 seeds); per `scripts/rebuttal/README.md` it yields ROC-AUC 0.572-0.601 with a CI
excluding 0.500. Not executed here — numbers as recorded in that README.

---

## 4. Fine-tuning of the dense MiniLM retriever

Implementation: `src/neural_models/bi_encoder.py`.

**a. Once, offline, before evaluation.** `train_and_predict` (line 454) runs fine-tuning
once (`_finetune`, line 352), then encodes and predicts. No per-incident or
during-evaluation update exists. Backbone `sentence-transformers/all-MiniLM-L6-v2`
(line 209), `MultipleNegativesRankingLoss` (line 369), 5 epochs, AdamW lr 2e-5,
warmup 10% (lines 25-27).

**b. Split: train + validation.** Line 491:

```python
        # --- 2. Fine-tune on train + val pairs (val windows DO have
        #         training even though they're held out for triage
        pairs = self._build_train_pairs(train_w + val_w, corpus, by_id)
```

The docstring agrees (line 23): "On our train+val: ~12k positives from 1262 windows."
Test is held out — the visibility masks (`_vis`, line 535) enforce time-ordered memory
visibility.

⚠️ **Worth disclosing:** the encoder trains on validation, so validation is not clean for
any threshold selection. This compounds Q2 — there is no untouched split on which the
gates could have been tuned.

**c. Frozen during evaluation: yes.** Prediction goes through `_encode` (line 402), which
calls `model.encode(...)` — inference-only, no optimizer step. Fine-tuning is confined to
`_finetune`, called once before the encode passes.

**d. Seeds — asymmetric, and WoL is single-seed.** From `paper-results/robustness/multiseed/`:

| dataset | retrained seeds |
|---|---|
| online-boutique | **3** — seed 42 + seed1 + seed2 |
| otel-demo | **3** — seed 42 + seed1 + seed2 |
| **wol-v3** | **1** — seed 42 only |

There is no `robustness/multiseed/wol-v3/` directory.
`scripts/rebuttal/07_seed_vs_sampling_variance.py:18-19` confirms it only loops over
`online-boutique` and `otel-demo`. So the headline 0.963 Hit@5 on WoL rests on a single
seed, and no seed-variance envelope exists for it.

---

## 5. LLM-as-judge validation

Producer: `scripts/research-lab/run_llm_judge_gold.py`. Results:
`paper-results/gold-validation/{wol-v3,online-boutique,otel-demo}/llm-judge-gold-results.json`.

**a. Model** — `Qwen/Qwen2.5-7B-Instruct` (line 35), bf16, greedy (`do_sample=False`),
`torch.manual_seed(42)`.

**b. Scale** — integers **1-5**; "5=clearly the same/related issue, 1=unrelated".
"Relevant" is thresholded at `>= 4` (`frac_rel`, line 118).

**c. Counts — 300 gold + 300 random per dataset** (`--limit 300`, one gold and one random
control per sampled window), seed 42. Confirmed in all three saved JSONs:
`n_windows: 300, n_gold_judged: 300, n_random_judged: 300`.

**d. Controls are drawn from the WHOLE memory corpus, not the same project** (lines 84-88):

```python
        goldset = set(w.matched_memory_issue_ids)
        neg = rng.choice(all_ids)
        for _ in range(5):
            if neg not in goldset:
                break
            neg = rng.choice(all_ids)
```

`all_ids = list(mem_text)` (line 68) is every ticket in the corpus — on WoL, all 24
projects. The only constraint is "not in this window's gold set." There is no project or
component matching.

⚠️ **This is exactly R1's objection, and the saved numbers support the reviewer, not the
paper.** A random cross-project ticket shares neither project nor component, so it cannot
be relevant under the gold relation by construction — the control is trivially easy, and
the gap measures "gold beats a different project," not usefulness. Worse, the absolute
scores are weak:

| dataset | gold mean | random mean | gap | **gold % rated ≥4** |
|---|---|---|---|---|
| wol-v3 | 2.60 | 1.36 | 1.24 | **6.3%** |
| online-boutique | 2.35 | 1.89 | 0.47 | **16.3%** |
| otel-demo | 2.31 | 1.97 | 0.34 | **11.0%** |

On WoL the judge rates only **6.3% of gold pairs as relevant (≥4)**, mean 2.60/5. Do not
lead with this evidence; a reviewer who opens the artifact will find that the judge
largely *disagrees* with the gold labels. The script's own docstring (line 11) already
calls it "a stopgap for a full human study."

**e. Prompt text** (lines 39-47, verbatim, single user turn via `tok.apply_chat_template`):

```
Rate how relevant a PAST TICKET is to a CURRENT incident window — i.e. whether
the past ticket describes the same or a closely related problem and would help
triage the incident.

CURRENT INCIDENT WINDOW:
{query[:600]}

PAST TICKET:
{ticket[:400]}

Reply with ONLY a single integer 1-5: 5=clearly the same/related issue,
1=unrelated. Answer:
```

`MAX_Q = 600`, `MAX_DOC = 400` chars (line 36); `max_new_tokens=4`; the score is parsed
with `re.search(r"[1-5]", g)`.

---

## 6. Human-annotation kit

**NOT FOUND. It does not exist in the repo or the artifact.**

Searched the whole tree for `annotation.kit`, `annotation_kit`, `annotator`, `kappa`,
`human.annotation`. Every hit is a *promise*, never an artifact:

- `ICSE/sections/08-threats.tex:14` — "and release a human-annotation kit"
  ← **the paper claims release**
- `DOCS/threats-to-validity.md:10-11` — "we ship a human-annotation kit for a later
  Cohen's/Fleiss' κ"
- `scripts/research-lab/run_llm_judge_gold.py:11` — "ship the human-annotation kit for
  later kappa"

There are no guidelines, no sample pairs, no rating sheet, no instructions, no κ
computation code anywhere.

The draft already concedes this — `response-R3.md:172`: *"'human-annotation kit'. This
phrasing in Threats was misleading and we…"*. Keep that concession. The Threats sentence
must be cut or changed to future tense, because R1 rated the artifact "Partially
Satisfactory" and a reviewer checking this claim will find nothing.

---

## 7. Knowledge-graph "components"

**a. LLM-extracted from ticket text — NOT the Jira `components` metadata field.** The
extraction prompt is `_TICKET_SYSTEM_PROMPT` in
`src/v2_advanced/proposal_d_knowledge_graph/extractor.py:100-102`:

```
  - components:          list of CANONICAL component / infra names actually
                         mentioned (e.g. ["envoy", "kubelet"]). Empty list
                         if none.
```

Parsed at `extractor.py:234` / `:321`:
`components=[s for s in (obj.get("components") or []) if isinstance(s, str)]`.
Output lands in
`data/derived/global/2026-06-17-wol-real-v3-global/v2_kg_extractions/all_extractions.jsonl`;
a sample row carries `components: ['hadoop']` alongside LLM-written `root_cause`, `fix`,
and `symptoms`.

These are a **different vocabulary** from the gold-defining field. The gold relation uses
`triage_components` (Jira metadata, see Q8); the KG uses its own extracted names. Per
`scripts/rebuttal/README.md`, the two vocabularies overlap by only **9.9%** — which is the
*defense* against a leakage charge, though it also means the graph is not exploiting the
gold signal.

**b. At query time the graph does NOT use the query's Jira component field.** The window
side has its own prompt, `_WINDOW_SYSTEM_PROMPT` (`extractor.py:129-140`):

```
  - components:          CANONICAL components mentioned. Empty list if none.
```

Window extractions go to `v2_kg_extractions_windows/`. Both sides are LLM-extracted from
text/telemetry under a canonical-name constraint ("Use ONLY canonical names from the lists
above… Don't invent services or errors not in the lists"). No Jira metadata field is read
at query time.

---

## 8. Relevance labels on World of Logs

Builder for the v3 corpus used in the paper:
`scripts/research-lab/build_wol_real_corpus_v3.py`.

**a. Coarse rule — `_coarse_match`, lines 362-371:**

```python
def _coarse_match(a_doc: dict, b_doc: dict) -> bool:
    """Same project AND at least one shared component."""
    a_proj = v1._safe_get(a_doc, "fields", "project", "name")
    b_proj = v1._safe_get(b_doc, "fields", "project", "name")
    if not a_proj or not b_proj or a_proj != b_proj:
        return False
    a_comps = set(v1._component_names(a_doc))
    b_comps = set(v1._component_names(b_doc))
    return len(a_comps & b_comps) >= 1
```

Note it reads `fields.project.name` and `_component_names` — the **Jira metadata** fields.

**b. Strict rule — `_strong_match`, lines 373-385:**

```python
def _strong_match(
    a_doc: dict, b_doc: dict, a_tokens: set[str], b_tokens: set[str],
    *, threshold: float = STRONG_MATCH_JACCARD_THRESHOLD,
) -> bool:
    """Coarse match AND symptom-token Jaccard > threshold."""
    if not _coarse_match(a_doc, b_doc):
        return False
    if not a_tokens or not b_tokens:
        return False
    inter = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return (inter / union) > threshold
```

`STRONG_MATCH_JACCARD_THRESHOLD = 0.15` (line 173).

**Symptom terms — `_symptom_tokens`, lines 355-359.** They are bag-of-words tokens from the
ticket's `log_msgs`, not extracted phrases:

```python
def _symptom_tokens(log_msgs: list[str]) -> set[str]:
    """Tokenize log_msgs for the strong-match Jaccard. Reuses v1's stopword set."""
    text = " ".join(log_msgs).lower()
    raw = re.findall(r"[a-z][a-z0-9_]{2,}", text)
    return {t for t in raw if t not in v1.SYMPTOM_STOPWORDS}
```

`SYMPTOM_STOPWORDS` is a 60-term frozenset at `build_wol_real_corpus.py:120-131` — English
function words plus log boilerplate (`error`, `info`, `warning`, `debug`, `trace`,
`fatal`, `line`, `file`, `thread`, `exception`, `stack`). Self-matches are excluded
(`compute_gold_relations` docstring, line ~397). These are **unrelated** to the KG's
LLM-generated `symptoms` field from Q7.

**c. Strict-rule baseline results: NOT SAVED.** No strict-rule leaderboard table exists in
`paper-results/`. Only per-query predictions are saved;
`scripts/rebuttal/04_strict_relation_leaderboard_significance.py` recomputes the table on
the fly from them, and its output was never persisted. `scripts/rebuttal/README.md` records
only a qualitative summary ("Hybrid best on Hit@1/Hit@5/MRR against every system with
per-query predictions (only exception: Hit@5 vs. degenerate raw-corpus BM25, n.s.)") —
**no numbers**. Not executed here.

⚠️ **Two of the eight systems cannot be rescored under the strict rule at all.** Rescoring
needs per-query `matched_issue_ids`, and on wol-v3 those exist only for:

| system | wol-v3 predictions file |
|---|---|
| Hybrid fusion | `paper-results/retrieval-cascades/wol-v3/hybrid-rrf-predictions.jsonl` ✅ |
| Dense bi-encoder | `.../biencoder-predictions.jsonl` ✅ |
| Knowledge graph | `.../kg-retrieval-predictions.jsonl` ✅ |
| BM25 | `.../bm25-predictions.jsonl` ✅ |
| BGE | `baselines/sota-dense/wol-v3/bge-predictions.jsonl` ✅ |
| E5 | `baselines/sota-dense/wol-v3/e5-predictions.jsonl` ✅ |
| Cross-encoder | `baselines/cross-encoder-rerank/wol-v3/ce-predictions.jsonl` ✅ |
| Qwen / LLM-RAG | `baselines/llm-rag/wol-v3/llm-rag-predictions.jsonl` ✅ *(500-window subset only)* |
| **MPNet** | **only `mpnet-results.json` — NO predictions JSONL** ❌ |
| **TF-IDF** | **only `tfidf-results.json` — NO predictions JSONL** ❌ |

To report a complete strict-rule table, re-run MPNet and TF-IDF on wol-v3 with prediction
dumping, or mark those two cells as unavailable. For reference, the saved **coarse** Hit@5
on wol-v3 (`paper-results/baselines/SUMMARY.md`): bge 0.829, e5 0.838, mpnet 0.834,
tfidf 0.766, ce 0.874, llm-rag 0.856, bm25 —.

---

## 9. World of Logs data

**a. Version used: v3**, dataset id `2026-06-17-wol-real-v3-global`. Built by
`scripts/research-lab/build_wol_real_corpus_v3.py` — "24 distributed-systems projects, no
quality filters, maximum pool utilization (~78K total rows)… Memory corpus ~38K Bug+Fixed
rows" (lines 1-15). Matches the paper's 38,642 / 24 projects. Referenced in
`DOCS/dataset.md:269,537`, `DOCS/WoL-v3-dataset.md:5`, `DOCS/REPRODUCE.md:21`,
`DOCS/agentic-system.md:232,662`.

**b. Every place v2/v3 appear** (excluding `.venv`, `paper-results/`, and the review files):

*v3 = `2026-06-17-wol-real-v3-global` (active, used by the paper):*
- `data/derived/global/2026-06-17-wol-real-v3-global/` — `dataset-metadata.json:2,5,7`,
  `README.md:3`, `triage-split-manifest.json:4,150`,
  `tch-lite-refit/{biencoder,bm25,kg-retrieval}-mode3-results.json:3`
- `DOCS/agentic-system.md:232,662`; `DOCS/dataset.md:269,537`; `DOCS/REPRODUCE.md:21`;
  `DOCS/PUBLICATION.md:16,24`
- `DOCS/WoL-v3-dataset.md:5,8,28,402,417,437,460,478,491,510,528,534,546,619,699`
- `scripts/rebuttal/{01,02,03,04,05}.py` (hard-coded
  `G = ".../2026-06-17-wol-real-v3-global"`)

*v2 = `2026-06-15-wol-real-v2-global` (retired, but still wired in two live places):*
- **`scripts/agent/bundle_dataset_for_publication.py:44`** ← **the artifact bug**
- **`agent-config.yaml:145`** ← verifier calibration (see below)
- `data/derived/global/2026-06-15-wol-real-v2-global/` — `dataset-metadata.json:2`,
  `tch-lite-refit/{biencoder,hybrid-rrf,kg-retrieval}-mode3-results.json:3`
- `data/README.md:14,29,37`; `DOCS/dataset.md:536`; `DOCS/WoL-v3-dataset.md:8,491,546`;
  `data/.../triage-split-manifest.json:150` (`comparable_to`)

⚠️ **R1's artifact complaint is confirmed at the line level.**
`scripts/agent/bundle_dataset_for_publication.py:44`:

```python
    "world-of-logs": {
        "dataset_id": "2026-06-15-wol-real-v2-global",   # v2 refresh 2026-06-16 (Phase B augmented)
```

⚠️ **Second, previously-unflagged v2 leak — `agent-config.yaml:141-145`:**

```yaml
verifier_calibration:
  known_helpful_distributions:
    - 2026-05-25-dataset-v5-large-global   # OB (verifier helps; in cascade)
  known_harmful_distributions:
    - 2026-06-15-wol-real-v2-global        # WoL v2 — RQ-D3 / Mode 3 §3.9: -0.272 coarse Hit@5
```

The harmful-distribution entry names **v2**, while the paper evaluates **v3**, and
`default_policy: skip`. So on v3 the verifier is skipped by *fallback*, not by
calibration. The claim that calibration "structurally closes RQ-A8"
(comment at `agent-config.yaml:76-78`) does not hold for the dataset actually evaluated.
Fix the id before releasing.

**c. `pred_uncertainty` filter — present in v1/v2, REMOVED in v3.** v3 header, line 6:
`* No pred_uncertainty filter (was ≤ 0.05 in v1/v2)`. Also `v3.py:192` ("1. No
`pred_uncertainty` ≤ 0.05 predicate"), `v3.py:806`
(`"pred_uncertainty_filter": "REMOVED (was <= 0.05)"`), `v3.py:878`
(`~~pred_uncertainty ≤ 0.05~~ — removed`).

The v1/v2 code that applied it, `build_wol_real_corpus_v2.py:304`:
```python
        "pred_uncertainty":     {"$lte": PRED_UNCERTAINTY_MAX},
```
(also `build_wol_real_corpus.py:190`). v3 likewise dropped `description ≥ 200 chars` and
`log_msgs ≥ 1`.

**Note the interaction with (b):** the artifact ships v2, which *has* the `≤ 0.05` filter;
the paper reports v3, which does not. Anyone reproducing from the published artifact gets
a differently-filtered corpus.

**d. `log_msgs` is used — in several load-bearing places.** Most importantly it defines the
strict relation's symptom tokens (`v3.py:355-359`, Q8b). Also:
- `build_wol_real_corpus.py:281-287` — `_first_n_log_msgs` / `_joined_log_msgs` (capped at
  `MAX_LOG_MSGS_PER_TICKET`; v3 bumps truncation 4× to 200 log lines)
- `:346-347,369` — becomes `description_code` and `log_quotes` in the humanized ticket
- `:433`, `:751` — becomes `evidence_text` (the retrieval query text)
- `:665-675` — `parts.append(f"Log lines:\n{log_msgs_str}")` in the doc text
- `build_wol_real_corpus_v2.py:421-427` — `evidence_text = "\n".join(log_msgs)`
- `build_wol_real_corpus.py:191`, `v2.py:311` — the (v1/v2-only) `log_msgs ≥ 1` Mongo predicate

**e. Resolution status and timestamp.**

*Status* — `fields.resolution.name`, from the source Jira/Mongo docs. The label taxonomy
(`v3.py:120-134`, documented at `:883-885`):
```python
TICKET_WORTHY_RESOLUTION  = "Fixed"
BORDERLINE_RESOLUTIONS    = ["Duplicate", "Incomplete", "Cannot Reproduce"]
NOISE_RESOLUTIONS         = ["Won't Fix", "Invalid", "Not a Bug", "Not A Problem"]
REGULAR_ISSUETYPES        = ["Improvement", "New Feature", "Question", "Documentation", "Wish"]
```
`ticket_worthy` = `issuetype=Bug AND resolution=Fixed` (`v3.py:248`). v3 adds two buckets:
`borderline_unresolved` (Bug + `resolution: None`, 12,671) and `borderline_other_res`
(Bug + resolution outside the known set, 3,093) — `v3.py:255-264`.

*Timestamp* — `fields.resolutiondate`, used only to derive a duration
(`build_wol_real_corpus.py:313-323`):
```python
def _resolution_time_seconds(doc: dict) -> int:
    created = _safe_get(doc, "fields", "created")
    resolved = _safe_get(doc, "fields", "resolutiondate")
    if not (created and resolved):
        return 0
```
Note it returns **0** when either field is missing or unparseable — indistinguishable from
a genuine zero-duration resolution.

This is the construct R1 attacks: ticket-worthiness is `resolution == "Fixed"`, a final
disposition, not on-call page-worthiness. The code confirms the reviewer's reading exactly.

**f. Component counts — computed and saved, partially.**

Saved in `ICSE/reviewers-comments/response-R1.md:161-170`:
- **75.3%** of all 78,140 issues carry ≥1 component; **80.5%** on the test split
- Of 6,773 held-out ticket-worthy queries, **1,621 (23.9%) have no component at all** → no
  gold by construction. This is why the retrieval table reports **n = 5,150, not 6,773** —
  an undisclosed conditioning step
- More than one component: **8,935 issues with 2** (48,394 with exactly 1)
- Vocabularies are project-local and uneven: Camel 205 distinct components, IMPALA 9

Producer: `scripts/rebuttal/01_component_metadata_and_gold_stats.py` (the `ncomp` counter,
line 25). **Caveat:** no machine-readable output was persisted — these figures exist only
as prose in `response-R1.md` and `scripts/rebuttal/README.md`. The full count distribution
beyond "1 or 2" (i.e. 3+) is **NOT COMPUTED/NOT SAVED**; the script prints only the first
8 buckets (`dict(sorted(ncomp.items())[:8])`) and that output was never captured. Re-run
and save it before citing anything past the 2-component bucket.

Gold-set sizes, from `scripts/rebuttal/README.md`: coarse **mean 410 matches/query**,
strict **mean 50**. Against a 38,642-item memory, a random ranker scores Hit@5 = 0.036
(coarse) / 0.0044 (strict) — the useful context for 0.963.

---

## 10. Cost measurement (40%, 63%, 78%)

**a. How cost is computed: a counterfactual estimate from a hard-coded per-skill price
list — NOT measured wall-clock, tokens, or money.** The table is `PER_SKILL_COST` in
`scripts/agent/cost_vs_cascade.py:50-72`, values
`(mean_wall_ms, mean_llm_tokens, usd_per_call)`, introduced by this comment (lines 47-49):

```python
# Per-skill cost model — conservative LLM rates per Mode 3 telemetry
# + cheap-skill wall times from the §3.5 v5 run. The point is to
# give a defensible counterfactual; not to claim exact $cost.
```

Key entries:
```python
    "retrieve_dense":                (1.0,    0, 0.0),
    "retrieve_hybrid_fusion":        (1.0,    0, 0.0),
    "compose_l2":                    (0.5,    0, 0.0),
    "verify_with_llm":               (15400.0, 1969, 0.00050),   # Mode 3 §3.9 telemetry
    "reformulate_query":             (300.0,    400, 0.00010),    # estimated
    "request_similar_incident_window": (3.0,   0, 0.0),
    "rerank_with_evidence":          (1.0,     0, 0.0),
```

Costs are assigned by counting trace events, never by timing (lines 100-115): `skill_end` →
invoked, `skill_skipped_by_gate` → skipped, then
`actual_wall = sum(_cost_for(s)[0] for s in invoked)`.

**b. The "run-all cascade" baseline** is not a separate system or run. It is the same trace
with every gate forced open — `cost_vs_cascade.py:106-107`:

```python
        # Counterfactual: every gated skill would have run too
        counterfactual = invoked + skipped
```

So the baseline is exactly "the skills this plan contained," priced from the table. Skills
never placed in the plan (e.g. `verify_with_llm`, `retrieve_knowledge_graph`,
`retrieve_log_sequence` — none appear in any trace) are **absent from the baseline
entirely**. It is not "a cascade that runs everything," as `06-results.tex:140` claims.

**c. The file producing the percentages** is `scripts/agent/cost_vs_cascade.py` (formula at
lines 160-163), with outputs saved to
`paper-results/agent-value/{dataset}/cost-vs-cascade.json`. The table's 40/63/78 are
`summary.savings_pct.wall`:

| dataset | n_windows | **wall %** | tokens % | usd % | paper |
|---|---|---|---|---|---|
| online-boutique | 1,008 | **39.97** | 41.12 | 41.12 | 40% |
| otel-demo | 247 | **63.37** | 65.28 | 65.28 | 63% |
| wol-v3 | 13,388 | **78.09** | 78.99 | 78.99 | 78% |

⚠️ **Three problems, in increasing severity.**

1. **"Measured" is wrong.** `06-results.tex:140` says gating "cuts per-window cost
   (wall-clock time and model usage) by 40%, 63%, and 78%." Both quantities are table
   lookups over event counts. `scripts/rebuttal/README.md` defect #3 already says so:
   *"Cost saving is an estimated counterfactual, not a measurement."*

2. **The estimate contradicts the measured run.** For WoL, this analysis reports
   `actual_llm_tokens: 1,124,000` and `actual_wall_seconds: 901.1`. The actual run
   (`paper-results/agent-end-to-end/wol-v3/agent-eval.json`) recorded `llm_tokens: 0` and
   `wall_seconds: 590.0`. The cost file also points at exactly those traces
   (`trace_root: paper-results/agent-end-to-end/wol-v3/traces`) — so the same run yields
   0 tokens when measured and 1.12M when priced.

3. **On WoL, 100% of the saving is a skill that makes no LLM call.** From `per_skill` in the
   saved JSON, only three skills have a non-zero save rate — `reformulate_query` (78.99%),
   `request_similar_incident_window` (79.01%), `rerank_with_evidence` (79.01%) — and of
   these only `reformulate_query` carries non-zero cost in the table. The token arithmetic
   closes exactly:

   - skipped: 10,566 × 400 = **4,226,400** = 5,350,400 − 1,124,000 ✅
   - invoked: 2,810 × 400 = **1,124,000** ✅

   So the entire 78.99% token saving prices `reformulate_query` at 400 tokens/call — but it
   is registered with `use_llm=False` (`harness_builder.py:358`) and spends **zero** tokens.
   `verify_with_llm`, the only genuinely expensive skill in the table at
   15,400ms/1,969 tokens, never entered the plan and contributes nothing.

The honest claim the artifacts support is a **gate-skip rate**: on WoL the controller
skipped 3 of 8 candidate skills on 78.9% of windows (10,566/13,388). That is real and
verifiable from the traces. Any currency- or token-denominated saving is an unvalidated
price model, and on WoL it prices a stub.

---

## Paper-vs-code discrepancies, ranked by rebuttal risk

1. **Cost (Q10)** — "measured" 40/63/78 are counterfactual estimates; on WoL the entire
   saving prices a no-LLM stub, and the run measured 0 tokens. Highest risk: the numbers
   are in a headline table.
2. **WoL triage (Q3)** — ROC-AUC 0.500 is forced by an all-zero design matrix (verified:
   0/78,140 rows non-zero across 94 columns). "Collapses to chance" is unsupported;
   measured text signal is 0.57-0.60.
3. **Human-annotation kit (Q6)** — `08-threats.tex:14` claims release; it does not exist.
   R1 already docked the artifact score.
4. **Artifact + config ship v2, paper reports v3 (Q9b)** —
   `bundle_dataset_for_publication.py:44` *and* `agent-config.yaml:145`. The second is new
   and affects the verifier-calibration claim.
5. **MAXCONF notation (Q1)** — Alg. 1 line 84 reads as the fused set; code uses max triage
   probability over retriever skills. Already conceded in `response-R2.md`; the rename fixes it.
6. **No LLM calls at decision time (Q1d)** — `03-approach.tex:99-100` says calls are limited
   to gated verification and reformulation; both ran with zero LLM (stub / never invoked).
7. **Reformulation is a no-op (Q1d)** — retrievers never re-query on reformulated text, so
   Alg. 1 line 84 does not change `R`.
8. **Single seed on WoL (Q4d)** — 3 seeds on OB/OTel, 1 on WoL; the 0.963 headline has no
   seed envelope.
9. **Undisclosed conditioning (Q9f)** — n=5,150 not 6,773 because 23.9% of queries lack
   components. `response-R1.md` already commits to disclosing this.
10. **Encoder trains on validation (Q4b)** — combined with untuned, test-split-only
    sensitivity tooling, there is no clean split for threshold selection.

## Two fixes needed in the current drafts

- `response-R2.md:122` promises a sensitivity sweep whose output does not exist in the repo.
- `response-R2.md:123` attributes WoL's always-escalate behavior to scores not reaching
  0.90, when the real cause is that `triage_numeric` never runs at all.
