I would not deploy the stock `release/kubernetes-manifests.yaml` directly for this research. It will run Online Boutique, but it will not give us the unified, Jira-ready telemetry dataset we need.

**What I Found**
- The cloned repo is at [microservices-demo-google](/C:/workplace/JiraAndLogs/microservices-demo-google).
- Online Boutique already has partial OpenTelemetry hooks in several services.
- The included OpenTelemetry collector is configured for Google Cloud export, not our local/research stack.
- Some services have weaker tracing support, so for production-grade research data we should rely on both app instrumentation and Kubernetes/service-level metadata.
- This machine does not currently have `kubectl`, `helm`, `docker`, `kind`, or `minikube` on PATH, so I cannot deploy from here yet.

**Recommended Architecture**
Use two namespaces:

- `online-boutique-research`: Online Boutique app, load generator, scenario labels.
- `observability`: Prometheus, Alertmanager, Loki, Tempo, Grafana, OpenTelemetry Collector, Grafana Alloy.

Use:
- **OpenTelemetry Collector** for traces and resource enrichment.
- **Prometheus + Alertmanager** for metrics and alert events.
- **Loki + Grafana Alloy** for Kubernetes/application logs. I recommend Alloy, not Promtail, because Grafana’s docs say Promtail is deprecated and has reached EOL in 2026.
- **Tempo** for traces.
- **Grafana** for unified exploration: logs, metrics, traces, and incident timelines.

**Important Metadata To Store From Day One**
We should add a research metadata contract before generating data:

- `dataset_run_id`
- `scenario_id`
- `experiment_id`
- `fault_id`
- `traffic_profile_id`
- `service_name`
- `service_version`
- `deployment_version`
- `git_sha`
- `image_digest`
- `k8s_namespace`
- `k8s_pod`
- `k8s_node`
- `trace_id`
- `span_id`
- `request_id`
- `session_id`
- `alert_fingerprint`
- `incident_episode_id`
- `jira_shadow_issue_id`
- `jira_issue_key`, nullable until real Jira integration exists
- `expected_severity`
- `affected_service`
- `fault_start_time`
- `fault_end_time`
- `jira_candidate`, true/false

High-cardinality fields like `request_id`, `session_id`, `trace_id`, and `fault_id` should not become Prometheus labels. They belong in logs, traces, and dataset tables. Metrics should keep low-cardinality labels only.

**Jira Recommendation**
We should create **shadow Jira issue records** now, even before connecting Jira Cloud. For every incident episode, store a JSON payload shaped like a future Jira issue:

- summary
- description
- component/service
- severity
- priority
- labels
- root-cause category
- linked alert ids
- linked trace ids
- linked telemetry window ids
- expected remediation notes

Later, we can replay these records into Jira Cloud and preserve stable links. This avoids wasting early telemetry runs that cannot be linked to Jira-like ground truth.

**Realism Requirements**
The dataset should include more than clean chaos failures:

- normal traffic windows
- noisy but non-incident anomalies
- near-misses that should not become Jira issues
- pod restarts
- CPU and memory pressure
- dependency latency
- Redis/cart degradation
- network latency/loss
- bad deployment/config scenarios
- cascading failures
- traffic spikes
- low-traffic quiet periods
- repeated incidents across different days
- mixed-severity incidents

That is what will make the ranking model credible for a real company, not just a lab demo.

**What I Suggest Implementing Next**
After your approval, I would add a research deployment scaffold without modifying the upstream Google repo directly:

- `deploy/research-lab/`
- `deploy/research-lab/online-boutique/`
- `deploy/research-lab/observability/`
- `deploy/research-lab/scenarios/`
- `schemas/incident_episode.schema.json`
- `schemas/alert_event.schema.json`
- `schemas/telemetry_window.schema.json`
- `schemas/jira_shadow_issue.schema.json`
- `docs/research-lab-deployment.md`

Approval items:
1. Use `online-boutique-research` and `observability` namespaces.
2. Use Grafana Alloy for log collection instead of Promtail.
3. Add shadow Jira issue records from the first dataset run.
4. Keep MVP v1 ranking-only, but make telemetry/Jira metadata rich enough for Phase 2.
5. Build the scaffold outside `microservices-demo-google` so the upstream clone stays clean.