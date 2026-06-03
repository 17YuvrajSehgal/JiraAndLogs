"""Proposal B — LogSeq2Vec encoder over raw log lines.

Two-stage architecture:

  Stage 1 — line encoder: a small Transformer that embeds individual log
            lines into 128-d vectors. We initialize from MiniLM-L6 (which
            we already use elsewhere) and fine-tune on log-line text.

  Stage 2 — sequence aggregator: a tiny Transformer that consumes the
            sequence of line embeddings for one window and outputs a
            single 384-d window embedding via attention pooling.

The two stages can be fine-tuned jointly (end-to-end) on (window,
gold-ticket) contrastive pairs, OR the line encoder can be frozen and
only the aggregator trained.

For this iteration we use MiniLM as the line encoder (no pretraining —
the pretraining sketch is preserved in EXPERIMENTS-B.md for future
work) and train only the aggregator end-to-end. This gives most of the
benefit with ~30 minutes of training instead of 12 hours of pretraining.

Files:
    data_prep.py    parse Loki JSON dumps -> per-window log line sequences
    model.py        the two-stage neural model
    train.py        contrastive training on (window, gold-ticket) pairs
    pipeline.py     full PipelineRunner using LogSeq2Vec as the retriever
"""
