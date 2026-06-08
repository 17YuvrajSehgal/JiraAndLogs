# GCP VM Collection Runbook — OTel Demo Cross-App Dataset

**Audience:** a fresh Claude Code session starting on the GCP VM. This document tells you what's already done, what you need to do, and what to hand back to the local workstation.

**Branch you'll work on:** `otel-demo-cross-app` (already pushed; cut from `master-final-models`).

**Your scope (GCP):** Phase 4 + Phase 4b only — full corpus collection. Humanize / LLM-extract / cascade-evaluation stay on the local workstation (LM Studio + Neo4j live there).

**Estimated wall time:** ~1 day setup + ~4-5 days unattended collection + ~½ day data sync.

---

## 1. Read this first

Before touching anything, load context from these files (in order):

1. `RESEARCH-CHARTER.md` — full project scope, the LOCKED §17 cross-app validation entry.
2. `docs5/00-otel-demo-cross-app-plan.md` — strategy + 47 scenario plan + graded difficulty (L1–L4) + propagation evidence.
3. `docs5/01-otel-demo-implementation-plan.md` — file-level implementation plan with hard isolation contract (§1, Rules R1–R5).
4. `docs5/02-implementation-status.md` — current state. **Phase 2 local pilot is GREEN.**
5. This file.

Auto-memory references (load via the Memory tool):
- `project-research-charter-locked` — the binding claims
- `project-tch-cascade-design` — the cascade you're feeding
- `project-g-series-outcomes` — what's already proven on the OB side
- `reference-final-artifacts` — locked OB paths (DO NOT TOUCH)

**Critical:** the OB v5-large dataset and locked TCH artifacts at `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/` are **read-only**. Nothing you do on the GCP VM should write to that directory. Cross-app outputs go under a different `<global_id>` path.

---

## 2. What's already done (don't redo)

Validated end-to-end on a local kind cluster on 2026-06-08:

| Component | Status | Where to verify |
|---|---|---|
| Helm chart deploy (`open-telemetry/opentelemetry-demo` v0.40.9) | ✅ | `deploy/otel-demo/helm-values.yaml` |
| OTel Demo telemetry → our observability stack | ✅ | `deploy/otel-demo/otel-collector-config.yaml` exports to `opentelemetrycollector.observability.svc.cluster.local:4317` |
| Alloy allowlist update (added `otel-demo-research`) | ✅ source file | `deploy/research-lab/observability/values/alloy-values.yaml` — **you'll need to re-apply this to the GCP cluster's live Alloy CM** |
| All 4 harness primitives (Flagd, ScaleDeployment, RestartPods, MultiFault) | ✅ | `scripts/research-lab/run-scenario.ps1` + `scripts/research-lab/otel-demo/` |
| 94-column compatibility (`build_triage_dataset.py`) | ✅ | Locally produced 94/94 `triage_feature_*` columns |
| 47 scenarios + 9 sidecar JSONs + 5 run plans | ✅ | `deploy/research-lab/scenarios/otel-demo/` and `deploy/research-lab/run-plans/otel-demo-*.json` |

**Five deploy-time bugs already fixed (do not re-introduce).** See commit `921bb82` — collector service name, env-overrides duplication, PodSecurity bumped to `privileged` for the OTel Demo namespace, flagd-ui sidecar disabled, flagd ConfigMap named `flagd-config` (not `otel-demo-flagd-config`).

---

## 3. Prerequisites on the VM

Verify before starting:

```bash
# Tooling
docker --version              # Docker 20+
kubectl version --client      # 1.28+
helm version                  # 3.10+ (4.x is fine; we used 4.1 locally)
kind version                  # 0.20+ if running on kind; or confirm GKE access if cloud k8s
python3 --version             # 3.11+
git --version

# Resources (e2-standard-16 = 16 vCPU, 64 GB RAM)
free -h                       # expect ~60 GB available
df -h /                       # expect 1 TB pd-balanced (per existing GCP runbook)
docker info | grep -E "CPUs|Total Memory"
```

If any tool is missing, install per `docs/gcp-production-dataset-vm-runbook.md` (existing OB-era runbook covers the base provisioning).

**Chaos-mesh check** — the user said it's installed; confirm:

```bash
kubectl get crds | grep chaos-mesh.org
kubectl get pods -n chaos-mesh 2>&1 | head
# Expect: NetworkChaos, PodChaos, StressChaos CRDs present; chaos-controller-manager pod Running
```

If chaos-mesh is present, you can author the 5 deferred scenarios after collection starts (see §10).

---

## 4. Repo bootstrap

```bash
cd ~  # or wherever you keep workspace
git clone https://github.com/17YuvrajSehgal/JiraAndLogs.git
cd JiraAndLogs
git checkout otel-demo-cross-app
git pull

# Python venv (per repo convention)
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -r scripts/research-lab/requirements.txt
```

Verify:
```bash
git log --oneline -5
# Expect to see commits up through 441c7ef (or later if there have been more)
```

---

## 5. Cluster + observability setup

If the VM already has a kind cluster (`jira-telemetry-lab`) and observability stack from previous OB collection runs, skip to §5.3. Otherwise:

### 5.1 Create kind cluster

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/create-kind-cluster.ps1
kubectl config use-context kind-jira-telemetry-lab
kubectl get nodes  # expect 3 nodes Ready
```

### 5.2 Install observability stack

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/install-observability.ps1
kubectl wait --for=condition=Ready pods --all -n observability --timeout=900s
```

This deploys Loki, Tempo, Prometheus, Grafana, Alloy, OTel Collector — the same stack OB uses.

### 5.3 Patch the live Alloy ConfigMap to allowlist `otel-demo-research`

This is the **one observability-stack change** required for OTel Demo logs to reach Loki. The branch has the patched source file but the live CM may need separate patching depending on how install-observability.ps1 resolved values:

```bash
# Check current state
kubectl get cm alloy -n observability -o jsonpath='{.data.config\.alloy}' | grep "regex.*online-boutique"

# If it says: regex = "online-boutique-research|observability"
# OR:        regex = "online-boutique-research|observability|trainticket"
# but does NOT include otel-demo-research, patch:

kubectl get cm alloy -n observability -o yaml > /tmp/alloy-cm.yaml
# Use sed with # as delimiter (| conflicts with regex content)
sed -i 's#online-boutique-research|observability"#online-boutique-research|observability|trainticket|otel-demo-research"#' /tmp/alloy-cm.yaml
sed -i 's#online-boutique-research|observability|trainticket"#online-boutique-research|observability|trainticket|otel-demo-research"#' /tmp/alloy-cm.yaml
kubectl apply -f /tmp/alloy-cm.yaml
kubectl rollout restart -n observability daemonset/alloy
kubectl rollout status -n observability daemonset/alloy --timeout=60s

# Verify
kubectl get cm alloy -n observability -o jsonpath='{.data.config\.alloy}' | grep "otel-demo-research"
```

### 5.4 Verify OTel Demo's target observability collector is reachable

```bash
kubectl get svc opentelemetrycollector -n observability
# Should show ports 4317 (OTLP gRPC) and 4318 (OTLP HTTP)
```

If the service name is different (e.g. `opentelemetry-collector` with a hyphen), update `deploy/otel-demo/helm-values.yaml` and `deploy/otel-demo/otel-collector-config.yaml` to match. The local pilot's actual service name was `opentelemetrycollector` (no hyphen).

---

## 6. Deploy OTel Demo

```bash
pwsh deploy/otel-demo/helm-install.ps1
```

This script:
1. Reads `deploy/otel-demo/helm-version.txt` (pinned to chart `0.40.9`, image `2.2.0`)
2. Adds the `open-telemetry` helm repo
3. Applies `deploy/otel-demo/namespace.yaml` (`otel-demo-research` namespace with PSS=privileged)
4. `helm upgrade --install` with `deploy/otel-demo/helm-values.yaml`
5. Waits for pods (10 min timeout — first run pulls ~18 images)
6. Smoke-checks via port-forward to frontend-proxy

Expected result: 23 pods Ready, ~3–6 min wall time. If pods stay Pending, check memory (~6 GB needed for OTel Demo + ~5 GB for observability ≈ ~11 GB total).

### Confirm telemetry flow

```bash
# Watch a checkout request hit the frontend-proxy
kubectl logs -n otel-demo-research -l app.kubernetes.io/name=load-generator --tail=5
# Should show traffic being generated

# Confirm our observability collector receives OTel Demo telemetry
kubectl logs -n observability deploy/opentelemetrycollector --tail=20 | grep -i "spans\|metrics\|logs"
# Should show: resource spans: 8, spans: 36 (etc.) — telemetry flowing

# Confirm Loki indexed the otel-demo-research namespace
kubectl port-forward -n observability svc/loki-gateway 13100:80 &
sleep 4
curl -s 'http://127.0.0.1:13100/loki/api/v1/label/namespace/values' | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['data'])"
# Should include: 'otel-demo-research'
# If missing: re-check §5.3 Alloy patch
pkill -f "port-forward.*loki-gateway"
```

---

## 7. Pilot (go/no-go before full collection)

**Always run the pilot first.** Do not skip to full collection — even though the harness is validated locally, the GCP cluster may surface different issues (different chart-key behavior, different service names, etc.).

```bash
# Start the dataset run scaffold
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/start-dataset-run.ps1 \
    -DatasetRunId "otel-demo-gcp-pilot-001"

# Run the pilot plan (11 scenarios; ~50 min wall time)
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/collect-dataset-plan.ps1 \
    -DatasetRunId "otel-demo-gcp-pilot-001" \
    -PlanFile "deploy/research-lab/run-plans/otel-demo-pilot.json" \
    -PythonExe .venv/bin/python3 \
    -BuildDerived
```

### Go/no-go checklist

Per `otel-demo-pilot.json` and `docs5/01 §9`:

- [ ] All 11 scenarios complete without harness errors
- [ ] Each scenario produces telemetry windows in `data/runs/otel-demo-gcp-pilot-001/`
- [ ] `build_triage_dataset.py` emits **94** `triage_feature_*` columns per window (the critical compatibility check)
- [ ] L3 cascade scenario (`cascade-kafka-broker-checkout`) shows observable secondary failure via trace data
- [ ] flagd ConfigMap (`flagd-config`) restored to baseline after each Flagd scenario (paymentFailure variant = "off")

Verify:
```bash
# Feature column count
head -1 data/derived/otel-demo-gcp-pilot-001/triage_examples.jsonl | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
f = [k for k in d if k.startswith('triage_feature_')]
print(f'features: {len(f)}/94')
assert len(f) == 94, f'EXPECTED 94 got {len(f)}'
print('OK')"

# All deployments back to expected replicas
kubectl get deploy -n otel-demo-research -o json | python3 -c "
import json, sys
for d in json.load(sys.stdin)['items']:
    print(f\"  {d['metadata']['name']}: replicas={d['spec']['replicas']}\")"
```

**If anything fails the go/no-go, debug locally before scaling up.** Don't burn 5 days of VM time on a broken pipeline.

---

## 8. Full collection

Once pilot is green, kick off the full corpus:

```bash
# Run in tmux so SSH disconnect doesn't kill it
tmux new -s otel-collection
source .venv/bin/activate

pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/collect-dataset-corpus.ps1 \
    -CorpusFile "deploy/research-lab/corpora/otel-demo-v1.json" \
    -DatasetRunPrefix "2026-06-XX-otel-demo-v1" \
    -GlobalDatasetId "2026-06-XX-otel-demo-v1-global" \
    -PythonExe .venv/bin/python3 \
    -Quick -BuildTriage -HaltOnValidationFail \
    -SkipDerivedBuild -SkipAggregateBuild \
    2>&1 | tee logs/otel-demo-collection.log

# Detach: Ctrl+B then D
# Reattach: tmux attach -t otel-collection
```

The corpus manifest `otel-demo-v1.json` references 5 run plans totaling **~70 runs** (subject to `n_runs` multipliers in the manifest):
- `otel-demo-baseline` (1 plan × 8 runs)
- `otel-demo-l1-compact` (33 scenarios × 1 run each, or adjust)
- `otel-demo-kafka` (5 scenarios)
- `otel-demo-multifault` (9 scenarios)

Expected wall time: **4–5 days unattended.** Each scenario takes ~10–15 min (5 min pre-fault + 10 min active + 3 min post + telemetry export). Resume-on-failure is built in — if anything errors, re-run the same command and it picks up where it left off.

### Monitor

```bash
# Tail collection log
tail -f logs/otel-demo-collection.log

# Quick run-count
ls data/runs/2026-06-*-otel-demo-v1-* 2>/dev/null | wc -l

# Disk usage
du -sh data/runs/ data/derived/

# Cluster health (memory pressure most likely failure mode)
kubectl top nodes
kubectl top pods -n otel-demo-research --sort-by=memory | head -10
```

---

## 9. Build global aggregation

After the corpus completes:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/build-global-triage-dataset.ps1 \
    -DatasetRunPrefix "2026-06-XX-otel-demo-v1" \
    -GlobalDatasetId "2026-06-XX-otel-demo-v1-global" \
    -PythonExe .venv/bin/python3
```

Verify:
```bash
ls data/derived/global/2026-06-XX-otel-demo-v1-global/
# Expect: global-triage-examples.jsonl, triage-split-manifest.json, jira-memory-corpus.jsonl, etc.

wc -l data/derived/global/2026-06-XX-otel-demo-v1-global/global-triage-examples.jsonl
# Expect: ~5,000–9,000 windows depending on actual run counts
```

**Known issue surfaced during local pilot:** `scenario_family` column may show `'unknown'` for all rows. This is a downstream bug in the global builder; doesn't block collection but affects depth-stratified analysis. The local workstation team is patching this in parallel — if your global build hits this, document the affected file and continue.

---

## 10. Optional: author the 5 chaos-mesh scenarios

If §3's chaos-mesh check passed and you have time before kicking off the full corpus (or while it runs), author the 5 scenarios deferred per `docs5/01 §10.3`:

```
deploy/research-lab/scenarios/otel-demo/chaos/network-latency-major.yaml
deploy/research-lab/scenarios/otel-demo/chaos/network-packet-loss-major.yaml
deploy/research-lab/scenarios/otel-demo/chaos/network-partition-critical.yaml
deploy/research-lab/scenarios/otel-demo/chaos/dns-outage-critical.yaml
deploy/research-lab/scenarios/otel-demo/multifault/compound-saturation-network-latency.yaml
+ components/compound-saturation-network-latency.json
```

Pattern: use `action: ChaosMeshChaos` (existing OB primitive in `run-scenario.ps1`); reference a NetworkChaos CR manifest via `execution.chaos_manifest`. Use the existing OB chaos manifests under `deploy/research-lab/scenarios/chaos/` as templates; adapt selectors to the `otel-demo-research` namespace.

Then update `deploy/research-lab/corpora/otel-demo-v1.json` to reference a new `otel-demo-network` run plan, and rerun the affected portion of the collection.

**Commit + push** any chaos-mesh scenario additions to the `otel-demo-cross-app` branch so the local workstation sees them.

---

## 11. Hand off raw data to local workstation

After full collection completes, the local workstation needs the raw runs + global derived dataset for the humanize + LLM-extract + cascade-evaluation phases.

### Option A — GCS bucket (preferred; built into GCP)

```bash
# Create bucket (one-time)
gsutil mb -l us-central1 gs://yuvraj-research-otel-demo

# Sync raw runs
gsutil -m rsync -r data/runs/2026-06-XX-otel-demo-v1-* \
    gs://yuvraj-research-otel-demo/data/runs/

# Sync global derived
gsutil -m rsync -r data/derived/global/2026-06-XX-otel-demo-v1-global/ \
    gs://yuvraj-research-otel-demo/data/derived/global/2026-06-XX-otel-demo-v1-global/
```

On the local workstation:
```bash
gsutil -m rsync -r gs://yuvraj-research-otel-demo/data/ data/
```

### Option B — gcloud compute scp (if no GCS available)

```bash
# From local workstation
gcloud compute scp --recurse \
    USER@VM:~/JiraAndLogs/data/runs/2026-06-XX-otel-demo-v1-* \
    C:/workplace/JiraAndLogs/data/runs/

gcloud compute scp --recurse \
    USER@VM:~/JiraAndLogs/data/derived/global/2026-06-XX-otel-demo-v1-global/ \
    C:/workplace/JiraAndLogs/data/derived/global/
```

Approximate volume: **~10–15 GB compressed** (~80M trace files dominate — Tempo data per run).

---

## 12. What happens after hand-off (local workstation)

You don't do this part on the VM; mentioned here for context so you know when your work is done.

The local workstation will:
1. Run the V2 humanizer over the new `jira-memory-corpus.jsonl` with `--service-catalog deploy/research-lab/service-catalogs/otel-demo.yaml`
2. Run the LLM extractor against the humanized corpus (Qwen 35B via LM Studio)
3. Load the new Neo4j graph
4. Pre-fit the 6 pipelines on the OTel Demo test split
5. Run the DiagnosisAgent on test windows (~6 hours LM Studio)
6. Build the cascade in zero-shot mode (locked OB artifacts, no retraining)
7. Build the cascade in L1-retrained mode (refit only the L1 stacker)
8. Generate the cross-app headline table for the paper's §6.5

Your work on the GCP VM is complete when:
- Full corpus is collected
- Global aggregation built
- Raw runs + global derived synced to local

---

## 13. Cleanup / teardown

When the data is safely on the local workstation:

```bash
# Optional: keep the cluster running for repeat collections, OR teardown
kind delete cluster --name jira-telemetry-lab

# Optional: stop / delete the VM (per your cost management)
# gcloud compute instances stop <vm-name>
```

The `otel-demo-cross-app` branch's data outputs are reproducible from the run scripts; the raw VM data is the only thing that's expensive to regenerate.

---

## 14. Known gotchas from local validation

Things that already bit us locally. Pre-emptively guard against them:

| # | Gotcha | Fix |
|---|---|---|
| 1 | Helm collector service name `opentelemetry-collector` vs `opentelemetrycollector` | Already fixed in `deploy/otel-demo/helm-values.yaml`; verify §5.4 still matches |
| 2 | Duplicate `OTEL_EXPORTER_OTLP_ENDPOINT` from `default.envOverrides` | Already removed; do not re-add |
| 3 | flagd-ui sidecar OOMs at 250Mi | Already disabled via `components.flagd.sidecarContainers: []`; do not re-enable |
| 4 | flagd ConfigMap name is `flagd-config` (no release prefix) | Already corrected in scripts + default values |
| 5 | PodSecurity `baseline` rejects OTel collector hostPath volume | Namespace bumped to `privileged` in `deploy/otel-demo/namespace.yaml` |
| 6 | `run-scenario.ps1` must pass `-WorkloadNamespace` to `export-telemetry-window.ps1` | Already fixed in commit `c6820c8` |
| 7 | Port-forward conflict if you `curl` Loki manually then try to run export | `pkill -f "port-forward"` before running scenarios |
| 8 | `git add -A` sweeps in OB G-series logs from `results/v2_advanced/` | Use targeted `git add` |
| 9 | Alloy regex uses `\|` as delimiter; sed needs `#` as alternate delimiter | See §5.3 sed command |

---

## 15. Charter / contract reminders

- **Rule R1 (output paths)**: all collection outputs go under `data/runs/2026-06-XX-otel-demo-v1-*` and `data/derived/global/2026-06-XX-otel-demo-v1-global/`. Never under any `online-boutique`-prefixed path.
- **Rule R2 (script behavior)**: existing OB scripts are parameterized but never rewritten. If you find a hardcoded OB path that breaks for OTel Demo, EITHER add an additive flag OR fork the script under `scripts/research-lab/otel-demo/`. Never edit OB behavior.
- **Rule R3 (cascade + humanizer)**: locked OB cascade artifacts are read-only. The GCP VM has no business reading or writing `comparison/v2g-final-models/final/`.
- **Rule R4 (k8s namespace)**: only `otel-demo-research` namespace. Do not touch `online-boutique-research` or any other.
- **Rule R5 (branch)**: stay on `otel-demo-cross-app`. Do not merge to master from the VM.

If any of these rules feel like they'd block correct work, STOP and escalate — the rule exists to protect the locked OB primary claim.

---

## 16. Quick command reference

```bash
# Status checks
kubectl get pods -A | grep -v "Running\|Completed"   # anything unhealthy
kubectl top nodes
df -h /
docker system df

# Collection control
tmux attach -t otel-collection                       # see what's running
tail -f logs/otel-demo-collection.log
ls data/runs/ | wc -l                                # progress: total runs so far

# Per-scenario debug
pwsh scripts/research-lab/run-scenario.ps1 -DatasetRunId test-001 \
    -ScenarioFile <one-scenario.yaml> \
    -DurationSeconds 60 -PreWindowSeconds 30 -PostWindowSeconds 30 \
    -SkipJiraGeneration

# Flagd quick-check
kubectl get cm flagd-config -n otel-demo-research -o jsonpath='{.data.demo\.flagd\.json}' | \
    python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print({k:v['defaultVariant'] for k,v in d['flags'].items()})"

# Restore flagd to baseline (if a scenario crashed mid-flip)
pwsh scripts/research-lab/otel-demo/Invoke-FlagdFlip.ps1 \
    -FlagName paymentFailure -Variant off -DurationSeconds 1 \
    -Namespace otel-demo-research
```

---

## 17. When to escalate back to local

Pause and ping local if:

- Pilot fails the 94-column check (any drift from `94/94` is a structural issue)
- Pilot's L3 cascade scenario fails to produce observable secondary failure
- More than 3 scenarios in the full corpus error in succession (suggests a systemic harness break)
- chaos-mesh authoring blocked by missing harness primitive
- Any need to modify OB-shared scripts (Rule R2 — always preferable to fork)
- Disk fills up (estimate: ~150 GB for full corpus including raw exports)

Otherwise: collection is meant to run unattended for 4–5 days. Babysit lightly via tmux + tail.

---

## 18. Done criteria

Your GCP work is complete when ALL of these are true:

- [ ] Full corpus collected (~70 runs, ~6,500–9,000 windows)
- [ ] `data/derived/global/2026-06-XX-otel-demo-v1-global/global-triage-examples.jsonl` exists
- [ ] `data/derived/global/2026-06-XX-otel-demo-v1-global/jira-memory-corpus.jsonl` exists
- [ ] Raw runs + global derived synced to local workstation (per §11)
- [ ] No OB regression: `python3 -m v2_advanced.tch.check_cascade --cascade-dir data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final` still passes (if running locally) — on the VM, just confirm you didn't touch that path
- [ ] Branch `otel-demo-cross-app` has any GCP-side commits pushed (e.g. chaos-mesh scenarios if authored)
- [ ] `docs5/02-implementation-status.md` updated with the GCP collection status

After that, the local workstation takes over for humanize → extract → cascade evaluation → paper write-up.

---

*Last updated 2026-06-08. Authored from the local workstation after Phase 2 pilot validation. The GCP VM session should treat this as a runbook; deviate only with explicit re-charter or explicit user direction.*
