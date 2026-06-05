"""Tiered Cascade Hybrid (TCH).

Combines the best of each v2 pipeline into a layered system:

  L1  Triage gate          HGB.triage_score
  L2  Retrieval fusion     RRF over [bi_encoder, hybrid_rrf rule,
                                     hybrid_rrf LLM, logseq2vec]
  L3  Conditional verify   DiagnosisAgent re-rank on hard cases
                           (high triage * low retrieval confidence)
  L4  Triage stacking      Logistic regression over per-pipeline
                           triage_scores, 5-fold CV
"""
