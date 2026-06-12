# From Telemetry to Jira and Back

Using Jira issue history as supervision to improve log-based detection, alerting, and triage.

---

## Overview

Modern distributed systems generate massive volumes of telemetry data in the form of logs, metrics, and traces.
This telemetry feeds detection and alerting pipelines, where rules and anomaly detectors try to identify suspicious behavior and raise alerts to on-call engineers.

However, only a small fraction of telemetry ultimately leads to actionable engineering work items such as bugs, incident reports, or reliability tasks captured in Jira.
Our core idea is to treat **historical Jira issues as operational ground truth** and use them to train models that make log analysis and alerting more focused, less noisy, and more aligned with what engineers actually care about.

Because existing public datasets rarely contain both detailed telemetry and linked Jira issues, a key part of this project is to **construct our own paired telemetry-Jira dataset** using an open-source microservices application, a modern observability stack, and chaos engineering.

This repository explores that idea and provides code, dataset generation pipelines, and experiments around **learning from Jira history to de-noise log analysis**.

---

## Problem Statement

Observed in many real systems:

- Telemetry (logs/metrics/traces) is **high-volume and noisy**. Many anomalies or rule matches do not correspond to real incidents.
- Detection and alerting systems often rely on **hand-tuned thresholds and static rules**, leading to either alert fatigue (too many alerts) or missed incidents (too few alerts).
- **Jira issue trackers** accumulate rich, long-term knowledge about what actually mattered: incidents, bugs, mitigation steps, components involved, and impact levels.

Today, the data flow is mostly one-way:

> Telemetry -> Detection / Alerting -> Human Triage -> Jira Issue

The feedback from Jira back into the detection pipeline is usually manual (e.g., engineers tweak rules after incidents).
There is **no systematic way** to learn from the Jira corpus and update how telemetry is interpreted.

**Research question:**
Can we use historical Jira issues as supervision to learn which telemetry patterns correspond to real, important incidents, and then use that knowledge to improve future detection, alerting, and triage?

---

## High-Level Idea

We propose a **closed feedback loop** between telemetry and Jira:

1. **Telemetry generation**
   Systems emit logs, metrics, and traces as usual.

2. **Detection and alerting**
   Existing rules/anomaly detectors identify suspicious patterns and raise alerts.

3. **Triage and investigation**
   Engineers investigate alerts, examine telemetry, and decide whether there is a real issue.

4. **Jira issues as ground truth**
   Confirmed incidents, bugs, and reliability tasks are recorded as Jira issues with text, metadata, and links.

5. **Feedback: learning from Jira history**
   We mine historical Jira issues (and their associated telemetry) to learn:
   - Which telemetry patterns consistently led to real Jira issues.
   - Which components/services and error patterns were involved.
   - What severities and impacts were observed.
   - Which remediation steps were effective.

6. **Jira-informed detection/triage**
   The learned models are injected back into the detection pipeline to:
   - Score or re-rank log-based alerts by **likelihood of becoming a Jira issue**.
   - Enrich alerts with **predicted Jira fields** (service, severity, incident type).
   - Retrieve **similar past Jira issues** to speed triage and suggest likely fixes.

In short:

> **Telemetry leads to issues, issues accumulate knowledge in Jira, and Jira-derived knowledge improves how we analyze telemetry next time.**

---

## Research Objectives

This project aims to:

1. **Model Jira issues as operational knowledge**
   - Learn representations of issues that capture incident types, impacted components, severities, and remediation patterns using large Jira datasets (e.g., Public Jira datasets and locally collected Jira projects).

2. **Construct a realistic paired telemetry-Jira dataset**
   - Deploy an open-source microservices application (e.g., Google's Online Boutique / microservices-demo) on Kubernetes as a realistic target system.
   - Instrument it with a modern observability stack (Prometheus for metrics, centralized logging, distributed tracing, and Grafana for visualization) so that logs, metrics, and traces are captured in a unified way.
   - Integrate a Jira Service Management instance via APIs so that alerts and incidents are reflected as structured Jira issues.
   - Use chaos engineering tools (e.g., Chaos Mesh / Gremlin) to inject controlled failures and generate labeled incident episodes under realistic load.

3. **Link telemetry patterns to Jira issues**
   - Build a schema that associates log sequences and telemetry windows with specific Jira issues, incident episodes, and injected fault types.
   - Learn models that estimate the **probability that a telemetry pattern will lead to a Jira issue** and predict issue metadata (service, severity, incident type, fault category).

4. **Improve detection and triage**
   - Use Jira-informed models to:
     - Reduce alert noise at fixed recall (fewer spurious alerts).
     - Provide better context (likely component, similar historical incidents, potential fixes).
     - Evaluate impact on triage performance using offline metrics and, where possible, user-study style evaluations.

5. **Produce reusable artifacts**
   - Code and pipelines for **Jira-aware log and telemetry analysis**.
   - Dataset generation tooling for replaying the full experimental setup (Kubernetes app, chaos scenarios, observability, Jira integration).
   - Experimental benchmarks against standard log anomaly detection baselines.

---

## Custom Dataset and Experimental Setup

To support ML/AI development, we will create a **fully controlled, reproducible environment** that continuously generates paired telemetry and Jira data.

### Application and observability

- Deploy the Google microservices-demo application (Online Boutique) as the main workload, providing multiple services, request paths, and cross-service dependencies.
- Use:
  - Prometheus to scrape and store metrics for each service (latencies, error rates, resource usage).
  - A log aggregation stack (e.g., Loki / OpenSearch) to centralize structured logs.
  - An OpenTelemetry-based tracing pipeline with Jaeger or Tempo as the backend, with trace IDs propagated into logs and metrics for correlation.

### Incident generation and labeling

- Configure alerting rules (SLO-style) on key golden signals (latency, error rate, saturation) per service.
- Integrate Alertmanager (or equivalent) with a small gateway service that:
  - Receives alerts, aggregates them into incidents.
  - Automatically creates or updates Jira issues via the Jira REST API, attaching alert metadata and links to logs/metrics/traces.
- Use Chaos Mesh / Gremlin to inject controlled failures (pod kills, network latency, resource pressure, etc.) against specific services while synthetic traffic is generated.
- For each chaos experiment, record:
  - Experiment type and parameters.
  - Incident time windows and affected services.
  - Corresponding alerts and Jira issues.

### ML-ready views

From this environment, we will derive ML-ready datasets, including:

- Time-windowed telemetry samples labeled with incident presence, impacted services, and severity.
- Log and trace sequences leading up to incidents vs normal periods.
- Paired examples of `(telemetry window <-> Jira issue)` for supervised prediction and retrieval tasks.

This setup makes the resulting dataset highly suitable for **supervised learning, contrastive representation learning, and retrieval-augmented detection**.

---

## Expected Contributions

This project aims to contribute:

1. **Conceptual framework**
   A clear formulation of Jira issues as supervision signals for log analysis and detection, forming a closed feedback loop between telemetry and issue tracking.

2. **Models and algorithms**
   Jira-aware log and telemetry analysis methods that:
   - Learn from historical issues.
   - Improve alert ranking and triage support.
   - Integrate with existing anomaly detection and observability systems.

3. **Datasets and tooling**
   - A reproducible Kubernetes-based experimental setup combining:
     - An open-source microservices application.
     - An observability stack (Prometheus, logging, tracing, Grafana).
     - Chaos engineering infrastructure.
     - Jira integration for incident tracking.
   - Scripts and pipelines to generate ML-ready paired telemetry-Jira datasets from this environment.
   - Where licensing permits, curated datasets of linked Jira issues and logs for reproducible research.

4. **Empirical evaluation**
   - Comprehensive experiments on datasets generated from the controlled environment, as well as synthetic variants, demonstrating the benefits and limitations of Jira-informed detection and triage.
   - Comparisons to standard log anomaly detection baselines and ablation studies showing the impact of Jira-derived supervision.

---

## Research and Productization Plan

### Working thesis

Historical Jira issues can be treated as weak but valuable operational labels for telemetry. If we can reliably link incidents, alerts, logs, metrics, traces, and Jira issue metadata, we can build models that reduce alert noise, rank incidents by operational importance, and give engineers useful context from similar past issues.

The research goal is not just to prove a model works on logs. The larger goal is to build an industry-usable system that fits into existing SRE workflows, works with common observability tools, and earns trust by showing evidence, uncertainty, and clear links back to source telemetry and Jira history.

The confirmed product direction is **commercial/internal application first, research paper second**. The research work is still essential, but its role is to prove that the application is correct, measurable, and better than credible baselines. The paper should be treated as a validation artifact built from the same datasets, experiments, and evaluation harness used by the product.

### Target industry application

The product should become a **Jira-aware observability intelligence layer** that sits between telemetry systems, alerting systems, and Jira.

Primary users:

- On-call engineers who need faster triage and less noisy alert queues.
- SRE/platform teams who maintain alerting rules and incident workflows.
- Engineering managers who need incident trends, recurring failure patterns, and reliability backlog quality.
- Incident commanders who need historical context during active incidents.

Core product capabilities:

- Score incoming alerts by likelihood of becoming a real Jira incident, bug, or reliability task.
- Group related alerts into incident episodes and attach supporting evidence.
- Predict likely affected service, severity, incident type, and failure category.
- Retrieve similar historical Jira issues and show what fixed them.
- Suggest Jira issue fields and draft structured incident summaries.
- Provide feedback controls so engineers can mark model suggestions as useful, wrong, duplicate, or noisy.
- Export auditable datasets for offline model evaluation and governance.

MVP v1 boundary:

- Rank alerts and telemetry windows by likelihood of becoming a meaningful Jira issue.
- Show the evidence behind the ranking.
- Compare the ranking model against baseline alert rules and telemetry-only models.
- Export product and research metrics from the same evaluation pipeline.
- Do not create, modify, or approve Jira issues in the first MVP.

Phase 2 product expansion:

- Human-approved Jira issue creation.
- Jira field suggestions.
- Feedback buttons for accepted/rejected recommendations.
- Similar-incident retrieval inside the active triage workflow.

Non-goals for the first version:

- Replacing existing alerting systems.
- Automatically resolving incidents.
- Fully autonomous Jira creation without human review.
- Depending on one proprietary observability vendor.
- Depending on private enterprise Jira data for the first proof.

### Confirmed setup decisions

- **Primary goal:** commercial/internal application with research-grade proof.
- **Research paper:** secondary deliverable, based on the product's reproducible experiments and evaluation harness.
- **Dataset source:** generated lab data first. Public Jira datasets lack linked telemetry, and public log datasets generally lack linked Jira issues, so the project will simulate both sides in one controlled environment.
- **Jira target:** start with Jira Cloud / Jira Service Management Free because it is the easiest low-cost path for API integration and lab issue creation. Atlassian's current Cloud plan documentation describes a Free plan for small teams, and Jira Service Management Free supports up to 3 agents with 2 GB storage. Data Center should be deferred until an enterprise pilot explicitly requires self-managed compatibility.
- **Observability target:** use a complete open stack with metrics, logs, traces, dashboards, and alerts. The recommended default is OpenTelemetry + Prometheus + Loki + Tempo + Grafana + Alertmanager. OpenSearch and Jaeger can be supported later as connector variants.
- **MVP v1 behavior:** ranking only. The application should rank alerts/windows and explain the ranking; human approval and Jira-writing workflows are Phase 2.

---

## Phase 0: Problem Validation and Scope Control

**Goal:** Confirm the precise problem, target users, and operational success criteria before building infrastructure.

Key activities:

1. Interview 5-10 SREs, platform engineers, or on-call engineers.
2. Map the real workflow from alert trigger to Jira issue creation to incident closure.
3. Identify where Jira currently contains useful signal and where it is incomplete or noisy.
4. Define what "better alerting" means for this project:
   - fewer false positives,
   - faster triage,
   - better incident routing,
   - better Jira issue quality,
   - better historical retrieval.
5. Lock the first product workflow around alert/window ranking, with Jira creation and human approval explicitly deferred to Phase 2.
6. Define the research proof needed for product credibility:
   - ranking performance against baselines,
   - false-positive reduction at fixed recall,
   - calibration quality,
   - generalization to unseen services and fault types,
   - reproducibility of the generated dataset.

Deliverables:

- User workflow map.
- Product requirements document.
- Research hypotheses.
- Initial risk register.
- Evaluation metric definitions.
- MVP v1 scope statement.

Go/no-go criteria:

- At least one high-value workflow has a measurable operational outcome.
- Users agree that Jira history contains enough signal to be useful.
- The first MVP can be tested as a ranking layer without taking control of production alerting or Jira writes.

---

## Phase 1: Reproducible Dataset Lab

**Goal:** Build a controlled environment that generates paired telemetry, alert, trace, and Jira data.

System components:

- Kubernetes cluster.
- Online Boutique / microservices-demo workload.
- Synthetic traffic generator.
- OpenTelemetry Collector for telemetry collection and correlation.
- Prometheus for metrics.
- Loki for logs.
- Tempo for traces.
- Grafana dashboards.
- Alertmanager as the alert router.
- Jira Cloud / Jira Service Management Free for lab issue creation through the Jira REST API.
- Chaos Mesh or equivalent chaos injection framework.
- Dataset export service.

Dataset entities:

- `incident_episode`
  - episode id,
  - start/end time,
  - fault type,
  - affected service,
  - severity,
  - injected or organic label,
  - related Jira issue id.

- `telemetry_window`
  - window id,
  - time range,
  - service,
  - log snippets,
  - metric features,
  - trace summaries,
  - alert state,
  - label fields.

- `jira_issue`
  - issue key,
  - title,
  - description,
  - components,
  - labels,
  - severity,
  - priority,
  - status transitions,
  - comments,
  - resolution text,
  - linked incident episode ids.

- `alert_event`
  - alert id,
  - rule name,
  - labels,
  - annotations,
  - firing/resolved timestamps,
  - linked telemetry windows,
  - linked Jira issue.

- `service_topology`
  - service name,
  - dependencies,
  - deployment version,
  - ownership metadata.

Data generation plan:

1. Run normal traffic with no injected failures.
2. Inject single-service failures:
   - pod kill,
   - CPU pressure,
   - memory pressure,
   - network latency,
   - packet loss,
   - HTTP error injection,
   - database or cache dependency degradation.
3. Inject multi-service and cascading failures.
4. Vary load levels, failure duration, and affected service.
5. Generate lab Jira issues through an alert gateway, then enrich them with known ground-truth fault metadata.
6. Preserve negative examples where telemetry produced alerts but no Jira-worthy incident label.
7. Export repeatable train/validation/test splits by time, service, and fault type.

Deliverables:

- Working lab deployment.
- Dataset schema.
- Data export format.
- First dataset release.
- Reproducibility guide.
- Jira Cloud setup notes and API credential handling guide.

Go/no-go criteria:

- Each chaos experiment produces correlated logs, metrics, traces, alerts, and Jira records.
- Dataset can be regenerated from scripts.
- Labels are explicit enough for supervised learning and retrieval evaluation.
- The same exported dataset can support both product ranking evaluation and research-paper experiments.

---

## Phase 2: Baselines and Measurement

**Goal:** Establish honest baselines before adding advanced models.

Baseline families:

- Alert-rule baseline:
  - current alert rules only,
  - severity from static thresholds,
  - no Jira history.

- Log anomaly baseline:
  - log parsing,
  - template frequency features,
  - classical anomaly detection.

- Metric anomaly baseline:
  - golden-signal thresholds,
  - rolling z-score,
  - seasonal or robust statistical models.

- Retrieval baseline:
  - keyword search over historical Jira issues,
  - service/component matching,
  - simple embedding search.

- Supervised baseline:
  - gradient boosted trees or logistic regression over telemetry features,
  - text classifier over logs and alert annotations.

Primary ML tasks:

1. **Alert-to-Jira prediction**
   - Binary classification: will this alert/window become a Jira issue?

2. **Incident severity prediction**
   - Multi-class prediction: severity/priority/category.

3. **Affected service prediction**
   - Multi-label classification over services/components.

4. **Similar incident retrieval**
   - Rank historical Jira issues relevant to the current telemetry window.

5. **Jira field suggestion**
   - Suggest title, component, severity, labels, and summary draft.

Evaluation metrics:

- AUROC and AUPRC for classification.
- Precision at K for alert ranking.
- Recall at fixed alert budget.
- False-positive reduction at fixed recall.
- NDCG, MRR, and recall at K for retrieval.
- Exact/partial match for Jira field prediction.
- Calibration error for risk scores.
- Time-to-triage reduction in controlled user studies.
- Engineer acceptance rate for suggestions.

Deliverables:

- Baseline results report.
- Reusable evaluation harness.
- Failure analysis on false positives, false negatives, and poor retrieval cases.

Go/no-go criteria:

- Baseline metrics are reproducible.
- Dataset has enough positive and negative examples to support meaningful evaluation.
- Research team can identify where Jira-derived supervision should plausibly improve results.

---

## Phase 3: Jira-Aware Models

**Goal:** Build models that use Jira history as supervision and context, not just as a storage target.

Model tracks:

### Track A: Alert ranking model

Purpose:

- Re-rank incoming alerts by probability of operational importance.

Inputs:

- Alert labels and annotations.
- Recent log templates.
- Metric-window features.
- Trace summary features.
- Service topology features.
- Historical Jira similarity features.

Outputs:

- Jira-likelihood score.
- Confidence interval or calibrated probability.
- Top contributing evidence.

### Track B: Incident metadata model

Purpose:

- Predict structured Jira fields and routing metadata.

Outputs:

- affected service,
- owner/team,
- severity,
- incident type,
- likely fault category,
- duplicate or related Jira issues.

### Track C: Retrieval-augmented triage model

Purpose:

- Retrieve similar Jira issues and present evidence-backed triage context.

Outputs:

- similar incidents,
- matching telemetry patterns,
- historical remediation notes,
- recurring services or dependencies,
- caveats when evidence is weak.

### Track D: Feedback learning loop

Purpose:

- Learn from engineer corrections and Jira issue outcomes after deployment.

Signals:

- accepted/rejected suggestion,
- changed severity,
- duplicate marking,
- issue status transitions,
- linked pull requests or deployment changes,
- postmortem tags.

Research experiments:

- Does Jira supervision improve alert ranking beyond telemetry-only baselines?
- Does retrieval over Jira issues reduce triage time?
- Does the model generalize to unseen services and unseen fault types?
- How much labeled Jira history is needed before performance becomes useful?
- Does synthetic chaos-generated data transfer to real operational Jira data?
- Which source adds the most value: logs, metrics, traces, topology, or Jira text?

Deliverables:

- Model training pipeline.
- Model registry entries.
- Evaluation notebooks/reports.
- Explainability and evidence format.
- Ablation study report.

Go/no-go criteria:

- Jira-aware model beats telemetry-only baselines on at least one primary metric.
- Model explanations are understandable to engineers.
- Calibration is good enough to support ranking decisions.

---

## Phase 4: Industry MVP Application

**Goal:** Convert research outputs into a usable ranking product that can run safely beside existing tools.

MVP operating mode:

- Read from observability systems.
- Read lab Jira issues and labels for training/evaluation.
- Score and rank alerts or telemetry windows.
- Show ranking evidence in a dashboard.
- Export evaluation results for research and product review.
- Do not create or modify Jira issues in MVP v1.

Application modules:

1. **Connectors**
   - Jira connector for reading lab issue metadata and labels.
   - Prometheus connector.
   - Loki connector.
   - Tempo connector.
   - Alertmanager webhook receiver.

2. **Incident linker**
   - Links alerts, telemetry windows, traces, and Jira issues.
   - Maintains episode timelines.

3. **Feature pipeline**
   - Extracts log templates, metric features, trace summaries, and text embeddings.
   - Stores versioned features.

4. **Model service**
   - Scores alert importance.
   - Returns confidence, uncertainty, and evidence.
   - Exposes model version and feature version for reproducibility.

5. **Evaluation service**
   - Compares the ranking model against alert-rule and telemetry-only baselines.
   - Computes precision at K, recall at fixed alert budget, AUPRC, calibration, and false-positive reduction.
   - Exports paper-ready tables and product dashboards from the same run.

6. **Dashboard**
   - Ranked alerts.
   - Alert/window detail page.
   - Evidence timeline.
   - Baseline comparison.
   - Model confidence and calibration.
   - Dataset/run selector.
   - Research metrics view.

7. **Phase 2 services**
   - Similar incident retrieval.
   - Suggested Jira fields.
   - Human approval workflow.
   - Jira issue creation or update.
   - Engineer feedback controls.

8. **Governance layer**
   - Audit log.
   - Role-based access.
   - PII/secrets redaction.
   - Data retention controls.
   - Explicit Jira write-disable guard for MVP v1.

Suggested technical shape:

- Backend API: Python FastAPI or similar.
- Data processing: batch jobs plus streaming ingestion.
- Storage: PostgreSQL for metadata, object storage for raw exports, vector index for retrieval.
- Model serving: lightweight HTTP service with versioned models.
- UI: web dashboard oriented around on-call workflow.
- Deployment: Docker Compose for local demo, Helm charts for Kubernetes.

MVP screens:

- Alert queue ranked by Jira-likelihood.
- Incident detail page with evidence timeline.
- Ranking explanation page.
- Baseline comparison page.
- Dataset/evaluation page for researchers.
- System health and connector status page.

Deliverables:

- Running local demo.
- Demo dataset.
- API documentation.
- Admin setup guide.
- Ranking workflow guide.
- Research evaluation report.
- Security and privacy checklist.

Go/no-go criteria:

- An engineer can inspect an alert/window, see why it was ranked highly, and compare the model's ranking to baseline alert ordering.
- The system does not require replacing existing alerting tools.
- Every model output is traceable to source evidence.
- MVP v1 produces enough evaluation evidence to support a research-paper result section.

---

## Phase 5: Pilot and Enterprise Hardening

**Goal:** Validate usefulness in a realistic team environment and prepare the product for industry adoption.

Pilot setup:

- Start in read-only mode against historical production data if available.
- Replay past incidents and compare model recommendations to actual Jira outcomes.
- Move to shadow mode for live alerts.
- Only after validation, allow controlled Jira enrichment with human approval.

Enterprise requirements:

- Jira Cloud first, with a later Jira Data Center compatibility decision only if a pilot requires it.
- Observability vendor compatibility matrix.
- Secrets management.
- PII and credential redaction.
- Tenant isolation if used by multiple teams.
- Auditability of all model outputs.
- Model rollback.
- Versioned datasets and training runs.
- Configurable retention policy.
- Clear failure modes when connectors are unavailable.

Operational success metrics:

- Alert noise reduction.
- Mean time to acknowledge.
- Mean time to triage.
- Mean time to route to owner.
- Ranking usefulness rating.
- False-positive reduction at fixed recall.
- Recall at fixed alert-review budget.
- Phase 2 only: percentage of Jira drafts accepted.
- Phase 2 only: percentage of suggested fields retained.
- Phase 2 only: retrieval usefulness rating.
- Duplicate incident reduction.
- On-call satisfaction survey.

Deliverables:

- Pilot report.
- Production readiness review.
- Security review.
- Runbook.
- SLOs for the application itself.
- Roadmap for general availability.

Go/no-go criteria:

- Pilot users would keep using the system after the study.
- The system improves at least one operational metric without increasing incident risk.
- Security and governance requirements are clear enough for a real deployment conversation.

---

## Research Risks and Mitigations

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Jira is incomplete ground truth | Not every real incident becomes a clean Jira issue. | Treat Jira as weak supervision; include alert outcomes, incident labels, and human feedback. |
| Label leakage | Models may learn synthetic labels or Jira automation artifacts instead of telemetry patterns. | Strict time splits, remove generated fields from model inputs, test on unseen fault types. |
| Synthetic data may not transfer | Chaos experiments are cleaner than real failures. | Include noisy scenarios, mixed failures, real historical data when possible, and transfer evaluation. |
| Alert ranking can hide critical incidents | Bad ranking may reduce visibility. | Use shadow mode first; never suppress alerts in MVP; expose uncertainty. |
| LLM outputs may hallucinate fixes | Unsafe suggestions can mislead engineers. | Retrieval-first design, citations to evidence, human approval, no autonomous remediation. |
| Privacy and secrets in logs | Logs and Jira comments may contain sensitive data. | Redaction, access control, retention policy, audit logs. |
| Integration complexity | Enterprises use different observability stacks. | Connector abstraction and start with a narrow compatibility matrix. |
| Model drift | Services, alerts, and Jira practices change over time. | Continuous monitoring, retraining schedule, drift reports, feedback loop. |

---

## First 30 Days

Week 1:

- Finalize research hypotheses and ranking-only product scope.
- Define the first user workflow around alert/window ranking.
- Set up Jira Cloud / Jira Service Management Free.
- Confirm the OpenTelemetry, Prometheus, Loki, Tempo, Grafana, and Alertmanager stack.
- Write the dataset schema draft.

Week 2:

- Stand up the microservices demo locally or in a small Kubernetes environment.
- Add metrics, logs, traces, and basic dashboards.
- Define initial alert rules and incident episode format.
- Implement the first alert-to-Jira lab issue flow.

Week 3:

- Add chaos scenarios and synthetic traffic.
- Build the alert-to-Jira gateway prototype.
- Generate the first 20-50 labeled incident episodes.
- Preserve normal and noisy non-incident windows as negative examples.

Week 4:

- Export the first ML-ready dataset.
- Train simple baselines.
- Create the first evaluation report.
- Create the first ranking dashboard view.
- Decide whether the next month should prioritize dataset scale, model quality, or MVP dashboard polish.

Expected end-of-month artifact:

- A reproducible demo showing: injected failure -> telemetry -> alert -> Jira issue -> dataset export -> baseline model result.

---

## Resolved Decisions and Remaining Questions

Resolved decisions:

1. The main goal is a commercial/internal application.
2. A research paper is required, but it is not the main product goal.
3. The research proof must show that the ranking application works and is correct against credible baselines.
4. The first dataset will be generated in a controlled lab because public Jira datasets and public log datasets do not provide the required linked supervision.
5. The target workload is Google's Online Boutique / microservices-demo.
6. The initial Jira target should be Jira Cloud / Jira Service Management Free.
7. The observability stack must include metrics, logs, traces, dashboards, and alert routing.
8. MVP v1 is ranking-only. Jira write workflows and human approval are Phase 2.

Remaining questions:

1. Should the application be positioned as an internal enterprise tool first, or as a commercial SaaS-style product from the start?
2. Should the first demo run on local Kubernetes, kind/minikube, or a low-cost cloud Kubernetes cluster?
3. Should the model stack prioritize classical ML first, deep sequence models first, or a hybrid with retrieval/LLM features after the baseline?
4. What is the expected first-demo timeline: 4 weeks, 8 weeks, or 12+ weeks?
5. Who is the first reviewer of the finished MVP: SRE engineers, engineering leadership, potential customers, or academic reviewers?

---

## Current External Setup Notes

- Atlassian's current Jira Cloud plan documentation describes the Free plan as intended for small teams and lists up to 10 users, or 3 agents for Jira Service Management, with 2 GB storage and Community support.
- Jira Cloud Free has limitations around permissions, audit logs, email limits, and app compatibility, but these are acceptable for a controlled lab and early MVP.
- Jira Data Center should not be the initial path because it adds setup and licensing complexity without improving the first ranking proof.

References:

- Jira Cloud plan comparison: https://support.atlassian.com/jira-cloud-administration/docs/explore-jira-cloud-plans/
- Jira Cloud Free limitations: https://support.atlassian.com/jira-cloud-administration/docs/what-is-the-free-jira-cloud-plan/
- Jira Service Management pricing/features: https://www.atlassian.com/collections/service/pricing
