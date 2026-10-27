"""Extrinsic RCA evaluation, step 1: generate diagnoses under four context conditions.

Pre-registered design: icse-review-results/08-extrinsic-rca-eval.md. Do not
change conditions, prompts, or sampling after results exist.

For each sampled held-out query, the SAME model with the SAME prompt diagnoses
the incident four times; only the context block differs:
    none    no context
    arise   the system's actual top-5 retrieved tickets (hybrid fusion)
    hard    5 same-project non-gold tickets, most lexically similar (near-misses)
    oracle  5 of the query's coarse-gold matches

Judge target (step 2): the query ticket's own recorded root cause/fix. Every TW
query wol-q-X has a memory twin wol-m-X (verified 6,773/6,773), whose
LLM-extracted root_cause/fix live in v2_kg_extractions/all_extractions.jsonl.

FIREWALL: the twin itself and the twins of every query sharing the query's
duplicate cluster (incident_episode_id = wol-incident-*; 266 clusters, size
2-4) are excluded from all four contexts.

Backend: local HuggingFace Qwen2.5-7B-Instruct greedy by default (reproducible,
cached on Trillium). Set EXTRINSIC_API_BASE / EXTRINSIC_API_KEY /
EXTRINSIC_MODEL for an OpenAI-compatible API instead (stronger-model
replication).

Usage (GPU node):
    python scripts/v2/extrinsic_rca_generate.py \
        --global-dir data/derived/global/2026-06-17-wol-real-v3-global \
        --predictions paper-results/retrieval-cascades/wol-v3/hybrid-rrf-predictions.jsonl \
        --out-dir paper-results-v2/extrinsic-rca --n 500
"""

from __future__ import annotations

import argparse
import hashlib
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
log = logging.getLogger("extrinsic-gen")

LOCAL_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_QUERY_CHARS = 1800
MAX_CTX_DOC_CHARS = 420
K_CONTEXT = 5

#: Generation prompt. One prompt for all four conditions; {context} is either a
#: rendered block or the exact string "(none)". Persisted into results verbatim.
GEN_PROMPT = (
    "You are a senior site-reliability engineer diagnosing a software incident.\n\n"
    "INCIDENT REPORT:\n{query}\n\n"
    "PAST RESOLVED INCIDENTS THAT MAY BE RELATED:\n{context}\n\n"
    "Based on the incident report{ctx_clause}, state the most likely root cause "
    "and a fix. Be specific to THIS incident. Answer in exactly this format:\n"
    "ROOT CAUSE: <one short paragraph>\n"
    "FIX: <one line>"
)


def tokenize(s: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9_]{2,}", (s or "").lower()))


def render_ctx_doc(ext: dict) -> str:
    """A past ticket as an investigation-context entry: cause, fix, symptoms.
    These are the fields a context builder surfaces; raw log bodies are not
    included so the context stays compact and comparable across conditions."""
    rc = (ext.get("root_cause") or "").strip()
    fx = (ext.get("fix") or "").strip()
    sy = ", ".join((ext.get("symptoms") or [])[:4])
    doc = f"Root cause: {rc}\n  Fix: {fx}"
    if sy:
        doc += f"\n  Symptoms: {sy}"
    return doc[:MAX_CTX_DOC_CHARS]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-new-tokens", type=int, default=220)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    G = args.global_dir

    # ---- memory-side extractions: targets + context docs -------------------
    ext_by_mid: dict[str, dict] = {}
    with (G / "v2_kg_extractions/all_extractions.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            ext_by_mid[d["ticket_id"]] = d
    log.info("memory extractions: %d", len(ext_by_mid))

    # ---- queries: test TW with text; project + duplicate cluster ------------
    queries: dict[str, dict] = {}
    cluster_members: dict[str, list[str]] = defaultdict(list)
    with (G / "global-triage-examples.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("triage_label") != "ticket_worthy":
                continue
            wid = d["window_id"]
            ep = d.get("incident_episode_id") or wid
            cluster_members[ep].append(wid)
            if d.get("split") == "test":
                queries[wid] = {
                    "text": (d.get("triage_evidence_text") or "")[:MAX_QUERY_CHARS],
                    "project": d.get("scenario_family") or "",
                    "episode": ep,
                }
    log.info("test TW queries: %d", len(queries))

    # ---- gold (coarse) ------------------------------------------------------
    gold: dict[str, list[str]] = {}
    with (G / "window-memory-matchings.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            ids = d.get("matched_memory_issue_ids") or []
            if ids and d["window_id"] in queries:
                gold[d["window_id"]] = ids

    # ---- system predictions (hybrid top-k) ----------------------------------
    preds: dict[str, list[str]] = {}
    with args.predictions.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d["window_id"] in queries:
                preds[d["window_id"]] = list(d.get("matched_issue_ids") or [])

    # ---- same-project pools for hard negatives ------------------------------
    by_proj: dict[str, list[str]] = defaultdict(list)
    for mid, ext in ext_by_mid.items():
        by_proj[ext.get("family") or ""].append(mid)

    def twin(wid: str) -> str:
        return "wol-m-" + wid[len("wol-q-"):]

    def firewall(wid: str) -> set[str]:
        """Memory ids that must never appear in any context for this query:
        the query's own twin plus the twins of its duplicate-cluster members."""
        out = {twin(wid)}
        for member in cluster_members.get(queries[wid]["episode"], [wid]):
            out.add(twin(member))
        return out

    # ---- eligibility + sampling (pre-registered: seed 42, n=500) ------------
    eligible = []
    for wid in sorted(queries):
        t = ext_by_mid.get(twin(wid))
        if not t or not (t.get("root_cause") or "").strip() or not (t.get("fix") or "").strip():
            continue
        if wid not in gold or wid not in preds or not queries[wid]["text"].strip():
            continue
        eligible.append(wid)
    log.info("eligible queries: %d", len(eligible))
    rng.shuffle(eligible)
    sample = eligible[: args.n]

    # ---- build the four contexts per query ----------------------------------
    cases = []
    n_short = {"arise": 0, "hard": 0, "oracle": 0}
    for wid in sample:
        q = queries[wid]
        fw = firewall(wid)
        goldset = set(gold[wid])

        arise_ids = [m for m in preds[wid] if m in ext_by_mid and m not in fw][:K_CONTEXT]
        oracle_ids = [m for m in gold[wid] if m in ext_by_mid and m not in fw][:K_CONTEXT]

        cands = [m for m in by_proj.get(q["project"], [])
                 if m not in goldset and m not in fw]
        pool = cands if len(cands) <= 400 else rng.sample(cands, 400)
        qt = tokenize(q["text"])
        pool.sort(key=lambda m: -len(qt & tokenize(render_ctx_doc(ext_by_mid[m]))))
        hard_ids = pool[:K_CONTEXT]

        for cond, ids in (("arise", arise_ids), ("hard", hard_ids), ("oracle", oracle_ids)):
            if len(ids) < K_CONTEXT:
                n_short[cond] += 1

        target = ext_by_mid[twin(wid)]
        cases.append({
            "window_id": wid,
            "project": q["project"],
            "query_text": q["text"],
            "target_root_cause": target["root_cause"],
            "target_fix": target["fix"],
            "contexts": {"none": [], "arise": arise_ids, "hard": hard_ids,
                         "oracle": oracle_ids},
        })
    log.info("cases: %d (contexts shorter than k=%d: %s)", len(cases), K_CONTEXT, n_short)

    # ---- backend -------------------------------------------------------------
    api_base = os.environ.get("EXTRINSIC_API_BASE")
    model_name = os.environ.get("EXTRINSIC_MODEL", LOCAL_MODEL)

    def make_prompts(batch):
        out = []
        for case, cond in batch:
            ids = case["contexts"][cond]
            if ids:
                ctx = "\n".join(f"{i+1}) {render_ctx_doc(ext_by_mid[m])}"
                                for i, m in enumerate(ids))
                clause = " and the past incidents above"
            else:
                ctx, clause = "(none)", ""
            out.append(GEN_PROMPT.format(query=case["query_text"],
                                         context=ctx, ctx_clause=clause))
        return out

    work = [(c, cond) for c in cases for cond in ("none", "arise", "hard", "oracle")]
    rng.shuffle(work)  # conditions interleaved; no condition-order artifacts
    log.info("generations to run: %d  (backend: %s)", len(work),
             api_base or f"local {model_name}")

    results, t0 = [], time.time()
    if api_base:
        # OpenAI-compatible API path (set EXTRINSIC_API_KEY, EXTRINSIC_MODEL).
        import urllib.request
        key = os.environ["EXTRINSIC_API_KEY"]
        for i, (case, cond) in enumerate(work):
            prompt = make_prompts([(case, cond)])[0]
            body = json.dumps({"model": model_name, "temperature": 0,
                               "max_tokens": args.max_new_tokens,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req = urllib.request.Request(
                f"{api_base.rstrip('/')}/chat/completions", data=body,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                hyp = json.load(r)["choices"][0]["message"]["content"]
            results.append({"window_id": case["window_id"], "condition": cond,
                            "hypothesis": hyp.strip(),
                            "prompt_sha1": hashlib.sha1(prompt.encode()).hexdigest()[:12]})
            if i % 50 == 0:
                log.info("  %d/%d (%.0fs)", i, len(work), time.time() - t0)
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
        for s in range(0, len(work), args.batch_size):
            batch = work[s:s + args.batch_size]
            prompts = make_prompts(batch)
            chat = [tok.apply_chat_template([{"role": "user", "content": p}],
                                            tokenize=False, add_generation_prompt=True)
                    for p in prompts]
            enc = tok(chat, return_tensors="pt", padding=True,
                      truncation=True, max_length=4096).to("cuda")
            with torch.no_grad():
                out = model.generate(**enc, max_new_tokens=args.max_new_tokens,
                                     do_sample=False, pad_token_id=tok.pad_token_id)
            gen = tok.batch_decode(out[:, enc["input_ids"].shape[1]:],
                                   skip_special_tokens=True)
            for (case, cond), p, g in zip(batch, prompts, gen):
                results.append({"window_id": case["window_id"], "condition": cond,
                                "hypothesis": g.strip(),
                                "prompt_sha1": hashlib.sha1(p.encode()).hexdigest()[:12]})
            if (s // args.batch_size) % 10 == 0:
                log.info("  %d/%d (%.0fs)", len(results), len(work), time.time() - t0)

    # ---- persist everything (verify_claims needs the raw artifacts) ---------
    (args.out_dir / "cases.jsonl").write_text(
        "\n".join(json.dumps(c) for c in cases), encoding="utf-8")
    (args.out_dir / "generations.jsonl").write_text(
        "\n".join(json.dumps(r) for r in results), encoding="utf-8")
    meta = {
        "model": model_name, "backend": api_base or "local-hf", "seed": args.seed,
        "n_queries": len(cases), "n_generations": len(results),
        "k_context": K_CONTEXT, "gen_prompt": GEN_PROMPT,
        "contexts_shorter_than_k": n_short,
        "elapsed_s": time.time() - t0,
    }
    (args.out_dir / "generate-meta.json").write_text(json.dumps(meta, indent=2),
                                                     encoding="utf-8")
    log.info("done: %d generations for %d queries in %.0fs",
             len(results), len(cases), time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
