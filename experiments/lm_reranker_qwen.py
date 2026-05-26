#!/usr/bin/env python3
"""LM reranker for Jira-memory retrieval — Phase 4 of the dev plan.

For each ticket_worthy test window:
  1. BM25-rank Jira memory candidates (cheap retriever)
  2. Send top-k to the LM with the window evidence text
  3. LM returns its top pick (or rank-order)
  4. Compute recall@1/3/5 + MRR against the ground-truth matched memory issue id(s)

Uses a local OpenAI-compatible chat endpoint (LM Studio default
http://localhost:1234) so it works without ANTHROPIC_API_KEY.

Why this matters:
  The Phase 4 bi-encoder result (docs/results-v5-quick.md §6) showed
  text features can't outperform numeric for TRIAGE CLASSIFICATION
  because that task is count-based. Jira-memory RETRIEVAL is a
  different task — matching window evidence text to past ticket
  descriptions IS semantic. An LM should be able to read both texts
  and reason about which past ticket is the closest match, which is
  beyond what BM25 (lexical overlap) can do.

Usage:
    python experiments/lm_reranker_qwen.py
    python experiments/lm_reranker_qwen.py --top-k 5 --max-windows 50
    python experiments/lm_reranker_qwen.py --no-llm  # BM25-only baseline

Expected runtime: ~2-5 min for ~44 ticket_worthy test windows on
v5-quick with Qwen 2.5 Coder 14B running locally.
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


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GLOBAL_ID = "2026-05-25-dataset-v5-quick-m05v4"
DEFAULT_BASE_URL = "http://localhost:1234"
DEFAULT_MODEL = "qwen/qwen2.5-coder-14b"


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
# Minimal BM25 (stdlib, ~50 lines — avoids the rank_bm25 install)
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


@dataclass
class BM25:
    """Standard Okapi BM25. k1=1.5, b=0.75 are textbook defaults."""

    docs: list[list[str]]
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self):
        self.n = len(self.docs)
        self.doc_lens = [len(d) for d in self.docs]
        self.avg_len = sum(self.doc_lens) / max(self.n, 1)
        self.idf: dict[str, float] = {}
        df: dict[str, int] = defaultdict(int)
        for doc in self.docs:
            for t in set(doc):
                df[t] += 1
        for t, count in df.items():
            # Standard BM25 IDF: log((N - df + 0.5) / (df + 0.5) + 1)
            self.idf[t] = math.log((self.n - count + 0.5) / (count + 0.5) + 1)
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
        return [(i, s) for i, s in ranked[:k]]


# ---------------------------------------------------------------------------
# Chat API client (OpenAI-compatible, works with LM Studio)
# ---------------------------------------------------------------------------


def _chat(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = 200,
    timeout: float = 120.0,
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


_RANK_RE = re.compile(r"\b(?:rank|choice|top|best|answer|pick)\s*[:=]?\s*\[?(\d+(?:\s*,\s*\d+)*)\]?", re.I)
_INT_LIST_RE = re.compile(r"(\d+)")


_MD_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S | re.I)


def _parse_lm_ranking(response: str, k: int) -> list[int]:
    """Extract an ordered list of 1-based candidate indices from the LM
    response. Tolerant — accepts JSON `{"ranks":[1,3,2]}`, bare `[1,3,2]`,
    `Answer: 1, 3, 2`, or just `1`. Strips ```json fences first."""
    response = response.strip()
    # Strip optional ```json ... ``` markdown fences
    m = _MD_FENCE_RE.match(response)
    if m:
        response = m.group(1).strip()
    # Try JSON first
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
    # Regex fallback: pull all integers and take them in order, capped at k
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
    """Format the rerank request as a chat message.

    candidates is a list of (1-based_index, candidate_text)."""
    cand_block = "\n\n".join(
        f"[{idx}] {text[:500]}" for idx, text in candidates
    )
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
        {
            "role": "system",
            "content": (
                "You are a triage assistant. Respond with JSON only — "
                "no prose, no markdown fences."
            ),
        },
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Retrieval metrics
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-id", default=DEFAULT_GLOBAL_ID)
    parser.add_argument("--derived-root", default=str(REPO_ROOT / "data" / "derived"))
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="Top-k slot count we score (R@1/R@3/R@5)",
    )
    parser.add_argument(
        "--pool-size", type=int, default=0,
        help="BM25 pool size handed to the LM for reranking. Default 0 = "
             "same as --top-k (no extra reach). Set larger (e.g. 10, 20) to "
             "let the LM promote candidates BM25 ranked 6+ into the top-k.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LM rerank; just report BM25-only baseline",
    )
    parser.add_argument(
        "--max-windows",
        type=int,
        default=0,
        help="Limit to first N ticket_worthy test windows (0 = all)",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--debug-responses", action="store_true",
                        help="Print every LM response for debugging")
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
    # Score only ticket_worthy windows that have a non-empty gold match set.
    # Orphan windows (D12) have empty gold by design and aren't measurable
    # here. Non-ticket_worthy windows have no expected match.
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
        print("nothing to score; exiting", file=sys.stderr)
        return 0

    # Build BM25 over the memory corpus. Each entry has a top-level
    # `memory_text` field already containing the Jira-shaped summary +
    # components + labels — see build_jira_memory_corpus.py for shape.
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
    bm25 = BM25([_tokenize(t) for t in memory_texts])
    print(
        f"BM25 indexed {len(memory_texts)} memory entries; avg doc len "
        f"{bm25.avg_len:.0f}",
        file=sys.stderr,
    )

    # Score each window
    bm25_recalls = {1: [], 3: [], 5: []}
    bm25_mrrs: list[float] = []
    lm_recalls = {1: [], 3: [], 5: []}
    lm_mrrs: list[float] = []
    lm_errors = 0
    per_family_lm: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"r1": [], "r3": [], "mrr": []}
    )

    t0 = time.time()
    for i, (window, match) in enumerate(scorable, start=1):
        wid = window["window_id"]
        family = window.get("scenario_family", "?")
        gold = match["matched_memory_issue_ids"]
        evidence = _strip_window_header(window.get("triage_evidence_text") or "")

        pool_size = max(args.pool_size or args.top_k, args.top_k)
        bm25_hits = bm25.topk(_tokenize(evidence), k=max(pool_size, 10))
        bm25_pred = [memory_ids[i] for i, _ in bm25_hits]

        # BM25-only metrics — use the FULL ranking, not just top-k
        for k in (1, 3, 5):
            bm25_recalls[k].append(_recall_at_k(bm25_pred, gold, k))
        bm25_mrrs.append(_mrr(bm25_pred, gold))

        if args.no_llm:
            continue

        # LM rerank of top-pool_size (LM sees up to pool_size candidates,
        # we score whichever it ranks top-k of)
        pool_candidates = bm25_pred[:pool_size]
        pool_texts = [memory_texts[bm25_hits[j][0]] for j in range(pool_size)]
        messages = _build_prompt(
            evidence,
            [(j + 1, pool_texts[j]) for j in range(pool_size)],
        )
        resp = _chat(
            args.base_url, args.model, messages,
            temperature=args.temperature, max_tokens=args.max_tokens,
        )
        if args.debug_responses:
            print(f"  [{wid[:60]}] LM resp: {resp[:200]!r}", file=sys.stderr)
        if resp.startswith("__ERROR__"):
            lm_errors += 1
            ranks = list(range(1, pool_size + 1))  # fall back to BM25 order
        else:
            ranks = _parse_lm_ranking(resp, pool_size)
            if not ranks:
                lm_errors += 1
                if not args.debug_responses and lm_errors == 1:
                    print(f"  first LM parse failure: {resp[:300]!r}", file=sys.stderr)
                ranks = list(range(1, pool_size + 1))
        # Map LM's 1-based candidate indices to issue_ids
        lm_pred = [pool_candidates[r - 1] for r in ranks if 1 <= r <= pool_size]
        # Ensure all pool candidates represented even if LM omitted some
        for cid in pool_candidates:
            if cid not in lm_pred:
                lm_pred.append(cid)

        for k in (1, 3, 5):
            lm_recalls[k].append(_recall_at_k(lm_pred, gold, k))
        lm_mrrs.append(_mrr(lm_pred, gold))
        per_family_lm[family]["r1"].append(_recall_at_k(lm_pred, gold, 1))
        per_family_lm[family]["r3"].append(_recall_at_k(lm_pred, gold, 3))
        per_family_lm[family]["mrr"].append(_mrr(lm_pred, gold))

        if i % 10 == 0:
            elapsed = time.time() - t0
            eta = (elapsed / i) * (len(scorable) - i)
            print(
                f"  [{i}/{len(scorable)}] elapsed={elapsed:.0f}s eta={eta:.0f}s "
                f"lm_errors={lm_errors}",
                file=sys.stderr,
            )

    def _avg(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    print()
    print(f"=== LM rerank leaderboard ({args.global_id}, n={len(scorable)}) ===")
    print(f"Model: {args.model} via {args.base_url}")
    print(f"BM25 top-k pool size: {args.top_k}")
    print()
    print(f"{'pipeline':<28} {'R@1':>6} {'R@3':>6} {'R@5':>6} {'MRR':>6}")
    print("-" * 56)
    print(
        f"{'bm25_only':<28} "
        f"{_avg(bm25_recalls[1]):>6.3f} {_avg(bm25_recalls[3]):>6.3f} "
        f"{_avg(bm25_recalls[5]):>6.3f} {_avg(bm25_mrrs):>6.3f}"
    )
    if not args.no_llm:
        print(
            f"{'bm25_then_lm_rerank':<28} "
            f"{_avg(lm_recalls[1]):>6.3f} {_avg(lm_recalls[3]):>6.3f} "
            f"{_avg(lm_recalls[5]):>6.3f} {_avg(lm_mrrs):>6.3f}"
        )
        if lm_errors:
            print(f"  (lm errors: {lm_errors}/{len(scorable)} — fell back to BM25 order)")

    if not args.no_llm and per_family_lm:
        print()
        print("=== LM rerank per scenario_family ===")
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
