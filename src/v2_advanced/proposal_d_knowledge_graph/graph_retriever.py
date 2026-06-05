"""Cypher-based retriever — score memory tickets by graph-entity overlap
with a live window's extracted entities.

Used standalone (as the entire retrieval head for a graph-only pipeline)
OR fused with dense/sparse retrievers via RRF in Phase C.

The scoring is interpretable: for any returned candidate we can produce
a short natural-language explanation ("shared services: A, B; shared
error classes: X").
"""
from __future__ import annotations

from typing import Any

from v2_advanced.shared import Neo4jClient, get_logger

from .schema import WindowExtraction

log = get_logger("phase_d.retriever")


# Default scoring weights (tunable per pipeline if needed).
DEFAULT_WEIGHTS = {
    "service": 2.0,
    "error_class": 3.0,
    "component": 1.5,
    "symptom": 1.0,
    "severity_match": 0.5,
    "family_match": 1.0,
}


_RETRIEVE_CYPHER = """
WITH $window AS w, $weights AS wt
MATCH (i:Incident)
WHERE
  // Time-ordered visibility: only consider incidents that existed before
  // this window's timestamp. Caller passes w.before_ts (ISO string).
  (w.before_ts = '' OR i.timestamp = '' OR i.timestamp < w.before_ts)
WITH i, w, wt,
     // Service overlap
     [s IN w.affected_services WHERE EXISTS {
       MATCH (i)-[:AFFECTS]->(:Service {name: s})
     }] AS svc_match,
     // Component overlap
     [c IN w.components WHERE EXISTS {
       MATCH (i)-[:INVOLVES]->(:Component {name: c})
     }] AS comp_match,
     // Error class overlap
     [e IN w.error_classes WHERE EXISTS {
       MATCH (i)-[:RAISED]->(:ErrorClass {name: e})
     }] AS err_match,
     // Symptom overlap (description match)
     [s IN w.symptoms WHERE EXISTS {
       MATCH (i)-[:EXHIBITED]->(:Symptom {description: s})
     }] AS sym_match
WITH i, w, wt, svc_match, comp_match, err_match, sym_match,
     // Severity match bonus
     CASE WHEN i.severity = w.severity AND w.severity <> '' THEN 1.0 ELSE 0.0 END AS sev_bonus,
     // Family match bonus (in-distribution: when the family is known)
     CASE WHEN i.family = w.family AND w.family <> '' THEN 1.0 ELSE 0.0 END AS fam_bonus
WITH i,
     (
       size(svc_match)  * wt.service
     + size(comp_match) * wt.component
     + size(err_match)  * wt.error_class
     + size(sym_match)  * wt.symptom
     + sev_bonus        * wt.severity_match
     + fam_bonus        * wt.family_match
     ) AS score,
     svc_match, comp_match, err_match, sym_match
WHERE score > 0
RETURN
    i.id AS ticket_id,
    score,
    svc_match AS matched_services,
    err_match AS matched_error_classes,
    comp_match AS matched_components,
    sym_match  AS matched_symptoms
ORDER BY score DESC
LIMIT $k
"""


class GraphRetriever:
    """Wrap a Neo4j connection + the scoring Cypher.

    Designed to be reused across many window queries — keep one client
    open and call .retrieve() repeatedly.
    """

    def __init__(
        self,
        client: Neo4jClient,
        *,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.client = client
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    def retrieve(
        self,
        window: WindowExtraction,
        *,
        top_k: int = 20,
        before_ts: str = "",
    ) -> list[dict[str, Any]]:
        """Return up to top_k Incidents scored by entity overlap with this
        window. before_ts is the ISO timestamp the window observed at —
        only earlier-timestamped incidents are eligible (time-ordered
        visibility). Pass empty string to disable the filter.
        """
        params = {
            "window": {
                "affected_services": window.affected_services,
                "components": window.components,
                "error_classes": window.error_classes,
                "symptoms": window.symptoms,
                "severity": window.severity,
                "family": window.family,
                "before_ts": before_ts,
            },
            "weights": self.weights,
            "k": top_k,
        }
        try:
            rows = self.client.run(_RETRIEVE_CYPHER, **params)
        except Exception as e:
            log.error("graph retrieve failed", window=window.window_id, err=str(e)[:200])
            return []
        return rows

    def retrieve_ids(self, window: WindowExtraction, *, top_k: int = 20, before_ts: str = "") -> list[str]:
        return [r["ticket_id"] for r in self.retrieve(window, top_k=top_k, before_ts=before_ts)]
