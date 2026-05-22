# GCP VM Runbook For Production Dataset Collection

This runbook explains how to create a cost-controlled Google Cloud VM, install
the full research lab from scratch, run the **Dataset v4 large** triage corpus
(40 runs, ~1.5-2 days), back up the outputs, and shut everything down.

Use this when you want to run a multi-day dataset collection on a Google Cloud
VM instead of a laptop. The active product framing is the Jira-as-memory
triage task; see `docs/triage-task-contract.md` and `docs/dataset-v4-plan.md`
for what we collect and why.

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
| Boot disk | 500 GB `pd-balanced` (allows ~150 GB raw telemetry + Docker images + headroom) |
| Provisioning | Standard VM, not Spot, for unattended multi-day runs |
| Region | `us-central1` unless you have a reason to use another region |
| Kubernetes | kind cluster with 1 control-plane and 2 workers |

The v4 large corpus produces ~90-130 GB of raw telemetry plus ~5-10 GB of
derived files. 500 GB boot disk covers that plus Docker images, system
overhead, and a buffer for retries.

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

1. Create a billing budget alert (optional but recommended).
2. Use labels on the VM (already in the create command below).
3. Use a unique VM name (set below).
4. Stop or delete the VM immediately after the run.
5. Download the collected data to your laptop before deleting (instructions
   later in this runbook).

Important cost notes:

- Stopping the VM stops compute charges, but disk charges continue.
- Deleting the VM deletes the boot disk only if auto-delete is enabled.
- Network egress when downloading data to your laptop is metered but small
  for this dataset (~100 GB at standard pricing).
- Do not buy a committed-use discount for this short research run.

As of the checked Google pricing page, `e2-standard-8` in `us-central1` is listed
at about `$0.26804568/hour` on demand. That means 72 hours of compute is roughly
`$19.30`, excluding disk, network, taxes, and pricing changes. Always verify
with the Google Cloud Pricing Calculator before launching.

This runbook does not use a GCS bucket. Data stays on the VM disk during
collection and is downloaded directly to your laptop afterward.

## What Dataset To Run On The VM

For the multi-day VM collection, use the v4 large corpus manifest:

```text
deploy/research-lab/corpora/dataset-v4-large.json
```

It creates 40 planned dataset runs:

| Plan alias | Repeats | Per-run scenarios | Per-run windows | Purpose |
| --- | ---: | ---: | ---: | --- |
| `control` (baseline-only) | 8 | 6 | ~24 | False-positive anchor, no faults |
| `compact-a` | 16 | 10 | ~78 | Latency, dependency outage, restart, Redis degradation, bad config, near-miss |
| `compact-b` | 16 | 13 | ~114 | Service-diverse outages, frontend / Redis restarts, intermittent failure, noisy traffic |

Expected scale at completion:

| Item | Value |
| --- | ---: |
| Dataset runs | 40 |
| Total episodes | ~416 |
| Total telemetry windows | ~3700 |
| Scenario families | 13 |
| Shadow Jira memory corpus | ~260 entries |
| Raw data size | ~90-130 GB |
| Collection wall time (Quick mode) | ~24-30 hours |

This corpus is intentionally large enough to train non-trivial ML and AI
models with run-level holdouts and to fit lexical / retrieval / language-model
baselines on top of the same data.

A smaller pilot corpus (`dataset-v4-pilot-extended.json`, 13 runs, ~8-10
hours) is available for laptop validation but not recommended for the VM.

## Local Machine: Create The VM

Run these commands from your local machine where `gcloud` is installed. All
values are filled in for this project; no manual substitution is required
except for the optional billing budget step.

Authenticate and select the project:

```bash
gcloud auth login
gcloud config set project project-dfc1abf4-e3f9-44ce-8a3
```

Enable the required API:

```bash
gcloud services enable compute.googleapis.com
```

Optional (recommended): create a project budget alert. This step requires
your billing account ID, which the gcloud CLI cannot infer automatically.
Look it up with `gcloud billing accounts list`, then run:

```bash
# Replace BILLING_ACCOUNT_ID below with the value from
#   gcloud billing accounts list --format='value(name)'
# A billing account ID looks like 0X0X0X-0X0X0X-0X0X0X.

PROJECT_NUMBER="$(gcloud projects describe project-dfc1abf4-e3f9-44ce-8a3 --format='value(projectNumber)')"

gcloud billing budgets create \
  --billing-account="BILLING_ACCOUNT_ID" \
  --display-name="JiraAndLogs dataset VM budget" \
  --budget-amount=75USD \
  --filter-projects="projects/${PROJECT_NUMBER}" \
  --threshold-rule=percent=0.5,basis=CURRENT_SPEND \
  --threshold-rule=percent=0.9,basis=CURRENT_SPEND \
  --threshold-rule=percent=1.0,basis=CURRENT_SPEND
```

If you skip the budget step, set a manual reminder to delete the VM after
collection.

Create the VM:

```bash
gcloud compute instances create jira-logs-dataset-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  --machine-type=e2-standard-8 \
  --provisioning-model=STANDARD \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=500GB \
  --boot-disk-type=pd-balanced \
  --scopes=https://www.googleapis.com/auth/cloud-platform \
  --labels=project=jiraandlogs,purpose=dataset,env=research \
  --metadata=enable-oslogin=TRUE
```

SSH into the VM:

```bash
gcloud compute ssh jira-logs-dataset-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a
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

Verify tools:

```bash
docker version
kubectl version --client
kind version
helm version
pwsh -NoProfile -Command '$PSVersionTable.PSVersion'
```

(The Google Cloud CLI is not needed inside the VM for this workflow because we
do not back up to GCS. Downloads happen from your laptop via
`gcloud compute scp` after collection.)

## VM: Clone The Project

Clone this repository.

Important: push the current branch from your laptop before cloning, because
the v4 triage scripts, scenario YAML triage blocks, and the v4 large corpus
manifest must be present on the VM.

```bash
mkdir -p ~/workplace
cd ~/workplace
git clone https://github.com/17YuvrajSehgal/JiraAndLogs.git JiraAndLogs
cd JiraAndLogs
```

Clone Online Boutique into the expected folder:

```bash
git clone https://github.com/GoogleCloudPlatform/microservices-demo.git microservices-demo-google
```

Create the Python environment and install the one required package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r scripts/research-lab/requirements.txt
```

The only required Python package is **PyYAML**, used by the triage builder
to read the per-window triage blocks from scenario YAML files. Without
PyYAML the builder silently falls back to deterministic derived labels,
which is permitted by the contract but loses the `scenario_authored`
label-source guarantee. Confirm the install worked:

```bash
python -c "import yaml; print('PyYAML', yaml.__version__)"
```

Set run variables inside the VM. These name the collection; they're filled in
so you can copy-paste without edits.

```bash
export RUN_PREFIX="2026-05-22-dataset-v4-large"
export GLOBAL_DATASET_ID="2026-05-22-dataset-v4-large-global"
export BENCHMARK_ID="triage-baseline-v1"
```

Check prerequisites:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/check-prereqs.ps1
```

(The legacy `test-cloud-dataset-preflight.ps1` requires a GCS bucket and is
intentionally skipped in this no-bucket workflow. The mandatory smoke test
below covers the same end-to-end validation.)

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

Confirm cluster, observability, and Online Boutique are healthy:

```bash
kubectl get pods -n observability --no-headers | grep -v Running && echo "observability has non-Running pods" || echo "observability OK"
kubectl get pods -n online-boutique-research --no-headers | grep -v Running && echo "online-boutique has non-Running pods" || echo "online-boutique OK"
df -h ~ | awk 'NR==2 {print "free disk:", $4}'
```

Free disk should be at least 300 GB at this point. Do not start the multi-day
run if either namespace has non-Running pods or disk free is low.

## VM: Smoke Test The Pipeline (Mandatory Before The Long Run)

Before launching the 24-30 hour collection, run one short scenario end-to-end
and confirm the triage builders and validation gate work. This catches
environment issues before you commit a day of compute.

```bash
export SMOKE_RUN_ID="smoke-$(date -u +%Y%m%dT%H%M%SZ)"

# 1. Scaffold a single run.
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/start-dataset-run.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" \
  -Force

# 2. Run one Jira-worthy fault scenario.
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/run-scenario.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" \
  -ScenarioFile deploy/research-lab/scenarios/faults/paymentservice-unavailable-critical.yaml \
  -DurationSeconds 60 \
  -PostWindowSeconds 60

# 3. Build the triage example and validate.
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/build-triage-dataset.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" -Force

pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/validate-run-feature-distribution.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID"
```

The last command should print `PASS smoke-... fails=0`. Inspect the report:

```bash
cat "data/runs/${SMOKE_RUN_ID}/summaries/data-quality-report.md"
```

If status is **PASS**, the pipeline is healthy; proceed. If **FAIL**, fix the
underlying issue (the report names the failing check) before launching the
multi-day collection.

## VM: Preview The Corpus

Preview the 40 planned runs:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/collect-dataset-corpus.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-v4-large.json" \
  -DatasetRunPrefix "2026-05-22-dataset-v4-large" \
  -PlanOnly
```

You should see:

```text
Dataset corpus plan:
  corpus_id: dataset-v4-large
  planned_runs: 40
  selected_runs: 40
  [1]  2026-05-22-dataset-v4-large-control-r01    -> deploy/research-lab/run-plans/control-baseline-only.json
  [2]  2026-05-22-dataset-v4-large-control-r02    -> ...
  ...
  [9]  2026-05-22-dataset-v4-large-compact-a-r01  -> ...
  [25] 2026-05-22-dataset-v4-large-compact-b-r01  -> ...
```

Control runs come first as the false-positive anchor.

## VM: Launch The Collection

Start a persistent terminal session (so SSH disconnects do not kill the run):

```bash
tmux new -s dataset
cd ~/workplace/JiraAndLogs
source .venv/bin/activate
set -euo pipefail
mkdir -p logs
```

Then launch the full corpus in a single command. The `-BuildTriage` flag
makes the runner produce per-run triage_examples.jsonl immediately after
each scenario plan finishes and call `validate-run-feature-distribution.ps1`.
With `-HaltOnValidationFail` the corpus stops the moment any run produces
zero-signal ticket-worthy windows or all-zero features. This is the safety
net for unattended multi-day collection.

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/collect-dataset-corpus.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-v4-large.json" \
  -DatasetRunPrefix "2026-05-22-dataset-v4-large" \
  -GlobalDatasetId "2026-05-22-dataset-v4-large-global" \
  -Quick \
  -BuildTriage \
  -HaltOnValidationFail \
  -SkipDerivedBuild \
  -SkipAggregateBuild \
  2>&1 | tee logs/2026-05-22-dataset-v4-large-corpus.log
```

What the flags do:

- `-Quick`: 75-second scenario durations (the validated pilot setting).
- `-BuildTriage`: after every run, build triage examples + memory matchings,
  and after all runs build the global triage dataset + Jira memory corpus.
- `-HaltOnValidationFail`: stop the corpus if any per-run validation fails.
- `-SkipDerivedBuild` + `-SkipAggregateBuild`: skip the legacy ranking
  pipeline; we're collecting v4 triage data, not retrospective ranking.

If SSH disconnects, reattach with:

```bash
tmux attach -t dataset
```

## VM: Monitor Progress

While the collection runs (1-2 days), check status from another SSH session:

```bash
# Where are we?
cat data/derived/corpora/2026-05-22-dataset-v4-large/corpus-run-manifest.json \
  | jq '.completed_run_count, .selected_run_count, .status'

# Latest data quality reports (sorted newest first)
ls -lt data/runs/2026-05-22-dataset-v4-large-*/summaries/data-quality-report.md 2>/dev/null | head -5

# Disk free
df -h ~

# Live tail of the corpus log
tail -f logs/2026-05-22-dataset-v4-large-corpus.log
```

Inspect any single run that just completed (change the run name to whichever
run you want to look at, e.g. `-control-r03`, `-compact-a-r05`, `-compact-b-r12`):

```bash
cat data/runs/2026-05-22-dataset-v4-large-compact-a-r01/summaries/data-quality-report.md
cat data/runs/2026-05-22-dataset-v4-large-compact-a-r01/summaries/feature-distribution.md
```

Each completed run also writes a `manifest.json` with the git SHA, builder
SHA256 hashes, and tool versions used. Inspect for provenance:

```bash
cat data/runs/2026-05-22-dataset-v4-large-compact-a-r01/manifest.json \
  | jq '.git, .builder_hashes, .tool_versions'
```

## VM: Resume After Interruption

If the corpus stops (either because a validation failed or the VM rebooted),
fix the underlying issue, then resume from the next un-collected run. The
corpus runner detects completed runs by the presence of their `manifest.json`
and a validation report, so you can re-launch the same command without
re-running completed work:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/collect-dataset-corpus.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-v4-large.json" \
  -DatasetRunPrefix "2026-05-22-dataset-v4-large" \
  -GlobalDatasetId "2026-05-22-dataset-v4-large-global" \
  -Quick \
  -BuildTriage \
  -HaltOnValidationFail \
  -SkipDerivedBuild \
  -SkipAggregateBuild \
  2>&1 | tee -a logs/2026-05-22-dataset-v4-large-corpus.log
```

Do NOT add `-ForceNewRun` unless you intentionally want to discard completed
runs. If a single run completed but its triage build failed, fix the issue
then re-run the triage build directly on that run (change the run id to the
failing one):

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/build-triage-dataset.ps1 \
  -DatasetRunId "2026-05-22-dataset-v4-large-control-r03" -Force
```

## VM: Run The Triage Benchmark

After all 40 corpus runs finish and the global triage dataset is built
(automatic with `-BuildTriage`), run the first triage benchmark:

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/run-triage-benchmark.ps1 \
  -GlobalDatasetId "2026-05-22-dataset-v4-large-global" \
  -BenchmarkId "triage-baseline-v1" \
  -Force
```

This trains two baselines (rule + logistic) on the family-level split and
reports:

- Headline PR-AUC / ROC-AUC / ECE on the held-out test families
- Precision@FPR=1% and 5% operating points (threshold tuned on validation)
- Strict and inclusive borderline handling
- **Leave-one-family-out** macro PR-AUC / ROC-AUC across all 13 families
- Per-family and per-`is_hard_case` stratified metrics
- 15-feature logistic weights so you can inspect what the model learned

## Local Machine: Download The Data

Run these commands from your laptop (not from the VM). They use
`gcloud compute scp` over SSH to copy the collected data down to your machine.
Plan for ~90-130 GB of raw telemetry plus a few GB of derived files.

Make a local destination directory:

```bash
mkdir -p ~/jira-logs-dataset-v4-large
cd ~/jira-logs-dataset-v4-large
```

Download the derived files first (small, but the most important — these are
the ML-ready outputs):

```bash
gcloud compute scp --recurse \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  jira-logs-dataset-vm:~/workplace/JiraAndLogs/data/derived \
  ./
```

Download the collection log:

```bash
gcloud compute scp \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  jira-logs-dataset-vm:~/workplace/JiraAndLogs/logs/2026-05-22-dataset-v4-large-corpus.log \
  ./
```

Optionally, download the raw runs (this is the big ~100 GB chunk — only do
this if you need the raw telemetry; the derived files alone are enough for
ML training and benchmarking):

```bash
gcloud compute scp --recurse \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  jira-logs-dataset-vm:~/workplace/JiraAndLogs/data/runs \
  ./
```

Alternative for the large raw runs: compress on the VM first to save transfer
time. From an SSH session on the VM:

```bash
cd ~/workplace/JiraAndLogs
tar -czf ~/data-runs.tar.gz data/runs
ls -lh ~/data-runs.tar.gz
```

Then from your laptop:

```bash
gcloud compute scp \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  jira-logs-dataset-vm:~/data-runs.tar.gz \
  ./
tar -xzf data-runs.tar.gz
```

The `data/runs/*/summaries/data-quality-report.md` files are part of the
raw-run tree, so they come down with `data/runs`. Provenance metadata
(git SHA, builder hashes, tool versions) is in each run's `manifest.json`.

## VM: What To Check After The Run

Confirm corpus completeness:

```bash
cat data/derived/corpora/2026-05-22-dataset-v4-large/corpus-run-manifest.json \
  | jq '{completed: .completed_run_count, selected: .selected_run_count, status: .status}'
```

Inspect global triage dataset:

```bash
ls data/derived/global/2026-05-22-dataset-v4-large-global/
wc -l data/derived/global/2026-05-22-dataset-v4-large-global/global-triage-examples.jsonl
cat data/derived/global/2026-05-22-dataset-v4-large-global/triage-split-manifest.json \
  | jq '.family_assignment, .label_counts_by_split'
```

Inspect Jira memory corpus:

```bash
wc -l data/derived/global/2026-05-22-dataset-v4-large-global/jira-memory-corpus.jsonl
head -1 data/derived/global/2026-05-22-dataset-v4-large-global/jira-memory-corpus.jsonl | jq .
```

Read the benchmark headline:

```bash
cat data/derived/global/2026-05-22-dataset-v4-large-global/benchmarks/triage-baseline-v1/benchmark-report.md
```

Check for any failed runs:

```bash
grep -l '"passed": false' data/runs/2026-05-22-dataset-v4-large-*/summaries/data-quality-report.json || echo "no failed runs"
```

The fully complete v4 large collection should have:
- 40 entries in the corpus manifest with `status: completed`
- ~3700 rows in `global-triage-examples.jsonl`
- ~260 entries in `jira-memory-corpus.jsonl`
- 13 scenario families in the split manifest
- Zero `"passed": false` data-quality reports

## Local Machine: Stop Or Delete The VM

**Confirm you have downloaded the data first.** Verify on your laptop:

```bash
ls -1 ~/jira-logs-dataset-v4-large/derived/global/2026-05-22-dataset-v4-large-global/
# should list global-triage-examples.jsonl, jira-memory-corpus.jsonl,
# triage-split-manifest.json, etc.
```

Stop the VM if you may come back soon (compute stops, disk continues to bill):

```bash
gcloud compute instances stop jira-logs-dataset-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a
```

Delete the VM when you no longer need it. This stops all billing for compute
and (because auto-delete is on by default for the boot disk we created)
deletes the 500 GB disk too:

```bash
gcloud compute instances delete jira-logs-dataset-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a
```

Confirm there are no leftover disks (the next command should output nothing):

```bash
gcloud compute disks list \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --filter="name~jira-logs-dataset-vm"
```

If a disk is listed, delete it explicitly (only after re-confirming the
local copy of the data):

```bash
gcloud compute disks delete DISK_NAME_FROM_LIST_ABOVE \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a
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
