"""Integrity package — startup safeguards that refuse to run mis-configured.

Closes the "OB and OTel Demo share vocabulary" hazard (IMPROVEMENTS
§1.1): the agent will not start if the loaded Neo4j graph belongs to a
different dataset than the experiment expects, or if Option-B tenancy
tags are present in a research run.

Public API:
  - `GraphMetadata` — fingerprint of the currently-loaded graph.
  - `write_graph_metadata` — called by `reload_neo4j` after a successful load.
  - `read_graph_metadata` — fetch the fingerprint or None if missing.
  - `assert_loaded_dataset` — refuses to return when the wrong dataset
    is loaded (or when no fingerprint exists).
  - `Neo4jLike` — minimal protocol the integrity check requires.

Exceptions:
  - `IntegrityError` (base)
  - `MetadataMissingError`
  - `DatasetMismatchError`
  - `MultiTenancyForbiddenError`

Spec: `DOCS/docs7/IMPROVEMENTS.md` §1.1 (Option A locked).
"""

from .exceptions import (
    DatasetMismatchError,
    IntegrityError,
    MetadataMissingError,
    MultiTenancyForbiddenError,
)
from .graph_metadata import (
    GraphMetadata,
    Neo4jLike,
    assert_loaded_dataset,
    check_no_tenancy_tags,
    read_graph_metadata,
    write_graph_metadata,
)

__all__ = [
    # data
    "GraphMetadata",
    "Neo4jLike",
    # writers + readers
    "write_graph_metadata",
    "read_graph_metadata",
    "check_no_tenancy_tags",
    "assert_loaded_dataset",
    # exceptions
    "IntegrityError",
    "MetadataMissingError",
    "DatasetMismatchError",
    "MultiTenancyForbiddenError",
]
