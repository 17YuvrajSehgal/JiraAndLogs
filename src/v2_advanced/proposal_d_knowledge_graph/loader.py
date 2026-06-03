"""Load a batch of IncidentExtractions into Neo4j as graph nodes + edges.

Uses MERGE statements so the loader is idempotent — running it twice
in a row produces the same graph state.

Schema is defined in `schema.py` and reproduced as constraints in
`Neo4jClient.ensure_constraints()`.
"""
from __future__ import annotations

from typing import Iterable

from v2_advanced.shared import Neo4jClient, get_logger, log_step

from .schema import IncidentExtraction

log = get_logger("phase_d.loader")


_INCIDENT_LOAD_CYPHER = """
UNWIND $rows AS r
MERGE (i:Incident {id: r.ticket_id})
SET i.severity = r.severity,
    i.family = r.family,
    i.timestamp = r.timestamp,
    i.root_cause_text = r.root_cause,
    i.fix_text = r.fix,
    i.fix_kind = r.fix_kind

// Services
FOREACH (s_name IN r.affected_services |
  MERGE (s:Service {name: s_name})
  MERGE (i)-[:AFFECTS]->(s)
)

// Components
FOREACH (c_name IN r.components |
  MERGE (c:Component {name: c_name})
  MERGE (i)-[:INVOLVES]->(c)
)

// Error classes
FOREACH (e_name IN r.error_classes |
  MERGE (e:ErrorClass {name: e_name})
  MERGE (i)-[:RAISED]->(e)
)

// Root cause (one per incident; we keep the long-form text on the node)
FOREACH (_ IN CASE WHEN r.root_cause = '' THEN [] ELSE [1] END |
  MERGE (rc:RootCause {description: r.root_cause})
  MERGE (i)-[:CAUSED_BY]->(rc)
)

// Fix (description + kind)
FOREACH (_ IN CASE WHEN r.fix = '' THEN [] ELSE [1] END |
  MERGE (f:Fix {description: r.fix})
  SET f.kind = r.fix_kind
  MERGE (i)-[:FIXED_BY]->(f)
)

// Symptoms
FOREACH (sym IN r.symptoms |
  MERGE (sy:Symptom {description: sym})
  MERGE (i)-[:EXHIBITED]->(sy)
)
"""


def load_extractions(
    client: Neo4jClient,
    extractions: Iterable[IncidentExtraction],
    *,
    clear_first: bool = False,
    batch_size: int = 50,
) -> dict[str, int]:
    """Load the extractions into Neo4j.

    Args:
        client: an entered Neo4jClient context (already connected).
        extractions: iterable of IncidentExtraction objects.
        clear_first: if True, delete all nodes/edges before loading.
        batch_size: how many rows per UNWIND batch (50 is a safe default).

    Returns a dict of post-load counts per label.
    """
    extractions = list(extractions)
    with log_step(log, "load_extractions", n=len(extractions), clear_first=clear_first):
        if clear_first:
            client.clear_database()

        client.ensure_constraints()

        rows = [e.as_dict() for e in extractions]
        # Skip extractions that the LLM completely failed on.
        rows = [
            r for r in rows
            if r["affected_services"] or r["components"] or r["error_classes"]
            or r["root_cause"] or r["symptoms"]
        ]

        log.info("loading non-empty extractions", kept=len(rows), dropped=len(extractions) - len(rows))

        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            client.run_many(_INCIDENT_LOAD_CYPHER, batch)
            log.info(f"loaded batch", at=start + len(batch), total=len(rows))

    counts = {
        "Incident": client.count("Incident"),
        "Service": client.count("Service"),
        "Component": client.count("Component"),
        "ErrorClass": client.count("ErrorClass"),
        "RootCause": client.count("RootCause"),
        "Fix": client.count("Fix"),
        "Symptom": client.count("Symptom"),
    }
    log.info("post-load counts", **counts)
    return counts
