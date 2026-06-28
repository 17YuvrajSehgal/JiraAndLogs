"""HybridRRFPipeline — SPLADE + fine-tuned BiEncoder + KG graph via RRF.

This is the headline retrieval pipeline of v2_advanced. It composes the
three retrievers from Proposals B/D/G and fuses their rankings with
Reciprocal Rank Fusion.

At fit time:
  - Load the V2 humanized memory.
  - Index every memory ticket with SPLADE (sparse) and with the
    fine-tuned BiEncoder (dense). Both produce vectors per ticket.
  - Connect to Neo4j (already loaded by Phase D).

At predict time, for each test window:
  - Build a query text from the window's evidence.
  - SPLADE top-20    (sparse retrieval over memory)
  - BiEncoder top-20 (dense)
  - Graph top-20     (Cypher over Neo4j, using LLM/rule extracted entities)
  - RRF fuse the three → top-5 final candidates

Triage head: similarity features from all three retrievers (max+mean
+ count above threshold) fed to a logistic regression.

This is a HEAVYWEIGHT pipeline: SPLADE indexing + BiEncoder indexing
+ Graph load. First fit takes ~5 minutes; predict is ~1 min for the
test split.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from comparison.pipelines import PipelineRunner
from comparison.schema import PipelinePrediction, PipelineResult
from core.data.loaders import load_dataset
from core.data.splits import iter_split
from core.features.text import build_memory_doc_text, build_window_query_text
from core.memory.corpus import MemoryCorpus
from core.eval.metrics import precision_at_fpr
from memorygraph.humanized_loader import load_humanized_corpus

from v2_advanced.shared import Neo4jClient, get_logger, log_step
from v2_advanced.shared.neo4j_client import Neo4jConfig

from v2_advanced.proposal_d_knowledge_graph.graph_retriever import GraphRetriever
from v2_advanced.proposal_d_knowledge_graph.pipeline import KnowledgeGraphRetrievalPipeline
from v2_advanced.proposal_d_knowledge_graph.extractor import extract_from_window

from .splade import SpladeRetriever
from .rrf import rrf_fuse_ids

log = get_logger("phase_c.hybrid")


class HybridRRFRetrievalPipeline(PipelineRunner):
    """SPLADE + BiEncoder + Graph via RRF fusion."""

    name = "hybrid_rrf_retrieval"

    def __init__(
        self,
        *,
        humanized_subdir: str = "bulk-20260531",
        humanized_root: str = "jira-shadow-humanized-v2",
        # SPLADE config
        splade_model: str = "naver/splade-cocondenser-ensembledistil",
        # BiEncoder config — kept identical to the standalone v3 BiEncoder
        # (run_biencoder_wol_mode3.py defaults) so the dense retriever fused
        # here is the SAME model. use_all_golds=True would explode to millions
        # of (window, gold) pairs on v3's generous coarse matching (~11h
        # fine-tune); the standalone uses one example per window.
        biencoder_backbone: str = "sentence-transformers/all-MiniLM-L6-v2",
        biencoder_finetune_epochs: int = 5,
        biencoder_finetune_batch_size: int = 32,
        biencoder_use_all_golds: bool = False,
        biencoder_n_hard_negs: int = 2,
        biencoder_n_random_negs: int = 1,
        # Graph config
        neo4j_uri: str = "neo4j://127.0.0.1:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "123456789",
        extractions_subdir: str = "v2_kg_extractions",
        # G3 (2026-06-05): optional pre-extracted window facts cache.
        window_extractions_subdir: str | None = None,
        # Fusion config
        rrf_k: float = 60.0,
        retriever_weights: dict[str, float] | None = None,
        top_k_per_retriever: int = 20,
        top_k_final: int = 5,
        # Memory config
        max_chars: int = 512,
        skip_window_extraction: bool = True,
        skip_graph: bool = False,
        seed: int = 42,
    ) -> None:
        self.humanized_subdir = humanized_subdir
        self.humanized_root = humanized_root
        self.splade_model = splade_model
        self.biencoder_backbone = biencoder_backbone
        self.biencoder_finetune_epochs = biencoder_finetune_epochs
        self.biencoder_finetune_batch_size = biencoder_finetune_batch_size
        self.biencoder_use_all_golds = biencoder_use_all_golds
        self.biencoder_n_hard_negs = biencoder_n_hard_negs
        self.biencoder_n_random_negs = biencoder_n_random_negs
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.extractions_subdir = extractions_subdir
        self.window_extractions_subdir = window_extractions_subdir
        self.rrf_k = rrf_k
        self.retriever_weights = retriever_weights or {"splade": 1.0, "biencoder": 1.0, "graph": 1.0}
        self.top_k_per_retriever = top_k_per_retriever
        self.top_k_final = top_k_final
        self.max_chars = max_chars
        self.skip_window_extraction = skip_window_extraction
        self.skip_graph = skip_graph
        self.seed = seed

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root
        import torch
        from sklearn.linear_model import LogisticRegression

        torch.manual_seed(self.seed)
        np.random.seed(self.seed)

        t_fit_start = time.time()

        # 1) Load dataset + memory
        with log_step(log, "load_dataset_and_memory"):
            ds = load_dataset(global_dir)
            train_w = list(iter_split(ds.windows, ds.split_manifest, "train"))
            val_w = list(iter_split(ds.windows, ds.split_manifest, "validation"))
            test_w = list(iter_split(ds.windows, ds.split_manifest, "test"))
            memory_issues = load_humanized_corpus(
                global_dir,
                humanized_subdir=self.humanized_subdir,
                humanized_root=self.humanized_root,
            )
            corpus = MemoryCorpus(issues=memory_issues, mode="time_ordered")
            memory_ids = [iss.jira_shadow_issue_id for iss in memory_issues]
            memory_texts = [
                (build_memory_doc_text(iss) or "")[:self.max_chars]
                for iss in memory_issues
            ]
            log.info(
                "loaded",
                train=len(train_w), val=len(val_w), test=len(test_w),
                memory=len(memory_issues),
            )

            # Optional cap on the train/val windows scored ONLY to fit the
            # triage logistic head (the score_train / score_val loops below).
            # The Hit@K test rankings come from score_test, which is NEVER
            # subsampled, so retrieval metrics are unchanged; only the triage
            # threshold sees fewer (still representative) samples. At v3 scale
            # (~61k train windows) the per-window SPLADE+graph scoring is the
            # dominant cost, so this is the lever that keeps the run tractable.
            # Set HYBRID_TRIAGE_SCORE_SAMPLE>0 to enable (default 0 = full).
            import os as _os
            import random as _rnd
            _samp = int(_os.environ.get("HYBRID_TRIAGE_SCORE_SAMPLE", "0") or "0")
            if _samp > 0:
                _r = _rnd.Random(self.seed)
                if len(train_w) > _samp:
                    train_w = _r.sample(train_w, _samp)
                _vsamp = max(1, _samp // 3)
                if len(val_w) > _vsamp:
                    val_w = _r.sample(val_w, _vsamp)
                log.info("triage-score subsample applied",
                         train=len(train_w), val=len(val_w), test=len(test_w))

        # 2) Fit BiEncoder (reuses the Phase G code path)
        with log_step(log, "fit_biencoder"):
            from neural_models.bi_encoder import BiEncoderRetrievalPipeline
            biencoder_inner = BiEncoderRetrievalPipeline(
                backbone=self.biencoder_backbone,
                humanized_subdir=self.humanized_subdir,
                humanized_root=self.humanized_root,
                finetune_epochs=self.biencoder_finetune_epochs,
                finetune_batch_size=self.biencoder_finetune_batch_size,
                top_k=self.top_k_per_retriever,
                max_chars=self.max_chars,
                seed=self.seed,
                use_all_golds=self.biencoder_use_all_golds,
                n_hard_negs=self.biencoder_n_hard_negs,
                n_random_negs=self.biencoder_n_random_negs,
            )
            # Run BiEncoder pipeline up to its predict step; we want both
            # its top-K rankings AND its similarity features for triage.
            biencoder_result = biencoder_inner.train_and_predict(
                global_dir, Path("data/runs"), target_fpr=target_fpr,
            )
            biencoder_rankings_by_window = {
                p.window_id: p.matched_issue_ids for p in biencoder_result.predictions
            }
            biencoder_scores_by_window = {
                p.window_id: float(p.triage_score) for p in biencoder_result.predictions
            }
            log.info("biencoder ready", n_windows=len(biencoder_rankings_by_window))

        # 3) Fit SPLADE
        splade = SpladeRetriever(model_name=self.splade_model)
        with log_step(log, "fit_splade"):
            splade.fit(memory_ids, memory_texts)

        # 4) Connect to Neo4j (graph already loaded by Phase D)
        neo_cfg = Neo4jConfig(uri=self.neo4j_uri, user=self.neo4j_user, password=self.neo4j_password)
        neo_client = None
        graph_retriever = None
        if not self.skip_graph:
            try:
                neo_client = Neo4jClient(neo_cfg)
                neo_client.__enter__()
                # Check the graph is loaded
                n_inc = neo_client.count("Incident")
                if n_inc == 0:
                    log.warning("Neo4j has zero Incidents — graph not loaded; skipping graph retriever")
                    neo_client.__exit__(None, None, None)
                    neo_client = None
                else:
                    log.info("graph ready", n_incidents=n_inc)
                    graph_retriever = GraphRetriever(neo_client)
            except Exception as e:
                log.warning("neo4j unavailable; skipping graph retriever", err=str(e)[:120])
                neo_client = None

        # 5) Per-window scoring
        def visible_set(w):
            return {iss.jira_shadow_issue_id for iss in corpus.visible_to(w)}

        def query_text(w):
            return (build_window_query_text(w) or "")[:self.max_chars]

        kg_pipeline_helper = KnowledgeGraphRetrievalPipeline(
            humanized_subdir=self.humanized_subdir, humanized_root=self.humanized_root,
            skip_window_extraction=self.skip_window_extraction,
            window_extractions_subdir=self.window_extractions_subdir,
        )

        def retrieve_three(w) -> dict[str, list[str]]:
            qt = query_text(w)
            vis = visible_set(w)
            # SPLADE
            splade_ids = splade.retrieve_ids(qt, top_k=self.top_k_per_retriever, visible_doc_ids=vis)
            # BiEncoder (precomputed during fit_biencoder)
            be_ids = biencoder_rankings_by_window.get(w.window_id, [])
            be_ids = [d for d in be_ids if d in vis][:self.top_k_per_retriever]
            # Graph
            if graph_retriever is not None:
                ext = kg_pipeline_helper._extract_window(w, None, global_dir / self.extractions_subdir)
                graph_rows = graph_retriever.retrieve(ext, top_k=self.top_k_per_retriever)
                graph_ids = [r["ticket_id"] for r in graph_rows if r["ticket_id"] in vis]
            else:
                graph_ids = []
            return {"splade": splade_ids, "biencoder": be_ids, "graph": graph_ids}

        def feats_from_three(rankings: dict[str, list[str]], be_score: float) -> list[float]:
            # Feature vector for triage logistic head:
            #   n_unique_in_fused_top_10
            #   max_overlap_between_lists (how often does a doc appear in ≥2 lists)
            #   biencoder triage score (carried through)
            all_ids = [d for lst in rankings.values() for d in lst]
            unique = len(set(all_ids[:30]))
            from collections import Counter
            c = Counter(all_ids)
            shared = sum(1 for _, v in c.items() if v >= 2)
            return [float(unique), float(shared), be_score]

        with log_step(log, "score_train", n=len(train_w)):
            train_feats = []
            train_y = []
            for w in train_w:
                rankings = retrieve_three(w)
                be_score = biencoder_scores_by_window.get(w.window_id, 0.0)
                train_feats.append(feats_from_three(rankings, be_score))
                train_y.append(1 if w.triage_label == "ticket_worthy" else 0)
            train_feats = np.asarray(train_feats, dtype=np.float32)

        with log_step(log, "score_val", n=len(val_w)):
            val_feats = []
            val_y = []
            for w in val_w:
                rankings = retrieve_three(w)
                be_score = biencoder_scores_by_window.get(w.window_id, 0.0)
                val_feats.append(feats_from_three(rankings, be_score))
                val_y.append(1 if w.triage_label == "ticket_worthy" else 0)
            val_feats = np.asarray(val_feats, dtype=np.float32)

        with log_step(log, "score_test", n=len(test_w)):
            test_feats = []
            test_rankings = []
            for w in test_w:
                rankings = retrieve_three(w)
                be_score = biencoder_scores_by_window.get(w.window_id, 0.0)
                test_feats.append(feats_from_three(rankings, be_score))
                fused = rrf_fuse_ids(
                    rankings, k=self.rrf_k, weights=self.retriever_weights,
                    top_k=self.top_k_final,
                )
                test_rankings.append(fused)
            test_feats = np.asarray(test_feats, dtype=np.float32)

        # 6) Triage head
        with log_step(log, "fit_triage_head"):
            if len(set(train_y)) < 2:
                threshold = 0.5
                test_scores = [0.5] * len(test_w)
            else:
                clf = LogisticRegression(
                    class_weight="balanced", max_iter=2000, solver="lbfgs",
                ).fit(train_feats, train_y)
                if val_w:
                    val_scores = [float(p[1]) for p in clf.predict_proba(val_feats)]
                    _p, _r, threshold = precision_at_fpr(val_scores, val_y, target_fpr)
                else:
                    threshold = 0.5
                test_scores = [float(p[1]) for p in clf.predict_proba(test_feats)]

        if neo_client is not None:
            neo_client.__exit__(None, None, None)

        fit_seconds = time.time() - t_fit_start

        # 7) Build predictions
        t_predict_start = time.time()
        predictions = []
        for i, w in enumerate(test_w):
            score = float(test_scores[i])
            top_ids = test_rankings[i]
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=score,
                    triage_decision="ticket_worthy" if score >= threshold else "noise",
                    is_novel=(len(top_ids) == 0),
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
                )
            )
        predict_seconds = time.time() - t_predict_start

        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={
                "train_n": len(train_w),
                "val_n": len(val_w),
                "test_n": len(test_w),
                "n_memory": len(memory_issues),
                "rrf_k": self.rrf_k,
                "retriever_weights": self.retriever_weights,
                "splade_model": self.splade_model,
                "biencoder_backbone": self.biencoder_backbone,
                "graph_enabled": graph_retriever is not None,
                "retrieval": "hybrid_rrf",
            },
        )
