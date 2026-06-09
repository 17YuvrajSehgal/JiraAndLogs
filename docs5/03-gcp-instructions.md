# GCP VM Collection Runbook — OTel Demo Cross-App Dataset

**Audience:** a fresh Claude Code session starting on a **clean GCP VM** (no tooling installed). This document is end-to-end: OS bootstrap through full corpus collection to data hand-off back to the local workstation.

**Branch you'll work on:** `otel-demo-cross-app` (already pushed; cut from `master-final-models`).

**Your scope (GCP):** Phase 4 + Phase 4b only — full corpus collection. Humanize / LLM-extract / cascade-evaluation stay on the local workstation (LM Studio + Neo4j live there).

**Estimated wall time:** ~2 hours setup (clean VM) + ~30 min pilot + ~4-5 days unattended collection + ~½ day data sync.

**VM target:** Ubuntu 24.04 LTS on `e2-standard-16` (16 vCPU, 64 GB RAM, 1 TB pd-balanced). The disk size matters — full corpus + raw exports run ~100-150 GB.

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
- `reference-final-artifacts` — locked OB paths (DO NOT TOUCH if data lands here)

**Critical:** the OB v5-large dataset and locked TCH artifacts at `data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/final/` are **read-only**. Since this is a clean VM you won't have them locally — that's fine. Just never write to that exact path; cross-app outputs go under a different `<global_id>`.

---

## 2. What's already done (don't redo)

Validated end-to-end on a local kind cluster on 2026-06-08:

| Component | Status | Where to verify |
|---|---|---|
| Helm chart deploy (`open-telemetry/opentelemetry-demo` v0.40.9) | done | `deploy/otel-demo/helm-values.yaml` |
| OTel Demo telemetry → our observability stack | done | `deploy/otel-demo/otel-collector-config.yaml` exports to `opentelemetrycollector.observability.svc.cluster.local:4317` |
| Alloy allowlist source file (added `otel-demo-research`) | done | `deploy/research-lab/observability/values/alloy-values.yaml` |
| All 4 harness primitives (Flagd, ScaleDeployment, RestartPods, MultiFault) | done | `scripts/research-lab/run-scenario.ps1` + `scripts/research-lab/otel-demo/` |
| 94-column compatibility (`build_triage_dataset.py`) | done | Locally produced 94/94 `triage_feature_*` columns |
| 47 scenarios + 9 sidecar JSONs + 5 run plans | done | `deploy/research-lab/scenarios/otel-demo/` and `deploy/research-lab/run-plans/otel-demo-*.json` |

**Nine deploy-time gotchas already documented in §14** — do not re-introduce them.

---

## 3. Clean VM bootstrap

Run these as `$USER` (your SSH login on the VM). Most steps need `sudo`.

### 3.1 OS prep + base tooling

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \
    ca-certificates curl wget gnupg lsb-release apt-transport-https \
    software-properties-common build-essential git tmux jq \
    python3-pip python3-venv

# Confirm
python3 --version    # expect 3.12+ on Ubuntu 24.04
git --version
tmux -V
```

### 3.2 Docker

Official Docker repo (the default Ubuntu `docker.io` package is older and sometimes incompatible with kind):

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin

# Add yourself to the docker group so kubectl/kind/helm don't need sudo
sudo usermod -aG docker $USER
# Pick up the group membership without logging out:
newgrp docker

# Verify
docker --version
docker run --rm hello-world   # should print "Hello from Docker"
```

If `hello-world` fails with a permission error, log out + back in.

### 3.3 kubectl

```bash
KUBECTL_VER=$(curl -L -s https://dl.k8s.io/release/stable.txt)
curl -LO "https://dl.k8s.io/release/${KUBECTL_VER}/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
rm kubectl

kubectl version --client=true
```

### 3.4 helm

```bash
curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" \
    | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
sudo apt-get update
sudo apt-get install -y helm

helm version --short
```

### 3.5 kind (Kubernetes-in-Docker)

We pin to kind v0.31.0 to match the locally-validated cluster.

```bash
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

kind version
```

### 3.6 PowerShell (pwsh) — needed because all harness scripts are `.ps1`

```bash
source /etc/os-release
wget -q "https://packages.microsoft.com/config/ubuntu/${VERSION_ID}/packages-microsoft-prod.deb"
sudo dpkg -i packages-microsoft-prod.deb
rm packages-microsoft-prod.deb
sudo apt-get update
sudo apt-get install -y powershell

pwsh --version    # expect 7.x
```

If `${VERSION_ID}` resolves to a version Microsoft doesn't have a repo for, use the closest available (e.g. for 24.04, the 22.04 repo works in a pinch).

### 3.7 gcloud / gsutil — should already be installed on a GCE VM

```bash
gcloud --version
gsutil --version

# If missing:
# sudo apt-get install -y google-cloud-cli
```

Authenticate to your project (one-time):
```bash
gcloud auth login
gcloud config set project <YOUR_PROJECT_ID>
```

### 3.8 Verify resources before proceeding

```bash
free -h           # expect ~60 GB available
nproc             # expect 16
df -h /           # expect 1 TB total / >900 GB free
docker info | grep -E "CPUs|Total Memory"
```

If any of these are wildly off, the VM may be the wrong shape. The collection needs ~25 GB of cluster memory + ~150 GB disk headroom.

---

## 4. Clone the repo + Python environment

```bash
cd ~
git clone https://github.com/17YuvrajSehgal/JiraAndLogs.git
cd JiraAndLogs
git checkout otel-demo-cross-app
git pull origin otel-demo-cross-app

# Confirm we're on the right branch with the latest commits
git log --oneline -10
# Expect: c238fb1 docs5/03 (or later) at the top

# Python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -r scripts/research-lab/requirements.txt

# Confirm key packages
python3 -c "import yaml, neo4j, requests; print('python deps OK')"
```

---

## 5. Cluster setup (kind cluster + observability stack)

### 5.1 Create the kind cluster

The OB-era script handles this; on Linux pwsh it should work as-is. If it errors with Windows-isms, the equivalent kind CLI is given below.

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/create-kind-cluster.ps1
```

**If the script fails on Linux**, create the cluster manually with a 3-node config that matches what the OB pipeline expects:

```bash
cat > /tmp/kind-config.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: jira-telemetry-lab
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30080
        hostPort: 30080
        protocol: TCP
  - role: worker
  - role: worker
EOF
kind create cluster --config /tmp/kind-config.yaml --wait 5m
kubectl config use-context kind-jira-telemetry-lab
```

Verify:
```bash
kubectl get nodes
# Expect: 3 nodes, all Ready
```

### 5.2 Install the observability stack (Loki / Tempo / Prometheus / Grafana / Alloy / OTel Collector)

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/install-observability.ps1
kubectl wait --for=condition=Ready pods --all -n observability --timeout=900s
```

This deploys the same observability stack OB uses, and the source-of-truth `alloy-values.yaml` already includes `otel-demo-research` in the namespace allowlist (committed in `21a5b6c`). So in principle no extra patching is needed.

**Verify Alloy picked up the right config:**
```bash
kubectl get cm alloy -n observability -o jsonpath='{.data.config\.alloy}' | grep "regex.*otel-demo"
# Expect a line like:
#   regex = "online-boutique-research|observability|trainticket|otel-demo-research"
```

If the live ConfigMap does NOT include `otel-demo-research` (meaning install-observability.ps1 used a different values source), patch manually per §5.3 below.

### 5.3 (Conditional) Patch Alloy ConfigMap to allowlist `otel-demo-research`

Only needed if §5.2's verify-grep didn't find `otel-demo-research`:

```bash
kubectl get cm alloy -n observability -o yaml > /tmp/alloy-cm.yaml
# Use sed with # as delimiter (| would conflict with regex content)
sed -i 's#online-boutique-research|observability"#online-boutique-research|observability|trainticket|otel-demo-research"#' /tmp/alloy-cm.yaml
sed -i 's#online-boutique-research|observability|trainticket"#online-boutique-research|observability|trainticket|otel-demo-research"#' /tmp/alloy-cm.yaml
kubectl apply -f /tmp/alloy-cm.yaml

kubectl rollout restart -n observability daemonset/alloy
kubectl rollout status -n observability daemonset/alloy --timeout=60s

# Re-verify
kubectl get cm alloy -n observability -o jsonpath='{.data.config\.alloy}' | grep "otel-demo-research"
```

### 5.4 Verify the observability OTel collector service name

```bash
kubectl get svc opentelemetrycollector -n observability
# Expect ports: 4317/TCP (OTLP gRPC), 4318/TCP (OTLP HTTP), and others
```

If the service name is different (e.g. with a hyphen), update `deploy/otel-demo/helm-values.yaml` and `deploy/otel-demo/otel-collector-config.yaml` and commit. The local pilot's actual service name was `opentelemetrycollector` (no hyphen).

---

## 6. Install chaos-mesh

The previous OB-era VM had this pre-installed. This clean VM does not. Install via helm:

```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update chaos-mesh

kubectl create namespace chaos-mesh

# CRITICAL: kind uses containerd as the runtime, not docker.
# Default helm values target docker.sock — those will fail.
helm install chaos-mesh chaos-mesh/chaos-mesh \
    --namespace chaos-mesh \
    --set chaosDaemon.runtime=containerd \
    --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
    --version 2.7.0 \
    --wait

# Verify
kubectl get crds | grep chaos-mesh.org
# Expect: NetworkChaos, PodChaos, StressChaos, DNSChaos, IOChaos, TimeChaos, HTTPChaos, JVMChaos

kubectl get pods -n chaos-mesh
# Expect: chaos-controller-manager + chaos-daemon-* DaemonSet pods, all Running
```

If pods fail with "no such socket" or runtime mismatch, the kind cluster's containerd socket path may differ. Common alternates:
- `/run/containerd/containerd.sock` (most common)
- `/run/k3s/containerd/containerd.sock` (k3s)
- `/var/run/docker.sock` (docker runtime — wrong for kind)

Find it with:
```bash
docker exec jira-telemetry-lab-control-plane ls -l /run/containerd/containerd.sock
# Or:
docker exec jira-telemetry-lab-worker ls -la /run/
```

Update the helm install with the correct path and re-run.

### 6.1 Quick chaos-mesh smoke test

```bash
cat > /tmp/chaos-smoke.yaml <<'EOF'
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: smoke-test
  namespace: default
spec:
  action: delay
  mode: one
  selector:
    namespaces: [default]
  delay:
    latency: "100ms"
  duration: "30s"
EOF
kubectl apply -f /tmp/chaos-smoke.yaml
sleep 5
kubectl get networkchaos -n default smoke-test -o jsonpath='{.status}' | head
# Should show some status fields (AllInjected, AllRecovered, etc.) — even if no pods matched in default ns
kubectl delete -f /tmp/chaos-smoke.yaml
```

chaos-mesh is ready when this smoke test creates+deletes the NetworkChaos CR cleanly.

---

## 7. Deploy OTel Demo

```bash
pwsh deploy/otel-demo/helm-install.ps1
```

This script:
1. Reads `deploy/otel-demo/helm-version.txt` (pinned to chart `0.40.9`, image `2.2.0`)
2. Adds the `open-telemetry` helm repo
3. Applies `deploy/otel-demo/namespace.yaml` (`otel-demo-research` namespace with PSS=privileged)
4. `helm upgrade --install` with `deploy/otel-demo/helm-values.yaml`
5. Waits for pods (10 min timeout — first run pulls ~18 images from `ghcr.io/open-telemetry/demo`)
6. Smoke-checks via port-forward to frontend-proxy

Expected result: 23 pods Ready, ~5-10 min wall time (image pulls are the long pole on first run). If pods stay Pending, check memory.

### 7.1 Confirm telemetry flow end-to-end

```bash
# Wait for load-generator to produce some traffic
sleep 30
kubectl logs -n otel-demo-research -l app.kubernetes.io/name=load-generator --tail=5

# Confirm our observability collector receives OTel Demo telemetry
kubectl logs -n observability deploy/opentelemetrycollector --tail=20 | grep -iE "spans|metrics|logs" | head -5
# Should show batches arriving from k8s.namespace.name=otel-demo-research pods

# Confirm Loki indexed the namespace (THE critical check)
kubectl port-forward -n observability svc/loki-gateway 13100:80 &
PF_PID=$!
sleep 4
curl -s 'http://127.0.0.1:13100/loki/api/v1/label/namespace/values' | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['data'])"
# Expected output includes: 'otel-demo-research'
# If missing: re-do §5.3 Alloy patch
kill $PF_PID 2>/dev/null
```

### 7.2 Confirm chaos-mesh can target OTel Demo pods

```bash
cat > /tmp/chaos-target-test.yaml <<'EOF'
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: target-test
  namespace: chaos-mesh
spec:
  action: delay
  mode: one
  selector:
    namespaces: [otel-demo-research]
    labelSelectors:
      "app.kubernetes.io/name": "frontend"
  delay:
    latency: "50ms"
  duration: "20s"
EOF
kubectl apply -f /tmp/chaos-target-test.yaml
sleep 6
kubectl get networkchaos target-test -n chaos-mesh -o jsonpath='{.status.experiment.containerRecords[*].events[-1:].operation}' 2>/dev/null
# Should output: Apply (meaning chaos-mesh successfully applied the network delay)
sleep 20
kubectl delete -f /tmp/chaos-target-test.yaml
```

If this works, chaos-mesh + OTel Demo are correctly wired and the 4 network families + L4 compound scenario can be authored.

---

## 8. Pilot (go/no-go before full collection)

**Always run the pilot first.** Even though the harness is validated locally, the GCP cluster may surface different issues.

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
- [ ] `build_triage_dataset.py` emits **94** `triage_feature_*` columns per window
- [ ] L3 cascade scenario (`cascade-kafka-broker-checkout`) shows observable secondary failure via trace data
- [ ] flagd ConfigMap (`flagd-config`) restored to baseline after each Flagd scenario

Verify:
```bash
# Feature column count — THE critical compatibility check
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

# Confirm flagd flags are all restored to off
kubectl get cm flagd-config -n otel-demo-research -o jsonpath='{.data.demo\.flagd\.json}' | \
    python3 -c "import json,sys; d=json.loads(sys.stdin.read()); v={k:vv['defaultVariant'] for k,vv in d['flags'].items()}; print(v); assert all(x=='off' for x in v.values()), 'some flags not restored'"
```

**If anything fails the go/no-go, debug locally before scaling up.** Don't burn 5 days of VM time on a broken pipeline.

---

## 9. Author the 5 chaos-mesh-dependent scenarios

If §6 + §7.2 confirmed chaos-mesh works, author the deferred scenarios per `docs5/01 §10.3`. This unlocks the full 49-scenario corpus.

```
deploy/research-lab/scenarios/otel-demo/chaos/
├── network-latency-major.yaml
├── network-packet-loss-major.yaml
├── network-partition-critical.yaml
├── dns-outage-critical.yaml
└── (and chaos manifests under chaos/manifests/)

deploy/research-lab/scenarios/otel-demo/multifault/
├── compound-saturation-network-latency.yaml
└── components/compound-saturation-network-latency.json
```

Pattern:
- Use `action: ChaosMeshChaos` (existing OB primitive in `run-scenario.ps1`)
- Reference a NetworkChaos / DNSChaos CR manifest via `execution.chaos_manifest`
- Use the existing OB chaos manifests under `deploy/research-lab/scenarios/chaos/` as templates
- Adapt selectors to the `otel-demo-research` namespace

After authoring:
- Update `deploy/research-lab/corpora/otel-demo-v1.json` to include a new `otel-demo-network` run plan
- `git add` + `git commit` + `git push` to `otel-demo-cross-app` so local sees them

**This step is optional.** If time is tight, skip and run the 44-scenario corpus first; add chaos scenarios as a follow-up.

---

## 10. Full collection

Once pilot is green, kick off the full corpus in tmux:

```bash
tmux new -s otel-collection
source .venv/bin/activate

# Pick a stable dataset run prefix + global id (replace YYYYMMDD with today's date)
RUN_PREFIX="2026-06-XX-otel-demo-v1"
GLOBAL_ID="2026-06-XX-otel-demo-v1-global"

pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/collect-dataset-corpus.ps1 \
    -CorpusFile "deploy/research-lab/corpora/otel-demo-v1.json" \
    -DatasetRunPrefix "$RUN_PREFIX" \
    -GlobalDatasetId "$GLOBAL_ID" \
    -PythonExe .venv/bin/python3 \
    -Quick -BuildTriage -HaltOnValidationFail \
    -SkipDerivedBuild -SkipAggregateBuild \
    2>&1 | tee logs/otel-demo-collection.log

# Detach: Ctrl+B then D
# Reattach: tmux attach -t otel-collection
```

Expected wall time: **4–5 days unattended.** Each scenario takes ~10–15 min (5 min pre-fault + 10 min active + 3 min post + telemetry export). Resume-on-failure is built in.

### Monitor

```bash
# Tail collection log
tail -f logs/otel-demo-collection.log

# Run-count progress
ls data/runs/2026-06-*-otel-demo-v1-* 2>/dev/null | wc -l

# Disk usage
du -sh data/runs/ data/derived/

# Cluster health (memory pressure is the most likely failure mode)
kubectl top nodes
kubectl top pods -n otel-demo-research --sort-by=memory | head -10
```

---

## 11. Build global aggregation

After the corpus completes:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/build-global-triage-dataset.ps1 \
    -DatasetRunPrefix "$RUN_PREFIX" \
    -GlobalDatasetId "$GLOBAL_ID" \
    -PythonExe .venv/bin/python3
```

Verify:
```bash
ls data/derived/global/$GLOBAL_ID/
# Expect: global-triage-examples.jsonl, triage-split-manifest.json, jira-memory-corpus.jsonl

wc -l data/derived/global/$GLOBAL_ID/global-triage-examples.jsonl
# Expect ~5,000-9,000 windows depending on actual run counts
```

**Known issue from local pilot:** `scenario_family` column may show `'unknown'` for all rows. Doesn't block collection; affects depth-stratified analysis downstream. Local workstation team is patching in parallel; if your global build hits this, just document and continue.

---

## 12. Hand off raw data to local workstation

After full collection completes, the local workstation needs the raw runs + global derived dataset for the humanize + LLM-extract + cascade-evaluation phases.

### Option A — GCS bucket (preferred)

```bash
# Create bucket (one-time)
gsutil mb -l us-central1 gs://yuvraj-research-otel-demo

# Sync raw runs
gsutil -m rsync -r data/runs/2026-06-*-otel-demo-v1-* \
    gs://yuvraj-research-otel-demo/data/runs/

# Sync global derived
gsutil -m rsync -r data/derived/global/$GLOBAL_ID/ \
    gs://yuvraj-research-otel-demo/data/derived/global/$GLOBAL_ID/
```

On the local workstation:
```bash
gsutil -m rsync -r gs://yuvraj-research-otel-demo/data/ data/
```

### Option B — gcloud compute scp

```bash
# From local workstation
gcloud compute scp --recurse \
    USER@VM:~/JiraAndLogs/data/runs/2026-06-*-otel-demo-v1-* \
    C:/workplace/JiraAndLogs/data/runs/

gcloud compute scp --recurse \
    USER@VM:~/JiraAndLogs/data/derived/global/2026-06-XX-otel-demo-v1-global/ \
    C:/workplace/JiraAndLogs/data/derived/global/
```

Approximate volume: **~10-15 GB compressed**, dominated by Tempo trace data.

---

## 13. What happens after hand-off (local workstation)

Context only; nothing to do on the VM.

The local workstation will:
1. Run the V2 humanizer over the new `jira-memory-corpus.jsonl` with `--service-catalog deploy/research-lab/service-catalogs/otel-demo.yaml`
2. Run the LLM extractor against the humanized corpus (Qwen 35B via LM Studio)
3. Load the new Neo4j graph
4. Pre-fit the 6 pipelines on the OTel Demo test split
5. Run the DiagnosisAgent on test windows (~6 hours LM Studio)
6. Build the cascade in zero-shot mode (locked OB artifacts, no retraining)
7. Build the cascade in L1-retrained mode (refit only the L1 stacker)
8. Generate the cross-app headline table for the paper's §6.5

Your VM work is complete when:
- Full corpus collected
- Global aggregation built
- Raw runs + global derived synced to local

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
| 10 | chaos-mesh helm chart defaults to docker.sock; kind uses containerd | See §6 `--set chaosDaemon.runtime=containerd` |
| 11 | `${VERSION_ID}` for Microsoft pwsh repo may not exist for 24.04 | Fall back to 22.04 repo if needed (§3.6) |

---

## 15. Charter / contract reminders

- **Rule R1 (output paths)**: all collection outputs go under `data/runs/2026-06-XX-otel-demo-v1-*` and `data/derived/global/2026-06-XX-otel-demo-v1-global/`. Never under any `online-boutique`-prefixed path.
- **Rule R2 (script behavior)**: existing OB scripts are parameterized but never rewritten. If you find a hardcoded OB path that breaks for OTel Demo, EITHER add an additive flag OR fork the script under `scripts/research-lab/otel-demo/`. Never edit OB behavior.
- **Rule R3 (cascade + humanizer)**: locked OB cascade artifacts are read-only. The GCP VM has no business reading or writing `comparison/v2g-final-models/final/`.
- **Rule R4 (k8s namespace)**: only `otel-demo-research` namespace for the demo app. Do not touch `online-boutique-research` or any other.
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
tmux attach -t otel-collection
tail -f logs/otel-demo-collection.log
ls data/runs/ | wc -l                                # progress

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

# chaos-mesh status
kubectl get networkchaos,podchaos,stresschaos,dnschaos -A
```

---

## 17. When to escalate back to local

Pause and ping local if:

- Pilot fails the 94-column check (any drift from `94/94` is a structural issue)
- Pilot's L3 cascade scenario fails to produce observable secondary failure
- More than 3 scenarios in the full corpus error in succession (suggests a systemic harness break)
- chaos-mesh authoring (§9) blocked by missing harness primitive
- Any need to modify OB-shared scripts (Rule R2 — always preferable to fork)
- Disk fills up (estimate: ~150 GB for full corpus including raw exports)

Otherwise: collection is meant to run unattended for 4–5 days. Babysit lightly via tmux + tail.

---

## 18. Done criteria

Your GCP work is complete when ALL of these are true:

- [ ] Full corpus collected (~70 runs, ~6,500–9,000 windows)
- [ ] `data/derived/global/2026-06-XX-otel-demo-v1-global/global-triage-examples.jsonl` exists
- [ ] `data/derived/global/2026-06-XX-otel-demo-v1-global/jira-memory-corpus.jsonl` exists
- [ ] Raw runs + global derived synced to local workstation (per §12)
- [ ] Branch `otel-demo-cross-app` has any GCP-side commits pushed (e.g. chaos-mesh scenarios if authored)
- [ ] `docs5/02-implementation-status.md` updated with the GCP collection status

After that, the local workstation takes over for humanize → extract → cascade evaluation → paper write-up.

---

## 19. Cleanup / teardown

When the data is safely on the local workstation:

```bash
# Optional: keep the cluster running for repeat collections, OR teardown
kind delete cluster --name jira-telemetry-lab

# Stop the VM (per your cost management)
# Note: stopping retains the disk + IP; deleting is final
# gcloud compute instances stop <vm-name> --zone <zone>
```

The `otel-demo-cross-app` branch is reproducible from the scripts; the raw VM data is the only thing expensive to regenerate.

---

## 20. Total step summary (TL;DR for the VM session)

1. **§3** — install Docker, kubectl, helm, kind, pwsh, Python (~30 min)
2. **§4** — clone repo, set up venv (~10 min)
3. **§5** — create kind cluster + install observability stack (~15 min)
4. **§6** — install chaos-mesh + verify (~10 min)
5. **§7** — deploy OTel Demo + verify telemetry flow (~15 min)
6. **§8** — run pilot, validate go/no-go (~60 min)
7. **§9** — author chaos-mesh scenarios (optional, ~1 hour)
8. **§10** — kick off full collection in tmux (~5 days unattended)
9. **§11** — build global aggregation (~10 min)
10. **§12** — sync data back to local workstation (~30 min)
11. **§19** — teardown (optional)

Total active time: ~3 hours setup + ~½ day data ops, plus 5 days of unattended collection.

---

*Last updated 2026-06-08. Authored from the local workstation after Phase 2 pilot validation. Updated for a clean VM (no pre-installed tooling assumed). The GCP VM session should treat this as a runbook; deviate only with explicit re-charter or explicit user direction.*
