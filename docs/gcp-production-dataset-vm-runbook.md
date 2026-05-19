# GCP VM Runbook For Production Dataset Collection

This runbook explains how to create a cost-controlled Google Cloud VM, install
the full research lab from scratch, run a larger production-style dataset
collection, back up the outputs, and shut everything down.

Use this when you want to run a multi-hour or multi-day dataset collection on a
Google Cloud VM instead of a laptop.

## Recommended VM Shape

Use a single Compute Engine VM running Ubuntu, Docker, kind, and the project
scripts.

Do not use GKE for this stage. A single VM with kind is cheaper, simpler, and
closer to the current local research setup.

Recommended default:

| Setting | Value |
| --- | --- |
| VM type | `e2-standard-8` |
| vCPU / RAM | 8 vCPU, 32 GB RAM |
| OS | Ubuntu 24.04 LTS x86_64 |
| Boot disk | 500 GB `pd-balanced` |
| Provisioning | Standard VM, not Spot, for unattended multi-day runs |
| Region | `us-central1` unless you have a reason to use another region |
| Kubernetes | kind cluster with 1 control-plane and 2 workers |

Why this shape:

- `e2-standard-8` is cost-optimized and has enough memory for Online Boutique,
  Prometheus, Loki, Tempo, Grafana, Alloy, OpenTelemetry Collector, and kind.
- 500 GB gives room for Docker images, Kubernetes volumes, raw telemetry, derived
  datasets, logs, and retries.
- `pd-balanced` is a good cost/performance tradeoff for this workload.
- Standard VM avoids Spot interruption during a long unattended collection.

Use `e2-standard-16` only if:

- the VM shows sustained memory pressure,
- Docker image pulls and telemetry exports are too slow,
- you want to shorten a multi-day collection and accept roughly double compute
  cost.

Use Spot only if:

- you are running in small batches,
- you back up after each batch,
- you are comfortable resuming after preemption.

## Cost Controls

Before creating the VM:

1. Create a billing budget alert.
2. Use labels on the VM.
3. Use a unique VM name.
4. Back up results to a GCS bucket.
5. Stop or delete the VM immediately after the run.

Important cost notes:

- Stopping the VM stops compute charges, but disk charges continue.
- Deleting the VM deletes the boot disk only if auto-delete is enabled.
- GCS storage also costs money.
- External network egress can cost money, but this workflow should mostly pull
  images and write data inside the same project.
- Do not buy a committed-use discount for this short research run.

As of the checked Google pricing page, `e2-standard-8` in `us-central1` is listed
at about `$0.26804568/hour` on demand. That means 72 hours of compute is roughly
`$19.30`, excluding disk, storage, network, taxes, and pricing changes. Always
verify with the Google Cloud Pricing Calculator before launching.

## What Dataset To Run On The VM

For a bigger cloud run, use the cloud-balanced corpus manifest:

```text
deploy/research-lab/corpora/dataset-v3-cloud-balanced-corpus.json
```

It creates 16 planned dataset runs:

| Batch | Runs |
| --- | --- |
| 1 | foundation, outage-heavy, restart-traffic, latency-config |
| 2 | foundation, outage-heavy, restart-traffic, latency-config |
| 3 | foundation, outage-heavy, restart-traffic, latency-config |
| 4 | foundation, outage-heavy, restart-traffic, latency-config |

This is intentionally larger than the compact 6-run corpus but smaller than the
older 40-run stress design. It should give a stronger dataset for ML, NLP, LLM,
and agent benchmarks without wasting days on repeated same-family runs.

## Local Machine: Create The VM

Run these commands from your local machine where `gcloud` is installed.

Set variables:

```bash
export PROJECT_ID="YOUR_GCP_PROJECT_ID"
export REGION="us-central1"
export ZONE="us-central1-a"
export VM_NAME="jira-logs-dataset-vm"
export MACHINE_TYPE="e2-standard-8"
export BOOT_DISK_SIZE="500GB"
export BUCKET="gs://${PROJECT_ID}-jira-logs-dataset"
```

Authenticate and select the project:

```bash
gcloud auth login
gcloud config set project "$PROJECT_ID"
```

Enable required APIs:

```bash
gcloud services enable compute.googleapis.com storage.googleapis.com cloudbilling.googleapis.com
```

Optional but strongly recommended: create a project budget alert. If the CLI
budget command is not available for your account permissions, create it in the
Google Cloud Console under Billing -> Budgets & alerts.

```bash
export BILLING_ACCOUNT_ID="YOUR_BILLING_ACCOUNT_ID"
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

gcloud billing budgets create \
  --billing-account="$BILLING_ACCOUNT_ID" \
  --display-name="JiraAndLogs dataset VM budget" \
  --budget-amount=75USD \
  --filter-projects="projects/${PROJECT_NUMBER}" \
  --threshold-rule=percent=0.5,basis=CURRENT_SPEND \
  --threshold-rule=percent=0.9,basis=CURRENT_SPEND \
  --threshold-rule=percent=1.0,basis=CURRENT_SPEND
```

Create a GCS bucket for backups. Bucket names are globally unique, so change the
name if this fails:

```bash
gcloud storage buckets create "$BUCKET" \
  --location="$REGION" \
  --uniform-bucket-level-access
```

Create the VM:

```bash
gcloud compute instances create "$VM_NAME" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --provisioning-model=STANDARD \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size="$BOOT_DISK_SIZE" \
  --boot-disk-type=pd-balanced \
  --scopes=https://www.googleapis.com/auth/cloud-platform \
  --labels=project=jiraandlogs,purpose=dataset,env=research \
  --metadata=enable-oslogin=TRUE
```

SSH into the VM:

```bash
gcloud compute ssh "$VM_NAME" --zone="$ZONE"
```

## VM: Install Base Packages

Run the rest of this guide inside the VM.

```bash
set -euo pipefail

sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  git \
  jq \
  unzip \
  zip \
  tar \
  tmux \
  htop \
  rsync \
  python3 \
  python3-venv \
  python3-pip \
  apt-transport-https \
  software-properties-common
```

## VM: Install Docker Engine

Install Docker from Docker's official apt repository:

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
```

Add Docker log rotation so container logs do not fill the disk:

```bash
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
```

Refresh your shell group membership:

```bash
newgrp docker
```

Verify Docker:

```bash
docker version
docker run --rm hello-world
```

## VM: Install Kubernetes Tools

Install `kubectl`:

```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
chmod +x kubectl
sudo mv kubectl /usr/local/bin/kubectl
rm -f kubectl.sha256
```

Install kind:

```bash
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind
```

Install Helm:

```bash
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-4
chmod 700 get_helm.sh
./get_helm.sh
rm -f get_helm.sh
```

Install PowerShell:

```bash
source /etc/os-release
wget -q "https://packages.microsoft.com/config/ubuntu/${VERSION_ID}/packages-microsoft-prod.deb"
sudo dpkg -i packages-microsoft-prod.deb
rm -f packages-microsoft-prod.deb
sudo apt-get update
sudo apt-get install -y powershell
```

Install Google Cloud CLI for backups from the VM:

```bash
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg

echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list >/dev/null

sudo apt-get update
sudo apt-get install -y google-cloud-cli
```

Verify tools:

```bash
docker version
kubectl version --client
kind version
helm version
pwsh -NoProfile -Command '$PSVersionTable.PSVersion'
gcloud version
```

## VM: Clone The Project

Clone this repository. Replace the repository URL with the real remote.

Important: push the current branch before cloning, because the Linux portability
fixes and the cloud-balanced corpus manifest must be present on the VM.

```bash
mkdir -p ~/workplace
cd ~/workplace
git clone "YOUR_JIRA_AND_LOGS_REPO_URL" JiraAndLogs
cd JiraAndLogs
```

Clone Online Boutique into the expected folder:

```bash
git clone https://github.com/GoogleCloudPlatform/microservices-demo.git microservices-demo-google
```

Create the Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

The current research scripts use the Python standard library, so no extra Python
packages are required for dataset building and baseline benchmarking.

Set run variables inside the VM. Use the real bucket you created earlier:

```bash
export RUN_PREFIX="$(date -u +%Y-%m-%d)-dataset-v3-gcp-balanced"
export GLOBAL_DATASET_ID="${RUN_PREFIX}-global"
export BENCHMARK_ID="baseline-v1"
export BUCKET="gs://YOUR_BUCKET_NAME"
```

Check prerequisites:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/check-prereqs.ps1
```

Run the static part of the cloud preflight before creating the cluster:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/test-cloud-dataset-preflight.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-v3-cloud-balanced-corpus.json" \
  -DatasetRunPrefix "preflight-static" \
  -Bucket "$BUCKET" \
  -SkipClusterChecks
```

## VM: Create The kind Cluster

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/create-kind-cluster.ps1
kubectl config use-context kind-jira-telemetry-lab
kubectl cluster-info
kubectl get nodes -o wide
```

The project kind config creates three nodes:

```text
1 control-plane
2 workers
```

## VM: Install Observability

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/install-observability.ps1
kubectl wait --for=condition=Ready pods --all -n observability --timeout=900s
kubectl get pods -n observability -o wide
```

## VM: Deploy Online Boutique

Render once to catch Kustomize problems:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/render-online-boutique.ps1 >/tmp/online-boutique-rendered.yaml
head -40 /tmp/online-boutique-rendered.yaml
```

Apply the app:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/apply-online-boutique.ps1
kubectl wait --for=condition=Ready pods --all -n online-boutique-research --timeout=900s
kubectl get pods -n online-boutique-research -o wide
```

Check traffic:

```bash
kubectl logs -n online-boutique-research deploy/loadgenerator --tail=80
```

Run the full cloud preflight after the cluster, observability stack, and Online
Boutique are ready:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/test-cloud-dataset-preflight.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-v3-cloud-balanced-corpus.json" \
  -DatasetRunPrefix "$RUN_PREFIX" \
  -Bucket "$BUCKET" \
  -MinFreeDiskGb 250
```

Do not start the multi-day dataset run if this preflight reports failures.

## VM: Preview The Cloud Corpus

Preview the 16 planned runs:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/collect-dataset-corpus.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-v3-cloud-balanced-corpus.json" \
  -DatasetRunPrefix "$RUN_PREFIX" \
  -PlanOnly
```

## VM: Recommended Batch Collection

For a multi-day run, use four-run batches. Each batch includes all major plan
families, and the wrapper can resume completed runs.

Start a persistent terminal session:

```bash
tmux new -s dataset
cd ~/workplace/JiraAndLogs
source .venv/bin/activate
set -euo pipefail
mkdir -p logs
```

Run all four batches:

```bash
for START_AT in 1 5 9 13; do
  echo "Starting corpus batch at index ${START_AT}"

  pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/collect-dataset-corpus.ps1 \
    -CorpusFile "deploy/research-lab/corpora/dataset-v3-cloud-balanced-corpus.json" \
    -DatasetRunPrefix "$RUN_PREFIX" \
    -StartAt "$START_AT" \
    -MaxRuns 4 \
    2>&1 | tee "logs/${RUN_PREFIX}-batch-${START_AT}.log"

  gcloud storage rsync -r data/runs "${BUCKET}/${RUN_PREFIX}/data/runs"
  gcloud storage rsync -r data/derived "${BUCKET}/${RUN_PREFIX}/data/derived"
done
```

If SSH disconnects:

```bash
tmux attach -t dataset
```

If a batch fails:

1. Inspect the last log in `logs/`.
2. Fix the problem.
3. Rerun the same batch command without deleting completed runs.
4. Do not use `-ForceNewRun` unless you intentionally want to overwrite the
   selected run range.

## VM: Build Global Dataset And Benchmarks

After all corpus runs finish:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/build-global-hard-negative-dataset.ps1 \
  -DatasetRunPrefix "$RUN_PREFIX" \
  -GlobalDatasetId "$GLOBAL_DATASET_ID" \
  -Force
```

Run the first benchmark harness:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/run-global-pipeline-benchmark.ps1 \
  -GlobalDatasetId "$GLOBAL_DATASET_ID" \
  -BenchmarkId "$BENCHMARK_ID" \
  -Force
```

Back up final outputs:

```bash
gcloud storage rsync -r data/runs "${BUCKET}/${RUN_PREFIX}/data/runs"
gcloud storage rsync -r data/derived "${BUCKET}/${RUN_PREFIX}/data/derived"
gcloud storage cp logs/*.log "${BUCKET}/${RUN_PREFIX}/logs/"
```

## VM: What To Check After The Run

Check the corpus manifest:

```bash
cat "data/derived/corpora/${RUN_PREFIX}/corpus-run-manifest.json" | jq .
```

Check aggregate and holdout reports:

```bash
ls -R "data/derived/aggregate/${RUN_PREFIX}-aggregate"
ls -R "data/derived/holdout/${RUN_PREFIX}-holdout"
```

Check global dataset output:

```bash
ls -R "data/derived/global/${GLOBAL_DATASET_ID}"
cat "data/derived/global/${GLOBAL_DATASET_ID}/global-ranking-report.md"
```

Check benchmark output:

```bash
cat "data/derived/global/${GLOBAL_DATASET_ID}/benchmarks/${BENCHMARK_ID}/benchmark-report.md"
```

## Local Machine: Stop Or Delete The VM

When the run is complete and backed up, stop the VM if you may come back soon:

```bash
gcloud compute instances stop "$VM_NAME" --zone="$ZONE"
```

Delete the VM when you no longer need it:

```bash
gcloud compute instances delete "$VM_NAME" --zone="$ZONE"
```

If you delete the VM, confirm whether the boot disk was auto-deleted:

```bash
gcloud compute disks list --filter="name~${VM_NAME}"
```

Delete leftover disks only after confirming the data is backed up:

```bash
gcloud compute disks delete "DISK_NAME" --zone="$ZONE"
```

## Reference Sources Checked

- Google Compute Engine E2 machine types and `e2-standard-8` shape:
  `https://cloud.google.com/compute/docs/general-purpose-machines`
- Google Compute Engine pricing:
  `https://cloud.google.com/compute/all-pricing`
- Google Persistent Disk behavior and disk type notes:
  `https://cloud.google.com/compute/docs/disks/persistent-disks`
- Google Cloud budget alerts:
  `https://cloud.google.com/billing/docs/how-to/budgets`
- Docker Engine on Ubuntu:
  `https://docs.docker.com/engine/install/ubuntu/`
- Kubernetes `kubectl` install:
  `https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/`
- kind quick start:
  `https://kind.sigs.k8s.io/docs/user/quick-start/`
- Helm install:
  `https://helm.sh/docs/intro/install/`
- PowerShell on Ubuntu:
  `https://learn.microsoft.com/powershell/scripting/install/install-ubuntu`
