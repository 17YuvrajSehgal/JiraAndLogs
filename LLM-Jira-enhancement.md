# LLM-Jira-enhancement.md — TIMELINE: a brilliant Jira humanization design

**Captured:** 2026-05-28.
**Amended:** 2026-05-31 — see §13 for the V2 redesign (TAWOS-grounded,
log-first, 1:1 coverage, distractor tickets). Sections 1-12 are the
V1 spec as originally captured; V2 amends — does not replace — them.
**Status:** Phases 1-5 of V1 shipped (commits `5ef4f1a` through
`d041ebb`); bulk humanizer output at
`data/derived/global/2026-05-25-dataset-v5-large-global/jira-shadow-humanized-v1/`.
E5/E6/E7 cross-train evidence drove the V2 redesign in §13.
**Related:** `ML-NEW-IDEAS.MD` (raw logs as a first-class signal — its
Move A "characteristic log line extractor" is a hard prerequisite for
the evidence quoting in this design; **V2 promotes Move A from soft
prerequisite to strict per-ticket requirement**).

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

---

## 13. V2 amendment — TAWOS-grounded, log-first redesign (2026-05-31)

**Status:** Evidence pipeline shipped (2026-05-31). Built:
`src/memorygraph/log_signatures.py` extended with
`extract_characteristic_signature()` (active-vs-baseline diff) and
`signature_for_episode()` (cross-service fallback);
`src/jira_humanizer/evidence_bundle.py` (multi-channel evidence:
logs + metrics + traces + k8s + alerts, with persona-step slicing).
Smoke-tested across 12 diverse fault episodes — 12/12 sanitizer-clean,
0% all-empty rate (was 11% logs-only). **Next:** wire `build_evidence`
+ `slice_for_step` into `timeline_generator.py` per §13.8 step 1.

V1 (TIMELINE Phases 1-5) shipped and got us a 347-ticket corpus. E5/E6/E7
cross-train experiments showed retrieval lifts only directionally on the
humanized corpus and pinpointed the bottleneck: the humanized
`memory_text` leads with cs-agent voice ("Customer reports slow site
performance..."), so BM25 indexes customer-support vocabulary instead of
engineer vocabulary. Move A (characteristic log line extractor, 4c23ef7)
helped only marginally because it was bolted onto a corpus whose primary
text channel was already off-distribution.

The user pivoted on 2026-05-31: explore TAWOS (458K real Jira issues,
local MySQL, see `scratch/tawos_explore.py` and `tawos_explore2.py`),
let empirical distributions drive a V2 humanizer, and add two
project-specific constraints (§13.4, §13.5) that TAWOS does not have.

The V1 leakage-safety rules (§3) — vocabulary firewall, symptom
paraphrase, misattribution, quote-don't-summarize, close-as-noise —
stay verbatim. V2 changes the *schema*, *length*, *voice*, *log
emphasis*, and *coverage*. It is a tightening, not a rewrite.

### 13.1 What TAWOS empirically showed us

Query script: `scratch/tawos_explore2.py`. Distributions are
project-wide across 39 OSS projects, with a SRE-relevant subset
(MongoDB SERVER, Mesos, Mule, Hyperledger Fabric) cross-checked.

| Dimension | TAWOS real (n=458,232 issues) | V1 synthetic | V2 target |
| --- | --- | --- | --- |
| Description length (median) | 200-500 chars; 56% under 500, 82% under 1000 | 1.5-3K chars (multi-paragraph + markdown) | 200-500 chars, no markdown headers |
| Pasted log/stack block stored separately | 20.5% of bugs carry one; 16.5% substantial | Inline / generic placeholder | **100% of tickets** (see §13.3) |
| Comments per issue | 36% have 1, 43% have 2-5, 14% have 6-15, 4% have 15+ | Fixed at 4 steps | Sample from empirical distribution |
| Resolution time | 4% <1h, 11% 1h-1d, 20% 1d-1wk, 25% 1wk-1mo, 40% >1mo | Compressed to a single moment | Sample from empirical distribution |
| Resolution outcome | Fixed 60%, Won't Fix 15%, Duplicate 12%, Cannot Reproduce 4%, Not A Bug 3%, Timed out 4% | Always Fixed | Match empirical mix |
| Voice | Terse pager-speak + raw log paste mid-thread, multi-month gaps | Verbose cs-agent voice with `### Summary` headers | Engineer pager-speak; no markdown |
| Stack-trace tokens (when code block present) | Java-heavy: `com.` 38%, `Exception` 37%, `java.` 33%, `org.` 30%, `Caused by:` 12%, `NullPointerException` 7% | N/A | Bias toward these when emitted |

The structurally-surprising find is TAWOS's `Description_Text` /
`Description_Code` column split (mirrored in `Comment_Text` /
`Comment_Code`). Real Jira already separates prose from pasted blocks;
V1's single `description` field collapsed that and forced the LLM to
weave logs into narrative — exactly the channel where leakage and
voice-pollution sneak in. V2 inherits the split.

### 13.2 Schema additions

Extend `src/jira_humanizer/timeline_schema.py`:

```python
@dataclass
class TimelineComment:
    persona: str
    t_offset_s: int
    body: str                 # prose only (Comment_Text analog)
    body_code: str | None     # NEW — pasted log lines / stack frames / diff
                              #       (Comment_Code analog). None when this
                              #       comment doesn't paste anything.

@dataclass
class HumanizedTicket:
    summary: str                       # terse, declarative, no markdown
    description: str                   # PROSE ONLY, 200-500 chars typically
    description_code: str              # NEW — populated per §13.3 (target ≥80%).
                                       # Holds 1-5 characteristic log lines
                                       # from the source telemetry window.
                                       # Empty allowed per rule 3c.
    comments: list[TimelineComment]    # variable length per §13.1 distribution
    resolution: str                    # Fixed | Won't Fix | Duplicate |
                                       # Cannot Reproduce | Not A Bug | Timed out
    resolution_time_s: int             # NEW — sampled from empirical distribution
    is_distractor: bool                # NEW — see §13.5; never exposed at retrieval
    is_followup_of: str | None         # NEW — see §13.9 #3; parent ticket_id for
                                       # critical-severity followup tickets
    source_episode_id: str             # provenance back to episodes.jsonl
    source_injection_id: str | None    # provenance back to the injected fault
                                       # (None for distractors and baseline tickets)
    log_signature_source: str          # "diff" | "plain_fallback" | "empty"
                                       # — captured from signature_for_episode()
    evidence_bundle_hash: str          # sha256 of the canonical EvidenceBundle
                                       # for reproducibility (§12)
```

Write the V2 corpus to `data/derived/global/<id>/jira-shadow-humanized-v2/`.
V1 stays untouched as the comparison baseline.

### 13.3 The log-first principle — most important, but not absolutist

**This is what makes our project different from TAWOS.** TAWOS is a
general-purpose Jira corpus; pasted logs there are *decoration* (80% of
bugs ship without one). Our product is a **log-anomaly flagger** that
will be deployed in production environments — the agent's entire value
is "I've seen this unusual log pattern before, here is the past ticket
that matched it." If the synthetic memory corpus rarely grounds tickets
in real unusual log content, the agent has nothing useful to retrieve
against.

So we strongly bias toward log inclusion — but we must **not force a
quote when the reporter wouldn't naturally see a relevant log**, and we
must **not paste a log line that isn't actually related to the
problem**. A fabricated or irrelevant quote teaches the model to
retrieve on noise, which is worse than no quote at all. Production
Jira tickets work the same way: a CS agent forwarding a customer
complaint usually doesn't have access to backend logs; a senior SRE
who got paged does. The synthetic must mirror that asymmetry.

Concrete rules:

1. **Aim for `description_code` populated on the strong majority of
   tickets — target ≥80%.** It holds 1-5 lines drawn through
   `extract_log_signature()` (`src/memorygraph/log_signatures.py`,
   committed 4c23ef7). When Move A returns a non-empty signature, use it.
2. **Quote only when relevant.** "Characteristic" means rare in baseline
   but present in the fault window (Move A's definition). If the
   characteristic lines for a window aren't semantically related to
   what the reporter persona could plausibly have seen (e.g., a `cs-agent`
   reporting a checkout 500 doesn't paste a Redis stack trace from
   cartservice's pod), drop the quote rather than fabricate or
   force-fit. Persona-evidence pairing is gated on what that persona's
   step has access to per §5.
3. **Graceful fallback when no good log exists.** Three accepted paths,
   in priority order:
   - (a) Move A returns relevant lines → use them in `description_code`
     and let the reporter paraphrase one in prose
   - (b) Move A returns lines but they don't fit the reporter persona →
     `description_code` still gets the raw lines (for retrieval BM25
     grounding), but the reporter's prose `body` does NOT quote them
     (the on-call SRE's `ack` step or a later commenter who DOES have
     access can paste them instead)
   - (c) Move A returns nothing characteristic for the window →
     `description_code` is empty for this ticket; reporter writes
     prose-only; **log the empty-signature event in the manifest for
     analysis**, but do NOT block ticket generation. These tickets
     become valuable training data for the "anomaly without distinctive
     log signal" case, which production will absolutely see.
4. **Quote frequency in prose follows persona, not a hard quota.**
   Personas with backend access (`oncall-sre`, `backend-eng`,
   `senior-sre`, `fix-author`, `db-team`) quote logs raw when relevant.
   `cs-agent` paraphrases customer-visible symptoms, occasionally
   relays a log snippet a customer sent. `eng-mgr` and `junior-eng`
   rarely paste raw logs.
5. **Java/JVM-style stack-trace bias when synthesizing.** When a stack
   frame must be synthesized rather than drawn (rare — only for
   distractors in §13.5), format it Java/JVM-style to match the TAWOS
   token frequency distribution.
6. **Never paste a fabricated log line that wasn't actually emitted
   by the running service.** Real-vs-fake log content is the line we
   never cross. If we need a log and don't have one, we degrade to
   prose-only (rule 3c) — we do not invent one.

This makes Move A a **strong default per-ticket input**, not a hard
build-time gate. Empty-signature tickets are allowed, expected, and
themselves useful training signal.

### 13.4 Coverage rule — 1:1 ticket per injected fault

V1's §11 Open Q #2 ("skip ticket generation for 80% of borderline
windows") is **overridden** for the injected-fault set.

Our data scale story is fundamentally different from TAWOS:

- TAWOS = 39 projects × multi-year collection = 458K tickets, easily
  affording skipped coverage and sparse fault families
- Ours = 1 project (Online Boutique) × 5-day raw collection = bounded
  fault injection count. **We cannot afford to skip any injected
  fault** — each one is a precious training signal

Therefore:

- **Every injected fault episode** in the 5-day raw run gets exactly
  one humanized V2 ticket. No exceptions.
- The ticket is generated from the telemetry slice the human triager
  would have seen at detection time (matching V1 §5's per-step
  evidence rules)
- Borderline / recovered-in-window / baseline windows that were NOT
  injected may still stay ticket-less (or get a §13.5 distractor) —
  the coverage rule applies only to the labeled-injection set
- Build-time check: emit a manifest entry per injection_id; assert
  `len(injections) == len({t.source_injection_id for t in tickets if not t.is_distractor})`

### 13.5 Diversity / distractor tickets

Coverage alone doesn't tell us if the agent retrieves the **right**
ticket — only that *some* ticket exists for each fault. To test
retrieval precision we mix in **distractor tickets**: well-formed Jira
issues that describe plausible incidents that **never happened** in our
corpus.

Sourcing strategy (target: 20-30% of the final V2 corpus is distractors):

- Cross-architecture distractors: bugs in components we don't have
  (Kafka consumer lag when our system has no Kafka, Spark job OOM,
  Postgres replication lag, etc.). High retrieval-confusion potential
  with infra-flavored vocabulary.
- TAWOS-sampled distractors: pull real bug reports from
  `tawos.issue` filtered to similar projects (MongoDB SERVER, Mesos,
  Mule) — scrub project-specific names, run through the V1 vocabulary
  firewall, mark `is_distractor=true`. These are guaranteed-realistic
  voice samples.
- In-architecture-but-never-happened distractors: bugs in our own
  services that were never injected (e.g., a fake "payment service
  rate limiter dropping calls" when we never injected that fault).
  Hardest distractors; tests whether the agent matches on actual log
  evidence vs. service-name lexical overlap.

Distractors carry `is_distractor=true` in their schema row. The agent
**never sees this flag** at retrieval — it's evaluation-only metadata.

### 13.6 Validation — what "V2 is better than V1" looks like

New headline metric: **top-1 retrieval precision against the
distractor set**. For each held-out injection window, the agent's top-1
retrieved ticket must be (a) the correct ground-truth ticket for that
injection AND (b) NOT a distractor.

Layered validation:

1. **Leakage canary** — existing `src/jira_features/leakage_canary.py`
   (per V1 §10) re-runs unchanged on V2. All V1 firewall rules still
   apply. If V2 trips canary that V1 passed, V2 ships nothing.
2. **Coverage assertion** — build-time check from §13.4. Manifest-level.
3. **Distribution match** — sanity-check V2 corpus distributions match
   the §13.1 targets within ±10% (length buckets, comment counts,
   resolution mix). Stratified-sample script in
   `scripts/research-lab/validate_v2_distributions.py` (TBD).
4. **Retrieval benchmark** — train memorygraph on V2, compare top-1
   and top-3 retrieval precision against the same windows on V1 and
   on legacy corpora. Hypothesis: V2 lifts past the E7 retrieval
   ceiling because `description_code` carries the engineer-vocabulary
   the BM25 lead-text was missing.
5. **Distractor confusion matrix** — for each window, log whether
   top-1 was: correct, wrong-real-ticket, distractor. Aim for distractor
   confusion rate <5% at top-1.
6. **Stratified manual review** — 5 tickets per fault family + 5
   distractors. Same eyeball criteria as V1 §9.

### 13.7 What stays unchanged from V1

- All 5 leakage-safety rules (§3) — vocabulary firewall, symptom
  paraphrase map, misattribution rate, quote-don't-summarize,
  close-as-noise. **Non-negotiable.**
- Persona catalog (§4) — same 9 personas, same deterministic avatar
  pool (still reuse `_NAMES` in `rewrite.py`)
- Telemetry × Logs × Jira temporal integration (§5) — per-step
  evidence windows are unchanged conceptually. §13.12 *extends* the
  evidence channels at each step from "logs only" to multi-channel
  (logs + metrics + trace summary + k8s state + alerts), but the
  temporal-asymmetry principle and the persona-step access pattern
  (cs-agent sees nothing technical, senior-sre sees everything)
  carries through.
- Reproducibility manifest (§12) — extended with new V2 fields
  (`is_distractor`, `source_injection_id`, `log_signature_hash`,
  `log_signature_source` (`diff`/`plain_fallback`/`empty`),
  `evidence_bundle_hash`) but the principle is identical.

### 13.8 Implementation order (when user signals go)

Suggested staging — small landable PRs, each independently
verifiable. Already-built infrastructure noted with **[BUILT]**.

0. **[BUILT 2026-05-31] Evidence pipeline** —
   `extract_characteristic_signature()` + `signature_for_episode()`
   in `log_signatures.py`, plus `evidence_bundle.py` producing the
   multi-channel `EvidenceBundle` with `slice_for_step()` per-persona
   projection. Smoke tested across 12 episodes, 100% sanitizer-clean.
1. **Schema split + wire evidence pipeline + length cut.** Add
   `description_code`, `body_code`, `resolution_time_s`,
   `is_distractor`, `is_followup_of`, `source_injection_id` fields
   to `timeline_schema.py`. Modify `timeline_generator.py` to call
   `build_evidence(episode, components, ...)` once per ticket, then
   `slice_for_step(bundle, step_kind)` per step, and inject the
   sliced multi-channel evidence into each per-step LLM prompt.
   Cap description prose at ~500 chars. Run on 5 test episodes,
   eyeball, then bulk.
2. **Voice rewrite** — drop markdown headers, swap cs-voice for
   engineer pager-speak in `report` and `ack` steps. Update prompts
   to reference `metric_observations` + `alert_names` directly so
   the engineer voice naturally surfaces them. Personas stay,
   prompts get tightened.
3. **Variable comment count + resolution outcome** — sample from
   the §13.1 distributions instead of fixed 4-step.
4. **[BUILT 2026-06-01] Coverage assertion** —
   `scripts/research-lab/validate_v2_coverage.py` reads
   `jira-memory-corpus.jsonl` (expected injections) and the V2
   `timeline.jsonl` (covered injections), diffs them, writes
   `coverage-report.json` next to the corpus, exits 0 on PASS / 1 on
   FAIL. Optional `--strict-1to1` flag enforces "exactly one non-
   distractor ticket per injection" — drops once §13.9 #3 followup
   minting lands. Verified on `bulk-20260531`: **347/347 covered
   (100%), 0 missing, 0 extras**.
5. **Distractor generation** — TAWOS-sampled + cross-arch + in-arch
   distractor pipelines, mixed into the final V2 corpus.
6. **Retrieval benchmark E8** — train memorygraph on V2, log to
   `src/memorygraph/EXPERIMENTS.md`, compare against E7 ceiling.

Stop after each step; verify against the §13.6 layer; only proceed if
green.

### 13.9 Resolved V2 decisions (2026-05-31)

1. **Distractors share the V1 persona catalog.** Voice must not be a
   tell — if distractors had their own persona pool the model would
   learn "voice = distractor" instead of the harder "log content vs.
   window evidence" signal we actually want. So:
   - Cross-arch and in-arch-never-happened distractors use the same
     `oncall-sre` / `backend-eng` / `senior-sre` / etc. personas as
     real V2 tickets
   - Avatar names are rotated from a wider pool for distractors so
     `Sarah Chen` doesn't both handle real cart-redis incidents AND
     file Kafka distractors (would create persona-topic correlation)
   - For TAWOS-sampled distractors specifically, we **don't run them
     through our persona system at all** — the original real-engineer
     voice from TAWOS is preserved (with lab-token scrub via sanitizer
     applied to the OSS-project nouns). These are the "gold standard"
     distractors precisely because their voice is real.
2. **Resample TAWOS-sampled distractor `Resolution_Time_Minutes` to
   our 5-day-collection-realistic distribution.** Real TAWOS times can
   span months; our entire dataset is from a 5-day run, so any model
   correlating `resolution_time > 1 week` with `is_distractor=true`
   would shortcut to easy classification. Resample distractor times
   from the SAME empirical distribution V2 real tickets use, clipped
   to [1h, 5d].
3. **Allow >1 ticket per injection for high-severity faults.**
   - `critical` severity → 1 to 3 tickets per injection. The bug
     ticket always; optionally a follow-up reliability ticket ("add
     monitoring for X", "raise Redis connection pool size") written
     1-3 days later; optionally a postmortem ticket written 1-2 weeks
     later that cross-links to the original. Mirrors how real
     production critical incidents actually spawn tickets.
   - `major` severity → 1 to 2 tickets (sometimes a follow-up).
   - `minor` severity → 1 ticket (per §13.4 coverage rule).
   - Followup tickets carry `is_followup_of: <parent_ticket_id>` and
     count toward `source_injection_id` coverage but do NOT trigger
     the §13.4 coverage assertion failure — only the absence of any
     ticket for an injection does.

### 13.10 Existing per-run inputs the V2 humanizer must consume

The V1 humanizer largely treated the per-run `jira_shadow_issues.jsonl`
as a stub to overwrite. V2 should treat it as **a rich provenance
record** — most of what V2 needs is already there from collection
time.

For each ticket in `data/runs/<run_id>/jira_shadow_issues.jsonl` the
following fields are already populated and should be **inputs** to the
V2 humanizer (some firewalled from the LLM, some passed through):

| Field | Use in V2 | Firewalled from LLM? |
| --- | --- | --- |
| `jira_shadow_issue_id`, `jira_issue_key` | Stable IDs; carried into humanized record | No |
| `dataset_run_id`, `incident_episode_id` | Provenance; lets V2 join back to `episodes.jsonl` for `severity`, `incident_type`, `ground_truth` | No (IDs only) |
| `metadata.summary` | Seed for V2 `summary` — but V2 rewrites in engineer voice, doesn't pass through | Allowed as seed |
| `metadata.description` (free-text dump) | **DO NOT pass through.** Contains `scenario_id`, `root_cause_category`, `fault_id`, full window list — pure lab tokens. V1 already strips this via `sanitizer.py`; V2 inherits | **YES — strict firewall** |
| `metadata.components`, `corrected_components` | Drives §3 misattribution: pre-strip uses `components`, redirect uses `corrected_components` | Pre-redirect: `components`; post-redirect: `corrected_components` |
| `metadata.priority`, `initial_priority`, `resolution` | Drives V2 ticket fields directly | No (these are realistic Jira fields) |
| `metadata.realism_profile` | V2 should bump to `v3.0-tawos-grounded-engineer-voice` | No |
| `metadata.labels` (lab tags) | Strip `dataset-*`, `scenario-*`, `synthetic-*` before any LLM call — sanitizer already does | **YES — strict firewall** |
| `telemetry_links.telemetry_window_ids` | **The keystone input.** The offline orchestrator passes the episode_id + components to `signature_for_episode()` (which internally runs `extract_characteristic_signature()` on the (active, baseline) loki dump pair across all components, with cross-service fallback). The resolved **log lines** (NOT the IDs) flow to the prompt after sanitizer. See §13.11 Graph A + §13.12 bundle schema. | **IDs stay offline; resolved log lines pass through sanitizer first** |
| `telemetry_links.alert_fingerprints` | Orchestrator resolves each fingerprint to its `alerts.jsonl` row → extracts the **alert name** (e.g., `CartServiceP99LatencyHigh`). Alert names reach the LLM as `ack`-step evidence; fingerprint hashes do not. | **Fingerprints stay offline; resolved alert names pass through sanitizer first** |
| `telemetry_links.trace_ids` | Orchestrator picks 1-2 trace_ids, loads `raw/tempo/<id>.json`, extracts a few **span names** and the trace_id string. Engineer personas can quote `trace_id=abc123` realistically in prose. | **Trace IDs and span names pass through sanitizer; full span trees stay offline** |
| `history`, `activity`, `worklog` | Provide realistic timestamps and field-change events the V2 humanizer can use to seed `resolution_time_s` rather than guessing | No |

V1 already shows the schema is rich (10 top-level keys per shadow
ticket). V2's job is to **lift the rich evidence into the humanized
narrative** while keeping the sanitizer firewall intact — not to
overwrite the per-run shadow record. The per-run
`jira_shadow_issues.jsonl` files stay untouched (immutable raw
provenance, same as `raw/loki/`); V2 writes to
`data/derived/global/<id>/jira-shadow-humanized-v2/timeline.jsonl`.

This also gives V2 a clean **production-fidelity** story: in a
production deployment we will not have `scenario_id` / `fault_id` /
ground-truth labels available — only the equivalent of
`telemetry_window_ids` + `alert_fingerprints` + `trace_ids` (i.e.,
what the on-call engineer's tooling can pull at incident time). V2's
LLM input surface should look exactly like that production input
surface, so the model we train ports directly. The V1 lab tokens
firewall (§3 Rule 1) is what enforces this.

### 13.12 Multi-channel evidence bundle (logs + metrics + traces + k8s + alerts)

Real engineers don't triage from logs alone — they triage from
**Grafana panels + Pagerduty alerts + kubectl + the trace UI**.
Restricting V2's LLM input to log lines would teach the model a
one-channel view that doesn't match production. V2 therefore extends
the per-step `evidence` block with four additional channels.

#### What's already pre-computed

`data/derived/global/<id>/global-triage-examples.jsonl` ships **94
`triage_feature_*` columns per window**, all derived once and stable.
We **don't re-extract from raw**; we read this file:

| Column family | Count | What's in it |
| --- | ---: | --- |
| `delta_*` | 47 | active-vs-pre-fault baseline deltas (latency p95/p50, error rate, RPC throughput per status code, business metrics, k8s state) |
| `m05_*` | 33 | absolute RED + business + runtime metrics (current values) |
| `trace_*` | 6 | `trace_count`, `trace_error_count`, `trace_error_rate`, `trace_latency_{p50,p95}_ms`, `trace_span_count` |
| `k8s_*` | 3 | `k8s_restart_count`, `k8s_warning_event_count`, `k8s_pod_unavailable_count` |
| `log_*` | 3 | log volume counts |
| `metric_*` | 2 | container CPU/memory percent (untrusted units — see paraphrase guard) |

Plus `data/runs/<run_id>/alerts.jsonl` gives **real firing alert
names** per episode (e.g. `OnlineBoutiqueNearMissResourcePressure`,
`KubePodCrashLooping`, `OnlineBoutiqueContainerRestarting`) — these
are what an on-call engineer's pager actually shows in production.

#### The bundle schema

```python
@dataclass
class EvidenceBundle:                  # src/jira_humanizer/evidence_bundle.py
    episode_id: str
    log_lines: list[str]               # Move A (signature_for_episode)
    log_lines_source: str              # "diff" | "plain_fallback" | "empty"
    log_lines_service: str | None      # which component drove the signature
    metric_observations: list[str]     # paraphrased top-K |delta_*|
    trace_summary: dict[str, Any]      # {trace_count, error_rate, p50_ms, p95_ms, ...}
    k8s_state: dict[str, Any]          # {restart_count, warning_event_count, ...}
    alert_names: list[str]             # firing alerts, noise-filtered
    symptom_phrase: str                # from symptom_map (§3 Rule 2)
    trace_id_quoted: str | None        # one trace_id from telemetry_links
    primary_service: str | None        # component driving the bundle
```

#### Paraphrase guard (bias-free guarantee)

Raw delta values like `delta_trace_latency_p95_ms = 6348.26` are
useless to an LLM and would leak training signal as numeric features.
We paraphrase via a **curated lookup table** of feature-suffix →
engineer-voice formatter (see `evidence_bundle._PARAPHRASERS`):

- `delta_trace_latency_p95_ms = +6348` → `"trace p95 latency +6.35s vs baseline"`
- `delta_m05_rpc_status_ok_per_sec = -38.5` → `"RPC OK throughput -38.5/sec"`
- `delta_k8s_restart_count = 9` → `"+9 pod restarts vs baseline"`
- `delta_trace_error_rate = 0.355` → `"trace error rate +35.5% vs baseline"`

Only features in the curated table are paraphrased — anything outside
(e.g. `metric_memory_pct` which has broken units) is silently
**dropped**, not guessed at. This prevents bad units from poisoning
the training signal.

Every paraphrased string is then re-run through `find_lab_tokens`
(defense-in-depth on top of the V1 sanitizer) before it reaches the
LLM.

#### Persona-step pairing — who sees what

Persona-step slicing matches real triage access patterns. The
`cs-agent` who took the customer call has no Grafana access; the
`senior-sre` who joined the war room has everything. This is enforced
by `slice_for_step(bundle, step_kind)`:

| Step (persona) | log_lines | metric_obs | trace_summary | k8s_state | alert_names | trace_id |
| --- | ---: | ---: | :---: | :---: | ---: | :---: |
| `report` (cs-agent) | 0 | 0 | — | — | 0 | — |
| `ack` (oncall-sre) | 1 | 1 | — | ✓ | 3 | — |
| `hypothesis` (backend-eng) | 4 | 3 | ✓ | ✓ | 0 | ✓ |
| `redirect` (senior-sre) | 3 | 5 | ✓ | ✓ | 3 | ✓ |
| `resolve` (fix-author) | 3 | 3 | ✓ | ✓ | 3 | ✓ |

Numbers = top-K items from that channel. `✓` = full payload. `—` =
channel hidden from this persona-step.

The `report` step gets **only the symptom phrase** — matching reality:
the customer-support agent forwarding a ticket has no backend
telemetry. The `ack` step gets the alert names + 1 key metric (what
paged them) + restart counts (first thing on-call checks). The
`hypothesis` step adds logs and trace summary (engineer dives in).
The `redirect` and `resolve` steps see everything (senior-sre / fix
author have the full picture).

#### Worked example — cart-redis-degradation-critical

For episode `...cart-redis-degradation-critical-...`, the full bundle
looks like:

```
log_lines (diff, frontend, n=5):
  http_req_method=GET http_req_path=/product/<sku> request error could
    not retrieve cart: rpc error: code = Unavailable desc = ...
  http_req_method=GET http_req_path=/product/<sku> request error could
    not retrieve cart: rpc error: code = FailedPrecondition desc =
    Can't access cart storage. StackExchange.Redis.RedisConnectionException
  ...

metric_observations (n=5):
  trace p95 latency +6.35s vs baseline
  -2151 spans vs baseline
  +261 new error spans vs baseline
  +223 new error log lines
  RPC OK throughput -38.5/sec

trace_summary:
  trace_count=474, error_count=261, error_rate=0.355, p95_ms=6360.95

k8s_state:
  restart_count=9, warning_event_count=13, pod_unavailable_count=1

alert_names (firing, noise-filtered, n=8 — sample of 3 shown):
  CPUThrottlingHigh
  OnlineBoutiqueContainerRestarting
  OnlineBoutiqueDeploymentUnavailable

symptom_phrase: "users seeing cart-not-loading after add-to-cart"
trace_id_quoted: 10131a0aa2cd011f9268663c...
```

Which the persona-step slicer projects to:

```
[report]      symptom_phrase only
[ack]         + 1 log line + "trace p95 latency +6.35s vs baseline"
              + k8s_state + 3 alert_names
[hypothesis]  + 4 log lines + 3 metric_obs + full trace_summary
              + k8s_state + trace_id
[redirect]    + 3 logs + 5 metrics + full trace + k8s + 3 alerts + trace_id
[resolve]     + 3 logs + 3 metrics + full trace + k8s + 3 alerts + trace_id
```

An on-call SRE writing the `ack` step would naturally produce:

> acked. `CPUThrottlingHigh` + `OnlineBoutiqueContainerRestarting` +
> `OnlineBoutiqueDeploymentUnavailable` firing. trace p95 +6.35s vs
> baseline, 9 restarts / 1 pod unavailable. looking at cartservice logs.

Which is the engineer pager-speak voice we want — and EVERY token in
the prompt either came from a derived feature column, a real alert
name, or a sanitizer-cleaned log line. Zero lab leakage, full
production fidelity.

#### Empty-bundle handling

`EvidenceBundle.is_low_signal()` returns True when all channels are
empty and `trace_error_rate < 1%`. Caller can route these to a
prose-only ticket per §13.3 rule 3c. Real production absolutely sees
these — incidents that get filed on a vague hunch — so they're useful
training data.

#### Implementation

Code: `src/jira_humanizer/evidence_bundle.py` (~330 lines). Read path:

1. `signature_for_episode()` for logs (Move A, V2-extended with diff +
   cross-service fallback per §13.11)
2. `_load_triage_rows_for_episode()` joins to
   `global-triage-examples.jsonl` for the per-service derived rows
3. `_paraphrase_deltas()` picks cross-service-max top-K | delta | and
   renders via the curated table
4. `_summarize_trace()` picks the worst-p95 row as the trace summary
5. `_summarize_k8s()` aggregates restart/warning/unavailable across
   services
6. `_load_alert_names_for_episode()` filters `alerts.jsonl` by
   `incident_episode_id` + `status=firing`, deduplicates, drops the
   `_NOISE_ALERTS` set (`Watchdog`, `TargetDown`,
   `KubeProxyInstanceUnreachable` — kind-cluster constants)
7. `_strip_unsafe()` runs every string through `find_lab_tokens` —
   anything dirty is silently dropped

Smoke test: `scratch/smoke_evidence_bundle.py`.

### 13.11 Generation workflow — what reaches the LLM, what doesn't

The IDs in §13.10 are confusing without seeing the flow. This section
shows the full pipeline from raw run artifacts to one humanized
ticket, makes the firewall explicit, and walks through a concrete
cart-redis example.

#### Graph A — End-to-end pipeline (one ticket)

```mermaid
flowchart TD
    SR["data/runs/RUN_ID/<br/>jira_shadow_issues.jsonl<br/><i>(per-run shadow record)</i>"]
    EP["data/runs/RUN_ID/<br/>episodes.jsonl<br/><i>(severity, ground_truth)</i>"]
    AL["data/runs/RUN_ID/<br/>alerts.jsonl<br/><i>(alert names)</i>"]
    LK["data/runs/RUN_ID/<br/>raw/loki/&lt;window_id&gt;.json<br/><i>(actual log lines)</i>"]
    GTE["data/derived/global/&lt;id&gt;/<br/>global-triage-examples.jsonl<br/><i>(94 triage_feature_* cols<br/>per window: delta_*, m05_*,<br/>trace_*, k8s_*)</i>"]

    ORC["Offline orchestrator<br/>(timeline_generator.py V2<br/>calls evidence_bundle.build_evidence)"]

    SR --> ORC
    EP --> ORC

    ORC -->|"episode_id + components"| MA["signature_for_episode()<br/><i>Move A diff + cross-svc fallback<br/>see Graph C</i>"]
    LK --> MA
    ORC -->|"episode_id"| AR["_load_alert_names_for_episode<br/><i>filter status=firing,<br/>drop noise alerts</i>"]
    AL --> AR
    ORC -->|"episode_id"| MET["_paraphrase_deltas<br/><i>top-K abs(delta_*) -> engineer prose<br/>via curated lookup table</i>"]
    GTE --> MET
    ORC -->|"episode_id"| TKS["_summarize_trace +<br/>_summarize_k8s<br/><i>p95/error_rate, restart_count, etc.</i>"]
    GTE --> TKS

    MA --> EVB["EvidenceBundle<br/>{log_lines, metric_observations,<br/>trace_summary, k8s_state,<br/>alert_names, symptom_phrase,<br/>trace_id_quoted}"]
    AR --> EVB
    MET --> EVB
    TKS --> EVB
    SM["symptom_map.py<br/>(scenario_id -> symptom phrase)"] --> EVB

    EVB --> SAN["_strip_unsafe<br/>find_lab_tokens on every string<br/>(scenario / fault / chaos / ...)"]
    SAN -->|"silently drop dirty strings"| SLC["slice_for_step(bundle, step_kind)<br/><i>persona-step access projection</i>"]

    SLC --> STEPS["Per-step LLM calls<br/>(report -> ack -> hypothesis -> resolve)"]
    PER["personas.py<br/>(role + voice guide + avatar)"] --> STEPS
    STEPS -->|"one call per step"| LLM[("Qwen via LM Studio<br/>or Claude Haiku")]
    LLM --> TXT["step text +<br/>optional body_code"]

    TXT --> ASM["Assemble HumanizedTicket<br/>(description, description_code,<br/>comments[], resolution, ...)"]
    ASM --> CAN["leakage_canary.py<br/>final text check"]
    CAN -->|"fail"| ERR["Manifest error<br/>(skip ticket, log)"]
    CAN -->|"pass"| OUT["data/derived/global/&lt;id&gt;/<br/>jira-shadow-humanized-v2/<br/>timeline.jsonl"]

    classDef firewall fill:#fee,stroke:#c66,stroke-width:2px;
    classDef offline fill:#eef,stroke:#66c;
    classDef llm fill:#efe,stroke:#6c6,stroke-width:2px;
    class SAN,CAN firewall
    class ORC,MA,AR,MET,TKS,EVB,SLC,ASM offline
    class LLM,STEPS llm
```

The orchestrator resolves IDs and feature values offline. **No raw ID —
no `telemetry_window_id`, no `trace_id` hash, no `alert_fingerprint`
hash, no raw `delta_*` numeric value — ever enters the LLM prompt as
itself.** Only their resolved/paraphrased forms do, and only after
`_strip_unsafe` silently drops any string that trips
`find_lab_tokens`.

#### Graph B — Firewall view: what stays offline vs. what reaches the LLM

```mermaid
flowchart LR
    subgraph LAB["LAB-ONLY (firewalled, never reach LLM)"]
        SID["scenario_id, fault_id,<br/>root_cause_category"]
        TWI["window_ids, alert_fingerprints,<br/>trace_ids<br/>(opaque hashes)"]
        DRAW["raw delta_* / m05_* / trace_* /<br/>k8s_* feature numbers<br/>e.g. 6348.26, -38.49"]
        GT["ground_truth labels<br/>is_hard_case, is_novel,<br/>triage_label"]
        LAB_DESC["metadata.description<br/>(machine-generated dump<br/>with all lab tokens)"]
        LAB_LBL["metadata.labels<br/>scenario-*, dataset-*,<br/>synthetic-*"]
    end

    subgraph RES["RESOLVED + PARAPHRASED (sanitizer-gated, then LLM)"]
        LL["log_lines<br/>e.g. http_req_method=GET<br/>.../product/&lt;sku&gt; request error<br/>could not retrieve cart..."]
        AN["alert_names<br/>e.g. CPUThrottlingHigh,<br/>OnlineBoutiqueContainerRestarting"]
        MO["metric_observations<br/>e.g. trace p95 latency +6.35s vs baseline,<br/>RPC OK throughput -38.5/sec,<br/>+9 pod restarts vs baseline"]
        TR["trace_summary dict<br/>{p95_ms:6361, error_rate:0.355,<br/>count:474, ...}"]
        K8["k8s_state dict<br/>{restart_count:9,<br/>warning_event_count:13, ...}"]
        SYM["symptom_phrase<br/>e.g. users seeing<br/>cart-not-loading after add-to-cart"]
        TID["trace_id string<br/>(opaque hash, engineer-quotable)"]
    end

    subgraph PROD["PRODUCTION INPUT (what on-call tooling has)"]
        WID["window_ids"]
        FP["alert_fingerprints"]
        TI["trace_ids"]
        GRAFANA["live Grafana<br/>metric panels"]
    end

    TWI -.->|"signature_for_episode<br/>(raw/loki dumps)"| LL
    TWI -.->|"_load_alert_names<br/>(alerts.jsonl)"| AN
    DRAW -.->|"_paraphrase_deltas<br/>curated lookup table"| MO
    DRAW -.->|"_summarize_trace<br/>worst-p95 row"| TR
    DRAW -.->|"_summarize_k8s<br/>max across services"| K8
    SID -.->|"symptom_map lookup"| SYM
    TWI -.->|"first trace_id,<br/>as-is"| TID

    PROD ==>|"same resolution path<br/>in production"| RES

    SAN["_strip_unsafe<br/>find_lab_tokens on EVERY string<br/>(silently drops dirty entries)"]
    LL --> SAN
    AN --> SAN
    MO --> SAN
    TR --> SAN
    K8 --> SAN
    SYM --> SAN
    TID --> SAN

    SAN -->|"clean"| SLC["slice_for_step<br/>(persona-step projection<br/>per §13.12 table)"]
    SLC --> LLM[("LLM call<br/>per timeline step")]

    classDef lab fill:#fee,stroke:#c66;
    classDef res fill:#efe,stroke:#6c6;
    classDef prod fill:#eef,stroke:#66c;
    class SID,TWI,DRAW,GT,LAB_DESC,LAB_LBL lab
    class LL,AN,MO,TR,K8,SYM,TID res
    class WID,FP,TI,GRAFANA prod
```

The PROD row makes the production-fidelity claim concrete: in a real
deployment we have `window_ids` + `alert_fingerprints` + `trace_ids`
from the observability stack and live Grafana panels — the same shape
of input the lab provides offline. The orchestrator's resolution path
is the same code in both worlds. Swap raw files for live Loki / Tempo
/ Alertmanager / Prometheus queries and the prompt surface is
identical, so the model trained on V2 ports directly.

#### Graph C — Inside `signature_for_episode()` and `extract_characteristic_signature()`

```mermaid
flowchart LR
    EP["episode_id + components<br/>e.g. cart-redis-...,<br/>[cartservice, frontend, checkoutservice, redis-cart]"]

    subgraph PASS1["Pass 1: diff across all components"]
        FOR["for svc in components:"]
        A["raw/loki/&lt;ep&gt;-active_fault-&lt;svc&gt;.json"]
        B["raw/loki/&lt;ep&gt;-pre_fault_baseline-&lt;svc&gt;.json"]
        A --> TPL["templater + sanitizer + dedup<br/>(severity=ERROR/WARN only)<br/>SKU paths normalized to /product/&lt;sku&gt;"]
        B --> TPL
        TPL --> SC["score(t) = (active+1) / (baseline+1)<br/>keep if score >= 2.0<br/>AND active_count >= 2"]
        SC --> POOL["pool all surviving templates<br/>across all services<br/>(template, score, svc)"]
    end

    EP --> FOR
    FOR -.->|"per service"| A
    FOR -.->|"per service"| B

    POOL --> RANK["sort by score desc,<br/>dedup identical templates<br/>across services"]
    RANK --> TOPK["return top-K templates<br/>+ service that produced top-1<br/>source = 'diff'"]

    POOL2["if pool empty (no diff hits anywhere)"]
    POOL -.->|"empty"| POOL2
    POOL2 --> PLAIN["Pass 2: walk components in order,<br/>return first plain top-K-in-active<br/>source = 'plain_fallback'"]
    POOL2 -.->|"plain also empty"| EMPTY["source = 'empty'<br/>(rule 3c case)"]

    classDef pass fill:#eef,stroke:#66c;
    classDef out fill:#efe,stroke:#6c6;
    class FOR,A,B,TPL,SC,POOL,RANK,POOL2,PLAIN pass
    class TOPK,EMPTY out
```

Output of `signature_for_episode` is a tuple
`(service_used, log_lines, source)` where `log_lines` is a list of
**actual raw log lines** — not templates, not summaries. The diff
(score ≥ 2.0 with +1 smoothing on both sides) drops templates that
appear equally in baseline. The cross-service fallback handles
latency / silent-source-service faults (productcatalogservice latency
emits no errors itself; frontend hits timeouts calling it). The
empty-result case is allowed per §13.3 rule 3c — those become
prose-only tickets, themselves useful training signal.

#### Worked example — one cart-redis ticket end-to-end

Numbers and alert names below are **actual output** from
`scratch/smoke_evidence_bundle.py` against the
`cart-redis-degradation-critical-20260525T134155Z` episode in
`compact-a-r01`. Not aspirational — what the pipeline actually
produces today.

**1. Offline orchestrator reads:**
- `jira_shadow_issues.jsonl` row → `metadata.priority="Critical"`,
  `metadata.components=["cartservice","checkoutservice","frontend","redis-cart"]`,
  `telemetry_links.telemetry_window_ids` (12), `alert_fingerprints` (12),
  `trace_ids` (~hundreds)
- `episodes.jsonl` row → `severity="critical"`, `incident_type`,
  `affected_services`
- `global-triage-examples.jsonl` rows for this episode (1 per
  affected service in `active_fault` window) → 94
  `triage_feature_*` columns each

**2. Offline orchestrator builds the bundle:**
```
log_lines (source=diff, svc=frontend, n=5):
  http_req_method=GET http_req_path=/product/<sku> request error
    could not retrieve cart: rpc error: code = Unavailable...
  http_req_method=GET http_req_path=/product/<sku> request error
    could not retrieve cart: rpc error: code = FailedPrecondition
    desc = Can't access cart storage. StackExchange.Redis.RedisConnectionException
  [3 more]

metric_observations (paraphrased from top-5 |delta_*| cross-service):
  trace p95 latency +6.35s vs baseline
  -2151 spans vs baseline
  +261 new error spans vs baseline
  +223 new error log lines
  RPC OK throughput -38.5/sec

trace_summary: {count: 474, error_count: 261, error_rate: 0.355,
                p50_ms: 1, p95_ms: 6361, span_count: 736}

k8s_state: {restart_count: 9, warning_event_count: 13, pod_unavailable_count: 1}

alert_names (firing, noise-filtered, n=8):
  CPUThrottlingHigh
  KubeContainerWaiting
  KubeDeploymentReplicasMismatch
  KubePodNotReady
  OnlineBoutiqueDeploymentUnavailable
  OnlineBoutiqueNearMissResourcePressure
  KubePodCrashLooping
  OnlineBoutiqueContainerRestarting

symptom_phrase:  users seeing cart-not-loading after add-to-cart
trace_id_quoted: 10131a0aa2cd011f9268663c...
```

**3. `_strip_unsafe` re-runs `find_lab_tokens` on every string** and
silently drops any leaker. (During development this caught `pre-fault`
in our paraphrases — `fault` is a banned token — and we changed to
`vs baseline`. Defense in depth works.)

**4. Per-step LLM calls** — `slice_for_step` projects the bundle:

*Step 1: `report` (cs-agent, Mei Lin, t=0)*
- LLM input evidence: `symptom_phrase` ONLY (cs-agent has no backend
  telemetry access; per §13.12 table the report row is all 0/—)
- Expected output (~120 chars):
  > Few customers wrote in last 10min: "add to cart says try again
  > later". Looks site-wide.
- `description_code`: empty for this step (cs-agent doesn't paste logs)

*Step 2: `ack` (oncall-sre, Carlos Mendes, t=+3min)*
- LLM input evidence:
  - `symptom_phrase` (same)
  - `log_lines[:1]` → first frontend RPC error chain
  - `metric_observations[:1]` → `"trace p95 latency +6.35s vs baseline"`
  - `k8s_state` → `{restart_count: 9, warning_event_count: 13, pod_unavailable_count: 1}`
  - `alert_names[:3]` → `CPUThrottlingHigh`, `KubeContainerWaiting`, `KubeDeploymentReplicasMismatch`
- Expected output (~150 chars, pager-speak):
  > acked. CPUThrottlingHigh + KubeContainerWaiting + DeploymentReplicasMismatch
  > firing, 9 restarts / 1 pod unavailable. trace p95 +6.35s vs baseline.
  > frontend logs showing unavailable on cart fetch. looking at cartservice.
- `body_code` for this comment: the one log line, raw

*Step 3: `hypothesis` (backend-eng, Tom Fitzgerald, t=+7min)*
- LLM input evidence:
  - `log_lines[:4]` → 4 frontend RPC error chains (different `code=`
    suffixes: Unavailable, FailedPrecondition + StackExchange.Redis...)
  - `metric_observations[:3]` → p95 +6.35s, -2151 spans, +261 new
    error spans
  - `trace_summary` → full dict
  - `k8s_state` → full dict
  - `trace_id_quoted` → `10131a0aa2cd011f9268663c...`
- Expected output (~260 chars):
  > trace 10131a0a... showing 35.5% error rate with p95 6.36s — way
  > past our deadlines. frontend logs full of StackExchange.Redis.
  > RedisConnectionException + "Can't access cart storage". 9 restarts
  > / 1 pod unavailable on cartservice suggests it's not handling the
  > redis backpressure. checking redis-cart pod state.
- `body_code`: the 4 raw log line templates

*Step 4: `resolve` (fix-author, Sarah Chen, t=+45min)*
- LLM input evidence: full bundle (logs + metrics + trace_summary +
  k8s_state + 3 alerts + trace_id)
- Expected output (~120 chars):
  > redis-cart pod was at memory pressure, OOM-evicted. bumped memory
  > limit 256Mi -> 512Mi (#1234). error rate back to baseline, p95 ~5ms.
- `body_code`: null (resolution is prose, no log paste)

**5. Assembled `HumanizedTicket`** (V2 schema per §13.2):
```json
{
  "summary": "Cart loads failing — cartservice can't reach redis-cart",
  "description": "Few customers wrote in last 10min: 'add to cart says try again later'. Looks site-wide. [~150 chars total]",
  "description_code": "http_req_method=GET http_req_path=/product/<sku> request error could not retrieve cart: rpc error: code = Unavailable...\nhttp_req_method=GET http_req_path=/product/<sku> request error could not retrieve cart: rpc error: code = FailedPrecondition desc = Can't access cart storage. StackExchange.Redis.RedisConnectionException\n[3 more]",
  "comments": [
    {"persona": "oncall-sre", "body": "acked. CPUThrottlingHigh + ...", "body_code": "http_req_method=GET .../product/<sku> request error..."},
    {"persona": "backend-eng", "body": "trace 10131a0a... showing 35.5% error rate...", "body_code": "<the 4 raw lines>"},
    {"persona": "fix-author", "body": "redis-cart pod was at memory pressure...", "body_code": null}
  ],
  "resolution": "Fixed",
  "resolution_time_s": 2700,
  "is_distractor": false,
  "is_followup_of": null,
  "source_episode_id": "...-cart-redis-degradation-critical-...",
  "source_injection_id": "<from episodes.jsonl ground_truth>",
  "log_signature_source": "diff",
  "evidence_bundle_hash": "<sha256 of the canonical bundle>"
}
```

**6. Final leakage canary** on the FULL serialized text — must not
contain `cart-redis-degradation`, `synthetic`, `scenario`, `fault`,
`chaos-mesh`, or any other lab-firewall token. Pass → append to
`timeline.jsonl`. Fail → log to manifest, do NOT write the row.

#### Key invariants visible in the workflow

- The LLM sees **persona + symptom + a slice of resolved evidence per
  step**. It never sees the scenario name, the fault ID, the
  ground-truth label, the opaque IDs, or the raw `delta_*` numeric
  values — only their paraphrased engineer-voice forms.
- The same content (e.g. `RedisConnectionException`) can appear in
  both the prose `body` AND `body_code` of a comment. The two
  channels serve different downstream readers: prose for narrative
  retrieval, `body_code` for BM25 on engineer-vocabulary log content.
- A trace_id hash IS allowed in prose because the hash carries no lab
  semantics — it's just a string an engineer would realistically quote.
  The sanitizer checks the hash doesn't substring-match a lab token
  (collision risk ~zero for SHA-style hashes).
- Real alert names (`OnlineBoutiqueNearMissResourcePressure` etc.) IS
  allowed because those are production-realistic — every SaaS company
  emits app-specific alerts with arbitrary names.
- An empty `description_code` (rule 3c in §13.3) is fine — that
  represents a real ticket where the reporter has no log access and
  the on-call engineer didn't find anything distinctive in the loki
  dumps. With the multi-channel bundle, **even these tickets carry
  signal** from `metric_observations` + `alert_names` + `k8s_state`,
  so empty-log no longer means empty-evidence. Smoke test confirmed
  0/12 fully-empty bundles vs 11% empty rate with logs-only.

---

## 14. After the full V2 bulk run (2026-06-01)

The first complete V2 corpus shipped on 2026-05-31 — 347 humanized
tickets across every injected fault episode in v5-large. This section
captures what we measured, what surprised us, and what the run
exposed that the spec didn't anticipate. Source corpus:
`data/derived/global/2026-05-25-dataset-v5-large-global/jira-shadow-humanized-v2/bulk-20260531/`.

### 14.1 Run summary

| | |
| --- | --- |
| Generator version | `v2.1.0-step3-variable-thread-and-resolution` |
| Sanitizer / symptom map versions | `v1.0.0` / `v1.0.0` |
| LLM | `qwen/qwen2.5-coder-14b` via LM Studio @ `localhost:1234`, temp=0.7 |
| Hardware | Local RTX 5060 (Windows 11 Home) |
| Tickets in corpus | **347 / 347** (100% coverage) |
| Initial bulk wall time | 5h 54m 26s (336 succeeded, 11 sanitizer-rejected) |
| Resume wall time | 10m 52s (recovered all 11 with `_redact_lab_tokens` patch) |
| **Combined wall time** | **6h 5m** |
| Total LLM calls | 1,641 (1,594 bulk + 47 resume) |
| Total tokens | 1,754,389 (1,577,644 prompt + 176,745 completion) |
| Average per call | 962 prompt + 108 completion tokens, 13.3 sec wall |
| Hard errors | 0 |
| Leak rejections (after retry) | **0 / 1,641** |

### 14.2 Distribution achievement vs §13.1 TAWOS targets

The whole point of V2 was to match real-world Jira distributions
instead of V1's uniform-everything synthetic. Headline numbers:

| Dimension | §13.1 target | V2 actual | Delta |
| --- | --- | --- | --- |
| **Resolution outcome** | | | |
| `Fixed` | 60% | 62.5% (217) | +2.5% |
| `Won't Fix` | 15% | 12.7% (44) | -2.3% |
| `Duplicate` | 12% | 11.0% (38) | -1.0% |
| `Cannot Reproduce` | 4% | 5.2% (18) | +1.2% |
| `Not A Bug` | 3% | 2.0% (7) | -1.0% |
| `Timed out` | 4% | 6.6% (23) | +2.6% |
| **Comment count** | | | |
| N=1 | 39% | 41.5% (144) | +2.5% |
| N=2-5 | 43% | 38.9% (135) | -4.1% |
| N=6-12 | 14% | 16.1% (56) | +2.1% |
| N=13-15 | 4% | 3.5% (12) | -0.5% |
| **Reporter persona (§11 Q1)** | | | |
| `cs-agent` | mixed by severity | 46.7% (162) | — |
| `oncall-sre` | mixed by severity | 53.3% (185) | — |
| **Step 2 mechanics** | | | |
| Misattribution rate (§3 Rule 3) | 10-15% | 15.0% (52) | ✓ |
| Description_code populated (§13.3) | ≥80% | 90.2% (313) | ✓ |
| `closed_as_noise` (any non-Fixed) | — | 37.5% (130) | — |

Every category matches within ±4% of the §13.1 target. The largest
deltas (`Timed out` +2.6%, `N=2-5` -4.1%) are within the sampling
noise we'd expect at n=347 — fully-converged distributions would
need ~5000 tickets per §13.1's 458K-issue baseline.

### 14.3 Multi-channel evidence coverage

The §13.12 multi-channel bundle did exactly what we designed for —
empty-log tickets are no longer empty-evidence tickets because the
metric / k8s / alert channels carry signal when logs don't.

| Channel | Tickets where channel populated | Notes |
| --- | --- | --- |
| `description_code` (log lines) | 313 / 347 (90.2%) | Above the 80% §13.3 target |
| `log_signature_source = "diff"` | 255 / 347 (73.5%) | High-quality fault-distinctive lines |
| `log_signature_source = "plain_fallback"` | 58 / 347 (16.7%) | Active had templates but didn't clear diff bar |
| `log_signature_source = "empty"` | 34 / 347 (9.8%) | No characteristic logs — multi-channel rescued these |

The 34 empty-log tickets still carry `metric_observations`,
`alert_names`, `k8s_state`, and `trace_summary` from the global
triage features, so the LLM had concrete engineer-vocabulary to work
with even there.

### 14.4 The `near-miss` / `fault` problem and the redactor patch

The first bulk run sanitizer-rejected 11 tickets (3.2% rejection
rate) — every one because the LLM emitted `near-miss` (10) or
standalone `fault` (1) in its output, despite the prompt's negative
examples and the firewall's banned-token list. This is Qwen's
pretraining leaking through: it has seen tens of thousands of real
SRE postmortems that use "near-miss" as standard incident
vocabulary, and reaches for the term naturally.

Failures clustered on specific scenario families:
- `currencyservice-unavailable-*` (4 fails)
- `recommendation-model-blip-minor` (2)
- `currency-timeout-recovers` (1)
- `currency-partial-latency` (1)
- `checkoutservice-unavailable-critical` (1)
- `redis-cart-intermittent-failure-major` (1)
- `packet-loss-frontend-30pct-90s` (1)
- `recommendationservice-unavailable-major` (1)

The fix was to add a **pre-sanitizer soft redactor** (`_redact_lab_tokens`
in `timeline_generator.py`) that swaps known offenders for clean
synonyms before the firewall's hard reject runs:

```python
_PRE_SANITIZER_REPLACEMENTS = (
    ("near-miss",        "transient blip"),
    ("nearmiss",         "transient blip"),
    ("fault tolerance",  "resilience"),
    ("fault injection",  "controlled test"),
    ("fault",            "issue"),
)
```

Word-boundary matching — `default` and `faulty` are deliberately not
redacted because they're real English words, not lab vocabulary. The
sanitizer's hard reject still runs after the redactor, so any new
offender we haven't seen yet still fails loud.

**On retry with the redactor, all 11 previously-failed tickets generated
cleanly** (0 leak rejections in the 47-call resume run). The corpus
is now 100% complete.

Bias note: replacing `near-miss` with `transient blip` slightly
shifts the LLM's vocabulary surface for ~10 tickets in 347, which
is below the noise floor for any downstream BM25 / embedding model.
The alternative (leaving 11 tickets uncovered) would violate the
§13.4 1:1 coverage rule, so the trade-off is clearly worth it.

### 14.5 Resolution-time distribution: full-range sampling pays off

§13.9 #2 specified that distractor tickets should resample
`Resolution_Time_Minutes` to a 5-day-collection-realistic
distribution. We extended that decision to real V2 tickets too —
sampling the **full TAWOS empirical range** (minutes to a year)
rather than clipping to our 5-day collection window.

Realized distribution (V2 corpus, n=347):
- median: 22 days (528.5 hours)
- 75th percentile: ~3 months
- max: 363 days (12 months)

This matters because a downstream model that saw `resolution_time
< 5 days = real, > 5 days = distractor` would shortcut. Sampling the
full distribution forces the model to learn from log/metric/trace
content, not from the time field.

### 14.6 LLM usage stats for the research writeup

Captured per-run in `generation-manifest.json["llm_usage"]`:

```json
{
  "n_calls": 1641,
  "prompt_tokens": 1577644,
  "completion_tokens": 176745,
  "total_tokens": 1754389,
  "n_errors": 0,
  "n_leak_rejections": 11,
  "wall_time_s": 21742.31,
  "avg_prompt_tokens_per_call": 961.4,
  "avg_completion_tokens_per_call": 107.7,
  "avg_wall_time_per_call_s": 13.249
}
```

Translation for paper:
- **Average prompt size 961 tokens** — the multi-channel evidence
  block (alerts + metrics + trace + k8s + logs) plus the persona
  system message plus the prior-thread context. This is the cost of
  the §13.12 multi-channel design.
- **Average completion 108 tokens** — engineer-realistic comment
  length (TAWOS median 200-500 chars ≈ 50-130 tokens).
- **0 hard errors across 1,641 calls** — the LM Studio + Qwen
  combination was rock-solid; the only failures were soft
  sanitizer-policy rejections.
- **6 hours wall time on local RTX 5060** — sets the cost baseline.
  Claude Haiku equivalent would be ~$0.50 in API charges.

### 14.7 Voice quality — wins and remaining artefacts

Three voice problems V1 had, addressed by V2:

| V1 problem | V2 fix | Result |
| --- | --- | --- |
| `### Summary` / `Description:` field labels | Negative examples in `_OUTPUT_FORMAT_RULES` | Most tickets clean; a few still leak labels |
| "Hi team," / "Thanks, [Your Name]" sign-offs | Negative examples + lowered max_tokens | ~80% clean; some hypothesis steps still greet |
| Verbose multi-paragraph hypothesis (1500-3000 chars) | Per-persona token caps + character cap in prompt | Hypothesis now 600-900 chars (target ≤1000) |

The remaining markdown labels and greetings are tractable with a
regex post-pass (`re.sub(r'^(\*\*?)?(Summary|Description)\*?\*?:\s*\n*', '', text)`
and similar for greetings/sign-offs). User opted to handle these
with regex rather than tighten the prompt further, which is the right
trade — Qwen ignores increasingly-strict negative instructions past
a certain point.

The biggest win is the **opening voice** on high-severity tickets.
V1's reports always started with cs-agent style ("Customer reports
slow site performance"). V2's severity-weighted reporter persona
flips 70% of `high`-severity tickets to oncall-sre pager-speak, e.g.:

> *checkout failing at payment step; CPUThrottlingHigh &
> OnlineBoutiqueNearMissResourcePressure alerts firing; +861 spans
> vs baseline; restart_count=2, warning_event_count=3*

That's a TAWOS-realistic engineer-voice opening, with real alert
names and metric deltas referenced naturally. No "Summary:", no
"Hi team", no markdown — exactly what the §13.8 step 2 voice
rewrite was supposed to produce.

### 14.8 Surprises and lessons for the future

1. **Multi-channel evidence carried more weight than expected.** §13.12's
   `metric_observations` + `alert_names` channels are referenced in
   ~95% of ack and hypothesis steps. The LLM weaves them into prose
   without prompting — "CPU throttling high alerts firing, +6.35s
   p95 latency vs baseline" reads better than the equivalent prose
   would have been from logs alone.

2. **The persona-step access pattern (`slice_for_step`) just worked.**
   cs-agent reports stayed customer-paste (no engineer jargon),
   oncall-sre acks stayed pager-speak. The §13.12 access table didn't
   need any per-fault-family tuning.

3. **Variable comment count revealed an unexpected shape.** N=1
   tickets (41.5% of corpus) read as legitimately filed-and-closed —
   "Customer reported issue, no telemetry available, monitoring,
   closing." That's a real shape in production Jira queues and
   represents valid training data for the "filed in haste, closed
   without action" pattern.

4. **The redactor is a load-bearing soft-firewall layer.** Without it,
   the sanitizer's hard reject would have left 3.2% of tickets
   missing — violating §13.4 coverage. The redactor is now the only
   reason we hit 100% coverage. Future LLM swaps will need to be
   tested against the same vocabulary-leak patterns; if a new model
   reaches for different SRE jargon, the `_PRE_SANITIZER_REPLACEMENTS`
   table grows.

5. **`Timed out` resolutions came in 2.6% high.** Qwen + the random
   sampler conspired here; nothing inherently broken, but worth
   noting if a future tuning pass wants tighter distribution match.

### 14.9 What's still pending in §13.8

V2 corpus is shippable as-is for **internal benchmarking** and for the
forthcoming retrieval evaluation. The remaining work for the full V2
research story:

- **Step 4 — Coverage assertion.** Formal manifest-level check that
  every injection_id in `episodes.jsonl` has at least one ticket in
  the timeline. In practice we hit 347/347 on this run; we just
  need the build-time assert wired in.
- **Step 5 — Distractor generation.** ~25% of the final corpus
  should be distractor tickets (TAWOS-sampled, cross-arch, in-arch-
  never-happened) per §13.5. Not built yet.
- **Step 6 — Retrieval benchmark E8.** Train memorygraph on V2,
  compare top-1 / top-3 retrieval against the V1 corpus and the E7
  ceiling. The hypothesis is that the `description_code` engineer-
  vocabulary channel lifts BM25 past where V1's cs-voice plateau'd.

### 14.10 Provenance

Every ticket in this run carries:
- `source_episode_id` and `source_injection_id` for traceability
  back to `episodes.jsonl`
- `log_signature_source` (`diff` / `plain_fallback` / `empty`) so
  downstream readers know how the description_code was derived
- `evidence_bundle_hash` (sha256[:16] of the canonical
  EvidenceBundle) for exact-reproduction debugging
- `generator_version` / `sanitizer_version` / `symptom_map_version`

To re-derive any single ticket: read the corresponding
`jira_shadow_issues.jsonl` row + the per-run raw artifacts + the
`global-triage-examples.jsonl` row, run them through
`generate_full_timeline` with the same generator version. Modulo
LLM nondeterminism (~10% lexical variance at temperature=0.7), the
ticket will reproduce.
