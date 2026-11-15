"""LLM-as-judge v2 — hard negatives, and judging what the system actually returns.

The submission's judge has two weaknesses that R1 and R2 both identified, and
which we accept:

  1. Its control is drawn UNIFORMLY from the 38,642-item memory. A random ticket
     from a different project is an easy negative, so a large gold-vs-control gap
     shows the relation is non-random, not that it is useful.
  2. It judges the GOLD match. But the operationally meaningful question is
     whether the ticket the SYSTEM RETURNS would help an engineer.

This script fixes both. For each sampled query it judges three candidates, each
in an independent single-blind call (the judge never sees which condition a
candidate belongs to, nor the other candidates):

  system  — the system's actual top-1 retrieved incident
  hard    — a HARD negative: same project, not in the query's gold set, chosen as
            the most lexically similar such ticket so it is genuinely confusable
  easy    — a uniform random non-gold ticket, retained only so the result is
            comparable to the published number

The comparisons that matter are system-vs-hard (does our output beat a
confusable same-project alternative?) and the absolute fraction rated >= 4
(would an engineer call it relevant at all?). system-vs-easy reproduces the old
protocol.

This is still a model judging, not a human. It does not replace the annotator
study; it makes the automated check measure the right thing, and gives the human
study a pre-registered quantity to validate against.

Usage (GPU node):
    python scripts/v2/llm_judge_hard_negatives.py \
        --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
        --humanized-subdir bulk-20260617 \
        --predictions paper-results/retrieval-cascades/wol-v3/hybrid-rrf-predictions.jsonl \
        --out-dir paper-results-v2/gold-validation/wol-v3 --limit 300
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
log = logging.getLogger("judge-v2")

from core.data.loaders import load_dataset                      # noqa: E402
from core.features.text import build_memory_doc_text, build_window_query_text  # noqa: E402
from memorygraph.humanized_loader import load_humanized_corpus   # noqa: E402

MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_DOC, MAX_Q = 400, 600

#: The judge prompt, reproduced verbatim in the paper. Deliberately identical to
#: the published one so scores remain comparable across protocol versions.
PROMPT = (
    "Rate how relevant a PAST TICKET is to a CURRENT incident window — i.e. "
    "whether the past ticket describes the same or a closely related problem "
    "and would help triage the incident.\n\n"
    "CURRENT INCIDENT WINDOW:\n{query}\n\n"
    "PAST TICKET:\n{ticket}\n\n"
    "Reply with ONLY a single integer 1-5: 5=clearly the same/related issue, "
    "1=unrelated. Answer:"
)


def tokenize(s: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9_]{2,}", (s or "").lower()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--humanized-subdir", required=True)
    ap.add_argument("--humanized-root", default="jira-shadow-humanized-v2")
    ap.add_argument("--predictions", type=Path, required=True,
                    help="per-query predictions whose top-1 is judged")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    memory = load_humanized_corpus(args.global_dir,
                                   humanized_subdir=args.humanized_subdir,
                                   humanized_root=args.humanized_root)
    mem_text = {m.jira_shadow_issue_id: (build_memory_doc_text(m) or "") for m in memory}
    # Project is carried on the legacy metadata as scenario_family (wol-<project>).
    mem_proj = {m.jira_shadow_issue_id: (m.scenario_family or "") for m in memory}
    by_proj: dict[str, list[str]] = defaultdict(list)
    for mid, proj in mem_proj.items():
        by_proj[proj].append(mid)
    all_ids = list(mem_text)
    log.info("memory=%d items across %d projects", len(all_ids), len(by_proj))

    preds = {}
    with args.predictions.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            preds[d["window_id"]] = list(d.get("matched_issue_ids") or [])

    ds = load_dataset(args.global_dir)
    wins = [w for w in ds.windows
            if w.matched_memory_issue_ids and build_window_query_text(w)
            and preds.get(w.window_id)]
    rng.shuffle(wins)
    wins = wins[: args.limit]
    log.info("judging %d queries x 3 conditions", len(wins))

    pairs = []   # (window_id, query_text, candidate_text, condition, candidate_id)
    n_no_hard = 0
    for w in wins:
        q = build_window_query_text(w) or ""
        goldset = set(w.matched_memory_issue_ids)
        proj = getattr(w, "scenario_family", "") or ""

        top1 = next((c for c in preds[w.window_id] if c in mem_text), None)
        if top1 is None:
            continue

        # HARD negative: same project, not gold, most lexically similar to the
        # query among a bounded sample -- i.e. the kind of near-miss a retriever
        # would plausibly return and an engineer would have to rule out.
        cands = [m for m in by_proj.get(proj, []) if m not in goldset and m in mem_text]
        hard = None
        if cands:
            qt = tokenize(q)
            pool = cands if len(cands) <= 400 else rng.sample(cands, 400)
            hard = max(pool, key=lambda m: len(qt & tokenize(mem_text[m][:MAX_DOC])))
        else:
            n_no_hard += 1

        # EASY control: uniform non-gold, reproducing the published protocol.
        easy = rng.choice(all_ids)
        for _ in range(5):
            if easy not in goldset:
                break
            easy = rng.choice(all_ids)

        pairs.append((w.window_id, q, mem_text[top1], "system", top1))
        if hard:
            pairs.append((w.window_id, q, mem_text[hard], "hard", hard))
        pairs.append((w.window_id, q, mem_text[easy], "easy", easy))

    if n_no_hard:
        log.warning("%d queries had no same-project non-gold candidate", n_no_hard)
    # Judge in shuffled order so condition never correlates with position.
    rng.shuffle(pairs)
    log.info("%d judgement calls", len(pairs))

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.manual_seed(args.seed)
    tok = AutoTokenizer.from_pretrained(MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, torch_dtype=torch.bfloat16, device_map="cuda").eval()

    scored, t0 = [], time.time()
    for s in range(0, len(pairs), args.batch_size):
        batch = pairs[s:s + args.batch_size]
        prompts = [
            tok.apply_chat_template(
                [{"role": "user",
                  "content": PROMPT.format(query=q[:MAX_Q], ticket=t[:MAX_DOC])}],
                tokenize=False, add_generation_prompt=True)
            for _, q, t, _, _ in batch
        ]
        enc = tok(prompts, return_tensors="pt", padding=True,
                  truncation=True, max_length=3072).to("cuda")
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=4, do_sample=False,
                                 pad_token_id=tok.pad_token_id)
        gen = tok.batch_decode(out[:, enc["input_ids"].shape[1]:],
                               skip_special_tokens=True)
        for (wid, _, _, cond, cid), g in zip(batch, gen):
            m = re.search(r"[1-5]", g)
            scored.append({"window_id": wid, "condition": cond,
                           "candidate_id": cid,
                           "score": int(m.group()) if m else None,
                           "raw": g.strip()[:20]})
        if (s // args.batch_size) % 10 == 0:
            log.info("  %d/%d (%.0fs)", len(scored), len(pairs), time.time() - t0)

    def stats(cond: str) -> dict:
        xs = [r["score"] for r in scored
              if r["condition"] == cond and r["score"] is not None]
        if not xs:
            return {"n": 0}
        return {
            "n": len(xs),
            "mean": sum(xs) / len(xs),
            "frac_ge4": sum(1 for x in xs if x >= 4) / len(xs),
            "frac_ge3": sum(1 for x in xs if x >= 3) / len(xs),
        }

    # Paired comparison on queries where both conditions were judged.
    by_win: dict[str, dict[str, int]] = defaultdict(dict)
    for r in scored:
        if r["score"] is not None:
            by_win[r["window_id"]][r["condition"]] = r["score"]
    paired = [(v["system"], v["hard"]) for v in by_win.values()
              if "system" in v and "hard" in v]
    wins_sys = sum(1 for a, b in paired if a > b)
    ties = sum(1 for a, b in paired if a == b)
    losses = sum(1 for a, b in paired if a < b)

    res = {
        "model": MODEL, "seed": args.seed, "prompt": PROMPT,
        "n_queries": len(wins), "n_calls": len(scored),
        "conditions": {c: stats(c) for c in ("system", "hard", "easy")},
        "system_vs_hard_paired": {
            "n": len(paired), "system_higher": wins_sys, "tie": ties,
            "hard_higher": losses,
            "mean_delta": (sum(a - b for a, b in paired) / len(paired)) if paired else None,
        },
        "elapsed_s": time.time() - t0,
    }
    res["gap_system_minus_hard"] = (
        res["conditions"]["system"].get("mean", 0) - res["conditions"]["hard"].get("mean", 0))
    res["gap_system_minus_easy"] = (
        res["conditions"]["system"].get("mean", 0) - res["conditions"]["easy"].get("mean", 0))

    (args.out_dir / "judge-v2-scores.jsonl").write_text(
        "\n".join(json.dumps(r) for r in scored), encoding="utf-8")
    (args.out_dir / "judge-v2-results.json").write_text(json.dumps(res, indent=2),
                                                        encoding="utf-8")
    c = res["conditions"]
    log.info("SYSTEM top-1 mean=%.2f (>=4: %.1f%%)", c["system"]["mean"],
             100 * c["system"]["frac_ge4"])
    log.info("HARD  same-proj mean=%.2f (>=4: %.1f%%)  gap=%.2f",
             c["hard"]["mean"], 100 * c["hard"]["frac_ge4"], res["gap_system_minus_hard"])
    log.info("EASY  uniform    mean=%.2f (>=4: %.1f%%)  gap=%.2f",
             c["easy"]["mean"], 100 * c["easy"]["frac_ge4"], res["gap_system_minus_easy"])
    log.info("paired system>hard %d / tie %d / hard>system %d",
             wins_sys, ties, losses)
    return 0


if __name__ == "__main__":
    sys.exit(main())
