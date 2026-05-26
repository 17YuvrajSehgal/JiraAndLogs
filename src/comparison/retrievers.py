"""Shared retrieval backends used by the comparison-harness pipelines.

These are the building blocks for any pipeline that does Jira-memory
retrieval (cheap-retriever -> optional rerank). Extracted from the
experiments scripts so pipelines.py can re-use them without circular
imports back into experiments.

Backends:
  BM25Retriever          — stdlib Okapi BM25 (k1=1.5, b=0.75)
  NomicRetriever         — Nomic embed + cosine via LM Studio OpenAI
                           compatible API
  LMReranker             — Qwen chat rerank over candidates from any
                           upstream retriever (used by lm-rerank pipelines)
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------


@dataclass
class BM25Retriever:
    docs: list[list[str]]
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self):
        self.n = len(self.docs)
        self.doc_lens = [len(d) for d in self.docs]
        self.avg_len = sum(self.doc_lens) / max(self.n, 1)
        df: dict[str, int] = defaultdict(int)
        for doc in self.docs:
            for t in set(doc):
                df[t] += 1
        self.idf = {
            t: math.log((self.n - count + 0.5) / (count + 0.5) + 1)
            for t, count in df.items()
        }
        self.tfs: list[Counter[str]] = [Counter(d) for d in self.docs]

    def topk(self, query: list[str], k: int) -> list[tuple[int, float]]:
        scores = [0.0] * self.n
        for q in query:
            idf = self.idf.get(q, 0.0)
            if idf == 0.0:
                continue
            for i, tf in enumerate(self.tfs):
                f = tf.get(q, 0)
                if f == 0:
                    continue
                norm = self.k1 * (1 - self.b + self.b * self.doc_lens[i] / self.avg_len)
                scores[i] += idf * (f * (self.k1 + 1)) / (f + norm)
        return sorted(enumerate(scores), key=lambda x: -x[1])[:k]


# ---------------------------------------------------------------------------
# Nomic embeddings via LM Studio OpenAI-compatible /v1/embeddings
# ---------------------------------------------------------------------------


def embed_via_lm_studio(
    base_url: str,
    model: str,
    texts: list[str],
    *,
    batch_size: int = 32,
    timeout: float = 120.0,
) -> list[list[float]]:
    """Batch-embed texts. Truncates each to 6000 chars before sending to
    stay safely under the embedding model's token limit."""
    out: list[list[float] | None] = [None] * len(texts)
    for batch_start in range(0, len(texts), batch_size):
        batch = texts[batch_start : batch_start + batch_size]
        clipped = [t[:6000] for t in batch]
        payload = {"model": model, "input": clipped}
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/v1/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        for entry in data.get("data", []):
            idx = entry.get("index", 0)
            out[batch_start + idx] = entry.get("embedding") or []
    return [v if v is not None else [] for v in out]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class NomicRetriever:
    """Pre-computes corpus embeddings; cosine-similarity scoring per query.

    Designed to be constructed once per pipeline and reused across many
    queries — the corpus embed is the expensive part."""

    def __init__(
        self,
        base_url: str,
        model: str,
        docs: list[str],
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.docs = docs
        self.doc_embeddings = embed_via_lm_studio(base_url, model, docs)

    def topk(self, query_text: str, k: int) -> list[tuple[int, float]]:
        q_emb = embed_via_lm_studio(self.base_url, self.model, [query_text])[0]
        if not q_emb:
            return []
        scored = [(i, cosine(q_emb, e)) for i, e in enumerate(self.doc_embeddings)]
        return sorted(scored, key=lambda x: -x[1])[:k]


# ---------------------------------------------------------------------------
# LM reranker (Qwen via LM Studio /v1/chat/completions)
# ---------------------------------------------------------------------------


_MD_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S | re.I)
_INT_LIST_RE = re.compile(r"(\d+)")


def parse_lm_ranking(response: str, k: int) -> list[int]:
    response = response.strip()
    m = _MD_FENCE_RE.match(response)
    if m:
        response = m.group(1).strip()
    try:
        obj = json.loads(response)
        if isinstance(obj, dict):
            for key in ("ranks", "ranking", "order", "top"):
                if key in obj and isinstance(obj[key], list):
                    return [int(x) for x in obj[key] if isinstance(x, (int, float))][:k]
        if isinstance(obj, list):
            return [int(x) for x in obj if isinstance(x, (int, float))][:k]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    nums = [int(m) for m in _INT_LIST_RE.findall(response)]
    seen: set[int] = set()
    out: list[int] = []
    for n in nums:
        if 1 <= n <= k and n not in seen:
            out.append(n)
            seen.add(n)
        if len(out) == k:
            break
    return out


def chat_via_lm_studio(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = 200,
    timeout: float = 180.0,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.URLError as e:
        return f"__ERROR__ {e}"
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""
