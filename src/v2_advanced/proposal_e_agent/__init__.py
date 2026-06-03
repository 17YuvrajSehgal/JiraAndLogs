"""Proposal E — DiagnosisAgent (capstone).

An LLM with tool use that:
  1. Reads a live window's evidence.
  2. Hypothesizes a likely root cause.
  3. Calls the retrieval tools (dense, sparse, graph) to fetch candidates.
  4. Reads each candidate's full ticket.
  5. Checks whether the candidate's root cause is consistent with the
     window's symptoms.
  6. Produces a ranked top-5 with one-sentence justifications.
  7. If no candidate passes its consistency check, flags as NOVEL —
     solving the cold-start novelty failure mode from Phase G.

Files:
    agent.py       the agent loop + prompt templates
    tools.py       the tool definitions (retrieve_by_*, read_ticket)
    pipeline.py    full PipelineRunner using the agent
"""
