# MVP Evaluation Dataset

This document records the current final lab dataset for ranking-MVP testing.
It is the dataset we should use to test the first internal application version
and to decide which ranker improvements are worth implementing next.

The dataset is intentionally small but complete. It contains repeated controlled
runs from the Google Online Boutique research lab, shadow Jira issues, raw
telemetry exports, derived ranking examples, and cross-run baseline metrics.

## Included Runs

Current final aggregate id:

```text
mvp-final-v1
```

The same run set is also published as the local moving pointer:

```text
data/derived/aggregate/current/
```

Included raw runs:

| Run id | Episodes | Telemetry windows | Shadow Jira issues | Exact-log windows | Trace windows | Validation |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `2026-05-14-research-final-001` | 5 | 30 | 2 | 25 | 30 | 0 errors, 0 warnings |
| `2026-05-14-mvp-eval-002` | 5 | 30 | 2 | 25 | 30 | 0 errors, 0 warnings |
| `2026-05-14-mvp-eval-003` | 5 | 30 | 2 | 25 | 30 | 0 errors, 0 warnings |

Raw tree hashes captured in the aggregate report:

| Run id | Raw tree SHA256 |
| --- | --- |
| `2026-05-14-research-final-001` | `87586a19f948d41d4b992f20d7f68f992dafca2486b8582606afbde638d80d2f` |
| `2026-05-14-mvp-eval-002` | `aed570d5145411654561ec5c6d6fd9ad3c69d08a2c3b64fc54a88fcca04fe0b8` |
| `2026-05-14-mvp-eval-003` | `3a525468f94580072df44cc5560899bd49dc6143cf67b0d94970c9380edddf7b` |

## Dataset Size

The cross-run ranking dataset contains:

| Item | Count |
| --- | ---: |
| Dataset runs | 3 |
| Incident or baseline episodes | 15 |
| Telemetry windows | 90 |
| Shadow Jira issues | 6 |
| Ranking examples | 30 |
| Positive examples | 6 |
| Negative examples | 24 |

Each run currently contains these scenario episodes:

- `baseline-normal-traffic`
- `productcatalog-latency-major`
- `cart-redis-degradation-critical`
- `frontend-cpu-nearmiss`
- `baseline-normal-traffic`

Only the productcatalog latency and cart/Redis degradation scenarios generate
shadow Jira issues. Baseline and near-miss episodes are important negative
candidates.

## Generated Artifacts

Raw evidence lives under:

```text
data/runs/<DATASET_RUN_ID>/
```

Per-run derived ranking files live under:

```text
data/derived/<DATASET_RUN_ID>/
```

Final aggregate files live under:

```text
data/derived/aggregate/mvp-final-v1/
  cross-run-evaluation.json
  cross-run-evaluation.md
  combined-ranking-examples.jsonl
  combined-ranking-examples.csv
  cross-run-candidate-scores.csv
```

The local default aggregate pointer is:

```text
data/derived/aggregate/current/
```

The MVP should use `combined-ranking-examples.jsonl` as the main query-candidate
contract and `cross-run-candidate-scores.csv` for baseline comparison.

## Current Metrics

Metrics from `data/derived/aggregate/mvp-final-v1/cross-run-evaluation.md`:

| Profile | Uses lab-only candidate labels | MRR | Recall@1 | Recall@3 | nDCG@3 |
| --- | --- | ---: | ---: | ---: | ---: |
| `label_aware_baseline` | Yes | 1.0 | 1.0 | 1.0 | 1.0 |
| `raw_telemetry` | No | 0.777778 | 0.666667 | 1.0 | 0.833333 |

Interpretation:

- The label-aware baseline is perfect, which means the joins, labels, and
  generated Jira links are internally consistent.
- The raw telemetry profile finds every correct issue within the top 3.
- The raw telemetry profile is not yet reliable at rank 1, which gives the MVP
  a concrete improvement target.

## Known Ranking Gaps

The current raw telemetry profile misses rank 1 for the productcatalog issue in
two of three runs:

| Query | Correct scenario | Current raw rank |
| --- | --- | ---: |
| `2026-05-14-mvp-eval-002::OBSRV-1001` | `productcatalog-latency-major` | 3 |
| `2026-05-14-mvp-eval-003::OBSRV-1001` | `productcatalog-latency-major` | 3 |

The cart/Redis issue is stable:

| Query family | Correct scenario | Current raw rank |
| --- | --- | ---: |
| `OBSRV-1002` across all runs | `cart-redis-degradation-critical` | 1 |

Primary improvement target:

- Baseline traffic windows can outrank the productcatalog fault because the
  current raw score overweights broad service overlap and activity volume.

Candidate fixes to test next:

- add pre-fault to active-fault deltas for logs, metrics, and trace latency,
- downweight healthy baseline observation windows when query text describes an
  active incident,
- add service-local latency features from Tempo spans and Prometheus histograms,
- add error-rate and saturation deltas instead of raw activity volume only,
- add query expansion for service aliases such as product catalog,
- train a simple logistic or learning-to-rank model on the component features
  and compare it against the deterministic raw profile.

Do not use `label_aware_baseline` for product claims. It is a dataset integrity
check, not a production ranker.

## Reproduction Commands

The commands below recreate the same run plan from a deployed research lab.
Telemetry timing and raw tree hashes will change if the runs are recollected.
Use the retained `data/runs/` folders above when an exact benchmark snapshot is
required.

Collect the three raw runs:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-run.ps1 `
  -DatasetRunId "2026-05-14-research-final-001" `
  -Quick `
  -ForceNewRun

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-run.ps1 `
  -DatasetRunId "2026-05-14-mvp-eval-002" `
  -Quick `
  -ForceNewRun

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\collect-dataset-run.ps1 `
  -DatasetRunId "2026-05-14-mvp-eval-003" `
  -Quick `
  -ForceNewRun
```

Build per-run derived ranking artifacts:

```powershell
foreach ($runId in @(
  "2026-05-14-research-final-001",
  "2026-05-14-mvp-eval-002",
  "2026-05-14-mvp-eval-003"
)) {
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-ranking-dataset.ps1 `
    -DatasetRunId $runId `
    -Force
}
```

Build the fixed final aggregate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-cross-run-evaluation.ps1 `
  -AggregateId "mvp-final-v1" `
  -DatasetRunId "2026-05-14-research-final-001,2026-05-14-mvp-eval-002,2026-05-14-mvp-eval-003" `
  -Force
```

Update the local current aggregate pointer:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\build-cross-run-evaluation.ps1 `
  -AggregateId "current" `
  -DatasetRunId "2026-05-14-research-final-001,2026-05-14-mvp-eval-002,2026-05-14-mvp-eval-003" `
  -Force
```

## MVP Acceptance Gates

For the first MVP test, use these gates:

- Load all 30 ranking examples without schema errors.
- Treat query ids as `<DATASET_RUN_ID>::<JIRA_ISSUE_KEY>`.
- Exclude lab-only candidate labels from the production ranking path.
- Match or beat the raw telemetry baseline.
- Preserve Recall@3 at 1.0.
- Improve raw telemetry Recall@1 above 0.666667 without regressing the
  cart/Redis rank-1 behavior.

## Caveats

This is a research-appropriate MVP benchmark, not a statistical production
benchmark. It has repeated runs and real telemetry exports, but it is still
small, same-day, same-application, and uses generated shadow Jira issues.

Before making external claims, add more days, more traffic shapes, more fault
types, deploy-version changes, and noisier non-incident windows.
