"""Score-level ensembles.

Each blender takes a dict {pipeline_name -> score} for one window and
returns a single ensembled score in [0, 1]. The Ensemble*Pipeline wraps a
list of PipelineResult into a new PipelineResult so the report code
treats the ensemble as just another pipeline.

Score normalization: we min-max each input pipeline's scores across the
test set before blending. Otherwise pipelines with naturally wider score
ranges dominate a `mean` blend.
"""

from __future__ import annotations

from typing import Callable

from .schema import PipelinePrediction, PipelineResult


BlendFn = Callable[[dict[str, float]], float]


def blend_mean(per_pipeline: dict[str, float]) -> float:
    if not per_pipeline:
        return 0.0
    return sum(per_pipeline.values()) / len(per_pipeline)


def blend_max(per_pipeline: dict[str, float]) -> float:
    if not per_pipeline:
        return 0.0
    return max(per_pipeline.values())


def blend_weighted(weights: dict[str, float]) -> BlendFn:
    """Factory: returns a BlendFn that does sum(w * s) / sum(w)."""
    total_weight = sum(weights.values()) or 1.0

    def fn(per_pipeline: dict[str, float]) -> float:
        num = 0.0
        denom = 0.0
        for name, score in per_pipeline.items():
            w = weights.get(name, 0.0)
            num += w * score
            denom += w
        if denom == 0:
            return 0.0
        return num / denom

    return fn


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return values
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 1e-12:
        return [0.5] * len(values)
    return [(v - lo) / span for v in values]


def _blend_decision(blended: float, threshold: float) -> str:
    return "ticket_worthy" if blended >= threshold else "noise"


def _ensemble_retrieval(window_predictions: list[PipelinePrediction], top_k: int = 5) -> tuple[list[str], bool | None]:
    """Reciprocal-rank fusion on the matched_issue_ids lists.

    Returns (top-K issue ids, is_novel).  is_novel = AND of underlying is_novel
    decisions (if any pipeline thinks it has a match, ensemble keeps it).
    """
    scores: dict[str, float] = {}
    for pred in window_predictions:
        for rank, issue_id in enumerate(pred.matched_issue_ids, start=1):
            scores[issue_id] = scores.get(issue_id, 0.0) + 1.0 / (60 + rank)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top = [issue_id for issue_id, _ in ranked[:top_k]]
    novel_flags = [p.is_novel for p in window_predictions if p.is_novel is not None]
    if not novel_flags:
        is_novel = None
    else:
        # If any constituent pipeline found a match, the ensemble is not novel.
        is_novel = all(novel_flags)
    return top, is_novel


class EnsemblePipeline:
    """Combines several PipelineResults into a synthetic PipelineResult.

    Does not retrain anything - just blends already-scored test predictions.
    Construction is deferred: you call .from_results() AFTER the underlying
    pipelines have produced their predictions.
    """

    def __init__(
        self,
        name: str,
        blend_fn: BlendFn,
        *,
        normalize: bool = True,
        retrieval_top_k: int = 5,
    ) -> None:
        self.name = name
        self.blend_fn = blend_fn
        self.normalize = normalize
        self.retrieval_top_k = retrieval_top_k

    def from_results(
        self,
        results: list[PipelineResult],
        *,
        threshold: float = 0.5,
    ) -> PipelineResult:
        if not results:
            raise ValueError("EnsemblePipeline.from_results needs at least 1 input")

        # Normalize per-pipeline scores across the test set (optional but
        # recommended for mean blends).
        by_pipeline: dict[str, dict[str, float]] = {}
        all_window_ids: set[str] = set()
        for result in results:
            preds = result.predictions
            raw = [p.triage_score for p in preds]
            normed = _minmax(raw) if self.normalize else raw
            by_pipeline[result.pipeline_name] = {
                p.window_id: normed[i] for i, p in enumerate(preds)
            }
            all_window_ids.update(by_pipeline[result.pipeline_name].keys())

        # Build a master window -> [prediction objects] index for retrieval fusion
        per_window_predictions: dict[str, list[PipelinePrediction]] = {wid: [] for wid in all_window_ids}
        per_window_gold: dict[str, PipelinePrediction] = {}
        for result in results:
            for p in result.predictions:
                per_window_predictions[p.window_id].append(p)
                per_window_gold.setdefault(p.window_id, p)

        blended_predictions: list[PipelinePrediction] = []
        for window_id, preds_for_window in per_window_predictions.items():
            per_pipeline_scores = {
                name: by_pipeline[name].get(window_id, 0.0)
                for name in by_pipeline
                if window_id in by_pipeline[name]
            }
            blended = self.blend_fn(per_pipeline_scores)
            top_ids, is_novel = _ensemble_retrieval(
                preds_for_window, top_k=self.retrieval_top_k
            )
            ref = per_window_gold[window_id]
            blended_predictions.append(
                PipelinePrediction(
                    window_id=window_id,
                    pipeline_name=self.name,
                    triage_score=blended,
                    triage_decision=_blend_decision(blended, threshold),
                    is_novel=is_novel,
                    matched_issue_ids=top_ids,
                    gold_label=ref.gold_label,
                    gold_is_novel=ref.gold_is_novel,
                    gold_matched_issue_ids=ref.gold_matched_issue_ids,
                    scenario_family=ref.scenario_family,
                    service_name=ref.service_name,
                    window_type=ref.window_type,
                )
            )

        return PipelineResult(
            pipeline_name=self.name,
            predictions=blended_predictions,
            triage_threshold=threshold,
            metadata={
                "blend": self.blend_fn.__name__ if hasattr(self.blend_fn, "__name__") else "weighted",
                "constituent_pipelines": [r.pipeline_name for r in results],
                "normalize": self.normalize,
            },
        )


def pick_ensemble_threshold(
    blended_predictions: list[PipelinePrediction],
    val_blended_predictions: list[PipelinePrediction] | None = None,
    *,
    target_fpr: float = 0.05,
) -> float:
    """Pick an operating threshold on the validation predictions if provided,
    otherwise fall back to 0.5 (mean-blend default).
    """
    from loganalyzer.eval.metrics import precision_at_fpr  # local import

    source = val_blended_predictions or []
    if not source:
        return 0.5
    scores = [p.triage_score for p in source]
    labels = [1 if p.gold_label == "ticket_worthy" else 0 for p in source]
    if sum(labels) == 0 or sum(labels) == len(labels):
        return 0.5
    _p, _r, threshold = precision_at_fpr(scores, labels, target_fpr)
    return threshold
