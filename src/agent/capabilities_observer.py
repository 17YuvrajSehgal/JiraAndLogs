"""Capabilities Observer — turns an `InputBundle` (+ external context)
into a populated `Capabilities` set.

The observer is **the only place** in the agent that knows the mapping
from raw evidence fields to capability flags. Skills consult only the
output `Capabilities`; if a new modality is added, this is the file
that learns about it.

Two inputs:

  1. `InputBundle` — window-side evidence (what the system *observed*).
  2. `ObservationContext` — external state the observer needs:
        * dataset id (for VerifierCalibration lookup)
        * whether Neo4j has memory-side entities loaded
        * whether per-window LLM extractions exist
        * the active VerifierCalibration (loaded from agent-config.yaml)

The observer is stateless and deterministic: same `(bundle, ctx)`
always produces the same `Capabilities`. This makes ablations safe —
masking a flag at the controller level can't accidentally re-add it.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §8 (Adaptive modality).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .capabilities import (
    Capabilities,
    K8S_EVENTS,
    KG_GRAPH_MEMORY,
    KG_GRAPH_WINDOW,
    MEMORY_TEXT,
    METRIC_SNAPSHOTS,
    NUMERIC_FEATURES,
    ORDERED_LOGS,
    TEXT_EVIDENCE,
    TRACE_SUMMARY,
    UNORDERED_LOGS,
    VERIFIER_KNOWN_HELPFUL,
)
from .types import InputBundle


# ---------------------------------------------------------------------------
# Verifier calibration — closes RQ-A8
# ---------------------------------------------------------------------------


VerifierPolicy = Literal["skip", "enable"]


@dataclass(frozen=True)
class VerifierCalibration:
    """Which datasets the `verify_with_llm` skill is allowed to run on.

    The Mode 3 §3.9 finding showed that running the OB-tuned verifier on
    WoL DEGRADED Hit@5 by −0.272 absolute. So the agent must
    structurally refuse to invoke the verifier on datasets that aren't
    explicitly in `known_helpful_distributions`. This is the **structural
    closure of RQ-A8** — not a re-prompt, not a re-train; a refusal.

    The observer reads this table and sets `VERIFIER_KNOWN_HELPFUL`
    accordingly; the `verify_with_llm` skill declares that flag as
    required, so the runner can't invoke it on a dataset that isn't
    cleared.

    Add a dataset to one of the two lists when you have evidence that
    the verifier helps or hurts that dataset. New datasets stay in the
    `default_policy` bucket until calibrated.

    Loaded from `agent-config.yaml > verifier_calibration`:

        verifier_calibration:
          known_helpful_distributions:
            - 2026-05-25-dataset-v5-large-global   # OB
          known_harmful_distributions:
            - 2026-06-11-wol-real-global            # WoL (Mode 3 §3.9)
          default_policy: skip
    """

    known_helpful_distributions: frozenset[str] = field(default_factory=frozenset)
    known_harmful_distributions: frozenset[str] = field(default_factory=frozenset)
    default_policy: VerifierPolicy = "skip"

    # ------------------------------------------------------------------ policy

    def is_helpful(self, dataset_id: str) -> bool:
        """Return True iff the verifier should be allowed to run for `dataset_id`.

        Order:
            1. If dataset is in `known_harmful` → False (never).
            2. If dataset is in `known_helpful` → True.
            3. Else fall through to `default_policy`.
        """
        # known_harmful WINS over known_helpful — if someone accidentally
        # puts the same id in both lists, we err on the safe side.
        if dataset_id in self.known_harmful_distributions:
            return False
        if dataset_id in self.known_helpful_distributions:
            return True
        return self.default_policy == "enable"

    # ------------------------------------------------------------------ loaders

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VerifierCalibration":
        if not d:
            return cls()
        return cls(
            known_helpful_distributions=frozenset(
                d.get("known_helpful_distributions") or ()
            ),
            known_harmful_distributions=frozenset(
                d.get("known_harmful_distributions") or ()
            ),
            default_policy=d.get("default_policy", "skip"),
        )

    @classmethod
    def from_yaml_file(cls, path: Path | str) -> "VerifierCalibration":
        """Load just the `verifier_calibration` block from an
        `agent-config.yaml`-shaped file."""
        import yaml
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        block = data.get("verifier_calibration") or {}
        return cls.from_dict(block)

    def to_dict(self) -> dict[str, Any]:
        return {
            "known_helpful_distributions": sorted(self.known_helpful_distributions),
            "known_harmful_distributions": sorted(self.known_harmful_distributions),
            "default_policy": self.default_policy,
        }


# ---------------------------------------------------------------------------
# Observation context — what the observer needs beyond the bundle itself
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservationContext:
    """External context the observer reads beyond the InputBundle.

    Constructed once per experiment (or once per dataset switch) and
    reused across every bundle. Cheap to build; the observer just
    reads the booleans.

    Fields:
        dataset_id        — Matches `experiment.dataset_id` in agent-config.yaml;
                             used to look up `VERIFIER_KNOWN_HELPFUL`.
        has_memory_text   — True when the dataset's humanized corpus has
                             `memory_text` populated per ticket (true for all
                             three datasets in v1; included for
                             forward-compat).
        has_kg_graph_memory — True when Neo4j has Incident nodes for the
                             memory side. Set by the AgentRunner after
                             confirming the GraphMetadata fingerprint matches.
        has_kg_graph_window — True when per-window LLM extractions exist
                             on disk under `v2_kg_extractions_windows/`.
                             RQ-A6 closes when this is True for WoL.
        verifier_calibration — Loaded from agent-config.yaml.
    """

    dataset_id: str = ""
    has_memory_text: bool = True
    has_kg_graph_memory: bool = False
    has_kg_graph_window: bool = False
    verifier_calibration: VerifierCalibration = field(default_factory=VerifierCalibration)

    @classmethod
    def from_agent_config(
        cls,
        config: dict[str, Any],
        *,
        has_kg_graph_memory: bool = False,
        has_kg_graph_window: bool = False,
        has_memory_text: bool = True,
    ) -> "ObservationContext":
        """Build from the parsed `agent-config.yaml` dict.

        The KG/memory presence flags are runtime-discovered (the
        AgentRunner sets them after probing Neo4j + the on-disk
        extractions directory), so they're explicit kwargs."""
        experiment_block = config.get("experiment") or {}
        dataset_id = str(experiment_block.get("dataset_id") or "")
        calibration = VerifierCalibration.from_dict(
            config.get("verifier_calibration") or {}
        )
        return cls(
            dataset_id=dataset_id,
            has_memory_text=has_memory_text,
            has_kg_graph_memory=has_kg_graph_memory,
            has_kg_graph_window=has_kg_graph_window,
            verifier_calibration=calibration,
        )


# ---------------------------------------------------------------------------
# Observer
# ---------------------------------------------------------------------------


# Minimum text-evidence length to count as TEXT_EVIDENCE present.
# A few stray characters from a malformed window shouldn't unlock the
# dense retriever — the controller's downstream confidence checks will
# catch that case too, but rejecting it here makes the failure mode
# explicit.
_MIN_TEXT_EVIDENCE_CHARS = 8


class CapabilitiesObserver:
    """Observe a bundle + context → Capabilities.

    Stateless and deterministic — same inputs always produce the same
    output. Intentionally not a function so future extensions (e.g.
    per-dataset overrides) can subclass.
    """

    def observe(
        self,
        bundle: InputBundle,
        ctx: ObservationContext | None = None,
    ) -> Capabilities:
        ctx = ctx or ObservationContext()
        flags: set[str] = set()
        richness: dict[str, dict[str, Any]] = {}

        # NUMERIC_FEATURES ----------------------------------------------------
        if bundle.numeric_features:
            flags.add(NUMERIC_FEATURES)
            richness[NUMERIC_FEATURES] = {
                "n_columns": len(bundle.numeric_features),
            }

        # TEXT_EVIDENCE -------------------------------------------------------
        if bundle.text_evidence and len(bundle.text_evidence) >= _MIN_TEXT_EVIDENCE_CHARS:
            flags.add(TEXT_EVIDENCE)
            richness[TEXT_EVIDENCE] = {
                "n_chars": len(bundle.text_evidence),
            }

        # ORDERED_LOGS / UNORDERED_LOGS ---------------------------------------
        if bundle.log_lines:
            n_lines = len(bundle.log_lines)
            services = {l.service for l in bundle.log_lines}
            severities = {l.severity for l in bundle.log_lines}
            block: dict[str, Any] = {
                "n_lines": n_lines,
                "n_services": len(services),
                "n_severities": len(severities),
            }
            if bundle.log_lines_ordered:
                flags.add(ORDERED_LOGS)
                # max_span_seconds = (max ts_ns − min ts_ns) / 1e9
                ts_values = [l.ts_ns for l in bundle.log_lines if l.ts_ns]
                if len(ts_values) >= 2:
                    block["max_span_seconds"] = round(
                        (max(ts_values) - min(ts_values)) / 1e9, 3
                    )
                richness[ORDERED_LOGS] = block
            else:
                flags.add(UNORDERED_LOGS)
                richness[UNORDERED_LOGS] = block

        # TRACE_SUMMARY -------------------------------------------------------
        # Surface in two cases:
        #   1. bundle carries an in-memory trace_summary (legacy path).
        #   2. bundle marks "Tempo capture fetchable from disk" via
        #      extra["trace_summary_fetchable"] — set by the loader when
        #      the raw Tempo file exists for the window.
        # The ReAct `request_extended_trace_window` skill consumes the latter.
        if bundle.trace_summary is not None and bundle.trace_summary.n_spans > 0:
            flags.add(TRACE_SUMMARY)
            richness[TRACE_SUMMARY] = {
                "n_spans": bundle.trace_summary.n_spans,
                "error_spans": bundle.trace_summary.error_spans,
                "n_affected_services": len(bundle.trace_summary.affected_services),
            }
        elif (bundle.extra or {}).get("trace_summary_fetchable"):
            flags.add(TRACE_SUMMARY)
            richness[TRACE_SUMMARY] = {"source": "data_lake_disk"}

        # K8S_EVENTS ----------------------------------------------------------
        # Surface the flag in two cases:
        #   1. bundle already carries k8s_events in-memory.
        #   2. bundle marks "k8s events fetchable from disk for this
        #      window" via extra["k8s_events_fetchable"] — the loader
        #      sets this when the raw k8s file exists at
        #      data/runs/<run_id>/raw/kubernetes/<window_id>.json.
        # The ReAct `request_pod_events` skill consumes either path.
        if bundle.k8s_events:
            flags.add(K8S_EVENTS)
            richness[K8S_EVENTS] = {"n_events": len(bundle.k8s_events)}
        elif (bundle.extra or {}).get("k8s_events_fetchable"):
            flags.add(K8S_EVENTS)
            richness[K8S_EVENTS] = {"source": "data_lake_disk"}

        # METRIC_SNAPSHOTS ----------------------------------------------------
        # Surface in two cases:
        #   1. bundle carries in-memory metric_snapshots (legacy).
        #   2. bundle marks "Prometheus capture fetchable from disk" via
        #      extra["metric_snapshots_fetchable"] — set by the loader.
        # ReAct `request_pod_metrics` consumes the latter.
        if bundle.metric_snapshots:
            flags.add(METRIC_SNAPSHOTS)
            richness[METRIC_SNAPSHOTS] = {
                "n_series": len(bundle.metric_snapshots),
            }
        elif (bundle.extra or {}).get("metric_snapshots_fetchable"):
            flags.add(METRIC_SNAPSHOTS)
            richness[METRIC_SNAPSHOTS] = {"source": "data_lake_disk"}

        # MEMORY_TEXT / KG_GRAPH_MEMORY / KG_GRAPH_WINDOW ---------------------
        # These describe the OPPOSITE side of retrieval (the memory + KG),
        # not the bundle. They come from ObservationContext.
        if ctx.has_memory_text:
            flags.add(MEMORY_TEXT)
        if ctx.has_kg_graph_memory:
            flags.add(KG_GRAPH_MEMORY)
        if ctx.has_kg_graph_window:
            flags.add(KG_GRAPH_WINDOW)

        # VERIFIER_KNOWN_HELPFUL ---------------------------------------------
        if ctx.verifier_calibration.is_helpful(ctx.dataset_id):
            flags.add(VERIFIER_KNOWN_HELPFUL)
            richness[VERIFIER_KNOWN_HELPFUL] = {
                "source": "verifier_calibration.known_helpful_distributions",
            }

        return Capabilities(flags=frozenset(flags), richness=richness)


# ---------------------------------------------------------------------------
# Convenience module-level function
# ---------------------------------------------------------------------------


_default_observer = CapabilitiesObserver()


def observe(
    bundle: InputBundle,
    ctx: ObservationContext | None = None,
) -> Capabilities:
    """Module-level shortcut around `CapabilitiesObserver().observe()`.

    Convenient for tests and ad-hoc usage. Production code that may
    want to subclass should use `CapabilitiesObserver` directly.
    """
    return _default_observer.observe(bundle, ctx)
