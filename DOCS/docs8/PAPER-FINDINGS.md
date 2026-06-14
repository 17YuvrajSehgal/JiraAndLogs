# Paper-section findings — consolidated from Phase 2 + Phase 3

**Status:** 2026-06-14. The numerical evidence and prose hooks for
every paper section. **No new measurements live here** — every
claim is sourced from a SUMMARY.md in `results/{ob,otel-demo,wol}/`
or a JSON in the same directories. The paper draft pulls from this
file; this file pulls from the source of truth (`RQ-CLOSURE-TABLE.md`).

When the paper text needs a number, it should:
1. Find the claim here
2. Follow the citation link to the SUMMARY.md
3. Confirm the number is the same in both files (no drift)

---

## Section: Abstract / Introduction headline numbers

The agent runs on 3 datasets (Online Boutique synthetic, OTel Demo,
World of Logs real Apache Jira). One-paragraph numerical
fingerprint:

> "On Online Boutique (1008-window test, 331 evaluable for retrieval),
> the capability-adaptive agent achieves Hit@5 = 0.7583, Hit@1 =
> 0.6888, and triage accuracy = 0.8343 while reducing wall time
> by 68.1%, LLM tokens by 64.1%, and dollar-equivalent cost by
> 64.1% relative to an always-on cascade baseline. Generalisation
> holds: on OTel Demo the same agent achieves Hit@5 = 0.7563
> (65% cost saved). On real Apache Jira (World of Logs, 55
> evaluable), it achieves Hit@5 = 0.8364, Hit@1 = 0.7818, and
> triage accuracy = 0.9342 — its strongest dataset. Page
> suppression converges to exactly 1.000 pages per incident on
> all three datasets. The agent's behaviour is fully replayable
> from per-window Traces; the Phase 2 ReAct loop's contribution
> is statistically insignificant on Hit@1 (p=0.262) but the
> `request_extended_trace_window` tool is significantly harmful
> on OB (Δ=−0.018, p=0.002) — an honest negative finding that
> motivates per-family tool selection."

---

## Section: Headline tables (one per dataset)

### Online Boutique (OB) — synthetic microservices telemetry

n = 1008 windows test, 331 evaluable for retrieval.

| Metric | Point | 95% CI | Source |
|---|---|---|---|
| Hit@1 | **0.6888** | [0.6385, 0.7405] | results/ob/4.3-bootstrap-cis/SUMMARY.md |
| Hit@5 | **0.7583** | [0.7085, 0.8029] | same |
| Hit@10 | 0.7583 | [0.7085, 0.8029] | same |
| MRR | 0.7138 | [0.6637, 0.7604] | same |
| Triage accuracy | 0.8343 | [0.8095, 0.8591] | same |
| Novel recall / precision | 0.5361 / 0.1128 | — | results/ob/3.5-agent-smoke-v5-react-4tools/SUMMARY.md |
| Pages per incident | **1.000** | — | same |
| Suppressions fired | 20 | — | same |
| Distinct plan IDs | 4 (of 6 branches) | — | same |
| Cost savings vs cascade | **64.1%** USD (verifier-ON) | — | results/ob/4.10-verifier-on-cost/SUMMARY.md |
| Cost savings vs cascade | 41.0% USD (verifier-OFF) | — | results/ob/4.5-cost-vs-cascade/SUMMARY.md |

### OTel Demo

n = 247 windows test, 119 evaluable for retrieval.

| Metric | Point | 95% CI | Source |
|---|---|---|---|
| Hit@1 | 0.6471 | [0.5641, 0.7411] | results/otel-demo/4.3-bootstrap-cis/otel-smoke-bootstrap.json |
| Hit@5 | 0.7563 | [0.6726, 0.8333] | same |
| MRR | 0.6880 | [0.6132, 0.7715] | same |
| Triage accuracy | 0.8421 | [0.7976, 0.8866] | same |
| Pages per incident | **1.000** | — | results/otel-demo/PHASE3-OTEL-SUMMARY.md |
| Distinct plan IDs | 4 | — | same |
| Cost savings vs cascade | **65.3%** USD | — | results/otel-demo/4.5-cost-vs-cascade/SUMMARY.md |

### World of Logs (WoL) — real Apache Jira

n = 304 windows test, 55 evaluable for retrieval. Two test
projects (Kafka, MariaDB).

| Metric | Point | Source |
|---|---|---|
| **Hit@1** | **0.7818** (highest of 3 datasets) | results/wol/PHASE3-WOL-SUMMARY.md |
| **Hit@5** | **0.8364** | same |
| MRR | 0.8045 | same |
| **Triage accuracy** | **0.9342** | same |
| Pages per incident | **1.000** | same |
| Suppressions fired | 18 | same |
| Distinct plan IDs | 1 (text-only — no fault-window taxonomy) | same |
| Cascade Mode 3 Hit@5 (BiEncoder coarse) | 0.7553 (test); 0.8503 (Kafka); 0.7692 (MariaDB) | data/derived/global/2026-06-11-wol-real-global/tch-lite-refit/biencoder-mode3-results.json |

---

## Section: RQ-by-RQ claims with statistical support

### RQ-A1 (plan diversity) — dataset-dependent

- OB: 4 distinct plan IDs across 1008 windows
- OTel: 4 distinct plan IDs across 247 windows
- WoL: 1 distinct plan ID across 304 windows

**Honest framing:** the 6-branch `CapabilityAwareRuleController`
emits diverse plans on telemetry datasets where `window_type`
varies (active_fault / pre_fault_baseline / recovery_window /
observation_window). On text-only Apache Jira data (WoL), there
is no fault-window taxonomy, so the controller collapses to one
plan — the branching mechanism is operational but not exercised.

→ Cite: `results/ob/3.5-*/SUMMARY.md`, per-dataset SUMMARYs.

### RQ-A2 (cost savings vs cascade) — STRONGEST quantitative claim

| Config | OB | OTel | WoL |
|---|---|---|---|
| Wall savings | **68.1%** (verifier-ON) | 63.3% | TBD |
| Token savings | **64.1%** | 65.3% | TBD |
| USD savings | **64.1%** (= 0.1170 saved per 1008 windows) | 65.3% | TBD |

Mechanism: capability-drop (e.g., `retrieve_log_sequence` never
enters Plan because ORDERED_LOGS absent on WoL) + gate-skip (the
cheap-first / escalation gate drops 68.8% of verifier invocations
when cheap path is confident). Both mechanisms preserve Hit@K
(§4.1 finding: every cascade-skill ablation has Δ Hit@K = 0).

→ Cite: `results/ob/4.5-cost-vs-cascade/SUMMARY.md` + `4.10-verifier-on-cost`.

### RQ-A4 (page suppression) — UNIVERSAL across 3 datasets

| Dataset | Pages/incident | Suppressions fired |
|---|---|---|
| OB | **1.000** | 20 |
| OTel | **1.000** | 1 |
| WoL | **1.000** | 18 |

The conservative suppression rule (same `top1_match` in last 3
windows + same `scenario_family` + no recovery_window
intervened) hits target ≤ 1.5 on all 3 datasets.

→ Cite: per-dataset `PHASE3-{OB,OTEL,WOL}-SUMMARY.md`.

### RQ-A5 (skill ablation, paired-delta) — STATISTICAL

| Ablation | OB Δ | p | OTel Δ | p |
|---|---|---|---|---|
| `no_react` | −0.0121 Hit@1 | 0.262 (NS) | 0 (flat) | 1.0 |
| `no_triage_numeric` | **−0.117 triage** | **<0.0001** | **−0.158 triage** | **<0.0001** |
| All other cascade-skill ablations | exactly 0 | — | exactly 0 | — |

**Paper claim:** "On OB and OTel, `triage_numeric` (HGB on 94
numeric features) is statistically essential for triage accuracy
(p<0.0001 both datasets). Every other cascade-skill ablation
produces exactly zero per-window deltas — confirming
`BiEncoder + triage_numeric` is the load-bearing skill pair."

→ Cite: `results/ob/4.12-paired-delta-cis/SUMMARY.md`, `results/otel-demo/4.12-paired-delta-cis/`.

### RQ-A6 (ReAct lift) — POINT estimate suggestive; ONE significant negative

- **OB point estimate**: peers-only gives +0.0151 Hit@1 (vs no-ReAct).
  But paired CI is [−0.006, +0.036], p=0.180 — NOT significant.
- **OB significant negative**: `request_extended_trace_window`
  alone vs no-tools: Δ = −0.018 Hit@1, paired CI [−0.033, −0.006],
  **p = 0.002**.
- **OTel**: every tool subset (16 cells) produces exactly 0 Hit@1
  delta. ReAct loop is functionally inert on OTel due to gate
  firing only on 25 of 247 windows and 88% empty rate on
  `request_pod_events`.
- **WoL**: same — every tool subset produces exactly 0 delta on
  the 55 evaluable cases.

**Paper framing:** "Phase 2 ReAct's positive Hit@1 contribution
is not statistically significant on any of 3 datasets. The single
significant finding is the `request_extended_trace_window` tool's
**net-harmful effect** on OB (p=0.002), motivating per-family
tool selection — disable the trace tool by default; enable it
only on families where its service-graph context outweighs the
cross-family token noise."

→ Cite: `results/ob/4.13-tool-paired-deltas/SUMMARY.md`.

### RQ-A7 (budget curve) — non-monotone OB, flat OTel/WoL

| N (max_tool_calls) | OB Hit@1 | OTel | WoL |
|---|---|---|---|
| 0 | 0.6767 | 0.6471 | 0.7818 |
| 1 | 0.6798 (+0.003) | 0.6471 | 0.7818 |
| 2 | **0.6647 (−0.012)** | 0.6471 | 0.7818 |
| 3 | **0.6647 (−0.012)** | 0.6471 | 0.7818 |
| 4 | 0.6888 (+0.012) | 0.6471 | 0.7818 |

**Paper claim:** "RQ-A7's plan-spec hypothesis (monotone Hit@K
with budget) is rejected on OB — the curve is non-monotone with
a regression at N=2 and N=3 (the trace + metrics tools fire
without peers to anchor against). OTel and WoL produce flat
curves (gate rarely fires; only peers tool would apply on WoL)."

→ Cite: `results/ob/3.7-budget-curve/SUMMARY.md`.

### RQ-B2 (Pareto curve) — flat Hit@K, variable cost

OB 6-cell sweep over `cheap_path_threshold ∈ {0.50..0.95}` with
verifier-ON. **All cells produce identical Hit@K** (0.6888 /
0.7583 / 0.7138 / 0.8413). Cost varies $0.0589 (72.3% saved at
threshold=0.50) to $0.0679 (66.5% at 0.95).

**Production recommendation:** drop OB `cheap_path_threshold`
from 0.90 (default) → 0.50 for an extra 4pp of cost savings at
zero Hit@K cost.

→ Cite: `results/ob/4.11-pareto-sweep/SUMMARY.md`.

### RQ-B3 (bootstrap CIs) — 6 statistically-significant findings

Across 3 datasets, 1000-resample paired bootstrap (seed=42, 95%):

| Finding | Dataset | Effect | p |
|---|---|---|---|
| `request_extended_trace_window` harms Hit@1 | OB §4.13 | −0.018 | 0.002 |
| `triage_numeric` carries triage_accuracy | OB §4.12 | −0.117 | <0.0001 |
| `triage_numeric` carries triage_accuracy | OTel §4.12 | −0.158 | <0.0001 |
| `NUMERIC_FEATURES` carries triage_accuracy | OB §4.14 | −0.117 | <0.0001 |
| `MEMORY_TEXT` carries Hit@1 | WoL §4.14 | −0.78 | <0.0001 |
| `TEXT_EVIDENCE` carries Hit@1 | WoL §4.14 | −0.78 | <0.0001 |

All other paired deltas (≈ 80 ablation cells × 3 datasets) are
either exactly 0 or non-significant at α=0.05.

→ Cite: 3 SUMMARY files in `results/{ob,otel-demo,wol}/4.12..4.14`.

### RQ-C1 (synthetic→real generalisation) — STRONGEST external-validity claim

The agent trained on OB synthetic generalises to real Apache
Jira: **WoL Hit@1 = 0.7818, MRR = 0.8045, triage = 0.9342** —
the highest values across the 3 datasets. The single significant
WoL finding (the −0.78 Hit@1 collapse when `MEMORY_TEXT` is
masked) confirms the fail-fast capability gate is working.

The underlying Mode 3 BiEncoder achieves coarse Hit@5 = 0.7553
on the WoL test split (with per-project: Kafka 0.8503, MariaDB
0.7692).

→ Cite: `results/wol/PHASE3-WOL-SUMMARY.md`.

### RQ-C4 (capability-mask robustness) — graceful degradation

- OB: masking any single capability flag produces a stable run
  (no crashes, plan_ids stay at 4). Masking TRACE_SUMMARY
  reproduces the §3.8 peers-only best subset.
- OTel: identical behaviour.
- WoL: the 2 catastrophic masks (`MEMORY_TEXT` and `TEXT_EVIDENCE`)
  cleanly collapse Hit@1 → 0 (fail-fast).

→ Cite: `results/{ob,otel-demo,wol}/4.4-capability-mask/SUMMARY.md`.

### RQ-D3 (verifier OOD failure) — structural skip

WoL has `verifier_policy="harmful"` in `WOL_PROFILE` →
`VERIFIER_KNOWN_HELPFUL` flag never surfaces → `verify_with_llm`
cannot be invoked on WoL (structural, not runtime). The Mode 3
finding (−0.272 Hit@5 if verifier ran on WoL) **cannot occur**.

Confirmed by `smoke_wol.py`'s
`_assert_verifier_structurally_skipped` post-condition.

→ Cite: `scripts/agent/smoke_wol.py`, the assertion + the Mode 3
finding in `docs7/MODE3-TCH-LITE-WoL-RESULTS.md` §3.9.

### RQ-D5 (failure-mode distribution) — LLM-INDUCED finding

| Dataset | false_novel rate |
|---|---|
| OB | 40.6% |
| OTel | 39.7% |
| **WoL** | **0.7%** |

**Mechanism:** WoL has the verifier structurally skipped (RQ-D3).
The L3 novelty disjunction fires only on the free + learned
signals (NOT the LLM verifier's `is_novel` field). Without the
LLM signal, false_novel drops from ~40% → 0.7% — a **60× collapse**.

**Paper claim:** "The agent's biggest blind spot (40% false
novelty calls on OB+OTel) is **caused by the LLM verifier's
over-eager novelty calls**, NOT by the disjunction structure
itself. Removing the LLM signal (as WoL does by construction)
collapses the failure mode by 60×. This is an honest
mechanistic finding that motivates tighter LLM-verifier novelty
calibration as future work."

→ Cite: `results/{ob,otel-demo,wol}/4.8-failure-categories/SUMMARY.md`,
  `results/wol/PHASE3-WOL-SUMMARY.md` §1 finding #2.

### RQ-D6 (tool-use failure modes) — OB v6 catalog

| Failure mode | Count (716 invocations) | % |
|---|---|---|
| success | 670 | 93.6% |
| tool_returned_empty | 46 | 6.4% (all on `request_similar_incident_window` for `loadgenerator-noisy-high-traffic-nearm` family) |
| hallucinated_tool_name | 0 | 0% |
| looping_repeated_call | 0 | 0% |
| budget_exhausted | 0 | 0% |
| tool_threw_or_missing | 0 | 0% |

3 of 5 modes have 0% rate — they're defenses for the v2 LLM-emitted
ReAct loop that v1's deterministic controller doesn't trigger.

→ Cite: `results/ob/3.6-failure-mode-catalog/SUMMARY.md`.

---

## Section: Discussion / Honest framing

### Three claims the paper STRENGTHENS

1. **`triage_numeric` is the load-bearing triage skill.** Three
   independent mechanisms (skill skip, capability mask,
   dense_only reduction) all converge on triage Δ = −0.117 to
   −0.158 with p<0.0001. The most robust finding in Phase 3.

2. **Cost savings 41-72% across configurations.** Verifier-ON
   (production-realistic) configuration delivers 64.1% USD
   savings on OB. The threshold sweep shows we can push to
   72.3% at threshold=0.50 with no Hit@K cost.

3. **Synthetic→real transfer works.** WoL Hit@1 = 0.7818 (the
   strongest of any dataset) without any WoL-specific tuning
   beyond the Mode-3 BiEncoder fine-tune.

### Two claims the paper SOFTENS / reframes honestly

1. **ReAct lift is not statistically significant.** Point
   estimate +0.0151 on OB; paired CI [−0.006, +0.036], p=0.18.
   Reframe as "suggestive, not conclusive" — the framework
   supports active evidence gathering; the value on this data
   is below the noise floor at α=0.05.

2. **The `request_extended_trace_window` tool is harmful.**
   p=0.002 negative effect on OB. The paper should NOT claim
   "4 tools compose multiplicatively" — instead frame as
   per-tool ROI: peers tool dominates the positive signal; trace
   tool dominates the negative.

### Findings that ARE significant negatives (honest negative results)

1. **Budget curve is non-monotone (RQ-A7).** Rejects the original
   "more tools = better" hypothesis. Tools 2-3 (trace + metrics)
   degrade Hit@1 below baseline; only tool 4 (peers) recovers.

2. **The 40% false_novel rate (RQ-D5) is LLM-induced, not
   structural.** Removing the LLM verifier signal collapses
   false_novel by 60× on real Jira data.

3. **OTel ReAct lift is exactly 0.** Smaller corpus (147 vs OB
   347 tickets) + sparser per-family peers → peer-tool tokens
   don't discriminate enough to swap rank-1.

### v1 deferrals (with explicit hooks for v2)

| RQ | v1 status | v2 path |
|---|---|---|
| A3 (reformulation lift) | gate fires 17.8% on OB; Hit@K not measurable | Need live-retrieval mode (predictions-backed retrievers can't re-query) |
| D1 (distractor robustness on agent) | cascade-level only | Live distractor injection + cascade re-train |
| D4 (Phase-2 HP sensitivity) | only cascade HPs swept | Sweep rerank.alpha, peers.top_k, etc. |

---

## Section: Source-of-truth pointer reference

When the paper text needs a number, search this file first. Each
claim above has a direct citation to a SUMMARY.md or a JSON
output. If you change a number here without also changing it in
the source-of-truth file, the next paper-text-vs-data audit will
catch the drift.

| Doc | What it covers |
|---|---|
| `RQ-CLOSURE-TABLE.md` | row-per-RQ master table; 3 columns per dataset |
| `PAPER-FINDINGS.md` (this file) | paper-narrative-ready prose hooks + tables |
| `AGENTIC-SYSTEM-V3.md` | architecture + the post-Phase-2 system spec |
| `IMPLEMENTATION-PLAN.md` | Phase-2 task breakdown (historic) |
| `RESEARCH-QUESTIONS2.md` | RQ definitions + §9 Phase-2 closure addendum |
| `results/ob/3.5..4.14/SUMMARY.md` | OB per-section finding details |
| `results/otel-demo/3.6..4.14/SUMMARY.md` | OTel per-section finding details |
| `results/wol/3.6..4.14/SUMMARY.md` | WoL per-section finding details |
| `results/{ob,otel-demo,wol}/PHASE3-*-SUMMARY.md` | per-dataset consolidated closure |
