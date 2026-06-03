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
        try:
            h_dict = self.client.chat_json(
                system=_HYPOTHESIZE_SYSTEM,
                user=f"WINDOW: {window_id}\n\n{evidence_text[:3000]}",
                temperature=0.0,
                max_tokens=self.max_tokens_per_call,
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
        try:
            v_dict = self.client.chat_json(
                system=_VERIFY_SYSTEM,
                user=verify_user,
                temperature=0.0,
                max_tokens=self.max_tokens_per_call,
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
