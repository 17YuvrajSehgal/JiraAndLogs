#!/usr/bin/env python3
"""LM reranker with Nomic embeddings as the cheap retriever.

Same overall design as `experiments/lm_reranker_qwen.py`, but swaps BM25
for `text-embedding-nomic-embed-text-v1.5` (768-dim) cosine similarity
in the cheap-retrieval stage. The hypothesis tested by this script:

  BM25 R@10 on v5-quick caps the LM rerank at R@5 ≈ 0.308. The
  bottleneck is BM25 missing the gold from its top-10 entirely for
  some families (checkout-outage, productcatalog-latency). A semantic
  retriever should put the gold inside top-10 for more families, and
  the LM rerank should then promote it.

Two endpoints used:
  POST http://localhost:1234/v1/embeddings   (Nomic)
  POST http://localhost:1234/v1/chat/completions   (Qwen 2.5 Coder 14B)

Both are OpenAI-compatible (LM Studio default).

Reports three pipelines:
  bm25_only                     -- baseline for comparison
  nomic_only                    -- nomic embed + cosine, no rerank
  nomic_then_lm_rerank          -- nomic top-pool_size + Qwen rerank

Usage:
    python experiments/lm_reranker_nomic_qwen.py
    python experiments/lm_reranker_nomic_qwen.py --pool-size 10
    python experiments/lm_reranker_nomic_qwen.py --no-llm   # nomic+bm25 only

Expected runtime: ~6-10 min for 26 windows at pool=10 (embeddings
batched once at startup; only LM rerank dominates wall clock).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # src/experiments/X.py -> repo root
DEFAULT_GLOBAL_ID = "2026-05-25-dataset-v5-quick-m05v4"
DEFAULT_BASE_URL = "http://localhost:1234"
DEFAULT_CHAT_MODEL = "qwen/qwen2.5-coder-14b"
DEFAULT_EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"


# ---------------------------------------------------------------------------
# Common helpers (duplicated from lm_reranker_qwen.py — kept self-contained
# so this script can run standalone without internal-import refactors)
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _strip_window_header(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.startswith("WINDOW "))


# ---------------------------------------------------------------------------
# Minimal BM25 (for the baseline comparison only)
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


@dataclass
class BM25:
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

    def score(self, query: list[str]) -> list[float]:
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
        return scores

    def topk(self, query: list[str], k: int) -> list[tuple[int, float]]:
        scores = self.score(query)
        ranked = sorted(enumerate(scores), key=lambda x: -x[1])
        return ranked[:k]


# ---------------------------------------------------------------------------
# Nomic embeddings + cosine retriever
# ---------------------------------------------------------------------------


def _embed(
    base_url: str,
    model: str,
    texts: list[str],
    *,
    batch_size: int = 32,
    timeout: float = 120.0,
) -> list[list[float]]:
    """Batch-embed a list of texts via OpenAI-compatible /v1/embeddings.

    Nomic embed expects up to ~8k tokens per input. We truncate each text
    to 6000 chars (very conservative — should never exceed 2k tokens) to
    stay safely under any model-side limit."""
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
    # Fill any holes (shouldn't happen but be defensive)
    return [v if v is not None else [] for v in out]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class NomicRetriever:
    """Pre-computes memory embeddings; cosine-similarity scoring per query."""

    def __init__(self, base_url: str, model: str, docs: list[str]) -> None:
        self.base_url = base_url
        self.model = model
        self.docs = docs
        t0 = time.time()
        print(
            f"  embedding {len(docs)} memory docs via {model} ...",
            file=sys.stderr,
        )
        self.doc_embeddings = _embed(base_url, model, docs)
        elapsed = time.time() - t0
        non_empty = sum(1 for e in self.doc_embeddings if e)
        dim = len(self.doc_embeddings[0]) if self.doc_embeddings and self.doc_embeddings[0] else 0
        print(
            f"  embedded {non_empty}/{len(docs)} docs in {elapsed:.1f}s "
            f"(dim={dim})",
            file=sys.stderr,
        )

    def topk(self, query_text: str, k: int) -> list[tuple[int, float]]:
        q_emb = _embed(self.base_url, self.model, [query_text])[0]
        if not q_emb:
            return []
        scored = [
            (i, _cosine(q_emb, e)) for i, e in enumerate(self.doc_embeddings)
        ]
        scored.sort(key=lambda x: -x[1])
        return scored[:k]


# ---------------------------------------------------------------------------
# Chat API client (same as lm_reranker_qwen.py)
# ---------------------------------------------------------------------------


def _chat(
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


_MD_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S | re.I)
_INT_LIST_RE = re.compile(r"(\d+)")


def _parse_lm_ranking(response: str, k: int) -> list[int]:
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
    seen = set()
    out = []
    for n in nums:
        if 1 <= n <= k and n not in seen:
            out.append(n)
            seen.add(n)
        if len(out) == k:
            break
    return out


def _build_prompt(window_text: str, candidates: list[tuple[int, str]]) -> list[dict[str, str]]:
    cand_block = "\n\n".join(f"[{idx}] {text[:500]}" for idx, text in candidates)
    user = (
        "You are ranking past Jira incident tickets by how well they "
        "match a current telemetry window. Read the window evidence, "
        "then return a JSON object with key `ranks` containing the "
        "candidate numbers in order from MOST to LEAST relevant.\n\n"
        f"WINDOW EVIDENCE:\n{window_text[:2000]}\n\n"
        f"CANDIDATES:\n{cand_block}\n\n"
        f"Return JSON only, e.g. {{\"ranks\": [3,1,2,...]}} listing all "
        f"{len(candidates)} candidate numbers exactly once."
    )
    return [
        {"role": "system", "content": (
            "You are a triage assistant. Respond with JSON only — no prose, "
            "no markdown fences."
        )},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _recall_at_k(predicted: list[str], gold: list[str], k: int) -> float:
    if not gold:
        return 0.0
    return float(any(p in set(gold) for p in predicted[:k]))


def _mrr(predicted: list[str], gold: list[str]) -> float:
    if not gold:
        return 0.0
    gold_set = set(gold)
    for i, p in enumerate(predicted, start=1):
        if p in gold_set:
            return 1.0 / i
    return 0.0


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-id", default=DEFAULT_GLOBAL_ID)
    parser.add_argument("--derived-root", default=str(REPO_ROOT / "data" / "derived"))
    parser.add_argument("--top-k", type=int, default=5,
                        help="Top-k slot count we score (R@1/R@3/R@5)")
    parser.add_argument("--pool-size", type=int, default=10,
                        help="Top-N from cheap retriever handed to the LM")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--chat-model", default=DEFAULT_CHAT_MODEL)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LM rerank; report nomic-only + bm25-only")
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=200)
    args = parser.parse_args()

    global_dir = Path(args.derived_root) / "global" / args.global_id
    examples_path = global_dir / "global-triage-examples.jsonl"
    memory_path = global_dir / "jira-memory-corpus.jsonl"
    matchings_path = global_dir / "window-memory-matchings.jsonl"
    for p in (examples_path, memory_path, matchings_path):
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 2

    rows = _read_jsonl(examples_path)
    memory = _read_jsonl(memory_path)
    matchings = {m["window_id"]: m for m in _read_jsonl(matchings_path)}
    print(
        f"Loaded {len(rows)} windows / {len(memory)} memory entries / "
        f"{len(matchings)} matching rows",
        file=sys.stderr,
    )

    test_rows = [r for r in rows if r.get("split") == "test"]
    scorable = []
    for r in test_rows:
        if r.get("triage_label") != "ticket_worthy":
            continue
        m = matchings.get(r["window_id"])
        if not m or not m.get("matched_memory_issue_ids"):
            continue
        scorable.append((r, m))
    if args.max_windows > 0:
        scorable = scorable[: args.max_windows]
    print(f"Scorable windows: {len(scorable)}", file=sys.stderr)
    if not scorable:
        return 0

    # Build memory text corpus
    memory_texts: list[str] = []
    memory_ids: list[str] = []
    for issue in memory:
        text = " ".join(
            str(v) for v in (
                issue.get("memory_text"),
                issue.get("resolution_notes"),
                issue.get("affected_service"),
                issue.get("fault_type"),
            ) if v
        )
        memory_texts.append(text)
        memory_ids.append(issue.get("jira_shadow_issue_id") or "")

    # BM25 baseline (for direct comparison)
    bm25 = BM25([_tokenize(t) for t in memory_texts])

    # Nomic retriever (one-time batch embed of memory)
    print(f"Building Nomic retriever ({args.embed_model})", file=sys.stderr)
    nomic = NomicRetriever(args.base_url, args.embed_model, memory_texts)

    bm25_recalls = {1: [], 3: [], 5: []}
    bm25_mrrs: list[float] = []
    nomic_recalls = {1: [], 3: [], 5: []}
    nomic_mrrs: list[float] = []
    lm_recalls = {1: [], 3: [], 5: []}
    lm_mrrs: list[float] = []
    lm_errors = 0
    per_family_lm: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"r1": [], "r3": [], "mrr": []}
    )

    t0 = time.time()
    for i, (window, match) in enumerate(scorable, start=1):
        gold = match["matched_memory_issue_ids"]
        family = window.get("scenario_family", "?")
        evidence = _strip_window_header(window.get("triage_evidence_text") or "")

        # BM25 baseline
        bm25_hits = bm25.topk(_tokenize(evidence), k=max(args.pool_size, 10))
        bm25_pred = [memory_ids[idx] for idx, _ in bm25_hits]
        for k in (1, 3, 5):
            bm25_recalls[k].append(_recall_at_k(bm25_pred, gold, k))
        bm25_mrrs.append(_mrr(bm25_pred, gold))

        # Nomic cheap retriever
        nomic_hits = nomic.topk(evidence, k=max(args.pool_size, 10))
        nomic_pred = [memory_ids[idx] for idx, _ in nomic_hits]
        for k in (1, 3, 5):
            nomic_recalls[k].append(_recall_at_k(nomic_pred, gold, k))
        nomic_mrrs.append(_mrr(nomic_pred, gold))

        if args.no_llm:
            continue

        # LM rerank of Nomic top-pool_size
        pool_candidates = nomic_pred[: args.pool_size]
        pool_texts = [memory_texts[nomic_hits[j][0]] for j in range(args.pool_size)]
        messages = _build_prompt(
            evidence,
            [(j + 1, pool_texts[j]) for j in range(args.pool_size)],
        )
        resp = _chat(
            args.base_url, args.chat_model, messages,
            temperature=args.temperature, max_tokens=args.max_tokens,
        )
        if resp.startswith("__ERROR__"):
            lm_errors += 1
            ranks = list(range(1, args.pool_size + 1))
        else:
            ranks = _parse_lm_ranking(resp, args.pool_size)
            if not ranks:
                lm_errors += 1
                if lm_errors == 1:
                    print(f"  first LM parse failure: {resp[:300]!r}", file=sys.stderr)
                ranks = list(range(1, args.pool_size + 1))
        lm_pred = [pool_candidates[r - 1] for r in ranks if 1 <= r <= args.pool_size]
        for cid in pool_candidates:
            if cid not in lm_pred:
                lm_pred.append(cid)

        for k in (1, 3, 5):
            lm_recalls[k].append(_recall_at_k(lm_pred, gold, k))
        lm_mrrs.append(_mrr(lm_pred, gold))
        per_family_lm[family]["r1"].append(_recall_at_k(lm_pred, gold, 1))
        per_family_lm[family]["r3"].append(_recall_at_k(lm_pred, gold, 3))
        per_family_lm[family]["mrr"].append(_mrr(lm_pred, gold))

        if i % 5 == 0:
            elapsed = time.time() - t0
            eta = (elapsed / i) * (len(scorable) - i)
            print(
                f"  [{i}/{len(scorable)}] elapsed={elapsed:.0f}s eta={eta:.0f}s "
                f"lm_errors={lm_errors}",
                file=sys.stderr,
            )

    print()
    print(f"=== Retrieval leaderboard ({args.global_id}, n={len(scorable)}) ===")
    print(f"Chat: {args.chat_model}  Embed: {args.embed_model}")
    print(f"Pool size: {args.pool_size}")
    print()
    print(f"{'pipeline':<32} {'R@1':>6} {'R@3':>6} {'R@5':>6} {'MRR':>6}")
    print("-" * 60)
    print(
        f"{'bm25_only':<32} "
        f"{_avg(bm25_recalls[1]):>6.3f} {_avg(bm25_recalls[3]):>6.3f} "
        f"{_avg(bm25_recalls[5]):>6.3f} {_avg(bm25_mrrs):>6.3f}"
    )
    print(
        f"{'nomic_only':<32} "
        f"{_avg(nomic_recalls[1]):>6.3f} {_avg(nomic_recalls[3]):>6.3f} "
        f"{_avg(nomic_recalls[5]):>6.3f} {_avg(nomic_mrrs):>6.3f}"
    )
    if not args.no_llm:
        print(
            f"{'nomic_then_lm_rerank':<32} "
            f"{_avg(lm_recalls[1]):>6.3f} {_avg(lm_recalls[3]):>6.3f} "
            f"{_avg(lm_recalls[5]):>6.3f} {_avg(lm_mrrs):>6.3f}"
        )
        if lm_errors:
            print(f"  (lm errors: {lm_errors}/{len(scorable)} — fell back to BM25 order)")

    if not args.no_llm and per_family_lm:
        print()
        print("=== nomic + LM rerank per scenario_family ===")
        print(f"{'family':<48} {'n':>4} {'R@1':>6} {'R@3':>6} {'MRR':>6}")
        print("-" * 74)
        for fam in sorted(per_family_lm.keys()):
            stats = per_family_lm[fam]
            print(
                f"{fam:<48} {len(stats['r1']):>4} "
                f"{_avg(stats['r1']):>6.3f} {_avg(stats['r3']):>6.3f} "
                f"{_avg(stats['mrr']):>6.3f}"
            )

    print(file=sys.stderr)
    print(f"Total elapsed: {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
