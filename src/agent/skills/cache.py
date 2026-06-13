"""SkillCache — content-addressed cache for skill outputs.

Speeds up ablations dramatically. When the ablation harness disables
`verify_with_llm` and re-runs the same windows, every other skill's
`retrieve_dense` / `retrieve_hybrid_fusion` / etc. output is fetched
from disk instantly — the second-through-Nth ablation runs are
dominated by cache hits.

Storage layout::

    data/skill_cache/
        retrieve_dense@1.0.0/
            <key>.json           # JSON-serialised SkillOutput
            <key>.json
        verify_with_llm@1.0.0/
            <key>.json

One JSON file per (skill, key). Files are atomically written via
`os.replace` so partial writes don't corrupt the cache. Lookup is a
direct file-existence check — no index needed.

A skill bumps `version` to invalidate its cache; old entries live
under the previous version's directory and can be pruned manually.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §4.8.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from ..types import SkillOutput


log = logging.getLogger(__name__)

#: Default cache root. Mirrors AGENT_CACHE_DIR in .env.example.
DEFAULT_CACHE_ROOT = Path("data/skill_cache")


class SkillCache:
    """Disk-backed content-addressed cache.

    Thread-safe (file-level locks per skill directory). Process-safe
    via atomic-rename writes.

    Usage::

        cache = SkillCache()       # defaults to data/skill_cache/
        out = cache.get(skill, key)
        if out is None:
            out = skill.invoke(...)
            cache.put(skill, key, out)
    """

    def __init__(
        self,
        root: Path | str = DEFAULT_CACHE_ROOT,
        *,
        enabled: bool = True,
    ) -> None:
        self.root = Path(root)
        self.enabled = enabled
        # One lock per skill directory — created lazily.
        self._dir_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

        # Counters useful for ablation reporting
        self._hits = 0
        self._misses = 0
        self._puts = 0
        self._counter_lock = threading.Lock()

        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ public API

    def get(self, skill: Any, key: str) -> SkillOutput | None:
        """Return the cached SkillOutput for (skill, key), or None on miss."""
        if not self.enabled:
            return None
        path = self._path_for(skill, key)
        if not path.exists():
            with self._counter_lock:
                self._misses += 1
            return None
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning(
                "SkillCache: corrupt entry at %s (%s); treating as miss",
                path, type(e).__name__,
            )
            with self._counter_lock:
                self._misses += 1
            return None
        try:
            output = SkillOutput.from_dict(d)
        except (KeyError, TypeError) as e:
            log.warning(
                "SkillCache: unparseable entry at %s (%s); treating as miss",
                path, e,
            )
            with self._counter_lock:
                self._misses += 1
            return None
        with self._counter_lock:
            self._hits += 1
        return output

    def put(self, skill: Any, key: str, output: SkillOutput) -> Path:
        """Atomically store a SkillOutput under (skill, key). Returns the path."""
        if not self.enabled:
            return Path()
        path = self._path_for(skill, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = self._lock_for(self._dir_name(skill))
        # Atomic write: write to tempfile in same dir, then replace.
        with lock:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=path.parent, delete=False, suffix=".tmp",
            ) as fh:
                json.dump(output.to_dict(), fh, default=str)
                tmp_path = Path(fh.name)
            os.replace(tmp_path, path)
        with self._counter_lock:
            self._puts += 1
        return path

    def invalidate(self, skill: Any) -> int:
        """Delete every cached entry for this skill's current version.

        Returns the number of files removed. Useful when changing prompts
        without bumping `version` (during development)."""
        d = self._skill_dir(skill)
        if not d.exists():
            return 0
        n = 0
        for entry in d.iterdir():
            if entry.is_file():
                entry.unlink()
                n += 1
        return n

    def stats(self) -> dict[str, Any]:
        with self._counter_lock:
            total = self._hits + self._misses
            return {
                "enabled": self.enabled,
                "root": str(self.root),
                "hits": self._hits,
                "misses": self._misses,
                "puts": self._puts,
                "hit_rate": round(self._hits / total, 3) if total else 0.0,
            }

    def reset_stats(self) -> None:
        with self._counter_lock:
            self._hits = 0
            self._misses = 0
            self._puts = 0

    # ------------------------------------------------------------------ internals

    def _dir_name(self, skill: Any) -> str:
        """`<name>@<version>` — one subdirectory per skill version."""
        return f"{skill.name}@{skill.version}"

    def _skill_dir(self, skill: Any) -> Path:
        return self.root / self._dir_name(skill)

    def _path_for(self, skill: Any, key: str) -> Path:
        return self._skill_dir(skill) / f"{key}.json"

    def _lock_for(self, dir_name: str) -> threading.Lock:
        with self._locks_lock:
            if dir_name not in self._dir_locks:
                self._dir_locks[dir_name] = threading.Lock()
            return self._dir_locks[dir_name]

    def __repr__(self) -> str:
        return f"SkillCache(root={self.root!s}, enabled={self.enabled})"


# ---------------------------------------------------------------------------
# Null-object variant for tests / dry-runs
# ---------------------------------------------------------------------------


class NullSkillCache(SkillCache):
    """Cache that always misses + never stores. Useful for tests and
    for `agent --no-cache` runs that want to measure cold-cache performance."""

    def __init__(self) -> None:
        super().__init__(enabled=False)

    def get(self, skill: Any, key: str) -> SkillOutput | None:
        with self._counter_lock:
            self._misses += 1
        return None

    def put(self, skill: Any, key: str, output: SkillOutput) -> Path:
        return Path()
