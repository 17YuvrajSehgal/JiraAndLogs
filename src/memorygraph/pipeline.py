"""MemoryGraphPipeline — slots into src/comparison/runner.py as `memorygraph`.

End-to-end flow:

    load global dataset (windows, memory_corpus, split, matchings)
    build_jira_graph(memory_corpus)
    for window in test:
        visible = memory_corpus.visible_to(window)        # time-ordering
        builder.add_window(window)                        # transient node
        decision = agent.decide(window, visible_by_id)
        builder.remove_window(window.window_id)           # clear transient
        record (PipelinePrediction, explanation row)

The triage score, decision, matched_issue_ids fields populate the
PipelinePrediction shape the rest of the comparison harness expects. The
explanation goes into a sibling artifact `explanations.jsonl` written by
the CLI runner — the comparison harness ignores it.

Threshold tuning: same contract as the other pipelines — sweep
precision@FPR on the validation split, apply the resulting threshold on
test. We DON'T fit anything trainable on train; the graph is a fixed
structure and the skills are deterministic given the graph. Train data
is only used to compute Jira-side relationship statistics (e.g. how
often a fault_class co-occurs with a severity).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from loganalyzer.data.loaders import load_dataset
from loganalyzer.data.schema import TriageWindow
from loganalyzer.data.splits import iter_split
from loganalyzer.eval.metrics import precision_at_fpr
from loganalyzer.memory.corpus import MemoryCorpus

from comparison.pipelines import PipelineRunner
from comparison.schema import PipelinePrediction, PipelineResult

from .agent import Agent, AgentDecision, RulePlanner
from .graph import MemoryGraphBuilder
from .skills import default_skill_registry


class MemoryGraphPipeline(PipelineRunner):
    """Graph + agent pipeline. Drop-in replacement for any retrieval pipeline.

    Construction args:
      planner          : "rule" (default, deterministic) or "llm" (Qwen).
      llm_base_url     : LM Studio endpoint when planner='llm'.
      top_k_matches    : how many matched issue ids the pipeline reports.
      with_numeric     : when True, inserts numeric_blend into the chain
                         and fits a HistGradientBoosting head on train so
                         the per-window numeric signal is blended with
                         per-candidate graph + similarity scores. This is
                         the hybrid path the leaderboard expects from
                         `memorygraph_hybrid`.
    """

    name = "memorygraph"

    def __init__(
        self,
        *,
        planner: str = "rule",
        llm_base_url: str = "http://localhost:1234",
        top_k_matches: int = 5,
        with_numeric: bool = False,
        with_embeddings: bool = False,
        with_log_signatures: bool = False,
        humanized_subdir: str | None = None,
    ) -> None:
        self.planner_kind = planner
        self.llm_base_url = llm_base_url
        self.top_k_matches = top_k_matches
        self.with_numeric = with_numeric
        # When True, EmbeddingSimilaritySkill (Nomic via LM Studio) joins
        # the chain after lexical_similarity. Skill auto-disables if LM
        # Studio is unreachable — the chain still runs, just without
        # dense similarity. See skills.EmbeddingSimilaritySkill.
        self.with_embeddings = with_embeddings
        # When True, LogSignatureSimilaritySkill replaces the trace-
        # aggregate evidence_text query with characteristic log lines
        # extracted from raw/loki/<window>.json. Move A from
        # ML-NEW-IDEAS.MD. Requires runs_root to be passed to
        # train_and_predict so the skill can find the per-window
        # Loki dumps.
        self.with_log_signatures = with_log_signatures
        # When set, swap the loaded ds.memory_corpus for the humanized
        # corpus at jira-shadow-humanized-v1/<humanized_subdir>/timeline.jsonl
        # before any skill sees it. Used for Phase 5.3 cross-train
        # validation: legacy memory_corpus is known-leaky (see
        # text-leakage canary, commit b704cb8); humanized is the
        # production-safe replacement.
        self.humanized_subdir = humanized_subdir
        # Set by train_and_predict so the CLI can pull them out for the
        # explanations.jsonl artifact + the graph-stats summary.
        self.last_decisions: list[AgentDecision] = []
        self.last_graph_stats: dict[str, Any] | None = None

    def _make_planner(self):
        if self.planner_kind == "llm":
            from .agent import LLMPlanner
            return LLMPlanner(base_url=self.llm_base_url)
        return RulePlanner(
            with_numeric=self.with_numeric,
            with_embeddings=self.with_embeddings,
            with_log_signatures=self.with_log_signatures,
        )

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        # NB: runs_root was previously unused; the log-signature variant
        # (with_log_signatures=True) needs it to read raw/loki/<window>.json
        # per the Move A design (ML-NEW-IDEAS.MD).

        ds = load_dataset(global_dir)
        train = list(iter_split(ds.windows, ds.split_manifest, "train"))
        val = list(iter_split(ds.windows, ds.split_manifest, "validation"))
        test = list(iter_split(ds.windows, ds.split_manifest, "test"))

        # Phase 5.3 — when humanized_subdir is set, replace ds.memory_corpus
        # with the leak-free humanized corpus before any skill reads it.
        # The legacy corpus is known to be 100% contaminated by the text-
        # leakage canary; cross-train validation needs both available to
        # quantify the leakage premium.
        if self.humanized_subdir:
            from .humanized_loader import load_humanized_corpus
            ds.memory_corpus = load_humanized_corpus(
                global_dir, humanized_subdir=self.humanized_subdir,
            )

        # 1) Build the Jira side of the graph once. This is the
        #    expensive-ish step (still sub-second on v5-quick).
        t0 = time.time()
        builder = MemoryGraphBuilder()
        builder.add_jira_corpus(ds.memory_corpus)

        # Fit every trainable skill on the train split. Each skill's
        # default `Skill.fit` is a no-op so this is safe to call on the
        # full registry — only NumericBlendSkill (when wired in by the
        # hybrid planner) actually trains anything. We fit unconditionally
        # so an LLMPlanner that decides to use numeric_blend per-window
        # still finds it ready.
        planner = self._make_planner()
        registry = default_skill_registry()
        for skill in registry.values():
            skill.fit(train, ds.feature_columns)

        # GraphScoreSkill has a richer fit signature — it needs the Jira
        # corpus and the builder (so it can add/remove transient window
        # nodes during the fit pass) to compute kind-pair precision on
        # training pairs. Called directly rather than expanding the
        # Skill.fit ABC because graph_score is the only skill that needs
        # this richer context today.
        memory_by_id_pre = {m.jira_shadow_issue_id: m for m in ds.memory_corpus}
        gs_skill = registry.get("graph_score")
        if gs_skill is not None and hasattr(gs_skill, "fit_on_pairs"):
            gs_skill.fit_on_pairs(train, memory_by_id_pre, builder)

        # LogSignatureSimilaritySkill needs runs_root to find raw/loki/
        # files per window. The skill silently disables itself when
        # runs_root is None, so this is safe even when the variant
        # isn't enabled — but the pipeline only requests it when
        # with_log_signatures=True, so the skill is unused otherwise.
        log_sig_skill = registry.get("log_signature_similarity")
        if log_sig_skill is not None and self.with_log_signatures:
            log_sig_skill.runs_root = runs_root

        agent = Agent(
            builder.graph,
            planner=planner,
            registry=registry,
            top_k_matches=self.top_k_matches,
        )
        memory_corpus = MemoryCorpus(issues=ds.memory_corpus, mode="time_ordered")
        memory_by_id = memory_corpus.by_id()
        fit_seconds = time.time() - t0

        # 2) Compute validation scores to pick a threshold.
        def _score_one(window: TriageWindow) -> AgentDecision:
            visible_list = memory_corpus.visible_to(window)
            visible_map = {m.jira_shadow_issue_id: m for m in visible_list}
            builder.add_window(window)
            try:
                decision = agent.decide(window, visible_map)
            finally:
                builder.remove_window(window.window_id)
            return decision

        import sys
        # Progress cadence: print one line every PROGRESS_EVERY windows
        # so a piped run shows it's moving instead of looking hung. The
        # default of 100 means a 1755-window v5-large test split prints
        # ~18 lines per pipeline — informative but not chatty.
        PROGRESS_EVERY = 100

        if val:
            print(
                f"[{self.name}] scoring {len(val)} validation windows ...",
                file=sys.stderr, flush=True,
            )
            t_val_start = time.time()
            val_decisions: list[AgentDecision] = []
            for i, w in enumerate(val):
                val_decisions.append(_score_one(w))
                if (i + 1) % PROGRESS_EVERY == 0 or (i + 1) == len(val):
                    elapsed = time.time() - t_val_start
                    avg = elapsed / (i + 1)
                    remaining = (len(val) - i - 1) * avg
                    print(
                        f"[{self.name}] val {i+1}/{len(val)} "
                        f"elapsed={elapsed:.0f}s avg={avg:.2f}s/w "
                        f"eta={remaining:.0f}s",
                        file=sys.stderr, flush=True,
                    )
            val_scores = [d.triage_score for d in val_decisions]
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
            print(
                f"[{self.name}] val done; threshold={threshold:.4f}",
                file=sys.stderr, flush=True,
            )
        else:
            threshold = 0.5

        # 3) Score the test set and emit predictions.
        t0 = time.time()
        print(
            f"[{self.name}] scoring {len(test)} test windows ...",
            file=sys.stderr, flush=True,
        )
        predictions: list[PipelinePrediction] = []
        decisions: list[AgentDecision] = []
        for i, w in enumerate(test):
            decision = _score_one(w)
            decisions.append(decision)
            if (i + 1) % PROGRESS_EVERY == 0 or (i + 1) == len(test):
                elapsed = time.time() - t0
                avg = elapsed / (i + 1)
                remaining = (len(test) - i - 1) * avg
                print(
                    f"[{self.name}] test {i+1}/{len(test)} "
                    f"elapsed={elapsed:.0f}s avg={avg:.2f}s/w "
                    f"eta={remaining:.0f}s",
                    file=sys.stderr, flush=True,
                )
            decision_label = (
                "ticket_worthy" if decision.triage_score >= threshold else "noise"
            )
            top_ids = [m["jira_shadow_issue_id"] for m in decision.top_matches]
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=decision.triage_score,
                    triage_decision=decision_label,
                    is_novel=decision.is_novel if decision_label == "ticket_worthy" else None,
                    matched_issue_ids=top_ids[: self.top_k_matches],
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

        # 4) Cache the artifacts the CLI runner wants.
        self.last_decisions = decisions
        stats = builder.stats.as_dict()
        if gs_skill is not None and getattr(gs_skill, "learned", False):
            stats["learned_kind_weights"] = dict(gs_skill.kind_weights)
            stats["learned_kind_stats"] = gs_skill.learn_stats
        self.last_graph_stats = stats

        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={
                "train_n": len(train),
                "val_n": len(val),
                "test_n": len(test),
                "planner": self.planner_kind,
                "n_jira_nodes": builder.stats.n_jira_nodes,
                "n_entity_nodes": builder.stats.n_entity_nodes,
                "n_membership_edges": builder.stats.n_membership_edges,
                "n_relation_edges": builder.stats.n_relation_edges,
                "dropped_lab_labels": builder.stats.dropped_lab_labels,
                "entities_per_kind": dict(builder.stats.entities_per_kind),
                "bridges_per_kind": dict(builder.stats.bridges_per_kind),
            },
        )
