"""Phase B1+B2 — build (window, ticket) training pairs + hard negatives.

For each train-split window with non-empty gold_matched_issue_ids:
  - Emit positive pairs: (query_text, gold_ticket_text, label=1)
  - Use BM25 over the visible memory to retrieve top-N candidates;
    sample 2 hard negatives (top-ranked candidates NOT in gold).

Output: results/phase-b-finetune/triplets.jsonl with rows:
    {"query": "...", "doc": "...", "label": 0|1, "window_id": ..., "memory_id": ...}

We use the *same* query_text and memory_text builders the pipeline uses
so the fine-tuned model sees the same input distribution at predict time.

Move-A log signatures are folded into the query: when the window has a
characteristic log line, that line is appended to the query text. This
matches the SOTA pipeline's `with_log_signatures=True` setting.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

# Make src/ importable
import sys
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.data.loaders import load_dataset
from core.data.splits import iter_split
from core.features.text import build_memory_doc_text, build_window_query_text
from core.memory.corpus import MemoryCorpus
from core.memory.retrieval import BM25Retriever
from memorygraph.humanized_loader import load_humanized_corpus


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--humanized-subdir", default="bulk-20260531")
    p.add_argument("--humanized-root", default="jira-shadow-humanized-v2")
    p.add_argument("--n-hard-negs", type=int, default=3,
                   help="Hard negatives per positive pair")
    p.add_argument("--bm25-top-n", type=int, default=20,
                   help="BM25 top-N to sample hard negatives from")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    print(f"[build_crossenc_pairs] loading dataset from {args.global_dir}")
    ds = load_dataset(args.global_dir)
    train = list(iter_split(ds.windows, ds.split_manifest, "train"))
    val = list(iter_split(ds.windows, ds.split_manifest, "validation"))
    print(f"[build_crossenc_pairs] train={len(train)} val={len(val)}")

    # V2 humanized memory
    print(f"[build_crossenc_pairs] loading humanized corpus "
          f"{args.humanized_root}/{args.humanized_subdir}")
    ds.memory_corpus = load_humanized_corpus(
        args.global_dir,
        humanized_subdir=args.humanized_subdir,
        humanized_root=args.humanized_root,
    )
    corpus = MemoryCorpus(issues=ds.memory_corpus, mode="time_ordered")
    by_id = corpus.by_id()
    print(f"[build_crossenc_pairs] memory has {len(ds.memory_corpus)} tickets")

    # BM25 over the full corpus, time-ordering respected at retrieve time.
    print("[build_crossenc_pairs] fitting BM25 over corpus")
    bm25 = BM25Retriever()
    bm25.fit(corpus)

    rng = random.Random(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_pos = 0
    n_neg = 0
    n_windows = 0
    n_skip_no_gold = 0
    n_skip_gold_not_visible = 0

    with args.out.open("w", encoding="utf-8") as f:
        for window in train + val:
            gold_ids = list(
                getattr(window, "matched_memory_issue_ids", None)
                or window.raw.get("matched_memory_issue_ids", [])
                or []
            )
            if not gold_ids:
                n_skip_no_gold += 1
                continue
            visible = corpus.visible_to(window)
            visible_ids = {iss.jira_shadow_issue_id for iss in visible}
            gold_in_view = [gid for gid in gold_ids if gid in visible_ids]
            if not gold_in_view:
                n_skip_gold_not_visible += 1
                continue

            query_text = build_window_query_text(window)
            window_split = (
                "val" if window.window_id in {w.window_id for w in val}
                else "train"
            )
            n_windows += 1
            # Positive pairs
            for gid in gold_in_view:
                doc_text = build_memory_doc_text(by_id[gid])
                row = {
                    "query": query_text,
                    "doc": doc_text,
                    "label": 1,
                    "window_id": window.window_id,
                    "memory_id": gid,
                    "split": window_split,
                }
                f.write(json.dumps(row) + "\n")
                n_pos += 1

            # Hard negatives via BM25
            hits = bm25.retrieve(window, corpus, top_k=args.bm25_top_n)
            wrong = [h for h in hits if h.issue_id not in set(gold_in_view)]
            if wrong:
                sampled = rng.sample(wrong, min(args.n_hard_negs, len(wrong)))
                for h in sampled:
                    doc_text = build_memory_doc_text(h.issue)
                    row = {
                        "query": query_text,
                        "doc": doc_text,
                        "label": 0,
                        "window_id": window.window_id,
                        "memory_id": h.issue_id,
                        "bm25_rank": h.rank,
                        "split": window_split,
                    }
                    f.write(json.dumps(row) + "\n")
                    n_neg += 1

    print(f"[build_crossenc_pairs] wrote {args.out}")
    print(f"  windows kept: {n_windows}")
    print(f"  positives: {n_pos}")
    print(f"  hard negatives: {n_neg}")
    print(f"  skipped (no gold): {n_skip_no_gold}")
    print(f"  skipped (gold not visible): {n_skip_gold_not_visible}")


if __name__ == "__main__":
    main()
