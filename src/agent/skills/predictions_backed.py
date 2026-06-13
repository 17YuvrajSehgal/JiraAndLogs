"""PredictionsBackedSkill — wraps a cascade pipeline's cached predictions.

The cascade pipelines (HGB, BiEncoder, LogSeq2Vec, Hybrid-RRF,
KG-Retrieval, DiagnosisAgent) all emit `per-window-predictions.jsonl`
files. Each line is one window's prediction:

    {
        "window_id": "...",
        "pipeline_name": "bi_encoder_retrieval",
        "triage_score": 0.87,
        "triage_decision": "ticket_worthy" | "noise",
        "matched_issue_ids": ["PROJ-1", ...],
        "is_novel": false,
        "gold_label": "...",
        "gold_matched_issue_ids": [...],
        ...
    }

A PredictionsBackedSkill reads one of these files once at construction
and serves bundles by `window_id` lookup. This means:

  - Per-invoke cost is O(1) hash-table lookup (skill is "cheap" at
    invoke time even when its underlying model is expensive).
  - The same predictions feed every ablation — ablating a skill just
    means dropping it from the registry; non-ablated skills hit the
    cached predictions identically.
  - The agent's eval-loop wall-time is dominated by the controller +
    composition logic, not model inference.

Live-model variants (a skill that drives the underlying model
per-bundle for the v3 ReAct loop) are an extension point: subclass
this and override `invoke()` to call the model instead of looking up.

Predictions are loaded lazily on the first `invoke()` so constructing
many skills (the full registry) is cheap even if some predictions
never get used (e.g. an ablation that disables that skill).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from .base import AgentContext, MemoryView, Skill, make_cost
from ..types import InputBundle, SkillOutput

log = logging.getLogger(__name__)


class PredictionsNotFoundError(FileNotFoundError):
    """Raised when a PredictionsBackedSkill can't find its JSONL file.

    Distinct from a "this window has no prediction" miss — the file
    itself is missing, which is a configuration error the runner
    should surface clearly."""


class PredictionsBackedSkill(Skill):
    """Skill whose underlying model has already been run; predictions
    are cached on disk as a `per-window-predictions.jsonl`.

    Subclasses set:
        - `name`, `version`, `required_flags`, `cost_class`
          (the usual Skill class-attrs)
        - `predictions_pipeline_name` — the value of `pipeline_name`
          in the JSONL records that belong to this skill. Each pipeline
          can write multiple rows per window with different
          `pipeline_name` values (e.g. v2c-hybrid.jsonl contains BOTH
          `hybrid_rrf_retrieval_rule` and `hybrid_rrf_no_graph`).

    Construction takes the `predictions_path` (path to the JSONL).
    Default convention: `<global_dir>/comparison/<predictions_subdir>/
    per-window-predictions.jsonl`. The factory function
    `from_global_dir(...)` produces these by convention.
    """

    # Intermediate base — concrete subclasses set their own `name`.
    __intermediate_base__: bool = True

    #: The `pipeline_name` value to filter on within the JSONL.
    predictions_pipeline_name: str = ""

    #: Subdirectory under `<global_dir>/comparison/` where the
    #: per-window-predictions.jsonl lives. e.g. "v2a-resplit",
    #: "v2c-hybrid", "v2d-kg-rulebased". Subclasses set this so the
    #: factory `from_global_dir` can locate the file.
    predictions_subdir: str = ""

    def __init__(
        self,
        predictions_path: Path | str | None = None,
        *,
        skill_version: str | None = None,
    ) -> None:
        if predictions_path is None:
            raise ValueError(
                f"{type(self).__name__}: predictions_path is required. "
                f"Construct via {type(self).__name__}.from_global_dir(global_dir) "
                f"or supply an explicit path.",
            )
        self.predictions_path = Path(predictions_path)
        # Allow per-instance version override (Phase 1.5 ablation hook —
        # e.g. comparing two BiEncoder fine-tunes).
        if skill_version is not None:
            self.version = skill_version

        self._predictions: dict[str, dict] = {}
        self._loaded = False
        self._load_lock = threading.Lock()

    # ------------------------------------------------------------------ factory

    @classmethod
    def from_global_dir(
        cls,
        global_dir: Path | str,
        *,
        predictions_path: Path | str | None = None,
        skill_version: str | None = None,
    ) -> "PredictionsBackedSkill":
        """Construct from a dataset's `global_dir`, using class convention.

        `predictions_path` defaults to
            `<global_dir>/comparison/<predictions_subdir>/per-window-predictions.jsonl`
        and can be overridden explicitly (for tests / non-standard layouts).
        """
        if predictions_path is None:
            if not cls.predictions_subdir:
                raise ValueError(
                    f"{cls.__name__}: no `predictions_subdir` class attr "
                    f"defined; supply predictions_path explicitly.",
                )
            predictions_path = (
                Path(global_dir) / "comparison" / cls.predictions_subdir
                / "per-window-predictions.jsonl"
            )
        return cls(predictions_path=predictions_path, skill_version=skill_version)

    # ------------------------------------------------------------------ load

    def _ensure_loaded(self) -> None:
        """Load predictions JSONL on first use. Thread-safe + idempotent."""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            if not self.predictions_path.exists():
                raise PredictionsNotFoundError(
                    f"{self.name}: predictions JSONL missing at "
                    f"{self.predictions_path}. Run the upstream "
                    f"pipeline first (or pass --skip-skill {self.name}).",
                )
            n_total = 0
            n_kept = 0
            with self.predictions_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    n_total += 1
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        log.warning(
                            "%s: skipping malformed line in %s",
                            self.name, self.predictions_path,
                        )
                        continue
                    if (
                        self.predictions_pipeline_name
                        and d.get("pipeline_name") != self.predictions_pipeline_name
                    ):
                        continue
                    window_id = d.get("window_id")
                    if not window_id:
                        continue
                    self._predictions[window_id] = d
                    n_kept += 1
            log.info(
                "%s: loaded %d/%d predictions from %s (filter=%r)",
                self.name, n_kept, n_total, self.predictions_path,
                self.predictions_pipeline_name or "<any>",
            )
            self._loaded = True

    # ------------------------------------------------------------------ invoke

    def invoke(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        ctx: AgentContext,
    ) -> SkillOutput:
        self._ensure_loaded()
        pred = self._predictions.get(bundle.window_id)
        if pred is None:
            # No prediction for this window. Return empty output; runner
            # records it as a normal skill_end event with empty matches.
            return SkillOutput(
                skill=self.name,
                skill_version=self.version,
                triage_score=None,
                triage_decision=None,
                matched_issue_ids=(),
                is_novel=None,
                confidence=0.0,
                evidence_used=tuple(sorted(self.required_flags)),
                cost=make_cost(llm_tokens=0, wall_seconds=0.0, n_calls=1),
                extra={"prediction_missing": True},
            )
        return self._build_output(pred)

    def _build_output(self, pred: dict[str, Any]) -> SkillOutput:
        """Translate one prediction record into a SkillOutput. Subclasses
        may override to extract additional skill-specific fields into
        `extra`."""
        triage_score = pred.get("triage_score")
        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            triage_score=float(triage_score) if triage_score is not None else None,
            triage_decision=pred.get("triage_decision"),
            matched_issue_ids=tuple(pred.get("matched_issue_ids") or ()),
            is_novel=pred.get("is_novel"),
            confidence=float(triage_score) if triage_score is not None else 0.0,
            evidence_used=tuple(sorted(self.required_flags)),
            cost=make_cost(llm_tokens=0, wall_seconds=0.0, n_calls=1),
            extra={
                k: v for k, v in pred.items()
                if k in ("gold_label", "gold_matched_issue_ids", "gold_is_novel",
                         "scenario_family", "service_name", "window_type",
                         "is_hard_case", "triage_reason_class")
            },
        )

    # ------------------------------------------------------------------ debug

    def n_predictions_loaded(self) -> int:
        if not self._loaded:
            return 0
        return len(self._predictions)
