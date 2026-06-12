"""Train LogSeq2Vec contrastively on (window-log-sequence, jira-ticket-text) pairs.

Builds positive pairs from train+val windows where matched_memory_issue_ids
is non-empty. For each pair: encode the window's log sequence with the
two-stage model, encode the gold ticket's memory_text with the same line
encoder (single-line case), and pull them together via cosine similarity.
In-batch negatives + 3 BM25-mined hard negatives per positive.

The training objective is symmetric InfoNCE (MultipleNegativesRankingLoss-equivalent
implemented directly so we don't need sentence-transformers' Trainer):

    loss = -log( exp(s(a, p) / τ) / Σ_b exp(s(a, b) / τ) )

where a = anchor (window), p = positive (gold ticket text), and the
denominator sums over the positive + all in-batch + hard negatives.

This is fast: ~3-5 minutes on the RTX 5060 for 5 epochs over ~1.8K windows.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from v2_advanced.shared import get_logger, log_step

log = get_logger("phase_b.train")


def _load_logseq(path: Path, max_lines: int = 80) -> list[str]:
    """Read a per-window logseq file; return the line strings only.

    `data_prep.py` writes one JSON-line per log line with keys
    {ts_ns, service, severity, line}. We concatenate service+line so the
    line encoder knows which service emitted what.
    """
    out = []
    try:
        with path.open(encoding="utf-8") as fh:
            for ln in fh:
                if not ln.strip():
                    continue
                row = json.loads(ln)
                svc = row.get("service", "?")
                line = row.get("line", "")
                out.append(f"[{svc}] {line}")
                if len(out) >= max_lines:
                    break
    except (json.JSONDecodeError, OSError):
        pass
    return out


def build_train_pairs(
    *,
    global_dir: Path,
    train_split: str = "train_plus_val",   # train+val together
    humanized_subdir: str = "bulk-20260531",
    humanized_root: str = "jira-shadow-humanized-v2",
    logseq_subdir: str = "v2_logseq",
    max_lines: int = 80,
    n_hard_negs: int = 3,
    bm25_top_n: int = 20,
    seed: int = 42,
):
    """Yield (anchor_log_lines, positive_doc_text, [neg_doc_text, ...])
    triples for contrastive training."""
    from core.data.loaders import load_dataset
    from core.data.splits import iter_split
    from core.features.text import build_memory_doc_text
    from core.memory.corpus import MemoryCorpus
    from core.memory.retrieval import BM25Retriever
    from memorygraph.humanized_loader import load_humanized_corpus

    ds = load_dataset(global_dir)
    if train_split == "train_plus_val":
        windows = list(iter_split(ds.windows, ds.split_manifest, "train")) + \
                  list(iter_split(ds.windows, ds.split_manifest, "validation"))
    else:
        windows = list(iter_split(ds.windows, ds.split_manifest, train_split))

    memory = load_humanized_corpus(
        global_dir, humanized_subdir=humanized_subdir, humanized_root=humanized_root,
    )
    corpus = MemoryCorpus(issues=memory, mode="time_ordered")
    by_id = corpus.by_id()
    log.info("building train pairs", n_windows=len(windows), n_memory=len(memory))

    bm25 = BM25Retriever()
    bm25.fit(corpus)
    log.info("BM25 index built for hard-neg mining")

    rng = random.Random(seed)
    logseq_root = global_dir / logseq_subdir

    pairs = []
    skipped_no_gold = 0
    skipped_no_logs = 0
    skipped_no_visible_gold = 0
    for w in windows:
        gold_ids = list(getattr(w, "matched_memory_issue_ids", None) or [])
        if not gold_ids:
            skipped_no_gold += 1
            continue
        visible = {iss.jira_shadow_issue_id for iss in corpus.visible_to(w)}
        gold_in_view = [g for g in gold_ids if g in visible and g in by_id]
        if not gold_in_view:
            skipped_no_visible_gold += 1
            continue

        logseq_path = logseq_root / f"{w.window_id}.jsonl"
        log_lines = _load_logseq(logseq_path, max_lines=max_lines) if logseq_path.exists() else []
        if not log_lines:
            skipped_no_logs += 1
            continue

        # BM25 hard negatives
        hits = bm25.retrieve(w, corpus, top_k=bm25_top_n)
        gold_set = set(gold_in_view)
        wrong = [h for h in hits if h.issue_id not in gold_set]
        for gid in gold_in_view:
            pos_doc = (build_memory_doc_text(by_id[gid]) or "")[:512]
            neg_docs = []
            if wrong and n_hard_negs > 0:
                chosen = rng.sample(wrong, min(n_hard_negs, len(wrong)))
                neg_docs = [(build_memory_doc_text(h.issue) or "")[:512] for h in chosen]
            pairs.append((log_lines, pos_doc, neg_docs))

    log.info(
        "train pairs built",
        n=len(pairs),
        skipped_no_gold=skipped_no_gold,
        skipped_no_visible_gold=skipped_no_visible_gold,
        skipped_no_logs=skipped_no_logs,
    )
    return pairs


def train_logseq2vec(
    pairs: list[tuple[list[str], str, list[str]]],
    *,
    epochs: int = 5,
    batch_size: int = 8,        # batch is small because each example has variable-length log seq
    lr: float = 2e-4,
    temperature: float = 0.07,
    line_encoder_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    freeze_line_encoder: bool = True,
    d_model: int = 384,
    n_layers: int = 2,
    n_heads: int = 4,
    max_seq: int = 80,
    seed: int = 42,
    out_dir: Path | None = None,
):
    """Train the LogSeq2Vec model. Returns the trained model."""
    from .model import LogSeq2Vec

    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("training", n_pairs=len(pairs), epochs=epochs, batch_size=batch_size, device=device)

    model = LogSeq2Vec(
        line_encoder_name=line_encoder_name,
        d_model=d_model, n_layers=n_layers, n_heads=n_heads, max_seq=max_seq,
        freeze_line_encoder=freeze_line_encoder, device=device,
    )
    optim = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=lr, weight_decay=1e-4,
    )

    with log_step(log, "train_loop", epochs=epochs):
        for ep in range(epochs):
            rng = random.Random(seed + ep)
            indices = list(range(len(pairs)))
            rng.shuffle(indices)
            total_loss = 0.0
            n_batches = 0
            for start in range(0, len(indices), batch_size):
                idx = indices[start:start + batch_size]
                batch = [pairs[i] for i in idx]

                anchors = [p[0] for p in batch]      # list of list-of-lines
                positives = [p[1] for p in batch]    # list of strings
                hard_negs_flat = []
                for _, _, negs in batch:
                    hard_negs_flat.extend(negs)

                # Encode anchors (windows)
                anchor_vecs = model.encode_batch_windows(anchors)  # (B, d)

                # Encode positives + hard negatives as single-line "docs"
                all_docs_text = positives + hard_negs_flat
                doc_vecs_raw = model.encode_lines(all_docs_text)
                # Project + L2-normalize via the aggregator's projector? No — we want
                # docs in the same space as anchors, which IS aggregator output. Pass
                # each as a 1-line "window" to the aggregator.
                doc_vecs = model.encode_batch_windows([[t] for t in all_docs_text])

                # Build the contrastive matrix: each anchor's positive at column i,
                # all other anchors' positives + all hard_negs are negatives.
                B = len(anchors)
                # doc_vecs[:B] = positives, doc_vecs[B:] = hard_negs
                # cosine similarity (vectors are L2-normalized by aggregator)
                sim = anchor_vecs @ doc_vecs.T  # (B, B + n_hard_negs)
                sim = sim / temperature
                targets = torch.arange(B, device=sim.device)
                loss = F.cross_entropy(sim, targets)

                optim.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optim.step()

                total_loss += float(loss.item())
                n_batches += 1
            log.info(
                f"epoch {ep+1}/{epochs} done",
                avg_loss=round(total_loss / max(1, n_batches), 4),
                n_batches=n_batches,
            )

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "aggregator_state": model.aggregator.state_dict(),
                "config": {
                    "line_encoder_name": line_encoder_name,
                    "d_model": d_model,
                    "n_layers": n_layers,
                    "n_heads": n_heads,
                    "max_seq": max_seq,
                    "freeze_line_encoder": freeze_line_encoder,
                },
            },
            out_dir / "logseq2vec.pt",
        )
        log.info("saved model", path=str(out_dir / "logseq2vec.pt"))

    return model


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--max-lines", type=int, default=80)
    p.add_argument("--n-hard-negs", type=int, default=3)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    t0 = time.time()
    pairs = build_train_pairs(
        global_dir=args.global_dir,
        max_lines=args.max_lines,
        n_hard_negs=args.n_hard_negs,
        seed=args.seed,
    )
    if not pairs:
        raise SystemExit("no training pairs built — run data_prep first?")
    train_logseq2vec(
        pairs,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        max_seq=args.max_lines,
        seed=args.seed,
        out_dir=args.out_dir,
    )
    log.info("DONE", elapsed_s=round(time.time() - t0, 1))


if __name__ == "__main__":
    main()
