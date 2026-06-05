"""SPLADE — learned sparse retriever.

SPLADE (Formal et al., SIGIR 2021) replaces BM25's term-counting with a
neural model that produces a sparse vocabulary-sized vector per text.
The vector has high values for both the document's actual terms AND
semantically related terms the model "expands" to. Dot-product over
these sparse vectors yields a similarity score.

Compared to BM25: typically 5-15% better Recall@K on benchmarks. Compared
to dense bi-encoders: catches exact-term matches that dense misses.

Implementation: we use HuggingFace's `naver/splade-cocondenser-ensembledistil`
checkpoint — a small (110M-param), well-known SPLADE-v2 model that runs
in under a GB of VRAM.

We DO NOT fine-tune SPLADE on our corpus by default. SPLADE is sensitive
to fine-tuning and easy to break; the off-the-shelf model works well
enough as a complement to our fine-tuned BiEncoder. If we need to fine-
tune, the recipe is in the SPLADE repo (KL-divergence distillation from
a cross-encoder).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from v2_advanced.shared import get_logger, log_step

log = get_logger("phase_c.splade")


class SpladeRetriever:
    """A SPLADE retriever wrapped around a precomputed sparse document
    index.

    Workflow:
        1. fit(corpus_texts) — embed every doc with SPLADE, store as
           sparse matrix.
        2. retrieve(query_text, top_k) — embed query, score via sparse
           dot-product.

    Doc embeddings are stored as a dict-of-dicts {doc_idx: {term_id: weight}}
    for transparency. For our small corpus (~347 docs) this is fine; for
    production at >10K docs you'd want a proper inverted index.
    """

    def __init__(
        self,
        *,
        model_name: str = "naver/splade-cocondenser-ensembledistil",
        device: str | None = None,
        max_length: int = 256,
    ) -> None:
        self.model_name = model_name
        self.device_pref = device
        self.max_length = max_length
        self.doc_ids: list[str] = []
        self.doc_vectors: list[dict[int, float]] = []
        self._model = None
        self._tokenizer = None

    def _device(self) -> str:
        import torch
        if self.device_pref:
            return self.device_pref
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForMaskedLM, AutoTokenizer

        device = self._device()
        log.info("loading SPLADE", model=self.model_name, device=device)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForMaskedLM.from_pretrained(self.model_name).to(device)
        self._model.eval()

    def _encode(self, texts: list[str]) -> list[dict[int, float]]:
        """Encode a batch of texts into SPLADE sparse vectors.

        Returns a list of {token_id: weight} dicts (one per text). Only
        non-zero entries are kept.
        """
        import torch

        self._ensure_model()
        device = self._device()
        vectors = []
        # Batch through to fit in VRAM
        BATCH = 8
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            enc = self._tokenizer(
                batch,
                truncation=True,
                max_length=self.max_length,
                padding=True,
                return_tensors="pt",
            ).to(device)
            with torch.no_grad():
                out = self._model(**enc).logits  # (B, T, V)
            # SPLADE sparse pooling: log(1 + relu(out)) * attention_mask, max over T
            mask = enc["attention_mask"].unsqueeze(-1).bool()
            relu = torch.relu(out)
            log1p = torch.log1p(relu)
            log1p = log1p.masked_fill(~mask, 0.0)
            # max over sequence
            doc_sparse = log1p.max(dim=1).values  # (B, V)
            # Move to CPU and collect nonzero
            doc_sparse = doc_sparse.cpu().numpy()
            for row in doc_sparse:
                nz = np.nonzero(row)[0]
                d = {int(j): float(row[j]) for j in nz if row[j] > 0.0}
                vectors.append(d)
        return vectors

    def fit(self, doc_ids: list[str], doc_texts: list[str]) -> None:
        assert len(doc_ids) == len(doc_texts)
        with log_step(log, "fit_splade", n_docs=len(doc_ids)):
            self.doc_ids = list(doc_ids)
            self.doc_vectors = self._encode(doc_texts)
            avg_nnz = (
                sum(len(v) for v in self.doc_vectors) / max(1, len(self.doc_vectors))
            )
            log.info("indexed", n_docs=len(self.doc_ids), avg_nonzero_per_doc=round(avg_nnz, 1))

    def retrieve(
        self,
        query_text: str,
        *,
        top_k: int = 20,
        visible_doc_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Top-K most-similar docs to the query. If visible_doc_ids is set,
        candidates not in it are excluded (used for time-ordered visibility).
        """
        if not self.doc_ids:
            return []
        q_vec = self._encode([query_text])[0]
        scores = []
        for did, dvec in zip(self.doc_ids, self.doc_vectors):
            if visible_doc_ids is not None and did not in visible_doc_ids:
                continue
            # sparse dot product
            if len(q_vec) <= len(dvec):
                s = sum(w * dvec.get(t, 0.0) for t, w in q_vec.items())
            else:
                s = sum(w * q_vec.get(t, 0.0) for t, w in dvec.items())
            if s > 0.0:
                scores.append((did, float(s)))
        scores.sort(key=lambda kv: -kv[1])
        return scores[:top_k]

    def retrieve_ids(self, query_text: str, **kwargs: Any) -> list[str]:
        return [d for d, _ in self.retrieve(query_text, **kwargs)]
