"""extract_entities_llm — indexing-time LLM extractor.

Closes RQ-A6. The OB cascade had **asymmetric extraction**: LLM
entities on the memory side (jira tickets) but rule-based extraction
on the window side. This let kg_retrieval / hybrid-LLM-graph match
on generic phrases like "Unavailable" instead of specific ones like
"RedisConnectionException", so retrieval underperformed on real WoL
windows.

This skill runs LLM extraction on the **window** side too. After it's
been run over a dataset's test split, the window-side and memory-side
extractions are symmetric and KG retrieval gets a fair shot.

Two important properties:
  - **Indexing-time, not invocation-time.** The skill is registered
    for completeness, but the v1 RuleController does NOT include it
    in the per-window plan. It's invoked by a separate CLI
    (`scripts/agent/extract_window_entities.py`) over the entire
    test split. Doing it per-bundle at evaluation time would re-run
    the extractor on every ablation pass.
  - **Produces the KG_GRAPH_WINDOW capability flag** at the dataset
    level (not per-bundle). When the resulting JSONL exists, the
    smoke + ablation scripts set `has_kg_graph_window=True` on the
    ObservationContext; the capabilities observer then surfaces the
    flag and KG-aware retrievers gain a usable window-side signal.

The skill itself is thin — it just adapts the `LLMProvider` interface
(or directly invokes a cached extractor) to the agent's Skill ABC. The
real work lives in `v2_advanced/proposal_d_knowledge_graph/extractor.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..capabilities import TEXT_EVIDENCE
from ..types import InputBundle, SkillOutput
from .base import AgentContext, MemoryView, Skill, make_cost


log = logging.getLogger(__name__)


# Field names the skill surfaces in SkillOutput.extra — must match the
# WindowExtraction dataclass in v2_advanced.proposal_d_knowledge_graph.
_EXTRACTION_FIELDS = (
    "affected_services",
    "components",
    "error_classes",
    "symptoms",
)


class ExtractEntitiesLLMSkill(Skill):
    """LLM-backed entity extractor — used at indexing time.

    Construction:
        extractor_fn: callable(window_id, evidence_text, ...) ->
            object with `affected_services`, `components`,
            `error_classes`, `symptoms` attributes. Defaults to
            `extract_from_window` from
            `v2_advanced.proposal_d_knowledge_graph.extractor` when
            available; otherwise a callable must be supplied.
        cache_dir: optional Path the extractor uses to checkpoint
            per-window results so re-runs are cheap.
        use_llm: when False, returns empty extractions (used for tests
            + dry-runs without LM Studio).
    """

    name = "extract_entities_llm"
    version = "1.0.0"
    required_flags = frozenset({TEXT_EVIDENCE})
    cost_class = "expensive_llm"

    def __init__(
        self,
        *,
        extractor_fn=None,
        cache_dir: Path | str | None = None,
        use_llm: bool = True,
        skill_version: str | None = None,
    ) -> None:
        self.extractor_fn = extractor_fn or _default_extractor_fn()
        self.cache_dir = Path(cache_dir) if cache_dir else None
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
        text = bundle.text_evidence or ""
        if not text or not self.use_llm:
            return self._empty_output(reason="no_text_or_stub_mode")

        client = ctx.llm
        if client is None and self.extractor_fn is _default_extractor_fn():
            # The default extractor wants an LMStudioClient via ctx.llm.
            # Caller didn't wire one — return an empty result rather
            # than raise (consistent with the skill's "indexing tool"
            # role; per-bundle invocation is unusual).
            return self._empty_output(reason="no_llm_client_in_ctx")

        try:
            extraction = self.extractor_fn(
                client=client,
                window_id=bundle.window_id,
                evidence_text=text,
                severity=bundle.window_type or "",
                family=bundle.scenario_family or "",
                cache_dir=self.cache_dir,
            )
        except Exception as e:                                       # noqa: BLE001
            log.warning("extract_entities_llm failed for %s: %s",
                        bundle.window_id, e)
            return self._empty_output(reason=f"extractor_exception:{type(e).__name__}")

        # Translate the extractor's dataclass into the SkillOutput shape
        extra = {}
        for field in _EXTRACTION_FIELDS:
            extra[field] = list(getattr(extraction, field, ()) or ())
        n_entities = sum(len(extra[f]) for f in _EXTRACTION_FIELDS)
        confidence = 1.0 if n_entities > 0 else 0.0

        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            triage_score=None,
            triage_decision=None,
            matched_issue_ids=(),
            is_novel=None,
            confidence=confidence,
            evidence_used=("TEXT_EVIDENCE",),
            cost=make_cost(n_calls=1),
            extra={
                **extra,
                "n_entities": n_entities,
                "window_id": bundle.window_id,
            },
        )

    # ------------------------------------------------------------------ empty

    def _empty_output(self, *, reason: str) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            confidence=0.0,
            evidence_used=("TEXT_EVIDENCE",),
            cost=make_cost(n_calls=0),
            extra={
                **{f: [] for f in _EXTRACTION_FIELDS},
                "n_entities": 0,
                "noop": True,
                "reason": reason,
            },
        )


# ---------------------------------------------------------------------------
# Default extractor — lazily imported so the agent package doesn't pull
# the v2_advanced dependency tree unless this skill is used.
# ---------------------------------------------------------------------------


_default_fn_cache = None


def _default_extractor_fn():
    global _default_fn_cache
    if _default_fn_cache is None:
        try:
            from v2_advanced.proposal_d_knowledge_graph.extractor import (
                extract_from_window,
            )
            _default_fn_cache = extract_from_window
        except ImportError:
            # The v2_advanced layer isn't on the path — skill will need
            # an explicit extractor_fn or it falls back to empty output.
            _default_fn_cache = _no_extractor_available
    return _default_fn_cache


def _no_extractor_available(**kwargs) -> Any:
    """Stub used when v2_advanced isn't importable. Surfaces a clear
    error if anyone tries to actually invoke it (rather than the bare
    skill)."""
    raise ImportError(
        "v2_advanced.proposal_d_knowledge_graph.extractor.extract_from_window "
        "is not available. Either install the v2_advanced layer or pass "
        "an explicit `extractor_fn` to ExtractEntitiesLLMSkill.",
    )
