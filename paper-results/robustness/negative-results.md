# Negative results & honest failure analysis

Reported explicitly (not hidden) — see `significance.md` for the BH-corrected tests.

1. **Fusion is not universally best.** On Online-Boutique, Hybrid-RRF Hit@5 (0.559)
   is *significantly below* the standalone BiEncoder (0.634; Δ−0.076, q=0.027).
   When one retriever strongly dominates and the others add noisy candidates,
   RRF fusion can dilute the top ranks. Hybrid wins decisively on the **real**
   WoL data (Δ+0.065 vs BiEncoder, q≈0) — fusion helps where the corpus is large
   and heterogeneous, not on the small synthetic OB memory.

2. **The KG's contribution is rank-shape-specific.** The ±graph ablation shows the
   graph improves **Hit@1 / MRR** (OB Hit@1 +0.133, MRR +0.067) but **not Hit@5**
   (OB −0.033, n.s. q=0.20; OTel ≈0). The KG sharpens the top candidate rather
   than widening recall — a precision aid, not a recall aid.

3. **KG-alone retrieval is weak** (Hit@5 0.41–0.47 synthetic; ~0.28 on WoL). Entity-
   overlap graph matching alone is a weak retriever; its value is only as a
   fusion component (see #2), which we report rather than overselling KG-alone.

4. **Lexical retrieval is corpus-text dependent.** BM25 over the *raw* shadow
   corpus collapses on OB (Hit@5 0.088) while BM25/TF-IDF over the *humanized*
   corpus recover (0.356/0.372). Lexical methods are highly sensitive to memory
   text quality; we report both and use the humanized-corpus variant as the fair
   baseline.

5. **LLM-RAG does not beat trained retrieval.** Qwen2.5-7B reranking the dense
   top-10 underperforms our BiEncoder/Hybrid on every dataset (WoL 0.856 vs
   0.905/0.970), indicating the gains come from domain-tuned retrieval, not from
   a general LLM reader over the same candidates.
