"""Online Boutique dataset loader.

Produces `EvaluationCase`s from the locked OB layout:

    <global_dir>/
        global-triage-examples.jsonl                 # window-side features + text
        comparison/v2a-resplit/per-window-predictions.jsonl  # gold labels (per-window)

The loader is intentionally **lazy on memory**: it loads gold + windows
into memory (the dataset is ~7k rows, fits comfortably), but builds
each `EvaluationCase` with an empty `MemoryView`. Predictions-backed
skills load their JSONLs on first invocation; the agent doesn't need a
materialized memory corpus for the smoke test because retrieval was
already done at cascade time and stored in `comparison/`.

For ablations that re-rank against a *new* memory corpus, this loader
would be extended to thread the corpus through. v1 doesn't need it.
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
_DEFAULT_GOLD_SUBDIR = "v2a-resplit"
_DEFAULT_GOLD_PIPELINE = "bi_encoder_retrieval"


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_ob_cases(
    global_dir: Path | str,
    *,
    split: str = "test",
    limit: int | None = None,
    gold_subdir: str = _DEFAULT_GOLD_SUBDIR,
    gold_pipeline: str = _DEFAULT_GOLD_PIPELINE,
    dataset_label: str = "online_boutique",
    order_by_incident_time: bool = False,
) -> list[EvaluationCase]:
    """Load OB windows of one split and produce `EvaluationCase`s.

    Args:
        global_dir: dataset root (e.g.
            `data/derived/global/2026-05-25-dataset-v5-large-global`).
        split: "train" | "validation" | "test". Default "test".
        limit: optional cap (smoke test convenience).
        gold_subdir: comparison subdir under `<global_dir>/comparison/`
            to read gold from (default v2a-resplit — the canonical OB
            resplit).
        gold_pipeline: which `pipeline_name` row to read gold from. Gold
            is per-window, so any pipeline works, but pinning the name
            keeps results deterministic (default bi_encoder_retrieval).
        dataset_label: value to put in `InputBundle.dataset` (default
            "online_boutique"; "otel_demo"/"wol" for other loaders).

    Returns:
        A list of `EvaluationCase` whose memory views are empty (the
        agent's predictions-backed skills don't need a populated
        memory corpus for v1).
    """
    global_dir = Path(global_dir)
    examples_path = global_dir / "global-triage-examples.jsonl"
    gold_path = (
        global_dir / "comparison" / gold_subdir / "per-window-predictions.jsonl"
    )
    if not examples_path.exists():
        raise FileNotFoundError(f"OB triage examples missing: {examples_path}")
    if not gold_path.exists():
        raise FileNotFoundError(
            f"OB gold predictions missing: {gold_path}. "
            f"Run the v2a-resplit pipeline first or supply a different gold_subdir.",
        )

    gold_by_window = _load_gold(gold_path, gold_pipeline)
    log.info("OB loader: gold loaded for %d windows from %s",
             len(gold_by_window), gold_path)

    # Honor the v2-resplit manifest when present (overrides JSONL's split).
    manifest = load_split_manifest(global_dir)

    cases: list[EvaluationCase] = []
    sort_keys: list[tuple] = []     # parallel; only used when order_by_incident_time
    n_seen = 0
    n_kept = 0
    n_no_gold = 0

    for window in _iter_jsonl(examples_path):
        n_seen += 1
        if resolve_split(window, manifest) != split:
            continue
        window_id = window.get("window_id")
        if not window_id:
            continue

        gold = gold_by_window.get(window_id)
        if gold is None:
            n_no_gold += 1
            # Keep the case anyway — gold-less windows still flow through
            # the harness (their retrieval metrics are excluded by the
            # mean-with-filter rule).
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

    if order_by_incident_time and sort_keys:
        # Sort cases by (service, episode_id, start_time) so the StateLayer
        # sees multi-window same-incident sequences (closes C7).
        idx = sorted(range(len(cases)), key=lambda i: sort_keys[i])
        cases = [cases[i] for i in idx]
        log.info("OB loader: cases re-ordered by (service, episode, start_time)")

    log.info(
        "OB loader: scanned %d rows; kept %d (%s split); %d without gold",
        n_seen, n_kept, split, n_no_gold,
    )
    return cases


# ---------------------------------------------------------------------------
# Gold loading
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
    """Index gold labels by window_id. Pulls from the row matching
    `pipeline_name` (gold is per-window, so any pipeline's row works;
    pinning the name keeps the load deterministic)."""
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
            f"_load_gold: no rows matched pipeline_name={pipeline_name!r} in {path}. "
            f"Double-check the pipeline name; the JSONL might use a different one.",
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

    # Phase 2 ReAct: surface K8S_EVENTS capability via an extra marker
    # so `request_pod_events` can fire. The skill itself fetches the
    # actual events from disk via the data lake; the marker just tells
    # the CapabilitiesObserver "this window has a k8s capture available."
    return InputBundle(
        window_id=window["window_id"],
        dataset=dataset_label,
        text_evidence=window.get("triage_evidence_text"),
        numeric_features=numeric or None,
        # log_lines/trace_summary/k8s_events left None on purpose: the
        # cascade predictions already consumed them upstream. Phase 2
        # ReAct fetches the raw data on-demand instead.
        scenario_family=window.get("scenario_family"),
        service_name=window.get("service_name"),
        window_type=window.get("window_type"),
        extra={"k8s_events_fetchable": True},
    )


def _label_to_triage(label: str) -> str:
    """Coarse mapping from `gold_label` to the agent's triage decision space."""
    if label == "ticket_worthy":
        return "ticket_worthy"
    return "noise"


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


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
