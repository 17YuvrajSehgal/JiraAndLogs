"""v2_advanced — second-iteration research pipelines.

Five proposals from docs3/08-RESEARCH-DIRECTIONS.md, implemented as
parallel pipelines (not replacements) so we can compare against
the Phase G baseline:

    proposal_a_resplit              in-distribution train/val/test
    proposal_b_logseq2vec           log-sequence encoder
    proposal_c_hybrid_retrieval     SPLADE + BiEncoder + Graph via RRF
    proposal_d_knowledge_graph      LLM-extracted graph in Neo4j
    proposal_e_agent                DiagnosisAgent (LLM with tool use)
    shared/                          logging, LM Studio client, Neo4j client

Old (v1) code in src/{comparison, memorygraph, neural_models, etc.}
is UNTOUCHED. Both panels can be run independently; the comparison
harness picks up pipelines from either via KNOWN_PIPELINES.
"""
