"""Composition skills — fuse upstream retriever / triage outputs into a final
ranking, triage probability, and novelty flag.

These skills don't load JSONLs; they read the **current bundle's Trace**
(via ctx.extra["trace"]) and consume the outputs of previously-invoked
retrieval / triage skills. The Runner ensures these run AFTER their
inputs.

Three skills mirror the cascade's L1 / L2 / L3 layers:

  - compose_l2       — RRF + BiEncoder-anchored overlap rerank
  - compose_triage   — logistic stacker on per-pipeline triage scores
  - compose_novelty  — three-signal disjunction (agent ∨ free ∨ learned)

The math is ported verbatim from `v2_advanced/tch/build_cascade.py`.
This is deliberate: the agent's composition layer is *the same logic* as
the locked cascade, exposed as skills the Runner orchestrates. The
agentic contribution lies in adaptive *invocation*, not in re-deriving
the fusion math.
"""

from __future__ import annotations

import math
from typing import Any

from ..capabilities import MEMORY_TEXT, TEXT_EVIDENCE
from ..trace import Trace
from ..types import InputBundle, SkillOutput, TriageDecision
from .base import AgentContext, MemoryView, Skill, make_cost


# ---------------------------------------------------------------------------
# Shared helpers — same constants as TCH
# ---------------------------------------------------------------------------


#: Reciprocal Rank Fusion's denominator constant (Cormack et al.).
RRF_K = 60.0

#: Final output list length.
TOP_K_OUTPUT = 5

#: L1 triage threshold (cascade convention).
L1_TRIAGE_THRESHOLD = 0.5

#: L3 free-signal novelty threshold (max retriever triage_score below this
#: marks the window as novel via the free signal).
L3_FREE_NOVELTY_THRESHOLD = 0.5

#: L3 learned-classifier threshold.
L3_LEARNED_NOVELTY_THRESHOLD = 0.5


def _get_trace(ctx: AgentContext) -> Trace | None:
    return ctx.extra.get("trace")


# ---------------------------------------------------------------------------
# compose_l2 — RRF + overlap rerank
# ---------------------------------------------------------------------------


class ComposeL2Skill(Skill):
    """Fuse retriever outputs into the final top-5.

    Position 1: BiEncoder-anchored overlap rerank.
        Take BiEncoder's top-3 as the anchor pool. For each candidate c
        in that pool, count how many other retrievers (Hybrid-RRF,
        LogSeq2Vec, KG-Retrieval) have c in their top-3 with rank
        weighting (3 − rank). Pick argmax overlap; tie-break to
        BiEncoder's top-1.

    Positions 2-5: standard RRF over the L2 retriever set.
        Score = Σ 1 / (k + rank). The position-1 anchor is removed from
        consideration so positions 2-5 fill with the next-best fused
        candidates.

    Both phases match the locked cascade's L2 logic (build_cascade.py).
    """

    name = "compose_l2"
    version = "1.0.0"
    required_flags = frozenset()        # composition skill — no evidence needed
    cost_class = "cheap"

    #: L2 retriever set — same as `L2_RETRIEVERS` in build_cascade.py.
    #: Configurable per-instance for ablations.
    DEFAULT_L2_RETRIEVERS = (
        "retrieve_dense",
        "retrieve_hybrid_fusion",
        "retrieve_log_sequence",
        "retrieve_knowledge_graph",
    )

    #: Overlap-rerank voter set — three retrievers vote on position 1.
    DEFAULT_OVERLAP_VOTERS = (
        "retrieve_hybrid_fusion",
        "retrieve_hybrid_fusion_llm",     # may be absent; gracefully skipped
        "retrieve_log_sequence",
    )

    #: Anchor pool source.
    DEFAULT_ANCHOR_SKILL = "retrieve_dense"

    def __init__(
        self,
        *,
        l2_retrievers: tuple[str, ...] | None = None,
        overlap_voters: tuple[str, ...] | None = None,
        anchor_skill: str | None = None,
        anchor_pool_size: int = 3,
        voter_top_k: int = 3,
        top_k_output: int = TOP_K_OUTPUT,
        rrf_k: float = RRF_K,
    ) -> None:
        self.l2_retrievers = l2_retrievers or self.DEFAULT_L2_RETRIEVERS
        self.overlap_voters = overlap_voters or self.DEFAULT_OVERLAP_VOTERS
        self.anchor_skill = anchor_skill or self.DEFAULT_ANCHOR_SKILL
        self.anchor_pool_size = anchor_pool_size
        self.voter_top_k = voter_top_k
        self.top_k_output = top_k_output
        self.rrf_k = rrf_k

    def invoke(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        ctx: AgentContext,
    ) -> SkillOutput:
        trace = _get_trace(ctx)
        if trace is None:
            # No trace context — degrade gracefully.
            return SkillOutput(
                skill=self.name, skill_version=self.version,
                confidence=0.0,
                extra={"warning": "compose_l2 invoked without trace in ctx.extra"},
            )

        # Pull rankings from the trace
        retriever_outputs: dict[str, list[str]] = {}
        for name in self.l2_retrievers:
            out = trace.latest_output(name)
            if out is None:
                continue
            retriever_outputs[name] = list(out.matched_issue_ids)

        if not retriever_outputs:
            return SkillOutput(
                skill=self.name, skill_version=self.version,
                matched_issue_ids=(), confidence=0.0,
                extra={"warning": "no retriever outputs in trace"},
            )

        # --- Position 1 -----------------------------------------------------
        position_1 = self._pick_position_1(trace, retriever_outputs)

        # --- Positions 2-5 via RRF -----------------------------------------
        rrf_ranking = self._rrf_fuse(retriever_outputs)
        # Remove the position-1 anchor from RRF output to fill positions 2-5
        positions_2_to_k = [c for c in rrf_ranking if c != position_1]
        positions_2_to_k = positions_2_to_k[: self.top_k_output - 1]

        final_top = []
        if position_1:
            final_top.append(position_1)
        final_top.extend(positions_2_to_k)
        final_top = final_top[: self.top_k_output]

        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            triage_score=None,
            triage_decision=None,
            matched_issue_ids=tuple(final_top),
            is_novel=None,
            confidence=1.0 if final_top else 0.0,
            evidence_used=tuple(sorted(retriever_outputs)),
            cost=make_cost(wall_seconds=0.001),
            extra={
                "anchor_skill": self.anchor_skill,
                "n_retrievers_seen": len(retriever_outputs),
                "rrf_k": self.rrf_k,
            },
        )

    # ------------------------------------------------------------------ helpers

    def _pick_position_1(
        self,
        trace: Trace,
        retriever_outputs: dict[str, list[str]],
    ) -> str | None:
        """BiEncoder-anchored overlap rerank.

        Take the anchor skill's top-N (N=anchor_pool_size). For each
        candidate c in that pool, score by Σ over voters of
            1[c ∈ voter.top_K] · (voter_top_k − rank)
        Pick argmax (ties broken by anchor order). If no candidates,
        fall back to anchor's top-1.
        """
        anchor_out = trace.latest_output(self.anchor_skill)
        if anchor_out is None or not anchor_out.matched_issue_ids:
            # No anchor — return whatever retriever happens to have output
            for r in self.l2_retrievers:
                if r in retriever_outputs and retriever_outputs[r]:
                    return retriever_outputs[r][0]
            return None

        anchor_pool = list(anchor_out.matched_issue_ids[: self.anchor_pool_size])

        # Build voter top-K lookup
        voter_top_lists: list[list[str]] = []
        for v_name in self.overlap_voters:
            v_out = trace.latest_output(v_name)
            if v_out is None:
                continue
            voter_top_lists.append(list(v_out.matched_issue_ids[: self.voter_top_k]))

        if not voter_top_lists:
            return anchor_pool[0]

        # Score each anchor candidate by voter overlap
        scored: list[tuple[str, float, int]] = []   # (candidate, overlap, anchor_order)
        for anchor_rank, c in enumerate(anchor_pool):
            score = 0.0
            for voter_list in voter_top_lists:
                if c in voter_list:
                    rank_in_voter = voter_list.index(c)
                    score += (self.voter_top_k - rank_in_voter)
            scored.append((c, score, anchor_rank))

        # Sort: score desc, anchor_order asc
        scored.sort(key=lambda t: (-t[1], t[2]))
        best_c, best_score, _ = scored[0]
        if best_score == 0:
            # No overlap; fall back to anchor's top-1
            return anchor_pool[0]
        return best_c

    def _rrf_fuse(self, retriever_outputs: dict[str, list[str]]) -> list[str]:
        """Standard Reciprocal Rank Fusion.

            score(c) = Σ_r 1 / (k + rank_r(c))

        Returns the fused candidate list, descending by score."""
        scores: dict[str, float] = {}
        for r_name, ranking in retriever_outputs.items():
            for rank_idx, c in enumerate(ranking[:10], start=1):
                scores[c] = scores.get(c, 0.0) + 1.0 / (self.rrf_k + rank_idx)
        return sorted(scores, key=lambda c: -scores[c])


# ---------------------------------------------------------------------------
# compose_triage — logistic stacker on per-pipeline triage_score
# ---------------------------------------------------------------------------


class ComposeTriageSkill(Skill):
    """Class-balanced logistic stacker on the L4 feature set.

    The stacker takes one feature per upstream skill: its `triage_score`.
    Skills that didn't run for this bundle contribute 0.0 (gracefully
    handled). The stacker weights are loaded from a fitted artifact on
    disk (produced by the L1 stacker refit script).

    v1: weights are loaded from a YAML-shaped config at construction.
    A "no stacker yet" fallback emits triage_score = max(triage_scores)
    so the skill is functional during early development.
    """

    name = "compose_triage"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    #: Default feature names — match `L4_STACK_FEATURES` in build_cascade.py.
    DEFAULT_FEATURES = (
        "triage_numeric",
        "retrieve_dense",
        "retrieve_hybrid_fusion",
        "retrieve_hybrid_fusion_llm",
        "retrieve_log_sequence",
        "retrieve_knowledge_graph",
    )

    def __init__(
        self,
        *,
        features: tuple[str, ...] | None = None,
        coefficients: dict[str, float] | None = None,
        intercept: float = 0.0,
        threshold: float = L1_TRIAGE_THRESHOLD,
    ) -> None:
        self.features = features or self.DEFAULT_FEATURES
        # If no coefficients supplied, fall back to "max" mode at invoke time
        self.coefficients = coefficients
        self.intercept = intercept
        self.threshold = threshold

    def invoke(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        ctx: AgentContext,
    ) -> SkillOutput:
        trace = _get_trace(ctx)
        if trace is None:
            return SkillOutput(
                skill=self.name, skill_version=self.version,
                triage_score=0.0, triage_decision="noise",
                confidence=0.0,
                extra={"warning": "compose_triage invoked without trace in ctx.extra"},
            )

        # Build the feature vector
        feature_vec: dict[str, float] = {}
        n_present = 0
        for f in self.features:
            out = trace.latest_output(f)
            if out is None or out.triage_score is None:
                feature_vec[f] = 0.0
            else:
                feature_vec[f] = float(out.triage_score)
                n_present += 1

        # Compute stacker probability
        if self.coefficients is not None:
            z = self.intercept + sum(
                self.coefficients.get(f, 0.0) * feature_vec[f]
                for f in self.features
            )
            triage_score = _sigmoid(z)
            mode = "stacker"
        else:
            # Fallback: max of present triage scores. Useful during
            # development before the stacker artifact is fitted.
            triage_score = max(feature_vec.values(), default=0.0)
            mode = "fallback_max"

        decision: TriageDecision = (
            "ticket_worthy" if triage_score >= self.threshold else "noise"
        )
        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            triage_score=triage_score,
            triage_decision=decision,
            confidence=triage_score,
            evidence_used=tuple(sorted(feature_vec)),
            cost=make_cost(wall_seconds=0.0001),
            extra={
                "mode": mode,
                "n_features_present": n_present,
                "threshold": self.threshold,
            },
        )


def _sigmoid(z: float) -> float:
    # Stable sigmoid that avoids overflow for large |z|.
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e_z = math.exp(z)
    return e_z / (1.0 + e_z)


# ---------------------------------------------------------------------------
# compose_novelty — three-signal disjunction
# ---------------------------------------------------------------------------


class ComposeNoveltySkill(Skill):
    """Three-signal novelty disjunction (closes RQ-A5).

        is_novel = agent_novel ∨ (max_ret_conf < 0.5) ∨ (P_learned ≥ 0.5)

    Signals:
      1. `agent_novel` — pulled from verify_with_llm's SkillOutput.is_novel
         (when the skill ran; absent on WoL by structural design).
      2. Free signal — max triage_score over the retriever set < threshold.
      3. Learned classifier — currently a placeholder; v2 will wire in
         the LogReg artifact from `data/agent_traces/<exp>/learned_novelty.pkl`.
         For now, this signal is False unless a `P_learned` is provided
         via ctx.extra["learned_novelty_prob"].

    Implements §3.10 of MODE3 + cascade L3 logic verbatim. The full
    disjunction with all three signals is the closure of RQ-A5
    (previously the WoL Mode 2 result reported only the free signal).
    """

    name = "compose_novelty"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    #: Retrievers contributing to the free signal.
    DEFAULT_FREE_SIGNAL_RETRIEVERS = (
        "retrieve_dense",
        "retrieve_hybrid_fusion",
        "retrieve_hybrid_fusion_llm",
    )

    def __init__(
        self,
        *,
        free_signal_retrievers: tuple[str, ...] | None = None,
        free_signal_threshold: float = L3_FREE_NOVELTY_THRESHOLD,
        learned_novelty_threshold: float = L3_LEARNED_NOVELTY_THRESHOLD,
        verifier_skill: str = "verify_with_llm",
    ) -> None:
        self.free_signal_retrievers = (
            free_signal_retrievers or self.DEFAULT_FREE_SIGNAL_RETRIEVERS
        )
        self.free_signal_threshold = free_signal_threshold
        self.learned_novelty_threshold = learned_novelty_threshold
        self.verifier_skill = verifier_skill

    def invoke(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        ctx: AgentContext,
    ) -> SkillOutput:
        trace = _get_trace(ctx)
        if trace is None:
            return SkillOutput(
                skill=self.name, skill_version=self.version,
                is_novel=False, confidence=0.0,
                extra={"warning": "compose_novelty invoked without trace in ctx.extra"},
            )

        # Signal 1: agent_novel
        agent_novel = False
        verify_out = trace.latest_output(self.verifier_skill)
        if verify_out is not None and verify_out.is_novel is not None:
            agent_novel = bool(verify_out.is_novel)

        # Signal 2: free signal — max retriever triage_score below threshold
        max_conf = 0.0
        any_retriever_seen = False
        for r in self.free_signal_retrievers:
            out = trace.latest_output(r)
            if out is None or out.triage_score is None:
                continue
            any_retriever_seen = True
            max_conf = max(max_conf, float(out.triage_score))
        free_signal = (any_retriever_seen and max_conf < self.free_signal_threshold)

        # Signal 3: learned classifier (placeholder for v1)
        learned_prob = float(ctx.extra.get("learned_novelty_prob", 0.0))
        learned_signal = learned_prob >= self.learned_novelty_threshold

        is_novel = agent_novel or free_signal or learned_signal

        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            is_novel=is_novel,
            confidence=1.0,
            cost=make_cost(wall_seconds=0.0001),
            extra={
                "agent_novel": agent_novel,
                "free_signal": free_signal,
                "free_signal_max_conf": max_conf,
                "learned_signal": learned_signal,
                "learned_novelty_prob": learned_prob,
            },
        )
