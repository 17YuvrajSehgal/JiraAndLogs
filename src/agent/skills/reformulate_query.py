"""reformulate_query — bounded-action query reformulator.

Closes `XX_AGENTIC_IDEA.md` §4.2. When the cheap retrieval path fails
consensus (no top-K overlap between voters AND max retriever confidence
< 0.5), the agent emits a *reformulated* query and the controller can
re-run retrieval with it.

Bounded action space (per spec, §5.1 row):

  - `drop_token`         — remove a token from the query that's
                           absent from every retrieved candidate.
  - `add_service`        — add a service name the bundle carries
                           (`bundle.service_name` or one from
                           `service_vocabulary`) that wasn't already
                           in the query.
  - `substitute_synonym` — swap a token for its mapping in a
                           controlled synonym dictionary.

No free-form generation. The LLM picks from this action set via a
strict JSON schema (Phase 1.2's `chat_json(schema=...)` enforces it).

For v1 the predictions-backed retrievers don't actually re-query on the
reformulated text (they look up by window_id), so the loop's value is
mostly an instrumentation hook: a populated `extra["reformulated_query"]`
in the trace marks "this is where the agent would re-retrieve". v2's
live-retrieval mode will close the loop fully.

A stub mode (`use_llm=False`) produces deterministic reformulations
without an LLM call — used for tests and dry-run smokes.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..capabilities import TEXT_EVIDENCE
from ..types import InputBundle, SkillOutput
from .base import AgentContext, MemoryView, Skill, make_cost


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action schema — what the LLM must return
# ---------------------------------------------------------------------------


REFORMULATION_ACTIONS = ("drop_token", "add_service", "substitute_synonym")


_REFORMULATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": list(REFORMULATION_ACTIONS),
        },
        "argument": {
            "type": "string",
            "description": (
                "drop_token: token to remove; add_service: service name "
                "to insert; substitute_synonym: token to replace (paired "
                "with `replacement`)."
            ),
        },
        "replacement": {
            "type": "string",
            "description": "Only set when action='substitute_synonym'.",
        },
        "reason": {
            "type": "string",
            "description": "Brief explanation; surfaced in the trace.",
        },
    },
    "required": ["action", "argument", "reason"],
}


_SYSTEM_PROMPT = """\
You reformulate a failed retrieval query by picking ONE bounded action.

Action vocabulary (do not invent new actions):
  - drop_token       — remove ONE token from the query that's absent
                       from every retrieved candidate. Use when a
                       generic word (the, error, failed) is dominating
                       the dense embedding.
  - add_service      — ADD a service name from the bundle's metadata
                       that wasn't already in the query.
  - substitute_synonym — replace ONE token with a closer synonym.

Constraints:
  - One action per call.
  - `argument` is the exact token / service name (not a sentence).
  - For substitute_synonym, also supply `replacement`.

Goal: surface gold tickets the first query missed because of
embedding-space drift. Stay conservative — small edits.
"""


# ---------------------------------------------------------------------------
# ReformulateQuerySkill
# ---------------------------------------------------------------------------


class ReformulateQuerySkill(Skill):
    """Bounded-action query reformulator.

    Construction:
        controlled_synonyms: optional dict mapping token → list of
            allowed substitutions. Filters substitute_synonym actions
            so the LLM can't invent replacements.
        service_vocabulary: tuple of known service names. Filters
            add_service actions.
        max_reformulations_per_window: ctx-extra-tracked cap.
        use_llm: when False, skill operates in deterministic-stub
            mode (returns a fixed action chosen by a hash of the
            query). Useful for tests + no-LLM smokes.

    Invocation reads `ctx.extra["retry_count"]` (default 0) and stamps
    the new count into the output's `extra["retry_count"] = old + 1`.
    The controller bumps retry_count for the next pass."""

    name = "reformulate_query"
    version = "1.0.0"
    required_flags = frozenset({TEXT_EVIDENCE})
    cost_class = "expensive_llm"

    def __init__(
        self,
        *,
        controlled_synonyms: dict[str, list[str]] | None = None,
        service_vocabulary: tuple[str, ...] | None = None,
        max_reformulations_per_window: int = 2,
        use_llm: bool = True,
        skill_version: str | None = None,
    ) -> None:
        self.controlled_synonyms = controlled_synonyms or {}
        self.service_vocabulary = service_vocabulary or ()
        self.max_reformulations_per_window = max_reformulations_per_window
        self.use_llm = use_llm
        if skill_version is not None:
            self.version = skill_version

    # ------------------------------------------------------------------ invoke

    def invoke(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        ctx: AgentContext,
    ) -> SkillOutput:
        retry_count = int(ctx.extra.get("retry_count", 0))
        if retry_count >= self.max_reformulations_per_window:
            # Cap reached — emit a no-op output so the trace records
            # the reason. The controller's gate should also catch this,
            # but defense in depth.
            return self._noop_output(
                bundle.text_evidence or "",
                reason="max_reformulations_reached",
                retry_count=retry_count,
                cost=make_cost(),
            )

        query = bundle.text_evidence or ""
        if not query:
            return self._noop_output(
                "", reason="empty_text_evidence",
                retry_count=retry_count, cost=make_cost(),
            )

        previous_matches = self._collect_previous_matches(ctx)
        candidate_services = self._candidate_services(bundle)

        # Pick an action: LLM or deterministic stub.
        if self.use_llm and ctx.llm is not None:
            action, cost = self._llm_pick_action(
                query=query,
                previous_matches=previous_matches,
                candidate_services=candidate_services,
                bundle=bundle, ctx=ctx,
            )
        else:
            action = self._stub_pick_action(query, candidate_services)
            cost = make_cost(wall_seconds=0.0001)

        # Validate against our vocab; reject invalid argument values.
        action = self._validate_action(action, query, candidate_services)
        reformulated = self._apply_action(query, action)

        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            triage_score=None,
            triage_decision=None,
            matched_issue_ids=(),
            is_novel=None,
            confidence=1.0 if reformulated != query else 0.0,
            evidence_used=("TEXT_EVIDENCE",),
            cost=cost,
            extra={
                "reformulated_query": reformulated,
                "original_query": query,
                "action_applied": action,
                "retry_count": retry_count + 1,
                "n_previous_matches": len(previous_matches),
            },
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _collect_previous_matches(ctx: AgentContext) -> list[str]:
        """All matched_issue_ids from retrievers that ran so far."""
        trace = ctx.extra.get("trace")
        if trace is None:
            return []
        seen: list[str] = []
        for r in ("retrieve_dense", "retrieve_hybrid_fusion",
                  "retrieve_log_sequence", "retrieve_knowledge_graph"):
            out = trace.latest_output(r)
            if out is None:
                continue
            for c in out.matched_issue_ids:
                if c not in seen:
                    seen.append(c)
        return seen

    def _candidate_services(self, bundle: InputBundle) -> list[str]:
        """Service names the agent could `add_service`."""
        candidates: list[str] = list(self.service_vocabulary)
        if bundle.service_name and bundle.service_name not in candidates:
            candidates.insert(0, bundle.service_name)
        return candidates

    def _llm_pick_action(
        self,
        *,
        query: str,
        previous_matches: list[str],
        candidate_services: list[str],
        bundle: InputBundle,
        ctx: AgentContext,
    ) -> tuple[dict[str, Any], Any]:
        """Call the LLM with the constrained schema. Returns (action, cost)."""
        user_msg = (
            f"Original query (text_evidence):\n{query[:1500]}\n\n"
            f"Previous retrieval pulled (none of these helped):\n"
            f"{', '.join(previous_matches[:10]) if previous_matches else '(none)'}\n\n"
            f"Candidate service names you may `add_service`:\n"
            f"{', '.join(candidate_services) if candidate_services else '(none)'}\n\n"
            f"Controlled synonym pairs you may `substitute_synonym`:\n"
            f"{self._format_synonyms()}\n\n"
            f"Pick ONE action."
        )
        start = time.monotonic()
        try:
            resp = ctx.llm.chat_json(
                system=_SYSTEM_PROMPT,
                user=user_msg,
                schema=_REFORMULATION_SCHEMA,
                temperature=0.0,
                max_tokens=256,
                experiment=ctx.experiment,
                phase="reformulate",
                skill=self.name,
                bundle_id=ctx.bundle_id,
            )
        except Exception as e:                                       # noqa: BLE001
            log.warning("reformulate_query LLM call failed: %s", e)
            # Fall back to a stub action; record the LLM failure in cost.
            wall = time.monotonic() - start
            return (
                self._stub_pick_action(query, candidate_services),
                make_cost(wall_seconds=wall, n_calls=1),
            )

        wall = time.monotonic() - start
        action = resp.content if isinstance(resp.content, dict) else {}
        cost = make_cost(
            llm_tokens=resp.total_tokens,
            wall_seconds=wall,
            n_calls=1,
        )
        return action, cost

    def _format_synonyms(self) -> str:
        if not self.controlled_synonyms:
            return "(no controlled synonyms configured)"
        lines = []
        for k, vs in self.controlled_synonyms.items():
            lines.append(f"  {k} -> {', '.join(vs)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ deterministic stub

    @staticmethod
    def _stub_pick_action(
        query: str,
        candidate_services: list[str],
    ) -> dict[str, Any]:
        """Pick a deterministic action based on the query's content.

        Used in tests + no-LLM smokes. Strategy:
          - If the query has a candidate service NOT in it → add_service.
          - Else if the query has a "noisy" common token → drop_token.
          - Else no-op (the validator turns this into a noop)."""
        for svc in candidate_services:
            if svc and svc.lower() not in query.lower():
                return {
                    "action": "add_service",
                    "argument": svc,
                    "reason": "stub_add_missing_service",
                }
        for noisy in ("error", "failed", "the", "exception"):
            if noisy in query.lower():
                return {
                    "action": "drop_token",
                    "argument": noisy,
                    "reason": "stub_drop_generic_token",
                }
        return {
            "action": "drop_token",
            "argument": "",                          # validator → noop
            "reason": "stub_noop",
        }

    # ------------------------------------------------------------------ validation + application

    def _validate_action(
        self,
        action: dict[str, Any],
        query: str,
        candidate_services: list[str],
    ) -> dict[str, Any]:
        """Filter the LLM's action through our bounded vocabulary.

        Invalid actions degrade to a no-op (empty argument)."""
        kind = action.get("action", "")
        argument = str(action.get("argument", ""))

        if kind not in REFORMULATION_ACTIONS:
            return {**action, "action": "drop_token", "argument": "",
                    "reason": "invalid_action_kind"}

        if kind == "add_service":
            if not argument or argument not in candidate_services:
                return {**action, "argument": "",
                        "reason": "service_not_in_vocabulary"}
        elif kind == "substitute_synonym":
            replacement = str(action.get("replacement", ""))
            allowed = self.controlled_synonyms.get(argument, [])
            if replacement not in allowed:
                return {**action, "argument": "",
                        "reason": "synonym_not_in_controlled_vocab"}
            action = {**action, "replacement": replacement}
        elif kind == "drop_token":
            # drop_token only makes sense if the token is actually in the query
            if argument and argument.lower() not in query.lower():
                return {**action, "argument": "",
                        "reason": "drop_token_not_in_query"}
        return action

    @staticmethod
    def _apply_action(query: str, action: dict[str, Any]) -> str:
        """Apply the validated action to the query string."""
        kind = action.get("action")
        arg = str(action.get("argument", ""))
        if not arg:
            return query                              # no-op
        if kind == "drop_token":
            # Case-insensitive single-token removal
            tokens = query.split()
            kept = [t for t in tokens if t.lower().strip(",.;:") != arg.lower()]
            return " ".join(kept)
        if kind == "add_service":
            return f"{query} {arg}".strip()
        if kind == "substitute_synonym":
            replacement = str(action.get("replacement", ""))
            if not replacement:
                return query
            # Case-insensitive single-word substitution
            tokens = query.split()
            out = []
            for t in tokens:
                bare = t.strip(",.;:").lower()
                if bare == arg.lower():
                    out.append(replacement)
                else:
                    out.append(t)
            return " ".join(out)
        return query

    # ------------------------------------------------------------------ no-op output

    def _noop_output(
        self,
        query: str,
        *,
        reason: str,
        retry_count: int,
        cost: Any,
    ) -> SkillOutput:
        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            confidence=0.0,
            cost=cost,
            extra={
                "reformulated_query": query,
                "original_query": query,
                "action_applied": {"action": "drop_token", "argument": "",
                                   "reason": reason},
                "retry_count": retry_count,
                "noop": True,
            },
        )

    # ------------------------------------------------------------------ cache key

    def cache_key(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        *,
        extra_inputs: dict[str, Any] | None = None,
    ) -> str:
        """Cache key mixes in retry_count so retry-1 and retry-2 produce
        distinct cache entries (otherwise we'd hit the first reformulation
        every time)."""
        extra = dict(extra_inputs or {})
        # The controller passes retry_count via SkillInvocation.inputs;
        # if absent fall back to 0 so the v1 single-call path still keys.
        extra.setdefault("retry_count", 0)
        return super().cache_key(bundle, memory, extra_inputs=extra)
