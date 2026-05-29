# LLM-Jira-enhancement.md — TIMELINE: a brilliant Jira humanization design

**Captured:** 2026-05-28.
**Status:** Spec for a phased implementation. Phase 1 + Phase 2 are
already in flight (see `src/jira_humanizer/timeline_schema.py`,
`personas.py`, `sanitizer.py`, `symptom_map.py`, `timeline_generator.py`
and `scripts/research-lab/humanize_5_episodes.py`).
**Related:** `ML-NEW-IDEAS.MD` (raw logs as a first-class signal — its
Move A "characteristic log line extractor" is a hard prerequisite for
the evidence quoting in this design).

> This doc captures the design verbatim from the brainstorm so a future
> contributor (or future-me) can pick it up without re-deriving the
> reasoning. Numbers like "10–15% misattribution" are calibrated
> defaults to be tuned once the first ~50 humanized tickets land.

---

## 1. The core insight

A real Jira ticket is **not a document**. It's a **timeline of
contributions by people with different roles, at different times, who
each know different things**. The current shadow tickets are
single-author single-shot snapshots, which is why they look synthetic
— and worse, they leak because they're written from an oracle's
perspective.

Two design moves change everything:

1. **Temporal information asymmetry.** The reporter at `t=0` has ONLY
   seen the first 30 seconds of the fault. The first commenter at
   `t=+10min` has seen the active_fault window. The resolver at
   `t=+45min` has seen recovery too. Each contribution is generated
   from ONLY the telemetry slice visible at that timestamp.
2. **Persona-driven voice.** A senior SRE writes `redis ctimeout on
   cart` in 4 words. A junior writes a paragraph. A customer-support
   forward says `customers can't add to cart`. An eng-manager writes
   `any update on this?`. Vocabulary diversity isn't decoration — it's
   the signal that prevents models from memorizing one synthetic
   writing style.

Together: the ticket is a **synthesized incident timeline** where the
LLM gets a different telemetry slice + different persona at each turn,
and **never sees the ground-truth fault name**.

---

## 2. The TIMELINE framework

**TIMELINE** = Temporally-Informed Multi-persona Ledger of Incident
Notes & Evolution.

Every ticket becomes a `(persona, timestamp, telemetry-slice,
evidence-quote)` sequence. Each entry in the sequence is generated
independently, in order, with strict information rules.

### Schema per ticket

```json
{
  "ticket_id": "...",
  "timeline": [
    {"step": "report",        "persona": "cs-agent",      "t_offset_s": 0,    "context_window_s": 30},
    {"step": "ack",           "persona": "oncall-sre",    "t_offset_s": 180,  "context_window_s": 180},
    {"step": "hypothesis-1",  "persona": "frontend-eng",  "t_offset_s": 420,  "context_window_s": 300},
    {"step": "redirect",      "persona": "senior-sre",    "t_offset_s": 900,  "context_window_s": 900},
    {"step": "resolve",       "persona": "fix-author",    "t_offset_s": 1800, "context_window_s": 1800}
  ],
  "fields": {
    "summary": "...",
    "description": "...",
    "comments": [...],
    "resolution_notes": "...",
    "components": [...],
    "severity": "..."
  }
}
```

Each timeline step = one LLM call with a tight prompt. We're not
asking the LLM to write a ticket — we're asking it to roleplay a
specific person at a specific moment with specific evidence.

### Step → field mapping

| Step | Maps to ticket field |
| --- | --- |
| `report` | `summary` + first part of `description` (the original report) |
| `ack` | First comment (acknowledgement) |
| `hypothesis-N` (1+) | Next comments (investigation) |
| `redirect` (optional) | Comment that reassigns or corrects |
| `resolve` | Last comment + `resolution_notes` |

---

## 3. The 5 leakage-safety rules (non-negotiable)

This is where the design either works or doesn't.

### Rule 1 — Vocabulary firewall at the prompt boundary

The LLM **never sees** any of these:
- `scenario_id`, `scenario_family`, `fault_type`, `incident_type`,
  `root_cause_category`
- `triage_label`, `triage_severity`, `triage_reason_class`
- Anything from `scripts/research-lab/triage_labels.py` taxonomies
- The strings `fault`, `synthetic`, `injected`, `chaos-mesh`, `dataset
  run`, `scenario`, `lab`, `nearmiss`, `borderline`

The prompt only contains: paraphrased symptoms, persona role, time
elapsed, and a sampled-and-redacted evidence slice. `sanitizer.py`
asserts these tokens don't appear in the LLM input; fails loud if
they do.

### Rule 2 — Symptom paraphrase map

Before generation, map technical fault → user-visible symptom
vocabulary:

| Fault (hidden from LLM) | Symptom phrase LLM sees |
| --- | --- |
| `cart-redis-degradation-critical` | "users seeing cart-not-loading after add-to-cart" |
| `paymentservice-unavailable-critical` | "checkout 5xx at payment step" |
| `productcatalog-latency-major` | "category pages above 3s p95" |
| `flapping-pod` | "intermittent failures, can't reproduce reliably" |
| `slow-leak-saturation` | "gradual degradation, error rate climbing over hours" |
| `frontend-restart` | "site briefly down, came back ~30s later" |
| `recovered-in-window` | "errors spiked then settled before we could react" |
| `post-deploy-churn` | "elevated errors right after last release, watching" |

The LLM is told `the symptom is X` and writes a ticket reporting X —
never knowing it's actually Y. This is the leakage firewall.

### Rule 3 — Strategic misattribution (10–15% of tickets)

Real on-call engineers get the initial diagnosis wrong sometimes.
Deliberately set:

- 10–15% of tickets have `triage_components[0]` set to a
  **downstream-symptom service** rather than the root-cause service
  (e.g., `productcatalog-latency` ticket filed under `checkoutservice`
  because that's where the user saw the error)
- The reporter and 1st–2nd commenters frame it as a `checkoutservice`
  problem
- The senior-SRE comment redirects: *"checkoutservice looks healthy
  from our metrics — checking upstream deps"*
- Resolution names the actual fix without naming the lab fault

A model trained on this learns "components field is a hint, not an
oracle". It cannot exploit the perfect alignment that current shadows
have.

### Rule 4 — Quote, don't summarize

The reporter and early commenters MUST quote specific log lines or
metric values they "saw" — from the actual `raw/loki/` content for
that window — instead of summarizing. Constraints:

- Quotes come from the **characteristic-log-line extractor** in
  `ML-NEW-IDEAS.MD` Move A (rare lines vs baseline). **This makes
  Move A a hard prerequisite.**
- Each quote is paraphrased through persona voice: a senior writes
  `redis ctimeout x12 on cart-redis:6379` while a junior writes `I
  see "ConnectTimeoutException" in cartservice logs from around
  14:23, looks like it's failing to reach redis-cart`
- Numbers in quotes (`p95=1832ms`) are rounded to engineer-realistic
  precision (`~1.8s`)
- Stack traces are **never full** — engineers paste only the
  relevant lines

This grounds the ticket in real telemetry without giving the model
an oracle.

### Rule 5 — Self-resolved / cannot-reproduce / not-a-bug closures

For 10–20% of `borderline` and 30–40% of `noise` windows, generate
tickets that close as:

- *"Cannot reproduce, closing — please re-open if it recurs"*
- *"Looks like post-deploy churn, settled on its own, closing"*
- *"By design, customer was using deprecated checkout flow"*
- *"Duplicate of TICKET-1234"* (cross-link to an existing ticket
  from a similar window)

These are **training data the model desperately needs**. Without
them every ticket in the memory corpus is a "real bug", and the
model can't distinguish "this was filed but isn't worth filing
again" from "this is a true positive". With them, the retrieval task
becomes much more honest — a window similar to a `cannot-reproduce`
ticket should NOT trigger triage_worthy.

---

## 4. Persona catalog

Concrete, with rough vocabulary distributions:

| Persona | Role | Tenure | Vocabulary | Length | Typical step |
| --- | --- | ---: | --- | --- | --- |
| `cs-agent` | Customer support forwarder | 1y | Customer-quote-paste style, non-technical | short | report |
| `oncall-sre` | On-call SRE during the page | 4y | Terse, abbreviated, pager-speak | very short | ack |
| `junior-eng` | Recently-hired backend eng | 0.5y | Verbose, asks questions, over-explains | long | hypothesis |
| `frontend-eng` | Owns the user-facing layer | 3y | Biased toward "frontend issue" framing initially | medium | hypothesis (often wrong) |
| `backend-eng` | Owns the service the symptom appears on | 3y | Technical, references PRs and deploys | medium | hypothesis |
| `senior-sre` | The person who actually finds root cause | 8y | Hedged, asks for evidence, redirects | medium | redirect |
| `eng-mgr` | Manager checking in | 6y | Status-asking, no technical content | short | nudge (occasional) |
| `db-team` | Owns Redis/cache layer | 5y | Surfaces only on infra-layer tickets | short | targeted comment |
| `fix-author` | The person who shipped the fix | varies | Resolution-focused, terse close note | short | resolve |

Each persona has 3–5 named avatars (Sarah Chen, Marcus Williams, …)
drawn deterministically from `episode_id` so the same persona appears
consistently across tickets for the same fault — and a new mix appears
across runs. The existing `src/jira_humanizer/rewrite.py` already has
a `_NAMES` pool; **reuse it** so we don't introduce two sources of
truth for avatar names.

---

## 5. Telemetry × Logs × Jira integration

The framework deliberately uses all three streams at the moment of
generation:

| Timeline step | What evidence the LLM sees | Why |
| --- | --- | --- |
| `report` (t=0) | Top-3 characteristic log lines + metric anomaly summary from t..t+30s | Reporter saw a Grafana spike and pasted a tail of logs |
| `ack` (t=+3m) | Active dashboard panels + alert names + the first error spike duration | On-call SRE acknowledged via pager |
| `hypothesis` (t=+7m) | Service-specific log slice + recent deploy events (if any) | Engineer dug into their service's logs |
| `redirect` (t=+15m) | Wider trace span tree showing dependency calls + dep_error logs | Senior looked at the call chain |
| `resolve` (t=+30m) | Full active_fault window + early recovery_window | Fix-author saw the whole picture |

The timeline mirrors the actual triage workflow, so the dataset
captures not just *what the bug was* but *how it was investigated*. A
model trained on these timelines learns the **triage trajectory**,
not just the label.

---

## 6. Behavioral training signal (the big secondary win)

The timeline gives us SEQUENCE supervision, not just point labels.
Targets that become possible:

- **Next-step prediction**: given `(timeline so far + current telemetry
  window)`, what does the next contributor write? Much richer than
  triage classification.
- **Hypothesis-correctness**: hypotheses are explicitly labeled
  `correct` or `wrong-redirected`. Models can learn to flag
  low-confidence hypotheses.
- **Time-to-resolution**: timestamps in the timeline give us a
  regression target — how long did this take? Models can learn
  severity calibration from human resolution-time.
- **Handoff prediction**: when does the ticket get reassigned? Models
  learn cross-team boundary signals.
- **Close-as-noise prediction**: of the tickets opened, which ones
  close without a fix? Hardest variant of triage — and directly the
  product question.

None of these are exposed today because the current shadows have no
temporal structure.

---

## 7. Implementation plan (phased)

### Phase 1 — Schema + persona catalog + sanitizer (no LLM yet)

- `src/jira_humanizer/timeline_schema.py` — dataclasses for the
  timeline structure
- `src/jira_humanizer/personas.py` — persona definitions +
  deterministic avatar assignment
- `src/jira_humanizer/sanitizer.py` — vocabulary firewall: asserts
  lab tokens aren't in the LLM input, fails loud
- `src/jira_humanizer/symptom_map.py` — fault → symptom paraphrase
  table

### Phase 2 — Single-step generation against one ticket

- Pick 5 representative episodes (one per family bucket: cart-redis,
  baseline, productcatalog-latency, payment-outage,
  recovered-in-window)
- Generate just the `report` step end-to-end via Qwen on LM Studio
- Manual eyeball: does it sound human? Does it leak?
- Run the existing leakage canary on the new field — must pass

### Phase 3 — Multi-step timelines + misattribution

- Add `ack`, `hypothesis`, `redirect`, `resolve` steps
- Enable 10–15% misattribution
- Generate full timelines for the 5 test episodes
- Manual review again

### Phase 4 — Wrong-hypothesis injection + close-as-noise

- Add wrong-hypothesis sampling on 15% of tickets
- Add close-as-noise tickets for borderline/noise windows
- Sanity-check the negative-training-data subset is internally
  coherent

### Phase 5 — Bulk regeneration on v5-large + validation

- Re-generate all 347 tickets through the timeline pipeline
- Validate via:
  - leakage canary on text fields (per `ML-NEW-IDEAS.MD` §2 Move C
    — required prereq)
  - cross-validate: train a model on humanized v5-large, hold out
    one family, check that scores don't suddenly jump (would
    indicate leak)
  - manual review of a stratified sample of 50 tickets (10 per
    fault family)

### Cost estimate at v5-large scale

347 tickets × ~5 timeline steps × 1 Qwen call each ≈ 1,700 LM Studio
calls. At ~3s each that's ~85 minutes unattended on the local
RTX 5060 + LM Studio. Or Claude Haiku at ~$0.0005/call ≈ $1 total.

---

## 8. Risks / what could go wrong

1. **The LLM still leaks via its training data.** LLMs know Online
   Boutique is a Google demo. If the prompt mentions `paymentservice`
   they may infer the architecture. **Mitigation:** paraphrase service
   names too — use `payment-service` / `payment-svc` / `payments`
   interchangeably; sometimes `payment processor` in non-technical
   comments.
2. **Persona consistency across the corpus.** If `senior-sre Sarah
   Chen` writes hostile responses on ticket A and helpful ones on
   ticket B, retrieval gets confused. **Mitigation:** cache the
   persona-specific style guide deterministically from `episode_id`
   so the same persona has the same voice everywhere.
3. **Wrong-hypothesis comments may correlate with fault type.** If
   the LLM always blames `frontend` when the real fault is
   `productcatalog-latency`, the model can learn the inverse.
   **Mitigation:** sample wrong-hypothesis target service uniformly
   from the architecture, not biased toward
   downstream-of-the-fault.
4. **Resolution notes might still be too verbose.** LLMs tend to
   over-explain. **Mitigation:** hard-cap resolution to 1–2
   sentences; randomly sample "self-resolved, monitoring" without a
   clear cause for 20% of tickets.
5. **The misattribution rate (15%) is a guess.** Industry surveys
   suggest ~20–30% of incidents get initially misattributed. Tune
   once we have a baseline.

---

## 9. Atomic first PR (what to ship before scaling)

**Phase 1 + Phase 2 on 5 test episodes.** That's a 1-day spike —
enough to confirm:
- the framework works
- the leakage canary catches what we expect
- the personas read as different humans
- the symptom paraphrase doesn't accidentally name the fault

Output goes into a new artifact:

```
data/derived/global/<id>/jira-shadow-humanized-v1/
  timeline.jsonl           # one row per humanized ticket
  generation-manifest.json # which episode, persona seeds, prompt hashes
  sample-comparison.md     # original shadow vs humanized side-by-side for 5 episodes
```

The original `jira-memory-corpus.jsonl` is **untouched** as the
baseline. Pipelines opt into the new corpus via a CLI flag for A/B
comparison.

Decision criteria after the spike:
- ≥4 of 5 tickets read as plausibly human to a domain reader (eyeball)
- 0 lab-leakage tokens detected by the sanitizer at LLM input
- 0 of the leakage-canary fail signals trip
- Vocabulary differs measurably across persona seeds (lexical
  overlap < 0.7 between two `report` steps for different families)

If those pass → proceed to Phase 3. If any fails → diagnose and
re-prompt before scaling.

---

## 10. Where this fits

| Doc | Relationship |
| --- | --- |
| `ML-NEW-IDEAS.MD` | Move A (characteristic-log-line extractor) is a hard prereq for Rule 4 (Quote, don't summarize). Move C (leakage canary on text fields) is a hard prereq for Phase 5 validation. |
| `todo.md` | Extends Phase 6 (Memory enhancement). Specifically replaces the original `6.1 LLM-generated summary field` with this much richer multi-step generation. |
| `todo-v5available.md` §3.5 | Closes the "evidence_text could include L3 business events" gap by writing real conversational mentions of business events into ticket descriptions. |
| `src/memorygraph/EXPERIMENTS.md` | Once Phase 5 lands, swap the Jira memory corpus and re-run `memorygraph_full`. Record as E7 (or whatever's next). |
| `docs/jira-shadow-issue-contract.md` | The TIMELINE schema is an extension, not a replacement. Original `jira_shadow_issue.schema.json` remains for the legacy generator. |
| `docs/triage-task-contract.md` | Field policy stays the same. The LLM input sanitizer is the enforcement layer; the contract is unchanged. |

---

## 11. Open questions

1. Should `report` always come from `cs-agent` or sometimes from
   `oncall-sre` (paged before user-impact)? Real ratio probably
   ~60/40. Make persona-of-report a random draw weighted by severity:
   `critical` → 70% on-call paged first, `major` → 50/50, `minor` →
   80% CS forward.
2. How do we handle tickets for `borderline` windows where no human
   would actually file? Skip them entirely (no synthetic ticket) for
   80% of borderline, generate a self-closed ticket for 20%. The
   no-ticket case is its own signal — it teaches the model that
   borderline ≠ ticket-worthy.
3. Do we want a `chaos-mesh` aware persona (someone who recognizes
   network-partition symptoms specifically)? Probably not — would
   create a leak path. Keep all personas service-aware, not
   fault-mechanism-aware.
4. Should the resolver always identify the actual root cause? In real
   data ~30% of tickets close without a clearly-identified cause.
   Sample resolution-includes-cause as `0.7 * (1 - is_hard_case)` so
   hard cases more often close without a clear cause.

---

## 12. Reproducibility

Every humanized ticket gets a manifest entry capturing:

- `episode_id` it was generated for
- The 5 persona seeds (which avatar from each role)
- The hash of every prompt that hit the LLM
- LM Studio model id + temperature
- Sanitizer version + symptom-map version
- Git SHA of the generator

So a future contributor can re-run the exact generation deterministically
(modulo LLM nondeterminism, which Qwen at temperature=0.7 keeps under
~10% lexical variance).
