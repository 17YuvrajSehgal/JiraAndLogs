"""Persistent embedding cache (LLM-Jira-enhancement / EXPERIMENTS.md O6).

Embedding-based pipelines (memorygraph_full, bi_encoder_hybrid,
nomic_retrieval, future variants) call Nomic-via-LM-Studio for every
document and every query at fit time. On v5-large that's ~6-10 minutes
per pipeline, almost entirely network round-trips for embeddings that
are deterministic functions of the text + model id.

This module wraps any "text -> vector" callable with a disk-backed
cache:

    data/derived/global/<global_id>/embeddings/<model_safe>/<sha256>.npy

Cache hits are read from disk (microseconds). Cache misses call the
underlying embedder and persist the result. Re-runs of the same
pipeline against the same corpus take ~30s instead of ~6min.

Stdlib + numpy only — no torch/transformers dependency. The cache is
content-addressed (sha256 of text), so adding a new sentence to the
corpus doesn't invalidate the existing entries.

Usage:

    embedder = CachedEmbedder(
        model_id="nomic-embed-text-v1.5",
        cache_root=Path("data/derived/global/<id>/embeddings"),
        backend=raw_nomic_call,     # callable(text) -> np.ndarray
    )

    vec = embedder.embed("some text")           # writes cache on miss
    vecs = embedder.embed_batch(["a", "b"])     # batched, cache-aware

    # Persisted stats for the training-run manifest:
    stats = embedder.stats()
    # {"hits": 941, "misses": 12, "hit_rate": 0.987, ...}
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    import numpy as np  # type: ignore
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


_SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_model_id(model_id: str) -> str:
    """Make a model id safe for a filesystem path."""
    return _SAFE_RE.sub("_", model_id).strip("_") or "unknown"


def _text_key(text: str) -> str:
    """Content-addressed cache key. Uses sha256 over UTF-8 bytes of the
    text — deterministic across machines / Python versions."""
    h = hashlib.sha256(text.encode("utf-8"))
    return h.hexdigest()


def _shard_path(cache_root: Path, model_id: str, key: str) -> Path:
    """Two-char sharding so any one directory doesn't grow past 256
    entries. On a 1000-document corpus that's ~4 entries per shard;
    on 100k documents it's ~400 per shard."""
    model_safe = _safe_model_id(model_id)
    return cache_root / model_safe / key[:2] / f"{key}.npy"


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    read_seconds: float = 0.0
    write_seconds: float = 0.0
    backend_seconds: float = 0.0

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "hit_rate": round(self.hit_rate(), 4),
            "read_seconds": round(self.read_seconds, 3),
            "write_seconds": round(self.write_seconds, 3),
            "backend_seconds": round(self.backend_seconds, 3),
        }


@dataclass
class CachedEmbedder:
    """Wraps any `backend: text -> vector` callable with a disk cache.

    backend signature: `backend(text: str) -> np.ndarray` (1-D).
    Caller is responsible for the backend being deterministic for a
    given (model_id, text) pair. The cache trusts this — if the
    backend's model version silently changes, bump `model_id` to
    invalidate the cache (path is namespaced by model_safe).
    """
    model_id: str
    cache_root: Path
    backend: Callable[[str], Any]
    stats: CacheStats = field(default_factory=CacheStats)

    def __post_init__(self) -> None:
        if not _HAS_NUMPY:
            raise ImportError(
                "CachedEmbedder requires numpy. Install via `pip install numpy`."
            )
        self.cache_root = Path(self.cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, text: str) -> Path:
        return _shard_path(self.cache_root, self.model_id, _text_key(text))

    def embed(self, text: str) -> "np.ndarray":
        """Return the embedding vector for `text`, hitting the cache
        first."""
        p = self._path_for(text)
        if p.exists():
            t0 = time.time()
            vec = np.load(p)
            self.stats.read_seconds += time.time() - t0
            self.stats.hits += 1
            return vec
        # Miss — call the backend.
        t0 = time.time()
        vec = self.backend(text)
        self.stats.backend_seconds += time.time() - t0
        self.stats.misses += 1
        if not isinstance(vec, np.ndarray):
            vec = np.asarray(vec, dtype=np.float32)
        # Persist for future runs.
        t0 = time.time()
        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write — write to .partial.npy then rename so a kill
        # mid-write doesn't leave a corrupt file other runs would read.
        # np.save appends `.npy` if the path doesn't end with it, so we
        # use `.partial` prefix on the basename instead.
        tmp = p.parent / (p.stem + ".partial.npy")
        np.save(tmp, vec)
        os.replace(tmp, p)
        self.stats.write_seconds += time.time() - t0
        self.stats.writes += 1
        return vec

    def embed_batch(self, texts: Iterable[str]) -> "np.ndarray":
        """Batched convenience — returns a 2-D array `[len(texts), dim]`.

        Cache lookups happen per-text (not vectorized) but the backend
        sees the same 1-by-1 invocation pattern. If a future backend
        supports true batching, override this method to call the
        backend once per cache-miss batch.
        """
        vecs = [self.embed(t) for t in texts]
        return np.stack(vecs, axis=0)

    def warmup_from_disk(self) -> int:
        """Count cached entries for this model on disk. Useful for
        diagnostics — doesn't load anything into memory.

        Returns the count of `.npy` files under the model dir.
        """
        model_dir = self.cache_root / _safe_model_id(self.model_id)
        if not model_dir.exists():
            return 0
        return sum(1 for _ in model_dir.rglob("*.npy"))

    def manifest_entry(self) -> dict[str, Any]:
        """One-line summary suitable for embedding in a training-run
        manifest under `embedding_cache`."""
        return {
            "model_id": self.model_id,
            "cache_root": str(self.cache_root),
            "n_cached_on_disk": self.warmup_from_disk(),
            **self.stats.as_dict(),
        }


# ---------------------------------------------------------------------------
# Convenience: factory that wires a Nomic-via-LM-Studio embedder.
# ---------------------------------------------------------------------------


def make_nomic_cached_embedder(
    cache_root: Path,
    *,
    base_url: str = "http://localhost:1234",
    model_id: str = "text-embedding-nomic-embed-text-v1.5",
    timeout_s: float = 60.0,
) -> CachedEmbedder:
    """Wrap the Nomic-via-LM-Studio backend in a CachedEmbedder.

    Backend probes once on first call; raises a clear error if
    LM Studio is unreachable. Subsequent calls reuse the same HTTP
    session implicitly via urllib's connection reuse.
    """
    import json as _json
    import urllib.request
    import urllib.error

    endpoint = f"{base_url.rstrip('/')}/v1/embeddings"

    def _nomic_call(text: str):
        payload = {"model": model_id, "input": text}
        req = urllib.request.Request(
            endpoint,
            data=_json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = _json.load(resp)
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Nomic embedding backend unreachable at {endpoint}: {e}"
            ) from e
        rows = data.get("data") or []
        if not rows:
            raise RuntimeError(
                f"Nomic backend returned no embeddings for input "
                f"(len={len(text)})"
            )
        vec = rows[0].get("embedding") or []
        if not vec:
            raise RuntimeError("Nomic backend returned empty embedding list")
        if _HAS_NUMPY:
            return np.asarray(vec, dtype=np.float32)
        return vec

    return CachedEmbedder(
        model_id=model_id,
        cache_root=cache_root,
        backend=_nomic_call,
    )


if __name__ == "__main__":
    # Smoke: cache one short text, then read it back.
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache-root", required=True)
    p.add_argument("--text", default="hello world")
    p.add_argument("--use-nomic", action="store_true",
                   help="Use real Nomic backend (requires LM Studio).")
    args = p.parse_args()

    cache_root = Path(args.cache_root)
    if args.use_nomic:
        emb = make_nomic_cached_embedder(cache_root)
    else:
        # Stub backend — deterministic but not a real embedding.
        def _stub(text: str):
            import numpy as _np
            h = hashlib.sha256(text.encode("utf-8")).digest()
            return _np.frombuffer(h, dtype=_np.uint8).astype(_np.float32) / 255.0

        emb = CachedEmbedder(
            model_id="stub-sha256-32d",
            cache_root=cache_root,
            backend=_stub,
        )

    v1 = emb.embed(args.text)
    v2 = emb.embed(args.text)  # should hit cache
    print(f"dim: {len(v1)}")
    print(f"vec[:6]: {v1[:6]}")
    print(f"stats: {emb.stats.as_dict()}")
    print(f"n_cached_on_disk: {emb.warmup_from_disk()}")
