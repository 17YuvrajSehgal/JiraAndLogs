"""World of Logs (WoL / Apache Jira) dataset loader.

WoL is the **text-retrieval generalisation** dataset (`evaluation_mode =
"text_retrieval_generalisation"`). Bundles intentionally drop the
telemetry-side fields that OB carries:

  - no `numeric_features` (no Prometheus / k8s instrumentation)
  - no ordered `log_lines` (log quotes are unordered fragments)
  - no `trace_summary` / `k8s_events` / `metric_snapshots`

These omissions are what makes the agent's capability-adaptive design
visible: the same RuleController emits a plan WITHOUT triage_numeric,
retrieve_log_sequence, and verify_with_llm — closing RQ-A8
structurally (the verifier is `known_harmful` for WoL per Mode 3 §3.9).

WoL layout differs from OB:
  <global_dir>/
      global-triage-examples.jsonl              # window features + text
      tch-lite-refit/
          biencoder-predictions.jsonl           # one per retriever
          hybrid-rrf-predictions.jsonl
          logseq2vec-predictions.jsonl
          kg-retrieval-predictions.jsonl
          diagnosis-agent-predictions.jsonl

Pipeline-name conventions also differ (WoL uses plain
`logseq2vec_retrieval` / `kg_retrieval` vs OB's
`logseq2vec_retrieval_pretrained` / `kg_retrieval_rulebased`); callers
must thread per-instance overrides through.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

from ..eval_harness import EvaluationCase
from ..skills.base import MemoryView
from ..types import InputBundle


log = logging.getLogger(__name__)


_DEFAULT_GOLD_PREDS = "biencoder-predictions.jsonl"
_DEFAULT_GOLD_PIPELINE = "bi_encoder_retrieval"


# ---------------------------------------------------------------------------
# Per-retriever predictions JSONL paths (used by the smoke script)
# ---------------------------------------------------------------------------

#: Mapping from agent skill name → (filename under tch-lite-refit/,
#: pipeline_name string the JSONL uses). The smoke script consults this
#: to build per-skill instances with the right WoL-specific overrides.
WOL_PREDICTIONS_PATHS: dict[str, tuple[str, str]] = {
    "retrieve_dense":              ("biencoder-predictions.jsonl",        "bi_encoder_retrieval"),
    "retrieve_log_sequence":       ("logseq2vec-predictions.jsonl",       "logseq2vec_retrieval"),
    "retrieve_hybrid_fusion":      ("hybrid-rrf-predictions.jsonl",       "hybrid_rrf_retrieval"),
    "retrieve_knowledge_graph":    ("kg-retrieval-predictions.jsonl",     "kg_retrieval"),
    "verify_with_llm":             ("diagnosis-agent-predictions.jsonl",  "diagnosis_agent"),
}


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_wol_cases(
    global_dir: Path | str,
    *,
    split: str = "test",
    limit: int | None = None,
    gold_filename: str = _DEFAULT_GOLD_PREDS,
    gold_pipeline: str = _DEFAULT_GOLD_PIPELINE,
    dataset_label: str = "wol",
) -> list[EvaluationCase]:
    """Load WoL windows of one split and produce `EvaluationCase`s.

    Bundles deliberately have:
      - text_evidence (from `triage_evidence_text` — the log quote block)
      - service_name / scenario_family / window_type (used by suppression)

    And deliberately do NOT have:
      - numeric_features (WoL has no Prometheus telemetry)
      - log_lines (WoL `log_quotes` are unordered fragments; surfacing
        them would unlock ORDERED_LOGS, which the capabilities observer
        would set, which would let retrieve_log_sequence fire — but
        the underlying retriever was trained on OB-style streams).
        UNORDERED_LOGS *would* be the right flag; v2 wires it.

    Args:
        global_dir: WoL dataset root (e.g.
            `data/derived/global/2026-06-11-wol-real-global`).
        split: "train" | "validation" | "test" (default "test").
        limit: optional cap (smoke convenience).
        gold_filename: predictions JSONL under `tch-lite-refit/` to pull
            gold from. Default biencoder; any of the 5 works (gold is
            per-window, not per-retriever).
        gold_pipeline: `pipeline_name` value to filter on within that
            JSONL. Defaults to `bi_encoder_retrieval`.
        dataset_label: value put into `InputBundle.dataset`. Default
            "wol" — recognised by the runner's evaluation_mode inference.

    Returns:
        `EvaluationCase` list with empty MemoryViews (the predictions
        are pre-cached; v1 doesn't need a populated corpus).
    """
    global_dir = Path(global_dir)
    examples_path = global_dir / "global-triage-examples.jsonl"
    gold_path = global_dir / "tch-lite-refit" / gold_filename
    if not examples_path.exists():
        raise FileNotFoundError(f"WoL triage examples missing: {examples_path}")
    if not gold_path.exists():
        raise FileNotFoundError(
            f"WoL gold predictions missing: {gold_path}. "
            f"Run the WoL TCH-lite refit pipeline first.",
        )

    gold_by_window = _load_gold(gold_path, gold_pipeline)
    log.info("WoL loader: gold loaded for %d windows from %s",
             len(gold_by_window), gold_path)

    cases: list[EvaluationCase] = []
    n_kept = 0
    n_no_gold = 0

    for window in _iter_jsonl(examples_path):
        if window.get("split") != split:
            continue
        window_id = window.get("window_id")
        if not window_id:
            continue

        gold = gold_by_window.get(window_id)
        if gold is None:
            n_no_gold += 1
            gold = _GoldRow(matched_issue_ids=(), is_novel=False, label="noise")

        bundle = _build_bundle(window, dataset_label=dataset_label)
        case = EvaluationCase(
            bundle=bundle,
            memory=MemoryView([]),
            gold_matched_issue_ids=gold.matched_issue_ids,
            gold_is_novel=gold.is_novel,
            gold_triage=_label_to_triage(gold.label),
        )
        cases.append(case)
        n_kept += 1

        if limit is not None and n_kept >= limit:
            break

    log.info(
        "WoL loader: kept %d cases (%s split); %d without gold",
        n_kept, split, n_no_gold,
    )
    return cases


# ---------------------------------------------------------------------------
# Gold loading (shared shape with OB loader, separated for clarity)
# ---------------------------------------------------------------------------


class _GoldRow:
    __slots__ = ("matched_issue_ids", "is_novel", "label")

    def __init__(
        self,
        *,
        matched_issue_ids: tuple[str, ...],
        is_novel: bool,
        label: str,
    ) -> None:
        self.matched_issue_ids = matched_issue_ids
        self.is_novel = is_novel
        self.label = label


def _load_gold(path: Path, pipeline_name: str) -> dict[str, _GoldRow]:
    gold: dict[str, _GoldRow] = {}
    for row in _iter_jsonl(path):
        if row.get("pipeline_name") != pipeline_name:
            continue
        wid = row.get("window_id")
        if not wid:
            continue
        gold[wid] = _GoldRow(
            matched_issue_ids=tuple(row.get("gold_matched_issue_ids") or ()),
            is_novel=bool(row.get("gold_is_novel", False)),
            label=str(row.get("gold_label") or "noise"),
        )
    if not gold:
        raise ValueError(
            f"_load_gold: no rows matched pipeline_name={pipeline_name!r} in {path}.",
        )
    return gold


# ---------------------------------------------------------------------------
# Bundle construction
# ---------------------------------------------------------------------------


def _build_bundle(window: dict[str, Any], *, dataset_label: str) -> InputBundle:
    """Build a WoL bundle — deliberately TEXT-only.

    We do NOT thread numeric_features (the columns are all-zero on WoL
    and would falsely unlock NUMERIC_FEATURES) or log_lines (unordered
    fragments would need a UNORDERED_LOGS path, deferred to v2).
    """
    return InputBundle(
        window_id=window["window_id"],
        dataset=dataset_label,
        text_evidence=window.get("triage_evidence_text"),
        numeric_features=None,
        log_lines=None,
        scenario_family=window.get("scenario_family"),
        service_name=window.get("service_name"),
        window_type=window.get("window_type"),
    )


def _label_to_triage(label: str) -> str:
    if label == "ticket_worthy":
        return "ticket_worthy"
    return "noise"


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                log.warning("skipping malformed line in %s: %s", path, e)
                continue
