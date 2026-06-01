"""Phase B3 — fine-tune MS-MARCO MiniLM cross-encoder on our pairs.

Reads `triplets.jsonl` produced by `build_crossenc_pairs.py` and fine-
tunes `cross-encoder/ms-marco-MiniLM-L-6-v2` with sentence-transformers
`CrossEncoder` API. Train split rows are used for training, val split
rows for early stopping.

Output: results/phase-b-finetune/crossenc_ft_v1/ (the local model dir
that `CrossEncoderRerankSkill` can load by passing a local path).

The architecture intentionally stays small: 6-layer MiniLM, ~22M params.
We're not building a foundation model — we're shifting a small reranker's
prior toward our domain.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from sentence_transformers import CrossEncoder
from sentence_transformers.cross_encoder.evaluation import (
    CrossEncoderClassificationEvaluator,
)
from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss
from sentence_transformers.cross_encoder.trainer import CrossEncoderTrainer
from sentence_transformers.cross_encoder.training_args import (
    CrossEncoderTrainingArguments,
)
from datasets import Dataset


def load_triplets(path: Path):
    train_rows, val_rows = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        target = train_rows if d.get("split", "train") == "train" else val_rows
        target.append((d["query"], d["doc"], int(d["label"])))
    return train_rows, val_rows


def to_dataset(rows):
    return Dataset.from_dict({
        "sentence_1": [r[0] for r in rows],
        "sentence_2": [r[1] for r in rows],
        "label": [float(r[2]) for r in rows],
    })


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--triplets", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--base-model", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--max-len", type=int, default=512)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    print(f"[finetune_crossenc] loading triplets from {args.triplets}")
    train_rows, val_rows = load_triplets(args.triplets)
    pos_t = sum(1 for r in train_rows if r[2] == 1)
    neg_t = len(train_rows) - pos_t
    pos_v = sum(1 for r in val_rows if r[2] == 1)
    neg_v = len(val_rows) - pos_v
    print(f"[finetune_crossenc] train: {len(train_rows)} pairs ({pos_t} pos, {neg_t} neg)")
    print(f"[finetune_crossenc] val:   {len(val_rows)} pairs ({pos_v} pos, {neg_v} neg)")

    train_ds = to_dataset(train_rows)
    val_ds = to_dataset(val_rows)

    print(f"[finetune_crossenc] loading base model: {args.base_model}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[finetune_crossenc] device: {device}")
    model = CrossEncoder(
        args.base_model,
        num_labels=1,
        max_length=args.max_len,
    )
    loss_fn = BinaryCrossEntropyLoss(model=model)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    train_args = CrossEncoderTrainingArguments(
        output_dir=str(args.out_dir / "training_checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        warmup_ratio=0.1,
        logging_steps=50,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        save_total_limit=1,
        seed=args.seed,
        report_to="none",
        fp16=device == "cuda",
        dataloader_num_workers=0,
    )

    # Evaluator: binary classification accuracy / F1 on val
    val_evaluator = CrossEncoderClassificationEvaluator(
        sentence_pairs=[(r[0], r[1]) for r in val_rows],
        labels=[r[2] for r in val_rows],
        name="val",
    )

    trainer = CrossEncoderTrainer(
        model=model,
        args=train_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        loss=loss_fn,
        evaluator=val_evaluator,
    )

    print("[finetune_crossenc] training ...")
    trainer.train()
    print("[finetune_crossenc] training done")

    print(f"[finetune_crossenc] saving model to {args.out_dir}")
    model.save_pretrained(str(args.out_dir))
    print(f"[finetune_crossenc] DONE — model at {args.out_dir}")


if __name__ == "__main__":
    main()
