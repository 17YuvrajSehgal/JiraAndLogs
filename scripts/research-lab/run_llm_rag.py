"""LLM-RAG baseline (review.md gap #2): retrieve-then-LLM-rerank.

Pipeline per window: take the dense retriever's top-k candidate tickets, show
their text to an instruction LLM (Qwen2.5-7B-Instruct, offline via transformers),
ask it to rank the candidates by relevance to the incident window, and score
Hit@1/5 + MRR. This is the standard RAG selection baseline a reviewer expects.

Runs on a fixed subset per dataset (default 500 windows-with-gold, seed 42) —
standard for LLM baselines and documented. Reuses a dense baseline's candidate
predictions so we don't re-embed.

Usage:
  python scripts/research-lab/run_llm_rag.py \
    --global-dir data/derived/global/<id> --humanized-subdir <sub> \
    --candidates paper-results/baselines/sota-dense/<label>/bge-predictions.jsonl \
    --out-dir paper-results/baselines/llm-rag/<label> --limit 500
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "src")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", force=True)
log = logging.getLogger("llm-rag")

from core.data.loaders import load_dataset
from core.features.text import build_memory_doc_text, build_window_query_text
from memorygraph.humanized_loader import load_humanized_corpus

MODEL = "Qwen/Qwen2.5-7B-Instruct"
CAND_K = 10           # candidates shown to the LLM
MAX_DOC_CHARS = 350
MAX_Q_CHARS = 600


def build_prompt(query: str, cands: list[str]) -> list[dict]:
    lines = [f"[{i+1}] {c[:MAX_DOC_CHARS]}" for i, c in enumerate(cands)]
    user = (
        "You are triaging a software incident. Below is the current incident "
        "window, then a numbered list of past tickets retrieved as candidates.\n\n"
        f"INCIDENT WINDOW:\n{query[:MAX_Q_CHARS]}\n\n"
        f"CANDIDATE PAST TICKETS:\n" + "\n".join(lines) + "\n\n"
        "Rank the candidate numbers from most to least relevant to this incident. "
        "Reply with ONLY the numbers, comma-separated, best first (e.g. 3,1,5,2). "
        "Include every candidate number exactly once."
    )
    return [{"role": "user", "content": user}]


def parse_ranking(text: str, n: int) -> list[int]:
    nums = [int(x) for x in re.findall(r"\d+", text)]
    seen, order = set(), []
    for x in nums:
        if 1 <= x <= n and x not in seen:
            seen.add(x); order.append(x)
    for x in range(1, n + 1):           # append any the LLM dropped, stable
        if x not in seen:
            order.append(x)
    return order


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--humanized-subdir", required=True)
    ap.add_argument("--humanized-root", default="jira-shadow-humanized-v2")
    ap.add_argument("--candidates", type=Path, required=True,
                    help="dense baseline *-predictions.jsonl (top-k candidate ids per window)")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=500, help="windows-with-gold to score (0=all)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)

    # memory text by id + query text by window_id
    memory = load_humanized_corpus(args.global_dir, humanized_subdir=args.humanized_subdir,
                                   humanized_root=args.humanized_root)
    mem_text = {m.jira_shadow_issue_id: (build_memory_doc_text(m) or "") for m in memory}
    ds = load_dataset(args.global_dir)
    q_text = {w.window_id: (build_window_query_text(w) or "") for w in ds.windows}

    cand_rows = [json.loads(l) for l in args.candidates.read_text(encoding="utf-8").splitlines() if l.strip()]
    # only windows with gold AND with candidates AND with a query
    rows = [r for r in cand_rows
            if (r.get("gold_matched_issue_ids") and r.get("matched_issue_ids")
                and q_text.get(r["window_id"]))]
    random.shuffle(rows)
    if args.limit:
        rows = rows[: args.limit]
    log.info("scoring %d windows (candidates=%s)", len(rows), args.candidates.name)

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.manual_seed(args.seed)
    tok = AutoTokenizer.from_pretrained(MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16, device_map="cuda")
    model.eval()
    log.info("loaded %s", MODEL)

    predictions = []
    t0 = time.time()
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start:start + args.batch_size]
        cand_lists = [list(r["matched_issue_ids"])[:CAND_K] for r in batch]
        prompts = [tok.apply_chat_template(
            build_prompt(q_text[r["window_id"]], [mem_text.get(c, c) for c in cl]),
            tokenize=False, add_generation_prompt=True)
            for r, cl in zip(batch, cand_lists)]
        enc = tok(prompts, return_tensors="pt", padding=True, truncation=True, max_length=4096).to("cuda")
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=48, do_sample=False,
                                 pad_token_id=tok.pad_token_id)
        gen = tok.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
        for r, cl, g in zip(batch, cand_lists, gen):
            order = parse_ranking(g, len(cl))
            ranked_ids = [cl[i - 1] for i in order]
            predictions.append({
                "window_id": r["window_id"],
                "matched_issue_ids": ranked_ids,
                "gold_matched_issue_ids": list(r["gold_matched_issue_ids"]),
                "scenario_family": r.get("scenario_family"),
                "llm_raw": g.strip()[:120],
            })
        if (start // args.batch_size) % 5 == 0:
            log.info("  %d/%d (%.1fs)", len(predictions), len(rows), time.time() - t0)
    elapsed = time.time() - t0
    log.info("generated %d in %.1fs", len(predictions), elapsed)

    # metrics (coarse gold from the candidate file)
    h1 = h5 = n = 0
    mrr = 0.0
    per = defaultdict(lambda: {"n": 0, "h1": 0, "h5": 0})
    for p in predictions:
        gold = set(p["gold_matched_issue_ids"])
        n += 1
        proj = p.get("scenario_family") or "?"
        per[proj]["n"] += 1
        for r, t in enumerate(p["matched_issue_ids"], 1):
            if t in gold:
                if r == 1: h1 += 1; per[proj]["h1"] += 1
                if r <= 5: h5 += 1; per[proj]["h5"] += 1
                mrr += 1.0 / r
                break
    results = {
        "method": "llm-rag", "model": MODEL, "candidates_from": str(args.candidates),
        "global_dir": str(args.global_dir), "subset_n": n, "seed": args.seed,
        "cand_k": CAND_K, "elapsed_s": elapsed,
        "coarse": {"n_with_gold": n, "hit_at_1": h1 / max(1, n),
                   "hit_at_5": h5 / max(1, n), "mrr": mrr / max(1, n),
                   "per_project": {k: {"n": v["n"], "hit_at_1": v["h1"]/max(1,v["n"]),
                                       "hit_at_5": v["h5"]/max(1,v["n"])} for k, v in per.items()}},
    }
    (args.out_dir / "llm-rag-predictions.jsonl").write_text(
        "\n".join(json.dumps(p) for p in predictions), encoding="utf-8")
    (args.out_dir / "llm-rag-results.json").write_text(json.dumps(results, indent=2))
    c = results["coarse"]
    log.info("LLM-RAG coarse Hit@1=%.4f Hit@5=%.4f MRR=%.4f (n=%d)",
             c["hit_at_1"], c["hit_at_5"], c["mrr"], n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
