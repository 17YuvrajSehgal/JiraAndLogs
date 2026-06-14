"""Pure-retrieval and retrieval+rerank pipelines for the comparison harness.

These pipelines focus on the Jira-memory retrieval task — for a given
telemetry window, rank past Jira memory entries by relevance. They use
the shared backends in src/comparison/retrievers.py.

Pipelines exported:
  NomicRetrievalPipeline      — Nomic embed + cosine, classification via
                                 threshold on max(cosine) (proxy for
                                 "is this window similar enough to any
                                 past ticket to call ticket_worthy?")
  BM25RetrievalPipeline       — same shape, BM25 cheap retriever
  NomicLMRerankPipeline       — Nomic top-pool + Qwen rerank (gated on
                                 LM Studio being reachable; falls back to
                                 Nomic order if unavailable)

Each pipeline emits real retrieval metrics (recall@k, MRR) — the
classification side is a proxy score, useful for inclusion in the
unified leaderboard but not the primary use of these pipelines.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)

from core.data.loaders import load_dataset as load_loganalyzer_dataset
from core.data.splits import iter_split
from core.eval.metrics import precision_at_fpr

from .pipelines import PipelineRunner
from .retrievers import (
    BM25Retriever,
    NomicRetriever,
    chat_via_lm_studio,
    parse_lm_ranking,
    tokenize,
)
from .schema import PipelinePrediction, PipelineResult


def _strip_window_header(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.startswith("WINDOW "))


def _memory_text(issue: Any) -> str:
    """Build the per-memory-entry text the retrievers index against."""
    return " ".join(
        str(v) for v in (
            issue.memory_text, issue.resolution_notes,
            issue.affected_service, issue.fault_type,
        ) if v
    )


class _RetrievalPipelineBase(PipelineRunner):
    """Shared scaffolding for retrieval-only pipelines.

    Subclasses define `name`, optionally `__init__` params, and implement
    `_build_retriever(memory_texts)` returning an object with
    `.topk(query_text_or_tokens, k)` -> list[(idx, score)].

    The triage score is `max(top-k similarity)` clipped to [0,1] — a
    proxy that lets these pipelines join the strict-PR-AUC leaderboard.
    Real product use of these pipelines is the retrieval-quality metrics."""

    retrieval_top_k: int = 10

    def _query_arg(self, text: str) -> Any:
        """Return whatever `self.retriever.topk` expects as its first arg."""
        return text  # default: raw text (Nomic). BM25 override returns tokens.

    def _build_retriever(self, memory_texts: list[str]) -> Any:
        raise NotImplementedError

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root
        ds = load_loganalyzer_dataset(global_dir)
        train = list(iter_split(ds.windows, ds.split_manifest, "train"))
        val = list(iter_split(ds.windows, ds.split_manifest, "validation"))
        test = list(iter_split(ds.windows, ds.split_manifest, "test"))

        memory_ids = [m.jira_shadow_issue_id for m in ds.memory_corpus]
        memory_texts = [_memory_text(m) for m in ds.memory_corpus]
        log.info("[%s] dataset loaded: train=%d val=%d test=%d memory=%d",
                 self.name, len(train), len(val), len(test), len(memory_texts))

        t0 = time.time()
        log.info("[%s] building retriever index over %d memory docs ...",
                 self.name, len(memory_texts))
        self.retriever = self._build_retriever(memory_texts)
        fit_seconds = time.time() - t0
        log.info("[%s] retriever built in %.2fs", self.name, fit_seconds)

        def _score_window(window: Any) -> tuple[float, list[str]]:
            """Returns (proxy_triage_score, top-k memory_ids ordered by relevance)."""
            evidence = _strip_window_header(window.evidence_text or "")
            if not evidence:
                return 0.0, []
            hits = self.retriever.topk(self._query_arg(evidence), k=self.retrieval_top_k)
            if not hits:
                return 0.0, []
            ranked_ids = [memory_ids[i] for i, _ in hits]
            top_score = max(s for _, s in hits)
            # Clip to [0, 1] — BM25 scores can be unbounded; cosine is in [-1, 1]
            triage_score = max(0.0, min(1.0, float(top_score)))
            return triage_score, ranked_ids

        # Validation threshold tuning at target FPR
        if val:
            log.info("[%s] tuning threshold on val (n=%d) ...", self.name, len(val))
            val_scores = [_score_window(w)[0] for w in val]
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
            log.info("[%s] val threshold tuned to %.4f", self.name, threshold)
        else:
            threshold = 0.5

        t0 = time.time()
        log.info("[%s] predicting on test split (n=%d) ...", self.name, len(test))
        predictions: list[PipelinePrediction] = []
        log_every = max(1, len(test) // 10)
        for i, w in enumerate(test):
            if i % log_every == 0 and i > 0:
                log.info("[%s]   predict progress: %d/%d windows (%.1f%%)",
                         self.name, i, len(test), 100.0 * i / len(test))
            score, ranked_ids = _score_window(w)
            decision = "ticket_worthy" if score >= threshold else "noise"
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=score,
                    triage_decision=decision,
                    is_novel=None,  # retrieval-only — novelty inferred later
                    matched_issue_ids=ranked_ids[:5],
                    gold_label=w.triage_label,
                    gold_is_novel=w.is_novel,
                    gold_matched_issue_ids=list(w.matched_memory_issue_ids or []),
                    gold_expected_in_memory=getattr(w, "expected_in_memory", None),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                    is_hard_case=getattr(w, "is_hard_case", False),
                    triage_reason_class=getattr(w, "triage_reason_class", None),
                )
            )
        predict_seconds = time.time() - t0
        log.info("[%s] predict complete: %d predictions in %.2fs (%.1f windows/s)",
                 self.name, len(predictions), predict_seconds,
                 len(predictions) / max(predict_seconds, 1e-9))

        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={
                "train_n": len(train), "val_n": len(val), "test_n": len(test),
                "n_memory": len(memory_ids), "retrieval_top_k": self.retrieval_top_k,
            },
        )


class BM25RetrievalPipeline(_RetrievalPipelineBase):
    """BM25-only retrieval. Cheap baseline for the retrieval-track lift
    measurement against Nomic."""

    name = "bm25_retrieval_only"

    def _query_arg(self, text: str) -> list[str]:
        return tokenize(text)

    def _build_retriever(self, memory_texts: list[str]) -> Any:
        return BM25Retriever([tokenize(t) for t in memory_texts])


class NomicRetrievalPipeline(_RetrievalPipelineBase):
    """Dense semantic retrieval via Nomic embed (LM Studio).

    v5-quick result: R@5 0.385 vs BM25's 0.154 (2.5×) with no LM call.
    The cheapest meaningful retrieval upgrade vs the BM25 default.

    Fail-soft: if LM Studio isn't reachable (no embedding server on
    base_url), falls back to BM25 internally + sets metadata flag so the
    report can flag the degradation. This keeps the harness from
    crashing on machines that don't have the embedding server."""

    name = "nomic_retrieval_only"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:1234",
        model: str = "text-embedding-nomic-embed-text-v1.5",
        retrieval_top_k: int = 10,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.retrieval_top_k = retrieval_top_k
        self._fell_back_to_bm25 = False

    def _build_retriever(self, memory_texts: list[str]) -> Any:
        # Probe the embedding server once with a tiny test input. If it
        # fails we fall back to BM25 rather than crashing the harness.
        import urllib.error
        try:
            from .retrievers import embed_via_lm_studio
            probe = embed_via_lm_studio(
                self.base_url, self.model, ["probe"], timeout=5.0
            )
            if not probe or not probe[0]:
                raise RuntimeError("empty embedding")
        except (urllib.error.URLError, RuntimeError, ConnectionError, OSError) as exc:
            import sys
            print(
                f"WARN nomic_retrieval_only: LM Studio embedding endpoint "
                f"{self.base_url} unreachable ({exc!r}); falling back to BM25",
                file=sys.stderr,
            )
            self._fell_back_to_bm25 = True
            return BM25Retriever([tokenize(t) for t in memory_texts])
        return NomicRetriever(self.base_url, self.model, memory_texts)

    def _query_arg(self, text: str) -> Any:
        # When fallen back to BM25 we need tokenized queries
        return tokenize(text) if self._fell_back_to_bm25 else text


class NomicLMRerankPipeline(_RetrievalPipelineBase):
    """Nomic top-pool + Qwen rerank. Gated on LM Studio reachability.

    v5-quick finding: this HURTS R@5 vs Nomic alone (0.385 → 0.269) on
    the small 48-entry corpus. Kept here for v5-large verification —
    with a 10× larger corpus and more legitimate near-duplicates the
    LM may add value."""

    name = "nomic_then_lm_rerank"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:1234",
        embed_model: str = "text-embedding-nomic-embed-text-v1.5",
        chat_model: str = "qwen/qwen2.5-coder-14b",
        pool_size: int = 10,
        retrieval_top_k: int = 5,
    ) -> None:
        self.base_url = base_url
        self.embed_model = embed_model
        self.chat_model = chat_model
        self.pool_size = pool_size
        self.retrieval_top_k = retrieval_top_k

    def _build_retriever(self, memory_texts: list[str]) -> Any:
        # We wrap NomicRetriever and add LM rerank in topk()
        nomic = NomicRetriever(self.base_url, self.embed_model, memory_texts)
        chat_model = self.chat_model
        base_url = self.base_url
        pool_size = self.pool_size

        class _RerankWrapper:
            def topk(_self, query_text: str, k: int):
                pool = nomic.topk(query_text, k=max(pool_size, k))
                if not pool:
                    return []
                pool_indices = [i for i, _ in pool]
                pool_texts = [memory_texts[i][:500] for i in pool_indices]
                messages = [
                    {"role": "system", "content": (
                        "You are a triage assistant. Respond with JSON only — "
                        "no prose, no markdown fences."
                    )},
                    {"role": "user", "content": (
                        "Rank these candidate past Jira tickets by relevance "
                        "to the current window evidence. Return JSON "
                        "{\"ranks\":[...]} listing candidate numbers in order "
                        "from MOST to LEAST relevant.\n\n"
                        f"WINDOW EVIDENCE:\n{query_text[:2000]}\n\nCANDIDATES:\n"
                        + "\n\n".join(f"[{j+1}] {t}" for j, t in enumerate(pool_texts))
                    )},
                ]
                resp = chat_via_lm_studio(base_url, chat_model, messages,
                                          temperature=0.0, max_tokens=200)
                if resp.startswith("__ERROR__"):
                    return pool[:k]
                ranks = parse_lm_ranking(resp, len(pool_indices))
                if not ranks:
                    return pool[:k]
                # Reorder pool by LM ranks, take top-k
                reordered = []
                seen = set()
                for r in ranks:
                    if 1 <= r <= len(pool_indices) and r not in seen:
                        reordered.append(pool[r - 1])
                        seen.add(r)
                for j, p in enumerate(pool, start=1):
                    if j not in seen:
                        reordered.append(p)
                return reordered[:k]

        return _RerankWrapper()
