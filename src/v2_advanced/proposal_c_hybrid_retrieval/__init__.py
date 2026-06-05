"""Proposal C — Hybrid retrieval via Reciprocal Rank Fusion.

Three retrievers combined:
    SPLADE       learned-sparse, replaces BM25 (10-20% better in literature)
    BiEncoder    dense, the Phase G fine-tuned MiniLM
    Graph        Phase D's Cypher-based entity-overlap retriever

Fusion is Reciprocal Rank Fusion (RRF): each retriever produces a
ranking, RRF takes 1/(k + rank) and sums across retrievers. Robust to
weight tuning — RRF's only knob is k (we use 60, the standard).
"""
