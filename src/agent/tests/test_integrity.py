"""Offline tests for Phase 1.14: GraphMetadata + assert_loaded_dataset.

Covers:
  - GraphMetadata round-trip (to_dict, from_neo4j_row).
  - write_graph_metadata emits the correct MERGE cypher with the
    expected parameters; refuses empty dataset_id.
  - read_graph_metadata returns None when no fingerprint exists.
  - assert_loaded_dataset:
      - succeeds when expected matches loaded.
      - raises MetadataMissingError when no fingerprint.
      - raises DatasetMismatchError with expected/actual fields populated.
      - raises MultiTenancyForbiddenError when tagged nodes exist.
  - AgentRunner.__init__:
      - passes when expected_dataset_id matches loaded.
      - refuses construction on mismatch.
      - skips integrity check when neo4j is None.
      - skips integrity check when expected_dataset_id is unset.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_integrity -v
"""

from __future__ import annotations

import unittest
from typing import Any

from agent.integrity import (
    DatasetMismatchError,
    GraphMetadata,
    IntegrityError,
    MetadataMissingError,
    MultiTenancyForbiddenError,
    assert_loaded_dataset,
    check_no_tenancy_tags,
    read_graph_metadata,
    write_graph_metadata,
)
from agent.runner import AgentRunner, RunnerError
from agent.skills import SkillRegistry


# ---------------------------------------------------------------------------
# Fake Neo4j — pattern-matches on cypher keywords + returns canned rows
# ---------------------------------------------------------------------------


class _FakeNeo4j:
    """In-memory test double. Records every (cypher, params) call and
    serves canned rows for the queries the integrity layer issues."""

    def __init__(
        self,
        *,
        loaded_dataset: str | None = None,
        loaded_at: str = "2026-06-12T12:00:00.000+00:00",
        n_incidents: int = 100,
        global_dir: str = "data/derived/global/test-ds",
        n_tagged_nodes_total: int = 0,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.loaded_dataset = loaded_dataset
        self.loaded_at = loaded_at
        self.n_incidents = n_incidents
        self.global_dir = global_dir
        # Total of nodes with `.dataset` set, INCLUDING the metadata
        # node itself (which always has it when a dataset is loaded).
        # `check_no_tenancy_tags` subtracts 1 for the metadata node.
        self.n_tagged_nodes_total = n_tagged_nodes_total
        # If a write_graph_metadata call happens, we capture the
        # new dataset_id here so subsequent reads see it.
        self._post_write_dataset: str | None = None

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        self.calls.append((cypher, params))
        text = cypher.lower()

        # Writer pattern: MERGE GraphMetadata ... SET ...
        if "merge (m:graphmetadata" in text:
            # Capture write so subsequent reads see the new value
            ds = params.get("dataset_id")
            if ds is not None:
                self.loaded_dataset = ds
                self.n_incidents = int(params.get("n_incidents") or 0)
                self.global_dir = str(params.get("global_dir") or "")
                self._post_write_dataset = ds
            return []

        # Reader pattern: MATCH (m:GraphMetadata) RETURN m.dataset ...
        if "match (m:graphmetadata" in text:
            if self.loaded_dataset is None:
                return []
            return [{
                "dataset": self.loaded_dataset,
                "loaded_at": self.loaded_at,
                "n_incidents": self.n_incidents,
                "global_dir": self.global_dir,
            }]

        # Tenancy-tag count: MATCH (n) WHERE n.dataset IS NOT NULL
        if "n.dataset is not null" in text:
            return [{"c": self.n_tagged_nodes_total}]

        # Default
        return []


# ---------------------------------------------------------------------------
# GraphMetadata dataclass
# ---------------------------------------------------------------------------


class TestGraphMetadata(unittest.TestCase):
    def test_to_dict(self):
        gm = GraphMetadata(
            dataset_id="ob-2026", loaded_at="t",
            n_incidents=100, global_dir="/x",
        )
        d = gm.to_dict()
        self.assertEqual(d["dataset_id"], "ob-2026")
        self.assertEqual(d["n_incidents"], 100)

    def test_from_neo4j_row(self):
        row = {
            "dataset": "ob-2026",
            "loaded_at": "2026-06-12T12:00:00",
            "n_incidents": 50,
            "global_dir": "/x",
        }
        gm = GraphMetadata.from_neo4j_row(row)
        self.assertEqual(gm.dataset_id, "ob-2026")
        self.assertEqual(gm.n_incidents, 50)

    def test_from_neo4j_row_handles_missing_fields(self):
        gm = GraphMetadata.from_neo4j_row({"dataset": "x"})
        self.assertEqual(gm.dataset_id, "x")
        self.assertEqual(gm.n_incidents, 0)
        self.assertEqual(gm.loaded_at, "")


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class TestWriteGraphMetadata(unittest.TestCase):
    def test_empty_dataset_id_raises(self):
        with self.assertRaises(ValueError):
            write_graph_metadata(_FakeNeo4j(), GraphMetadata(dataset_id=""))

    def test_emits_merge_cypher(self):
        n = _FakeNeo4j()
        write_graph_metadata(n, GraphMetadata(
            dataset_id="ob-2026", n_incidents=100, global_dir="/x",
        ))
        # One call recorded, with the expected params
        self.assertEqual(len(n.calls), 1)
        cypher, params = n.calls[0]
        self.assertIn("MERGE", cypher)
        self.assertEqual(params["dataset_id"], "ob-2026")
        self.assertEqual(params["n_incidents"], 100)
        self.assertEqual(params["global_dir"], "/x")
        # The default writer uses server-side datetime() — verify the
        # cypher contains it.
        self.assertIn("datetime()", cypher)

    def test_uses_python_timestamp_when_requested(self):
        n = _FakeNeo4j()
        write_graph_metadata(
            n,
            GraphMetadata(dataset_id="ob-2026", loaded_at="2026-06-12T00:00:00"),
            use_neo4j_datetime=False,
        )
        _, params = n.calls[0]
        self.assertIn("loaded_at", params)
        self.assertEqual(params["loaded_at"], "2026-06-12T00:00:00")


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


class TestReadGraphMetadata(unittest.TestCase):
    def test_returns_none_when_missing(self):
        n = _FakeNeo4j(loaded_dataset=None)
        self.assertIsNone(read_graph_metadata(n))

    def test_returns_metadata_when_present(self):
        n = _FakeNeo4j(loaded_dataset="ob-2026", n_incidents=50)
        gm = read_graph_metadata(n)
        self.assertIsNotNone(gm)
        self.assertEqual(gm.dataset_id, "ob-2026")
        self.assertEqual(gm.n_incidents, 50)


# ---------------------------------------------------------------------------
# Tenancy-tag check
# ---------------------------------------------------------------------------


class TestCheckTenancyTags(unittest.TestCase):
    def test_zero_when_only_fingerprint_tagged(self):
        # Only the GraphMetadata node has `.dataset`
        n = _FakeNeo4j(loaded_dataset="ob-2026", n_tagged_nodes_total=1)
        self.assertEqual(check_no_tenancy_tags(n), 0)

    def test_returns_count_of_extra_tagged_nodes(self):
        n = _FakeNeo4j(loaded_dataset="ob-2026", n_tagged_nodes_total=11)
        # 11 total - 1 metadata node = 10 contamination
        self.assertEqual(check_no_tenancy_tags(n), 10)

    def test_zero_when_no_tags_at_all(self):
        n = _FakeNeo4j(loaded_dataset=None, n_tagged_nodes_total=0)
        self.assertEqual(check_no_tenancy_tags(n), 0)


# ---------------------------------------------------------------------------
# assert_loaded_dataset — the integrity gate
# ---------------------------------------------------------------------------


class TestAssertLoadedDataset(unittest.TestCase):
    def test_succeeds_on_match(self):
        n = _FakeNeo4j(loaded_dataset="ob-2026", n_tagged_nodes_total=1)
        gm = assert_loaded_dataset(n, "ob-2026")
        self.assertEqual(gm.dataset_id, "ob-2026")

    def test_missing_metadata_raises(self):
        n = _FakeNeo4j(loaded_dataset=None)
        with self.assertRaises(MetadataMissingError):
            assert_loaded_dataset(n, "ob-2026")

    def test_mismatch_raises_with_fields(self):
        n = _FakeNeo4j(loaded_dataset="otel-demo", n_tagged_nodes_total=1)
        with self.assertRaises(DatasetMismatchError) as ctx:
            assert_loaded_dataset(n, "ob-2026")
        self.assertEqual(ctx.exception.expected, "ob-2026")
        self.assertEqual(ctx.exception.actual, "otel-demo")

    def test_tenancy_tags_raises(self):
        n = _FakeNeo4j(loaded_dataset="ob-2026", n_tagged_nodes_total=5)
        with self.assertRaises(MultiTenancyForbiddenError) as ctx:
            assert_loaded_dataset(n, "ob-2026")
        # 5 total - 1 metadata = 4 contamination
        self.assertEqual(ctx.exception.n_tagged_nodes, 4)

    def test_tenancy_check_can_be_disabled(self):
        n = _FakeNeo4j(loaded_dataset="ob-2026", n_tagged_nodes_total=5)
        # Should NOT raise when the check is off (production multi-tenant
        # mode — explicitly off-limits during research, but tested for
        # API completeness).
        gm = assert_loaded_dataset(n, "ob-2026", check_tenancy_tags=False)
        self.assertEqual(gm.dataset_id, "ob-2026")

    def test_empty_expected_raises_value_error(self):
        n = _FakeNeo4j(loaded_dataset="ob-2026")
        with self.assertRaises(ValueError):
            assert_loaded_dataset(n, "")

    def test_all_integrity_errors_are_subclass_of_base(self):
        self.assertTrue(issubclass(MetadataMissingError, IntegrityError))
        self.assertTrue(issubclass(DatasetMismatchError, IntegrityError))
        self.assertTrue(issubclass(MultiTenancyForbiddenError, IntegrityError))


# ---------------------------------------------------------------------------
# AgentRunner integration
# ---------------------------------------------------------------------------


class TestAgentRunnerIntegrityCheck(unittest.TestCase):
    def test_runner_succeeds_when_dataset_matches(self):
        neo = _FakeNeo4j(loaded_dataset="ob-2026", n_tagged_nodes_total=1)
        r = AgentRunner(
            SkillRegistry(),
            neo4j=neo,
            expected_dataset_id="ob-2026",
        )
        self.assertEqual(r.expected_dataset_id, "ob-2026")
        # The MATCH query landed on the fake
        match_calls = [c for c, _ in neo.calls if "match (m:graphmetadata" in c.lower()]
        self.assertGreaterEqual(len(match_calls), 1)

    def test_runner_refuses_on_mismatch(self):
        neo = _FakeNeo4j(loaded_dataset="otel-demo", n_tagged_nodes_total=1)
        with self.assertRaises(DatasetMismatchError):
            AgentRunner(
                SkillRegistry(),
                neo4j=neo,
                expected_dataset_id="ob-2026",
            )

    def test_runner_refuses_when_metadata_missing(self):
        neo = _FakeNeo4j(loaded_dataset=None)
        with self.assertRaises(MetadataMissingError):
            AgentRunner(
                SkillRegistry(),
                neo4j=neo,
                expected_dataset_id="ob-2026",
            )

    def test_runner_refuses_on_tenancy_tags(self):
        neo = _FakeNeo4j(loaded_dataset="ob-2026", n_tagged_nodes_total=20)
        with self.assertRaises(MultiTenancyForbiddenError):
            AgentRunner(
                SkillRegistry(),
                neo4j=neo,
                expected_dataset_id="ob-2026",
            )

    def test_runner_skips_check_without_neo4j(self):
        # No neo4j → no integrity check, even with expected_dataset_id.
        r = AgentRunner(
            SkillRegistry(),
            expected_dataset_id="ob-2026",
        )
        self.assertEqual(r.expected_dataset_id, "ob-2026")
        self.assertIsNone(r.neo4j)

    def test_runner_skips_check_without_expected_dataset(self):
        # neo4j provided but no expected_dataset_id → no integrity check.
        neo = _FakeNeo4j(loaded_dataset="something")
        r = AgentRunner(SkillRegistry(), neo4j=neo)
        self.assertEqual(r.neo4j, neo)
        # No MATCH issued
        match_calls = [c for c, _ in neo.calls if "graphmetadata" in c.lower()]
        self.assertEqual(len(match_calls), 0)


if __name__ == "__main__":
    unittest.main()
