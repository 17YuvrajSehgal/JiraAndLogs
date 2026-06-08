# `scripts/research-lab/otel-demo/` — OTel Demo-specific harness helpers

Forked scripts and helpers for cross-app collection on the OpenTelemetry Demo (Astronomy Shop). Per docs5/01 Rule R2, OTel Demo-specific behavior lives here, never inside the OB-shared scripts under `scripts/research-lab/`. The OB pipeline is unaffected by anything in this directory.

## Files

| File | Purpose |
|---|---|
| `Invoke-FlagdFlip.ps1` | Flip a flagd feature flag's `defaultVariant` for a duration, then restore. Used by the `Flagd` scenario primitive. |
| `Invoke-MultiFaultOrchestration.ps1` | Orchestrate concurrent / cascade / compound multi-fault scenarios. Used when scenario YAML carries `composition_type`. (Phase 1c) |
| `Export-PropagationEvidence.ps1` | Compute the `propagation_evidence` block per window from Tempo trace data. (Phase 1c+) |
| `validate_otel_demo_telemetry.py` | OTel Demo-specific smoke validator (mirrors `validate_l1_l2_telemetry.py`). (Phase 2 prep) |

## How these compose with the existing harness

`scripts/research-lab/run-scenario.ps1` dispatches scenario actions by string match on `execution.action`. The OB primitives (`RecordOnly`, `SetEnv`, `RestartPods`, `ScaleDeployment`, `ChaosMeshChaos`) remain unchanged. The Phase 1b additions introduce one new primitive:

- **`Flagd`** — flip an OTel Demo flagd flag via ConfigMap patch.

When a scenario YAML sets `execution.action: Flagd`, `run-scenario.ps1` invokes `Invoke-FlagdFlip.ps1` for both the fault inject and the restore.

The existing primitives are also reusable on OTel Demo. For example, `cart-redis-degradation-critical` on OTel Demo uses `ScaleDeployment` against `valkey-cart` (the demo's Redis-compatible cache); no new harness work needed.

## Network families

The 4 network-fault families (`network-latency`, `network-packet-loss`, `network-partition`, `dns-outage`) require chaos-mesh. Per docs5/01 §10.3 resolution, chaos-mesh is **not assumed installed** in v1 of the OTel Demo collection. The 4 network scenarios are deferred; if chaos-mesh is installed on the GCP VM, they will be enabled in Phase 2 pilot and re-included in the corpus manifest.

## PausePod primitive — DROPPED

Per docs5/01 §10.4 resolution, the originally-planned `PausePod` (SIGSTOP / SIGCONT) primitive has been dropped in favor of `ScaleDeployment` to zero. This:

- Matches OB's existing consumer-down pattern exactly.
- Avoids SIGSTOP/SIGCONT realism concerns (pod stays "Running" but unresponsive vs cleanly absent).
- Keeps the cascade-aware retrieval task semantically identical between OB and OTel Demo.

The `kafka-consumer-crash` scenario uses `ScaleDeployment` to zero replicas on `fraud-detection` (or `accounting`) and restores to 1 after the active-fault window.
