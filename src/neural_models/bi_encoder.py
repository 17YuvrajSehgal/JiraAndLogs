"""Fine-tuned BiEncoder for production-deployable retrieval.

Why bi-encoders matter for this paper:

  The cross-encoder reranker (Phase B) is accurate but expensive: it
  scores every (query, doc) pair jointly, so candidate scores cannot be
  precomputed. At memory scales of 10k+ tickets, joint scoring blows
  the per-query latency budget.

  A bi-encoder embeds documents once and queries once; top-K retrieval
  is then an ANN lookup over precomputed document vectors. This is what
  production teams actually deploy.

Training recipe (Phase G v2, 2026-06-02):

  - Backbone: sentence-transformers/all-MiniLM-L6-v2 (22M params, 384-d
    embeddings, fast).
  - Loss: MultipleNegativesRankingLoss for contrastive in-batch negs
    PLUS explicit BM25-mined hard negatives appended to each batch via
    the (anchor, positive, hard_neg_1, hard_neg_2, ...) "triplet+"
    format that MNRL accepts when each example has 2+ entries.
  - Positives: ALL gold-matched tickets per window (not 1-random). On
    our train+val: ~12k positives from 1262 windows.
  - Hard negatives: per window, top-N BM25 candidates that are NOT in
    the gold set. Default N=3.
  - Epochs: 5 (smoke test showed 1 epoch already gives Hit@1=0.42).
  - Optimizer: AdamW lr=2e-5, warmup 10%.

At predict time:
  1. Embed full memory corpus once (~347 docs).
  2. For each test window, embed its query and cosine-rank visible
     memory tickets (time-ordered visibility respected).
  3. Top-K by similarity = matched_issue_ids.
  4. Triage features [max_sim, mean_top5_sim, n_above_0.5] go through
     a logistic head trained on the train split. Threshold tuned on
     val for FPR=5%.

The pipeline emits a full PipelineResult with both triage_score and
matched_issue_ids, so the comparison harness scores PR-AUC and Hit@K
out of the box.
"""
from __future__ import annotations

import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np


log = logging.getLogger(__name__)

from comparison.pipelines import PipelineRunner
from comparison.schema import PipelinePrediction, PipelineResult
from .gpu_monitor import GPUMonitor
from core.data.loaders import load_dataset
from core.data.splits import iter_split
from core.features.text import (
    build_memory_doc_text,
    build_window_query_text,
)
from core.memory.corpus import MemoryCorpus


def _evi(window: Any, max_chars: int) -> str:
    """Window query text; strip any window-id leading line then trim."""
    text = build_window_query_text(window) or ""
    return text[:max_chars]


def _doc_text(issue: Any, max_chars: int) -> str:
    return (build_memory_doc_text(issue) or "")[:max_chars]


# ---------------------------------------------------------------------------
# Parallel BM25 hard-negative mining (result-preserving).
#
# The per-window BM25 retrieval + time-ordered visibility filtering is the
# dominant cost of BiEncoder training at v3 scale (~61k windows x ~39k memory
# docs; the scorer and the visibility filter are both pure-Python and
# single-threaded). Each window is independent, so we fan the per-window
# "mining" across processes and then reassemble the training pairs
# DETERMINISTICALLY in the main process using a single seeded RNG, in the
# original window order. The emitted pairs are bit-identical to the serial
# path regardless of worker count; only wall-clock changes.
#
# Enabled by env var BIENC_BM25_JOBS (default 1 = original serial path;
# 0 or negative = use all CPUs). Uses the 'fork' start method so workers
# inherit the fitted BM25 scorer and corpus copy-on-write with no pickling.
# ---------------------------------------------------------------------------

# Worker-visible globals (populated in the parent before fork).
_MINE_CORPUS: Any = None
_MINE_BM25: Any = None
_MINE_BY_ID: Any = None
_MINE_WINDOWS: Any = None
_MINE_MAX_CHARS: int = 512
_MINE_TOP_N: int = 20
_MINE_NEED_RANDOM: bool = False


def _bm25_jobs() -> int:
    """Resolve worker count from BIENC_BM25_JOBS (default 1 = serial)."""
    raw = os.environ.get("BIENC_BM25_JOBS", "").strip()
    if not raw:
        return 1
    try:
        v = int(raw)
    except ValueError:
        return 1
    if v <= 0:
        return os.cpu_count() or 1
    return v


def _mine_worker_init() -> None:
    # The work is pure-Python; keep each worker single-threaded so the
    # process pool does not oversubscribe the node's cores.
    os.environ.setdefault("OMP_NUM_THREADS", "1")


def _mine_window_record(w: Any):
    """Mine one window. Returns a small picklable record:

      None                          -> contributes nothing, NOT counted
      ("kept_no_anchor",)           -> counted in n_windows_kept, no pairs
      ("ok", anchor, gold_ids, pos_texts, wrong_texts, random_ids)

    `random_ids` is only populated when random negatives are requested, to
    avoid materialising the (potentially corpus-sized) background pool.
    """
    corpus = _MINE_CORPUS
    bm25 = _MINE_BM25
    by_id = _MINE_BY_ID
    max_chars = _MINE_MAX_CHARS

    gold = list(getattr(w, "matched_memory_issue_ids", None) or [])
    if not gold:
        return None
    visible = corpus.visible_to(w)
    visible_ids = {iss.jira_shadow_issue_id for iss in visible}
    gold_in_view = [g for g in gold if g in visible_ids and g in by_id]
    if not gold_in_view:
        return None
    anchor = _evi(w, max_chars)
    if not anchor:
        return ("kept_no_anchor",)

    hits = bm25.retrieve(w, corpus, top_k=_MINE_TOP_N)
    gold_set = set(gold_in_view)
    wrong = [h for h in hits if h.issue_id not in gold_set]
    pos_texts = [_doc_text(by_id[g], max_chars) for g in gold_in_view]
    wrong_texts = [_doc_text(h.issue, max_chars) for h in wrong]

    random_ids: list[str] = []
    if _MINE_NEED_RANDOM:
        wrong_ids = {h.issue_id for h in wrong}
        random_ids = [
            iss.jira_shadow_issue_id
            for iss in visible
            if iss.jira_shadow_issue_id not in gold_set
            and iss.jira_shadow_issue_id not in wrong_ids
        ]
    return ("ok", anchor, gold_in_view, pos_texts, wrong_texts, random_ids)


def _mine_window_record_idx(i: int):
    return _mine_window_record(_MINE_WINDOWS[i])


class BiEncoderRetrievalPipeline(PipelineRunner):
    """Fine-tuned dense retrieval over the V2 humanized corpus.

    Output emits both triage_score (via a logistic head on similarity
    features) and matched_issue_ids (top-K cosine), so it scores on
    every comparison metric without further plumbing.
    """

    name = "bi_encoder_retrieval"

    def __init__(
        self,
        *,
        backbone: str = "sentence-transformers/all-MiniLM-L6-v2",
        humanized_subdir: str = "bulk-20260531",
        humanized_root: str = "jira-shadow-humanized-v2",
        max_chars: int = 512,
        finetune_epochs: int = 5,
        finetune_batch_size: int = 32,
        finetune_lr: float = 2e-5,
        top_k: int = 5,
        top_k_logistic: int = 5,
        device: str | None = None,
        seed: int = 42,
        use_all_golds: bool = True,
        n_hard_negs: int = 3,
        bm25_top_n: int = 20,
        n_random_negs: int = 0,
    ) -> None:
        self.backbone = backbone
        self.humanized_subdir = humanized_subdir
        self.humanized_root = humanized_root
        self.max_chars = max_chars
        self.finetune_epochs = finetune_epochs
        self.finetune_batch_size = finetune_batch_size
        self.finetune_lr = finetune_lr
        self.top_k = top_k
        self.top_k_logistic = top_k_logistic
        self.device_pref = device
        self.seed = seed
        # Phase G v2 (2026-06-02): emit ALL gold matches per window
        # (not 1-random) and append BM25-mined hard negatives to each
        # example so MNRL has stronger contrastive signal.
        self.use_all_golds = use_all_golds
        self.n_hard_negs = n_hard_negs
        self.bm25_top_n = bm25_top_n
        # G1 (2026-06-05): in addition to BM25-mined hard negatives,
        # sample N random negatives from tickets NOT in the gold set.
        # Mixing random negatives forces the model to learn semantic
        # discrimination beyond BM25 lexical overlap. Set to 0 for the
        # original Phase G v2 behavior (BM25-only hard negatives).
        self.n_random_negs = n_random_negs

    # --- internals ---

    def _device(self) -> str:
        import torch
        if self.device_pref:
            return self.device_pref
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _build_train_pairs(self, train_windows, corpus: MemoryCorpus, by_id: dict):
        """Emit InputExample examples from train+val windows.

        Each example is a list of texts: (anchor, positive, hard_neg_1,
        hard_neg_2, ...). MultipleNegativesRankingLoss treats every
        non-anchor as a candidate negative; in-batch examples from
        other windows are also negatives.

        Strategy (Phase G v2):
          - If use_all_golds: emit ONE example per (window, gold) pair,
            each with its own BM25-mined hard negatives.
          - Otherwise: emit one example per window with a random gold.
        """
        from sentence_transformers import InputExample
        from core.memory.retrieval import BM25Retriever
        import random

        rng = random.Random(self.seed)

        # Fit BM25 over the full corpus once for hard-negative mining.
        bm25 = BM25Retriever()
        bm25.fit(corpus)

        # --- Phase 1: mine per-window records (expensive; optionally parallel)
        # Publish the shared, read-only state for fork-inheriting workers.
        global _MINE_CORPUS, _MINE_BM25, _MINE_BY_ID, _MINE_WINDOWS
        global _MINE_MAX_CHARS, _MINE_TOP_N, _MINE_NEED_RANDOM
        _MINE_CORPUS = corpus
        _MINE_BM25 = bm25
        _MINE_BY_ID = by_id
        _MINE_WINDOWS = train_windows
        _MINE_MAX_CHARS = self.max_chars
        _MINE_TOP_N = self.bm25_top_n
        _MINE_NEED_RANDOM = self.n_random_negs > 0

        n_jobs = _bm25_jobs()
        n = len(train_windows)

        # Guard: 'fork' after CUDA is initialized corrupts the child CUDA
        # context. The mining happens before any model is built, and
        # torch.manual_seed is lazy (does not init CUDA), so this is normally
        # safe — but fall back to serial if CUDA is somehow already live.
        cuda_live = False
        if n_jobs > 1:
            try:
                import torch
                cuda_live = bool(torch.cuda.is_initialized())
            except Exception:                                        # noqa: BLE001
                cuda_live = False
            if cuda_live:
                print(
                    f"[{self.name}] CUDA already initialized; running BM25 "
                    f"mining serially to avoid fork+CUDA corruption.",
                    file=sys.stderr, flush=True,
                )

        t_mine = time.time()
        if n_jobs > 1 and n > 1 and not cuda_live:
            import multiprocessing as mp

            chunk = max(1, n // (n_jobs * 8))
            print(
                f"[{self.name}] mining BM25 hard negatives for {n} windows "
                f"across {n_jobs} processes (chunksize={chunk}) ...",
                file=sys.stderr, flush=True,
            )
            ctx = mp.get_context("fork")
            with ctx.Pool(processes=n_jobs, initializer=_mine_worker_init) as pool:
                records = pool.map(_mine_window_record_idx, range(n), chunksize=chunk)
        else:
            records = [_mine_window_record(w) for w in train_windows]
        print(
            f"[{self.name}] BM25 mining done in {time.time() - t_mine:.1f}s "
            f"(n_jobs={n_jobs}, n_windows={n})",
            file=sys.stderr, flush=True,
        )

        # --- Phase 2: assemble pairs DETERMINISTICALLY (single seeded RNG,
        # original window order). This reproduces the serial logic exactly:
        # the RNG is advanced in the same order and over equal-length lists,
        # so the emitted pairs are independent of the worker count.
        pairs: list[InputExample] = []
        n_windows_kept = 0
        for rec in records:
            if rec is None:
                continue
            n_windows_kept += 1
            if rec[0] != "ok":
                continue
            _tag, anchor, gold_ids, pos_texts, wrong_texts, random_ids = rec

            if self.use_all_golds:
                gold_emit = list(zip(gold_ids, pos_texts))
            else:
                gid = rng.choice(gold_ids)
                gold_emit = [(gid, _doc_text(by_id[gid], self.max_chars))]

            for _gid, positive in gold_emit:
                if not positive:
                    continue
                texts = [anchor, positive]
                if wrong_texts and self.n_hard_negs > 0:
                    chosen = rng.sample(wrong_texts, min(self.n_hard_negs, len(wrong_texts)))
                    texts.extend(chosen)
                if random_ids and self.n_random_negs > 0:
                    chosen_ids = rng.sample(random_ids, min(self.n_random_negs, len(random_ids)))
                    texts.extend(_doc_text(by_id[i], self.max_chars) for i in chosen_ids)
                pairs.append(InputExample(texts=texts))

        print(
            f"[{self.name}] training pairs built: {len(pairs)} from "
            f"{n_windows_kept} windows (use_all_golds={self.use_all_golds}, "
            f"n_hard_negs={self.n_hard_negs}, n_random_negs={self.n_random_negs})",
            file=sys.stderr, flush=True,
        )
        return pairs

    def _finetune(self, pairs):
        """Fine-tune MiniLM with MultipleNegativesRankingLoss (in-batch
        negatives). Returns the fitted SentenceTransformer."""
        from sentence_transformers import (
            SentenceTransformer,
            losses,
            InputExample,
        )
        from torch.utils.data import DataLoader

        device = self._device()
        model = SentenceTransformer(self.backbone, device=device)
        train_dl = DataLoader(
            pairs,
            shuffle=True,
            batch_size=self.finetune_batch_size,
            collate_fn=model.smart_batching_collate,
        )
        loss = losses.MultipleNegativesRankingLoss(model)
        # warmup_steps = 10% of total updates
        steps_per_epoch = max(1, len(pairs) // self.finetune_batch_size)
        warmup = int(0.1 * self.finetune_epochs * steps_per_epoch)
        import time
        n_batches = max(1, len(train_dl))
        total_steps = n_batches * self.finetune_epochs
        print(
            f"[{self.name}] fine-tuning {self.backbone} on {len(pairs)} pairs "
            f"for {self.finetune_epochs} epochs (~{total_steps} steps) on {device}",
            file=sys.stderr,
            flush=True,
        )
        t_train_start = time.time()

        # Per-epoch heartbeat via an in-line callback. We can't easily
        # hook step-level events through sentence-transformers' fit_mixin,
        # but enabling the progress bar at least gives us tqdm output
        # streaming to stderr so a long run doesn't look hung.
        model.fit(
            train_objectives=[(train_dl, loss)],
            epochs=self.finetune_epochs,
            warmup_steps=warmup,
            optimizer_params={"lr": self.finetune_lr},
            show_progress_bar=True,
        )
        print(
            f"[{self.name}] fine-tune complete in {time.time()-t_train_start:.0f}s",
            file=sys.stderr,
            flush=True,
        )
        return model

    def _encode(self, model, texts: list[str], *, label: str = "encode") -> np.ndarray:
        """Encode a list of texts with the BiEncoder.

        Logs an INFO message before + after so long encode passes
        (memory corpus, test split) are visible during training runs
        instead of producing silent multi-minute gaps in the log.
        """
        t0 = time.time()
        log.info("[%s] encoding %d texts (batch_size=64, device=%s) ...",
                 label, len(texts), self._device())
        emb = model.encode(
            texts,
            batch_size=64,
            show_progress_bar=True,                # tqdm to stderr for live progress
            convert_to_numpy=True,
            device=self._device(),
            normalize_embeddings=True,
        )
        dt = time.time() - t0
        log.info("[%s] encoded %d texts in %.1fs (%.1f texts/s)",
                 label, len(texts), dt, len(texts) / max(dt, 1e-9))
        return np.asarray(emb, dtype=np.float32)

    def _build_sim_features(
        self,
        window_emb: np.ndarray,
        memory_emb: np.ndarray,
        visible_mask: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return per-window features for the logistic triage head and
        the ranked list of memory indices."""
        # window_emb: (B, d), memory_emb: (M, d), visible_mask: (B, M)
        sims = window_emb @ memory_emb.T  # (B, M)
        # Mask non-visible memory rows with -inf so they never rank
        masked = np.where(visible_mask, sims, -np.inf)
        # Sort descending
        ranked_idx = np.argsort(-masked, axis=1)  # (B, M)
        top_k_l = self.top_k_logistic
        # Triage features: max_sim, mean of top-K_logistic, count above 0.5
        top_sims = np.take_along_axis(masked, ranked_idx[:, :top_k_l], axis=1)
        # Replace -inf with 0 in features so the logistic head can train
        top_sims_finite = np.where(np.isfinite(top_sims), top_sims, 0.0)
        max_sim = top_sims_finite[:, 0]
        mean_top = top_sims_finite.mean(axis=1)
        # n_above is computed on the FULL visible set
        sims_visible_only = np.where(visible_mask, sims, -np.inf)
        n_above_05 = (sims_visible_only > 0.5).sum(axis=1).astype(np.float32)
        feats = np.stack([max_sim, mean_top, n_above_05], axis=1)
        return feats, ranked_idx

    # --- main ---

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root
        import torch
        from sklearn.linear_model import LogisticRegression
        from core.eval.metrics import precision_at_fpr
        from memorygraph.humanized_loader import load_humanized_corpus

        torch.manual_seed(self.seed)
        np.random.seed(self.seed)

        # --- 1. Load dataset + memory ---
        ds = load_dataset(global_dir)
        train_w = list(iter_split(ds.windows, ds.split_manifest, "train"))
        val_w = list(iter_split(ds.windows, ds.split_manifest, "validation"))
        test_w = list(iter_split(ds.windows, ds.split_manifest, "test"))

        memory_issues = load_humanized_corpus(
            global_dir,
            humanized_subdir=self.humanized_subdir,
            humanized_root=self.humanized_root,
        )
        corpus = MemoryCorpus(issues=memory_issues, mode="time_ordered")
        by_id = corpus.by_id()
        memory_ids = [iss.jira_shadow_issue_id for iss in memory_issues]
        memory_texts = [_doc_text(iss, self.max_chars) for iss in memory_issues]

        # --- 2. Fine-tune on train + val pairs (val windows DO have
        #         gold matchings, so they're usable for contrastive
        #         training even though they're held out for triage
        #         threshold tuning).
        t0 = time.time()
        pairs = self._build_train_pairs(train_w + val_w, corpus, by_id)
        # GPU trace
        from pathlib import Path
        gpu_path = Path("results/phase-g-neural/gpu") / f"bi_encoder__{int(t0)}.jsonl"
        if len(pairs) >= self.finetune_batch_size:
            with GPUMonitor(gpu_path, interval_s=2.0, tag="bi_encoder.fit"):
                model = self._finetune(pairs)
        else:
            from sentence_transformers import SentenceTransformer
            print(
                f"[{self.name}] only {len(pairs)} pairs — skipping fine-tune, "
                "using off-the-shelf encoder",
                file=sys.stderr, flush=True,
            )
            model = SentenceTransformer(self.backbone, device=self._device())

        # --- 3. Embed memory once ---
        log.info("[bi_encoder] embedding memory corpus (M=%d) ...",
                 len(memory_texts))
        memory_emb = self._encode(model, memory_texts, label="memory")  # (M, d)

        # --- 4. Build visibility masks ---
        def _vis(windows):
            mask = np.zeros((len(windows), len(memory_issues)), dtype=bool)
            id_to_idx = {mid: j for j, mid in enumerate(memory_ids)}
            for i, w in enumerate(windows):
                visible_ids = {iss.jira_shadow_issue_id for iss in corpus.visible_to(w)}
                for vid in visible_ids:
                    j = id_to_idx.get(vid)
                    if j is not None:
                        mask[i, j] = True
            return mask

        train_texts = [_evi(w, self.max_chars) for w in train_w]
        val_texts = [_evi(w, self.max_chars) for w in val_w]
        test_texts = [_evi(w, self.max_chars) for w in test_w]
        log.info("[bi_encoder] embedding split windows: "
                 "train=%d val=%d test=%d",
                 len(train_texts), len(val_texts), len(test_texts))
        train_emb = self._encode(model, train_texts, label="train_q")
        val_emb = self._encode(model, val_texts, label="val_q") if val_w else None
        test_emb = self._encode(model, test_texts, label="test_q")
        log.info("[bi_encoder] building visibility masks (memory=%d × splits) ...",
                 len(memory_issues))
        train_mask = _vis(train_w)
        val_mask = _vis(val_w) if val_w else None
        test_mask = _vis(test_w)

        train_feats, _ = self._build_sim_features(train_emb, memory_emb, train_mask)
        test_feats, test_ranked = self._build_sim_features(test_emb, memory_emb, test_mask)

        # --- 5. Fit triage head ---
        y_train = np.asarray(
            [1 if w.triage_label == "ticket_worthy" else 0 for w in train_w],
            dtype=np.int64,
        )
        # WoL Mode 3 (or any dataset where every training window is
        # ticket_worthy by construction) produces a single-class y_train,
        # which sklearn LogisticRegression cannot fit. In that case skip
        # the logistic head — the retrieval ranking (matched_issue_ids)
        # is the load-bearing output anyway. The triage_score falls back
        # to max_sim, which still orders windows usefully but is not a
        # calibrated probability.
        if len(set(y_train.tolist())) < 2:
            print(f"[{self.name}] y_train is single-class; skipping logistic "
                  f"triage head, emitting max_sim as triage_score.",
                  file=sys.stderr, flush=True)
            clf = None
        else:
            clf = LogisticRegression(
                class_weight="balanced", max_iter=2000, solver="lbfgs",
            ).fit(train_feats, y_train)
        fit_seconds = time.time() - t0

        # --- 6. Threshold tuning on val ---
        if val_w and clf is not None:
            val_feats, _ = self._build_sim_features(val_emb, memory_emb, val_mask)
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val_w]
            val_scores = [float(p[1]) for p in clf.predict_proba(val_feats)]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
        else:
            threshold = 0.5

        # --- 7. Predict test ---
        log.info("[bi_encoder] predicting on test split (n=%d) ...", len(test_w))
        t0 = time.time()
        if clf is not None:
            test_scores = [float(p[1]) for p in clf.predict_proba(test_feats)]
        else:
            # Fall back to max_sim (column 0 of the feature vector).
            test_scores = [float(f[0]) for f in test_feats]
        predict_seconds = time.time() - t0

        predictions: list[PipelinePrediction] = []
        for i, w in enumerate(test_w):
            score = test_scores[i]
            top_idx = test_ranked[i, : self.top_k].tolist()
            # Filter out any -inf-masked indices (shouldn't happen if memory > top_k)
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
                "n_finetune_pairs": len(pairs),
                "backbone": self.backbone,
                "embed_dim": int(memory_emb.shape[1]),
                "device": self._device(),
                "retrieval": "bi_encoder_dense",
            },
        )
