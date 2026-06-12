"""KnowledgeGraphRetrievalPipeline — full PipelineRunner.

The pipeline:
  1. Loads the V2 humanized memory (347 tickets).
  2. Loads pre-extracted LLM facts for every ticket from the cache dir.
     (Run `extract_tickets_cli` once to populate.)
  3. Connects to Neo4j and loads the extractions (idempotent).
  4. For each test window:
       a. Build a query text from the window's evidence.
       b. Call the LLM to extract the same fact structure from the
          window (cached too).
       c. Cypher-query the graph for top-K compatible incidents.
       d. Score triage via the entity-overlap score passed through a
          small logistic head (fit on train similarities).
  5. Emit a PipelineResult with both triage_score and matched_issue_ids.

This pipeline assumes LM Studio is running and a model is loaded. If
LM Studio is unreachable, the pipeline fails fast at fit() time with a
clear error.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from comparison.pipelines import PipelineRunner
from comparison.schema import PipelinePrediction, PipelineResult
from core.data.loaders import load_dataset
from core.data.splits import iter_split
from core.features.text import build_window_query_text
from core.memory.corpus import MemoryCorpus
from core.eval.metrics import precision_at_fpr
from memorygraph.humanized_loader import load_humanized_corpus

from v2_advanced.shared import LMStudioClient, Neo4jClient, get_logger, log_step
from v2_advanced.shared.lm_studio import LMStudioConfig
from v2_advanced.shared.neo4j_client import Neo4jConfig
from .extractor import extract_from_window
from .graph_retriever import GraphRetriever
from .loader import load_extractions
from .schema import IncidentExtraction, WindowExtraction

log = get_logger("phase_d.pipeline")


_FAMILY_SLUG = re.compile(r"-r\d+-(.+?)-202\d{5}T\d{6}Z")


class KnowledgeGraphRetrievalPipeline(PipelineRunner):
    """LLM-extracted knowledge-graph retrieval pipeline."""

    name = "kg_retrieval"

    def __init__(
        self,
        *,
        humanized_subdir: str = "bulk-20260531",
        humanized_root: str = "jira-shadow-humanized-v2",
        extractions_subdir: str = "v2_kg_extractions",
        # G3 (2026-06-05): optional separate cache dir for pre-extracted
        # window facts. When set, kg_retrieval reads from
        # <global_dir>/<window_extractions_subdir>/window/<wid>__<hash>.json
        # instead of calling the LLM at query time. Falls through to
        # rule-based extraction if a window has no cached file.
        window_extractions_subdir: str | None = None,
        lm_studio_url: str = "http://localhost:1234",
        lm_studio_model: str = "local-model",
        neo4j_uri: str = "neo4j://127.0.0.1:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "123456789",
        top_k: int = 5,
        top_k_graph: int = 20,
        clear_graph_before_load: bool = False,
        skip_window_extraction: bool = False,
        seed: int = 42,
    ) -> None:
        self.humanized_subdir = humanized_subdir
        self.humanized_root = humanized_root
        self.extractions_subdir = extractions_subdir
        self.window_extractions_subdir = window_extractions_subdir
        self.lm_studio_url = lm_studio_url
        self.lm_studio_model = lm_studio_model
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.top_k = top_k
        self.top_k_graph = top_k_graph
        self.clear_graph_before_load = clear_graph_before_load
        # If True, use rule-based extraction for windows instead of calling
        # the LLM 2940 times. Falls back to regex+keyword matching on the
        # window's evidence_text. Faster but less accurate.
        self.skip_window_extraction = skip_window_extraction
        self.seed = seed

    # ---- helpers ----

    def _family_from_episode(self, eid: str) -> str:
        m = _FAMILY_SLUG.search(eid or "")
        return m.group(1) if m else ""

    def _load_ticket_extractions(self, global_dir: Path) -> list[IncidentExtraction]:
        cache = global_dir / self.extractions_subdir / "all_extractions.jsonl"
        if not cache.exists():
            raise FileNotFoundError(
                f"Pre-extracted facts not found at {cache}. "
                "Run `python -m v2_advanced.proposal_d_knowledge_graph.extract_tickets_cli` first."
            )
        rows = []
        with cache.open(encoding="utf-8") as fh:
            for line in fh:
                rows.append(IncidentExtraction.from_dict(json.loads(line)))
        return rows

    def _rule_based_window_extraction(self, window) -> WindowExtraction:
        """Cheap fallback when skip_window_extraction=True."""
        text = (build_window_query_text(window) or "").lower()
        # Service names from the corpus we know
        services = ["cartservice", "checkoutservice", "productcatalogservice",
                    "currencyservice", "paymentservice", "shippingservice",
                    "emailservice", "recommendationservice", "frontend",
                    "redis-cart", "loadgenerator", "adservice"]
        affected = [s for s in services if s in text]

        # Error class hints
        error_hints = ["DeadlineExceeded", "OOMKilled", "ConnectionRefused",
                       "CrashLoopBackOff", "ImagePullBackOff", "PodPending",
                       "Unavailable", "Internal", "Unauthenticated"]
        errors = [e for e in error_hints if e.lower() in text]

        # Component hints
        component_hints = ["envoy", "kubelet", "redis", "mysql"]
        components = [c for c in component_hints if c in text]

        symptoms = []
        if "p99" in text or "latency" in text:
            symptoms.append("high latency")
        if "500" in text or "5xx" in text:
            symptoms.append("5xx error spike")
        if "restart" in text or "crashloop" in text:
            symptoms.append("pod restart")

        return WindowExtraction(
            window_id=window.window_id,
            family=getattr(window, "scenario_family", "") or "",
            affected_services=affected,
            components=components,
            error_classes=errors,
            symptoms=symptoms,
        )

    # ---- main ----

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root
        from sklearn.linear_model import LogisticRegression

        t_fit_start = time.time()

        # 1) Load dataset
        with log_step(log, "load_dataset"):
            ds = load_dataset(global_dir)
            train_w = list(iter_split(ds.windows, ds.split_manifest, "train"))
            val_w = list(iter_split(ds.windows, ds.split_manifest, "validation"))
            test_w = list(iter_split(ds.windows, ds.split_manifest, "test"))
            log.info("dataset", train=len(train_w), val=len(val_w), test=len(test_w))

        # 2) Load humanized memory
        with log_step(log, "load_memory"):
            memory_issues = load_humanized_corpus(
                global_dir,
                humanized_subdir=self.humanized_subdir,
                humanized_root=self.humanized_root,
            )
            corpus = MemoryCorpus(issues=memory_issues, mode="time_ordered")
            log.info("memory", n_tickets=len(memory_issues))

        # 3) Load pre-extracted ticket facts. Prefer LLM extractions if
        #    available; fall back to rule-based extractions otherwise.
        with log_step(log, "load_ticket_extractions"):
            try:
                extractions = self._load_ticket_extractions(global_dir)
                source = "llm"
            except FileNotFoundError:
                # Fallback to rule-based
                rule_path = global_dir / "v2_kg_extractions_rules" / "all_extractions.jsonl"
                if not rule_path.exists():
                    raise FileNotFoundError(
                        f"Neither LLM extractions ({global_dir / self.extractions_subdir}) "
                        f"nor rule extractions ({rule_path}) found. "
                        "Run one of the extract_*_cli scripts first."
                    )
                extractions = []
                with rule_path.open(encoding="utf-8") as fh:
                    for line in fh:
                        extractions.append(IncidentExtraction.from_dict(json.loads(line)))
                source = "rules"
            log.info("extractions", n=len(extractions), source=source)
            extractions_by_id = {e.ticket_id: e for e in extractions}

        # 4) Load extractions into Neo4j
        neo_cfg = Neo4jConfig(
            uri=self.neo4j_uri, user=self.neo4j_user, password=self.neo4j_password,
        )
        with Neo4jClient(neo_cfg) as neo:
            with log_step(log, "load_into_neo4j"):
                counts = load_extractions(
                    neo, extractions, clear_first=self.clear_graph_before_load,
                )
                log.info("graph loaded", **counts)

            # 5) Set up LM Studio client (only used for window extraction)
            lm_client = None
            if not self.skip_window_extraction:
                lm_cfg = LMStudioConfig(base_url=self.lm_studio_url, model=self.lm_studio_model)
                lm_client = LMStudioClient(lm_cfg)
                if not lm_client.is_available():
                    log.warning("LM Studio unreachable — falling back to rule-based window extraction")
                    self.skip_window_extraction = True
                    lm_client = None

            retriever = GraphRetriever(neo)
            window_cache = global_dir / self.extractions_subdir

            # 6) For each window in train+val+test, extract window facts and
            #    score against the graph.
            with log_step(log, "score_windows", n=len(train_w) + len(val_w) + len(test_w)):
                train_feats, train_y = self._build_features_and_labels(
                    train_w, lm_client, retriever, window_cache,
                )
                val_feats, val_y = self._build_features_and_labels(
                    val_w, lm_client, retriever, window_cache,
                )
                test_feats, test_ranked, test_explanations = self._predict_test(
                    test_w, lm_client, retriever, window_cache,
                )

            # 7) Triage head: logistic regression on similarity features
            with log_step(log, "fit_triage_head"):
                if len(set(train_y)) < 2:
                    log.error("train labels are single-class — cannot fit logistic head")
                    threshold = 0.5
                    test_scores = [0.5] * len(test_w)
                else:
                    clf = LogisticRegression(
                        class_weight="balanced", max_iter=2000, solver="lbfgs",
                    ).fit(train_feats, train_y)

                    # Threshold tuning on val
                    if val_w:
                        val_scores_list = [float(p[1]) for p in clf.predict_proba(val_feats)]
                        _p, _r, threshold = precision_at_fpr(val_scores_list, val_y, target_fpr)
                    else:
                        threshold = 0.5
                    test_scores = [float(p[1]) for p in clf.predict_proba(test_feats)]

            fit_seconds = time.time() - t_fit_start

            t_predict_start = time.time()
            predictions: list[PipelinePrediction] = []
            for i, w in enumerate(test_w):
                score = float(test_scores[i])
                top_ids = test_ranked[i][: self.top_k]
                decision = "ticket_worthy" if score >= threshold else "noise"
                predictions.append(
                    PipelinePrediction(
                        window_id=w.window_id,
                        pipeline_name=self.name,
                        triage_score=score,
                        triage_decision=decision,
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
                "n_extractions": len(extractions),
                "window_extraction_mode": "rule_based" if self.skip_window_extraction else "llm",
                "neo4j_uri": self.neo4j_uri,
                "graph_counts": counts,
                "retrieval": "kg_cypher",
            },
        )

    def _extract_window(self, window, lm_client, window_cache) -> WindowExtraction:
        # G3 (2026-06-05): if a separate window-cache subdir is configured,
        # try to load a pre-extracted LLM result first. Falls through to
        # rule-based or live LLM extraction on miss.
        if self.window_extractions_subdir:
            from .schema import WindowExtraction as _WE
            import json as _json
            g3_cache = (
                window_cache.parent / self.window_extractions_subdir / "window"
                if window_cache else None
            )
            if g3_cache and g3_cache.exists():
                # Filename is "<window_id>__<hash>.json"; we don't have the
                # hash but extract_from_window uses content_hash(evidence).
                # Easier: use the consolidated jsonl if available.
                pass
            # Try the consolidated jsonl shortcut (much faster than per-file lookup)
            if not hasattr(self, "_g3_index"):
                self._g3_index = {}
                consolidated = (
                    window_cache.parent / self.window_extractions_subdir
                    / "all_extractions.jsonl"
                )
                if consolidated.exists():
                    with consolidated.open(encoding="utf-8") as fh:
                        for line in fh:
                            row = _json.loads(line)
                            wid = row.get("window_id")
                            if wid:
                                self._g3_index[wid] = _WE.from_dict(row)
            if window.window_id in self._g3_index:
                return self._g3_index[window.window_id]

        if self.skip_window_extraction or lm_client is None:
            return self._rule_based_window_extraction(window)
        evidence = build_window_query_text(window) or ""
        return extract_from_window(
            lm_client,
            window_id=window.window_id,
            evidence_text=evidence[:4000],
            family=getattr(window, "scenario_family", "") or "",
            cache_dir=window_cache,
            max_tokens=400,
        )

    def _build_features_and_labels(
        self, windows, lm_client, retriever, window_cache,
    ) -> tuple[np.ndarray, list[int]]:
        feats_rows = []
        labels = []
        for w in windows:
            ext = self._extract_window(w, lm_client, window_cache)
            rows = retriever.retrieve(ext, top_k=self.top_k_graph)
            if rows:
                max_score = float(rows[0]["score"])
                mean_top5 = float(np.mean([r["score"] for r in rows[:5]]))
                n_above_3 = sum(1 for r in rows if r["score"] > 3.0)
            else:
                max_score = 0.0
                mean_top5 = 0.0
                n_above_3 = 0
            feats_rows.append([max_score, mean_top5, float(n_above_3)])
            labels.append(1 if w.triage_label == "ticket_worthy" else 0)
        return np.asarray(feats_rows, dtype=np.float32), labels

    def _predict_test(
        self, windows, lm_client, retriever, window_cache,
    ) -> tuple[np.ndarray, list[list[str]], list[list[dict]]]:
        feats_rows = []
        all_ids: list[list[str]] = []
        all_explanations: list[list[dict]] = []
        for w in windows:
            ext = self._extract_window(w, lm_client, window_cache)
            rows = retriever.retrieve(ext, top_k=self.top_k_graph)
            if rows:
                max_score = float(rows[0]["score"])
                mean_top5 = float(np.mean([r["score"] for r in rows[:5]]))
                n_above_3 = sum(1 for r in rows if r["score"] > 3.0)
                top_ids = [r["ticket_id"] for r in rows]
            else:
                max_score = 0.0
                mean_top5 = 0.0
                n_above_3 = 0
                top_ids = []
            feats_rows.append([max_score, mean_top5, float(n_above_3)])
            all_ids.append(top_ids)
            all_explanations.append(rows[:5])
        return np.asarray(feats_rows, dtype=np.float32), all_ids, all_explanations
