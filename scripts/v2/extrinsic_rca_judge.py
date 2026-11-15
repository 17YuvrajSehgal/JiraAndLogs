"""Extrinsic RCA evaluation, step 2: blind-judge hypotheses and compute deltas.

Each generated hypothesis is rated 1-5 against the query ticket's recorded
root cause, with the judge blind to which condition produced it and all calls
shuffled. Then the three pre-registered comparisons (see
icse-review-results/08-extrinsic-rca-eval.md) are computed with paired
bootstraps and Benjamini-Hochberg correction.

The judge prompt is deliberately DIFFERENT from the generation prompt (same
base model is acceptable only because the roles and prompts differ, and because
a ~100-case human-rated subset calibrates it -- study #5).

Usage (GPU node, after extrinsic_rca_generate.py):
    python scripts/v2/extrinsic_rca_judge.py \
        --run-dir paper-results-v2/extrinsic-rca
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", force=True)
log = logging.getLogger("extrinsic-judge")

LOCAL_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_HYP, MAX_REF = 700, 400

JUDGE_PROMPT = (
    "You are grading an incident diagnosis.\n\n"
    "REFERENCE (what actually caused the incident, per the engineers who "
    "resolved it):\nRoot cause: {ref_rc}\nFix: {ref_fix}\n\n"
    "CANDIDATE DIAGNOSIS:\n{hyp}\n\n"
    "Does the candidate identify the SAME underlying root cause as the "
    "reference? Judge the cause, not the wording. Reply with ONLY one integer "
    "1-5: 5 = same underlying cause, 3 = partially overlapping or too generic, "
    "1 = different or unrelated cause. Answer:"
)

CONDITIONS = ("none", "arise", "hard", "oracle")
#: Pre-registered pairwise tests, in the order of the design doc.
TESTS = (("arise", "none"), ("arise", "hard"), ("oracle", "arise"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--n-bootstrap", type=int, default=2000)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    cases = {c["window_id"]: c for c in
             (json.loads(l) for l in
              (args.run_dir / "cases.jsonl").open(encoding="utf-8"))}
    gens = [json.loads(l) for l in
            (args.run_dir / "generations.jsonl").open(encoding="utf-8")]
    log.info("cases=%d generations=%d", len(cases), len(gens))

    pairs = []
    for g in gens:
        c = cases[g["window_id"]]
        pairs.append((g["window_id"], g["condition"],
                      JUDGE_PROMPT.format(ref_rc=c["target_root_cause"][:MAX_REF],
                                          ref_fix=c["target_fix"][:MAX_REF],
                                          hyp=g["hypothesis"][:MAX_HYP])))
    rng.shuffle(pairs)  # blind: judge never sees condition order

    api_base = os.environ.get("EXTRINSIC_API_BASE")
    model_name = os.environ.get("EXTRINSIC_JUDGE_MODEL",
                                os.environ.get("EXTRINSIC_MODEL", LOCAL_MODEL))
    scored, t0 = [], time.time()
    if api_base:
        import urllib.request
        key = os.environ["EXTRINSIC_API_KEY"]
        for i, (wid, cond, prompt) in enumerate(pairs):
            body = json.dumps({"model": model_name, "temperature": 0, "max_tokens": 4,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req = urllib.request.Request(
                f"{api_base.rstrip('/')}/chat/completions", data=body,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = json.load(r)["choices"][0]["message"]["content"]
            m = re.search(r"[1-5]", raw)
            scored.append({"window_id": wid, "condition": cond,
                           "score": int(m.group()) if m else None})
            if i % 100 == 0:
                log.info("  %d/%d (%.0fs)", i, len(pairs), time.time() - t0)
    else:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        torch.manual_seed(args.seed)
        tok = AutoTokenizer.from_pretrained(model_name)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        tok.padding_side = "left"
        model = AutoModelForCausalLM.from_pretrained(
            model_name, torch_dtype=torch.bfloat16, device_map="cuda").eval()
        for s in range(0, len(pairs), args.batch_size):
            batch = pairs[s:s + args.batch_size]
            chat = [tok.apply_chat_template([{"role": "user", "content": p}],
                                            tokenize=False, add_generation_prompt=True)
                    for _, _, p in batch]
            enc = tok(chat, return_tensors="pt", padding=True,
                      truncation=True, max_length=2048).to("cuda")
            with torch.no_grad():
                out = model.generate(**enc, max_new_tokens=4, do_sample=False,
                                     pad_token_id=tok.pad_token_id)
            gen = tok.batch_decode(out[:, enc["input_ids"].shape[1]:],
                                   skip_special_tokens=True)
            for (wid, cond, _), raw in zip(batch, gen):
                m = re.search(r"[1-5]", raw)
                scored.append({"window_id": wid, "condition": cond,
                               "score": int(m.group()) if m else None})
            if (s // args.batch_size) % 20 == 0:
                log.info("  %d/%d (%.0fs)", len(scored), len(pairs), time.time() - t0)

    (args.run_dir / "judge-scores.jsonl").write_text(
        "\n".join(json.dumps(r) for r in scored), encoding="utf-8")

    # ---- aggregate -----------------------------------------------------------
    by_win: dict[str, dict[str, int]] = defaultdict(dict)
    for r in scored:
        if r["score"] is not None:
            by_win[r["window_id"]][r["condition"]] = r["score"]
    complete = {w: v for w, v in by_win.items()
                if all(c in v for c in CONDITIONS)}
    log.info("queries with all 4 conditions judged: %d", len(complete))

    def stats(cond):
        xs = [v[cond] for v in complete.values()]
        return {"n": len(xs), "mean": sum(xs) / len(xs),
                "frac_ge4": sum(1 for x in xs if x >= 4) / len(xs),
                "frac_ge3": sum(1 for x in xs if x >= 3) / len(xs)}

    def paired_boot(a, b, metric):
        """metric: 'ge4' (primary) or 'mean' (secondary), paired over queries."""
        wins = sorted(complete)
        if metric == "ge4":
            da = [1.0 if complete[w][a] >= 4 else 0.0 for w in wins]
            db = [1.0 if complete[w][b] >= 4 else 0.0 for w in wins]
        else:
            da = [float(complete[w][a]) for w in wins]
            db = [float(complete[w][b]) for w in wins]
        n = len(wins)
        obs = sum(da) / n - sum(db) / n
        r2 = random.Random(args.seed)
        ds = []
        for _ in range(args.n_bootstrap):
            idx = [r2.randrange(n) for _ in range(n)]
            ds.append(sum(da[i] - db[i] for i in idx) / n)
        ds.sort()
        p = 2 * min(sum(1 for x in ds if x <= 0),
                    sum(1 for x in ds if x >= 0)) / args.n_bootstrap
        return {"delta": obs, "ci_low": ds[int(.025 * args.n_bootstrap)],
                "ci_high": ds[int(.975 * args.n_bootstrap)], "p": min(1.0, p)}

    raw_tests = []
    for a, b in TESTS:
        for metric in ("ge4", "mean"):
            raw_tests.append({"test": f"{a} - {b}", "metric": metric,
                              **paired_boot(a, b, metric)})
    m = len(raw_tests)
    order = sorted(range(m), key=lambda j: raw_tests[j]["p"])
    prev = 1.0
    for rank, j in enumerate(reversed(order), start=1):
        prev = min(prev, raw_tests[j]["p"] * m / (m - rank + 1))
        raw_tests[j]["q_bh"] = prev
        raw_tests[j]["significant"] = prev < 0.05

    summary = {
        "judge_model": model_name, "backend": api_base or "local-hf",
        "judge_prompt": JUDGE_PROMPT, "seed": args.seed,
        "n_complete_queries": len(complete),
        "conditions": {c: stats(c) for c in CONDITIONS},
        "tests": raw_tests,
        "elapsed_s": time.time() - t0,
    }
    (args.run_dir / "extrinsic-results.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{'condition':<9}{'n':>6}{'mean':>8}{'>=4':>9}{'>=3':>9}")
    for c in CONDITIONS:
        s = summary["conditions"][c]
        print(f"{c:<9}{s['n']:>6}{s['mean']:>8.3f}{s['frac_ge4']:>9.3f}{s['frac_ge3']:>9.3f}")
    print(f"\npre-registered tests (primary metric = frac >=4), BH-corrected:")
    for t in raw_tests:
        print(f"  {t['test']:<16}{t['metric']:<6}{t['delta']:+.4f} "
              f"[{t['ci_low']:+.4f},{t['ci_high']:+.4f}]  q={t['q_bh']:.3f} "
              f"{'SIG' if t['significant'] else 'n.s.'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
