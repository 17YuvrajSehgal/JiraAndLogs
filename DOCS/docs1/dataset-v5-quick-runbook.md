# Dataset v5 Quick — Local Laptop Collection Runbook

**Goal:** collect a 16-run diversity-preserving companion to v5-large on the
local Windows kind cluster (`kind-jira-telemetry-lab`) in ~6–8 hours, so ML
model bring-up can start while the GCP VM continues the full v5-large
collection.

**Corpus manifest:** `deploy/research-lab/corpora/dataset-v5-quick.json`
(8 plans, 22 families, ~470 windows, ~24 orphan ticket-worthy windows).

**Critical:** Online Boutique pods MUST run the M0–M5 instrumented images
(`v5.0.0-otel-pilot*`), NOT upstream `:v0.10.5`. The local Docker and kind
containerd are currently empty of pilot images, so step 3 below is mandatory.

---

## 0. Free up RAM (kind died with exit 137 last session)

This laptop has 15.34 GiB total RAM. The full stack (10 microservices + 6
observability components + kind nodes + Docker build peak) will run ~10–13
GiB. Stop anything non-essential first.

```powershell
# Stop the bakku-quant compose stack (~770 MiB) and any other dev containers
docker stop bakku-quant-web-1 bakku-quant-api-1 bakku-quant-postgres-1 `
            bakku-quant-redis-1 bakku-quant-minio-1
# Close browser tabs / IDE windows / electron apps before launching collection.
```

Optional but recommended: raise Docker Desktop's memory limit (`Settings →
Resources → Memory`) to at least **12 GiB** if it isn't already.

---

## 1. Verify kind cluster + observability

The cluster came back from restart with namespaces intact, but pods are
recycling. Wait until everything is Ready before proceeding.

```powershell
Set-Location C:\workplace\JiraAndLogs
kubectl config use-context kind-jira-telemetry-lab
kubectl get nodes
# Expect: 3 nodes Ready.

kubectl wait --for=condition=Ready pods --all -n observability --timeout=600s
kubectl get pods -n observability
# Expect: all pods Running 2/2 or 1/1 (loki-canary, loki-gateway, kube-state-metrics
# took the longest last time).
```

If observability got into a broken state, reinstall from scratch:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\install-observability.ps1
kubectl wait --for=condition=Ready pods --all -n observability --timeout=900s
kubectl apply -f deploy\research-lab\observability\online-boutique-servicemonitor.yaml
```

---

## 2. Build the M0–M5 images locally (~20–30 min, MANDATORY)

Build context is `microservices-demo-google/src/` for nine of the ten
services — needed because each Dockerfile copies sibling `_shared-<lang>/`
deps. **adservice is the exception:** it has no sibling shared lib (uses
the OTel Java agent) and its Dockerfile expects `gradle/` relative to its
own directory, so it must be built from `microservices-demo-google/src/adservice/`.

```powershell
Set-Location C:\workplace\JiraAndLogs\microservices-demo-google\src

docker build -t cartservice:v5.0.0-otel-pilot3 -f cartservice/src/Dockerfile .
docker build -t paymentservice:v5.0.0-otel-pilot2 -f paymentservice/Dockerfile .
docker build -t currencyservice:v5.0.0-otel-pilot2 -f currencyservice/Dockerfile .
docker build -t recommendationservice:v5.0.0-otel-pilot2 -f recommendationservice/Dockerfile .
docker build -t emailservice:v5.0.0-otel-pilot4 -f emailservice/Dockerfile .
docker build -t frontend:v5.0.0-otel-pilot -f frontend/Dockerfile .
docker build -t checkoutservice:v5.0.0-otel-pilot -f checkoutservice/Dockerfile .
docker build -t productcatalogservice:v5.0.0-otel-pilot -f productcatalogservice/Dockerfile .
docker build -t shippingservice:v5.0.0-otel-pilot -f shippingservice/Dockerfile .

# adservice — build from its own directory, NOT from src/
Set-Location C:\workplace\JiraAndLogs\microservices-demo-google\src\adservice
docker build -t adservice:v5.0.0-otel-pilot -f Dockerfile .

Set-Location C:\workplace\JiraAndLogs
```

Verify all 10 host-Docker tags exist:

```powershell
docker images --format "{{.Repository}}:{{.Tag}}" | Select-String "otel-pilot"
# Expect 10 lines.
```

---

## 3. Load images into kind containerd (~5–8 min)

```powershell
$imgs = @(
  "cartservice:v5.0.0-otel-pilot3",
  "paymentservice:v5.0.0-otel-pilot2",
  "currencyservice:v5.0.0-otel-pilot2",
  "recommendationservice:v5.0.0-otel-pilot2",
  "emailservice:v5.0.0-otel-pilot4",
  "frontend:v5.0.0-otel-pilot",
  "checkoutservice:v5.0.0-otel-pilot",
  "productcatalogservice:v5.0.0-otel-pilot",
  "shippingservice:v5.0.0-otel-pilot",
  "adservice:v5.0.0-otel-pilot"
)
foreach ($img in $imgs) {
  kind load docker-image $img --name jira-telemetry-lab
}
```

Verify the cluster sees all 10:

```powershell
docker exec jira-telemetry-lab-worker crictl images | Select-String "otel-pilot"
# Expect 10 lines.
```

---

## 4. Deploy Online Boutique with the M0–M5 image pins

The kustomize overlay already pins all 10 tags (`grep -c v5.0.0-otel-pilot
deploy/research-lab/online-boutique/kustomization.yaml` → 13 matches
including comments). Apply:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts\research-lab\apply-online-boutique.ps1
kubectl wait --for=condition=Ready pods --all -n online-boutique-research --timeout=900s
```

**Critical verification — confirm pods are running M0–M5 images, NOT v0.10.5:**

```powershell
kubectl -n online-boutique-research get deploy -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.template.spec.containers[0].image}{"\n"}{end}'
# Expect:
#   cartservice: cartservice:v5.0.0-otel-pilot3
#   paymentservice: paymentservice:v5.0.0-otel-pilot2
#   ... etc.
#   loadgenerator: us-central1-docker.pkg.dev/.../loadgenerator:v0.10.5 (intentionally upstream)
#   redis-cart: redis:alpine                                            (intentionally upstream)
#
# If any other service shows v0.10.5: STOP. The image-pin chain is broken.
```

Confirm traffic is flowing:

```powershell
kubectl logs -n online-boutique-research deploy/loadgenerator --tail=20
```

---

## 5. (Optional) Tiny smoke — 1 run, ~25 min

Catches harness regressions before sinking 6+ hours into the corpus.

```powershell
$ts = Get-Date -UFormat "%Y%m%dT%H%M%SZ"
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File scripts\research-lab\collect-dataset-plan.ps1 `
  -DatasetRunId "smoke-quick-$ts" `
  -PlanFile "deploy\research-lab\run-plans\dataset-v5-new-families-a.json" `
  -PythonExe .venv\Scripts\python.exe `
  -ForceNewRun -BuildDerived -PostWindowSeconds 30
```

Expected: exit 0, 12 episodes, ~75 windows, 5 Jira shadow issues,
recall@3 = 1.0 on the per-run derived ranking dataset.

If exit code is non-zero, check `data\runs\smoke-quick-*\summaries\data-quality-report.md`
and fix the issue before launching the corpus.

---

## 6. Launch the full v5-quick corpus

```powershell
$env:RUN_PREFIX = "2026-05-25-dataset-v5-quick"
$env:GLOBAL_DATASET_ID = "2026-05-25-dataset-v5-quick-global"
$env:BENCHMARK_ID = "triage-v5-quick-baseline"

New-Item -ItemType Directory -Force -Path logs | Out-Null

pwsh -NoProfile -ExecutionPolicy Bypass `
  -File scripts\research-lab\collect-dataset-corpus.ps1 `
  -CorpusFile "deploy\research-lab\corpora\dataset-v5-quick.json" `
  -DatasetRunPrefix $env:RUN_PREFIX `
  -GlobalDatasetId $env:GLOBAL_DATASET_ID `
  -PythonExe .venv\Scripts\python.exe `
  -Quick `
  -BuildTriage `
  -HaltOnValidationFail `
  -SkipDerivedBuild `
  -SkipAggregateBuild `
  2>&1 | Tee-Object -FilePath "logs\$($env:RUN_PREFIX)-corpus.log"
```

**Flags explained:**

- `-Quick` — shortens active fault windows to the plan's quick durations.
- `-BuildTriage` — after every run, build triage examples + per-window memory matchings + (at end) global triage dataset + Jira memory corpus. **This is what makes partial data usable for ML iteration before the full sweep finishes.**
- `-HaltOnValidationFail` — stop immediately if any per-run validation fails (zero-signal ticket_worthy windows, all-zero features). Prevents wasting compute on a broken cluster.
- `-SkipDerivedBuild` + `-SkipAggregateBuild` — skip the legacy ranking pipeline; v5 is a triage corpus.

The launcher is resumable — if it stops, fix the issue and re-run the exact
same command. Completed runs are detected via `manifest.json` and skipped
automatically. **Never add `-ForceNewRun`** — that discards completed runs.

### Detach + monitor (recommended)

PowerShell doesn't have tmux. Two pragmatic options:

**Option A — separate PowerShell window.** Open a new Windows Terminal tab,
run the command above. Leave that window open. From a second tab:

```powershell
# Live tail
Get-Content "logs\2026-05-25-dataset-v5-quick-corpus.log" -Wait -Tail 20
```

**Option B — Start-Process detached.** Less recoverable on close:

```powershell
Start-Process pwsh -ArgumentList @(
  "-NoProfile", "-ExecutionPolicy", "Bypass",
  "-File", "scripts\research-lab\collect-dataset-corpus.ps1",
  "-CorpusFile", "deploy\research-lab\corpora\dataset-v5-quick.json",
  "-DatasetRunPrefix", $env:RUN_PREFIX,
  "-GlobalDatasetId", $env:GLOBAL_DATASET_ID,
  "-PythonExe", ".venv\Scripts\python.exe",
  "-Quick", "-BuildTriage", "-HaltOnValidationFail",
  "-SkipDerivedBuild", "-SkipAggregateBuild"
) -RedirectStandardOutput "logs\$($env:RUN_PREFIX)-corpus.log" `
  -RedirectStandardError  "logs\$($env:RUN_PREFIX)-corpus.err"
```

---

## 7. Monitor progress

```powershell
# Where are we?
Get-Content "data\derived\corpora\$($env:RUN_PREFIX)\corpus-run-manifest.json" `
  | ConvertFrom-Json `
  | Select-Object completed_run_count, selected_run_count, status

# Disk free + per-run data quality
Get-PSDrive C | Select-Object Used, Free
Get-ChildItem data\runs\$($env:RUN_PREFIX)-*\summaries\data-quality-report.md `
  | Sort-Object LastWriteTime -Descending | Select-Object -First 5

# Latest log tail
Get-Content "logs\$($env:RUN_PREFIX)-corpus.log" -Tail 40
```

---

## 8. After collection — build benchmark

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File scripts\research-lab\run-triage-benchmark.ps1 `
  -GlobalDatasetId $env:GLOBAL_DATASET_ID `
  -BenchmarkId $env:BENCHMARK_ID `
  -PythonExe .venv\Scripts\python.exe `
  -Force

# Read the headline
Get-Content "data\derived\global\$($env:GLOBAL_DATASET_ID)\benchmarks\$($env:BENCHMARK_ID)\benchmark-report.md"
```

---

## 9. Train models on partial output while the sweep runs

You don't have to wait for all 16 runs to finish. After each run completes,
`data\derived\<run>\triage_examples.jsonl` exists and can be combined into a
partial global dataset at any time:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File scripts\research-lab\build-global-triage-dataset.ps1 `
  -DatasetRunPrefix $env:RUN_PREFIX `
  -GlobalDatasetId "$($env:GLOBAL_DATASET_ID)-partial" `
  -PythonExe .venv\Scripts\python.exe `
  -Force
```

Iterate on feature engineering + model code against the partial; the column
shape and label space are identical to what v5-large will eventually produce.

---

## Expected final state

| Asset | Expected |
| --- | ---: |
| Corpus runs with `status: completed` | 16 |
| Rows in `global-triage-examples.jsonl` | ~470 |
| Entries in `jira-memory-corpus.jsonl` | ~85 (orphans contribute 0) |
| Scenario families in the split manifest | 22 (D11 system-faults excluded by design) |
| Long-window (≥10 min) episodes | ~8 |
| Orphan ticket_worthy windows | 24 (vs 192 in full v5; noisier orphan-detection metric) |
| `"passed": false` data-quality reports | 0 |
| Leakage canary fails | 0 |

When the GCP VM's v5-large eventually lands (~4 days later), retrain the
same models on it with no code changes — column shape and label space are
identical.
