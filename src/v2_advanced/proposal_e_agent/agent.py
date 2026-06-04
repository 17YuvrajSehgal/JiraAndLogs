"""DiagnosisAgent — multi-step LLM that produces a ranked diagnosis
with citations.

The agent runs a fixed three-stage workflow rather than an open-ended
tool loop. Open-ended loops are unreliable on small local models;
fixed workflows are predictable and easy to debug.

Workflow:

  STAGE 1 — Hypothesize:
    Input: window evidence text
    Output: JSON {"root_cause_hypothesis": "...", "key_symptoms": [...],
                  "suspected_services": [...]}

  STAGE 2 — Retrieve:
    Mechanical: call dense + sparse + graph retrievers, RRF-fuse to top-10.
    No LLM call.

  STAGE 3 — Verify:
    Input: window evidence + 10 candidates' descriptions + the stage-1 hypothesis
    Output: JSON {"ranked": [{"ticket_id": "...", "confidence": 0-1,
                              "consistent": true/false, "reason": "..."},
                             ...]}
    The agent ranks candidates by consistency with the hypothesis. If
    NO candidate has consistent=true and confidence > novelty_threshold,
    we flag the window as NOVEL.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from v2_advanced.shared import LMStudioClient, get_logger
from v2_advanced.shared.lm_studio import LMStudioError
from v2_advanced.shared.json_schemas import HYPOTHESIZE_RF, VERIFY_RF

log = get_logger("phase_e.agent")


_HYPOTHESIZE_SYSTEM = """You are an SRE incident-diagnosis assistant.

Given a window of live telemetry (logs + metrics), produce a JSON object with EXACTLY:
  - root_cause_hypothesis: ONE short sentence (your best guess for the underlying cause)
  - key_symptoms: list of 2-5 short phrases observed
  - suspected_services: list of service short-names most likely affected

Output VALID JSON only — no markdown, no commentary."""


_VERIFY_SYSTEM = """You are an SRE incident-diagnosis assistant ranking past incident tickets by relevance to a live problem.

Given:
  - The hypothesized root cause for the current incident
  - The list of candidate past tickets (each with id, root cause summary, affected services)

Score each candidate on a 0-1 confidence scale for whether its root cause is consistent with the hypothesis. Mark `consistent=true` if you believe an engineer should consult this ticket; `false` otherwise.

Output EXACTLY this JSON shape:
{
  "ranked": [
    {"ticket_id": "...", "confidence": 0.0-1.0, "consistent": true/false, "reason": "one short sentence"},
    ... (one entry per candidate, ordered by descending confidence)
  ]
}

If NO candidate is consistent, return an empty ranked list with a top-level "novel": true.

Output VALID JSON only."""


@dataclass
class HypothesisOutput:
    root_cause_hypothesis: str = ""
    key_symptoms: list[str] = field(default_factory=list)
    suspected_services: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "HypothesisOutput":
        return cls(
            root_cause_hypothesis=(d.get("root_cause_hypothesis") or "").strip(),
            key_symptoms=[s for s in (d.get("key_symptoms") or []) if isinstance(s, str)],
            suspected_services=[s for s in (d.get("suspected_services") or []) if isinstance(s, str)],
        )


@dataclass
class RankedCandidate:
    ticket_id: str
    confidence: float
    consistent: bool
    reason: str


@dataclass
class AgentDiagnosis:
    window_id: str
    hypothesis: HypothesisOutput
    candidates_input: list[dict]   # raw candidate dicts shown to the agent
    ranked: list[RankedCandidate]
    is_novel: bool                  # True when no candidate passed consistency
    top_ids: list[str]              # final ranked top-K ticket IDs


class RuleBasedDiagnosisAgent:
    """Rule-based fallback for the DiagnosisAgent. Used when LM Studio
    is unavailable. Same interface and output shape as DiagnosisAgent,
    but the hypothesis + verification stages use keyword overlap
    instead of LLM reasoning.

    Workflow:
      1. Hypothesis = extracted services/errors/symptoms from window
         using the rule-based window extractor.
      2. Verify each candidate: compute Jaccard overlap between the
         hypothesized symptoms and the candidate's stated root_cause +
         services + errors. Confidence = overlap fraction.
      3. consistent=True if confidence > 0.2.
      4. is_novel=True if no candidate passes consistent=True.
    """

    def __init__(
        self,
        *,
        top_k_input: int = 10,
        top_k_output: int = 5,
        consistency_threshold: float = 0.2,
        novelty_threshold: float = 0.4,
    ) -> None:
        self.top_k_input = top_k_input
        self.top_k_output = top_k_output
        self.consistency_threshold = consistency_threshold
        self.novelty_threshold = novelty_threshold

    def diagnose(
        self,
        *,
        window_id: str,
        evidence_text: str,
        candidates: list[dict[str, Any]],
    ) -> "AgentDiagnosis":
        from v2_advanced.proposal_d_knowledge_graph.rule_extractor import (
            extract_from_window_rules,
        )
        ext = extract_from_window_rules(
            window_id=window_id, evidence_text=evidence_text,
        )
        hypothesis = HypothesisOutput(
            root_cause_hypothesis="; ".join(ext.symptoms) if ext.symptoms else "",
            key_symptoms=list(ext.symptoms),
            suspected_services=list(ext.affected_services),
        )

        window_terms = set(s.lower() for s in ext.affected_services) | \
                       set(s.lower() for s in ext.error_classes) | \
                       set(s.lower() for s in ext.symptoms)

        ranked: list[RankedCandidate] = []
        for c in candidates[: self.top_k_input]:
            tid = str(c.get("ticket_id") or "")
            if not tid:
                continue
            cand_services = set(str(s).lower() for s in (c.get("affected_services") or []))
            cand_root = (c.get("root_cause") or "").lower()
            cand_terms = cand_services | set(t.lower() for t in cand_services)
            for word in cand_root.split():
                cand_terms.add(word)
            if not window_terms or not cand_terms:
                conf = 0.0
            else:
                inter = window_terms & cand_terms
                union = window_terms | cand_terms
                conf = len(inter) / max(1, len(union))
            consistent = conf >= self.consistency_threshold
            ranked.append(RankedCandidate(
                ticket_id=tid,
                confidence=float(conf),
                consistent=consistent,
                reason=f"jaccard {conf:.2f}",
            ))
        ranked.sort(key=lambda r: -r.confidence)
        is_novel = not any(r.consistent and r.confidence >= self.novelty_threshold for r in ranked)
        top_ids = [] if is_novel else [r.ticket_id for r in ranked if r.consistent][: self.top_k_output]
        return AgentDiagnosis(
            window_id=window_id,
            hypothesis=hypothesis,
            candidates_input=candidates[: self.top_k_input],
            ranked=ranked,
            is_novel=is_novel,
            top_ids=top_ids,
        )


class DiagnosisAgent:
    """Stateless agent — one instance per pipeline run; one call per
    test window.
    """

    def __init__(
        self,
        client: LMStudioClient,
        *,
        top_k_input: int = 10,
        top_k_output: int = 5,
        novelty_threshold: float = 0.4,
        max_tokens_per_call: int = 600,
    ) -> None:
        self.client = client
        self.top_k_input = top_k_input
        self.top_k_output = top_k_output
        self.novelty_threshold = novelty_threshold
        self.max_tokens_per_call = max_tokens_per_call

    def diagnose(
        self,
        *,
        window_id: str,
        evidence_text: str,
        candidates: list[dict[str, Any]],
    ) -> AgentDiagnosis:
        """Run the three-stage workflow. `candidates` is a list of dicts
        each with keys: ticket_id, root_cause (str), affected_services (list).
        """
        # ----- Stage 1: hypothesize -----
        # Stage 1 is a short structured emit (hypothesis + symptoms +
        # services). We don't want chain-of-thought here — it's a
        # straightforward "what's wrong" call. Thinking OFF.
        try:
            h_dict = self.client.chat_json(
                system=_HYPOTHESIZE_SYSTEM,
                user=f"WINDOW: {window_id}\n\n{evidence_text[:3000]}",
                temperature=0.0,
                max_tokens=self.max_tokens_per_call,
                response_format=HYPOTHESIZE_RF,
                enable_thinking=False,
            )
            hypothesis = HypothesisOutput.from_dict(h_dict)
        except LMStudioError as e:
            log.warning("stage1 hypothesize failed", window=window_id, err=str(e)[:120])
            hypothesis = HypothesisOutput()

        # ----- Stage 3: verify (stage 2 is mechanical retrieval, done by caller) -----
        cands = candidates[: self.top_k_input]
        cand_text = "\n".join(
            f"- {c.get('ticket_id')}: {c.get('root_cause', '')[:200]} "
            f"[services: {','.join(c.get('affected_services') or [])[:60]}]"
            for c in cands
        )
        verify_user = (
            f"HYPOTHESIZED ROOT CAUSE: {hypothesis.root_cause_hypothesis}\n"
            f"KEY SYMPTOMS: {', '.join(hypothesis.key_symptoms)}\n"
            f"SUSPECTED SERVICES: {', '.join(hypothesis.suspected_services)}\n\n"
            f"CANDIDATES:\n{cand_text}\n\n"
            "Rank them; return JSON."
        )
        # Stage 3 IS the actual reasoning step — judging consistency of
        # 10 candidates against the hypothesis. Thinking ON gives us a
        # meaningfully better consistency check. Increase max_tokens to
        # accommodate the <think>...</think> block.
        try:
            v_dict = self.client.chat_json(
                system=_VERIFY_SYSTEM,
                user=verify_user,
                temperature=0.0,
                max_tokens=max(self.max_tokens_per_call, 1500),
                response_format=VERIFY_RF,
                enable_thinking=True,
            )
        except LMStudioError as e:
            log.warning("stage3 verify failed", window=window_id, err=str(e)[:120])
            v_dict = {"ranked": [], "novel": True}

        # Parse the ranking
        ranked_raw = v_dict.get("ranked") or []
        novel_flag = bool(v_dict.get("novel"))
        ranked = []
        for r in ranked_raw:
            if not isinstance(r, dict):
                continue
            tid = str(r.get("ticket_id") or "")
            if not tid:
                continue
            try:
                conf = float(r.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            consistent = bool(r.get("consistent"))
            reason = str(r.get("reason") or "")
            ranked.append(RankedCandidate(tid, conf, consistent, reason))
        # Sort by descending confidence just in case the LLM didn't.
        ranked.sort(key=lambda r: -r.confidence)

        # Novelty: NO ranked candidate consistent AND confidence > threshold.
        any_consistent = any(r.consistent and r.confidence >= self.novelty_threshold for r in ranked)
        is_novel = novel_flag or (not any_consistent)

        # If novel, top_ids is empty (engineer should investigate from scratch).
        # Otherwise, take the top-K by confidence among consistent candidates.
        if is_novel:
            top_ids = []
        else:
            top_ids = [r.ticket_id for r in ranked if r.consistent][: self.top_k_output]

        return AgentDiagnosis(
            window_id=window_id,
            hypothesis=hypothesis,
            candidates_input=cands,
            ranked=ranked,
            is_novel=is_novel,
            top_ids=top_ids,
        )
