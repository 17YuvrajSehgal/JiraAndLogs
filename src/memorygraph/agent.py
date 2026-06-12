"""Agent + planners — pick a skill chain, run it, return a structured decision.

Two planners ship in this file:

  * `RulePlanner`  — deterministic ordering of the best-known chain. This
                     is what the comparison-harness pipeline uses by
                     default; it's reproducible, doesn't depend on LM
                     Studio, and is what the regression tests assert on.
  * `LLMPlanner`   — sends the available-skills manifest + a short window
                     summary to a local Qwen via LM Studio and asks the
                     model to return a JSON skill chain. Falls back to
                     RulePlanner if LM Studio is unreachable or the model
                     returns an unparseable answer. Useful for the
                     "agentic" demo path; not the default for benchmarks
                     because it introduces nondeterminism.

The Agent class is intentionally tiny — it just iterates the chain and
records a trace. The interesting reasoning lives inside the individual
skills.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from core.data.schema import JiraMemoryIssue, TriageWindow

from .graph import MemoryGraph
from .skills import (
    AgentContext,
    Skill,
    SkillResult,
    available_skills,
    default_skill_registry,
)


# ---------------------------------------------------------------------------
# Decision dataclass
# ---------------------------------------------------------------------------


@dataclass
class AgentDecision:
    """Final structured result the pipeline reads."""

    window_id: str
    triage_score: float
    decision: str  # ticket_worthy | noise
    is_novel: bool
    top_matches: list[dict[str, Any]] = field(default_factory=list)
    explanation: str = ""
    skill_chain: list[str] = field(default_factory=list)
    skill_trace: list[dict[str, Any]] = field(default_factory=list)
    n_candidates_after_filter: int = 0
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "triage_score": self.triage_score,
            "decision": self.decision,
            "is_novel": self.is_novel,
            "top_matches": self.top_matches,
            "explanation": self.explanation,
            "skill_chain": self.skill_chain,
            "skill_trace": self.skill_trace,
            "n_candidates_after_filter": self.n_candidates_after_filter,
            "elapsed_ms": self.elapsed_ms,
        }


# ---------------------------------------------------------------------------
# Planners
# ---------------------------------------------------------------------------


class Planner:
    """Returns an ordered list of skill names to execute for a given window."""

    def plan(self, ctx: AgentContext) -> list[str]:
        raise NotImplementedError


class RulePlanner(Planner):
    """Deterministic best-known skill chain.

    The order encodes domain knowledge:
      1. entity_extract           - audit what we have
      2. component_filter         - direct pre-filter (cheap)
      3. service_filter           - narrower direct filter (only if it leaves >= 3)
      4. severity_align           - severity bonus (graph_scores)
      5. error_class_align        - error-class bonus (graph_scores)
      6. lexical_similarity       - BM25 on filtered set
      7. graph_score              - bridge-weight graph scoring
      [hybrid only]
      7.5 numeric_blend           - HGB head -> window-global numeric_score
      8. triage_decide            - blend sim + graph (+ numeric) -> combined_scores + decision
      9. novelty_check            - is_novel from top combined score
      10. graph_traverse_explain  - explanation from the graph for top match
    """

    DEFAULT_CHAIN: tuple[str, ...] = (
        "entity_extract",
        "component_filter",
        "service_filter",
        "severity_align",
        "error_class_align",
        "lexical_similarity",
        "graph_score",
        "triage_decide",
        "novelty_check",
        "graph_traverse_explain",
    )

    HYBRID_CHAIN: tuple[str, ...] = (
        "entity_extract",
        "component_filter",
        "service_filter",
        "severity_align",
        "error_class_align",
        "lexical_similarity",
        "graph_score",
        "numeric_blend",
        "triage_decide",
        "novelty_check",
        "graph_traverse_explain",
    )

    def __init__(
        self,
        chain: tuple[str, ...] | None = None,
        *,
        with_numeric: bool = False,
        with_embeddings: bool = False,
        with_log_signatures: bool = False,
        with_cross_encoder: bool = False,
    ) -> None:
        if chain is not None:
            self.chain = chain
            return
        base = self.HYBRID_CHAIN if with_numeric else self.DEFAULT_CHAIN
        base_list = list(base)
        if with_log_signatures:
            # log_signature_similarity OVERWRITES similarity_scores —
            # it replaces the lexical_similarity query vocabulary with
            # engineer-vocabulary log lines. Place it AFTER
            # lexical_similarity so it gets the last write.
            insert_at = base_list.index("lexical_similarity") + 1
            base_list.insert(insert_at, "log_signature_similarity")
        if with_embeddings:
            # embedding_similarity BLENDS its scores 50/50 with whatever
            # is in similarity_scores. Place it AFTER both lexical and
            # log_signature so it blends with the most recent writer.
            insert_at = (
                base_list.index("log_signature_similarity") + 1
                if with_log_signatures
                else base_list.index("lexical_similarity") + 1
            )
            base_list.insert(insert_at, "embedding_similarity")
        if with_cross_encoder:
            # cross_encoder_rerank OVERWRITES similarity_scores for the
            # top-K candidates with cross-encoder joint scoring. Place
            # it LAST among the similarity skills so it has access to
            # the consensus from BM25 / log_signature / embedding to
            # pick a sensible top-K to rerank.
            insert_at = base_list.index("graph_score")
            base_list.insert(insert_at, "cross_encoder_rerank")
        self.chain = tuple(base_list)

    def plan(self, ctx: AgentContext) -> list[str]:
        return list(self.chain)


class LLMPlanner(Planner):
    """Ask Qwen via LM Studio to pick the skill chain.

    Falls back to RulePlanner.DEFAULT_CHAIN on:
      - LM Studio unreachable
      - parse failure
      - the model picking unknown skill names

    This is a demo path more than a production path — running an LLM
    once per window for planning is expensive, and on the v5-quick
    corpus the RulePlanner ties or beats it.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:1234",
        model: str = "qwen/qwen2.5-coder-14b",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self._fallback = RulePlanner()

    def plan(self, ctx: AgentContext) -> list[str]:
        try:
            from comparison.retrievers import chat_via_lm_studio
        except ImportError:
            return self._fallback.plan(ctx)
        manifest = available_skills()
        win = ctx.window
        # Build a compact window summary for the prompt.
        raw = win.raw or {}
        summary = {
            "service": win.service_name,
            "window_type": win.window_type,
            "p95_ms": raw.get("triage_feature_trace_latency_p95_ms"),
            "trace_error_rate": raw.get("triage_feature_trace_error_rate"),
            "log_error_count": raw.get("triage_feature_log_error_count"),
            "k8s_restart_count": raw.get("triage_feature_k8s_restart_count"),
            "k8s_pod_unavailable_count": raw.get("triage_feature_k8s_pod_unavailable_count"),
            "n_visible_jira": len(ctx.visible_jira),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a triage planner. Given a window summary and a "
                    "manifest of available skills, output a JSON object "
                    '{"chain": [skill_name, ...]} ordering the skills to '
                    "execute. The chain MUST end with triage_decide and SHOULD "
                    "end with graph_traverse_explain. Respond with JSON only."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"window": summary, "skills": manifest}, indent=2
                ),
            },
        ]
        try:
            resp = chat_via_lm_studio(
                self.base_url, self.model, messages,
                temperature=0.0, max_tokens=300, timeout=self.timeout,
            )
        except Exception:
            return self._fallback.plan(ctx)
        if not resp or resp.startswith("__ERROR__"):
            return self._fallback.plan(ctx)
        try:
            stripped = resp.strip()
            if stripped.startswith("```"):
                # Strip markdown fences if the model added them
                stripped = stripped.strip("`")
                if stripped.startswith("json"):
                    stripped = stripped[4:]
            obj = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return self._fallback.plan(ctx)
        chain = obj.get("chain") if isinstance(obj, dict) else None
        if not isinstance(chain, list):
            return self._fallback.plan(ctx)
        registry = default_skill_registry()
        clean = [s for s in chain if isinstance(s, str) and s in registry]
        if not clean or "triage_decide" not in clean:
            return self._fallback.plan(ctx)
        return clean


# ---------------------------------------------------------------------------
# Agent controller
# ---------------------------------------------------------------------------


class Agent:
    """Skill-chain executor.

    Construct once per pipeline run; call `decide(window, visible_jira)`
    for each window. The same graph is reused across calls — the pipeline
    inserts the window's transient node before the call and removes it
    after.
    """

    def __init__(
        self,
        graph: MemoryGraph,
        *,
        planner: Planner | None = None,
        registry: dict[str, Skill] | None = None,
        top_k_matches: int = 5,
    ) -> None:
        self.graph = graph
        self.planner = planner or RulePlanner()
        self.registry = registry or default_skill_registry()
        self.top_k_matches = top_k_matches

    def decide(
        self,
        window: TriageWindow,
        visible_jira: dict[str, JiraMemoryIssue],
    ) -> AgentDecision:
        t0 = time.time()
        ctx = AgentContext(window=window, graph=self.graph, visible_jira=visible_jira)
        chain = self.planner.plan(ctx)
        results: list[SkillResult] = []
        for name in chain:
            skill = self.registry.get(name)
            if skill is None:
                continue
            try:
                res = skill.run(ctx)
            except Exception as exc:  # pragma: no cover — defensive
                res = SkillResult(
                    name=name, ok=False,
                    summary=f"skill raised: {exc!r}", metrics={},
                )
            results.append(res)
            ctx.skill_trace.append(
                {"skill": name, "ok": res.ok, "summary": res.summary, "metrics": res.metrics}
            )
            # Hard-fail the chain on a critical failure in triage_decide so
            # we don't silently emit garbage scores.
            if name == "triage_decide" and not res.ok:
                break

        top_matches = self._top_matches(ctx)
        is_novel = bool(
            ctx.decision == "ticket_worthy"
            and (not ctx.combined_scores or max(ctx.combined_scores.values()) < 0.15)
        )
        elapsed_ms = (time.time() - t0) * 1000.0
        return AgentDecision(
            window_id=window.window_id,
            triage_score=float(ctx.triage_score or 0.0),
            decision=ctx.decision or "noise",
            is_novel=is_novel,
            top_matches=top_matches,
            explanation=ctx.explanation,
            skill_chain=chain,
            skill_trace=ctx.skill_trace,
            n_candidates_after_filter=len(ctx.candidate_jira_ids),
            elapsed_ms=elapsed_ms,
        )

    def _top_matches(self, ctx: AgentContext) -> list[dict[str, Any]]:
        if not ctx.combined_scores:
            return []
        ordered = sorted(
            ctx.combined_scores.items(), key=lambda kv: -kv[1]
        )[: self.top_k_matches]
        out: list[dict[str, Any]] = []
        for cid, score in ordered:
            issue = ctx.visible_jira.get(cid)
            if issue is None:
                continue
            shared = ctx.graph.shared_entities(ctx.window.window_id, cid)
            out.append({
                "jira_shadow_issue_id": cid,
                "jira_issue_key": issue.jira_issue_key,
                "affected_service": issue.affected_service,
                "fault_type": issue.fault_type,
                "combined_score": float(score),
                "similarity_score": float(ctx.similarity_scores.get(cid, 0.0)),
                "graph_score": float(ctx.graph_scores.get(cid, 0.0)),
                "n_bridges": len(shared),
                "shared_entity_kinds": sorted({e.id.kind for e in shared}),
                "resolution_notes_preview": (issue.resolution_notes or "")[:160],
            })
        return out
