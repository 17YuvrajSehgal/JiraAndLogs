"""Lexical triage: how similar is this window's evidence text to known
ticket-worthy text vs known noise text?

This is a centroid-style classifier: build a TF-IDF centroid for each label
seen in training, then score a window by the cosine similarity of its
tf-idf vector to the ticket_worthy centroid minus the noise centroid.

A linear SVM would do better, but this stays stdlib and produces a calibrated
probability via a simple sigmoid on the margin.
"""

from __future__ import annotations

import math
from collections import Counter

from .base import TriageModel, label_to_target
from ..data.schema import TriageWindow
from ..features.text import build_window_query_text, tokenize


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


class LexicalTriageModel(TriageModel):
    name = "lexical_centroid"
    features_used = ["triage_evidence_text"]

    def __init__(self, *, borderline_as: int = 0, margin_scale: float = 6.0) -> None:
        self.borderline_as = borderline_as
        self.margin_scale = margin_scale
        self.idf: dict[str, float] = {}
        self.pos_centroid: dict[str, float] = {}
        self.neg_centroid: dict[str, float] = {}

    @staticmethod
    def _tf(tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        counts = Counter(tokens)
        total = sum(counts.values())
        return {term: cnt / total for term, cnt in counts.items()}

    @staticmethod
    def _norm(vec: dict[str, float]) -> float:
        return math.sqrt(sum(v * v for v in vec.values()))

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        tf = self._tf(tokens)
        return {term: tf_val * self.idf.get(term, 0.0) for term, tf_val in tf.items()}

    def fit(self, windows: list[TriageWindow]) -> None:
        token_lists: list[list[str]] = []
        targets: list[int] = []
        df: Counter[str] = Counter()
        for w in windows:
            toks = tokenize(build_window_query_text(w))
            token_lists.append(toks)
            targets.append(label_to_target(w.triage_label, borderline_as=self.borderline_as))
            for term in set(toks):
                df[term] += 1

        n_docs = max(len(token_lists), 1)
        self.idf = {term: math.log((1 + n_docs) / (1 + freq)) + 1.0 for term, freq in df.items()}

        pos_acc: dict[str, float] = {}
        neg_acc: dict[str, float] = {}
        pos_n = 0
        neg_n = 0
        for toks, y in zip(token_lists, targets):
            vec = self._vectorize(toks)
            n = self._norm(vec)
            if n > 0:
                vec = {t: v / n for t, v in vec.items()}
            target = pos_acc if y == 1 else neg_acc
            for term, val in vec.items():
                target[term] = target.get(term, 0.0) + val
            if y == 1:
                pos_n += 1
            else:
                neg_n += 1

        if pos_n > 0:
            pos_acc = {t: v / pos_n for t, v in pos_acc.items()}
        if neg_n > 0:
            neg_acc = {t: v / neg_n for t, v in neg_acc.items()}

        self.pos_centroid = pos_acc
        self.neg_centroid = neg_acc

    def predict_score(self, window: TriageWindow) -> float:
        toks = tokenize(build_window_query_text(window))
        vec = self._vectorize(toks)
        n = self._norm(vec)
        if n > 0:
            vec = {t: v / n for t, v in vec.items()}
        pos_sim = sum(vec.get(t, 0.0) * v for t, v in self.pos_centroid.items())
        neg_sim = sum(vec.get(t, 0.0) * v for t, v in self.neg_centroid.items())
        margin = pos_sim - neg_sim
        return _sigmoid(self.margin_scale * margin)
