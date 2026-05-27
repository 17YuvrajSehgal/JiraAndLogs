"""GPU-aware neural pipelines for the comparison harness.

These pipelines use the in-Python neural stack (sentence-transformers,
xgboost-cuda) rather than going through LM Studio. They auto-detect the
GPU via `util.device` and fall back to CPU cleanly when CUDA isn't usable.

Pipelines exported:
  BiEncoderHybridPipeline — sentence-transformers MiniLM embedding of the
                            window evidence text, concatenated with the
                            numeric features, fed to a logistic head.
                            GPU encoder when available.
  XgboostGPUPipeline      — xgboost classifier over the numeric features
                            with `device="cuda"`. Soft-imports xgboost; if
                            not installed, the pipeline raises at
                            construction time with a clear install hint.

Both pipelines respect the production-realism contract: they only read
`triage_evidence_text` and `triage_feature_*`, never label-derived fields.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

# Import the device helper. The src/ root is added to sys.path by the
# comparison CLI; if a caller imports this module directly we patch it.
_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))
from util.device import gpu_status, resolve_device, safe_batch_size  # noqa: E402

from loganalyzer.data.loaders import load_dataset as load_loganalyzer_dataset
from loganalyzer.data.splits import iter_split
from loganalyzer.eval.metrics import precision_at_fpr

from .pipelines import PipelineRunner, _build_feature_matrix
from .schema import PipelinePrediction, PipelineResult


def _strip_window_header(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("WINDOW "))


class BiEncoderHybridPipeline(PipelineRunner):
    """Sentence-transformers embedding + numeric features + logistic head.

    Why this pipeline:
      Pure-numeric pipelines (hgb, rf, logistic) ignore the rich textual
      evidence in each window. Pure BM25 retrieval can't match
      "dep_error during cart-redis" to "Redis Connection Timeout" — no
      shared tokens. A bi-encoder collapses that gap in vector space.

    GPU behavior:
      Uses `resolve_device()` to pick CUDA when available. On the box
      this is documented for (RTX 5060, 8 GB) the LM Studio server holds
      ~7 GB, so the encoder picks a conservative batch size via
      `safe_batch_size()`. Falls back to CPU silently otherwise.

    Production-realism:
      The WINDOW header line is stripped before encoding — that's where
      lab-only `scenario_id` / `window_id` substring leakage lives. See
      src/experiments/bi_encoder.py for the original ablation.
    """

    name = "bi_encoder_hybrid"

    def __init__(
        self,
        *,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        max_chars: int = 512,
        device: str | None = None,  # None = auto via util.device
        batch_size: int | None = None,
        logistic_C: float = 1.0,
    ) -> None:
        self.model_name = model_name
        self.max_chars = max_chars
        self.device_pref = device  # "cuda"/"cpu"/None
        self.batch_size_pref = batch_size
        self.logistic_C = logistic_C

    def _encode(self, texts: list[str]) -> Any:
        from sentence_transformers import SentenceTransformer
        import numpy as np

        device = resolve_device(prefer=self.device_pref)
        batch_size = self.batch_size_pref or safe_batch_size(
            bytes_per_item=200_000, default_cpu=64, default_gpu=256
        )
        print(
            f"[{self.name}] encoder model={self.model_name} device={device} "
            f"batch_size={batch_size} n={len(texts)}",
            file=sys.stderr,
        )
        model = SentenceTransformer(self.model_name, device=device)
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            device=device,
        )
        return np.asarray(embeddings, dtype="float32")

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        ds = load_loganalyzer_dataset(global_dir)
        train = list(iter_split(ds.windows, ds.split_manifest, "train"))
        val = list(iter_split(ds.windows, ds.split_manifest, "validation"))
        test = list(iter_split(ds.windows, ds.split_manifest, "test"))

        def _evi(windows: list[Any]) -> list[str]:
            return [
                _strip_window_header(w.evidence_text or "")[: self.max_chars]
                for w in windows
            ]

        t0 = time.time()
        # Embed ALL splits in one batch to amortize model-load cost.
        all_texts = _evi(train) + _evi(val) + _evi(test)
        all_emb = self._encode(all_texts)
        n_tr, n_va = len(train), len(val)
        E_train = all_emb[:n_tr]
        E_val = all_emb[n_tr : n_tr + n_va]
        E_test = all_emb[n_tr + n_va :]

        Xn_train = np.asarray(_build_feature_matrix(train, ds.feature_columns), dtype="float32")
        Xn_val = np.asarray(_build_feature_matrix(val, ds.feature_columns), dtype="float32")
        Xn_test = np.asarray(_build_feature_matrix(test, ds.feature_columns), dtype="float32")

        scaler = StandardScaler().fit(Xn_train)
        Xn_train_s = scaler.transform(Xn_train)
        Xn_val_s = scaler.transform(Xn_val)
        Xn_test_s = scaler.transform(Xn_test)

        X_train = np.hstack([E_train, Xn_train_s])
        X_val = np.hstack([E_val, Xn_val_s])
        X_test = np.hstack([E_test, Xn_test_s])

        y_train = np.asarray(
            [1 if w.triage_label == "ticket_worthy" else 0 for w in train], dtype="int64"
        )

        clf = LogisticRegression(
            C=self.logistic_C,
            class_weight="balanced",
            max_iter=2000,
            solver="lbfgs",
        ).fit(X_train, y_train)
        fit_seconds = time.time() - t0

        if val:
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val]
            val_scores = [float(p[1]) for p in clf.predict_proba(X_val)]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
        else:
            threshold = 0.5

        t0 = time.time()
        test_scores = [float(p[1]) for p in clf.predict_proba(X_test)]
        predict_seconds = time.time() - t0

        predictions: list[PipelinePrediction] = []
        for w, score in zip(test, test_scores):
            decision = "ticket_worthy" if score >= threshold else "noise"
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=score,
                    triage_decision=decision,
                    is_novel=None,
                    matched_issue_ids=[],
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

        status = gpu_status()
        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={
                "train_n": len(train),
                "val_n": len(val),
                "test_n": len(test),
                "embed_model": self.model_name,
                "embed_dim": int(E_train.shape[1]),
                "device": status.device,
                "device_name": status.device_name or "",
                "gpu_diagnosis": status.reason,
            },
        )


class XgboostGPUPipeline(PipelineRunner):
    """xgboost classifier over numeric features with `device="cuda"`.

    On the current dataset (3,216 rows × 28 features) the wall-clock win
    over sklearn HGB is essentially zero — both train in well under a
    second. We keep this pipeline for two reasons:

      1. Headroom: once v5-large lands (~10k+ rows) and the categorical
         RED / business columns push the feature matrix wider, xgboost-GPU
         starts to matter.
      2. Architectural symmetry: ensures every "natural GPU candidate" in
         the leaderboard actually exercises the GPU when one is present,
         instead of silently leaving it idle.

    Falls back to `device="cpu"` (still xgboost) when no GPU is usable,
    so the pipeline always runs. If xgboost isn't installed at all the
    constructor raises with a clear install hint."""

    name = "xgboost_gpu_numeric"

    def __init__(
        self,
        *,
        n_estimators: int = 400,
        learning_rate: float = 0.05,
        max_depth: int = 8,
        random_state: int = 42,
        device: str | None = None,
    ) -> None:
        try:
            import xgboost  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "xgboost is not installed. Install with: "
                '"pip install xgboost" (CPU works) or build with CUDA support '
                "per https://xgboost.readthedocs.io/en/stable/install.html#building-from-source"
            ) from exc
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.random_state = random_state
        self.device_pref = device

    def train_and_predict(
        self,
        global_dir: Path,
        runs_root: Path,
        *,
        target_fpr: float = 0.05,
    ) -> PipelineResult:
        del runs_root
        import numpy as np
        import xgboost as xgb

        ds = load_loganalyzer_dataset(global_dir)
        train = list(iter_split(ds.windows, ds.split_manifest, "train"))
        val = list(iter_split(ds.windows, ds.split_manifest, "validation"))
        test = list(iter_split(ds.windows, ds.split_manifest, "test"))

        X_train = np.asarray(_build_feature_matrix(train, ds.feature_columns), dtype="float32")
        X_val = np.asarray(_build_feature_matrix(val, ds.feature_columns), dtype="float32")
        X_test = np.asarray(_build_feature_matrix(test, ds.feature_columns), dtype="float32")
        y_train = np.asarray(
            [1 if w.triage_label == "ticket_worthy" else 0 for w in train], dtype="int64"
        )

        device = resolve_device(prefer=self.device_pref)
        # xgboost's API takes the literal string "cuda" or "cpu".
        pos = max(1, int((y_train == 1).sum()))
        neg = max(1, int((y_train == 0).sum()))
        clf = xgb.XGBClassifier(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            objective="binary:logistic",
            eval_metric="aucpr",
            device=device,
            tree_method="hist",  # GPU-supported tree method
            scale_pos_weight=neg / pos,  # class imbalance, like class_weight=balanced
            random_state=self.random_state,
        )

        t0 = time.time()
        clf.fit(X_train, y_train)
        fit_seconds = time.time() - t0

        if val:
            val_labels = [1 if w.triage_label == "ticket_worthy" else 0 for w in val]
            val_scores = [float(p[1]) for p in clf.predict_proba(X_val)]
            _p, _r, threshold = precision_at_fpr(val_scores, val_labels, target_fpr)
        else:
            threshold = 0.5

        t0 = time.time()
        test_scores = [float(p[1]) for p in clf.predict_proba(X_test)]
        predict_seconds = time.time() - t0

        predictions: list[PipelinePrediction] = []
        for w, score in zip(test, test_scores):
            decision = "ticket_worthy" if score >= threshold else "noise"
            predictions.append(
                PipelinePrediction(
                    window_id=w.window_id,
                    pipeline_name=self.name,
                    triage_score=score,
                    triage_decision=decision,
                    is_novel=None,
                    matched_issue_ids=[],
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

        status = gpu_status()
        return PipelineResult(
            pipeline_name=self.name,
            predictions=predictions,
            triage_threshold=threshold,
            fit_seconds=fit_seconds,
            predict_seconds=predict_seconds,
            metadata={
                "train_n": len(train),
                "val_n": len(val),
                "test_n": len(test),
                "n_features": len(ds.feature_columns),
                "device": status.device,
                "device_name": status.device_name or "",
                "gpu_diagnosis": status.reason,
            },
        )
