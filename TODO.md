# TODO — fresh run to close every RQ with no caveats

**Status: 2026-06-13.** Single-pass plan. No re-iteration budgeted. Every
checkbox below is required for the paper to ship without unresolved
caveats. Cross-references:
[`DOCS/docs7/RESEARCH-QUESTIONS.md`](DOCS/docs7/RESEARCH-QUESTIONS.md),
[`DOCS/docs7/RQ-ANSWERS.md`](DOCS/docs7/RQ-ANSWERS.md),
[`DOCS/docs7/AGENTIC-SYSTEM.md`](DOCS/docs7/AGENTIC-SYSTEM.md),
[`DOCS/docs7/IMPROVEMENTS.md`](DOCS/docs7/IMPROVEMENTS.md).

**Compute budget.** ~45–55 hours wall-clock (LM Studio + GPU). Most of
that is the three ~3–8h LM-Studio window-extraction passes (one per
dataset) which can run overnight.

---

## Section 0 — Pre-flight checks (10 minutes)

Verify these before starting. Stops the run from dying 10 hours in
because something was missing.

- [ ] **Cleanup verified.** Re-run the inventory; confirm everything in
  [`RQ-ANSWERS.md` §Run Plan](DOCS/docs7/RQ-ANSWERS.md) "Things to delete"
  is gone and "Things to keep" is intact.
  ```bash
  ls data/derived/global/2026-05-25-dataset-v5-large-global/
  ls data/derived/global/2026-06-09-otel-demo-v1-global/
  ls data/derived/global/2026-06-11-wol-real-global/
  # Expected: NO comparison/, training_runs/, v2_logseq/, embeddings/,
  # v2_kg_extractions_rules/, v2_kg_extractions_windows/, tch-lite-refit/,
  # mode2_*.{json,jsonl}, distractor_curve_*.json.
  ```

- [ ] **Neo4j reachable + empty.** New instance, same credentials.
  ```bash
  PYTHONPATH=src python -c "
  from v2_advanced.shared import Neo4jClient
  with Neo4jClient() as n:
      rows = n.run('MATCH (m) RETURN count(m) AS c')
      print('node count:', rows[0]['c'])
  "
  # Expected: 0
  ```

- [ ] **LM Studio reachable on `http://localhost:1234`** with
  `qwen/qwen3.6-35b-a3b` loaded (grammar-constrained inference required).

- [ ] **Memory-side LLM extractions intact.** These are EXPENSIVE
  to regenerate; verify they survived the cleanup.
  ```bash
  wc -l data/derived/global/2026-05-25-dataset-v5-large-global/v2_kg_extractions/all_extractions.jsonl
  wc -l data/derived/global/2026-06-11-wol-real-global/v2_kg_extractions/all_extractions.jsonl
  # OB expected: ~347 lines. WoL expected: ~2000 lines.
  ls data/derived/global/2026-06-09-otel-demo-v1-global/v2_kg_extractions/ 2>&1
  # OTel Demo expected: file MISSING — we'll generate it in Phase 3.1.
  ```

- [ ] **GitHub `agent-build` branch checked out + clean working tree.**
  ```bash
  git status
  git rev-parse HEAD     # note this hash; it's the "research code freeze" commit
  ```

- [ ] **Disk space.** Expected new artifacts: ~5 GB total
  (BiEncoder weights ×3 + embedding caches ×3 + trace logs + predictions).
  Verify ~10 GB free under `data/`.

---

## Section 1 — Build the 10 missing scripts (1 day of coding)

These don't exist on `agent-build` yet. Build + test + commit BEFORE
starting any data run — otherwise we'd run into them mid-run and stall.

Mark each with the file path + the one-line "what it does".

- [ ] **`src/v2_advanced/tch/run_cascade_full.py`** — single end-to-end
  driver. Fits + runs every retriever (BiEncoder, LogSeq2Vec, Hybrid-RRF
  with both rule + LLM extraction variants, KG-Retrieval) and HGB
  triage. Writes per-window-predictions JSONLs to
  `comparison/v2{a,b,c,c-llm,d}-*` matching the existing OB layout.
  Crucially: records per-skill **wall-time per window** in each JSONL row
  (new field `skill_wall_time_seconds`), needed for B3 + A9.

- [ ] **`src/v2_advanced/tch/run_bm25_baseline.py`** — pure BM25
  pipeline. Writes `comparison/bm25-baseline/per-window-predictions.jsonl`.
  Closes RQ-C4.

- [ ] **`src/v2_advanced/proposal_e_agent/run_on_ood.py`** — invokes
  DiagnosisAgent on the 800 WoL OOD queries from
  `novelty-queries/windows.jsonl`. Writes
  `data/derived/global/<wol>/ood-diagnosis-predictions.jsonl` — the
  agent signal for full L3 novelty (closes A5).

- [ ] **`src/v2_advanced/tch/build_cascade.py`** (extension) — add
  `--fit-l3-learned-novelty` flag. Trains a LogReg over the train-split
  cheap-skill outputs (triage_numeric.score, retrieve_dense.confidence,
  retrieve_hybrid_fusion.triage_score, etc.) to predict `gold_is_novel`.
  Writes `comparison/v2g-final-models/learned-novelty/{model.pkl,
  predictions.jsonl}`. Closes A5 learned signal.

- [ ] **`src/v2_advanced/tch/build_cascade.py`** (extension) — add
  `--gold-relation strong` flag. Uses `window-memory-matchings-strong.jsonl`
  as gold, refits L1 stacker + L3 novelty + L2 composition on strong
  relation. Closes A7 strong-relation.

- [ ] **`scripts/agent/annotate_wol_depth.py`** — adds
  `n_prior_same_project_tickets` field to each row of WoL
  `global-triage-examples.jsonl`. Reads `jira-memory-corpus.jsonl`,
  groups by `wol_project`, computes prior-count per window timestamp.
  Closes B2 (WoL gap).

- [ ] **`scripts/agent/hp_sensitivity.py`** — HP sweep driver. Sweeps
  BiEncoder epochs ∈ {3, 5, 7}, RRF k ∈ {30, 60, 90}, L1 threshold
  ∈ {0.3, 0.5, 0.7}, L3 novelty threshold ∈ {0.3, 0.5, 0.7}. Re-fits
  what needs re-fitting (BiEncoder), reuses cached predictions for the
  rest (RRF/L1/L3 are post-hoc). Reports point + 95% CI per setting +
  monotonicity check ("robust region"). Closes C2.

- [ ] **`scripts/agent/reformulation_recovery.py`** — for each
  gate-firing window (compose_l2 confidence < 0.5), invokes
  `ReformulateQuerySkill` LIVE, then re-runs BiEncoder inference on the
  reformulated query, compares Hit@1 before vs after. Reports recovery
  rate. Closes B4. **Requires the BiEncoder weights to be present on
  disk + a live-inference helper** (`v2_advanced/proposal_a_resplit/
  biencoder_infer.py` — add a one-off-query mode if it doesn't have one).

- [ ] **`scripts/agent/distractor_sweep_corpus_mix.py`** — Level-2
  corpus-mixing distractor sweep. At each ratio R ∈ {10, 25, 50},
  mixes R% of WoL distractors into the 347-ticket memory; re-fits
  BiEncoder on the contaminated corpus; re-runs retrieval; reports
  Hit@K + 95% CI. Closes A4 Level 2.

- [ ] **`scripts/agent/build_cross_corpus_gold.py`** +
  **`scripts/agent/run_cross_corpus_retrieval.py`** — Mode 4. Builds
  a Jaccard symptom-token gold relation between WoL Kafka tickets
  (memory) and OTel Demo Kafka scenario windows (queries); runs
  BiEncoder + Hybrid-RRF retrieval; bootstraps. Closes B5.

- [ ] **`scripts/agent/smoke_ob.py`** / **`smoke_wol.py`** /
  **`smoke_otel_demo.py`** — add `--order-by-incident-time` flag.
  Sorts cases by `(service_name, incident_episode_id, start_time)`
  before running, so the StateLayer's page-suppression rule actually
  sees multi-window same-incident sequences. Closes C7 non-trivially.

- [ ] **Build + test + commit each script as it's written.** Aim for
  one commit per script. Final commit before data runs: a single
  "Phase 0 — fresh-run tooling shipped" commit message that ties
  them together.

- [ ] **Run the full agent test suite** after the new scripts land.
  Should be ~425 tests + new tests for the scripts. Zero failures.
  ```bash
  PYTHONPATH=src python -m unittest discover -s src/agent/tests -t src
  ```

---

## Section 2 — Phase 0: Cleanup verification + manifest regeneration (5 minutes)

- [ ] **Confirm cleanup once more** (already done above; redo for safety).

- [ ] **Regenerate v2-resplit manifest for OB.**
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.make_resplit \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --out triage-split-manifest-v2-resplit.json \
      --train 0.70 --val 0.15 --test 0.15 --seed 42
  ```
  Verify: file present + 1008 windows under "test".

- [ ] **Regenerate v2-resplit manifest for WoL.**
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.make_resplit \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --out triage-split-manifest-v2-resplit.json \
      --train 0.70 --val 0.15 --test 0.15 --seed 42
  ```
  Verify: file present.

- [ ] **OTel Demo manifest already exists** (Phase 2.4 generated it).
  Verify:
  ```bash
  cat data/derived/global/2026-06-09-otel-demo-v1-global/triage-split-manifest-v2-resplit.json | python -c "
  import json, sys
  d = json.load(sys.stdin)
  from collections import Counter
  print(Counter(d['window_assignment'].values()))
  "
  # Expected: ~{train: 1150, validation: 246, test: 247}
  ```

- [ ] **Wipe Neo4j (fresh instance, but confirm zero nodes):**
  ```bash
  PYTHONPATH=src python -c "from v2_advanced.shared import Neo4jClient
  with Neo4jClient() as n:
      rows = n.run('MATCH (m) RETURN count(m) AS c'); print(rows[0]['c'])
  "
  # Expected: 0
  ```

- [ ] **Annotate WoL depth.** (Must happen NOW before Phase 2; cheap.)
  ```bash
  PYTHONPATH=src python scripts/agent/annotate_wol_depth.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global --inplace
  # Verify: spot-check a few rows of global-triage-examples.jsonl —
  # each should now have n_prior_same_project_tickets populated.
  ```

---

## Section 3 — Phase 1: OB end-to-end (~12–15 hours)

Order matters within this phase: Neo4j is loaded with OB entities and
stays loaded for everything in §3.

- [ ] **3.1 Reload Neo4j with OB memory entities** (~20 sec; writes
  GraphMetadata fingerprint).
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --source llm
  ```
  Verify: GraphMetadata node exists with dataset_id matching the dir name.
  ```bash
  PYTHONPATH=src python -c "from agent.integrity import read_graph_metadata
  from v2_advanced.shared import Neo4jClient
  with Neo4jClient() as n: print(read_graph_metadata(n))
  "
  ```

- [ ] **3.2 Symmetric window extraction on OB** (~2 hours LM Studio).
  ```bash
  PYTHONPATH=src python scripts/agent/extract_window_entities.py \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --split test
  ```
  Verify: `v2_kg_extractions_windows/all_extractions.jsonl` exists with
  ~1008 rows (one per test window).

- [ ] **3.3 Cascade full run on OB** (~6–8 h GPU). Writes every
  retriever's predictions JSONL + records per-skill wall-time per window.
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.run_cascade_full \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --persist-skill-wall-times --seed 42
  ```
  Verify: `comparison/{v2a-resplit, v2b-logseq2vec, v2c-hybrid,
  v2c-hybrid-llm, v2d-kg-rulebased}/per-window-predictions.jsonl` all exist.

- [ ] **3.4 BM25 baseline on OB** (~30 min). Closes C4 for OB.
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.run_bm25_baseline \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --out comparison/bm25-baseline
  ```

- [ ] **3.5 DiagnosisAgent on OB test windows** (~4 hours LM Studio).
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_e_agent.run_on_test \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --out comparison/v2e-agent-llm
  ```

- [ ] **3.6 Cascade composition + L1 stacker + L3 learned novelty + L2 RRF**
  (~10 min). Closes A5 learned signal.
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.build_cascade \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --fit-l3-learned-novelty \
      --out comparison/v2g-final-models/final
  ```

- [ ] **3.7 Agent smoke on OB with traces + incident-ordered + verifier**
  (~5 min — predictions cached). Closes A9 per-skill cost, C7
  multi-window suppression.
  ```bash
  PYTHONPATH=src python scripts/agent/smoke_ob.py \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --include-verifier \
      --cache-dir data/skill_cache \
      --trace-root data/agent_traces \
      --order-by-incident-time \
      --output data/agent_runs/ob-smoke.json
  ```

- [ ] **3.8 OB ablation grid + bootstrap** (~10 min). Closes C5 for OB.
  ```bash
  PYTHONPATH=src python scripts/agent/run_ablation.py \
      --dataset ob \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --output data/agent_runs/ob-ablation.json
  PYTHONPATH=src python scripts/agent/bootstrap_headlines.py \
      --reports data/agent_runs/ob-smoke.json \
      --ablation-grids data/agent_runs/ob-ablation.json
  ```

- [ ] **3.9 HP sensitivity on OB** (~2–3 hours, multiple BiEncoder
  refits). Closes C2.
  ```bash
  PYTHONPATH=src python scripts/agent/hp_sensitivity.py \
      --dataset ob \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --biencoder-epochs 3,5,7 --rrf-k 30,60,90 \
      --l1-threshold 0.3,0.5,0.7 --l3-novelty-threshold 0.3,0.5,0.7 \
      --output data/agent_runs/ob-hp-sensitivity.json
  ```

- [ ] **3.10 Reformulation recovery on OB** (~15 min — live BiEncoder
  inference). Closes B4.
  ```bash
  PYTHONPATH=src python scripts/agent/reformulation_recovery.py \
      --dataset ob \
      --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \
      --output data/agent_runs/ob-reformulation-recovery.json
  ```

- [ ] **3.11 Bootstrap all OB headlines + cascade Final**
  ```bash
  PYTHONPATH=src python scripts/agent/bootstrap_predictions.py \
      --predictions \
          data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
          data/derived/global/2026-05-25-dataset-v5-large-global/comparison/bm25-baseline/per-window-predictions.jsonl \
      --paired tch_cascade bm25 \
      --output data/agent_runs/ob-cascade-final-bootstrap.json
  ```

- [ ] **3.12 OB analysis passes (depth, cost, failure categories).**
  ```bash
  PYTHONPATH=src python scripts/agent/depth_scaling.py \
      --predictions data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
      --output data/agent_runs/ob-depth-scaling.json
  PYTHONPATH=src python scripts/agent/cost_summary.py \
      --reports data/agent_runs/ob-smoke.json \
      --traces data/agent_traces/ \
      --output data/agent_runs/ob-cost-summary.json
  PYTHONPATH=src python scripts/agent/failure_categories.py \
      --reports data/agent_runs/ob-smoke.json \
      --output data/agent_runs/ob-failure-categories.json
  ```

- [ ] **3.13 Sanity check — Phase 1 closure.** Verify all of:
  - `data/agent_runs/ob-smoke.json` exists, Hit@5 reported
  - `data/agent_runs/ob-ablation.json` exists, no_numeric_telemetry row present
  - `data/agent_runs/ob-hp-sensitivity.json` exists
  - `data/agent_runs/ob-reformulation-recovery.json` exists
  - `data/agent_traces/` has ~1008 trace files
  - `data/skill_cache/` has populated entries

---

## Section 4 — Phase 2: WoL end-to-end (~16–20 hours)

- [ ] **4.1 Wipe Neo4j + reload with WoL memory entities** (~20 sec).
  ```bash
  # New Neo4j instance OR clear via:
  PYTHONPATH=src python -c "from v2_advanced.shared import Neo4jClient
  with Neo4jClient() as n: n.clear_database()
  "
  PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --source llm
  ```
  Verify GraphMetadata flipped to WoL dataset_id.

- [ ] **4.2 Symmetric window extraction on WoL** (~6 hours LM Studio).
  RUN OVERNIGHT.
  ```bash
  PYTHONPATH=src python scripts/agent/extract_window_entities.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --split test
  ```

- [ ] **4.3 Cascade full run on WoL** (~6–8 h). Same as OB but per the
  WoL `tch-lite-refit` convention; the cascade runner should produce
  the same `comparison/v2{a..d}-*` layout for consistency with OB.
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.run_cascade_full \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --persist-skill-wall-times --seed 42
  ```

- [ ] **4.4 BM25 baseline on WoL.**
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.run_bm25_baseline \
      --global-dir data/derived/global/2026-06-11-wol-real-global
  ```

- [ ] **4.5 DiagnosisAgent on WoL test windows** (~4 h LM Studio).
  Needed for the published Mode 3 §3.9 RQ-A8 comparison + the strong-
  relation comparison.
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_e_agent.run_on_test \
      --global-dir data/derived/global/2026-06-11-wol-real-global
  ```

- [ ] **4.6 DiagnosisAgent on the 800 WoL OOD queries** (~7 h).
  Closes A5 agent signal.
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_e_agent.run_on_ood \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --queries novelty-queries/windows.jsonl
  ```

- [ ] **4.7 Mode 1 distractor sweep (Level 2 — corpus-mixing re-fit)**
  (~3 hours, 3 BiEncoder refits + retrieval). Closes A4.
  ```bash
  PYTHONPATH=src python scripts/agent/distractor_sweep_corpus_mix.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --distractor-pool 300 --ratios 10,25,50 \
      --output data/agent_runs/wol-distractor-level2.json
  ```

- [ ] **4.8 Mode 2 free signal (the 800 OOD queries free-signal precompute).**
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.mode2_free_signal \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --out mode2_per_query.jsonl
  ```

- [ ] **4.9 L3 learned-novelty classifier** (using cheap-skill outputs
  from train split + WoL gold).
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.build_cascade \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --fit-l3-learned-novelty
  ```

- [ ] **4.10 Full L3 novelty evaluation with all 3 signals** (closes A5
  fully).
  ```bash
  PYTHONPATH=src python scripts/agent/novelty_eval.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --agent-signal data/derived/global/2026-06-11-wol-real-global/ood-diagnosis-predictions.jsonl \
      --learned-signal data/derived/global/2026-06-11-wol-real-global/comparison/v2g-final-models/learned-novelty/ood-predictions.jsonl \
      --output data/agent_runs/wol-l3-novelty.json
  ```

- [ ] **4.11 Strong-relation cascade composition on WoL** (closes A7
  strong-relation).
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.build_cascade \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --gold-relation strong \
      --out comparison/v2g-final-models-strong
  ```

- [ ] **4.12 Agent smoke on WoL + ablation + bootstrap** (RQ-A8
  structural skip verified, traces persisted).
  ```bash
  PYTHONPATH=src python scripts/agent/smoke_wol.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --cache-dir data/skill_cache \
      --trace-root data/agent_traces \
      --order-by-incident-time \
      --output data/agent_runs/wol-smoke.json
  PYTHONPATH=src python scripts/agent/run_ablation.py --dataset wol \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --output data/agent_runs/wol-ablation.json
  PYTHONPATH=src python scripts/agent/bootstrap_headlines.py \
      --reports data/agent_runs/wol-smoke.json \
      --ablation-grids data/agent_runs/wol-ablation.json
  ```

- [ ] **4.13 WoL Mode 3 paired bootstrap CIs (5 retrievers).**
  ```bash
  PYTHONPATH=src python scripts/agent/bootstrap_predictions.py \
      --predictions \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2a-resplit/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2c-hybrid/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2b-logseq2vec/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2d-kg-rulebased/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2e-agent-llm/per-window-predictions.jsonl \
      --paired bi_encoder_retrieval hybrid_rrf_retrieval \
      --paired bi_encoder_retrieval diagnosis_agent \
      --output data/agent_runs/wol-mode3-bootstrap.json
  ```

- [ ] **4.14 WoL cascade composition vs best single (coarse + strong).**
  ```bash
  PYTHONPATH=src python scripts/agent/wol_cascade_compose.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --output data/agent_runs/wol-cascade-composition.json
  PYTHONPATH=src python scripts/agent/wol_cascade_compose.py \
      --global-dir data/derived/global/2026-06-11-wol-real-global \
      --gold-relation strong \
      --output data/agent_runs/wol-cascade-composition-strong.json
  ```

- [ ] **4.15 Depth-scaling on WoL** (now possible after annotate_wol_depth).
  ```bash
  PYTHONPATH=src python scripts/agent/depth_scaling.py \
      --predictions data/derived/global/2026-06-11-wol-real-global/comparison/v2a-resplit/per-window-predictions.jsonl \
      --output data/agent_runs/wol-depth-scaling.json
  ```

- [ ] **4.16 WoL cost + failure analyses.**
  ```bash
  PYTHONPATH=src python scripts/agent/cost_summary.py \
      --reports data/agent_runs/wol-smoke.json \
      --traces data/agent_traces/ \
      --output data/agent_runs/wol-cost-summary.json
  PYTHONPATH=src python scripts/agent/failure_categories.py \
      --reports data/agent_runs/wol-smoke.json \
      --output data/agent_runs/wol-failure-categories.json
  ```

- [ ] **4.17 Sanity check — Phase 2 closure.** Verify all 16
  `data/agent_runs/wol-*.json` artifacts exist + WoL traces in
  `data/agent_traces/`.

---

## Section 5 — Phase 3: OTel Demo end-to-end (~10–12 hours) — closes B1

- [ ] **5.1 Memory-side LLM extraction on OTel Demo** (~1 h —
  smaller corpus, ~147 tickets).
  ```bash
  PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global
  ```
  Verify: `v2_kg_extractions/all_extractions.jsonl` written.

- [ ] **5.2 Wipe Neo4j + reload with OTel Demo entities.**
  ```bash
  PYTHONPATH=src python -c "from v2_advanced.shared import Neo4jClient
  with Neo4jClient() as n: n.clear_database()
  "
  PYTHONPATH=src python -m v2_advanced.proposal_d_knowledge_graph.reload_neo4j \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --source llm
  ```

- [ ] **5.3 Symmetric window extraction on OTel Demo** (~3 hours).
  ```bash
  PYTHONPATH=src python scripts/agent/extract_window_entities.py \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --split test
  ```

- [ ] **5.4 Zero-shot cascade on OTel Demo (OB-trained retrievers)**
  (~4 h GPU — inference only, no re-fits).
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.run_cascade_full \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --use-pretrained-from data/derived/global/2026-05-25-dataset-v5-large-global \
      --out-suffix zero-shot --seed 42
  ```

- [ ] **5.5 L1-retrained variant (BiEncoder fit on OTel Demo train)**
  (~6 h GPU).
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.run_cascade_full \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --out-suffix l1-retrained --seed 42
  ```

- [ ] **5.6 BM25 baseline + DiagnosisAgent + cascade composition.**
  ```bash
  PYTHONPATH=src python -m v2_advanced.tch.run_bm25_baseline \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global
  PYTHONPATH=src python -m v2_advanced.proposal_e_agent.run_on_test \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global
  PYTHONPATH=src python -m v2_advanced.tch.build_cascade \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --fit-l3-learned-novelty \
      --out comparison/v2g-final-models/final
  ```

- [ ] **5.7 Agent smoke + ablation + bootstrap + analyses on OTel Demo.**
  ```bash
  PYTHONPATH=src python scripts/agent/smoke_otel_demo.py \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --cache-dir data/skill_cache \
      --trace-root data/agent_traces \
      --order-by-incident-time \
      --output data/agent_runs/otel-smoke.json
  PYTHONPATH=src python scripts/agent/run_ablation.py --dataset otel \
      --global-dir data/derived/global/2026-06-09-otel-demo-v1-global \
      --output data/agent_runs/otel-ablation.json
  PYTHONPATH=src python scripts/agent/bootstrap_headlines.py \
      --reports data/agent_runs/otel-smoke.json \
      --ablation-grids data/agent_runs/otel-ablation.json
  PYTHONPATH=src python scripts/agent/depth_scaling.py \
      --predictions data/derived/global/2026-06-09-otel-demo-v1-global/comparison/v2a-resplit/per-window-predictions.jsonl \
      --output data/agent_runs/otel-depth-scaling.json
  PYTHONPATH=src python scripts/agent/cost_summary.py \
      --reports data/agent_runs/otel-smoke.json \
      --traces data/agent_traces/ \
      --output data/agent_runs/otel-cost-summary.json
  PYTHONPATH=src python scripts/agent/failure_categories.py \
      --reports data/agent_runs/otel-smoke.json \
      --output data/agent_runs/otel-failure-categories.json
  ```

- [ ] **5.8 Sanity check — Phase 3 closure.** Verify all
  `data/agent_runs/otel-*.json` artifacts exist.

---

## Section 6 — Phase 4: Cross-cutting (~5–6 hours)

- [ ] **6.1 Build Mode 4 cross-corpus gold relation** (~1 h).
  ```bash
  PYTHONPATH=src python scripts/agent/build_cross_corpus_gold.py \
      --memory-dataset data/derived/global/2026-06-11-wol-real-global \
      --query-dataset  data/derived/global/2026-06-09-otel-demo-v1-global \
      --project-filter Kafka \
      --output data/derived/cross-corpus-kafka-gold.jsonl
  ```

- [ ] **6.2 Mode 4 retrieval run** (~2–3 h).
  ```bash
  PYTHONPATH=src python scripts/agent/run_cross_corpus_retrieval.py \
      --memory-dataset data/derived/global/2026-06-11-wol-real-global \
      --query-dataset  data/derived/global/2026-06-09-otel-demo-v1-global \
      --gold data/derived/cross-corpus-kafka-gold.jsonl \
      --output data/agent_runs/mode4-cross-corpus-kafka.json
  ```

- [ ] **6.3 Similarity-weighted distractor sweep** (Phase 3.4 already
  shipped — re-run on fresh OB + WoL data).
  ```bash
  PYTHONPATH=src python scripts/agent/run_distractor_sweep.py \
      --cascade-predictions data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
      --triage-examples data/derived/global/2026-05-25-dataset-v5-large-global/global-triage-examples.jsonl \
      --distractors data/derived/global/2026-06-11-wol-real-global/distractors/timeline.jsonl \
      --output data/agent_runs/wol-distractor-sweep.json
  ```

- [ ] **6.4 Bootstrap all final headline tables** (paired CIs everywhere).
  ```bash
  PYTHONPATH=src python scripts/agent/bootstrap_predictions.py \
      --predictions \
          data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/per-window-predictions.jsonl \
          data/derived/global/2026-05-25-dataset-v5-large-global/comparison/bm25-baseline/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2a-resplit/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2c-hybrid/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/v2e-agent-llm/per-window-predictions.jsonl \
          data/derived/global/2026-06-11-wol-real-global/comparison/bm25-baseline/per-window-predictions.jsonl \
          data/derived/global/2026-06-09-otel-demo-v1-global/comparison/v2a-resplit/per-window-predictions.jsonl \
          data/derived/global/2026-06-09-otel-demo-v1-global/comparison/bm25-baseline/per-window-predictions.jsonl \
      --paired tch_cascade bm25 \
      --paired bi_encoder_retrieval hybrid_rrf_retrieval \
      --paired bi_encoder_retrieval diagnosis_agent \
      --output data/agent_runs/all-headlines-bootstrap.json
  ```

---

## Section 7 — Phase 5: Validation + paper-ready artifacts (1 day)

- [ ] **7.1 Re-run the full agent test suite.** Must be green.
  ```bash
  PYTHONPATH=src python -m unittest discover -s src/agent/tests -t src
  ```

- [ ] **7.2 Sanity-table for every RQ** — verify every artifact mentioned
  in `RQ-ANSWERS.md` exists with non-zero content + the number isn't
  obviously wrong (e.g., Hit@5 ∈ [0, 1]).
  ```bash
  # One-liner that prints presence + n_cases for every expected artifact:
  for f in data/agent_runs/*.json; do
      python -c "
  import json, sys
  d = json.load(open(sys.argv[1]))
  print(f'{sys.argv[1]}: keys={sorted(d)[:5]}...')
  " $f
  done
  ```

- [ ] **7.3 Regenerate `DOCS/docs7/RQ-ANSWERS.md`** with the fresh
  numbers. Every "→ Deferred" should now be "✓ Closed". Every CI
  bracket should reflect the new data. The "Tally" at the bottom must
  read: Closed 22 / Partial 0 / Not done 0 / Deferred 0 (or close to it).

- [ ] **7.4 Generate the paper §5 draft tables.** One table per RQ —
  pull point + CI from the bootstrap JSONs.
  ```bash
  PYTHONPATH=src python scripts/agent/build_paper_tables.py \
      --in data/agent_runs/ \
      --out technical-paper/sections/05-results-tables/
  ```
  (This script is a stretch — if time-pressed, copy tables manually
  from the bootstrap JSONs.)

- [ ] **7.5 Final commit.** Tag the commit `rq-closure-v1`.
  ```bash
  git add -A
  git commit -m "fresh-run closure: every RQ answered with no caveats"
  git tag rq-closure-v1
  ```

- [ ] **7.6 Archive data/agent_runs/ + data/agent_traces/ + skill_cache/
  to backup** (gitignored, but irreplaceable).

---

## Section 8 — Known scope limits (NOT caveats, just honest framing)

These are intentional design choices. The fresh run **doesn't try to
remove them** — they're acknowledged in the paper as bounds on the
contribution.

- **B3 cost savings are counterfactual**, not measured against a
  parallel always-on cascade. Standard methodology; the paper should
  say "agent's gating WOULD have saved X seconds of LLM inference per
  window vs the always-on cascade." Concrete numbers come from the
  cascade's recorded per-skill wall-times (step 3.3) × the agent's
  skip-rate (step 3.7).

- **A4 Level 3** (full end-to-end re-train with contaminated corpus +
  re-train the entire retrieval model from scratch) is NOT in this
  run — Level 2 (corpus-mixing re-fit at the BiEncoder layer) is. The
  paper says "Level 2 corpus-mixing"; Level 3 is journal-extension work.

- **C7 multi-window probe** uses OB's `incident_episode_id` grouping
  (4-5 windows per incident). True long-running real-world incidents
  (24h+ outages) aren't in any of our datasets. Acknowledged.

- **OTel Demo zero-shot transfer** assumes OB and OTel Demo are
  "same modality" (microservices); cross-modality (mobile, desktop)
  is out of scope. Per the catalogue.

- **No cascade-side HP grid search** (e.g. transformer hidden dim,
  layer count). C2 covers BiEncoder epochs + RRF k + L1/L3 thresholds
  — the load-bearing parameters per `RQ-ANSWERS.md`.

---

## Section 9 — Checkpoint summary

After all sections complete, verify the closure tally:

| Section | RQs closed in this section |
|---|---|
| §3 OB | A1, A2, A3 reconfirm, A9 (per-skill cost), B2 (OB), C2, C3, C5 (OB), C6 (OB), C7 (OB), C4 (OB BM25) |
| §4 WoL | A4 (Level 2), A5 (full L3), A6 (transfer + symmetric), A7 (coarse + strong), A8 (struct + CI), B2 (WoL), C4 (WoL BM25), C5 (WoL), C6 (WoL), C7 (WoL), reformulation recovery |
| §5 OTel Demo | B1 (zero-shot + L1-retrained), C4 (OTel BM25), C5 (OTel), C6 (OTel) |
| §6 Cross-cutting | B5 (Mode 4), B3 counterfactual savings, identity-aware distractor sweep |
| §7 Validation | All bootstrap CIs, all tables, RQ-ANSWERS.md refresh |

**Target final tally:**
- Closed: A1, A2, A3, A4, A5, A6, A7, A8, A9, B1, B2, B3, B4, B5, B6, C1, C2, C3, C4, C5, C6, C7 = **22 RQs**
- Partial: 0
- Not done: 0
- Deferred: 0

If anything ends up in Partial / Not done after the run, that's the
honest-scope item to be flagged in the paper.

---

## Appendix A — File-by-file deletion confirmation (already done)

Verified 2026-06-13:

```
data/derived/global/2026-05-25-dataset-v5-large-global/:
  ✓ Gone:  comparison/, training_runs/, embeddings/, v2_logseq/,
           v2_kg_extractions_rules/, v2_kg_extractions_windows/,
           triage-split-manifest-v2-resplit.json
  ✓ Kept:  global-triage-examples.jsonl, jira-memory-corpus.jsonl,
           jira-shadow-humanized-v1/v2/v2-distractors/, v2_kg_extractions/,
           triage-feature-columns.json, triage-split-manifest.json,
           dataset-metadata.json, text-leakage-report/, family-coverage.json,
           leakage-canary-summary.json, validate-dataset-run-summary.json,
           global-triage-build-manifest.json, jira-memory-build-manifest.json,
           window-memory-matchings.jsonl

data/derived/global/2026-06-09-otel-demo-v1-global/:
  ✓ Kept:  all inputs intact, v2-resplit manifest present (from Phase 2.4)
  ⚠ Note:  v2_kg_extractions/ does NOT exist on disk yet — will be
           generated in §5.1.

data/derived/global/2026-06-11-wol-real-global/:
  ✓ Gone:  tch-lite-refit/, v2_logseq/, distractor_curve_wol_pool_300.json,
           mode2_novelty_lowerbound.json, mode2_per_query.jsonl,
           triage-split-manifest-v2-resplit.json
  ✓ Kept:  global-triage-examples.jsonl, jira-memory-corpus.jsonl,
           jira-shadow-humanized-v2/, novelty-queries/, distractors/,
           v2_kg_extractions/, window-memory-matchings.jsonl,
           window-memory-matchings-strong.jsonl, dataset-metadata.json,
           source-mapping.csv, triage-feature-columns.json,
           triage-split-manifest.json, gold-relations-debug.json,
           wol-extraction-manifest.json, wol-priority-mapping.json,
           README.md

data/:
  ✓ Gone:  agent_runs/, agent_traces/, skill_cache/, llm_telemetry/,
           neo4j-snapshots/ (was never present), smoke-otel-pilot-global/
  ✓ Kept:  README.md, runs/, otel-demo-runs/, wol/

Neo4j: fresh instance, zero nodes, same credentials.
```

---

## Appendix B — One-line summary

> **Build 10 scripts → cleanup → 3 dataset passes (OB → WoL → OTel Demo,
> serialized on Neo4j) → cross-cutting → validation. ~50 hours
> wall-clock. Every checkbox completed = paper-ready, every RQ
> closed.** Don't skip any step.
