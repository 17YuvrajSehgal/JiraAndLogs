"""CrossEncoderRetrievalPipeline — score (window, candidate) pairs with
a fine-tuned cross-encoder and emit the top-K candidates per window.

Differs from bi_encoder_retrieval: scores query+doc JOINTLY (no
precomputed doc vectors), so it captures interactions a bi-encoder
structurally cannot. Cost: ~5 ms per pair on RTX 5060.

Candidate pool: union of top-N from each L2 retriever (bi_encoder G1,
hybrid_rrf rule, logseq2vec, kg_retrieval). We don't score every
memory ticket — that would be 1008 windows × 347 tickets = 350k pairs
(too slow). The pool size is bounded at ~30-40 unique candidates per
window.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from comparison.pipelines import PipelineRunner
from comparison.schema import PipelinePrediction, PipelineResult
from loganalyzer.data.loaders import load_dataset
from loganalyzer.data.splits import iter_split
from loganalyzer.features.text import (
    build_memory_doc_text,
    build_window_query_text,
)
from loganalyzer.memory.corpus import MemoryCorpus
from memorygraph.humanized_loader import load_humanized_corpus


class CrossEncoderRetrievalPipeline(PipelineRunner):
    """Cross-encoder reranker pipeline.

    Candidate pool source: a JSONL file produced by another retriever
    pipeline (defaults to G1's bi_encoder predictions). We pool the
    top-`pool_size` ticket IDs from that file, score every pair with
    the cross-encoder, then emit the top-K by cross-encoder score.

    triage_score = sigmoid(top-1 cross-encoder logit).
    """

    name = "cross_encoder_retrieval_g2"

    def __init__(
        self,
        *,
        model_path: str = "data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/g2-crossencoder-rerank/model",
        candidate_source: str = "data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2g-final-models/g1-bienc-hard-negatives/per-window-predictions.jsonl",
        candidate_source_extras: list[str] | None = None,
        humanized_subdir: str = "bulk-20260531",
        humanized_root: str = "jira-shadow-humanized-v2",
        pool_size: int = 10,
        top_k: int = 10,
        max_chars: int = 512,
        batch_size: int = 32,
    ) -> None:
        self.model_path = model_path
        self.candidate_source = candidate_source
        # Optionally also pool candidates from additional retriever files
        # (e.g., hybrid_rrf rule top-K). Default = bi_encoder only.
        self.candidate_source_extras = candidate_source_extras or [
            "data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2c-hybrid/per-window-predictions.jsonl",
            "data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2b-logseq2vec/per-window-predictions.jsonl",
            "data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2d-kg-rulebased/per-window-predictions.jsonl",
        ]
        self.humanized_subdir = humanized_subdir
        self.humanized_root = humanized_root
        self.pool_size = pool_size
        self.top_k = top_k
        self.max_chars = max_chars
        self.batch_size = batch_size

    def _load_candidate_pool(self) -> dict[str, list[str]]:
        """For each window, build a deduplicated pool of candidate ticket IDs
        from the configured source + extras."""
        pool: dict[str, list[str]] = defaultdict(list)
        seen: dict[str, set[str]] = defaultdict(set)

        for src in [self.candidate_source] + self.candidate_source_extras:
            p = Path(src)
            if not p.exists():
                print(f"[{self.name}] candidate source missing, skipping: {src}")
                continue
            with p.open(encoding="utf-8") as fh:
                for line in fh:
                    d = json.loads(line)
                    wid = d.get("window_id")
                    top = d.get("matched_issue_ids") or []
                    for tid in top[: self.pool_size]:
                        if tid not in seen[wid]:
                            pool[wid].append(tid)
                            seen[wid].add(tid)
        return dict(pool)

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root, target_fpr
        from sentence_transformers import CrossEncoder

        t0 = time.time()

        # Load memory + windows
        ds = load_dataset(global_dir)
        test_w = list(iter_split(ds.windows, ds.split_manifest, "test"))
        memory_issues = load_humanized_corpus(
            global_dir,
            humanized_subdir=self.humanized_subdir,
            humanized_root=self.humanized_root,
        )
        corpus = MemoryCorpus(issues=memory_issues, mode="time_ordered")
        by_id = corpus.by_id()
        print(f"[{self.name}] test windows: {len(test_w)}, memory: {len(memory_issues)}")

        # Load candidate pool
        pool = self._load_candidate_pool()
        print(f"[{self.name}] candidate pool built for {len(pool)} windows")
        avg_pool = sum(len(v) for v in pool.values()) / max(1, len(pool))
        print(f"[{self.name}] avg pool size: {avg_pool:.1f} candidates/window")

        # Load fine-tuned cross-encoder
        print(f"[{self.name}] loading cross-encoder from {self.model_path}")
        model = CrossEncoder(self.model_path)

        predictions: list[PipelinePrediction] = []
        n_scored = 0

        for i, w in enumerate(test_w, 1):
            wid = w.window_id
            query = (build_window_query_text(w) or "")[: self.max_chars * 4]
            visible = corpus.visible_to(w)
            visible_ids = {iss.jira_shadow_issue_id for iss in visible}
            candidate_ids = [c for c in pool.get(wid, []) if c in visible_ids and c in by_id]

            if not candidate_ids or not query:
                # No candidates — emit empty top-K, triage 0
                predictions.append(PipelinePrediction(
                    window_id=wid,
                    pipeline_name=self.name,
                    triage_score=0.0,
                    triage_decision="noise",
                    is_novel=False,
                    matched_issue_ids=[],
                    gold_label=w.triage_label,
                    gold_is_novel=w.is_novel,
                    gold_matched_issue_ids=list(w.matched_memory_issue_ids or []),
                    gold_expected_in_memory=getattr(w, "expected_in_memory", None),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                    is_hard_case=getattr(w, "is_hard_case", False),
                    triage_reason_class=getattr(w, "triage_reason_class", None),
                ))
                continue

            # Score every (window, candidate) pair
            doc_texts = [
                (build_memory_doc_text(by_id[c]) or "")[: self.max_chars * 4]
                for c in candidate_ids
            ]
            pairs = [(query, dt) for dt in doc_texts]
            scores = model.predict(
                pairs, batch_size=self.batch_size, show_progress_bar=False,
                convert_to_numpy=True,
            )
            n_scored += len(pairs)

            # Sort by score desc
            order = np.argsort(-scores)
            top_ids = [candidate_ids[j] for j in order[: self.top_k]]
            # Sigmoid the top-1 logit → triage_score
            top1_score = float(scores[order[0]])
            triage_score = 1.0 / (1.0 + np.exp(-top1_score))

            predictions.append(PipelinePrediction(
                window_id=wid,
                pipeline_name=self.name,
                triage_score=float(triage_score),
                triage_decision="ticket_worthy" if triage_score >= 0.5 else "noise",
                is_novel=False,
                matched_issue_ids=top_ids,
                gold_label=w.triage_label,
                gold_is_novel=w.is_novel,
                gold_matched_issue_ids=list(w.matched_memory_issue_ids or []),
                gold_expected_in_memory=getattr(w, "expected_in_memory", None),
                scenario_family=w.scenario_family,
                service_name=w.service_name,
                window_type=w.window_type,
                is_hard_case=getattr(w, "is_hard_case", False),
                triage_reason_class=getattr(w, "triage_reason_class", None),
            ))

            if i % 100 == 0:
                print(f"[{self.name}] scored {i}/{len(test_w)} windows, {n_scored} pairs")

        elapsed = time.time() - t0
        print(f"[{self.name}] DONE in {elapsed:.1f}s, {n_scored} pairs scored")

        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=0.5,
            fit_seconds=0.0,
            predict_seconds=elapsed,
            metadata={
                "n_test_evaluated": len(test_w),
                "n_pairs_scored": n_scored,
                "pool_size_per_retriever": self.pool_size,
                "model_path": self.model_path,
                "candidate_sources": [self.candidate_source] + self.candidate_source_extras,
            },
        )
