"""Dense-retrieval baselines (reviewer W1/W4: 'a dense code retriever',
'jointly understands log semantics and code semantics'; fix #4: dense
similarity for incident retrieval).

On the SAME seeded 200-instance eval samples as noise_robustness.py:

  content_dense  dense twin of S3: cosine between the query embedding and
                 each candidate-pool file, a file represented by up to
                 4 chunks of ~350 words (max-pooled). Same candidate pool
                 as the lexical run.
  memory_dense   dense twin of S4: incidents retrieved by embedding
                 cosine instead of BM25; identical firewall and voting.
  cond_dense_*   the conditioned fusion with the dense signal swapped
                 into its lexical twin's slot, weights FROZEN from the
                 clean tuning (slightly unfavorable to dense; stated).

Model: BAAI/bge-small-en-v1.5 (33M params, CPU). Embeddings cached by
blob sha / issue key.

Usage:
    python industry-c7/scripts/dense_baselines.py --project kafka
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from function_stage import raw_blobs  # noqa: E402
from localize import (BENCH, FULL_REPOS, LIST_LEN, MEM_DEPTH, OUT,  # noqa: E402
                      PATH_POOL, PROJECTS, BM25Index, Snapshot, bm25_rank,
                      evaluate, load_support, parse_iso_epoch, path_tokens,
                      rrf, tokenize, trace_rank)

MODEL = "BAAI/bge-small-en-v1.5"
SEED = 42
SAMPLE = 200
CHUNK_WORDS = 350
MAX_CHUNKS = 4


def chunk(text: str) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + CHUNK_WORDS])
            for i in range(0, min(len(words), CHUNK_WORDS * MAX_CHUNKS),
                           CHUNK_WORDS)] or [""]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, choices=list(FULL_REPOS))
    args = ap.parse_args()
    cfg, git_dir = PROJECTS[args.project], FULL_REPOS[args.project]

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL, device="cpu")

    def embed(texts: list[str]) -> np.ndarray:
        return model.encode(texts, batch_size=64, convert_to_numpy=True,
                            normalize_embeddings=True,
                            show_progress_bar=False).astype(np.float32)

    bench = [json.loads(l) for l in
             (BENCH / f"{args.project}.jsonl").open(encoding="utf-8")]
    bench.sort(key=lambda b: b["fix_time"])
    summ = json.load((OUT / f"{args.project}-summary.json").open())
    n_dev, w_cond = summ["n_dev"], summ["tuned_weights"]["cond"]
    ev = bench[n_dev:]
    import random
    rng = random.Random(SEED)
    sample_b = [ev[i] for i in sorted(rng.sample(range(len(ev)),
                                                 min(SAMPLE, len(ev))))]

    mem_by_key, dupclusters, created_map, preds = load_support(
        args.project, cfg["key_prefix"])
    mem_index = BM25Index({k: r["toks"] for k, r in mem_by_key.items()})
    tok_cache = pickle.loads((OUT / f"blob-tokens-{args.project}.pkl")
                             .read_bytes())

    # ---- embed the whole memory pool once (ticket text) ----------------------
    # load_support keeps only tokens; raw ticket text comes from the pool file
    mem_text = {}
    for line in (BENCH / f"{args.project}-memory.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        mem_text[d["key"]] = (f"{d.get('summary') or ''}\n"
                              f"{d.get('text') or ''}")[:4000]
    t0 = time.time()
    mem_keys = [k for k in mem_by_key if k in mem_text]
    mem_emb = embed([mem_text[k] for k in mem_keys])
    print(f"memory pool embedded: {len(mem_keys)} in {time.time() - t0:.0f}s",
          flush=True)

    emb_cache_path = OUT / f"dense-blobs-{args.project}.pkl"
    emb_cache: dict[str, np.ndarray] = (pickle.loads(emb_cache_path.read_bytes())
                                        if emb_cache_path.exists() else {})

    def memory_votes(candidate_keys, b, cutoff, qcluster, snap):
        votes, rank = defaultdict(float), 0
        for key in candidate_keys:
            rec = mem_by_key.get(key)
            if (not rec or key == b["issue_key"]
                    or (qcluster is not None and dupclusters.get(key) == qcluster)
                    or rec["fix_shas"] & set(b["fix_shas"])
                    or (rec["resolved"] is not None and rec["resolved"] > cutoff)):
                continue
            rank += 1
            for f in rec["gold_files"]:
                if f in snap.blob_of:
                    votes[f] += 1.0 / rank
            if rank >= MEM_DEPTH:
                break
        return [f for f, _ in
                sorted(votes.items(), key=lambda x: (-x[1], x[0]))][:LIST_LEN]

    results = {s: [] for s in ("content_bm25", "content_dense", "memory_bm25",
                               "memory_dense", "cond_ours", "cond_dense_s3",
                               "cond_dense_s4", "cond_dense_both")}
    t0 = time.time()
    for i, b in enumerate(sample_b):
        snap = Snapshot(git_dir, b["snapshot_sha"], cfg["src_ext"])
        text = b["query_text"]
        qtoks = tokenize(text)
        cutoff = (parse_iso_epoch(b.get("created"))
                  or created_map.get(b["issue_key"]) or b["fix_time"])
        qcluster = dupclusters.get(b["issue_key"])

        trace_grep, has_mention, _ = trace_rank(text, snap)
        path_docs = {f: path_tokens(f) for f in snap.files}
        path_ranked = [f for f, _ in bm25_rank(qtoks, path_docs)][:LIST_LEN]
        memory_arise = memory_votes(preds.get(b["window_id"], []), b, cutoff,
                                    qcluster, snap)
        memory_bm25 = memory_votes(mem_index.rank(qtoks, MEM_DEPTH * 4), b,
                                   cutoff, qcluster, snap)
        q_emb = embed([text[:8000]])[0]
        order = np.argsort(-(mem_emb @ q_emb))[:MEM_DEPTH * 4]
        memory_dense = memory_votes([mem_keys[j] for j in order], b, cutoff,
                                    qcluster, snap)

        pool = list(dict.fromkeys(trace_grep + path_ranked[:PATH_POOL]
                                  + memory_arise + memory_bm25 + memory_dense))
        docs = snap.contents(pool, tok_cache)
        content_bm25 = [f for f, _ in bm25_rank(qtoks, docs)][:LIST_LEN]

        # dense twin of S3 over the same pool
        need = [(p_, snap.blob_of[p_]) for p_ in pool
                if p_ in snap.blob_of and snap.blob_of[p_] not in emb_cache]
        if need:
            texts = raw_blobs(git_dir, [bl for _, bl in need])
            todo_keys, todo_chunks, spans = [], [], []
            for p_, bl in need:
                ch = chunk(texts.get(bl, b"").decode("utf-8", "replace"))
                spans.append((bl, len(ch)))
                todo_chunks.extend(ch)
            vecs = embed(todo_chunks)
            pos = 0
            for bl, k in spans:
                emb_cache[bl] = vecs[pos:pos + k]
                pos += k
        scored = []
        for p_ in pool:
            bl = snap.blob_of.get(p_)
            if bl is None or bl not in emb_cache or not len(emb_cache[bl]):
                continue
            scored.append((p_, float((emb_cache[bl] @ q_emb).max())))
        scored.sort(key=lambda x: (-x[1], x[0]))
        content_dense = [p_ for p_, _ in scored][:LIST_LEN]

        rk = {"trace_grep": trace_grep, "path_bm25": path_ranked,
              "content_bm25": content_bm25, "memory_arise": memory_arise,
              "memory_bm25": memory_bm25}
        regime = "mention" if has_mention else "no_mention"
        w = w_cond[regime]
        variants = {
            "cond_ours": rk,
            "cond_dense_s3": {**rk, "content_bm25": content_dense},
            "cond_dense_s4": {**rk, "memory_bm25": memory_dense},
            "cond_dense_both": {**rk, "content_bm25": content_dense,
                                "memory_bm25": memory_dense},
        }
        gold = b["gold_files"]
        for name, ranking in (("content_bm25", content_bm25),
                              ("content_dense", content_dense),
                              ("memory_bm25", memory_bm25),
                              ("memory_dense", memory_dense)):
            results[name].append(evaluate(ranking, gold))
        for name, rks in variants.items():
            results[name].append(evaluate(rrf(rks, w), gold))
        if i % 20 == 0:
            print(f"  {i}/{len(sample_b)} ({time.time() - t0:.0f}s, "
                  f"emb cache {len(emb_cache)})", flush=True)
            emb_cache_path.write_bytes(pickle.dumps(emb_cache))
    emb_cache_path.write_bytes(pickle.dumps(emb_cache))

    def agg(ms):
        return {m: round(sum(x[m] for x in ms) / len(ms), 4)
                for m in ("acc@5", "mrr")}
    summary = {"project": args.project, "model": MODEL, "seed": SEED,
               "n_sample": len(sample_b), "chunks": f"{MAX_CHUNKS}x{CHUNK_WORDS}w",
               "weights": "clean-tuned cond (frozen)",
               "systems": {k: agg(v) for k, v in results.items()}}
    (OUT / f"{args.project}-dense-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["systems"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
