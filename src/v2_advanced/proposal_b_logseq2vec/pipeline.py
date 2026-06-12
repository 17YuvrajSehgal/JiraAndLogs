"""LogSeq2VecRetrievalPipeline — full PipelineRunner using the trained
two-stage log-sequence encoder.

Workflow:
  fit:
    1. Build (window, gold-ticket) pairs from train+val splits.
    2. Train LogSeq2Vec (5 epochs, ~3 min on RTX 5060).
    3. Encode all memory tickets via the line-encoder's single-line path
       (acts as a regular sentence-transformer when given 1 line).
    4. Fit a logistic head on similarity features for triage.

  predict:
    1. Load each test window's log sequence from data/derived/global/.../v2_logseq/.
    2. Encode via the trained aggregator into a 384-d window vector.
    3. Cosine-rank against memory; top-K = matched_issue_ids.
    4. Triage features (max sim, mean top-5 sim, n above threshold) ->
       logistic -> triage_score.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from comparison.pipelines import PipelineRunner
from comparison.schema import PipelinePrediction, PipelineResult
from core.data.loaders import load_dataset
from core.data.splits import iter_split
from core.features.text import build_memory_doc_text
from core.memory.corpus import MemoryCorpus
from core.eval.metrics import precision_at_fpr
from memorygraph.humanized_loader import load_humanized_corpus

from v2_advanced.shared import get_logger, log_step
from .train import build_train_pairs, train_logseq2vec, _load_logseq

log = get_logger("phase_b.pipeline")


class LogSeq2VecRetrievalPipeline(PipelineRunner):
    """Log-sequence encoder retrieval pipeline."""

    name = "logseq2vec_retrieval"

    def __init__(
        self,
        *,
        humanized_subdir: str = "bulk-20260531",
        humanized_root: str = "jira-shadow-humanized-v2",
        logseq_subdir: str = "v2_logseq",
        line_encoder_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        d_model: int = 384,
        n_layers: int = 2,
        n_heads: int = 4,
        max_lines: int = 80,
        epochs: int = 5,
        batch_size: int = 8,
        lr: float = 2e-4,
        n_hard_negs: int = 3,
        top_k: int = 5,
        max_chars_doc: int = 512,
        seed: int = 42,
        pretrained_path: str | None = None,
    ) -> None:
        self.humanized_subdir = humanized_subdir
        self.humanized_root = humanized_root
        self.logseq_subdir = logseq_subdir
        self.line_encoder_name = line_encoder_name
        self.d_model = d_model
        self.n_layers = n_layers
        self.n_heads = n_heads
        self.max_lines = max_lines
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.n_hard_negs = n_hard_negs
        self.top_k = top_k
        self.max_chars_doc = max_chars_doc
        self.seed = seed
        # When set, skip training and load the aggregator weights from
        # this path. Use this to avoid re-running the 14-minute training
        # for every comparison run.
        self.pretrained_path = pretrained_path

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root
        from sklearn.linear_model import LogisticRegression

        torch.manual_seed(self.seed)
        np.random.seed(self.seed)

        t_fit_start = time.time()

        # 1) Build or load model
        if self.pretrained_path and Path(self.pretrained_path).exists():
            from .model import LogSeq2Vec
            with log_step(log, "load_pretrained", path=self.pretrained_path):
                checkpoint = torch.load(self.pretrained_path, map_location="cpu", weights_only=False)
                cfg = checkpoint.get("config", {})
                model = LogSeq2Vec(
                    line_encoder_name=cfg.get("line_encoder_name", self.line_encoder_name),
                    d_model=cfg.get("d_model", self.d_model),
                    n_layers=cfg.get("n_layers", self.n_layers),
                    n_heads=cfg.get("n_heads", self.n_heads),
                    max_seq=cfg.get("max_seq", self.max_lines),
                    freeze_line_encoder=cfg.get("freeze_line_encoder", True),
                )
                model.aggregator.load_state_dict(checkpoint["aggregator_state"])
                log.info("loaded pretrained model", path=self.pretrained_path)
        else:
            with log_step(log, "build_pairs"):
                pairs = build_train_pairs(
                    global_dir=global_dir,
                    humanized_subdir=self.humanized_subdir,
                    humanized_root=self.humanized_root,
                    logseq_subdir=self.logseq_subdir,
                    max_lines=self.max_lines,
                    n_hard_negs=self.n_hard_negs,
                    seed=self.seed,
                )
                if not pairs:
                    raise RuntimeError(
                        "LogSeq2Vec has no training pairs. Did you run "
                        "`python -m v2_advanced.proposal_b_logseq2vec.data_prep` first?"
                    )

            with log_step(log, "train", n_pairs=len(pairs), epochs=self.epochs):
                model = train_logseq2vec(
                    pairs,
                    epochs=self.epochs,
                    batch_size=self.batch_size,
                    lr=self.lr,
                    line_encoder_name=self.line_encoder_name,
                    d_model=self.d_model, n_layers=self.n_layers,
                    n_heads=self.n_heads, max_seq=self.max_lines,
                    seed=self.seed,
                )

        # 3) Load dataset + memory; index memory
        with log_step(log, "index_memory"):
            ds = load_dataset(global_dir)
            train_w = list(iter_split(ds.windows, ds.split_manifest, "train"))
            val_w = list(iter_split(ds.windows, ds.split_manifest, "validation"))
            test_w = list(iter_split(ds.windows, ds.split_manifest, "test"))
            memory_issues = load_humanized_corpus(
                global_dir, humanized_subdir=self.humanized_subdir, humanized_root=self.humanized_root,
            )
            corpus = MemoryCorpus(issues=memory_issues, mode="time_ordered")
            memory_ids = [iss.jira_shadow_issue_id for iss in memory_issues]
            memory_texts = [
                (build_memory_doc_text(iss) or "")[:self.max_chars_doc]
                for iss in memory_issues
            ]
            # Encode every memory text as a 1-line "window" (consistent with training)
            with torch.no_grad():
                memory_emb = model.encode_batch_windows([[t] for t in memory_texts])
            memory_emb = memory_emb.cpu().numpy()
            log.info("memory indexed", n=len(memory_issues), dim=memory_emb.shape[1])

        # 4) Encode windows + score against memory
        logseq_root = global_dir / self.logseq_subdir
        def _encode_split(windows):
            anchors = []
            for w in windows:
                lp = logseq_root / f"{w.window_id}.jsonl"
                lines = _load_logseq(lp, max_lines=self.max_lines) if lp.exists() else []
                anchors.append(lines)
            # Batch through to avoid OOM
            out = []
            BATCH = 32
            for i in range(0, len(anchors), BATCH):
                chunk = anchors[i:i+BATCH]
                with torch.no_grad():
                    vecs = model.encode_batch_windows(chunk)
                out.append(vecs.cpu().numpy())
            return np.concatenate(out, axis=0) if out else np.zeros((0, self.d_model), dtype=np.float32)

        def _visible_mask(windows):
            id_to_idx = {mid: j for j, mid in enumerate(memory_ids)}
            mask = np.zeros((len(windows), len(memory_issues)), dtype=bool)
            for i, w in enumerate(windows):
                visible = {iss.jira_shadow_issue_id for iss in corpus.visible_to(w)}
                for v in visible:
                    j = id_to_idx.get(v)
                    if j is not None:
                        mask[i, j] = True
            return mask

        with log_step(log, "encode_train", n=len(train_w)):
            train_emb = _encode_split(train_w)
        with log_step(log, "encode_val", n=len(val_w)):
            val_emb = _encode_split(val_w) if val_w else None
        with log_step(log, "encode_test", n=len(test_w)):
            test_emb = _encode_split(test_w)

        train_mask = _visible_mask(train_w)
        val_mask = _visible_mask(val_w) if val_w else None
        test_mask = _visible_mask(test_w)

        # 5) Score features
        def _features(emb, mask):
            sims = emb @ memory_emb.T  # (B, M)
            masked = np.where(mask, sims, -np.inf)
            ranked = np.argsort(-masked, axis=1)
            top5 = np.take_along_axis(masked, ranked[:, :5], axis=1)
            top5_finite = np.where(np.isfinite(top5), top5, 0.0)
            max_sim = top5_finite[:, 0]
            mean_top5 = top5_finite.mean(axis=1)
            n_above_05 = (np.where(mask, sims, -np.inf) > 0.5).sum(axis=1).astype(np.float32)
            feats = np.stack([max_sim, mean_top5, n_above_05], axis=1)
            return feats, ranked

        train_feats, _ = _features(train_emb, train_mask)
        if val_w:
            val_feats, _ = _features(val_emb, val_mask)
        test_feats, test_ranked = _features(test_emb, test_mask)

        # 6) Triage head
        y_train = np.asarray(
            [1 if w.triage_label == "ticket_worthy" else 0 for w in train_w], dtype=np.int64,
        )
        # Single-class fallback: when every training window is ticket_worthy
        # (e.g. WoL Mode 3, where every WoL JIRA ticket is by construction
        # ticket-worthy), sklearn LogisticRegression cannot fit. Skip the
        # head and emit max_sim as triage_score — retrieval ranking is the
        # load-bearing output anyway.
        if len(set(y_train.tolist())) < 2:
            import sys
            print(f"[{self.name}] y_train is single-class; skipping logistic "
                  f"triage head, emitting max_sim as triage_score.",
                  file=sys.stderr, flush=True)
            clf = None
        else:
            clf = LogisticRegression(
                class_weight="balanced", max_iter=2000, solver="lbfgs",
            ).fit(train_feats, y_train)
        if val_w and clf is not None:
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val_w]
            val_scores = [float(p[1]) for p in clf.predict_proba(val_feats)]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
        else:
            threshold = 0.5

        fit_seconds = time.time() - t_fit_start

        # 7) Predict
        t_predict_start = time.time()
        if clf is not None:
            test_scores = [float(p[1]) for p in clf.predict_proba(test_feats)]
        else:
            # Fall back to max_sim (column 0 of the feature vector).
            test_scores = [float(f[0]) for f in test_feats]
        predict_seconds = time.time() - t_predict_start

        predictions = []
        for i, w in enumerate(test_w):
            score = test_scores[i]
            top_idx = test_ranked[i, : self.top_k].tolist()
            top_ids = [memory_ids[j] for j in top_idx if test_mask[i, j]]
            decision = "ticket_worthy" if score >= threshold else "noise"
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=score,
                    triage_decision=decision,
                    is_novel=None,
                    matched_issue_ids=top_ids,
                    gold_label=w.triage_label,
                    gold_is_novel=w.is_novel,
                    gold_matched_issue_ids=list(w.matched_memory_issue_ids or []),
                    gold_expected_in_memory=getattr(w, "expected_in_memory", None),
                    scenario_family=w.scenario_family,
                    service_name=w.service_name,
                    window_type=w.window_type,
                    is_hard_case=getattr(w, "is_hard_case", False),
                    triage_reason_class=getattr(w, "triage_reason_class", None),
                )
            )

        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={
                "train_n": len(train_w),
                "val_n": len(val_w),
                "test_n": len(test_w),
                "n_memory": len(memory_issues),
                "line_encoder": self.line_encoder_name,
                "d_model": self.d_model,
                "n_layers": self.n_layers,
                "max_lines": self.max_lines,
                "epochs": self.epochs,
                "retrieval": "logseq2vec",
            },
        )
