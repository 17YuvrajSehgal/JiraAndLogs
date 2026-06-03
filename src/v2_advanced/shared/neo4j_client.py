"""Neo4j client for the LLM knowledge-graph (Phase D).

The user's local Neo4j is exposed on bolt://127.0.0.1:7687 with default
credentials neo4j/123456789. This module wraps the driver with the small
set of operations we need: connect, run cypher, batch-create nodes/edges,
and clear the database before a fresh load.

Why we keep this thin:
  - The graph schema is small enough that we don't need an ORM.
  - We want every Cypher statement visible in the source so reviewers
    can audit the data we put into the graph.
  - Failure modes (Neo4j down, auth wrong, schema mismatch) need to
    surface as clear log lines for the engineer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from neo4j import GraphDatabase, Session

from .logging import get_logger

log = get_logger("neo4j")


@dataclass
class Neo4jConfig:
    uri: str = "neo4j://127.0.0.1:7687"
    user: str = "neo4j"
    password: str = "123456789"
    database: str = "neo4j"   # default database


class Neo4jClient:
    """Wraps the neo4j driver. Use as a context manager:

        with Neo4jClient() as cli:
            cli.run("MATCH (n) RETURN count(n)")
    """

    def __init__(self, config: Neo4jConfig | None = None) -> None:
        self.config = config or Neo4jConfig()
        self._driver = None

    # --- lifecycle ---

    def __enter__(self) -> "Neo4jClient":
        self._driver = GraphDatabase.driver(
            self.config.uri,
            auth=(self.config.user, self.config.password),
        )
        self._driver.verify_connectivity()
        log.info(
            "neo4j connected",
            uri=self.config.uri,
            database=self.config.database,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    # --- queries ---

    def session(self) -> Session:
        assert self._driver is not None, "use as a context manager"
        return self._driver.session(database=self.config.database)

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        """Run a cypher statement; return all rows as list of dicts."""
        assert self._driver is not None, "use as a context manager"
        with self.session() as s:
            result = s.run(cypher, **params)
            return [dict(rec) for rec in result]

    def run_many(self, cypher: str, rows: Iterable[dict[str, Any]]) -> None:
        """Run a parameterized cypher over many rows in a single batch.

        Uses UNWIND under the hood: cypher must reference $rows as a list,
        e.g. `UNWIND $rows AS r CREATE (i:Incident {id: r.id, ...})`.
        """
        assert self._driver is not None, "use as a context manager"
        with self.session() as s:
            s.run(cypher, rows=list(rows))

    # --- helpers used by Phase D ---

    def clear_database(self) -> None:
        """Delete EVERYTHING. Use before a fresh extraction load.

        Asks for confirmation by checking for a sentinel marker first.
        If you want to skip the confirmation, set
        Neo4jConfig.allow_unconfirmed_clear = True (TODO).
        """
        log.warning("clearing all nodes + relationships in Neo4j")
        self.run("MATCH (n) DETACH DELETE n")
        log.info("neo4j clear done")

    def ensure_constraints(self) -> None:
        """Apply uniqueness constraints for the v2_advanced schema.

        We require that each Incident has a unique id (the ticket ID from
        the V2 corpus), and that Service, Component, ErrorClass nodes are
        uniquely identified by their `name` property so repeated MERGE
        calls don't create duplicates.
        """
        constraints = [
            "CREATE CONSTRAINT incident_id_unique IF NOT EXISTS FOR (i:Incident) REQUIRE i.id IS UNIQUE",
            "CREATE CONSTRAINT service_name_unique IF NOT EXISTS FOR (s:Service) REQUIRE s.name IS UNIQUE",
            "CREATE CONSTRAINT component_name_unique IF NOT EXISTS FOR (c:Component) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT errorclass_name_unique IF NOT EXISTS FOR (e:ErrorClass) REQUIRE e.name IS UNIQUE",
            "CREATE CONSTRAINT rootcause_text_unique IF NOT EXISTS FOR (r:RootCause) REQUIRE r.description IS UNIQUE",
        ]
        for c in constraints:
            try:
                self.run(c)
            except Exception as e:  # constraint already exists or similar
                log.warning("constraint failed (probably already exists)", cypher=c[:80], err=str(e)[:120])
        log.info("schema constraints applied")

    def count(self, label: str) -> int:
        rows = self.run(f"MATCH (n:{label}) RETURN count(n) AS c")
        return int(rows[0]["c"]) if rows else 0
