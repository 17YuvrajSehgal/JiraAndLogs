"""Offline tests for Phase 3.2: WindowExtractionsStore.

Covers:
  - WindowEntities round-trip via to_dict/from_dict.
  - WindowEntities.n_entities + is_empty.
  - Store loads JSONL into window_id → entities lookup.
  - Missing file → empty store, no exception (smoke-friendly).
  - exists_on_disk reflects file presence.
  - coverage_fraction over a window-id list.
  - from_global_dir convenience factory.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_window_extractions -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.data_loaders import (
    WINDOW_EXTRACTIONS_DEFAULT_PATH,
    WindowEntities,
    WindowExtractionsStore,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _ext_row(
    window_id: str,
    *,
    affected_services=("cartservice",),
    error_classes=("RedisConnectionException",),
    symptoms=("timeout",),
    components=(),
    severity="active_fault",
    family="redis_oom",
) -> dict:
    return {
        "window_id": window_id,
        "severity": severity,
        "family": family,
        "affected_services": list(affected_services),
        "components": list(components),
        "error_classes": list(error_classes),
        "symptoms": list(symptoms),
    }


# ---------------------------------------------------------------------------
# WindowEntities dataclass
# ---------------------------------------------------------------------------


class TestWindowEntities(unittest.TestCase):
    def test_roundtrip(self):
        we = WindowEntities(
            window_id="w1",
            affected_services=("a", "b"),
            error_classes=("E",),
            symptoms=("s1", "s2"),
        )
        we2 = WindowEntities.from_dict(we.to_dict())
        self.assertEqual(we, we2)

    def test_n_entities_counts_all_fields(self):
        we = WindowEntities(
            window_id="w1",
            affected_services=("a",),
            components=("c1", "c2"),
            error_classes=("e",),
            symptoms=(),
        )
        self.assertEqual(we.n_entities(), 4)

    def test_is_empty(self):
        empty = WindowEntities(window_id="w0")
        self.assertTrue(empty.is_empty())
        not_empty = WindowEntities(window_id="w0", symptoms=("s",))
        self.assertFalse(not_empty.is_empty())


# ---------------------------------------------------------------------------
# Store loader behaviour
# ---------------------------------------------------------------------------


class TestStoreLoading(unittest.TestCase):
    def test_loads_jsonl_into_lookup(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "all_extractions.jsonl"
            _write_jsonl(path, [
                _ext_row("w1"),
                _ext_row("w2", affected_services=("paymentservice",)),
            ])
            store = WindowExtractionsStore(path=path)
            self.assertEqual(len(store), 2)
            self.assertTrue(store.has("w1"))
            self.assertEqual(
                store.get("w2").affected_services,
                ("paymentservice",),
            )

    def test_missing_file_returns_empty_store(self):
        store = WindowExtractionsStore(path="/nonexistent/missing.jsonl")
        # Lazy → must not raise on construction.
        self.assertEqual(len(store), 0)
        self.assertIsNone(store.get("anything"))
        self.assertFalse(store.exists_on_disk())

    def test_unknown_window_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ext.jsonl"
            _write_jsonl(path, [_ext_row("w1")])
            store = WindowExtractionsStore(path=path)
            self.assertIsNone(store.get("w2"))

    def test_corrupt_line_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ext.jsonl"
            path.write_text(
                json.dumps(_ext_row("ok")) + "\n"
                + "definitely not json\n"
                + json.dumps({"missing_window_id": True}) + "\n"
                + json.dumps(_ext_row("ok2")) + "\n",
                encoding="utf-8",
            )
            store = WindowExtractionsStore(path=path)
            self.assertEqual(len(store), 2)        # only the two valid rows

    def test_iter_yields_entities(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ext.jsonl"
            _write_jsonl(path, [_ext_row("a"), _ext_row("b")])
            store = WindowExtractionsStore(path=path)
            ids = sorted(e.window_id for e in store)
            self.assertEqual(ids, ["a", "b"])


# ---------------------------------------------------------------------------
# Coverage + from_global_dir
# ---------------------------------------------------------------------------


class TestStoreCoverage(unittest.TestCase):
    def test_coverage_fraction(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ext.jsonl"
            _write_jsonl(path, [_ext_row("a"), _ext_row("b")])
            store = WindowExtractionsStore(path=path)
            self.assertEqual(store.coverage_fraction(["a", "b"]), 1.0)
            self.assertAlmostEqual(
                store.coverage_fraction(["a", "x"]), 0.5,
            )
            self.assertEqual(store.coverage_fraction([]), 0.0)

    def test_from_global_dir_finds_default_path(self):
        with tempfile.TemporaryDirectory() as td:
            gd = Path(td) / "ds"
            ext_path = gd / WINDOW_EXTRACTIONS_DEFAULT_PATH
            _write_jsonl(ext_path, [_ext_row("w1")])
            store = WindowExtractionsStore.from_global_dir(gd)
            self.assertEqual(len(store), 1)
            self.assertTrue(store.exists_on_disk())

    def test_from_global_dir_missing_file_empty(self):
        with tempfile.TemporaryDirectory() as td:
            gd = Path(td) / "no-extractions-yet"
            gd.mkdir()
            store = WindowExtractionsStore.from_global_dir(gd)
            self.assertEqual(len(store), 0)
            self.assertFalse(store.exists_on_disk())


if __name__ == "__main__":
    unittest.main()
