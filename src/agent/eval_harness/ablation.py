"""Declarative ablation harness.

Closes RQ-C5: "how much of the agent's Hit@K came from skill X?".

Three knobs per ablation:
  - `disable_skills`        — drop named skills from the registry.
  - `enable_skills_exact`   — keep ONLY the named skills (drop the rest).
  - `mask_capabilities`     — remove capability flags AFTER observation,
                              so a skill's `required_flags` no longer
                              passes the gate. Closer to "what if the
                              modality didn't exist?" than disabling
                              the skill itself.

Per ablation, the harness:
  1. Mutates the registry (copy_without / copy_only).
  2. Wraps the observer with the capability mask.
  3. Constructs a FRESH EvalHarness + StateLayer for that ablation
     (so suppression counts don't leak across ablations).
  4. Calls `harness.evaluate(cases, contract=...)`.
  5. Captures the resulting `EvaluationReport`.

Each ablation re-runs over the same cases; cached predictions make
the grid 10× cheaper than a cold run (§9.4).

The cheap-path predictions-backed skills do not depend on the
mutability of `bundle` between runs, so the same `EvaluationCase`
list is safe to reuse.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §9.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from ..capabilities import Capabilities
from ..capabilities_observer import CapabilitiesObserver, ObservationContext
from ..controller import Controller, RuleController
from ..runner import AgentRunner
from ..skills.registry import SkillRegistry
from ..state import StateLayer
from ..types import InputBundle
from .harness import EvalHarness
from .types import ApplesToApplesContract, EvaluationCase, EvaluationReport


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AblationSpec — what one ablation does to the agent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AblationSpec:
    """One ablation declaration.

    Exactly one of `disable_skills` and `enable_skills_exact` may be
    non-empty (mixing them is confusing — the user almost certainly
    means one or the other). `mask_capabilities` may always be set.

    Fields:
        name: identifier for the ablation row (e.g. "no_verifier").
        disable_skills: skill names to remove from the registry.
        enable_skills_exact: skill names to KEEP (drop everything else).
        mask_capabilities: capability flags to strip from observed
            Capabilities before the controller sees them.
        description: optional human-readable note for the report.
    """
    name: str
    disable_skills: tuple[str, ...] = ()
    enable_skills_exact: tuple[str, ...] = ()
    mask_capabilities: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if self.disable_skills and self.enable_skills_exact:
            raise ValueError(
                f"AblationSpec {self.name!r}: choose either disable_skills "
                f"OR enable_skills_exact, not both.",
            )
        if not self.name:
            raise ValueError("AblationSpec.name must be non-empty.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "disable_skills": list(self.disable_skills),
            "enable_skills_exact": list(self.enable_skills_exact),
            "mask_capabilities": list(self.mask_capabilities),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AblationSpec":
        return cls(
            name=str(d["name"]),
            disable_skills=tuple(d.get("disable_skills") or ()),
            enable_skills_exact=tuple(d.get("enable_skills_exact") or ()),
            mask_capabilities=tuple(d.get("mask_capabilities") or ()),
            description=str(d.get("description", "")),
        )


@dataclass(frozen=True)
class AblationConfig:
    """Top-level ablation experiment config — one baseline + N ablations."""
    name: str
    baseline_name: str = "baseline"
    ablations: tuple[AblationSpec, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "baseline_name": self.baseline_name,
            "ablations": [a.to_dict() for a in self.ablations],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AblationConfig":
        return cls(
            name=str(d["name"]),
            baseline_name=str(d.get("baseline_name", "baseline")),
            ablations=tuple(
                AblationSpec.from_dict(a) for a in (d.get("ablations") or ())
            ),
        )


# ---------------------------------------------------------------------------
# Capability-masking observer wrapper
# ---------------------------------------------------------------------------


class _MaskedObserver:
    """Wraps a CapabilitiesObserver and strips configured flags from
    every observation. Acts identically to the base observer when
    `mask` is empty.

    Used by the ablation harness to answer "what if NUMERIC_FEATURES
    didn't exist?" — the bundle still carries the data, but the agent
    can't see it."""

    def __init__(
        self,
        base: CapabilitiesObserver,
        *,
        mask: Iterable[str] = (),
    ) -> None:
        self._base = base
        self._mask = frozenset(mask)

    def observe(
        self,
        bundle: InputBundle,
        ctx: ObservationContext | None = None,
    ) -> Capabilities:
        caps = self._base.observe(bundle, ctx)
        if not self._mask:
            return caps
        return caps.mask(self._mask)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AblationGridResult:
    """All EvaluationReports from one grid run + delta-vs-baseline summary."""
    config: AblationConfig
    contract: ApplesToApplesContract
    baseline_report: EvaluationReport
    ablation_reports: dict[str, EvaluationReport] = field(default_factory=dict)

    def to_summary_rows(self) -> list[dict[str, Any]]:
        """One row per ablation (and baseline), with deltas vs baseline.

        Useful for the paper's ablation table; each row is a dict that
        renders cleanly as Markdown or CSV."""
        rows: list[dict[str, Any]] = []

        def _row(label: str, report: EvaluationReport, baseline: EvaluationReport):
            return {
                "ablation": label,
                "hit_at_1": round(report.hit_at_1, 4),
                "hit_at_5": round(report.hit_at_5, 4),
                "hit_at_10": round(report.hit_at_10, 4),
                "mrr": round(report.mrr, 4),
                "triage_accuracy": round(report.triage_accuracy, 4),
                "n_pages_emitted": report.n_pages_emitted,
                "n_incidents": report.n_incidents,
                "pages_per_incident": round(report.pages_per_incident, 3),
                "delta_hit_at_5": round(report.hit_at_5 - baseline.hit_at_5, 4),
                "delta_mrr": round(report.mrr - baseline.mrr, 4),
                "n_cases": report.n_cases,
                "n_evaluable_retrieval_cases": report.n_evaluable_retrieval_cases,
                "plan_ids_seen": list(report.plan_ids_seen),
                "cost_llm_tokens": report.total_cost.llm_tokens,
                "cost_usd": round(report.total_cost.usd, 6),
            }

        rows.append(_row(self.config.baseline_name, self.baseline_report,
                         self.baseline_report))
        for spec in self.config.ablations:
            if spec.name not in self.ablation_reports:
                continue
            rows.append(_row(spec.name, self.ablation_reports[spec.name],
                             self.baseline_report))
        return rows

    def to_dict(self, *, include_case_results: bool = False) -> dict[str, Any]:
        """Serializable shape. By default case_results are dropped from
        every report (they make the file huge); pass
        include_case_results=True to keep them."""
        return {
            "config": self.config.to_dict(),
            "contract": self.contract.to_dict(),
            "baseline_report": self.baseline_report.to_dict(
                include_case_results=include_case_results,
            ),
            "ablation_reports": {
                name: r.to_dict(include_case_results=include_case_results)
                for name, r in self.ablation_reports.items()
            },
            "summary_rows": self.to_summary_rows(),
        }

    def write_to(
        self,
        path: Path | str,
        *,
        include_case_results: bool = False,
        indent: int | None = 2,
    ) -> Path:
        import json
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                self.to_dict(include_case_results=include_case_results),
                indent=indent, default=str,
            ),
            encoding="utf-8",
        )
        return out


# ---------------------------------------------------------------------------
# AblationHarness
# ---------------------------------------------------------------------------


#: Signature for the StateLayer factory — each ablation gets a fresh
#: StateLayer so suppression counts don't leak across ablations.
StateLayerFactory = Callable[[], "StateLayer | None"]


class AblationHarness:
    """Run an ablation grid over a fixed case list.

    The harness is constructed with a `template` registry (the full
    skill set) + the observer + observation_ctx. Each ablation in the
    config mutates the registry / observer per its spec, builds a
    fresh EvalHarness, and runs `evaluate()`.

    Each ablation gets a FRESH StateLayer (via state_layer_factory)
    so per-ablation page-suppression counts don't leak across runs.

    Args:
        registry: the template SkillRegistry (full skill set).
        controller_factory: callable taking the (possibly pruned)
            registry and returning a Controller. Default: a
            RuleController with default thresholds.
        runner_factory: callable taking the registry and an
            experiment-id string, returning an AgentRunner. Default:
            a NullSkillCache-backed AgentRunner.
        observer: CapabilitiesObserver (defaults to a stateless instance).
        observation_ctx: ObservationContext (defaults to a vanilla one).
        state_layer_factory: callable returning a fresh StateLayer for
            each ablation (None to disable state across the grid).
    """

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        controller_factory: Callable[[SkillRegistry], Controller] | None = None,
        runner_factory: Callable[[SkillRegistry, str], AgentRunner] | None = None,
        observer: CapabilitiesObserver | None = None,
        observation_ctx: ObservationContext | None = None,
        state_layer_factory: StateLayerFactory | None = None,
    ) -> None:
        self.registry = registry
        self.controller_factory = controller_factory or _default_controller_factory
        self.runner_factory = runner_factory or _default_runner_factory
        self.observer = observer or CapabilitiesObserver()
        self.observation_ctx = observation_ctx or ObservationContext()
        self.state_layer_factory = state_layer_factory or (lambda: StateLayer())

    # ------------------------------------------------------------------ run_grid

    def run_grid(
        self,
        cases: list[EvaluationCase],
        config: AblationConfig,
        *,
        contract: ApplesToApplesContract,
        keep_case_details: bool = False,
    ) -> AblationGridResult:
        """Run baseline + every ablation; return the full grid."""
        log.info(
            "AblationHarness.run_grid: experiment=%s n_cases=%d n_ablations=%d",
            config.name, len(cases), len(config.ablations),
        )

        # ------------------------------------------------------------------ baseline
        baseline_report = self._evaluate_one(
            cases=cases,
            contract=contract,
            ablation_name=config.baseline_name,
            registry=self.registry,                          # template, unmodified
            mask=(),
            keep_case_details=keep_case_details,
        )

        # ------------------------------------------------------------------ ablations
        ablation_reports: dict[str, EvaluationReport] = {}
        for spec in config.ablations:
            ablated_registry = self._apply_registry_mutation(self.registry, spec)
            report = self._evaluate_one(
                cases=cases,
                contract=contract,
                ablation_name=spec.name,
                registry=ablated_registry,
                mask=tuple(spec.mask_capabilities),
                keep_case_details=keep_case_details,
            )
            ablation_reports[spec.name] = report

        return AblationGridResult(
            config=config,
            contract=contract,
            baseline_report=baseline_report,
            ablation_reports=ablation_reports,
        )

    # ------------------------------------------------------------------ one ablation

    def _evaluate_one(
        self,
        *,
        cases: list[EvaluationCase],
        contract: ApplesToApplesContract,
        ablation_name: str,
        registry: SkillRegistry,
        mask: tuple[str, ...],
        keep_case_details: bool,
    ) -> EvaluationReport:
        controller = self.controller_factory(registry)
        runner = self.runner_factory(registry, ablation_name)
        observer: Any = self.observer
        if mask:
            observer = _MaskedObserver(self.observer, mask=mask)

        harness = EvalHarness(
            controller=controller,
            runner=runner,
            observer=observer,
            observation_ctx=self.observation_ctx,
            state_layer=self.state_layer_factory(),
        )
        log.info("ablation: %s — running over %d cases", ablation_name, len(cases))
        report = harness.evaluate(
            cases, contract=contract,
            experiment_name=ablation_name,
            ablation=ablation_name,
            keep_case_details=keep_case_details,
        )
        return report

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _apply_registry_mutation(
        registry: SkillRegistry,
        spec: AblationSpec,
    ) -> SkillRegistry:
        """Apply spec's enable_skills_exact / disable_skills to `registry`.

        Returns a copy; the input is untouched."""
        if spec.enable_skills_exact:
            return registry.copy_only(set(spec.enable_skills_exact))
        if spec.disable_skills:
            return registry.copy_without(set(spec.disable_skills))
        return registry.copy()


# ---------------------------------------------------------------------------
# Default factories
# ---------------------------------------------------------------------------


def _default_controller_factory(registry: SkillRegistry) -> Controller:
    return RuleController(registry)


def _default_runner_factory(registry: SkillRegistry, ablation_name: str) -> AgentRunner:
    return AgentRunner(registry, experiment=f"ablation:{ablation_name}")
