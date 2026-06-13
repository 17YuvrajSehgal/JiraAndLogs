"""AgentRunner — executes a Plan, populates a Trace, emits an AgentDecision.

The runner is *single-implementation*: behaviour is driven entirely by
the Plan the Controller emits, not by anything hardcoded here. Adding
new orchestration policies happens in a new Controller, not here.

Per-invocation lifecycle::

    for invocation in plan.invocations:
        if gate(trace, budget) is False:          # cheap-path-confident skip
            emit skill_skipped_by_gate; continue

        if cache hit:
            emit cache_hit + skill_end (cached output); continue

        if budget is exhausted:
            emit budget_exceeded; abort

        emit skill_start
        try:
            output = skill.invoke(bundle, memory, ctx)
        except Exception:
            emit skill_failed; consult on_failure policy

        emit skill_end (with output + duration + budget snapshot)
        cache.put(...)
        budget.deduct(output.cost)

After all invocations, the runner reads the trace's compose_* outputs
to derive an AgentDecision. WoL bundles get evaluation_mode
"text_retrieval_generalisation"; everything else gets
"telemetry_diagnosis" (enforces the apples-to-apples eval split from
IMPROVEMENTS §4).

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §3 (architecture L3), §6.4 (replay),
      §5.2 (skill failure handling).
"""

from __future__ import annotations

import dataclasses
import logging
import time
from pathlib import Path
from typing import Any

from ..budget import Budget, BudgetExhausted
from ..plan import Plan, SkillInvocation
from ..skills.base import AgentContext, MemoryView, Skill
from ..skills.cache import NullSkillCache, SkillCache
from ..skills.registry import SkillRegistry
from ..trace import Trace, TraceEvent
from ..types import (
    AgentDecision,
    EvaluationMode,
    InputBundle,
    SkillCallCost,
    SkillOutput,
    TriageDecision,
)
from .base import RunnerError


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants used to derive the AgentDecision from trace outputs
# ---------------------------------------------------------------------------

#: Datasets that evaluate as text-retrieval-generalisation. Everything
#: else is telemetry_diagnosis. Per IMPROVEMENTS §4 the eval harness
#: refuses cross-mode comparison rows.
TEXT_ONLY_DATASETS: frozenset[str] = frozenset({"wol", "world_of_logs"})

#: Composition skill names — read by `_build_decision` to assemble the
#: final AgentDecision shape.
_COMPOSE_TRIAGE = "compose_triage"
_COMPOSE_L2 = "compose_l2"
_COMPOSE_NOVELTY = "compose_novelty"
_RETRIEVE_DENSE = "retrieve_dense"


# ---------------------------------------------------------------------------
# AgentRunner
# ---------------------------------------------------------------------------


class AgentRunner:
    """The single Plan executor.

    Construction wires the runner to a SkillRegistry, an optional
    SkillCache (NullSkillCache when omitted), and optional external
    handles (LLM provider, Neo4j driver). The runner is stateless across
    `run()` calls — each call gets its own Budget tracker and Trace.

    Args:
        registry: SkillRegistry the controller targeted. Plans reference
            skills by name; the runner resolves names → instances here.
        cache: SkillCache. If None, a NullSkillCache is used (every
            invocation hits the skill, nothing is persisted).
        trace_root: directory to persist Traces to. If None, traces are
            kept in-memory only.
        experiment: experiment tag (threaded into AgentContext + cache
            and used as a trace subdirectory).
        llm: optional LLMProvider — passed through into AgentContext so
            LLM-backed skills can call it. The runner doesn't introspect
            it beyond a health-check at startup.
        neo4j: optional Neo4j driver — passed through similarly.
        health_check: if True (default) and `llm` exposes
            `is_available()`, the constructor checks it and raises
            RunnerError if the provider isn't reachable. This catches
            "12-hour run dies on call 1" upfront.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        cache: SkillCache | None = None,
        trace_root: Path | str | None = None,
        experiment: str = "",
        llm: Any | None = None,
        neo4j: Any | None = None,
        health_check: bool = True,
    ) -> None:
        if registry is None:
            raise RunnerError("AgentRunner requires a SkillRegistry (got None).")
        self.registry = registry
        self.cache = cache if cache is not None else NullSkillCache()
        self.trace_root = Path(trace_root) if trace_root else None
        self.experiment = experiment
        self.llm = llm
        self.neo4j = neo4j

        if health_check and llm is not None:
            self._health_check_llm(llm)

    # ------------------------------------------------------------------ health

    @staticmethod
    def _health_check_llm(llm: Any) -> None:
        """If the provider exposes `is_available()`, call it and refuse
        to start when unreachable. Quietly accepts providers that don't
        have the method (test stubs, custom adapters)."""
        check = getattr(llm, "is_available", None)
        if not callable(check):
            return
        try:
            health = check()
        except Exception as e:                                       # noqa: BLE001
            raise RunnerError(
                f"LLM provider health check raised: {type(e).__name__}: {e}",
            ) from e
        ok = getattr(health, "ok", None)
        if ok is False:
            message = getattr(health, "message", "<no message>")
            raise RunnerError(f"LLM provider unreachable: {message}")

    # ------------------------------------------------------------------ run

    def run(
        self,
        plan: Plan,
        bundle: InputBundle,
        memory: MemoryView,
        *,
        ablation: str = "",
        seed: int = 42,
        evaluation_mode: EvaluationMode | None = None,
        extra_ctx: dict[str, Any] | None = None,
        persist_trace: bool = True,
    ) -> AgentDecision:
        """Execute `plan` for one bundle. Returns the final AgentDecision.

        Always succeeds (in the sense of returning a decision) — skill
        failures are recorded in the Trace and degraded gracefully into
        the final decision. The only cases that raise are programmer
        errors (e.g. plan references a non-existent skill name AND the
        controller didn't pre-prune it; that's a registry-controller
        mismatch).

        Args:
            plan: the Plan emitted by a Controller.
            bundle: the InputBundle for this window.
            memory: pre-filtered memory view (time-ordered, same-run-excluded).
            ablation: ablation tag (threaded to AgentContext + trace).
            seed: deterministic seed for any random-sample skills.
            evaluation_mode: overrides the auto-detected mode. Default:
                "wol" / "world_of_logs" datasets → text_retrieval_generalisation;
                everything else → telemetry_diagnosis.
            extra_ctx: optional kwargs merged into AgentContext.extra.
            persist_trace: if True (default), write the trace to
                `trace_root/<experiment>/<window_id>.json` when
                `trace_root` is set on the runner.
        """
        budget = plan.global_budget.clone()
        trace = Trace(bundle_id=bundle.window_id, plan_id=plan.plan_id)

        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="plan_start",
            budget_snapshot=budget.snapshot(),
            notes={
                "plan_id": plan.plan_id,
                "controller": plan.controller_name,
                "n_invocations": len(plan.invocations),
                "dataset": bundle.dataset,
                "ablation": ablation,
            },
        ))

        ctx_extra = dict(extra_ctx or {})
        ctx_extra["trace"] = trace
        ctx = AgentContext(
            bundle_id=bundle.window_id,
            experiment=self.experiment,
            ablation=ablation,
            llm=self.llm,
            neo4j=self.neo4j,
            budget=budget,
            cache=self.cache,
            seed=seed,
            extra=ctx_extra,
        )

        aborted = False
        for invocation in plan.invocations:
            if aborted:
                break
            outcome = self._run_one(invocation, bundle, memory, ctx, trace, budget)
            if outcome == "abort":
                aborted = True

        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="plan_end",
            budget_snapshot=budget.snapshot(),
            notes={
                "aborted": aborted,
                "n_skill_calls": trace.n_skill_calls(),
                "had_error": trace.had_error(),
            },
        ))

        decision = self._build_decision(
            bundle=bundle, plan=plan, trace=trace,
            evaluation_mode=evaluation_mode, aborted=aborted,
        )

        trace_path = ""
        if persist_trace and self.trace_root is not None:
            trace.close(decision)
            written = trace.write_to(self.trace_root, experiment=self.experiment)
            trace_path = str(written)
            decision = dataclasses.replace(decision, trace_path=trace_path)
            # Re-write so trace_path appears inside the persisted JSON too.
            trace.close(decision)
            trace.write_to(self.trace_root, experiment=self.experiment)
        else:
            trace.close(decision)

        return decision

    # ------------------------------------------------------------------ one invocation

    def _run_one(
        self,
        invocation: SkillInvocation,
        bundle: InputBundle,
        memory: MemoryView,
        ctx: AgentContext,
        trace: Trace,
        budget: Budget,
    ) -> str:
        """Returns 'ok' or 'abort'."""
        name = invocation.skill_name

        # Gate check
        if invocation.gate is not None:
            try:
                gate_open = bool(invocation.gate(trace, budget))
            except Exception as e:                                   # noqa: BLE001
                log.warning("gate for %s raised %s; treating as gate-closed", name, e)
                gate_open = False
            if not gate_open:
                trace.add(TraceEvent(
                    ts=TraceEvent.now(), kind="skill_skipped_by_gate",
                    skill=name, skill_version=invocation.skill_version,
                    notes={"reason": "gate_closed"},
                ))
                return "ok"

        # Resolve skill from registry
        skill = self.registry.try_get(name)
        if skill is None:
            trace.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_failed",
                skill=name, skill_version=invocation.skill_version,
                error="not_registered",
                notes={"detail": f"skill {name!r} missing from registry"},
            ))
            return self._handle_on_failure(invocation, plan_has_fallback=False, trace=trace)

        # Soft version-mismatch warning (don't abort — registered version
        # is authoritative at execution time).
        if invocation.skill_version and invocation.skill_version != skill.version:
            log.warning(
                "skill %s version mismatch: plan=%s registry=%s; running registry version",
                name, invocation.skill_version, skill.version,
            )

        # Cache lookup
        cache_key = skill.cache_key(bundle, memory, extra_inputs=invocation.inputs or None)
        cached_output = self.cache.get(skill, cache_key)
        if cached_output is not None:
            self._record_cache_hit(trace, skill, cached_output, budget)
            return "ok"

        # Budget pre-check (we don't know the skill cost upfront, so just
        # verify the budget isn't already exhausted — actual cost is
        # deducted post-invoke and may trigger a BudgetExhausted then).
        if budget.is_exhausted():
            trace.add(TraceEvent(
                ts=TraceEvent.now(), kind="budget_exceeded",
                skill=name, skill_version=skill.version,
                error="budget exhausted before invocation",
                budget_snapshot=budget.snapshot(),
            ))
            return "abort"

        # Invoke
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_start",
            skill=name, skill_version=skill.version,
            budget_snapshot=budget.snapshot(),
        ))

        start = time.monotonic()
        try:
            output = skill.invoke(bundle, memory, ctx)
        except Exception as e:                                       # noqa: BLE001
            duration_ms = (time.monotonic() - start) * 1000.0
            trace.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_failed",
                skill=name, skill_version=skill.version,
                error=f"{type(e).__name__}: {e}",
                duration_ms=round(duration_ms, 3),
                budget_snapshot=budget.snapshot(),
            ))
            return self._handle_on_failure(
                invocation,
                plan_has_fallback=bool(invocation.skill_name in (ctx.extra.get("__plan_fallbacks", {}))),
                trace=trace,
            )

        duration_ms = (time.monotonic() - start) * 1000.0

        # Budget deduction
        try:
            budget.deduct(output.cost)
        except BudgetExhausted as e:
            trace.add(TraceEvent(
                ts=TraceEvent.now(), kind="budget_exceeded",
                skill=name, skill_version=skill.version,
                error=str(e),
                duration_ms=round(duration_ms, 3),
                budget_snapshot=budget.snapshot(),
            ))
            # The work was already done — record the output so downstream
            # skills can still consult it, but then abort the plan.
            trace.add(TraceEvent(
                ts=TraceEvent.now(), kind="skill_end",
                skill=name, skill_version=skill.version,
                output=output,
                duration_ms=round(duration_ms, 3),
                budget_snapshot=budget.snapshot(),
            ))
            return "abort"

        # Cache write (best-effort; never raises into the runner loop)
        try:
            self.cache.put(skill, cache_key, output)
        except Exception as e:                                       # noqa: BLE001
            log.warning("cache.put failed for %s: %s", name, e)

        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end",
            skill=name, skill_version=skill.version,
            output=output,
            duration_ms=round(duration_ms, 3),
            budget_snapshot=budget.snapshot(),
        ))
        return "ok"

    # ------------------------------------------------------------------ helpers

    def _record_cache_hit(
        self,
        trace: Trace,
        skill: Skill,
        cached_output: SkillOutput,
        budget: Budget,
    ) -> None:
        """Emit cache_hit + skill_end so latest_output() finds the
        cached value. Cache hits don't deduct from the budget (the work
        was paid for in a previous run)."""
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="cache_hit",
            skill=skill.name, skill_version=skill.version,
            output=cached_output,
            duration_ms=0.0,
            budget_snapshot=budget.snapshot(),
        ))
        trace.add(TraceEvent(
            ts=TraceEvent.now(), kind="skill_end",
            skill=skill.name, skill_version=skill.version,
            output=cached_output,
            duration_ms=0.0,
            budget_snapshot=budget.snapshot(),
            notes={"from_cache": True},
        ))

    def _handle_on_failure(
        self,
        invocation: SkillInvocation,
        *,
        plan_has_fallback: bool,
        trace: Trace,
    ) -> str:
        """Translate `on_failure` policy into a runner-loop return code.

        v1: 'fallback' has no concrete fallback chain in the rule
        controller, so it degrades to 'continue'. The hook exists for
        future controllers that populate Plan.fallback_chains."""
        policy = invocation.on_failure
        if policy == "abort":
            return "abort"
        if policy == "fallback":
            trace.add(TraceEvent(
                ts=TraceEvent.now(), kind="fallback_triggered",
                skill=invocation.skill_name,
                notes={"plan_has_fallback": plan_has_fallback},
            ))
            return "ok"
        # "continue" — and any unknown values degrade to continue
        return "ok"

    # ------------------------------------------------------------------ decision

    def _build_decision(
        self,
        *,
        bundle: InputBundle,
        plan: Plan,
        trace: Trace,
        evaluation_mode: EvaluationMode | None,
        aborted: bool,
    ) -> AgentDecision:
        """Translate the trace's compose_* outputs into an AgentDecision.

        Field-by-field derivation:
          - triage_decision/score/confidence ← compose_triage
          - matched_issue_ids ← compose_l2 (fall back to retrieve_dense if absent)
          - is_novel ← compose_novelty
          - evaluation_mode ← bundle.dataset (overridable)
          - skills_invoked ← every skill_end (cached + computed)
          - cost ← sum of all SkillOutput.cost
        """
        eval_mode = evaluation_mode or self._infer_evaluation_mode(bundle.dataset)

        triage_out = trace.latest_output(_COMPOSE_TRIAGE)
        l2_out = trace.latest_output(_COMPOSE_L2)
        novelty_out = trace.latest_output(_COMPOSE_NOVELTY)

        triage_decision: TriageDecision = "noise"
        triage_score = 0.0
        confidence = 0.0
        if triage_out is not None:
            if triage_out.triage_decision:
                triage_decision = triage_out.triage_decision
            if triage_out.triage_score is not None:
                triage_score = float(triage_out.triage_score)
            confidence = float(triage_out.confidence or 0.0)

        # Graceful degradation: if the run was aborted before any
        # composition output landed, surface needs_review.
        if aborted and triage_out is None:
            triage_decision = "needs_review"
            confidence = 0.0

        if l2_out is not None and l2_out.matched_issue_ids:
            matched: tuple[str, ...] = l2_out.matched_issue_ids
        else:
            dense_out = trace.latest_output(_RETRIEVE_DENSE)
            matched = dense_out.matched_issue_ids if dense_out else ()

        is_novel = bool(novelty_out.is_novel) if (novelty_out and novelty_out.is_novel is not None) else False

        # Sum cost across every skill_end event (cache hits contribute
        # the cached SkillOutput.cost, which captured the original work
        # — but we keep them at zero for cache hits via _record_cache_hit
        # only if the cached output itself had cost=zero. To get accurate
        # "cost paid this run", we zero out from-cache events.)
        total_cost = SkillCallCost.zero()
        skills_invoked: list[str] = []
        for event in trace.events:
            if event.kind != "skill_end" or event.output is None:
                continue
            skills_invoked.append(event.skill or event.output.skill)
            if event.notes.get("from_cache"):
                # cache hit — work was paid in a prior run
                continue
            total_cost = total_cost + event.output.cost

        return AgentDecision(
            bundle_id=bundle.window_id,
            triage_decision=triage_decision,
            triage_score=triage_score,
            matched_issue_ids=matched,
            is_novel=is_novel,
            confidence=confidence,
            evaluation_mode=eval_mode,
            plan_id=plan.plan_id,
            skills_invoked=tuple(skills_invoked),
            cost=total_cost,
        )

    @staticmethod
    def _infer_evaluation_mode(dataset: str) -> EvaluationMode:
        d = (dataset or "").lower()
        if d in TEXT_ONLY_DATASETS:
            return "text_retrieval_generalisation"
        return "telemetry_diagnosis"

    # ------------------------------------------------------------------ debug

    def __repr__(self) -> str:
        return (
            f"AgentRunner(registry={self.registry!r}, "
            f"cache={type(self.cache).__name__}, "
            f"experiment={self.experiment!r})"
        )
