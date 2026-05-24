# GCP VM Runbook For Train-Ticket Dataset Collection

This runbook explains how to create a cost-controlled Google Cloud VM, install
the full research lab, deploy FudanSELab's train-ticket (47 microservices, 4
languages, 2 databases), collect the **train-ticket pilot** triage corpus,
back up the outputs, and shut everything down.

Pair this with `docs/gcp-production-dataset-vm-runbook.md` (the Online Boutique
equivalent) and `trainticket-todo.md` (the planning doc that frames the
cross-app generalization story).

## Recommended VM Shape

Use a single Compute Engine VM running Ubuntu, Docker, kind, and the project
scripts.

| Setting | Value |
| --- | --- |
| VM type | `e2-standard-16` |
| vCPU / RAM | 16 vCPU, 64 GB RAM |
| OS | Ubuntu 24.04 LTS x86_64 |
| Boot disk | 1 TB `pd-balanced` |
| Provisioning | Standard VM (not Spot) |
| Region | `us-central1-a` unless you have a reason to use another |
| Kubernetes | kind cluster with 1 control-plane and 2 workers |

Why bigger than the boutique VM:

- 47 services * 300Mi MySQL + Nacos + RabbitMQ + observability ≈ 19 GB memory
  requests at scheduler floor; with limits and headroom you want ~40 GB
  available to the kind cluster.
- Java services (Spring Boot) have 60-120s cold starts. With 32 GB RAM, half
  the services OOM during startup. 64 GB is the realistic floor.
- 1 TB disk holds ~130 GB raw telemetry + the codewisdom/ts-* image cache
  (~25 GB) + retries + buffer.

If you must use 32 GB (e2-standard-8), use `--independent-db=false` (the
default) and accept that the cluster will be borderline during full traffic.

## What dataset to run on the VM

Use the pilot corpus first:

```text
deploy/research-lab/corpora/dataset-trainticket-pilot.json
```

It creates 6 dataset runs:

| Plan alias | Repeats | Per-run scenarios | Purpose |
| --- | ---: | ---: | --- |
| `control` (baseline-only) | 2 | 4 | False-positive anchor, no faults |
| `compact-a` | 2 | 7 | Booking, search, payment outages + restart |
| `compact-b` | 2 | 5 | Station, payment-restart, UI-restart |

Expected scale:

| Item | Value |
| --- | ---: |
| Dataset runs | 6 |
| Total episodes | ~38 |
| Total telemetry windows | ~270 |
| Scenario families | 8 |
| Shadow Jira memory corpus | ~15-20 entries |
| Raw data size | ~12-15 GB |
| Collection wall time (Quick mode) | ~6-8 hours |

This pilot is sized to validate the entire pipeline end-to-end before you
commit to a larger T8-style multi-day collection. If the pilot's headline
metrics look healthy, scale up by adding more run plans.

## Local Machine: Create The VM

```bash
gcloud auth login
gcloud config set project project-dfc1abf4-e3f9-44ce-8a3
gcloud services enable compute.googleapis.com

gcloud compute instances create jira-logs-trainticket-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  --machine-type=e2-standard-16 \
  --provisioning-model=STANDARD \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=1000GB \
  --boot-disk-type=pd-balanced \
  --scopes=https://www.googleapis.com/auth/cloud-platform \
  --labels=project=jiraandlogs,purpose=dataset,env=research,app=trainticket \
  --metadata=enable-oslogin=TRUE

gcloud compute ssh jira-logs-trainticket-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a
```

Cost estimate at us-central1 list prices: `e2-standard-16` is ~$0.54/hour ;
1 TB pd-balanced is ~$0.10/GB-month. For a 12-hour pilot collection that's
roughly $6.50 compute + $1.40 disk. A 5-day full collection is roughly $65
compute + $14 disk = ~$80 total before egress.

## VM: Install Base Packages

```bash
set -euo pipefail
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \
  ca-certificates curl gnupg git jq unzip zip tar tmux htop rsync \
  python3 python3-venv python3-pip apt-transport-https software-properties-common
```

## VM: Install Docker, kubectl, kind, Helm, PowerShell

These steps are identical to `docs/gcp-production-dataset-vm-runbook.md` -
follow that section verbatim. The Docker daemon.json log-rotation step is
particularly important for a 5-day collection.

## VM: Clone The Repositories

```bash
mkdir -p ~/workplace
cd ~/workplace
git clone https://github.com/17YuvrajSehgal/JiraAndLogs.git JiraAndLogs
cd JiraAndLogs

# Online Boutique (for cross-app comparisons; even if you only run train-ticket
# the boutique observability values are referenced).
git clone https://github.com/GoogleCloudPlatform/microservices-demo.git microservices-demo-google

# Train-ticket (FudanSELab) - the workload for this run.
git clone --depth=1 https://github.com/FudanSELab/train-ticket.git train-ticket

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r scripts/research-lab/requirements.txt
python -c "import yaml; print('PyYAML', yaml.__version__)"

export RUN_PREFIX="trainticket-pilot"
export GLOBAL_DATASET_ID="trainticket-pilot-global"
```

## VM: kind Cluster

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/create-kind-cluster.ps1
kubectl config use-context kind-jira-telemetry-lab
kubectl cluster-info
kubectl get nodes -o wide
```

## VM: Observability Overlay

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/install-observability.ps1
kubectl wait --for=condition=Ready pods --all -n observability --timeout=900s
kubectl get pods -n observability -o wide
```

The observability overlay is the same one used for Online Boutique. The
alloy-values.yaml already includes `trainticket` in its namespace allowlist
regex so logs from train-ticket pods will be scraped automatically.

## VM: Deploy Train-Ticket

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/apply-trainticket.ps1 \
  -Namespace trainticket \
  -WaitReady \
  -ReadyTimeoutSeconds 1800
```

Expect ~5-10 minutes for the helm charts (mysql / nacos / rabbitmq / ts-mysql)
to come up, then 10-15 minutes for the 45 train-ticket service pods to all
reach Ready (Java Spring Boot cold starts dominate the wall time).

Sanity:

```bash
kubectl get pods -n trainticket
kubectl get pods -n trainticket --no-headers | grep -v Running | grep -v Completed && echo "non-Running pods exist" || echo "trainticket OK"

# Verify alloy is scraping logs from the trainticket namespace.
kubectl exec -n observability deploy/alloy -- wget -qO- http://localhost:12345/api/v1/web/agent/components 2>/dev/null | head -100 || true

# Tail one service to confirm logs are flowing.
kubectl logs -n trainticket -l app=ts-auth-service --tail=20
```

Free disk should still be at least 850 GB.

## VM: Smoke Test The Pipeline

Before committing to the multi-hour pilot, run one short scenario end-to-end:

```bash
export SMOKE_RUN_ID="trainticket-smoke-$(date -u +%Y%m%dT%H%M%SZ)"

pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/start-dataset-run.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" \
  -DatasetName "train-ticket-jira-telemetry" \
  -ScenarioId "tt-smoke" \
  -TrafficProfileId "trainticket-booking-mix" \
  -WorkloadNamespace "trainticket" \
  -Force

pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/run-scenario.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" \
  -ScenarioFile deploy/research-lab/scenarios/trainticket/faults/ts-auth-service-unavailable-critical.yaml \
  -Namespace trainticket \
  -DurationSeconds 60 \
  -PostWindowSeconds 60

pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/build-triage-dataset.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID" -Force

pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/validate-run-feature-distribution.ps1 \
  -DatasetRunId "$SMOKE_RUN_ID"
```

The last command should print `PASS ... fails=0`. Inspect:

```bash
cat "data/runs/${SMOKE_RUN_ID}/summaries/data-quality-report.md"
```

If PASS, proceed. If FAIL, fix the underlying issue before committing to the
pilot.

## VM: Launch The Pilot Collection

```bash
tmux new -s dataset
cd ~/workplace/JiraAndLogs
source .venv/bin/activate
mkdir -p logs

pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/research-lab/collect-dataset-corpus.ps1 \
  -CorpusFile "deploy/research-lab/corpora/dataset-trainticket-pilot.json" \
  -DatasetRunPrefix "trainticket-pilot" \
  -GlobalDatasetId "trainticket-pilot-global" \
  -Quick \
  -BuildTriage \
  -HaltOnValidationFail \
  -SkipDerivedBuild \
  -SkipAggregateBuild \
  2>&1 | tee logs/trainticket-pilot-corpus.log
```

If SSH disconnects, reattach with `tmux attach -t dataset`.

## VM: Monitor Progress

```bash
cat data/derived/corpora/trainticket-pilot/corpus-run-manifest.json | jq '.completed_run_count, .selected_run_count, .status'
ls -lt data/runs/trainticket-pilot-*/summaries/data-quality-report.md 2>/dev/null | head -5
df -h ~
tail -f logs/trainticket-pilot-corpus.log
```

## VM: Resume After Interruption

If the corpus stops, re-run the same command. The corpus runner detects
completed runs by `manifest.json` + validation report.

## VM: Download Data, Shut Down

```bash
tar -czf trainticket-pilot.tar.gz data/runs/trainticket-pilot-* data/derived/corpora/trainticket-pilot
```

From your laptop:

```bash
gcloud compute scp \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  jira-logs-trainticket-vm:~/workplace/JiraAndLogs/trainticket-pilot.tar.gz \
  ./trainticket-pilot.tar.gz

gcloud compute instances delete jira-logs-trainticket-vm \
  --project=project-dfc1abf4-e3f9-44ce-8a3 \
  --zone=us-central1-a \
  --quiet
```

## Known Pitfalls

- **Codewisdom image tags drift.** A few `codewisdom/ts-*` images on Docker Hub
  are tagged `1.0.0` and a few are `1.0.1`. The bundled `deploy.yaml.sample`
  pins explicit tags so it just works; if you see ImagePullBackOff for one
  image, check the tag in `deploy.yaml.sample`.
- **Java cold start.** Don't start the pilot before every Spring Boot pod is
  Ready. The pre-fault baseline window will record JVM warmup noise otherwise.
- **Nacos cache.** After a `pod-restart` scenario, Nacos can take 30-60s to
  expire the dead endpoint. The recovery window's residual errors are expected
  and the scenario YAML's recovery-window triage label reflects this.
- **The shipped SkyWalking is not used.** The observability overlay uses
  Loki + Tempo + Prometheus + Alloy via OpenTelemetry. SkyWalking remains in
  `deployment/kubernetes-manifests/skywalking/` but is intentionally not
  deployed; the existing builders consume OTel/Tempo only.

## What this runbook does NOT cover

- Building train-ticket images from source. Pre-built images on Docker Hub
  are used. If those go away, run `make package && make build-image` inside
  the train-ticket repo on the VM (~30-90 min cold build for all 47 services).
- OTel auto-instrumentation of the Java/Node/Python services (Phase T1 in
  `trainticket-todo.md`). This pilot relies on the upstream services' raw
  logback / pino / python-logging output, which Alloy will ship to Loki. The
  Tempo trace surface is sparser than Online Boutique's; this is expected for
  the pilot and is the gap T1 closes.
- Chaos-mesh / network / disk / time faults (Phase D11 in `dataset-todo.md`
  and Phase T4.4 in `trainticket-todo.md`). The pilot uses only app-level
  scale/restart faults.
