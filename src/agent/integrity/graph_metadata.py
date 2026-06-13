"""GraphMetadata — fingerprint of the currently-loaded Neo4j graph.

Written by `reload_neo4j` after a successful load; read by
`AgentRunner.__init__` (via `assert_loaded_dataset`) before any KG-using
skill is allowed to run. The pair structurally prevents OB ↔ OTel Demo
silent contamination (same vocabulary, two different ground truths).

Cypher contract:

    MERGE (m:GraphMetadata {key: 'loaded_dataset'})
    SET m.dataset = $dataset_id,
        m.loaded_at = $loaded_at,
        m.n_incidents = $n_incidents,
        m.global_dir = $global_dir

Reader:

    MATCH (m:GraphMetadata {key: 'loaded_dataset'})
    RETURN m.dataset      AS dataset,
           m.loaded_at    AS loaded_at,
           m.n_incidents  AS n_incidents,
           m.global_dir   AS global_dir

The integrity check uses a `Neo4jLike` protocol — any object exposing
`run(cypher: str, **params) -> list[dict]` works. The existing
`v2_advanced.shared.Neo4jClient` satisfies this without modification.

Spec: `DOCS/docs7/IMPROVEMENTS.md` §1.1 (locked Option A).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from .exceptions import (
    DatasetMismatchError,
    MetadataMissingError,
    MultiTenancyForbiddenError,
)


log = logging.getLogger(__name__)


METADATA_KEY = "loaded_dataset"


# ---------------------------------------------------------------------------
# Neo4jLike protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Neo4jLike(Protocol):
    """Minimal interface the integrity check needs.

    `v2_advanced.shared.Neo4jClient` and any other thin Cypher wrapper
    satisfy this implicitly. The check works with stub clients in
    tests too."""

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# GraphMetadata dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphMetadata:
    """One snapshot of the currently-loaded graph's identity."""

    dataset_id: str
    loaded_at: str = ""                 # ISO-8601 UTC; written by Neo4j datetime()
    n_incidents: int = 0
    global_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "loaded_at": self.loaded_at,
            "n_incidents": self.n_incidents,
            "global_dir": self.global_dir,
        }

    @classmethod
    def from_neo4j_row(cls, row: dict[str, Any]) -> "GraphMetadata":
        """Build from a Cypher RETURN row. Coerces missing fields to
        defaults so a partial fingerprint (from an old reload script)
        still constructs."""
        loaded_at = row.get("loaded_at")
        # Neo4j returns its datetime() as a neo4j.time.DateTime instance;
        # str() yields an ISO-8601 string with offset.
        loaded_at_str = "" if loaded_at is None else str(loaded_at)
        return cls(
            dataset_id=str(row.get("dataset") or ""),
            loaded_at=loaded_at_str,
            n_incidents=int(row.get("n_incidents") or 0),
            global_dir=str(row.get("global_dir") or ""),
        )


# ---------------------------------------------------------------------------
# Writer — called by reload_neo4j after a successful load
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_graph_metadata(
    runner: Neo4jLike,
    metadata: GraphMetadata,
    *,
    use_neo4j_datetime: bool = True,
) -> None:
    """Upsert the GraphMetadata fingerprint into the live graph.

    Idempotent: calling twice with the same metadata produces no
    duplicate node. The `loaded_at` field defaults to Neo4j's
    `datetime()` (server-side timestamp) when `use_neo4j_datetime=True`;
    callers that want a Python-side timestamp can pass
    `metadata.loaded_at` and `use_neo4j_datetime=False`."""
    if not metadata.dataset_id:
        raise ValueError("GraphMetadata.dataset_id must be non-empty")

    if use_neo4j_datetime:
        cypher = (
            "MERGE (m:GraphMetadata {key: $key}) "
            "SET m.dataset = $dataset_id, "
            "    m.loaded_at = datetime(), "
            "    m.n_incidents = $n_incidents, "
            "    m.global_dir = $global_dir"
        )
        runner.run(
            cypher,
            key=METADATA_KEY,
            dataset_id=metadata.dataset_id,
            n_incidents=metadata.n_incidents,
            global_dir=metadata.global_dir,
        )
    else:
        cypher = (
            "MERGE (m:GraphMetadata {key: $key}) "
            "SET m.dataset = $dataset_id, "
            "    m.loaded_at = $loaded_at, "
            "    m.n_incidents = $n_incidents, "
            "    m.global_dir = $global_dir"
        )
        runner.run(
            cypher,
            key=METADATA_KEY,
            dataset_id=metadata.dataset_id,
            loaded_at=metadata.loaded_at or _now_iso(),
            n_incidents=metadata.n_incidents,
            global_dir=metadata.global_dir,
        )
    log.info(
        "GraphMetadata fingerprint written: dataset=%s n_incidents=%d",
        metadata.dataset_id, metadata.n_incidents,
    )


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def read_graph_metadata(runner: Neo4jLike) -> GraphMetadata | None:
    """Fetch the current fingerprint; return None if the node doesn't exist."""
    rows = runner.run(
        "MATCH (m:GraphMetadata {key: $key}) "
        "RETURN m.dataset AS dataset, "
        "       m.loaded_at AS loaded_at, "
        "       m.n_incidents AS n_incidents, "
        "       m.global_dir AS global_dir",
        key=METADATA_KEY,
    )
    if not rows:
        return None
    return GraphMetadata.from_neo4j_row(rows[0])


# ---------------------------------------------------------------------------
# Multi-tenancy detector
# ---------------------------------------------------------------------------


def check_no_tenancy_tags(runner: Neo4jLike) -> int:
    """Return the count of nodes carrying a `.dataset` property.

    Used to detect Option-B-style tagged nodes during a research run.
    The fingerprint node itself has `m.dataset` set, so we subtract
    one for it. Any other tagged node ⇒ research-mode violation."""
    rows = runner.run(
        "MATCH (n) WHERE n.dataset IS NOT NULL RETURN count(n) AS c",
    )
    total = int(rows[0]["c"]) if rows else 0
    # Subtract the fingerprint node itself (which legitimately has
    # `.dataset`; that's how the integrity check works).
    return max(0, total - 1)


# ---------------------------------------------------------------------------
# The integrity check
# ---------------------------------------------------------------------------


def assert_loaded_dataset(
    runner: Neo4jLike,
    expected_dataset_id: str,
    *,
    check_tenancy_tags: bool = True,
) -> GraphMetadata:
    """Refuse to return unless Neo4j has `expected_dataset_id` loaded.

    Args:
        runner: a `Neo4jLike` — any object with `.run(cypher, **params)`.
        expected_dataset_id: the dataset the experiment expects.
        check_tenancy_tags: when True (default) also refuse if any
            non-fingerprint node carries a `.dataset` property
            (Option B contamination signal — IMPROVEMENTS §1.1).

    Returns:
        The current `GraphMetadata` on success.

    Raises:
        MetadataMissingError: no fingerprint node — graph never loaded.
        DatasetMismatchError: wrong dataset loaded.
        MultiTenancyForbiddenError: Option-B tags present.
    """
    if not expected_dataset_id:
        raise ValueError(
            "assert_loaded_dataset: expected_dataset_id must be non-empty. "
            "Pass the dataset_id from agent-config.yaml > experiment.dataset_id.",
        )

    metadata = read_graph_metadata(runner)
    if metadata is None:
        raise MetadataMissingError(
            f"No GraphMetadata fingerprint in Neo4j. "
            f"Run reload_neo4j --global-dir <{expected_dataset_id}> first.",
        )

    if metadata.dataset_id != expected_dataset_id:
        raise DatasetMismatchError(
            expected=expected_dataset_id,
            actual=metadata.dataset_id,
            loaded_at=metadata.loaded_at,
        )

    if check_tenancy_tags:
        n_tagged = check_no_tenancy_tags(runner)
        if n_tagged > 0:
            raise MultiTenancyForbiddenError(n_tagged_nodes=n_tagged)

    log.info(
        "GraphMetadata integrity check passed: dataset=%s loaded_at=%s",
        metadata.dataset_id, metadata.loaded_at,
    )
    return metadata
