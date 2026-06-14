"""Shared harness builder — single source of truth for OB / WoL / OTel.

Phase 3 prerequisite (task #101). Before this module, every smoke
script (smoke_ob.py, smoke_wol.py, smoke_otel_demo.py) carried its
own copy of `_build_registry()` + `_build_harness()`. They drifted
during Phase 2 — the WoL and OTel smokes were stuck on the base
RuleController while smoke_ob.py moved to CapabilityAwareRuleController
+ 4 ReAct tools + RerankWithEvidenceSkill + ReformulateQuerySkill.

This module collapses all three builders into one. The per-dataset
differences are captured in `DatasetProfile` instances, picked by
the `dataset_label` argument. Adding a new dataset = add one
`DatasetProfile` constant. No new code path elsewhere.

Public API:

    from agent.harness_builder import build_harness_for_dataset

    harness, contract = build_harness_for_dataset(
        dataset_label="online_boutique",        # or "wol" | "otel_demo"
        global_dir=Path(...),
        cache_dir=Path(...),
        trace_root=Path(...),
        skip=set(),
        use_state_layer=True,
        max_tool_calls=None,
        runs_root_override=None,                # auto-resolved from profile
    )

The smoke scripts (smoke_ob.py, smoke_wol.py, smoke_otel_demo.py)
each call this with their `dataset_label`. The Phase-3 scripts
(budget_curve.py, tool_ablation.py, cost_vs_cascade.py,
capability_mask_sweep.py) also call this directly — they were
previously importing `_build_harness` from smoke_ob.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .capabilities_observer import (
    CapabilitiesObserver,
    ObservationContext,
    VerifierCalibration,
)
from .controller import CapabilityAwareRuleController
from .data_lake import RawRunDataLake
from .eval_harness import ApplesToApplesContract, EvalHarness
from .runner import AgentRunner
from .skills import (
    ComposeL2Skill,
    ComposeNoveltySkill,
    ComposeTriageSkill,
    RetrieveDenseSkill,
    RetrieveHybridFusionLLMSkill,
    RetrieveHybridFusionSkill,
    RetrieveKnowledgeGraphSkill,
    RetrieveLogSequenceSkill,
    SkillCache,
    SkillRegistry,
    TriageNumericSkill,
    VerifyWithLLMSkill,
)
from .skills.evidence_request import (
    RequestExtendedTraceWindowSkill,
    RequestPodEventsSkill,
    RequestPodMetricsSkill,
    RequestSimilarIncidentWindowSkill,
)
from .skills.reformulate_query import ReformulateQuerySkill
from .skills.rerank_with_evidence import RerankWithEvidenceSkill
from .state import StateLayer
from .types import EvaluationMode


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DatasetProfile — encapsulates per-dataset wiring
# ---------------------------------------------------------------------------


PredictionsLayout = Literal["comparison", "tch_lite_refit"]
VerifierPolicy = Literal["helpful", "harmful", "skip"]


@dataclass(frozen=True)
class PredictionsBackedEntry:
    """One predictions-backed skill registration recipe.

    Fields:
        skill_cls: the Skill subclass (e.g. TriageNumericSkill)
        path_segment: under `comparison/` for OB/OTel (a subdir); under
            `tch-lite-refit/` for WoL (a filename).
        pipeline_name: the `pipeline_name` to filter on inside the
            JSONL. None means accept rows from any pipeline (the
            predictions-backed skill's default).
    """
    skill_cls: type
    path_segment: str
    pipeline_name: str | None = None


@dataclass(frozen=True)
class DatasetProfile:
    """Per-dataset wiring profile.

    Encapsulates everything that varies between OB / OTel Demo / WoL so
    `build_harness_for_dataset()` is a single source of truth.

    The 4 ReAct evidence tools are always REGISTERED on the profile's
    behalf; the capability gate (set by the dataset's loader via
    `extra["*_fetchable"]` markers) decides whether each one fires.
    On WoL, the 3 telemetry tools auto-drop because the bundles don't
    carry K8S_EVENTS / TRACE_SUMMARY / METRIC_SNAPSHOTS markers; only
    `request_similar_incident_window` (no required_flags) actually fires.
    """
    dataset_label: str
    predictions_layout: PredictionsLayout
    runs_root: Path | None
    evaluation_mode: EvaluationMode
    verifier_policy: VerifierPolicy
    predictions_skills: tuple[PredictionsBackedEntry, ...]
    verifier_entry: PredictionsBackedEntry | None = None

    @property
    def supports_telemetry_react(self) -> bool:
        """True iff the dataset has on-disk telemetry the 3 telemetry
        tools (pod_events, extended_trace, pod_metrics) can read."""
        return self.runs_root is not None


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------


OB_PROFILE = DatasetProfile(
    dataset_label="online_boutique",
    predictions_layout="comparison",
    runs_root=Path("data/runs"),
    evaluation_mode="telemetry_diagnosis",
    verifier_policy="helpful",
    predictions_skills=(
        PredictionsBackedEntry(TriageNumericSkill, "v2a-resplit"),
        PredictionsBackedEntry(RetrieveDenseSkill, "v2a-resplit"),
        PredictionsBackedEntry(RetrieveLogSequenceSkill, "v2b-logseq2vec"),
        PredictionsBackedEntry(RetrieveHybridFusionSkill, "v2c-hybrid"),
        PredictionsBackedEntry(RetrieveHybridFusionLLMSkill, "v2c-hybrid-llm"),
        PredictionsBackedEntry(RetrieveKnowledgeGraphSkill, "v2d-kg-rulebased"),
    ),
    verifier_entry=PredictionsBackedEntry(VerifyWithLLMSkill, "v2e-agent-llm"),
)

OTEL_PROFILE = DatasetProfile(
    dataset_label="otel_demo",
    predictions_layout="comparison",
    runs_root=Path("data/otel-demo-runs"),
    evaluation_mode="telemetry_diagnosis",
    verifier_policy="skip",                          # tbd via RQ-B1 calibration
    predictions_skills=(
        PredictionsBackedEntry(TriageNumericSkill, "v2a-resplit"),
        PredictionsBackedEntry(RetrieveDenseSkill, "v2a-resplit"),
        PredictionsBackedEntry(RetrieveHybridFusionSkill, "v2c-hybrid"),
    ),
    verifier_entry=None,                             # not registered until calibrated
)

WOL_PROFILE = DatasetProfile(
    dataset_label="wol",
    predictions_layout="tch_lite_refit",
    runs_root=None,                                  # no telemetry on WoL
    evaluation_mode="text_retrieval_generalisation",
    verifier_policy="harmful",                       # Mode 3 §3.9
    predictions_skills=(
        PredictionsBackedEntry(
            RetrieveDenseSkill, "biencoder-predictions.jsonl",
            pipeline_name="bi_encoder_retrieval",
        ),
        PredictionsBackedEntry(
            RetrieveLogSequenceSkill, "logseq2vec-predictions.jsonl",
            pipeline_name="logseq2vec_retrieval",
        ),
        PredictionsBackedEntry(
            RetrieveHybridFusionSkill, "hybrid-rrf-predictions.jsonl",
            pipeline_name="hybrid_rrf_retrieval",
        ),
        PredictionsBackedEntry(
            RetrieveKnowledgeGraphSkill, "kg-retrieval-predictions.jsonl",
            pipeline_name="kg_retrieval",
        ),
    ),
    # Verifier still uses the diagnosis-agent predictions on WoL but
    # capability gate (VERIFIER_KNOWN_HELPFUL absent) prevents the
    # runner from ever invoking it. Registered for inspection only.
    verifier_entry=PredictionsBackedEntry(
        VerifyWithLLMSkill, "diagnosis-agent-predictions.jsonl",
        pipeline_name="diagnosis_agent",
    ),
)


DATASET_PROFILES: dict[str, DatasetProfile] = {
    OB_PROFILE.dataset_label:   OB_PROFILE,
    OTEL_PROFILE.dataset_label: OTEL_PROFILE,
    WOL_PROFILE.dataset_label:  WOL_PROFILE,
}


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------


def _resolve_predictions_path(
    global_dir: Path,
    layout: PredictionsLayout,
    path_segment: str,
) -> Path:
    """Map (layout, segment) → concrete predictions JSONL path."""
    if layout == "comparison":
        return global_dir / "comparison" / path_segment / "per-window-predictions.jsonl"
    elif layout == "tch_lite_refit":
        return global_dir / "tch-lite-refit" / path_segment
    raise ValueError(f"unknown predictions_layout: {layout!r}")


def _register_predictions_backed(
    reg: SkillRegistry,
    profile: DatasetProfile,
    global_dir: Path,
    *,
    skip: set[str],
    include_verifier: bool,
) -> None:
    """Register every predictions-backed skill from the profile."""
    entries = list(profile.predictions_skills)
    if include_verifier and profile.verifier_entry is not None:
        entries.append(profile.verifier_entry)

    for entry in entries:
        if entry.skill_cls.name in skip:
            continue
        preds_path = _resolve_predictions_path(
            global_dir, profile.predictions_layout, entry.path_segment,
        )
        if not preds_path.exists():
            log.warning(
                "skipping %s — predictions JSONL not found at %s",
                entry.skill_cls.name, preds_path,
            )
            continue
        kwargs: dict[str, Any] = {"predictions_path": preds_path}
        if entry.pipeline_name is not None:
            kwargs["predictions_pipeline_name"] = entry.pipeline_name
        reg.register(entry.skill_cls(**kwargs))


def _register_react_skills(
    reg: SkillRegistry,
    profile: DatasetProfile,
    global_dir: Path,
    *,
    skip: set[str],
    max_tool_calls: int | None,
    runs_root_override: Path | None,
) -> None:
    """Register the 4 EvidenceRequestSkills + RerankWithEvidenceSkill.

    On WoL (no runs_root), the 3 telemetry tools register but their
    `required_flags` (K8S_EVENTS / TRACE_SUMMARY / METRIC_SNAPSHOTS)
    aren't in the bundle's Capabilities, so the runner's
    `can_invoke()` check auto-drops them. The peers tool fires
    regardless — it reads the in-memory corpus, not the runs disk.
    """
    runs_root = runs_root_override if runs_root_override is not None else profile.runs_root
    can_fetch_telemetry = runs_root is not None and Path(runs_root).is_dir()

    # We still build a data lake even when runs_root is None — the
    # peers tool doesn't use runs_root, and the data lake's
    # constructor tolerates a non-existent root. We use a benign
    # stub so the data lake can still be created.
    lake_runs_root = Path(runs_root) if can_fetch_telemetry else Path("data/runs")
    lake = RawRunDataLake(
        runs_root=lake_runs_root,
        cache_root=Path("data/tool_cache"),
    )

    evidence_skills: list = []
    if can_fetch_telemetry:
        if RequestPodEventsSkill.name not in skip:
            evidence_skills.append(RequestPodEventsSkill(data_lake=lake))
        if RequestExtendedTraceWindowSkill.name not in skip:
            evidence_skills.append(RequestExtendedTraceWindowSkill(data_lake=lake))
        if RequestPodMetricsSkill.name not in skip:
            evidence_skills.append(RequestPodMetricsSkill(data_lake=lake))
    elif (
        RequestPodEventsSkill.name not in skip
        or RequestExtendedTraceWindowSkill.name not in skip
        or RequestPodMetricsSkill.name not in skip
    ):
        log.info(
            "telemetry-tool ReAct skills auto-dropped on dataset_label=%s "
            "(runs_root=%s; profile lacks telemetry capture)",
            profile.dataset_label, runs_root,
        )

    if RequestSimilarIncidentWindowSkill.name not in skip:
        evidence_skills.append(RequestSimilarIncidentWindowSkill(
            data_lake=lake, global_dir=global_dir, top_k=3,
        ))

    if max_tool_calls is not None:
        for s in evidence_skills:
            s.max_tool_calls = int(max_tool_calls)
    for s in evidence_skills:
        reg.register(s)

    if RerankWithEvidenceSkill.name not in skip:
        reg.register(RerankWithEvidenceSkill(alpha=0.4, rerank_top_k=5))


def _build_registry(
    profile: DatasetProfile,
    global_dir: Path,
    *,
    skip: set[str],
    include_verifier: bool,
    max_tool_calls: int | None,
    runs_root_override: Path | None,
) -> SkillRegistry:
    """Construct the full skill registry for a dataset.

    Order: predictions-backed → composition → reformulate → ReAct tools
    → rerank. Order is irrelevant for correctness (controller decides
    ordering inside Plans) but stable for debugging.
    """
    reg = SkillRegistry()

    _register_predictions_backed(
        reg, profile, global_dir, skip=skip, include_verifier=include_verifier,
    )

    # Composition skills — no JSONL backing; pure trace-readers.
    for compose_cls in (ComposeL2Skill, ComposeTriageSkill, ComposeNoveltySkill):
        if compose_cls.name in skip:
            continue
        reg.register(compose_cls())

    # Reformulation — deterministic stub by default (use_llm=False).
    if ReformulateQuerySkill.name not in skip:
        reg.register(ReformulateQuerySkill(use_llm=False))

    # Phase 2 ReAct: 4 evidence tools + rerank.
    _register_react_skills(
        reg, profile, global_dir,
        skip=skip, max_tool_calls=max_tool_calls,
        runs_root_override=runs_root_override,
    )

    return reg


def _build_verifier_calibration(
    profile: DatasetProfile,
    dataset_id: str,
) -> VerifierCalibration:
    """Build the VerifierCalibration appropriate to the profile.

    The capability gate (VERIFIER_KNOWN_HELPFUL) is set ON IFF the
    profile says "helpful". This is the structural-skip for RQ-A8 —
    a `harmful` (e.g. WoL) or `skip` (e.g. OTel pre-calibration)
    dataset never gets the flag, so verify_with_llm.can_invoke()
    returns False even if registered.
    """
    if profile.verifier_policy == "helpful":
        return VerifierCalibration(
            known_helpful_distributions=frozenset({dataset_id}),
            known_harmful_distributions=frozenset(),
            default_policy="skip",
        )
    if profile.verifier_policy == "harmful":
        return VerifierCalibration(
            known_helpful_distributions=frozenset(),
            known_harmful_distributions=frozenset({dataset_id}),
            default_policy="skip",
        )
    # "skip" default
    return VerifierCalibration(
        known_helpful_distributions=frozenset(),
        known_harmful_distributions=frozenset(),
        default_policy="skip",
    )


def _detect_kg_graph_window(global_dir: Path) -> bool:
    """Auto-detect KG_GRAPH_WINDOW (RQ-A6 closure path)."""
    window_ext_path = global_dir / "v2_kg_extractions_windows" / "all_extractions.jsonl"
    if window_ext_path.exists():
        log.info("KG_GRAPH_WINDOW: window extractions found at %s", window_ext_path)
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_harness_for_dataset(
    dataset_label: str,
    global_dir: Path | str,
    *,
    cache_dir: Path | None = None,
    trace_root: Path | None = None,
    skip: set[str] | None = None,
    include_verifier: bool = False,
    use_state_layer: bool = True,
    max_tool_calls: int | None = None,
    runs_root_override: Path | None = None,
    max_reformulation_retries: int = 1,
    experiment_prefix: str = "smoke",
) -> tuple[EvalHarness, ApplesToApplesContract]:
    """Build an EvalHarness for OB / WoL / OTel Demo from one entry point.

    Args:
        dataset_label: one of `DATASET_PROFILES` keys (currently
            "online_boutique", "otel_demo", "wol").
        global_dir: dataset root (e.g.
            `data/derived/global/2026-05-25-dataset-v5-large-global`).
        cache_dir: optional SkillCache root. None disables caching.
        trace_root: optional per-window trace root. None disables persist.
        skip: skill names to drop from the registry (works the same way
            `--skip-skill NAME` does in the smoke scripts).
        include_verifier: register `verify_with_llm` if the profile
            allows it (i.e. has a verifier_entry). Defaults to False so
            the cheap smoke stays cheap; pass True for §3.5 + Phase 3
            full runs.
        use_state_layer: enable the cross-window StateLayer + page
            suppression. Disabled in some sweeps (budget_curve.py,
            tool_ablation.py) for cleaner Hit@K isolation.
        max_tool_calls: per-window ReAct budget cap. None = profile
            default (DEFAULT_MAX_TOOL_CALLS=6).
        runs_root_override: override the profile's runs_root. Used by
            tests + ablations. Default None = use profile.runs_root.
        max_reformulation_retries: passed to CapabilityAwareRuleController.
        experiment_prefix: prefix for runner.experiment (used to name
            the trace subdirectory). Default "smoke".

    Returns:
        (harness, contract) tuple ready for `harness.evaluate(cases, contract=contract, ...)`.

    Raises:
        KeyError: if `dataset_label` isn't a registered profile.
        FileNotFoundError: if any required predictions JSONL is missing
            (the registry would log warnings; this surfaces them).
    """
    if dataset_label not in DATASET_PROFILES:
        raise KeyError(
            f"unknown dataset_label={dataset_label!r}; "
            f"available: {sorted(DATASET_PROFILES)}",
        )
    profile = DATASET_PROFILES[dataset_label]
    global_dir = Path(global_dir)
    dataset_id = global_dir.name
    skip = set(skip) if skip is not None else set()

    registry = _build_registry(
        profile, global_dir,
        skip=skip,
        include_verifier=include_verifier,
        max_tool_calls=max_tool_calls,
        runs_root_override=runs_root_override,
    )

    cache = SkillCache(root=cache_dir) if cache_dir else None
    runner = AgentRunner(
        registry,
        cache=cache,
        trace_root=trace_root,
        experiment=f"{experiment_prefix}-{dataset_id}",
    )

    controller = CapabilityAwareRuleController(
        registry,
        max_reformulation_retries=max_reformulation_retries,
    )

    obs_ctx = ObservationContext(
        dataset_id=dataset_id,
        has_memory_text=True,
        has_kg_graph_memory=False,
        has_kg_graph_window=_detect_kg_graph_window(global_dir),
        verifier_calibration=_build_verifier_calibration(profile, dataset_id),
    )

    harness = EvalHarness(
        controller=controller,
        runner=runner,
        observer=CapabilitiesObserver(),
        observation_ctx=obs_ctx,
        state_layer=StateLayer() if use_state_layer else None,
    )

    contract = ApplesToApplesContract(
        dataset_id=dataset_id,
        split="test",
        gold_relation="coarse",
        memory_pool_size=0,
        evaluation_mode=profile.evaluation_mode,
    )
    return harness, contract


__all__ = [
    "DatasetProfile",
    "PredictionsBackedEntry",
    "DATASET_PROFILES",
    "OB_PROFILE",
    "OTEL_PROFILE",
    "WOL_PROFILE",
    "build_harness_for_dataset",
]
