"""Persona catalog + deterministic avatar assignment.

See LLM-Jira-enhancement.md §4 for the persona table. Each persona
carries:
  - role: stable identifier ("oncall-sre", "cs-agent", …)
  - tenure_years: shapes vocabulary (juniors over-explain, seniors hedge)
  - style_descriptor: one-line voice guide injected into LLM prompt
  - terseness: short/medium/long target length
  - vocabulary_hints: positive + negative example words

Avatar assignment is **deterministic from the ticket's source_episode_id
+ role** so the same role on the same ticket always picks the same
avatar across re-runs — and different roles on the same ticket get
different avatars (no Sarah Chen playing two roles in one timeline).
"""

from __future__ import annotations

from dataclasses import dataclass

# Reuse the existing name pool from rewrite.py so the humanized corpus
# and the legacy generator draw from the same set of fictional people.
from .rewrite import _NAMES, _pick


@dataclass(frozen=True)
class Persona:
    role: str
    tenure_years: float
    style_descriptor: str
    terseness: str               # "very-short" | "short" | "medium" | "long"
    vocabulary_likes: tuple[str, ...]
    vocabulary_avoids: tuple[str, ...]


# Catalog matching LLM-Jira-enhancement.md §4. Order is meaningful for
# the planner: roles toward the top of the list are preferred for early
# timeline steps (`report`, `ack`), later roles for `redirect`/`resolve`.
PERSONA_CATALOG: dict[str, Persona] = {
    "cs-agent": Persona(
        role="cs-agent",
        tenure_years=1.0,
        style_descriptor=(
            "Customer support agent forwarding what a customer just told you. "
            "Non-technical, paste the customer's words. May include the "
            "customer's order id or session id if you have it. End with one "
            "sentence asking the eng team to look."
        ),
        terseness="short",
        vocabulary_likes=("customer says", "fwd from support", "ticket #",
                          "complaining", "experiencing"),
        vocabulary_avoids=("p95", "trace_id", "deployment", "k8s",
                           "OTel", "interceptor"),
    ),
    "oncall-sre": Persona(
        role="oncall-sre",
        tenure_years=4.0,
        style_descriptor=(
            "On-call SRE acknowledging an automated page. Pager-speak: "
            "abbreviations, lowercase, no greetings. State what you see, "
            "what's next. Two to three short lines max."
        ),
        terseness="very-short",
        vocabulary_likes=("paged", "ack", "looking", "p95", "err rate",
                          "checking"),
        vocabulary_avoids=("Hello", "Hi team", "I hope", "Please"),
    ),
    "junior-eng": Persona(
        role="junior-eng",
        tenure_years=0.5,
        style_descriptor=(
            "Recently-hired backend engineer. Over-explain what you observed, "
            "ask basic clarifying questions, copy-paste log lines liberally. "
            "Tend to suspect the obvious thing first. Polite, with greetings."
        ),
        terseness="long",
        vocabulary_likes=("hi team", "I see in the logs", "is this related to",
                          "should we", "I noticed"),
        vocabulary_avoids=("obviously", "trivial"),
    ),
    "frontend-eng": Persona(
        role="frontend-eng",
        tenure_years=3.0,
        style_descriptor=(
            "Owns the user-facing layer. Frame issues from the user-visible "
            "side first. Reference frontend metrics or recent deploys. "
            "Initially suspect 'is this on us' before redirecting downstream."
        ),
        terseness="medium",
        vocabulary_likes=("frontend", "client-side", "checkout flow",
                          "last release", "user-visible"),
        vocabulary_avoids=("kernel", "node-level"),
    ),
    "backend-eng": Persona(
        role="backend-eng",
        tenure_years=3.0,
        style_descriptor=(
            "Owns the service the symptom appears on. Technical, references "
            "specific code paths or recent PRs, knows the service's idioms. "
            "Speaks in terms of handlers, queues, retries."
        ),
        terseness="medium",
        vocabulary_likes=("handler", "retry", "circuit breaker", "since the "
                          "PR last week", "context cancelled"),
        vocabulary_avoids=("idk", "lol"),
    ),
    "senior-sre": Persona(
        role="senior-sre",
        tenure_years=8.0,
        style_descriptor=(
            "Senior SRE who's seen this before. Hedges everything. Asks for "
            "specific evidence rather than asserting. When redirecting, does "
            "so politely with a reason. Doesn't pile on; aims for the next "
            "useful action."
        ),
        terseness="medium",
        vocabulary_likes=("could be", "have we checked", "looks more like",
                          "let's pull", "before we", "the call chain"),
        vocabulary_avoids=("definitely", "for sure"),
    ),
    "eng-mgr": Persona(
        role="eng-mgr",
        tenure_years=6.0,
        style_descriptor=(
            "Engineering manager checking status. No technical content, "
            "just asks for an ETA or whether customer-impact is contained. "
            "One line."
        ),
        terseness="very-short",
        vocabulary_likes=("any update", "ETA", "customer impact",
                          "do we need to comms", "rollback?"),
        vocabulary_avoids=("trace", "p95", "deployment manifest"),
    ),
    "db-team": Persona(
        role="db-team",
        tenure_years=5.0,
        style_descriptor=(
            "Database/cache infra team. Surfaces only when the issue touches "
            "Redis, Postgres, or similar. Polite but firm: 'we see normal X "
            "on our side, suggest checking app-side timeouts'."
        ),
        terseness="short",
        vocabulary_likes=("from our side", "no anomalies in", "suggest "
                          "checking", "client config", "connection pool"),
        vocabulary_avoids=("oops", "sorry"),
    ),
    "fix-author": Persona(
        role="fix-author",
        tenure_years=4.0,
        style_descriptor=(
            "Person who shipped the fix. Resolution-focused, terse close "
            "note. State what you did, link a PR or runbook, mark resolved. "
            "May say 'self-resolved, monitoring' if no clear root cause."
        ),
        terseness="short",
        vocabulary_likes=("pushed a fix in", "deployed", "watching", "closing",
                          "if it recurs, reopen", "self-resolved"),
        vocabulary_avoids=("we definitely fixed", "guaranteed"),
    ),
}


def avatar_for(persona_role: str, episode_id: str, salt: str = "") -> str:
    """Deterministic avatar pick: same `(role, episode_id)` always returns
    the same name across re-runs.

    `salt` lets a single ticket have a unique avatar per timeline step
    even when the persona role repeats (e.g. two hypothesis steps both
    by `backend-eng` shouldn't be the same person).
    """
    seed = f"{persona_role}::{episode_id}::{salt}"
    return _pick(seed, _NAMES)


def persona_for(role: str) -> Persona:
    if role not in PERSONA_CATALOG:
        raise KeyError(
            f"Unknown persona role {role!r}. Available: "
            f"{sorted(PERSONA_CATALOG)}"
        )
    return PERSONA_CATALOG[role]


# Mapping from timeline step kind to the preferred persona for that step.
# `report` and `ack` are weighted picks (different fault severities draw
# different reporters); for now we keep the deterministic default and
# let Phase 3 introduce the weighted-by-severity logic.
DEFAULT_PERSONA_FOR_STEP: dict[str, str] = {
    "report": "cs-agent",       # placeholder; Phase 3 randomizes 60/40 cs-agent/oncall-sre by severity
    "ack": "oncall-sre",
    "hypothesis": "backend-eng",
    "redirect": "senior-sre",
    "nudge": "eng-mgr",
    "resolve": "fix-author",
}
