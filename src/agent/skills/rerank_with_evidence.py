"""RerankWithEvidenceSkill — consumes ReAct tool results to re-rank L2 candidates.

Pulls compose_l2's top-K from the trace, pulls tool_results from
ctx.extra (populated by EvidenceRequestSkills), tokenises the
evidence, scores each candidate by token-overlap against the
candidate's `memory_text`, and emits a re-ranked
matched_issue_ids list.

Why this exists (per `DOCS/docs8/IMPLEMENTATION-PLAN.md` §5.3 →
ReAct loop closure):

`request_pod_events` returns evidence into `ctx.extra["tool_results"]`
but the cascade's L2 composition doesn't natively read that slot.
Without this skill, the tool fires but doesn't change the ranking —
the framework is in place but the headline doesn't move. This skill
is the consumer that makes the loop *closed*: tool fires → evidence
reaches downstream → ranking updates → final decision shifts.

Design constraint (META-ANALYSIS.md §4.1, composition-fragility): we
do NOT add new score sources. The skill RE-WEIGHTS existing top-K
candidates from compose_l2's output, using evidence tokens as a
secondary signal. Anchor on rank-based L2 score; lift by overlap.

If no tool_results are present, the skill is a pass-through: emits
the same matched_issue_ids as compose_l2 with confidence inherited.
The runner skips it via gate, so the no-op case is cheap.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..tool_protocol import TOOL_RESULTS_KEY, get_tool_results
from ..types import InputBundle, SkillCallCost, SkillOutput
from .base import AgentContext, MemoryView, Skill, make_cost


# -----------------------------------------------------------------------------
# Tokenisation
# -----------------------------------------------------------------------------


# Stopwords for the very-cheap token overlap. Same approach as BM25Retriever's
# tokenize() — alphanumeric splits + lowercase + drop these.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "not", "to", "of", "in", "on",
    "at", "for", "with", "by", "from", "is", "are", "was", "were", "be",
    "been", "being", "this", "that", "these", "those", "it", "its", "as",
})


def _tokenize(text: str) -> set[str]:
    """Cheap tokenisation: lowercased alphanumeric words, length >= 3,
    minus stopwords, with light stem-stripping. Returns a SET."""
    if not text:
        return set()
    # Split on non-alphanumeric; keep tokens of length >= 3 to drop noise
    # like "v1" / "id" / single letters that match too aggressively.
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", text.lower())
    out: set[str] = set()
    for t in tokens:
        if t in _STOPWORDS:
            continue
        out.add(t)
        # Light stem: also include common-suffix-stripped forms so
        # "failed"/"failing" match "failure"/"failures" in memory_text.
        for suffix in ("ing", "ed", "es", "s"):
            if t.endswith(suffix) and len(t) > len(suffix) + 2:
                out.add(t[: -len(suffix)])
                break
    return out


def _split_camel(s: str) -> list[str]:
    """OOMKilled -> ['OOM', 'Killed']; CrashLoopBackOff -> ['Crash','Loop','Back','Off']."""
    # Split at boundary: lowercase->uppercase OR uppercase-cluster->next-word
    out = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+", s)
    return out


def _service_from_pod(pod: str) -> str | None:
    """Pod names look like `<service>-<rs-hash>-<pod-hash>`. Strip the
    two trailing hash-like segments."""
    if not pod or "-" not in pod:
        return None
    parts = pod.split("-")
    if len(parts) <= 2:
        return pod
    # Trailing 2 segments are deployment + pod hashes
    return "-".join(parts[:-2])


# -----------------------------------------------------------------------------
# Evidence-token extraction from tool_results
# -----------------------------------------------------------------------------


def _evidence_tokens_from_tool_results(
    tool_results: list,
    *,
    k_top_msg_chars: int = 200,
    anchor_service: str | None = None,
) -> set[str]:
    """Extract a useful token bag from all available tool_results.

    `anchor_service` is the bundle's own service_name. When set, ONLY
    events whose `pod` belongs to that service (or to a service whose
    name has substantial overlap with anchor_service) contribute
    tokens. Without this filter, cascading warnings from peer services
    drown the root-cause signal in re-ranking.

    For `request_pod_events` (the v1 tool):
      - Service names extracted from `pod` field (highest signal —
        these typically match service names in memory_text).
      - Reason tokens, with CamelCase split (OOMKilled → oom, killed).
      - First N chars of `message`, tokenised with light stemming.
    Normal-type events (Pulled / Created / Started / Scheduled) skipped
    — they happen on every healthy pod lifecycle and don't
    disambiguate which Jira ticket family matches.
    """
    tokens: set[str] = set()
    for tr in tool_results:
        if getattr(tr, "error", None):
            continue
        if tr.tool_name == "request_pod_events":
            events = (tr.result or {}).get("events") or []
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                if (ev.get("type") or "").lower() != "warning":
                    continue

                # 1. Service name from pod (the strongest signal —
                #    pod = "cartservice-866b-n5g" → "cartservice")
                pod = str(ev.get("pod") or "")
                svc = _service_from_pod(pod)

                # Anchor filter: drop events from peer services that
                # don't share substantial substring with the bundle's
                # service. Cascading warnings on paymentservice during
                # a cart-redis incident shouldn't pull paymentservice
                # candidates up.
                if anchor_service and svc:
                    a = anchor_service.lower()
                    s = svc.lower()
                    if a not in s and s not in a:
                        # Also accept the case where the LONGEST shared
                        # substring is at least 4 chars (covers
                        # "redis-cart" vs "cartservice" via "cart").
                        a_set = {p for p in a.split("-") if len(p) >= 4}
                        s_set = {p for p in s.split("-") if len(p) >= 4}
                        if not (a_set & s_set):
                            continue   # peer service — skip

                if svc:
                    tokens.add(svc.lower())
                    for sub in svc.lower().split("-"):
                        if len(sub) >= 3:
                            tokens.add(sub)

                # 2. Reason — split CamelCase so OOMKilled becomes
                #    {oom, killed} which match "memory"-adjacent
                #    tokens in memory_text via stem.
                reason = str(ev.get("reason") or "")
                for piece in _split_camel(reason):
                    tokens |= _tokenize(piece)

                # 3. Message — tokenise with light stem.
                msg = str(ev.get("message") or "")[:k_top_msg_chars]
                tokens |= _tokenize(msg)
        # Future tools (RequestExtendedTraceWindow, RequestPodMetrics,
        # RequestSimilarIncidentWindow) get their own elif branches here.
    return tokens


# -----------------------------------------------------------------------------
# Memory-text lookup
# -----------------------------------------------------------------------------


def _memory_index(memory: MemoryView) -> dict[str, str]:
    """Build a {issue_id -> memory_text} dict from the MemoryView.

    Cheap to compute (a few hundred to a few thousand entries). Cached
    on the AgentContext.extra under a private key so subsequent
    invocations of this skill in the same plan reuse it.
    """
    out: dict[str, str] = {}
    for iss in memory.issues():
        iid = getattr(iss, "jira_shadow_issue_id", None) or getattr(iss, "issue_id", None)
        mtext = getattr(iss, "memory_text", None) or ""
        if iid:
            out[iid] = mtext
    return out


# -----------------------------------------------------------------------------
# RerankWithEvidenceSkill
# -----------------------------------------------------------------------------


class RerankWithEvidenceSkill(Skill):
    """Re-rank compose_l2's top-K by token overlap with tool evidence.

    The skill consults the trace for the most recent `compose_l2`
    SkillOutput. It then reads tool_results from `ctx.extra`, extracts
    a token bag from any WARNING-type pod events, and re-weights the
    candidates by:

        new_score(c) = (1 - alpha) * (1 / rank_in_L2(c))
                     + alpha       * (|tokens ∩ memtext(c)| / |tokens|)

    Defaults: alpha = 0.4 (modest boost — we don't want to override L2
    on confident retrievals). Re-rank only the top-K from L2; ordering
    below position K is unchanged.

    Empty / missing tool_results → emit same matched_issue_ids as L2
    (pass-through). Empty / missing compose_l2 → no-op output.
    """

    name = "rerank_with_evidence"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def __init__(
        self,
        *,
        alpha: float = 0.6,
        rerank_top_k: int = 5,
        min_overlap_for_boost: int = 2,
    ) -> None:
        """alpha=0.6 weights evidence above L2-rank when overlap is
        non-trivial; raise to 0.8+ to make evidence dominant. The
        `min_overlap_for_boost` floor prevents rank-1 being demoted on
        single-token coincidences — only meaningful overlaps swap."""
        self.alpha = float(alpha)
        self.rerank_top_k = int(rerank_top_k)
        self.min_overlap_for_boost = int(min_overlap_for_boost)

    def invoke(
        self,
        bundle: InputBundle,
        memory: MemoryView,
        ctx: AgentContext,
    ) -> SkillOutput:
        # Pull compose_l2's output from the trace
        trace = (ctx.extra or {}).get("trace")
        if trace is None:
            return SkillOutput(
                skill=self.name, skill_version=self.version,
                confidence=0.0, cost=make_cost(),
                extra={"warning": "no trace in ctx.extra"},
            )
        l2_out = trace.latest_output("compose_l2")
        if l2_out is None or not l2_out.matched_issue_ids:
            return SkillOutput(
                skill=self.name, skill_version=self.version,
                confidence=0.0, cost=make_cost(),
                extra={"warning": "no compose_l2 output to re-rank"},
            )

        # Pull tool results. We don't anchor-filter events to the
        # bundle's service: OB faults are cross-service-cascading by
        # construction, so peer-service warnings are real signal.
        # Instead the rerank sort below uses a "strictly dominant
        # overlap" rule that protects rank-1 from noise swaps.
        tool_results = get_tool_results(ctx.extra)
        evidence_tokens = _evidence_tokens_from_tool_results(tool_results)

        # No evidence -> pass through with same ranking. Important: we
        # still emit a SkillOutput so the runner's decision builder
        # can find a `rerank_with_evidence` output (i.e. we don't fall
        # back to compose_l2 silently).
        if not evidence_tokens:
            return SkillOutput(
                skill=self.name, skill_version=self.version,
                matched_issue_ids=tuple(l2_out.matched_issue_ids),
                confidence=l2_out.confidence,
                cost=make_cost(wall_seconds=0.0001),
                extra={
                    "passthrough": True,
                    "reason": "no_evidence_tokens",
                    "n_tool_results": len(tool_results),
                },
            )

        # Build memory_text index (cached on ctx for re-use across
        # concurrent plan invocations of this skill — only matters when
        # the controller calls this multiple times in one plan, which
        # the v1 plan doesn't, but reserved for the v2 ReAct loop).
        cached = (ctx.extra or {}).get("__rerank_memtext_index")
        if cached is None:
            mem_index = _memory_index(memory)
            ctx.extra = {**(ctx.extra or {}), "__rerank_memtext_index": mem_index}
        else:
            mem_index = cached

        # Score the top-K. Lower ranks below K are appended unchanged.
        candidates = list(l2_out.matched_issue_ids)
        top_k = candidates[: self.rerank_top_k]
        tail = candidates[self.rerank_top_k:]

        scored: list[tuple[float, str, dict[str, Any]]] = []
        start_ms = time.monotonic()
        # Score strategy: use raw OVERLAP COUNT as the primary signal,
        # L2 rank as tie-breaker. Jaccard scores too tiny because memory
        # texts are very long (1500+ tokens vs 20-30 evidence tokens).
        # Raw count better reflects "how many evidence signals does
        # this candidate's text mention." We add the L2-rank tie-break
        # below in the sort.
        for rank, cid in enumerate(top_k, start=1):
            mem_text = mem_index.get(cid, "")
            mem_tokens = _tokenize(mem_text)
            overlap = len(evidence_tokens & mem_tokens)
            if overlap < self.min_overlap_for_boost:
                overlap_for_score = 0
            else:
                overlap_for_score = overlap
            scored.append((overlap_for_score, cid, {
                "rank_in_l2": rank,
                "overlap": overlap,
                "overlap_for_score": overlap_for_score,
            }))
        duration_ms = (time.monotonic() - start_ms) * 1000.0

        # "Strictly dominant overlap" sort: only swap rank-i with
        # rank-j (j > i) when j has STRICTLY more overlap than i. This
        # is more conservative than the simple `-overlap` sort because
        # it prevents tie-noise swaps. The sort key combines:
        #   (-overlap, rank_in_l2)
        # which already does this — if overlaps tie, L2 rank breaks
        # the tie in L2's favor (lower rank wins).
        scored.sort(key=lambda t: (-t[0], t[2]["rank_in_l2"]))
        reranked = [cid for _, cid, _ in scored] + tail

        # Compute how many top-K positions actually changed
        n_swaps = sum(1 for old, new in zip(top_k, reranked[: self.rerank_top_k]) if old != new)

        return SkillOutput(
            skill=self.name,
            skill_version=self.version,
            triage_score=None,
            triage_decision=None,
            matched_issue_ids=tuple(reranked),
            is_novel=None,
            confidence=l2_out.confidence,                   # inherit L2's confidence
            evidence_used=("tool_results",),
            cost=SkillCallCost(
                wall_seconds=duration_ms / 1000.0,
                n_calls=0,
                llm_tokens=0,
                usd=0.0,
            ),
            extra={
                "alpha": self.alpha,
                "n_evidence_tokens": len(evidence_tokens),
                "n_top_k_swaps": n_swaps,
                "per_candidate_scores": [s for _, _, s in scored],
            },
        )
