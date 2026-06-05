"""LogSeq2Vec neural model — two-stage architecture.

  Stage 1 — line encoder: sentence-transformers/all-MiniLM-L6-v2
            Embed each log line into a 384-d vector (we DON'T re-train
            this initially; only fine-tune the aggregator). Pretraining
            could come later — see EXPERIMENTS-B.md.

  Stage 2 — sequence aggregator: a tiny 2-layer Transformer encoder
            that consumes the sequence of (up to N) line embeddings,
            plus a learned [CLS] token, plus learned positional
            embeddings. The [CLS] output, mean-pooled with the
            non-CLS positions, is the window's 384-d vector.

The full model is trained contrastively on (window, gold-ticket) pairs:
positive pairs (the window's log sequence + the ticket's text) pull
together in embedding space; in-batch negatives + BM25 hard negatives
push apart.
"""
from __future__ import annotations

import math
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F


class SequenceAggregator(nn.Module):
    """Tiny Transformer encoder + learned [CLS] over a fixed-max
    sequence of line embeddings."""

    def __init__(
        self,
        *,
        d_in: int = 384,
        d_model: int = 384,
        n_heads: int = 4,
        n_layers: int = 2,
        max_seq: int = 100,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.d_in = d_in
        self.d_model = d_model
        self.max_seq = max_seq
        # Project line embeddings into model dim (no-op when d_in == d_model)
        self.proj = nn.Linear(d_in, d_model) if d_in != d_model else nn.Identity()
        self.cls = nn.Parameter(torch.empty(1, 1, d_model))
        nn.init.normal_(self.cls, std=0.02)
        self.pos = nn.Parameter(torch.empty(1, max_seq + 1, d_model))
        nn.init.normal_(self.pos, std=0.02)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_model * 4,
            dropout=dropout, activation="gelu", batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(d_model)

    def forward(
        self,
        x: torch.Tensor,                    # (B, T, d_in)
        attn_mask: torch.Tensor | None = None,  # (B, T) bool, True = real
    ) -> torch.Tensor:
        # x: (B, T, d_in) -> (B, T, d_model)
        b, t, _ = x.shape
        if t > self.max_seq:
            x = x[:, :self.max_seq]
            if attn_mask is not None:
                attn_mask = attn_mask[:, :self.max_seq]
            t = self.max_seq
        proj = self.proj(x)
        cls = self.cls.expand(b, -1, -1)
        seq = torch.cat([cls, proj], dim=1)               # (B, T+1, d_model)
        seq = seq + self.pos[:, :seq.size(1)]
        # Build a key_padding_mask for the Transformer: True = pad.
        if attn_mask is not None:
            pad = torch.cat([
                torch.zeros(b, 1, dtype=torch.bool, device=x.device),
                ~attn_mask.bool(),
            ], dim=1)
        else:
            pad = None
        out = self.encoder(seq, src_key_padding_mask=pad)
        cls_out = self.norm(out[:, 0])                    # (B, d_model)
        # L2-normalize for cosine similarity
        return F.normalize(cls_out, dim=-1)


class LogSeq2Vec(nn.Module):
    """End-to-end model: pre-loaded line encoder + trainable aggregator.

    The line encoder is a frozen `sentence-transformers/all-MiniLM-L6-v2`
    by default; we don't backprop through it (saves ~50% memory). Set
    `freeze_line_encoder=False` to fine-tune it jointly.
    """

    def __init__(
        self,
        *,
        line_encoder_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        d_model: int = 384,
        n_layers: int = 2,
        n_heads: int = 4,
        max_seq: int = 100,
        dropout: float = 0.1,
        freeze_line_encoder: bool = True,
        device: str | None = None,
    ) -> None:
        super().__init__()
        from sentence_transformers import SentenceTransformer
        self.device_name = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.line_encoder = SentenceTransformer(line_encoder_name, device=self.device_name)
        # Freeze line encoder if requested
        if freeze_line_encoder:
            for p in self.line_encoder.parameters():
                p.requires_grad = False
        self.freeze_line_encoder = freeze_line_encoder
        d_line = self.line_encoder.get_sentence_embedding_dimension()
        self.aggregator = SequenceAggregator(
            d_in=d_line, d_model=d_model, n_heads=n_heads, n_layers=n_layers,
            max_seq=max_seq, dropout=dropout,
        ).to(self.device_name)
        self.max_seq = max_seq

    def encode_lines(self, lines: list[str]) -> torch.Tensor:
        """Embed a batch of log line strings into (B, d_line) tensors."""
        if not lines:
            return torch.zeros(0, self.line_encoder.get_sentence_embedding_dimension(), device=self.device_name)
        with torch.no_grad() if self.freeze_line_encoder else torch.enable_grad():
            vecs = self.line_encoder.encode(
                lines, convert_to_tensor=True, show_progress_bar=False,
                device=self.device_name,
            )
        return vecs

    def encode_window(self, lines: list[str]) -> torch.Tensor:
        """Embed one window's sequence of log lines into a single 384-d
        vector. Returns (d_model,) tensor.
        """
        if not lines:
            # Empty windows get the [CLS]-only output (no lines to attend to)
            empty = torch.zeros(
                1, 0, self.aggregator.d_in, device=self.device_name,
            )
            mask = torch.zeros(1, 0, dtype=torch.bool, device=self.device_name)
            v = self.aggregator(empty, mask)
            return v.squeeze(0)
        line_vecs = self.encode_lines(lines[:self.max_seq])
        x = line_vecs.unsqueeze(0)
        mask = torch.ones(1, x.size(1), dtype=torch.bool, device=self.device_name)
        v = self.aggregator(x, mask)
        return v.squeeze(0)

    def encode_text(self, text: str) -> torch.Tensor:
        """Embed a single text (used for the ticket-side at contrastive time)."""
        line_vecs = self.encode_lines([text])
        x = line_vecs.unsqueeze(0)
        mask = torch.ones(1, x.size(1), dtype=torch.bool, device=self.device_name)
        v = self.aggregator(x, mask)
        return v.squeeze(0)

    def encode_batch_windows(self, batches_lines: list[list[str]]) -> torch.Tensor:
        """Embed a batch of windows (variable-length log sequences) in one
        forward pass. Pads to the longest sequence in the batch.
        """
        if not batches_lines:
            return torch.zeros(0, self.aggregator.d_model, device=self.device_name)
        # Embed all lines flat, then split back into per-window tensors
        max_t = min(self.max_seq, max(len(s) for s in batches_lines)) or 1
        b = len(batches_lines)
        # Truncate
        batches_lines = [s[:max_t] for s in batches_lines]
        flat = []
        offsets = [0]
        for s in batches_lines:
            flat.extend(s)
            offsets.append(offsets[-1] + len(s))
        if not flat:
            flat = [""]
        all_vecs = self.encode_lines(flat)
        d = all_vecs.size(-1)
        out = torch.zeros(b, max_t, d, device=self.device_name)
        mask = torch.zeros(b, max_t, dtype=torch.bool, device=self.device_name)
        for i in range(b):
            n = offsets[i + 1] - offsets[i]
            if n > 0:
                out[i, :n] = all_vecs[offsets[i]:offsets[i + 1]]
                mask[i, :n] = True
        return self.aggregator(out, mask)
