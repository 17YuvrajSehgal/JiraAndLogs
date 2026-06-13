"""WindowExtractionsStore — load per-window LLM extractions.

The Phase 3.1 CLI writes
`<global_dir>/v2_kg_extractions_windows/all_extractions.jsonl` with one
row per window. This module is the read side: it loads that JSONL into
a window_id → entities lookup the agent can consult at runtime.

Two use cases:
  1. **Capability surfacing.** Smoke + ablation scripts check
     `exists(global_dir)` to set `has_kg_graph_window=True` on the
     observation context — already wired in Phase 3.1.
  2. **Skill-side consumption.** Future live-retrieval skills will
     pull entities by window_id and incorporate them into queries.
     v1 predictions-backed retrievers don't dynamically re-rank on
     new entities, but the store provides the read API.

Schema (matches v2_advanced.proposal_d_knowledge_graph.extractor.WindowExtraction):
    {
      "window_id": str,
      "severity": str,
      "family": str,
      "affected_services": list[str],
      "components": list[str],
      "error_classes": list[str],
      "symptoms": list[str]
    }
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


log = logging.getLogger(__name__)


DEFAULT_RELATIVE_PATH = Path("v2_kg_extractions_windows/all_extractions.jsonl")


@dataclass(frozen=True)
class WindowEntities:
    """One window's LLM-extracted entities."""
    window_id: str
    severity: str = ""
    family: str = ""
    affected_services: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    error_classes: tuple[str, ...] = ()
    symptoms: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WindowEntities":
        return cls(
            window_id=str(d["window_id"]),
            severity=str(d.get("severity") or ""),
            family=str(d.get("family") or ""),
            affected_services=tuple(d.get("affected_services") or ()),
            components=tuple(d.get("components") or ()),
            error_classes=tuple(d.get("error_classes") or ()),
            symptoms=tuple(d.get("symptoms") or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "severity": self.severity,
            "family": self.family,
            "affected_services": list(self.affected_services),
            "components": list(self.components),
            "error_classes": list(self.error_classes),
            "symptoms": list(self.symptoms),
        }

    def n_entities(self) -> int:
        return (
            len(self.affected_services)
            + len(self.components)
            + len(self.error_classes)
            + len(self.symptoms)
        )

    def is_empty(self) -> bool:
        return self.n_entities() == 0


class WindowExtractionsStore:
    """Read-only index of window_id → WindowEntities.

    Construction:
        path: explicit JSONL path. If None, uses
            `<global_dir>/v2_kg_extractions_windows/all_extractions.jsonl`.
        global_dir: alternative entry — resolves the default path
            relative to this directory.

    Either `path` OR `global_dir` is required.

    Methods:
        get(window_id) → WindowEntities | None
        has(window_id) → bool
        __len__ → number of indexed windows
        coverage_fraction(window_ids) → float fraction with entries
    """

    def __init__(
        self,
        *,
        path: Path | str | None = None,
        global_dir: Path | str | None = None,
    ) -> None:
        if path is None and global_dir is None:
            raise ValueError(
                "WindowExtractionsStore needs `path` or `global_dir`",
            )
        if path is None:
            path = Path(global_dir) / DEFAULT_RELATIVE_PATH
        self.path = Path(path)
        self._entries: dict[str, WindowEntities] = {}
        self._loaded = False

    # ------------------------------------------------------------------ load

    @classmethod
    def from_global_dir(
        cls,
        global_dir: Path | str,
    ) -> "WindowExtractionsStore":
        """Return a store reading the default-location JSONL.

        Returns an empty store (no error) when the file is missing —
        useful when callers want to surface a `has_kg_graph_window`
        flag conditional on presence."""
        store = cls(global_dir=global_dir)
        try:
            store._ensure_loaded()
        except FileNotFoundError:
            log.info("WindowExtractionsStore: file not found at %s — "
                     "store will be empty", store.path)
        return store

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self.path.exists():
            self._loaded = True
            raise FileNotFoundError(
                f"window extractions JSONL missing: {self.path}",
            )
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("skipping malformed line in %s", self.path)
                    continue
                try:
                    we = WindowEntities.from_dict(d)
                except KeyError:
                    log.warning(
                        "skipping row missing window_id in %s", self.path,
                    )
                    continue
                self._entries[we.window_id] = we
        self._loaded = True
        log.info("WindowExtractionsStore: loaded %d windows from %s",
                 len(self._entries), self.path)

    # ------------------------------------------------------------------ lookup

    def get(self, window_id: str) -> WindowEntities | None:
        self._ensure_loaded_or_empty()
        return self._entries.get(window_id)

    def has(self, window_id: str) -> bool:
        self._ensure_loaded_or_empty()
        return window_id in self._entries

    def __len__(self) -> int:
        self._ensure_loaded_or_empty()
        return len(self._entries)

    def __iter__(self) -> Iterator[WindowEntities]:
        self._ensure_loaded_or_empty()
        return iter(self._entries.values())

    def coverage_fraction(self, window_ids: list[str]) -> float:
        """Fraction of `window_ids` with an entry in the store."""
        if not window_ids:
            return 0.0
        n_have = sum(1 for w in window_ids if self.has(w))
        return n_have / len(window_ids)

    def exists_on_disk(self) -> bool:
        return self.path.exists()

    # ------------------------------------------------------------------ helpers

    def _ensure_loaded_or_empty(self) -> None:
        """Lazy-load; treat missing file as an empty store."""
        if self._loaded:
            return
        try:
            self._ensure_loaded()
        except FileNotFoundError:
            # Already marked loaded inside _ensure_loaded; stay empty.
            pass

    def __repr__(self) -> str:
        return (
            f"WindowExtractionsStore(path={self.path!s}, "
            f"loaded={self._loaded}, n={len(self._entries)})"
        )
