"""Prior-art retrieval baselines for the ICSE comparison (review.md gap #1).

Runs published, widely-used retrieval methods ZERO-SHOT on a dataset's
test split, under the SAME memory/visibility/gold contract as our pipelines,
and writes predictions + Hit@1/5/10 + MRR (coarse + strong gold) to a clean
results dir.

Methods (--method):
  bge   : BAAI/bge-large-en-v1.5            (SOTA dense, query instruction)
  e5    : intfloat/e5-large-v2              (SOTA dense, query:/passage: prefixes)
  mpnet : sentence-transformers/all-mpnet-base-v2  (strong general dense)
  tfidf : TF-IDF + cosine                   (classic IR)
  ce    : bge dense top-k re-ranked by cross-encoder/ms-marco-MiniLM-L-6-v2

Usage:
  python scripts/research-lab/run_baseline_retrievers.py \
      --global-dir data/derived/global/<id> --humanized-subdir <sub> \
      --method bge --out-dir paper-results/baselines/sota-dense/<dataset>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from core.data.loaders import load_dataset
from core.data.splits import iter_split
from core.memory.corpus import MemoryCorpus
from core.features.text import build_memory_doc_text, build_window_query_text
from memorygraph.humanized_loader import load_humanized_corpus

MAX_CHARS = 512
TOP_K = 10
CE_CANDIDATES = 50  # dense top-N fed to the cross-encoder

_MODELS = {
    "bge": "BAAI/bge-large-en-v1.5",
    "e5": "intfloat/e5-large-v2",
    "mpnet": "sentence-transformers/all-mpnet-base-v2",
}


def _q(method: str, text: str) -> str:
    if method == "e5":
        return f"query: {text}"
    if method == "bge":
        return f"Represent this sentence for searching relevant passages: {text}"
    return text


def _d(method: str, text: str) -> str:
    return f"passage: {text}" if method == "e5" else text


def _encode(model, texts, device, bs=128):
    return np.asarray(
        model.encode(texts, batch_size=bs, convert_to_numpy=True,
                     normalize_embeddings=True, show_progress_bar=True,
                     device=device),
        dtype=np.float32,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--humanized-subdir", required=True)
    ap.add_argument("--humanized-root", default="jira-shadow-humanized-v2")
    ap.add_argument("--method", required=True, choices=list(_MODELS) + ["tfidf", "bm25", "ce"])
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=0, help="0 = all test windows")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[baseline:{args.method}] global={args.global_dir.name} device={device}", flush=True)

    ds = load_dataset(args.global_dir)
    # OB/OTel use the v2-resplit window_assignment (the paper's eval split);
    # WoL has no resplit -> fall back to the default split manifest.
    resplit = args.global_dir / "triage-split-manifest-v2-resplit.json"
    wa = None
    if resplit.exists():
        try:
            wa = json.loads(resplit.read_text(encoding="utf-8")).get("window_assignment")
        except Exception:                                            # noqa: BLE001
            wa = None
    if wa:
        test_w = [w for w in ds.windows if wa.get(w.window_id) == args.split]
        print(f"[baseline] v2-resplit split={args.split}: {len(test_w)} windows", flush=True)
    else:
        test_w = list(iter_split(ds.windows, ds.split_manifest, args.split))
    if args.limit:
        test_w = test_w[: args.limit]
    memory = load_humanized_corpus(args.global_dir, humanized_subdir=args.humanized_subdir,
                                   humanized_root=args.humanized_root)
    corpus = MemoryCorpus(issues=memory, mode="time_ordered")
    mem_ids = [m.jira_shadow_issue_id for m in memory]
    id2idx = {mid: i for i, mid in enumerate(mem_ids)}
    mem_texts = [(build_memory_doc_text(m) or "")[:MAX_CHARS] for m in memory]
    q_texts = [(build_window_query_text(w) or "")[:MAX_CHARS] for w in test_w]
    print(f"[baseline] memory={len(memory)} test={len(test_w)}", flush=True)

    t0 = time.time()
    # --- score matrix (queries x memory) ---
    if args.method == "tfidf":
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(min_df=2, sublinear_tf=True)
        M = vec.fit_transform(mem_texts)          # (Nmem, V)
        Q = vec.transform(q_texts)                # (Nq, V)
        sims = (Q @ M.T).toarray().astype(np.float32)   # cosine (l2-normalized tfidf)
    elif args.method == "bm25":
        # Fair BM25 over the SAME (humanized) memory the dense methods use,
        # so the lexical baseline is comparable (the cascade BM25 indexes the
        # raw jira-memory-corpus, which differs on OB/OTel).
        from rank_bm25 import BM25Okapi
        from comparison.retrievers import tokenize
        bm = BM25Okapi([tokenize(t) for t in mem_texts])
        sims = np.zeros((len(q_texts), len(mem_texts)), dtype=np.float32)
        for i, qt in enumerate(q_texts):
            sims[i] = bm.get_scores(tokenize(qt))
    elif args.method in _MODELS:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(_MODELS[args.method], device=device)
        mem_emb = _encode(model, [_d(args.method, t) for t in mem_texts], device)
        q_emb = _encode(model, [_q(args.method, t) for t in q_texts], device)
        sims = q_emb @ mem_emb.T                  # (Nq, Nmem)
    elif args.method == "ce":
        from sentence_transformers import SentenceTransformer, CrossEncoder
        dense = SentenceTransformer(_MODELS["bge"], device=device)
        mem_emb = _encode(dense, [_d("bge", t) for t in mem_texts], device)
        q_emb = _encode(dense, [_q("bge", t) for t in q_texts], device)
        sims = q_emb @ mem_emb.T
        ce = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device=device)

    # --- per-window ranking with time-ordered visibility ---
    predictions = []
    for i, w in enumerate(test_w):
        visible = {m.jira_shadow_issue_id for m in corpus.visible_to(w)}
        row = sims[i]
        order = np.argsort(-row)
        if args.method == "ce":
            # take dense top-N visible candidates, then cross-encode rerank
            cand = []
            for j in order:
                mid = mem_ids[j]
                if mid in visible:
                    cand.append(j)
                if len(cand) >= CE_CANDIDATES:
                    break
            if cand:
                pairs = [[q_texts[i], mem_texts[j]] for j in cand]
                ce_scores = ce.predict(pairs, batch_size=128, show_progress_bar=False)
                cand = [j for _, j in sorted(zip(ce_scores, cand), key=lambda x: -x[0])]
            top = [mem_ids[j] for j in cand[:TOP_K]]
        else:
            top = []
            for j in order:
                mid = mem_ids[j]
                if mid in visible:
                    top.append(mid)
                if len(top) >= TOP_K:
                    break
        predictions.append({
            "window_id": w.window_id,
            "matched_issue_ids": top,
            "gold_matched_issue_ids": list(w.matched_memory_issue_ids or []),
            "scenario_family": getattr(w, "scenario_family", None),
        })
    elapsed = time.time() - t0
    print(f"[baseline] scored {len(predictions)} windows in {elapsed:.1f}s", flush=True)

    # --- gold: coarse (per-window) + strong (file, if present) ---
    strong_path = args.global_dir / "window-memory-matchings-strong.jsonl"
    strong = {}
    if strong_path.exists():
        for line in strong_path.open(encoding="utf-8"):
            d = json.loads(line)
            strong[d["window_id"]] = set(d.get("matched_memory_issue_ids") or [])

    def metrics(gold_lookup, label):
        h1 = h5 = h10 = n = 0
        mrr = 0.0
        per = defaultdict(lambda: {"n": 0, "h1": 0, "h5": 0})
        for p in predictions:
            gold = set(p["gold_matched_issue_ids"]) if gold_lookup is None else gold_lookup.get(p["window_id"], set())
            if not gold:
                continue
            n += 1
            proj = p.get("scenario_family") or "?"
            per[proj]["n"] += 1
            for r, t in enumerate(p["matched_issue_ids"], 1):
                if t in gold:
                    if r == 1: h1 += 1; per[proj]["h1"] += 1
                    if r <= 5: h5 += 1; per[proj]["h5"] += 1
                    if r <= 10: h10 += 1
                    mrr += 1.0 / r
                    break
        return {
            "label": label, "n_with_gold": n,
            "hit_at_1": h1 / max(1, n), "hit_at_5": h5 / max(1, n),
            "hit_at_10": h10 / max(1, n), "mrr": mrr / max(1, n),
            "per_project": {k: {"n": v["n"], "hit_at_1": v["h1"]/max(1,v["n"]),
                                "hit_at_5": v["h5"]/max(1,v["n"])} for k, v in per.items()},
        }

    results = {
        "method": args.method, "model": _MODELS.get(args.method, args.method),
        "global_dir": str(args.global_dir), "split": args.split,
        "n_memory": len(memory), "n_test": len(test_w), "elapsed_s": elapsed,
        "coarse": metrics(None, "coarse"),
        "strong": metrics(strong, "strong") if strong else None,
    }
    pred_path = args.out_dir / f"{args.method}-predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as fh:
        for p in predictions:
            fh.write(json.dumps(p) + "\n")
    (args.out_dir / f"{args.method}-results.json").write_text(json.dumps(results, indent=2))
    c = results["coarse"]
    print(f"[baseline:{args.method}] coarse Hit@1={c['hit_at_1']:.4f} "
          f"Hit@5={c['hit_at_5']:.4f} MRR={c['mrr']:.4f} (n={c['n_with_gold']})", flush=True)
    print(f"[baseline] wrote {pred_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
