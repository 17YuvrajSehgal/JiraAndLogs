# GCP VM Runbook For Production Dataset Collection (v5-large)

This runbook is the **single source of truth** for collecting the
**Dataset v5 large** triage corpus (100 runs, ~4-5 days, 27 scenario
families, M0–M5 upgraded telemetry + chaos-mesh system faults +
orphan-fault detection coverage) on a fresh Google Cloud VM. Follow
top-to-bottom for an unattended production run.

The active product framing is the Jira-as-memory triage task; see
`docs/triage-task-contract.md` and `docs/dataset-v4-plan.md` for the
canonical contract and `microservice-changes-todo.md` for the M0–M5
telemetry upgrades that v5-large depends on.

For a one-shot index of what gets collected, see
`deploy/research-lab/corpora/dataset-v5-large.json`.

---

## Overview of the v5-large run

| Item | Value |
| --- | ---: |
| Corpus manifest | `deploy/research-lab/corpora/dataset-v5-large.json` |
| Total runs | 100 (8 control + 14 compact-a + 14 compact-b + 11 new-families-a + 11 new-families-b + 8 long-running + 24 orphans + 10 system-faults) |
| Scenario families | 27 (13 from v4 + 8 from D1 + 1 D12 email-outage + 5 D11 system-fault) |
| Expected episodes | ~920 |
| Expected telemetry windows | ~7,400 |
| Long-window episodes (≥10 min) | ~96 (from long-running plan) |
| Orphan ticket_worthy windows (D12) | 192 (orphans plan, no Jira filed) |
| System-fault active windows (D11) | 50 (chaos-mesh injected via system-faults plan) |
| Raw telemetry on disk | ~30-40 GB |
| Derived datasets | ~15-20 GB |
| **Total VM disk needed** | **1 TB recommended, 500 GB workable with care** |
| Collection wall time | ~4-5 days unattended |

Compared with v4-large (40 runs, ~24-30 hours, 13 families): 2.5× more
runs, **2× scenario diversity** (27 vs 13 families), ~3-5× per-window
log volume from the new M0–M5 telemetry layer (L1 per-RPC logs, L2
dep-error logs, L3 business events, structured spans, RED/runtime
metrics), **5 new system-level fault shapes** via chaos-mesh (DNS,
network partition, packet loss, network latency, memory pressure), and
**orphan-fault detection** coverage (200 ticket-worthy windows with no
paired Jira, enabling the "detection vs memorization" benchmark track).

---

## Recommended VM Shape

Use a single Compute Engine VM running Ubuntu, Docker, kind, and the
project scripts.

| Setting | v5-large target | Workable lower bound | Workable alternative |
| --- | --- | --- | --- |
| VM type | `e2-standard-8` (8 vCPU, 32 GB RAM) | same | same |
| OS | Ubuntu 24.04 LTS x86_64 | same | same |
| Boot disk | **1 TB** `pd-balanced` | 500 GB (cull old data mid-run) | 250 GB root + **1 TB attached `pd-balanced` at `/data`** (see "Use the attached disk" section below — same total storage, just split across two volumes) |
| Provisioning | Standard (not Spot) | same | same |
| Region | `us-central1` unless you have a reason | same | same |
| Kubernetes | kind cluster, 1 control-plane + 2 workers | same | same |

**Why 1 TB**: v5-large produces ~30-40 GB raw + ~15-20 GB derived. The
Loki PVC takes 120 GiB (or 50 GiB on a smaller disk — both supported by
`deploy/research-lab/observability/values/loki-values.yaml`). Docker
images for the rebuilt M0–M5 services + Online Boutique + kube
components + chaos-mesh consume another ~30-40 GB. With 500 GB you'll
fit but need to prune old Loki chunks mid-run; with 1 TB you don't have
to think about it.

**Attached-disk variant**: GCP often caps the root SSD around 250 GB
depending on the image / quota. If you can't get a 1 TB root, attach a
1 TB `pd-balanced` data disk and mount it at `/data`. Then follow the
"VM: Use the Attached Disk for All Heavy Storage" section below
**before** building images or cloning the repo — that step redirects
Docker's data-root + the JiraAndLogs run outputs to `/data` so the
small root never fills.

Do NOT use GKE for this stage. A single VM with kind is cheaper,
simpler, and matches the local research setup.

Do NOT use Spot. v5-large is a 5-day unattended run and Spot
preemption will lose mid-run state.

---

## Cost Controls

Before creating the VM:

1. (optional) Create a billing budget alert.
2. Label the VM (already in the create command below).
3. Set a manual reminder to stop/delete the VM after collection.

As of the checked Google pricing page, `e2-standard-8` in `us-central1`
is about `$0.27/hour` on demand. 5 days of compute ≈ `$32`. A 1 TB
`pd-balanced` disk is about `$0.10/GiB/month` ≈ `$3.40/day`. Total
v5-large run estimate: **~$55** compute + disk for the 5-day collection,
excluding network egress on data download (~50 GB at standard pricing).

Verify with the Google Cloud Pricing Calculator before launching.

---

## Local Machine: Push the Latest Code First

**Critical**: the fresh VM clones from GitHub, so any uncommitted local
changes will not exist on the VM. Before creating the VM, push both
repos:

```bash
# From your local laptop, in the JiraAndLogs working tree:
cd /path/to/JiraAndLogs
git push origin master-bigger-dataset

# And in the microservices-demo-google fork:
cd microservices-demo-google
git push origin main
```

Verify on GitHub that both `17YuvrajSehgal/JiraAndLogs@master-bigger-dataset`
and `17YuvrajSehgal/microservices-demo-google@main` have the latest
commits (the runbook addendum, kustomize image pins, D1 scenario
YAMLs, and the M0–M5 service changes).

---

## Local Machine: Create the VM

```bash
gcloud auth login
gcloud config set project project-dfc1abf4-e3f9-44ce-8a3
gcloud services enable compute.googleapis.com

gcloud compute instances create jira-logs-dataset-v5-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  --machine-type=e2-standard-8 \
  --provisioning-model=STANDARD \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=1000GB \
  --boot-disk-type=pd-balanced \
  --scopes=https://www.googleapis.com/auth/cloud-platform \
  --labels=project=jiraandlogs,purpose=dataset-v5,env=research \
  --metadata=enable-oslogin=TRUE
```

**Attached-disk variant** (if 1 TB boot disk isn't available, e.g.
your project's image quota caps root at 250 GB): use a smaller root
and attach a 1 TB data disk. The "VM: Use the Attached Disk for All
Heavy Storage" section below moves Docker + run output to the
attached disk so root never fills.

```bash
# Create the attached disk
gcloud compute disks create jira-logs-dataset-v5-data \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  --size=1000GB \
  --type=pd-balanced

# Create the VM with a smaller root + attach the data disk
gcloud compute instances create jira-logs-dataset-v5-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  --machine-type=e2-standard-8 \
  --provisioning-model=STANDARD \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=250GB \
  --boot-disk-type=pd-balanced \
  --disk=name=jira-logs-dataset-v5-data,device-name=data-disk,auto-delete=yes \
  --scopes=https://www.googleapis.com/auth/cloud-platform \
  --labels=project=jiraandlogs,purpose=dataset-v5,env=research \
  --metadata=enable-oslogin=TRUE
```

SSH in:

```bash
gcloud compute ssh jira-logs-dataset-v5-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a
```

Everything below this point runs **inside the VM** unless explicitly
marked "Local Machine".

---

## VM: Install Base Packages

```bash
set -euo pipefail

sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \
  ca-certificates curl gnupg git jq unzip zip tar tmux htop rsync \
  python3 python3-venv python3-pip \
  apt-transport-https software-properties-common
```

---

## VM: Install Docker Engine

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"

sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
JSON
sudo systemctl restart docker
newgrp docker
docker version
docker run --rm hello-world
```

**If you provisioned the attached-disk variant** (250 GB root + 1 TB
attached at `/data`), do the "VM: Use the Attached Disk for All Heavy
Storage" section now BEFORE going further. Otherwise images go to
root and root fills mid-run.

Also raise inotify limits so Go services don't hit "failed to create
fsnotify watcher: too many open files" under sustained load (the
checkoutservice L1 gap), AND so chaos-mesh's 22 CRD informers can
start without hitting Ubuntu's default `max_user_instances = 128`
(verified 2026-05-25 — without this bump, every chaos-mesh
controller-manager pod CrashLoopBackOffs with "too many open files"
the moment NetworkChaos / IOChaos / StressChaos resources are
referenced):

```bash
sudo tee /etc/sysctl.d/99-jira-logs-inotify.conf >/dev/null <<'EOF'
fs.inotify.max_user_watches = 1048576
fs.inotify.max_user_instances = 16384
fs.inotify.max_queued_events = 32768
EOF
sudo sysctl --system | grep -E "inotify"

# Confirm:
sysctl fs.inotify.max_user_instances
# Expect: 16384  (NOT the Ubuntu default of 128)
```

---

## VM: Use the Attached Disk for All Heavy Storage

**Skip this section if your boot disk is 1 TB and there's no separate
attached disk.** This is only for the 250 GB root + 1 TB attached
variant from the VM-shape table above.

Verify the attached disk is mounted at `/data` and has the expected
capacity:

```bash
df -h /data
# Expect: /dev/sdb (or similar) 984G ... mounted on /data
```

If it isn't mounted yet, format + mount before proceeding:

```bash
# DESTRUCTIVE — wipes the attached disk. Only run this on a fresh disk.
sudo mkfs.ext4 -F /dev/sdb
sudo mkdir -p /data
sudo mount /dev/sdb /data
# Persist across reboots:
DISK_UUID=$(sudo blkid -s UUID -o value /dev/sdb)
echo "UUID=${DISK_UUID} /data ext4 defaults 0 0" | sudo tee -a /etc/fstab
```

### Move Docker's data-root to /data (must happen before image build)

This is the single highest-leverage step. Docker container layers,
images, and **every kind PVC** (because kind nodes ARE Docker
containers) follow Docker's data-root. Without this, 30-40 GB of
images + the Loki PVC + chaos-mesh CRDs all land on the small root.

```bash
# Stop Docker
sudo systemctl stop docker.socket
sudo systemctl stop docker

# Copy anything already in /var/lib/docker to /data/docker (preserves
# pulled images / built layers from earlier steps if Docker has
# already been used).
sudo mkdir -p /data/docker
sudo rsync -aHX /var/lib/docker/ /data/docker/

# Update daemon.json to point at /data
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "data-root": "/data/docker",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
JSON

# Restart Docker
sudo systemctl start docker

# Verify
docker info | grep "Docker Root Dir"
# Expect: Docker Root Dir: /data/docker

docker run --rm hello-world
# Should succeed.

# Reclaim space (only AFTER you see the expected output above)
sudo rm -rf /var/lib/docker
df -h / /data
```

### Redirect JiraAndLogs `data/` and `logs/` to /data

The collection outputs (`data/runs/...`, `data/derived/...`, `logs/`)
grow to 50-60 GB during a v5-large run. Send them to `/data` too. Do
this AFTER cloning the repo (next section) — listed here for
reference.

```bash
# Run after `git clone ... JiraAndLogs && cd JiraAndLogs`
mkdir -p /data/jiraandlogs/data /data/jiraandlogs/logs

# If data/ or logs/ already exist in the repo as real dirs, move
# their contents to /data first:
if [ -d data ] && [ ! -L data ]; then
  [ -n "$(ls -A data 2>/dev/null)" ] && sudo mv data/* /data/jiraandlogs/data/ 2>/dev/null
  rmdir data
fi
if [ -d logs ] && [ ! -L logs ]; then
  [ -n "$(ls -A logs 2>/dev/null)" ] && sudo mv logs/* /data/jiraandlogs/logs/ 2>/dev/null
  rmdir logs
fi

# Create the symlinks
ln -s /data/jiraandlogs/data data
ln -s /data/jiraandlogs/logs logs

# Verify
ls -la data logs
# Expect both lines to show "-> /data/jiraandlogs/..."
```

### Final sanity check

```bash
echo "=== root disk ==="
df -h /

echo "=== attached disk ==="
df -h /data

echo "=== Docker on /data? ==="
docker info | grep "Docker Root Dir"

echo "=== JiraAndLogs storage on /data? ==="
ls -la ~/workplace/JiraAndLogs/data ~/workplace/JiraAndLogs/logs
```

Expected after these steps + a full v5-large run: root stays around
10-20 GB used (system + package install); `/data` grows to ~100-200 GB
used (Docker images ~30-40 GB, kind PVCs incl. Loki ~20-50 GB,
run output ~50-60 GB).

**Why not put `/var/lib/docker` on a symlink instead of using
`data-root`?** Docker explicitly does not support a symlinked
`/var/lib/docker` — file-locking and overlayfs behaviour break.
`data-root` in `daemon.json` is the supported path.

---

## VM: Install Kubernetes Tools

```bash
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
chmod +x kubectl
sudo mv kubectl /usr/local/bin/kubectl
rm -f kubectl.sha256

# kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# Helm
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-4
chmod 700 get_helm.sh
./get_helm.sh
rm -f get_helm.sh

# PowerShell (used by all collection scripts)
source /etc/os-release
wget -q "https://packages.microsoft.com/config/ubuntu/${VERSION_ID}/packages-microsoft-prod.deb"
sudo dpkg -i packages-microsoft-prod.deb
rm -f packages-microsoft-prod.deb
sudo apt-get update
sudo apt-get install -y powershell

# Verify all tools
docker version
kubectl version --client
kind version
helm version
pwsh -NoProfile -Command '$PSVersionTable.PSVersion'
```

---

## VM: Clone the Project (use the forks, not upstream)

The v5-large run depends on M0–M5 telemetry changes that live in the
**user's fork** of microservices-demo-google. Cloning upstream
Google's repo will produce images that lack ALL of the L1/L2/L3 logs,
RED metrics, and span enrichment.

```bash
mkdir -p ~/workplace
cd ~/workplace

# Main repo (run-plans, corpus manifests, scripts, kustomize overlay,
# scenario YAMLs including the 8 new D1 families):
git clone https://github.com/17YuvrajSehgal/JiraAndLogs.git JiraAndLogs
cd JiraAndLogs
git checkout master-bigger-dataset

# Microservices fork (M0-M5 instrumentation across the 10 services):
git clone https://github.com/17YuvrajSehgal/microservices-demo-google.git microservices-demo-google
cd microservices-demo-google
git checkout main
cd ..
```

Confirm both forks are at the expected HEADs:

```bash
git -C ~/workplace/JiraAndLogs log --oneline -1
git -C ~/workplace/JiraAndLogs/microservices-demo-google log --oneline -1
```

Python environment (only PyYAML is mandatory; build scripts otherwise
use stdlib):

```bash
cd ~/workplace/JiraAndLogs
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r scripts/research-lab/requirements.txt
python -c "import yaml; print('PyYAML', yaml.__version__)"
```

Set run variables (used in subsequent commands):

```bash
export RUN_PREFIX="2026-05-25-dataset-v5-large"
export GLOBAL_DATASET_ID="2026-05-25-dataset-v5-large-global"
export BENCHMARK_ID="triage-v5-baseline"
```

Pre-flight tool check:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/check-prereqs.ps1
```

---

## VM: Create the kind Cluster

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/create-kind-cluster.ps1
kubectl config use-context kind-jira-telemetry-lab
kubectl cluster-info
kubectl get nodes -o wide
```

Expected: 1 control-plane + 2 workers all `Ready`.

---

## VM: Install Observability

This installs Prometheus + Loki + Tempo + Grafana + Alloy + OpenTelemetry
collector via Helm, using the customized values files under
`deploy/research-lab/observability/values/`. The values files already
include the M0.4/M0.5 sizing (50 GiB Loki PVC, 2× collector replicas
at cpu=2/mem=2Gi limits, batch=16384), so a fresh install lands the
correct sizing without the destructive recreate sequence.

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/install-observability.ps1
kubectl wait --for=condition=Ready pods --all -n observability --timeout=900s
kubectl get pods -n observability -o wide
```

Confirm Loki has a persistent PVC bound (this is what unblocks the
cart-redis active_fault Loki export reliability gap):

```bash
kubectl -n observability get pvc storage-loki-0
# Expect: STATUS=Bound, CAPACITY=50Gi (or 120Gi if you bumped
# loki-values.yaml singleBinary.persistence.size)
```

Confirm collector is at 2 replicas with the new resources:

```bash
kubectl -n observability get pod -l app.kubernetes.io/name=opentelemetry-collector
# Expect: 2 pods Running
```

Apply the ServiceMonitor + headless Service for application-level
`/metrics` scrape (M4.1f). Without this, Prometheus only collects
spanmetrics + cAdvisor + kube-state-metrics — no business counters
(`payments_total`, `orders_placed_total`, etc.) and no RED metrics
from the app side.

```bash
kubectl apply -f deploy/research-lab/observability/online-boutique-servicemonitor.yaml
# Verify the ServiceMonitor was created:
kubectl -n observability get servicemonitor online-boutique-metrics
kubectl -n online-boutique-research get service online-boutique-metrics
```

The `service/online-boutique-metrics` won't have endpoints yet because
Online Boutique isn't deployed — that happens after image build.

---

## VM: Install chaos-mesh (required by the system-faults plan)

The v5-large corpus's `system-faults` plan (10 runs, 5 D11 scenarios per
run) injects DNS / network-partition / packet-loss / network-latency /
memory-pressure faults via chaos-mesh CRDs. Without chaos-mesh those 10
runs will fail at the first `kubectl apply -f <chaos manifest>` call.

Install chaos-mesh into its own `chaos-testing` namespace:

```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update

kubectl create namespace chaos-testing
helm install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-testing \
  --version 2.7.2 \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
  --set dashboard.create=false

kubectl wait --for=condition=Ready pods --all -n chaos-testing --timeout=300s
```

Notes:

- `chaosDaemon.runtime=containerd` + the matching socket path are
  correct for kind (which uses containerd). For Docker-runtime clusters
  use the chart's Docker defaults instead.
- `dashboard.create=false` skips the web UI — we don't need it for an
  unattended sweep and skipping saves ~150 MB of image pulls.
- Version pinned to `2.7.2` (the version validated against this
  repo's chaos manifests as of 2026-05-25).

Verify the CRDs are registered:

```bash
kubectl get crd | grep chaos-mesh.org
# Expect at least: networkchaos.chaos-mesh.org, stresschaos.chaos-mesh.org,
# podchaos.chaos-mesh.org, iochaos.chaos-mesh.org, dnschaos.chaos-mesh.org
```

Quick smoke (apply a NetworkChaos resource, verify the webhook accepts
it, force-delete via finalizer patch so we don't depend on the chaos
actually injecting against anything):

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: smoke-test
  namespace: chaos-testing
spec:
  action: delay
  mode: all
  selector:
    namespaces: [chaos-testing]
    labelSelectors:
      this-label: does-not-exist
  delay:
    latency: "100ms"
  duration: "5s"
EOF
# Resource creates, but with no matching pods chaos-mesh status stays
# at AllInjected: False forever. That's fine for the smoke — we only
# need to verify the admission webhook and CRD path work. Force-clean:
kubectl -n chaos-testing patch networkchaos smoke-test \
  --type=merge -p '{"metadata":{"finalizers":[]}}'
kubectl -n chaos-testing delete networkchaos smoke-test --grace-period=0 --force --ignore-not-found
```

If `networkchaos.chaos-mesh.org/smoke-test created` appears and the
patch+delete cycle completes within ~3s, chaos-mesh is healthy and
the admission webhook is up. If the `kubectl apply` itself fails with
a webhook error like "dial tcp ... connection refused", the
controller-manager pods aren't Ready — check:

```bash
kubectl -n chaos-testing get pods -l app.kubernetes.io/component=controller-manager
kubectl -n chaos-testing logs -l app.kubernetes.io/component=controller-manager --tail=30 | grep -E "ERROR|too many open"
```

The most common failure mode is `too many open files` — that means the
inotify sysctl bump above didn't actually apply. Re-run the
`sysctl --system` step and `kubectl -n chaos-testing delete pods --all`
to recycle the controller-managers.

**Escape hatches** (if you want to skip chaos-mesh or orphan coverage):

- **Skip system-faults entirely**: remove the `system-faults` entry
  from the `plans` array in
  `deploy/research-lab/corpora/dataset-v5-large.json` and rebalance the
  remaining `repeat` totals to 100 (e.g. bump `compact-a` from 14 to
  19, `compact-b` from 14 to 19). The rest of v5-large collects
  normally without chaos-mesh installed.
- **Skip orphan-fault coverage**: remove the `orphans` entry from the
  same `plans` array and rebalance. The orphan_fault_detection
  benchmark track will then report `no_orphan_data` (unmeasurable),
  but other tracks (triage_classification, ranking) are unaffected.
- **Skip both** (minimal v5 = upgraded telemetry but no D11/D12):
  remove both plans, rebalance to 100 across the v4 + D1 plans.

---

## VM: Build the M0–M5 Telemetry-Upgraded Images

The kustomize overlay pins **specific image tags** (e.g.
`cartservice:v5.0.0-otel-pilot3`). Those tags don't exist anywhere
public — they need to be built locally on the VM and loaded into the
kind cluster's container runtime.

10 services need rebuilding (`loadgenerator` + `redis-cart` keep their
upstream images intentionally):

```bash
cd ~/workplace/JiraAndLogs/microservices-demo-google/src

# Build context is microservices-demo-google/src/ for every service
# (needed because each Dockerfile copies sibling _shared-<lang>/ deps).

docker build -t cartservice:v5.0.0-otel-pilot3 -f cartservice/src/Dockerfile .
docker build -t paymentservice:v5.0.0-otel-pilot2 -f paymentservice/Dockerfile .
docker build -t currencyservice:v5.0.0-otel-pilot2 -f currencyservice/Dockerfile .
docker build -t recommendationservice:v5.0.0-otel-pilot2 -f recommendationservice/Dockerfile .
docker build -t emailservice:v5.0.0-otel-pilot4 -f emailservice/Dockerfile .
docker build -t frontend:v5.0.0-otel-pilot -f frontend/Dockerfile .
docker build -t checkoutservice:v5.0.0-otel-pilot -f checkoutservice/Dockerfile .
docker build -t productcatalogservice:v5.0.0-otel-pilot -f productcatalogservice/Dockerfile .
docker build -t shippingservice:v5.0.0-otel-pilot -f shippingservice/Dockerfile .
docker build -t adservice:v5.0.0-otel-pilot -f adservice/Dockerfile .
```

Expected total build time: **~20-30 minutes** on `e2-standard-8`
(cartservice and adservice are the longest at ~5-7 min each because of
.NET restore and Maven download respectively).

Load every image into the kind cluster (this copies them into kind's
containerd so the cluster can pull them locally):

```bash
for img in \
  cartservice:v5.0.0-otel-pilot3 \
  paymentservice:v5.0.0-otel-pilot2 \
  currencyservice:v5.0.0-otel-pilot2 \
  recommendationservice:v5.0.0-otel-pilot2 \
  emailservice:v5.0.0-otel-pilot4 \
  frontend:v5.0.0-otel-pilot \
  checkoutservice:v5.0.0-otel-pilot \
  productcatalogservice:v5.0.0-otel-pilot \
  shippingservice:v5.0.0-otel-pilot \
  adservice:v5.0.0-otel-pilot; do
    kind load docker-image "$img" --name jira-telemetry-lab
done
```

Expected total load time: ~5-8 minutes.

Verify the cluster sees them:

```bash
docker exec jira-telemetry-lab-worker crictl images | grep -E "v5\.0\.0-otel-pilot"
# Expect 10 lines, one per service.
```

---

## VM: Deploy Online Boutique

The kustomize overlay's `images:` block pins every service to its
`v5.0.0-otel-pilot*` tag (added 2026-05-25 — without this, a kustomize
apply silently reverts to upstream `:v0.10.5` which lacks all M0–M5
instrumentation). Verify the pins are present before applying:

```bash
cd ~/workplace/JiraAndLogs
grep -c "v5.0.0-otel-pilot" deploy/research-lab/online-boutique/kustomization.yaml
# Expect: 10 (one per modified service)
```

Render once to catch any kustomize problems:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/render-online-boutique.ps1 >/tmp/online-boutique-rendered.yaml
grep -E "image: (cartservice|paymentservice|frontend)" /tmp/online-boutique-rendered.yaml | head
# Expect: image strings with the v5.0.0-otel-pilot* tags above.
```

Apply:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/apply-online-boutique.ps1
kubectl wait --for=condition=Ready pods --all -n online-boutique-research --timeout=900s
kubectl get pods -n online-boutique-research -o wide
```

Confirm every pod is running its M0–M5 image (NOT upstream
`v0.10.5`):

```bash
kubectl -n online-boutique-research get deploy -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.template.spec.containers[0].image}{"\n"}{end}'
# Expect:
#   cartservice: cartservice:v5.0.0-otel-pilot3
#   paymentservice: paymentservice:v5.0.0-otel-pilot2
#   ...
#   loadgenerator: us-central1-docker.pkg.dev/google-samples/.../loadgenerator:v0.10.5  (intentionally upstream)
#   redis-cart: redis:alpine                                                            (intentionally upstream)
```

Confirm traffic is flowing:

```bash
kubectl logs -n online-boutique-research deploy/loadgenerator --tail=40 | head
```

Confirm the new metrics scrape is working (wait 30s for first scrape):

```bash
sleep 30
PROM_POD=$(kubectl -n observability get pod -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}')
kubectl -n observability port-forward $PROM_POD 19099:9090 >/tmp/prom-pf.log 2>&1 &
PF=$!; sleep 3
for m in payments_total cart_operations_total orders_placed_total \
         recommendations_served_total catalog_lookups_total \
         rpc_server_requests_total go_goroutines \
         process_runtime_dotnet_gc_collections_count_total \
         python_gc_objects_collected_total; do
  v=$(curl -s "http://127.0.0.1:19099/api/v1/query?query=count(${m})" | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else 'absent')" 2>/dev/null)
  echo "  $m: $v"
done
kill $PF 2>/dev/null; wait 2>/dev/null
```

You should see non-`absent` for at least 7 of the 9 metrics
(emailservice business counter and one or two others may need a minute
more). If everything is `absent`, the ServiceMonitor isn't picking up
pods — re-check that the headless Service `online-boutique-metrics`
exists in the `online-boutique-research` namespace.

Sanity-check disk:

```bash
df -h ~ | awk 'NR==2 {print "free disk:", $4}'
```

You should have at least 800 GB free on a 1 TB disk (or 350 GB on a
500 GB disk).

---

## VM: Mandatory Smoke Tests Before v5-Large

Before launching the 4-5 day collection, run **three short plan smokes**
to validate each of the new code paths (D1 family scenarios, D11
chaos-mesh, D12 orphan-fault gate). Each smoke is one run of one plan
(~45-90 min). Catching a harness issue here costs ~1.5 hours total;
catching it mid-way through day 3 of v5-large costs 3 days.

### Smoke 1 — D1 new families (~60-90 min)

Validates the 8 new scenario YAMLs + run plan against the M0–M5
telemetry layer.

```bash
cd ~/workplace/JiraAndLogs
source .venv/bin/activate

export SMOKE_RUN_ID="smoke-newfam-$(date -u +%Y%m%dT%H%M%SZ)"

pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/collect-dataset-plan.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" \
  -PlanFile "deploy/research-lab/run-plans/dataset-v5-new-families-a.json" \
  -PythonExe python3 -ForceNewRun -BuildDerived -PostWindowSeconds 30 \
  2>&1 | tee logs/$SMOKE_RUN_ID.log
```

Expected: exit 0, 12 episodes, ~75 windows, 5 Jira shadow issues,
recall@3 = 1.0 on the derived ranking dataset.

### Smoke 2 — D12 orphan-fault gate (~50-70 min)

Validates `produces_jira_ticket: false` end-to-end: orphan episodes
record windows but skip Jira generation.

```bash
export SMOKE_RUN_ID="smoke-orphans-$(date -u +%Y%m%dT%H%M%SZ)"

pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/collect-dataset-plan.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" \
  -PlanFile "deploy/research-lab/run-plans/dataset-v5-orphans.json" \
  -PythonExe python3 -ForceNewRun -BuildDerived -PostWindowSeconds 30 \
  2>&1 | tee logs/$SMOKE_RUN_ID.log

# After the smoke completes, build the matchings to validate
# expected_in_memory + is_novel invariants:
pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/build-triage-dataset.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" -PythonExe python3 -Force

pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/build-jira-memory-corpus.ps1 \
  -DatasetRunPrefix "smoke-orphans" \
  -GlobalDatasetId "smoke-orphans-global" \
  -PythonExe python3 -Force

pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/build-window-memory-matchings.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" \
  -GlobalDatasetId "smoke-orphans-global" \
  -PythonExe python3 -Force
```

Expected: exit 0, **10 episodes, 0 Jira shadow issues** (the critical
D12 invariant), final matchings line: `N ticket-worthy, 0 matched,
N novel` where every ticket-worthy window has `expected_in_memory:
false` + `is_novel: true`.

If `jira_shadow_issues.jsonl` line count is non-zero on this smoke,
the D12 gate is broken — do not proceed to v5-large.

### Smoke 3 — D11 system-faults via chaos-mesh (~45-60 min)

Validates the `ChaosMeshChaos` harness action: each chaos resource
applied, scenario runs, resource cleaned up (no lingering finalizers).

```bash
export SMOKE_RUN_ID="smoke-d11-$(date -u +%Y%m%dT%H%M%SZ)"

pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/collect-dataset-plan.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" \
  -PlanFile "deploy/research-lab/run-plans/dataset-v5-system-faults.json" \
  -PythonExe python3 -ForceNewRun -BuildDerived -PostWindowSeconds 30 \
  2>&1 | tee logs/$SMOKE_RUN_ID.log

# After completion, verify no chaos resources are stuck:
kubectl -n chaos-testing get networkchaos,dnschaos,stresschaos
```

Expected: exit 0, 7 episodes, ~50 windows, 5 Jira shadow issues
(1 per chaos), `No resources found` for the final
`kubectl get networkchaos,dnschaos,stresschaos`.

If chaos resources are stuck after the smoke completes, the bounded
delete / finalizer fallback in the harness isn't working — diagnose
before launching v5-large.

### Standard smoke expectations table

| Smoke | Plan | Episodes | Jira | Critical invariant |
| --- | --- | ---: | ---: | --- |
| newfam | `dataset-v5-new-families-a.json` | 12 | 5 | recall@3 = 1.0 |
| orphans | `dataset-v5-orphans.json` | 10 | **0** | every orphan window: `expected_in_memory: false` + `is_novel: true` |
| d11 | `dataset-v5-system-faults.json` | 7 | 5 | `kubectl get networkchaos,dnschaos,stresschaos` returns empty after the run |

Check the summary:

```bash
cat "data/runs/${SMOKE_RUN_ID}/summaries/data-quality-report.md" | head -30
ls -la "data/derived/${SMOKE_RUN_ID}/"
```

If exit code is non-zero OR the smoke log shows
"Port-forward exited early" / "Telemetry export failed" — diagnose
before launching the full sweep. Common causes:

| Error | Fix |
| --- | --- |
| `python is not recognized` | Confirm you passed `-PythonExe python3` |
| `Port-forward exited early for svc/loki-gateway` | Kill any leftover `kubectl port-forward` processes (`pkill -f "kubectl.*port-forward"`); rerun |
| `Activity does not contain a definition for RecordException` | Rebuilt cartservice from a stale checkout — pull latest and rebuild |
| All metric queries return `absent` | ServiceMonitor not applied — re-run the `kubectl apply -f deploy/research-lab/observability/online-boutique-servicemonitor.yaml` step |

---

## VM: Preview the v5-large Corpus

```bash
pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/collect-dataset-corpus.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-v5-large.json" \
  -DatasetRunPrefix "$RUN_PREFIX" \
  -PythonExe python3 \
  -PlanOnly
```

You should see (run index boundaries from the v5-large plan repeats:
8 / 14 / 14 / 11 / 11 / 8 / 24 / 10):

```text
Dataset corpus plan:
  corpus_id: dataset-v5-large
  planned_runs: 100
  selected_runs: 100
  [1]  2026-05-25-dataset-v5-large-control-r01            -> control-baseline-only.json
  [2]  2026-05-25-dataset-v5-large-control-r02            -> ...
  ...
  [9]  2026-05-25-dataset-v5-large-compact-a-r01          -> compact-a
  [23] 2026-05-25-dataset-v5-large-compact-b-r01          -> compact-b
  [37] 2026-05-25-dataset-v5-large-new-families-a-r01     -> new-families-a
  [48] 2026-05-25-dataset-v5-large-new-families-b-r01     -> new-families-b
  [59] 2026-05-25-dataset-v5-large-long-running-r01       -> long-running
  [67] 2026-05-25-dataset-v5-large-orphans-r01            -> orphans
  [91] 2026-05-25-dataset-v5-large-system-faults-r01      -> system-faults
```

Control runs come first as the false-positive anchor; long-running and
chaos-mesh runs come later because they're slower and have more
stringent prerequisites.

---

## VM: Launch the v5-Large Collection

Pre-flight: kill any leftover kubectl port-forwards from the smoke or
prior sessions (these are the #1 cause of pilot crashes; the launcher
script also kills them defensively but check first):

```bash
pkill -f "kubectl.*port-forward" 2>/dev/null || true
sleep 3
ss -lntp 2>/dev/null | grep -E ":13100|:13200|:19090|:19093" || echo "ports clean"
```

Start a tmux session so SSH disconnects don't kill the run:

```bash
tmux new -s v5-large
cd ~/workplace/JiraAndLogs
source .venv/bin/activate
mkdir -p logs
```

Launch:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/collect-dataset-corpus.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-v5-large.json" \
  -DatasetRunPrefix "$RUN_PREFIX" \
  -GlobalDatasetId "$GLOBAL_DATASET_ID" \
  -PythonExe python3 \
  -Quick \
  -BuildTriage \
  -HaltOnValidationFail \
  -SkipDerivedBuild \
  -SkipAggregateBuild \
  2>&1 | tee "logs/${RUN_PREFIX}-corpus.log"
```

What the flags do:

- `-PythonExe python3`: required on Ubuntu where only `python3` is on PATH.
- `-Quick`: shortens scenarios to the plan's quick durations (e.g.
  60s active fault + 30s post-window for the new-families plans).
- `-BuildTriage`: after every run, build triage examples + per-window
  memory matchings + (at end) global triage dataset + Jira memory
  corpus.
- `-HaltOnValidationFail`: stop the corpus immediately if any per-run
  validation fails (zero-signal ticket_worthy windows, all-zero
  features, etc.). Prevents wasting compute on a broken cluster.
- `-SkipDerivedBuild` + `-SkipAggregateBuild`: skip the legacy
  ranking pipeline; v5 is a triage corpus, not a retrospective ranking
  corpus.

Detach from tmux with `Ctrl-b d`. Reattach later with
`tmux attach -t v5-large`.

---

## VM: Monitor Progress

From a second SSH session (or after detaching tmux):

```bash
cd ~/workplace/JiraAndLogs
source .venv/bin/activate

# Where are we?
cat "data/derived/corpora/${RUN_PREFIX}/corpus-run-manifest.json" \
  | jq '{completed: .completed_run_count, selected: .selected_run_count, status: .status}'

# Latest data quality reports (newest 5)
ls -lt data/runs/${RUN_PREFIX}-*/summaries/data-quality-report.md 2>/dev/null | head -5

# Disk free + Loki disk usage
df -h ~ | tail -1
kubectl -n observability exec loki-0 -c loki -- du -sh /var/loki 2>/dev/null

# Live tail of the corpus log
tail -f "logs/${RUN_PREFIX}-corpus.log"
```

Inspect a single completed run:

```bash
cat data/runs/${RUN_PREFIX}-compact-a-r01/summaries/data-quality-report.md
cat data/runs/${RUN_PREFIX}-compact-a-r01/summaries/feature-distribution.md
cat data/runs/${RUN_PREFIX}-compact-a-r01/manifest.json | jq '.git, .builder_hashes, .tool_versions'
```

If disk free drops below 100 GB mid-run, prune older raw Loki chunks
(Loki has 7-day retention by default so this only matters if your VM
is 500 GB and the run extends beyond 4 days):

```bash
# Loki retention is governed by loki-values.yaml retention_period (168h).
# To force an earlier compaction:
kubectl -n observability exec loki-0 -c loki -- /usr/bin/loki -- \
  -config.file=/etc/loki/config/config.yaml -target=compactor \
  -compactor.retention-enabled=true -compactor.retention-delete-delay=1h
```

---

## VM: Resume After Interruption

If the corpus stops (validation fail, VM reboot, OOM), fix the underlying
issue and **rerun the same command**. The runner detects completed runs
by the presence of `manifest.json` + a validation report, so completed
runs are skipped automatically:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/collect-dataset-corpus.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-v5-large.json" \
  -DatasetRunPrefix "$RUN_PREFIX" \
  -GlobalDatasetId "$GLOBAL_DATASET_ID" \
  -PythonExe python3 \
  -Quick \
  -BuildTriage \
  -HaltOnValidationFail \
  -SkipDerivedBuild \
  -SkipAggregateBuild \
  2>&1 | tee -a "logs/${RUN_PREFIX}-corpus.log"
```

**Do NOT add `-ForceNewRun`** — that discards completed runs.

If a single run completed but its triage build failed, fix the issue
then re-run the triage build directly on that run:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/build-triage-dataset.ps1 \
  -DatasetRunId "${RUN_PREFIX}-control-r03" \
  -PythonExe python3 -Force
```

---

## VM: Run the Triage Benchmark

After all 100 runs finish (or after you stop the sweep early to inspect
intermediate results), run the baseline triage benchmark:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass \
  -File scripts/research-lab/run-triage-benchmark.ps1 \
  -GlobalDatasetId "$GLOBAL_DATASET_ID" \
  -BenchmarkId "$BENCHMARK_ID" \
  -PythonExe python3 \
  -Force
```

This trains rule + logistic baselines on the family-level split and
reports:

- Headline PR-AUC / ROC-AUC / ECE on held-out test families
- Precision@FPR=1% and 5% operating points
- Leave-one-family-out macro PR-AUC / ROC-AUC across all **27 families**
- Per-family and per-`is_hard_case` stratified metrics
- Feature weights for inspection
- **Orphan-detection recall gap** (D12.6): `recall_reported` vs
  `recall_orphan` vs `gap_pts` per pipeline. Verdict bucket:
  `signal_learning` (gap < 10pts), `borderline` (10-20),
  `pattern_matching` (> 20). This is the headline "memorisation vs
  detection" answer the v5 corpus is designed to give.

Read the headline:

```bash
cat data/derived/global/${GLOBAL_DATASET_ID}/benchmarks/${BENCHMARK_ID}/benchmark-report.md
```

---

## VM: Post-Run Validation

```bash
# Corpus completeness
cat "data/derived/corpora/${RUN_PREFIX}/corpus-run-manifest.json" \
  | jq '{completed: .completed_run_count, selected: .selected_run_count, status: .status}'

# Global triage dataset
ls "data/derived/global/${GLOBAL_DATASET_ID}/"
wc -l "data/derived/global/${GLOBAL_DATASET_ID}/global-triage-examples.jsonl"
cat "data/derived/global/${GLOBAL_DATASET_ID}/triage-split-manifest.json" \
  | jq '.family_assignment, .label_counts_by_split'

# Jira memory corpus
wc -l "data/derived/global/${GLOBAL_DATASET_ID}/jira-memory-corpus.jsonl"

# Any failed runs?
grep -l '"passed": false' data/runs/${RUN_PREFIX}-*/summaries/data-quality-report.json \
  || echo "no failed runs"

# Leakage canary across all completed runs
for run in data/runs/${RUN_PREFIX}-*; do
  rid=$(basename $run)
  pwsh -NoProfile -ExecutionPolicy Bypass \
    -File scripts/research-lab/validate-run-feature-distribution.ps1 \
    -DatasetRunId "$rid" -PythonExe python3 2>&1 | tail -1
done
```

**A fully complete v5-large collection has:**

| Asset | Expected |
| --- | ---: |
| Entries in corpus manifest with `status: completed` | 100 |
| Rows in `global-triage-examples.jsonl` | ~7,400 |
| Entries in `jira-memory-corpus.jsonl` | ~430 (orphan windows do NOT contribute Jira entries by design) |
| Scenario families in the split manifest | 27 |
| Long-window (≥10 min) episodes | ~96 |
| **Orphan ticket_worthy windows** (D12) | **192** (24 orphan runs × 8 orphan ticket_worthy windows/run) |
| **Chaos-mesh ticket_worthy windows** (D11) | **40** (10 system-fault runs × 4 ticket_worthy chaos scenarios/run; the 5th chaos is borderline) |
| `"passed": false` data-quality reports | 0 |
| Leakage canary fails | 0 |
| **Lingering chaos resources** (`kubectl -n chaos-testing get networkchaos,dnschaos,stresschaos`) | **empty** (every chaos resource cleaned up by the bounded delete + finalizer fallback) |

---

## Local Machine: Download the Data

From your laptop:

```bash
mkdir -p ~/jira-logs-dataset-v5-large
cd ~/jira-logs-dataset-v5-large
```

Download derived files first (the ML-ready ~20 GB chunk):

```bash
gcloud compute scp --recurse \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  jira-logs-dataset-v5-vm:~/workplace/JiraAndLogs/data/derived \
  ./
```

Download the collection log + smoke log:

```bash
gcloud compute scp \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  'jira-logs-dataset-v5-vm:~/workplace/JiraAndLogs/logs/*.log' \
  ./logs/
```

Optionally, download the raw runs (~30-40 GB — only if you need the
raw telemetry; derived is enough for training/benchmarking). Compress
on the VM first to save bandwidth:

```bash
# On the VM:
cd ~/workplace/JiraAndLogs
tar -czf ~/data-runs-v5-large.tar.gz data/runs
ls -lh ~/data-runs-v5-large.tar.gz
```

Then from your laptop:

```bash
gcloud compute scp \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  jira-logs-dataset-v5-vm:~/data-runs-v5-large.tar.gz \
  ./
tar -xzf data-runs-v5-large.tar.gz
```

Verify the download on your laptop:

```bash
ls -1 ~/jira-logs-dataset-v5-large/derived/global/2026-05-25-dataset-v5-large-global/
# Should list: global-triage-examples.jsonl, jira-memory-corpus.jsonl,
# triage-split-manifest.json, benchmarks/, etc.
```

---

## Local Machine: Stop or Delete the VM

**Re-confirm the local copy first** before touching the VM:

```bash
ls -1 ~/jira-logs-dataset-v5-large/derived/global/2026-05-25-dataset-v5-large-global/
wc -l ~/jira-logs-dataset-v5-large/derived/global/2026-05-25-dataset-v5-large-global/global-triage-examples.jsonl
```

Stop the VM (compute stops, disk still bills):

```bash
gcloud compute instances stop jira-logs-dataset-v5-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a
```

Delete the VM (auto-delete on the boot disk removes the 1 TB volume too):

```bash
gcloud compute instances delete jira-logs-dataset-v5-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a
```

Confirm no leftover disks:

```bash
gcloud compute disks list \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --filter="name~jira-logs-dataset-v5-vm"
# Expect: empty
```

---

## v5-large Sizing Addendum (background)

`deploy/research-lab/corpora/dataset-v5-large.json` defines a 100-run
sweep (2.5× v4-large) on the M0–M5 upgraded telemetry. Raw data growth
vs v4-large:

- Per-run log volume up ~3-5× because of the new L1/L2/L3 layers
  (`microservice-changes-todo.md` M0.5 estimate). Estimated raw export
  per run: 200-400 MB (vs ~80-130 MB on v4-large).
- 100 runs × 300 MB ≈ **30-40 GB raw telemetry**.
- Long-running plan (8 runs × ~30 min) adds ~5-8 GB.
- Orphans plan (24 runs × ~50 min each) adds ~10-15 GB (orphan runs
  produce the same telemetry as their non-orphan twins, just no Jira
  shadow rows).
- System-faults plan (10 runs × ~50 min each) adds ~5-10 GB.
  chaos-mesh injects produce noisier telemetry (more error logs, more
  span errors) than the equivalent application-level scenarios.
- Derived datasets add ~15-20 GB.
- Loki PVC (persistent) holds another 50-120 GiB while runs are in
  flight.
- chaos-mesh container images: another ~300 MB on the kind nodes (the
  chaos-daemon, controller-manager, and chaos-dns-server images).

**Binding target sizing** (when starting fresh on a new GCP VM):

| Setting | Binding target |
| --- | --- |
| Boot disk | **1 TB** `pd-balanced` |
| Loki PVC | **120 GiB** (edit `loki-values.yaml` `singleBinary.persistence.size` before install) |
| OTel collector | replicas=2, cpu=2/mem=2Gi limits, batch=16384 (already in the values file) |
| VM type | `e2-standard-8` |

If you provision a smaller disk (e.g. 500 GB), keep Loki at 50 GiB
(the default in our values file today) and plan to prune chunks
mid-run.

---

## Historical: dataset-v4-large

The v4-large corpus
(`deploy/research-lab/corpora/dataset-v4-large.json`, 40 runs,
13 families, no M0–M5 telemetry) still works on the same VM
infrastructure. Use the same commands above but substitute:

```bash
export RUN_PREFIX="2026-05-22-dataset-v4-large"
export GLOBAL_DATASET_ID="2026-05-22-dataset-v4-large-global"
# Then in the launch command:
#   -CorpusFile "deploy/research-lab/corpora/dataset-v4-large.json"
```

v4-large takes ~24-30 hours, produces ~3,700 windows, and does NOT
require the image-build step (it works with upstream `:v0.10.5`
images, since v4-large's scenarios don't depend on M0–M5
instrumentation).

---

## Reference Sources

- Google Compute Engine `e2-standard-8` shape:
  `https://cloud.google.com/compute/docs/general-purpose-machines`
- Compute Engine pricing:
  `https://cloud.google.com/compute/all-pricing`
- Persistent disk behavior:
  `https://cloud.google.com/compute/docs/disks/persistent-disks`
- Cloud billing budgets:
  `https://cloud.google.com/billing/docs/how-to/budgets`
- Docker Engine on Ubuntu:
  `https://docs.docker.com/engine/install/ubuntu/`
- `kubectl` install:
  `https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/`
- kind quick start:
  `https://kind.sigs.k8s.io/docs/user/quick-start/`
- Helm install:
  `https://helm.sh/docs/intro/install/`
- PowerShell on Ubuntu:
  `https://learn.microsoft.com/powershell/scripting/install/install-ubuntu`
