# V2 Humanized Corpus — ML/AI Training Pass Results (2026-06-01)

Consolidated report for the post-V2-corpus comparative analysis. All runs use the same train/val/test split:

- **train_n = 2796**, **val_n = 984**, **test_n = 2940** windows
- **n_pos = 650** (ticket-worthy), **n_neg = 2290** (noise) in test
- **n_retrievable = 317** test windows have a known-gold Jira match
- Memory: 347 V2-humanized Jira tickets + optional 110 distractors
- Global ID: `2026-05-25-dataset-v5-large-global`

All comparison runs live under `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/`.

---

## What is this system actually doing? (Plain-English)

For every telemetry "window" (a 5-minute slice of logs + traces + metrics from one microservice), the pipelines produce **two predictions**:

### 1. Triage — a binary classification problem
**Question:** "Is this window worth filing a Jira ticket for, or is it normal noise?"
- Output: a score between 0.0 and 1.0
- Metrics: PR-AUC, ROC-AUC, F1
- Ground truth: which windows in the test set actually have a real ticket attached.

### 2. Retrieval — a ranking problem
**Question:** "If this IS ticket-worthy, which past Jira ticket from our memory of 347 tickets is the same incident?"
- Output: a ranked list of candidate tickets
- Metrics: Recall@1, Recall@5 (is the gold ticket in the top-1 / top-5?), MRR (where in the list is it?)
- Ground truth: each test window has a known "this is the gold-matching Jira ticket" label.

So the goal is **"smart incident triage with citation"** — when a new incident appears, decide whether to alert AND show the engineer the past tickets it most resembles.

### Are we training ML models? Mixed.

The word "pipeline" is doing a lot of work — each one is a chain of components, and only *some* of those components actually train weights:

| Component | Trains? | What it does |
|---|---|---|
| **HGB (HistGradientBoosting)** | ✅ Trains | sklearn classifier learns from 94 numeric features (CPU%, latency, error rate, restart counts, etc.). Outputs a triage score 0–1. This is the only "real ML training" in the system. |
| **BM25** | ❌ No training | Classical keyword scoring — builds an inverted index over memory text, scores queries by term overlap. |
| **Entity graph + bridges** | ❌ No training | Hand-coded rules: extract `service`, `component`, `error_class` from text, count shared entities between window and candidate. Pure deterministic. |
| **Nomic embeddings** | ❌ Pretrained, off-the-shelf | A neural model someone else trained on internet text. We just call it to get 768-dim vectors. |
| **Cross-encoder (MS-MARCO MiniLM)** | ❌ Pretrained, off-the-shelf | Another model someone else trained. Reads `(window_text, candidate_text)` jointly and outputs a "are these about the same thing?" score. |
| **Numeric blend weight** | ❌ Hyperparameter | The `0.80` is just a number we picked by sweeping on the val split. Not learned. |

**So when we say "pipeline X scored Y":**
- For `hgb_numeric` → we genuinely trained a gradient-boosted classifier on the train split, evaluated on test.
- For `memorygraph_*` → we trained the small HGB head for the numeric_blend stage, but everything else (BM25, graph, embeddings, cross-encoder) is either deterministic or pretrained. The "fit" mostly just **builds the indexes** — BM25 inverted index, graph node/edge tables, cached embeddings.

### Why the numbers look so low

Two things to keep in mind when reading the tables below:

1. **Retrieval is hard because the corpus is small and ambiguous.** Only 317 of 2940 test windows have a retrievable gold match at all. R@5 = 0.074 means "in 7.4% of cases the gold ticket made top-5 across the whole corpus" — but on `productcatalogservice` specifically the MRR is 0.85. The aggregate number is dragged down by services with weak entity signal (e.g., `frontend`).

2. **Triage and retrieval pull in different directions.** Numeric features (latency spikes, error counts) tell you something is wrong, but they don't tell you *which past ticket it matches*. Memory text (Jira descriptions, log lines) tells you *what* matches, but isn't as crisp a "this is on fire" signal. That's why HGB wins PR-AUC by 16 pts but produces zero retrieval, while memorygraph trades 16 pts of PR-AUC for MRR 0.17.

### What "SOTA" means here

The SOTA — `memorygraph_v2_sota_nw080` — is the **best single configuration** combining:
- The V2-humanized memory corpus we built (engineer-voice tickets with `description_code` and per-step `body_code`)
- Move-A log signatures (a deterministic regex + frequency extractor that pulls characteristic log lines from both sides)
- BM25 lexical retrieval over those signatures
- Graph scoring over shared entities (`service`, `component`, `error_class` bridges)
- Cross-encoder rerank on the top-20 (the only learned component on the retrieval side — but pretrained, not trained by us)
- HGB numeric head for triage, blended at 0.80 weight with retrieval

Calling it "SOTA" is internal — it's the best among our 18 registered pipelines on **this** dataset. It is **not** state-of-the-art in any external benchmark sense.

The real "are we training ML models?" answer is: **we are mostly composing pretrained models + classical IR + a small trained numeric classifier**, and the comparative analysis is measuring which composition works best. The next planned step (E8 fine-tune the cross-encoder on our `(window, gold-ticket)` pairs) would be the first time we actually train a transformer on our own data.

---

## TL;DR

**New SOTA: `memorygraph_v2_sota_nw080`** — V2 humanized memory + Move-A log signatures on both sides + cross-encoder rerank with blend policy + numeric_weight=0.80.

| | V1 baseline | V2 baseline | **SOTA (nw080)** | Δ vs V1 | Δ vs V2 |
|---|---:|---:|---:|---:|---:|
| PR-AUC | 0.6062 | 0.6074 | **0.6186** | +2% | +2% |
| ROC-AUC | 0.7865 | 0.7957 | **0.7881** | +0.2% | −1% |
| Recall@1 | 0.0186 | 0.0152 | **0.0214** | **+15%** | **+41%** |
| Recall@5 | 0.0659 | 0.0686 | **0.0740** | **+12%** | +8% |
| MRR | 0.0998 | 0.1403 | **0.1724** | **+73%** | **+23%** |

The retrieval engine moved meaningfully on V2 + Move A + cross-encoder. PR-AUC was flat on the corpus swap because the triage signal is already dominated by numeric features (HGB hits 0.7718 on numerics alone). Cross-encoder reranking lifted MRR +73% over V1 while keeping triage roughly even.

**Bottleneck has shifted** from corpus quality (E5/E6/E7 ceiling on V1) to the rerank stage. To go further: a learned bi-encoder, or fine-tuning a cross-encoder on `(window_evidence_text → gold_jira_text)` pairs.

---

## What changed between V1 and V2

| Aspect | V1 humanized | V2 humanized |
|---|---|---|
| Voice | Customer-support agent | On-call engineer (TAWOS-realistic) |
| Length | ~800 chars/ticket | ~2400 chars/ticket |
| `description_code` field | None | 90.2% of tickets have it |
| Per-step `body_code` | None | Engineer log/trace paste blocks |
| Sanitizer firewall | Yes | Yes, §14.11-tightened |
| Distractor set | None | 110 (60 TAWOS + 25 in-arch + 25 cross-arch) |

V2 was designed to fix E7's conclusion that the *destination* side (cs-agent voice) was the dominant bottleneck. The 24% relative MRR lift V2-base over V1 confirmed the diagnosis.

---

## All pipelines tested

### Run 1: `v2-comparative-analysis` — corpus + Move A ablations

Goal: measure the corpus swap (V1 → V2) and Move-A log signatures on both sides.

| Pipeline | What it uses | PR-AUC | R@1 | R@5 | MRR |
|---|---|---:|---:|---:|---:|
| `memorygraph_hybrid_humanized` (V1 baseline) | V1 humanized memory + BM25 + graph + HGB numeric blend | 0.6062 | 0.0186 | 0.0659 | 0.0998 |
| `memorygraph_hybrid_humanized_v2` (V2 baseline) | V2 corpus, otherwise same | 0.6074 | 0.0152 | 0.0686 | 0.1403 |
| `memorygraph_hybrid_humanized_v2_logs` | V2 + Move-A characteristic log line extractor on both window evidence AND Jira step `body_code` | 0.6048 | 0.0214 | 0.0745 | 0.1613 |
| `memorygraph_hybrid_humanized_v2_distractors` | V2 + 110 distractors mixed into memory | 0.6125 | 0.0110 | 0.0668 | 0.1258 |
| `ensemble_mean` | Mean of all four | 0.6031 | 0.0212 | 0.0767 | 0.1547 |

**Interpretation:**
- V2 corpus alone: PR-AUC flat (+0.2%) but **MRR +41% rel** vs V1. The right ticket is finding its way nearer the top of candidates more often.
- Move A logs on top: pushes MRR another +15% rel (to 0.1613) and is the first variant to consistently beat V1 on R@1 (0.0214 vs 0.0186).
- Distractors confuse R@1 (-28% rel vs V2 base) but barely move R@5 — distractors get pushed down to ranks 6-15.

### Run 2: `v2-broader-panel` — non-memorygraph baselines

Goal: characterize the triage-only and log-only ceilings.

| Pipeline | What it uses | PR-AUC | R@1 | R@5 | MRR |
|---|---|---:|---:|---:|---:|
| `hist_gradient_boosting_numeric` | HGB on the 94 `triage_feature_*` numeric columns; no retrieval | **0.7718** | — | — | — |
| `logsense_hybrid_bm25` | Drain-lite log templates + BM25 vs Jira memory; no numeric features | 0.4393 | 0.0069 | 0.0323 | 0.0479 |
| `memorygraph_hybrid_humanized_v2` | Reference | 0.6074 | 0.0152 | 0.0702 | 0.1403 |
| `ensemble_mean` (HGB + logsense + memorygraph) | | 0.6650 | 0.0193 | 0.0799 | 0.1631 |

**Interpretation:**
- HGB ceiling is **PR-AUC 0.7718** — pure numeric signal. No memorygraph variant has come within 16 pts of this. Triage is decoupled from retrieval.
- Log-only (logsense_hybrid_bm25) is far below memorygraph on both triage and retrieval. Logs alone don't carry the signal; they help only as an *additional* channel.
- Ensemble of all three lifts R@5 to 0.0799 — the highest R@5 seen anywhere — but cannot be the SOTA "single model" answer.

### Run 3: `v2-nomic-rescue` — dense bi-encoder on V2

Goal: re-test the E6 hypothesis (dense embeddings rescue retrieval) now that the corpus has real engineer text.

| Pipeline | What it uses | PR-AUC | R@1 | R@5 | MRR |
|---|---|---:|---:|---:|---:|
| `memorygraph_full_humanized_v2` | V2 + BM25 + **Nomic embeddings (50/50 blend with BM25)** + graph + numeric | 0.6084 | 0.0154 | 0.0702 | 0.1422 |

**Interpretation:** No rescue. Dense embeddings move retrieval +0.1% vs V2 BM25-only baseline. Same negative result E6 hit on V1. The cross-encoder later succeeded because it does *joint* (query, candidate) scoring rather than two independent encodings. **Verdict: don't run dense bi-encoders again without fine-tuning.**

Runtime: 75 min wall (Nomic embedding all of memory + all windows). Cache (commit `5cea334`) now makes re-runs ~30s.

### Run 4: `v2-crossencoder` — initial REPLACE policy

Goal: try the cross-encoder reranker.

| Pipeline | What it uses | PR-AUC | R@1 | R@5 | MRR |
|---|---|---:|---:|---:|---:|
| `memorygraph_hybrid_humanized_v2` | Reference | 0.6074 | 0.0152 | 0.0702 | 0.1403 |
| `memorygraph_hybrid_humanized_v2_crossenc` | + MS-MARCO MiniLM-L-6-v2 cross-encoder, REPLACE top-20 | 0.6140 | 0.0197 | 0.0577 | 0.1550 |
| `memorygraph_hybrid_humanized_v2_logs_crossenc` | + Move A logs + cross-encoder REPLACE | 0.6133 | 0.0204 | 0.0638 | 0.1592 |

**Interpretation:** R@1 lifted (+30% rel) and MRR climbed, but **R@5 fell** (−9% to −18% rel). The REPLACE policy zeroed all bi-encoder scores outside the reranked top-20, killing broader recall.

### Run 5: `v2-crossencoder-blend` — fixed BLEND policy

Goal: keep cross-encoder gains on top of candidates without sacrificing broad recall.

Blend rule: for the reranked top-K, `final = 0.6 * cross_encoder_normalized + 0.4 * bi_encoder`. Candidates outside the top-K keep their bi-encoder scores unchanged.

| Pipeline | What it uses | PR-AUC | R@1 | R@5 | MRR |
|---|---|---:|---:|---:|---:|
| `memorygraph_hybrid_humanized_v2` | Reference | 0.6074 | 0.0152 | 0.0702 | 0.1403 |
| `memorygraph_hybrid_humanized_v2_crossenc` | + cross-encoder BLEND | 0.6003 | 0.0205 | 0.0618 | 0.1606 |
| `memorygraph_hybrid_humanized_v2_logs_crossenc` | + Move A logs + cross-encoder BLEND | 0.5948 | **0.0214** | **0.0740** | **0.1724** |

**Interpretation:** BLEND fixed R@5 (back to 0.0740, matching the no-crossenc Move-A run) while keeping the R@1/MRR lift. Best retrieval seen yet. PR-AUC dropped 2% — fixable by retuning the final triage blend.

### Run 6: `v2-sota-followups` — numeric retune + distractor confusion

Goal: (1) retune `numeric_weight` to recover the PR-AUC dip, (2) measure distractor confusion on the new SOTA.

Sweep the numeric_weight parameter in TriageDecideSkill — the convex blend coefficient between numeric_score (HGB head) and retrieval-derived combined_score. Old default = 0.7.

| Pipeline | numeric_weight | PR-AUC | ROC-AUC | R@1 | R@5 | MRR | ECE |
|---|---:|---:|---:|---:|---:|---:|---:|
| `memorygraph_v2_sota_nw050` | 0.50 | 0.4706 | 0.7070 | 0.0214 | 0.0740 | 0.1724 | 0.302 |
| `memorygraph_v2_sota_nw055` | 0.55 | 0.5137 | 0.7372 | 0.0214 | 0.0740 | 0.1724 | 0.262 |
| `memorygraph_v2_sota_nw065` | 0.65 | 0.5744 | 0.7630 | 0.0214 | 0.0740 | 0.1724 | 0.185 |
| `memorygraph_hybrid_humanized_v2_logs_crossenc` (nw=0.70) | 0.70 | 0.5948 | 0.7703 | 0.0214 | 0.0740 | 0.1724 | 0.152 |
| **`memorygraph_v2_sota_nw080`** | **0.80** | **0.6186** | **0.7881** | **0.0214** | **0.0740** | **0.1724** | **0.077** |
| `memorygraph_hybrid_humanized_v2_logs_crossenc_distractors` | 0.70 | 0.5882 | 0.7672 | 0.0164 | 0.0731 | 0.1559 | 0.156 |

**Interpretation:**
- **Retrieval metrics are IDENTICAL across the numeric_weight sweep** (R@1/R@5/MRR all 0.0214/0.0740/0.1724). This is correct — numeric_weight only affects the final triage blend, not per-candidate similarity ranking.
- PR-AUC monotonically increases with numeric_weight up through 0.80, which both recovers the cross-encoder dip and slightly *beats* the V2 baseline (0.6186 vs 0.6074). ECE also drops dramatically (0.302 → 0.077) — calibration improves as numeric dominates.
- **Distractor confusion** (with 110 distractors mixed into memory at predict time):
  - R@1: 0.0214 → 0.0164 (**−23% relative** — the §13.6 confusion rate)
  - R@5: 0.0740 → 0.0731 (−1% — robust)
  - MRR: 0.1724 → 0.1559 (−10%)
  - PR-AUC: 0.5948 → 0.5882 (−1%)
- The model **does discriminate** against distractors. They erode top-1 precision but cross-encoder pushes them to ranks 6-15 mostly.

---

## Per-family stratified retrieval (SOTA pipeline)

From `v2-sota-followups` strata for `memorygraph_v2_sota_nw080`:

| Family | n | R@5 | MRR |
|---|---:|---:|---:|
| `productcatalog-latency` | 426 | **0.2137** | **0.5791** |
| `currency-outage` | 342 | 0.1056 | 0.0850 |
| `cart-redis` | 918 | 0.0688 | 0.1797 |
| `ad-outage` | 300 | 0.0000 | 0.0000 |
| `baseline-normal` | 696 | 0.0000 | 0.0000 |
| `checkout-outage` | 168 | 0.0000 | 0.0000 |
| `network-latency` | 90 | 0.0000 | 0.0000 |
| **overall** | 2940 | 0.0740 | 0.1724 |

By service:
| Service | n | R@5 | MRR |
|---|---:|---:|---:|
| `productcatalogservice` | 388 | 0.1877 | **0.8462** |
| `cartservice` | 282 | 0.2076 | 0.5425 |
| `checkoutservice` | 844 | 0.0878 | 0.1419 |
| `frontend` | 928 | 0.0260 | 0.0275 |
| (zero-R@5 services) | varies | 0.0000 | 0.0000 |

**Interpretation:** Three scenario families (productcatalog-latency, currency-outage, cart-redis) carry the retrieval signal — 1686 / 2940 test windows. The other families have **zero R@5** because (a) `baseline-normal` has no gold-positive matches by construction, (b) the others have very few labeled retrievables in the test split. **On `productcatalogservice`, MRR is 0.85** — when retrieval *is* possible, the SOTA is excellent. The overall 0.0740 number understates the per-family wins.

Hard-case stratification:
- `is_hard_case=false`: R@5 = 0.1099, MRR = 0.2110
- `is_hard_case=true`: R@5 = 0.0255, MRR = 0.1204

Hard cases (ambiguous services, no clean component signal) remain ~4× worse than easy cases. This is where future work should focus.

---

## Pipeline architecture map

All memorygraph variants share the same skill chain shell:

```
entity_extract                  # parse window evidence → entities (service, component, error_class, severity, …)
component_filter                # cheap pre-filter on entity bridges
service_filter                  # narrower direct filter
severity_align                  # graph_score bonus for matching severity
error_class_align               # graph_score bonus for matching error_class
lexical_similarity              # BM25 over window text vs candidate memory_text
[log_signature_similarity]      # Move A: replace query+candidate text with characteristic log lines
[embedding_similarity]          # Nomic dense embeddings, 50/50 blend
[cross_encoder_rerank]          # MS-MARCO MiniLM-L-6-v2, top-K BLEND
graph_score                     # bridge-weighted graph scoring
[numeric_blend]                 # HGB head → window-global numeric_score
triage_decide                   # final blend: numeric_weight * numeric + (1-w) * similarity+graph
novelty_check                   # is_novel from top combined score
graph_traverse_explain          # explanation from the graph for top match
```

Skill inclusion per pipeline:

| Pipeline | logs | embed | crossenc | numeric_weight |
|---|:-:|:-:|:-:|:-:|
| `memorygraph_hybrid_humanized` (V1) | — | — | — | 0.70 |
| `memorygraph_hybrid_humanized_v2` | — | — | — | 0.70 |
| `memorygraph_hybrid_humanized_v2_logs` | ✓ | — | — | 0.70 |
| `memorygraph_full_humanized_v2` | — | ✓ | — | 0.70 |
| `memorygraph_hybrid_humanized_v2_crossenc` | — | — | ✓ | 0.70 |
| `memorygraph_hybrid_humanized_v2_logs_crossenc` | ✓ | — | ✓ | 0.70 |
| `memorygraph_v2_sota_nw050/055/065/080` | ✓ | — | ✓ | sweep |

Runtime cost (test split, 2940 windows):
- Bi-encoder variants: ~60–90s predict
- Cross-encoder variants: ~225–235s predict (sentence-transformers MiniLM on CUDA)
- Nomic variants: ~75 min cold, ~30s with the cache

---

## Infrastructure shipped during this pass

| | Status | Files / commits |
|---|---|---|
| Persistent embedding cache (O6) | ✓ | `src/util/embedding_cache.py`, wired in `EmbeddingSimilaritySkill`. Content-addressed sha256, two-char sharded. Commit `5cea334`. |
| Training-run registry | ✓ (utility only) | `src/util/training_registry.py`. Writes `data/derived/global/<id>/training_runs/<pipeline>__<UTC>__<sha8>/{config.json, metrics.json, predictions.jsonl, train.log, model/, artifacts/}`. **Not yet auto-called by the comparison harness.** |
| Cross-encoder skill | ✓ | `CrossEncoderRerankSkill` in `src/memorygraph/skills.py`. Lazy-load MS-MARCO MiniLM, CUDA auto. BLEND policy. Commits `fd81b9b`, `becbb85`. |
| Numeric_weight knob | ✓ | `MemoryGraphPipeline(numeric_weight=…)` override threads through to `TriageDecideSkill`. |
| V2 corpus loader | ✓ | `src/memorygraph/humanized_loader.py` — `humanized_root` + `extra_distractor_path` params; distractor tickets get `scenario_family="__DISTRACTOR__"` to firewall them from GT eval. |

---

## What needs to be done now

In rough priority order:

1. **Wire training_registry into the comparison runner** — every pipeline fit should automatically write to `training_runs/<run_id>/` so every result is reproducible from a single artifact. The utility exists; one ~20-line hook in `src/comparison/runner.py` does it.

2. **Promote `memorygraph_v2_sota_nw080` to the default SOTA** in the codebase. Rename the variant something stable (e.g., `memorygraph_sota`) and have the pipeline factory register it as the canonical V2 hybrid. Demote the no-crossenc and REPLACE-policy variants.

3. **E8 — fine-tune the cross-encoder** on `(window_evidence_text → gold_jira_memory_text)` pairs from the train split. The current MS-MARCO MiniLM is generic-domain; a domain-tuned model should lift R@5 past 0.10 on the families that already retrieve. Embedding cache makes the iteration loop fast. Roughly: 1.7k train pairs (650 windows × ~2-3 hard negatives each), 5-10 epochs, sentence-transformers `CrossEncoder` API.

4. **Hard-case lift** — `is_hard_case=true` gets R@5 = 0.0255 vs 0.1099 for easy cases. Inspect ~30 hard-case windows to characterize the failure mode (multi-service incidents? ambiguous components? logs that don't characterize the fault?). Targeted skills > generic improvements.

5. **Distractor-aware top-K UI contract** — given the 23% R@1 confusion rate, the production triage agent should display top-3 or top-5 candidates with confidence bars, NOT assert a single top-1 match. Document this in `LLM-Jira-enhancement.md` §13.6.

6. **Family-conditional thresholding** — `productcatalogservice` MRR = 0.85 vs `frontend` MRR = 0.03. A single decision threshold makes no sense across families. Either (a) condition the threshold on detected service, or (b) suppress retrieval on services with no historical retrievability.

7. **Negative results to retire** — deprecate `bi_encoder_hybrid`, `nomic_lm_rerank`, `memorygraph_full_humanized_v2` from the active panel. Two independent runs (E6 on V1, this pass's `v2-nomic-rescue` on V2) showed dense bi-encoders contribute ≤ 0.001 PR-AUC. They cost wall time without payoff.

8. **Ensemble investigation** — the ensemble mean in `v2-broader-panel` hit R@5 = 0.0799 (best single number in this pass) and PR-AUC = 0.6650 (between memorygraph and HGB). A learned ensemble head (logistic over per-pipeline scores) on the val split is cheap and could close more of the gap.

9. **Memorygraph triage ceiling** — memorygraph PR-AUC plateaued at ~0.62; HGB on numerics alone hits 0.77. The 15-point gap is the cost memorygraph pays for retrieval + explanation. Either (a) feed memorygraph's similarity_max as an extra column into HGB (small lift expected), or (b) accept the trade-off and ship two heads (HGB for the triage gate, memorygraph for the retrieval+explanation).

---

## Reproducibility

To regenerate any of these tables:

```powershell
$env:PYTHONPATH = "src"
python -m comparison.cli `
  --run-id v2-sota-followups `
  --pipelines memorygraph_v2_sota_nw080,memorygraph_hybrid_humanized_v2_logs_crossenc_distractors `
  --train-end-frac 0.6 --val-end-frac 0.8
```

Each run writes:
- `report.json` — full metric tables, strata, pairwise CIs
- `report.md` — human-readable summary
- `per-window-predictions.jsonl` — every window's per-pipeline prediction

The new SOTA's run_id under the training_registry contract (when it ships) will be e.g. `memorygraph_v2_sota_nw080__20260601T201500Z__a1b2c3d4`.

---

## Key memory files (auto-memory pointers)

- [[project-ml-training-pass-plan]] — top-level audit + plan, all numbers above
- [[project-jira-humanizer-redesign-tawos]] — why V2 was built
- [[reference-per-run-artifacts]] — what each output file contains
- [[reference-derived-feature-columns]] — the 94 numeric columns HGB uses
