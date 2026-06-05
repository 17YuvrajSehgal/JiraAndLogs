"""G2 — fine-tuned cross-encoder retriever for the TCH cascade.

Uses a fresh fine-tune of cross-encoder/ms-marco-MiniLM-L-6-v2 over v2
train + val pairs (mixed BM25 + random negatives, matching G1's recipe).
At inference time, the cross-encoder reranks candidates pooled from the
existing 4 L2 retrievers (bi_encoder G1, hybrid_rrf rule, logseq2vec,
kg_retrieval).

Two integration options tested:

  (a) 5th retriever in L2 RRF fusion — cross-encoder's top-K joins the
      RRF vote; the cascade picks position 1 via overlap-rerank and
      positions 2-5 via RRF over all 5 retrievers.

  (b) Reranker over L2's top-K — cross-encoder scores every candidate
      in L2's top-K and the cascade uses cross-encoder's ranking
      directly for positions 1-5.

We start with (a) and evaluate (b) as an ablation if (a) underperforms.
"""
