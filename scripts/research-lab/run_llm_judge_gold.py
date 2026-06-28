"""LLM-as-judge gold validation (review.md gap #4).

For a seeded sample of windows-with-gold, ask Qwen2.5-7B to rate how relevant a
candidate past ticket is to the incident window (1-5). We judge:
  - the GOLD ticket            -> should score HIGH (judge-gold agreement)
  - a RANDOM non-gold ticket   -> should score LOW  (discrimination / control)

Reports: mean gold score, mean random score, % gold rated relevant (>=4),
% random rated relevant (false-positive), and a discrimination gap. A large gap
+ high gold-agreement is evidence the gold labels are sound (a stopgap for a
full human study; ship the human-annotation kit for later kappa).

Deterministic: seed 42, greedy decoding.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", force=True)
log = logging.getLogger("llm-judge")

from core.data.loaders import load_dataset
from core.features.text import build_memory_doc_text, build_window_query_text
from memorygraph.humanized_loader import load_humanized_corpus

MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_DOC, MAX_Q = 400, 600


def prompt(query: str, ticket: str) -> list[dict]:
    return [{"role": "user", "content": (
        "Rate how relevant a PAST TICKET is to a CURRENT incident window — i.e. "
        "whether the past ticket describes the same or a closely related problem "
        "and would help triage the incident.\n\n"
        f"CURRENT INCIDENT WINDOW:\n{query[:MAX_Q]}\n\n"
        f"PAST TICKET:\n{ticket[:MAX_DOC]}\n\n"
        "Reply with ONLY a single integer 1-5: 5=clearly the same/related issue, "
        "1=unrelated. Answer:")}]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--humanized-subdir", required=True)
    ap.add_argument("--humanized-root", default="jira-shadow-humanized-v2")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    memory = load_humanized_corpus(args.global_dir, humanized_subdir=args.humanized_subdir,
                                   humanized_root=args.humanized_root)
    mem_text = {m.jira_shadow_issue_id: (build_memory_doc_text(m) or "") for m in memory}
    all_ids = list(mem_text)
    ds = load_dataset(args.global_dir)
    # windows-with-gold (coarse)
    wins = [w for w in ds.windows if (w.matched_memory_issue_ids and build_window_query_text(w))]
    rng.shuffle(wins)
    wins = wins[: args.limit]
    log.info("judging %d windows", len(wins))

    # build (window, ticket, is_gold) pairs: gold + one random non-gold each
    pairs = []
    for w in wins:
        q = build_window_query_text(w) or ""
        gold = [g for g in w.matched_memory_issue_ids if g in mem_text]
        if not gold:
            continue
        g = rng.choice(gold)
        pairs.append((w.window_id, q, mem_text[g], 1))
        goldset = set(w.matched_memory_issue_ids)
        neg = rng.choice(all_ids)
        for _ in range(5):
            if neg not in goldset:
                break
            neg = rng.choice(all_ids)
        pairs.append((w.window_id, q, mem_text[neg], 0))

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.manual_seed(args.seed)
    tok = AutoTokenizer.from_pretrained(MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16, device_map="cuda").eval()
    log.info("loaded %s; %d judgement pairs", MODEL, len(pairs))

    scored = []
    t0 = time.time()
    for s in range(0, len(pairs), args.batch_size):
        batch = pairs[s:s + args.batch_size]
        prompts = [tok.apply_chat_template(prompt(q, t), tokenize=False, add_generation_prompt=True)
                   for _, q, t, _ in batch]
        enc = tok(prompts, return_tensors="pt", padding=True, truncation=True, max_length=3072).to("cuda")
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=4, do_sample=False, pad_token_id=tok.pad_token_id)
        gen = tok.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
        for (wid, _, _, is_gold), g in zip(batch, gen):
            m = re.search(r"[1-5]", g)
            scored.append({"window_id": wid, "is_gold": is_gold,
                           "score": int(m.group()) if m else None, "raw": g.strip()[:20]})
        if (s // args.batch_size) % 5 == 0:
            log.info("  %d/%d (%.1fs)", len(scored), len(pairs), time.time() - t0)

    gold_s = [r["score"] for r in scored if r["is_gold"] == 1 and r["score"] is not None]
    rand_s = [r["score"] for r in scored if r["is_gold"] == 0 and r["score"] is not None]
    mean = lambda xs: sum(xs) / max(1, len(xs))
    frac_rel = lambda xs: sum(1 for x in xs if x >= 4) / max(1, len(xs))
    results = {
        "model": MODEL, "seed": args.seed, "n_windows": len(wins),
        "n_gold_judged": len(gold_s), "n_random_judged": len(rand_s),
        "gold_mean_score": mean(gold_s), "random_mean_score": mean(rand_s),
        "gold_frac_relevant_ge4": frac_rel(gold_s),
        "random_frac_relevant_ge4": frac_rel(rand_s),
        "discrimination_gap": mean(gold_s) - mean(rand_s),
        "elapsed_s": time.time() - t0,
    }
    (args.out_dir / "llm-judge-gold-scores.jsonl").write_text(
        "\n".join(json.dumps(r) for r in scored), encoding="utf-8")
    (args.out_dir / "llm-judge-gold-results.json").write_text(json.dumps(results, indent=2))
    log.info("GOLD mean=%.2f (rel%%=%.1f) | RANDOM mean=%.2f (rel%%=%.1f) | gap=%.2f",
             results["gold_mean_score"], 100*results["gold_frac_relevant_ge4"],
             results["random_mean_score"], 100*results["random_frac_relevant_ge4"],
             results["discrimination_gap"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
