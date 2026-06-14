"""DiagnosisAgentPipeline — wraps DiagnosisAgent as a PipelineRunner.

The agent depends on having retrieval candidates already. We get those
from the Hybrid RRF pipeline (Proposal C) — which internally uses
SPLADE + BiEncoder + Graph. The agent then reads the top-K and produces
a final ranking with consistency checks.

This is the most expensive pipeline:
  - 2 LLM calls per window (hypothesize + verify) at ~2-3s each on a
    7-14B local model = ~5s per window
  - 1008 test windows × 5s = ~85 minutes wall time
  - We DON'T run it on the entire test split by default; we run on a
    deterministic 200-window sub-sample for the paper's "quality vs
    latency" frontier table. Pass `subsample_size=0` to run all.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

from comparison.pipelines import PipelineRunner
from comparison.schema import PipelinePrediction, PipelineResult
from core.data.loaders import load_dataset
from core.data.splits import iter_split
from core.features.text import build_window_query_text
from memorygraph.humanized_loader import load_humanized_corpus

from v2_advanced.shared import LMStudioClient, get_logger, log_step
from v2_advanced.shared.lm_studio import LMStudioConfig

from v2_advanced.proposal_c_hybrid_retrieval.pipeline import HybridRRFRetrievalPipeline
from v2_advanced.proposal_d_knowledge_graph.schema import IncidentExtraction
from .agent import DiagnosisAgent, RuleBasedDiagnosisAgent

log = get_logger("phase_e.pipeline")


class DiagnosisAgentPipeline(PipelineRunner):
    """Wraps HybridRRF + DiagnosisAgent into a PipelineRunner.

    For each test window:
      1. Get top-10 candidates from HybridRRF (SPLADE + BiEncoder + Graph)
      2. For each candidate, look up its ticket extraction (root cause,
         affected services) from the cached LLM extractions
      3. Hand to DiagnosisAgent for hypothesis + verification
      4. Use the agent's ranked top-5 as matched_issue_ids and confidence
         as the triage score

    Latency: ~5-10 seconds per window depending on LLM model size.
    """

    name = "diagnosis_agent"

    def __init__(
        self,
        *,
        humanized_subdir: str = "bulk-20260531",
        humanized_root: str = "jira-shadow-humanized-v2",
        extractions_subdir: str = "v2_kg_extractions",
        lm_studio_url: str = "http://localhost:1234",
        lm_studio_model: str = "local-model",
        subsample_size: int = 200,
        subsample_seed: int = 42,
        top_k_input: int = 10,
        top_k_output: int = 5,
        novelty_threshold: float = 0.4,
    ) -> None:
        self.humanized_subdir = humanized_subdir
        self.humanized_root = humanized_root
        self.extractions_subdir = extractions_subdir
        self.lm_studio_url = lm_studio_url
        self.lm_studio_model = lm_studio_model
        # Subsample because the agent is slow. 0 = run all.
        self.subsample_size = subsample_size
        self.subsample_seed = subsample_seed
        self.top_k_input = top_k_input
        self.top_k_output = top_k_output
        self.novelty_threshold = novelty_threshold

    def _load_extractions_map(self, global_dir: Path) -> dict[str, IncidentExtraction]:
        import json
        # Try LLM-extracted first; fall back to rule-based.
        candidates = [
            global_dir / self.extractions_subdir / "all_extractions.jsonl",
            global_dir / "v2_kg_extractions_rules" / "all_extractions.jsonl",
        ]
        cache = next((c for c in candidates if c.exists()), None)
        if cache is None:
            raise FileNotFoundError(
                f"No extractions found. Tried: {candidates}. Run "
                "extract_tickets_cli (LLM) or extract_rulebased_cli (rules)."
            )
        log.info("using extractions", path=str(cache))
        out = {}
        with cache.open(encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                ext = IncidentExtraction.from_dict(d)
                out[ext.ticket_id] = ext
        return out

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        t_fit_start = time.time()

        # 1) Get the candidate pool. Either reuse cached hybrid predictions
        #    (env var V2_AGENT_HYBRID_PREDICTIONS_PATH) — useful when the
        #    LLM is already in VRAM and a BiEncoder refit would OOM — or
        #    refit the hybrid from scratch.
        import json as _json
        import os as _os
        cached_path = _os.environ.get("V2_AGENT_HYBRID_PREDICTIONS_PATH", "").strip()
        if cached_path:
            with log_step(log, "load_cached_hybrid", path=cached_path):
                hybrid_top_by_window: dict[str, list[str]] = {}
                hybrid_score_by_window: dict[str, float] = {}
                with open(cached_path, encoding="utf-8") as fh:
                    for line in fh:
                        d = _json.loads(line)
                        wid = d.get("window_id")
                        if not wid:
                            continue
                        hybrid_top_by_window[wid] = list(d.get("matched_issue_ids") or [])
                        hybrid_score_by_window[wid] = float(d.get("triage_score") or 0.0)
                log.info(
                    "hybrid pool loaded from cache",
                    n_windows=len(hybrid_top_by_window),
                    path=cached_path,
                )
        else:
            with log_step(log, "run_hybrid_retriever"):
                hybrid = HybridRRFRetrievalPipeline(
                    humanized_subdir=self.humanized_subdir,
                    humanized_root=self.humanized_root,
                    extractions_subdir=self.extractions_subdir,
                    top_k_per_retriever=self.top_k_input,
                    top_k_final=self.top_k_input,
                )
                hybrid_result = hybrid.train_and_predict(global_dir, runs_root, target_fpr=target_fpr)
                hybrid_top_by_window = {
                    p.window_id: p.matched_issue_ids for p in hybrid_result.predictions
                }
                hybrid_score_by_window = {
                    p.window_id: float(p.triage_score) for p in hybrid_result.predictions
                }
                log.info("hybrid pool ready", n_windows=len(hybrid_top_by_window))

        # 2) Load extraction map
        with log_step(log, "load_extractions"):
            extractions_map = self._load_extractions_map(global_dir)
            log.info("extractions", n=len(extractions_map))

        # 3) LM Studio — fall back to rule-based agent if not available.
        # Env overrides let the harness redirect at runtime (e.g. OpenAI).
        import os as _os
        base_url = _os.environ.get("AGENT_LLM_BASE_URL", self.lm_studio_url)
        model    = _os.environ.get("AGENT_LLM_MODEL", self.lm_studio_model)
        api_key  = _os.environ.get("AGENT_LLM_API_KEY") or _os.environ.get("OPENAI_API_KEY")
        lm_cfg = LMStudioConfig(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_s=60.0,   # remote APIs are fast; 60s is plenty
        )
        lm_client = LMStudioClient(lm_cfg)
        if lm_client.is_available():
            agent = DiagnosisAgent(
                lm_client,
                top_k_input=self.top_k_input,
                top_k_output=self.top_k_output,
                novelty_threshold=self.novelty_threshold,
            )
            agent_mode = "llm"
            log.info("using LLM agent", url=self.lm_studio_url)
        else:
            log.warning(
                "LM Studio unreachable; falling back to rule-based agent. "
                "Load a model in LM Studio for the LLM version."
            )
            agent = RuleBasedDiagnosisAgent(
                top_k_input=self.top_k_input,
                top_k_output=self.top_k_output,
                novelty_threshold=self.novelty_threshold,
            )
            agent_mode = "rule_based"

        # 4) Load test windows
        ds = load_dataset(global_dir)
        test_w = list(iter_split(ds.windows, ds.split_manifest, "test"))
        log.info("test windows", n=len(test_w))

        # Optional: filter to a specific window-ID set (env var). Used by
        # the TCH cascade to run the agent on targeted hard-case windows
        # instead of a random subsample.
        import os as _os
        wid_filter_path = _os.environ.get("V2_AGENT_WINDOW_IDS_PATH", "").strip()
        if wid_filter_path:
            with open(wid_filter_path, encoding="utf-8") as fh:
                wid_set = {line.strip() for line in fh if line.strip()}
            before = len(test_w)
            test_w = [w for w in test_w if w.window_id in wid_set]
            log.info(
                "filtered to window-ID list",
                requested=len(wid_set), matched=len(test_w), before=before,
            )
        elif self.subsample_size and self.subsample_size < len(test_w):
            rng = np.random.default_rng(self.subsample_seed)
            idx = rng.choice(len(test_w), size=self.subsample_size, replace=False)
            test_w = [test_w[i] for i in sorted(idx)]
            log.info("subsampled to fit agent latency budget", n=len(test_w))

        # 5) Run agent per window
        predictions: list[PipelinePrediction] = []
        n_novel = 0
        with log_step(log, "agent_run", n=len(test_w)):
            for i, w in enumerate(test_w, start=1):
                evidence = build_window_query_text(w) or ""
                candidate_ids = hybrid_top_by_window.get(w.window_id, [])[:self.top_k_input]
                candidates = []
                for cid in candidate_ids:
                    ext = extractions_map.get(cid)
                    if ext is None:
                        continue
                    candidates.append({
                        "ticket_id": cid,
                        "root_cause": ext.root_cause,
                        "affected_services": ext.affected_services,
                    })
                diag = agent.diagnose(
                    window_id=w.window_id,
                    evidence_text=evidence,
                    candidates=candidates,
                )
                if diag.is_novel:
                    n_novel += 1

                # Triage score: max consistency-weighted confidence; if novel, low.
                if diag.is_novel:
                    triage_score = 0.0
                else:
                    triage_score = max(
                        (r.confidence for r in diag.ranked if r.consistent),
                        default=0.0,
                    )
                # As a backup signal, also incorporate the hybrid pipeline's
                # score with low weight (helps PR-AUC calibration).
                triage_score = 0.7 * triage_score + 0.3 * hybrid_score_by_window.get(w.window_id, 0.0)

                predictions.append(
                    PipelinePrediction(
                        window_id=w.window_id,
                        pipeline_name=self.name,
                        triage_score=float(triage_score),
                        triage_decision="ticket_worthy" if triage_score >= 0.5 else "noise",
                        is_novel=diag.is_novel,
                        matched_issue_ids=diag.top_ids,
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
                if i % 25 == 0:
                    log.info(
                        "agent progress",
                        done=i, total=len(test_w),
                        novel_so_far=n_novel,
                    )

        fit_seconds = time.time() - t_fit_start
        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=0.5,
            fit_seconds=fit_seconds,
            predict_seconds=0.0,
            metadata={
                "n_test_evaluated": len(test_w),
                "n_novel_flagged": n_novel,
                "subsample_size": self.subsample_size,
                "top_k_input": self.top_k_input,
                "top_k_output": self.top_k_output,
                "novelty_threshold": self.novelty_threshold,
                "lm_studio_url": self.lm_studio_url,
                "agent_mode": agent_mode,
                "retrieval": "diagnosis_agent",
            },
        )
