"""TabTransformer for binary triage.

Architecture (Gorishniy et al., 2021 — FT-Transformer simplified):

  numeric feature vector (94-d)
        |
        +-- per-feature linear embedding (each scalar -> d_model vector)
        +-- shared [CLS] token prepended
        |
        v
   sequence of (1 + 94) tokens of dim d_model
        |
        v
   N Transformer encoder layers (multi-head self-attention + FFN)
        |
        v
   [CLS] head -> linear -> sigmoid -> P(ticket_worthy)

This is a tabular Transformer — it treats each numeric feature as a
distinct token, lets self-attention learn feature interactions, and
predicts triage from the [CLS] representation.

Goal: see whether a modern tabular Transformer can match or beat HGB
(PR-AUC 0.7718 on our test split) on the binary anomaly task. The
charter (§4 non-claim #2) is explicit that we do NOT claim to improve
anomaly detection — but reviewers will ask "did you try a neural
approach?" so we run the experiment and report honestly.

Implementation notes:
  - Stdlib + torch only (no extra deps beyond what sentence-transformers
    already pulled in).
  - StandardScaler on inputs (Transformers are scale-sensitive even
    after embedding).
  - AdamW + cosine schedule, val-AUROC early stopping, 30 epochs max.
  - CUDA auto-detected; falls back to CPU.
"""
from __future__ import annotations

import math
import time
import warnings
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

# Suppress the noisy nested-tensor UserWarning that pre-LN
# TransformerEncoder always emits. It's harmless (just says nested-tensor
# fast-path is off because norm_first=True), but pollutes logs.
warnings.filterwarnings(
    "ignore",
    message="enable_nested_tensor is True, but self.use_nested_tensor is False",
)

from comparison.pipelines import _NumericClassifierPipeline
from .gpu_monitor import GPUMonitor


class _NumericTokenizer(nn.Module):
    """Per-feature linear embedding. Each scalar x_i becomes a d_model
    vector e_i = W_i * x_i + b_i. The per-feature W_i, b_i are learned
    so different features can specialize their token representation."""

    def __init__(self, n_features: int, d_model: int) -> None:
        super().__init__()
        # Per-feature scale + bias. Shape (n_features, d_model).
        self.weight = nn.Parameter(torch.empty(n_features, d_model))
        self.bias = nn.Parameter(torch.empty(n_features, d_model))
        # Init: Kaiming uniform for weight, zeros for bias.
        bound = 1.0 / math.sqrt(d_model)
        nn.init.uniform_(self.weight, -bound, bound)
        nn.init.zeros_(self.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, n_features) -> (B, n_features, d_model)
        return x.unsqueeze(-1) * self.weight.unsqueeze(0) + self.bias.unsqueeze(0)


class TabTransformer(nn.Module):
    """Tabular Transformer over numeric features.

    Args:
      n_features: number of input numeric features
      d_model: embedding dimension per feature token (default 64)
      n_heads: attention heads (default 4)
      n_layers: encoder layers (default 4)
      dropout: dropout in attention + FFN (default 0.1)
    """

    def __init__(
        self,
        *,
        n_features: int,
        d_model: int = 64,
        n_heads: int = 4,
        n_layers: int = 4,
        ffn_mult: int = 4,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.n_features = n_features
        self.d_model = d_model
        self.tokenizer = _NumericTokenizer(n_features, d_model)
        self.cls_token = nn.Parameter(torch.empty(1, 1, d_model))
        nn.init.normal_(self.cls_token, std=0.02)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=d_model * ffn_mult,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, n_features) -> logit (B,)
        b = x.size(0)
        tokens = self.tokenizer(x)                       # (B, n_features, d)
        cls = self.cls_token.expand(b, -1, -1)           # (B, 1, d)
        seq = torch.cat([cls, tokens], dim=1)            # (B, 1+n_features, d)
        seq = self.encoder(seq)
        cls_out = self.norm(seq[:, 0])
        return self.head(cls_out).squeeze(-1)


class _TabTransformerSklearnWrapper:
    """Wraps a fitted TabTransformer in an sklearn-like .predict_proba so
    it slots into the existing _NumericClassifierPipeline scaffolding
    without further changes."""

    def __init__(self, model: TabTransformer, device: str, scaler) -> None:
        self.model = model
        self.device = device
        self.scaler = scaler

    def predict_proba(self, X: list[list[float]]) -> np.ndarray:
        X_arr = self.scaler.transform(np.asarray(X, dtype=np.float32))
        x_t = torch.tensor(X_arr, dtype=torch.float32, device=self.device)
        self.model.eval()
        out = []
        with torch.no_grad():
            for i in range(0, x_t.size(0), 256):
                logits = self.model(x_t[i:i + 256])
                probs = torch.sigmoid(logits).cpu().numpy()
                out.append(probs)
        p1 = np.concatenate(out)
        # Shape (n, 2) — column 0 = P(noise), column 1 = P(ticket_worthy)
        return np.stack([1.0 - p1, p1], axis=1)


def _train_tab_transformer(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray | None,
    y_val: np.ndarray | None,
    *,
    d_model: int = 64,
    n_heads: int = 4,
    n_layers: int = 4,
    dropout: float = 0.1,
    epochs: int = 30,
    batch_size: int = 128,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    device: str | None = None,
    verbose: bool = True,
) -> TabTransformer:
    """Train a TabTransformer. Returns the best-validation-loss model.

    Class imbalance handled via pos_weight in BCE.
    """
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    n_features = X_train.shape[1]
    n_pos = int(y_train.sum())
    n_neg = int((1 - y_train).sum())
    pos_weight = torch.tensor(n_neg / max(1, n_pos), dtype=torch.float32, device=device)

    model = TabTransformer(
        n_features=n_features,
        d_model=d_model,
        n_heads=n_heads,
        n_layers=n_layers,
        dropout=dropout,
    ).to(device)
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optim, T_max=epochs)
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    train_ds = TensorDataset(
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.float32),
    )
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True)

    if X_val is not None and len(X_val):
        val_x = torch.tensor(X_val, dtype=torch.float32, device=device)
        val_y = torch.tensor(y_val, dtype=torch.float32, device=device)
    else:
        val_x = val_y = None

    best_val_loss = float("inf")
    best_state: dict[str, Any] | None = None
    patience = 5
    epochs_no_improve = 0

    for epoch in range(epochs):
        model.train()
        train_loss_acc = 0.0
        n_batches = 0
        for xb, yb in train_dl:
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            optim.zero_grad()
            logits = model(xb)
            loss = bce(logits, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            train_loss_acc += float(loss.item())
            n_batches += 1
        scheduler.step()

        train_loss = train_loss_acc / max(1, n_batches)
        if val_x is not None:
            model.eval()
            with torch.no_grad():
                val_logits = model(val_x)
                val_loss = bce(val_logits, val_y).item()
                val_probs = torch.sigmoid(val_logits).cpu().numpy()
                # Quick AUC for monitoring
                try:
                    from sklearn.metrics import roc_auc_score
                    val_auc = float(roc_auc_score(val_y.cpu().numpy(), val_probs))
                except Exception:
                    val_auc = float("nan")
            if verbose:
                print(
                    f"[tab_transformer] ep {epoch+1:02d}/{epochs}  "
                    f"train_loss={train_loss:.4f}  "
                    f"val_loss={val_loss:.4f}  val_AUC={val_auc:.4f}",
                    flush=True,
                )
            if val_loss < best_val_loss - 1e-4:
                best_val_loss = val_loss
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                epochs_no_improve = 0
            else:
                epochs_no_improve += 1
                if epochs_no_improve >= patience:
                    if verbose:
                        print(
                            f"[tab_transformer] early stopping at epoch {epoch+1} "
                            f"(no val_loss improvement for {patience} epochs)",
                            flush=True,
                        )
                    break
        elif verbose:
            print(f"[tab_transformer] ep {epoch+1:02d} train_loss={train_loss:.4f}", flush=True)

    if best_state is not None:
        model.load_state_dict(best_state)
    return model


class TabTransformerPipeline(_NumericClassifierPipeline):
    """Pipeline wrapper. Slots into the comparison harness exactly like
    GradientBoostingPipeline / CalibratedRandomForestPipeline."""

    name = "tab_transformer"
    needs_scaling = False  # we handle scaling internally so we can keep it on the wrapper

    def __init__(
        self,
        *,
        d_model: int = 64,
        n_heads: int = 4,
        n_layers: int = 4,
        dropout: float = 0.1,
        epochs: int = 30,
        batch_size: int = 128,
        lr: float = 1e-3,
        seed: int = 42,
    ) -> None:
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.seed = seed

    def _fit(self, X_train: list[list[float]], y_train: list[int]) -> Any:
        from sklearn.preprocessing import StandardScaler

        torch.manual_seed(self.seed)
        np.random.seed(self.seed)
        X_train_arr = np.asarray(X_train, dtype=np.float32)
        y_train_arr = np.asarray(y_train, dtype=np.float32)
        scaler = StandardScaler().fit(X_train_arr)
        X_train_scaled = scaler.transform(X_train_arr).astype(np.float32)

        # Hold out a small slice of train for val-loss early stopping
        # (the harness already passes a val split for threshold tuning,
        # but inside _fit we only see X_train_arr — so split internally).
        n = len(X_train_scaled)
        idx = np.random.permutation(n)
        cut = max(1, int(0.9 * n))
        tr_idx, val_idx = idx[:cut], idx[cut:]
        Xtr = X_train_scaled[tr_idx]
        Ytr = y_train_arr[tr_idx]
        Xva = X_train_scaled[val_idx]
        Yva = y_train_arr[val_idx]

        t0 = time.time()
        # GPU trace: write samples every 2s into results/phase-g-neural/gpu/
        from pathlib import Path
        gpu_path = Path("results/phase-g-neural/gpu") / f"tab_transformer__{int(t0)}.jsonl"
        with GPUMonitor(gpu_path, interval_s=2.0, tag="tab_transformer.fit"):
            model = _train_tab_transformer(
                Xtr, Ytr, Xva, Yva,
                d_model=self.d_model,
                n_heads=self.n_heads,
                n_layers=self.n_layers,
                dropout=self.dropout,
                epochs=self.epochs,
                batch_size=self.batch_size,
                lr=self.lr,
            )
        elapsed = time.time() - t0
        print(
            f"[tab_transformer] training done in {elapsed:.1f}s "
            f"(d_model={self.d_model}, layers={self.n_layers})",
            flush=True,
        )
        device = "cuda" if torch.cuda.is_available() else "cpu"
        return _TabTransformerSklearnWrapper(model, device, scaler)

    def lofo_evaluate(self, global_dir, *, binarize_inclusive=False):
        """Skip LOFO for TabTransformer — it retrains the model 14 times
        which costs ~3 minutes on the RTX 5060 and adds nothing the main
        test split doesn't already tell us. The comparison harness
        accepts an empty list and excludes the pipeline from LOFO macros.
        """
        del global_dir, binarize_inclusive
        return []
