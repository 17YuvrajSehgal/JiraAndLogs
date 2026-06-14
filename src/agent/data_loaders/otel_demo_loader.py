"""OpenTelemetry Demo dataset loader.

OTel Demo is the **second telemetry-rich dataset** (alongside OB) used
to argue the agent generalises across two ground-truth telemetry
sources. As of 2026-06-12 the dataset is in active collection; the
test/validation splits haven't been cut yet (only `train` is present).
This loader is ready for when the cascade has been run on it.

Layout (similar to OB but currently sparser):

    <global_dir>/
        global-triage-examples.jsonl                  # window features + text
        window-memory-matchings.jsonl                 # gold (different shape from OB)
        triage-split-manifest.json
        # comparison/<pipeline>/per-window-predictions.jsonl
        #     ← NOT YET PRESENT; populated by cascade-on-otel-demo run

Gold-source priority:
  1. `comparison/v2a-resplit/per-window-predictions.jsonl` if present
     (matches the OB convention).
  2. `window-memory-matchings.jsonl` as fallback (the raw matchings the
     cascade was built from). Field rename: `matched_memory_issue_ids`
     → `gold_matched_issue_ids`.

The loader always falls back to (2) if (1) is missing, so it works
right now on the partial dataset.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

from ..eval_harness import EvaluationCase
from ..skills.base import MemoryView
from ..types import InputBundle
from .split_manifest import load_split_manifest, resolve_split


log = logging.getLogger(__name__)


_NUMERIC_FEATURE_PREFIX = "triage_feature_"


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_otel_demo_cases(
    global_dir: Path | str,
    *,
    split: str = "test",
    limit: int | None = None,
    gold_source: str = "auto",      # "auto" | "comparison" | "matchings"
    dataset_label: str = "otel_demo",
    order_by_incident_time: bool = False,
) -> list[EvaluationCase]:
    """Load OTel Demo windows of one split.

    Args:
        global_dir: dataset root (e.g.
            `data/derived/global/2026-06-09-otel-demo-v1-global`).
        split: which split to load (default "test"). Raises with a
            clear message if no windows have that split — OTel Demo is
            still in collection so `train` may be the only choice.
        limit: cap the number of cases.
        gold_source: how to find gold labels:
            - "comparison" — read from `comparison/v2a-resplit/...`
              (cascade output; fails if not present).
            - "matchings"  — read from `window-memory-matchings.jsonl`
              (the raw matchings the cascade is built from; always
              present).
            - "auto" (default) — prefer comparison, fall back to matchings.
        dataset_label: value put into `InputBundle.dataset`. Default
            "otel_demo" — runner auto-infers evaluation_mode =
            "telemetry_diagnosis" from this.
    """
    global_dir = Path(global_dir)
    examples_path = global_dir / "global-triage-examples.jsonl"
    if not examples_path.exists():
        raise FileNotFoundError(
            f"OTel Demo triage examples missing: {examples_path}",
        )

    gold_by_window = _load_gold_with_fallback(global_dir, gold_source)
    log.info(
        "OTel Demo loader: gold loaded for %d windows",
        len(gold_by_window),
    )

    manifest = load_split_manifest(global_dir)

    cases: list[EvaluationCase] = []
    sort_keys: list[tuple] = []
    n_kept = 0
    n_no_gold = 0
    splits_seen: dict[str, int] = {}

    for window in _iter_jsonl(examples_path):
        s = resolve_split(window, manifest)
        splits_seen[s] = splits_seen.get(s, 0) + 1
        if s != split:
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
        if order_by_incident_time:
            sort_keys.append((
                str(window.get("service_name") or ""),
                str(window.get("incident_episode_id") or ""),
                str(window.get("start_time") or ""),
            ))
        n_kept += 1

        if limit is not None and n_kept >= limit:
            break

    if n_kept == 0:
        raise ValueError(
            f"OTel Demo loader: no cases found in split={split!r}. "
            f"Splits seen in the JSONL: {dict(splits_seen)}. "
            f"If the dataset is mid-collection, try split='train'.",
        )

    if order_by_incident_time and sort_keys:
        idx = sorted(range(len(cases)), key=lambda i: sort_keys[i])
        cases = [cases[i] for i in idx]
        log.info("OTel Demo loader: cases re-ordered by (service, episode, start_time)")

    log.info(
        "OTel Demo loader: kept %d cases (%s split); %d without gold",
        n_kept, split, n_no_gold,
    )
    return cases


# ---------------------------------------------------------------------------
# Gold loaders
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


def _load_gold_with_fallback(
    global_dir: Path,
    source: str,
) -> dict[str, _GoldRow]:
    comparison_path = (
        global_dir / "comparison" / "v2a-resplit" / "per-window-predictions.jsonl"
    )
    matchings_path = global_dir / "window-memory-matchings.jsonl"

    if source == "comparison":
        if not comparison_path.exists():
            raise FileNotFoundError(
                f"OTel Demo: gold_source='comparison' but {comparison_path} "
                f"doesn't exist. Run the cascade on this dataset first or "
                f"pass gold_source='matchings'.",
            )
        return _load_gold_from_comparison(comparison_path)

    if source == "matchings":
        if not matchings_path.exists():
            raise FileNotFoundError(
                f"OTel Demo: matchings file missing: {matchings_path}",
            )
        return _load_gold_from_matchings(matchings_path)

    # "auto"
    if comparison_path.exists():
        log.info("OTel Demo: using comparison gold (%s)", comparison_path)
        return _load_gold_from_comparison(comparison_path)
    if matchings_path.exists():
        log.info("OTel Demo: using matchings gold (%s)", matchings_path)
        return _load_gold_from_matchings(matchings_path)
    raise FileNotFoundError(
        f"OTel Demo: no gold source found. Expected one of "
        f"{comparison_path} or {matchings_path}.",
    )


def _load_gold_from_comparison(path: Path) -> dict[str, _GoldRow]:
    """Read gold from the cascade output (matches OB shape)."""
    pipeline_name = "bi_encoder_retrieval"           # canonical retrieval row
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
    return gold


def _load_gold_from_matchings(path: Path) -> dict[str, _GoldRow]:
    """Read gold from window-memory-matchings.jsonl.

    Key rename: `matched_memory_issue_ids` → `gold_matched_issue_ids`.
    `triage_label` is the gold label."""
    gold: dict[str, _GoldRow] = {}
    for row in _iter_jsonl(path):
        wid = row.get("window_id")
        if not wid:
            continue
        gold[wid] = _GoldRow(
            matched_issue_ids=tuple(row.get("matched_memory_issue_ids") or ()),
            is_novel=bool(row.get("is_novel", False)),
            label=str(row.get("triage_label") or "noise"),
        )
    return gold


# ---------------------------------------------------------------------------
# Bundle construction
# ---------------------------------------------------------------------------


def _build_bundle(window: dict[str, Any], *, dataset_label: str) -> InputBundle:
    numeric: dict[str, float] = {}
    for k, v in window.items():
        if k.startswith(_NUMERIC_FEATURE_PREFIX) and isinstance(v, (int, float)):
            numeric[k] = float(v)

    # Phase 2 ReAct: surface K8S_EVENTS / TRACE_SUMMARY / METRIC_SNAPSHOTS
    # capabilities via extra markers so the 4 EvidenceRequestSkills can
    # fire. The skills themselves read from disk via the data lake; the
    # markers just tell the CapabilitiesObserver "this window has a
    # <modality> capture available." Tool fetches that miss the on-disk
    # file fail gracefully (failure_mode=TOOL_ERROR per §3.6 catalog).
    # OTel Demo's data lake runs_root is `data/otel-demo-runs/`,
    # configured per-profile in agent.harness_builder.
    return InputBundle(
        window_id=window["window_id"],
        dataset=dataset_label,
        text_evidence=window.get("triage_evidence_text"),
        numeric_features=numeric or None,
        scenario_family=window.get("scenario_family"),
        service_name=window.get("service_name"),
        window_type=window.get("window_type"),
        extra={
            "k8s_events_fetchable": True,
            "trace_summary_fetchable": True,
            "metric_snapshots_fetchable": True,
        },
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
