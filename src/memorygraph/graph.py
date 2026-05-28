"""MemoryGraph — typed in-memory store of cross-context entity nodes + edges.

The graph holds three node families:

  1. **window nodes** — one per telemetry window we've ingested (transient,
     re-built per query in the pipeline; not persisted).
  2. **jira nodes** — one per Jira memory entry (persistent across queries
     for the lifetime of a `MemoryGraphPipeline`).
  3. **entity nodes** — one per `EntityId` discovered by either extractor
     (shared between the two domains — this is the join).

Edge families:

  * **membership** (`window--has-->entity`, `jira--has-->entity`)
  * **relation** (entity--rel-->entity), only created when both an obs and
    a jira node touch the same entity. These are the bridges retrieval
    actually traverses.

Why hand-roll a graph rather than use networkx:

  - The whole project is dependency-cautious (see `microservices-demo-google`
    fork policy, optional sentence-transformers, etc). networkx pulls in
    scipy/numpy for trivial operations we don't need.
  - Our query pattern is narrow: "neighbors of node X by relation R", which
    is a dict-of-set lookup. A 60-line custom store is faster to read and
    review than a wrapper around a bigger library.

Performance: 100% pure Python. On v5-quick (48 Jira, ~470 windows) the
build runs in well under a second.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from loganalyzer.data.schema import JiraMemoryIssue, TriageWindow

from .entities import (
    BRIDGEABLE_KINDS,
    Edge,
    Entity,
    EntityId,
    EntityKind,
    SEVERITY_ORDINAL,
    extract_jira_entities,
    extract_obs_entities,
)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass
class GraphStats:
    """Diagnostic summary of the graph that we write to disk for inspection."""

    n_jira_nodes: int = 0
    n_window_nodes: int = 0
    n_entity_nodes: int = 0
    n_membership_edges: int = 0
    n_relation_edges: int = 0
    entities_per_kind: dict[str, int] = field(default_factory=dict)
    bridges_per_kind: dict[str, int] = field(default_factory=dict)
    dropped_lab_labels: int = 0

    def as_dict(self) -> dict:
        return {
            "n_jira_nodes": self.n_jira_nodes,
            "n_window_nodes": self.n_window_nodes,
            "n_entity_nodes": self.n_entity_nodes,
            "n_membership_edges": self.n_membership_edges,
            "n_relation_edges": self.n_relation_edges,
            "entities_per_kind": dict(self.entities_per_kind),
            "bridges_per_kind": dict(self.bridges_per_kind),
            "dropped_lab_labels": self.dropped_lab_labels,
        }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class MemoryGraph:
    """Adjacency-list graph keyed by string node ids.

    Entity nodes use `EntityId.key()` ("component:paymentservice").
    Window nodes use `window_id`.
    Jira nodes use `jira_shadow_issue_id`.

    The store is intentionally write-then-read — there's no "delete edge"
    operation. The pipeline builds the graph once for the Jira corpus,
    then adds + removes window nodes per query.
    """

    def __init__(self) -> None:
        # node_id -> {"kind": str, "domain": str, "attrs": dict, "source": str|None}
        self.nodes: dict[str, dict] = {}
        # outgoing edges: src -> list[Edge]
        self.out: dict[str, list[Edge]] = defaultdict(list)
        # incoming edges: dst -> list[Edge]
        self.into: dict[str, list[Edge]] = defaultdict(list)
        # entity_id -> set of (window or jira) node ids touching it,
        # broken out by domain for fast cross-domain lookups
        self.entity_owners: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: {"obs": set(), "jira": set()}
        )

    # -- node ops ---------------------------------------------------------

    def add_node(
        self,
        node_id: str,
        kind: str,
        *,
        domain: str | None = None,
        attrs: dict | None = None,
        source: str | None = None,
    ) -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                "kind": kind,
                "domain": domain,
                "attrs": attrs or {},
                "source": source,
            }

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all its incident edges.

        Used to clear transient window nodes between queries. Entity
        nodes themselves are kept — they're shared across queries.
        """
        if node_id not in self.nodes:
            return
        for edge in list(self.out.get(node_id, [])):
            self._remove_edge(edge)
        for edge in list(self.into.get(node_id, [])):
            self._remove_edge(edge)
        self.out.pop(node_id, None)
        self.into.pop(node_id, None)
        self.nodes.pop(node_id, None)

    # -- edge ops ---------------------------------------------------------

    def add_edge(self, edge: Edge) -> None:
        self.out[edge.src].append(edge)
        self.into[edge.dst].append(edge)

    def _remove_edge(self, edge: Edge) -> None:
        if edge in self.out.get(edge.src, []):
            self.out[edge.src].remove(edge)
        if edge in self.into.get(edge.dst, []):
            self.into[edge.dst].remove(edge)

    # -- queries ----------------------------------------------------------

    def neighbors(
        self,
        node_id: str,
        *,
        relation: str | None = None,
        direction: str = "out",
    ) -> list[Edge]:
        """Return edges incident on `node_id`. `direction` is 'out' or 'in'."""
        edges = self.out.get(node_id, []) if direction == "out" else self.into.get(node_id, [])
        if relation is None:
            return list(edges)
        return [e for e in edges if e.relation == relation]

    def entities_of(self, node_id: str) -> list[Entity]:
        """All entity nodes a window or jira node `has` an edge to."""
        out: list[Entity] = []
        for edge in self.out.get(node_id, []):
            if edge.relation != "has":
                continue
            n = self.nodes.get(edge.dst)
            if not n or n["kind"] != "entity":
                continue
            kind, value = edge.dst.split(":", 1)
            out.append(
                Entity(
                    id=EntityId(kind, value),
                    domain=n.get("domain") or "shared",
                    source_id=node_id,
                    attributes=n.get("attrs", {}),
                )
            )
        return out

    def jira_candidates_for(self, window_id: str) -> list[str]:
        """Jira nodes that share ANY entity with the given window node.

        This is the "direct-mapping" pre-filter the project sketch calls
        for: only keep Jira memories that touch at least one entity the
        window also touches. On v5-quick this typically cuts the
        candidate pool from ~48 -> ~12.
        """
        window_entities = {e.id.key() for e in self.entities_of(window_id)}
        if not window_entities:
            return []
        candidate_set: set[str] = set()
        for entity_key in window_entities:
            owners = self.entity_owners.get(entity_key, {}).get("jira", set())
            candidate_set.update(owners)
        return sorted(candidate_set)

    def shared_entities(self, window_id: str, jira_id: str) -> list[Entity]:
        """Entity nodes that bridge window_id <-> jira_id."""
        win_keys = {e.id.key(): e for e in self.entities_of(window_id)}
        out: list[Entity] = []
        for e in self.entities_of(jira_id):
            if e.id.key() in win_keys:
                out.append(e)
        return out

    def bridge_weight(self, eid: EntityId) -> float:
        """How discriminative is this entity as a cross-domain bridge?

        Reads the entity node's self-edge of relation='bridge' set by the
        builder when both obs and jira sides touch the same entity.
        Returns 0.0 when no bridge edge exists yet.
        """
        for edge in self.out.get(eid.key(), []):
            if edge.relation == "bridge":
                return edge.weight
        return 0.0


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class MemoryGraphBuilder:
    """Builds a MemoryGraph from a Jira corpus + (optionally) a stream of windows.

    Typical lifecycle inside the pipeline:

        builder = MemoryGraphBuilder()
        builder.add_jira_corpus(memory_corpus)  # once
        for window in windows:
            builder.add_window(window)
            ... query ...
            builder.remove_window(window.window_id)
    """

    def __init__(self) -> None:
        self.graph = MemoryGraph()
        self.stats = GraphStats()

    # -- ingest ----------------------------------------------------------

    def add_jira_corpus(self, issues: Iterable[JiraMemoryIssue]) -> None:
        for issue in issues:
            self._add_jira(issue)
        self._materialize_bridges()

    def add_window(self, window: TriageWindow) -> None:
        entities, summary = extract_obs_entities(window)
        self.graph.add_node(
            window.window_id,
            kind="window",
            domain="obs",
            attrs={
                "service": window.service_name,
                "window_type": window.window_type,
                "p95_ms": summary.get("p95_ms"),
            },
            source=window.window_id,
        )
        self.stats.n_window_nodes += 1
        for ent in entities:
            self._add_entity_node(ent, window_or_jira_id=window.window_id)
        # Re-materialize bridges incident on the new window's entities so
        # the cross-domain edges include this window.
        for ent in entities:
            self._materialize_bridges_for_entity(ent.id)

    def remove_window(self, window_id: str) -> None:
        self.graph.remove_node(window_id)
        # Owner sets — strip references to the removed window
        for owners in self.graph.entity_owners.values():
            owners["obs"].discard(window_id)
        self.stats.n_window_nodes = max(0, self.stats.n_window_nodes - 1)

    # -- internals -------------------------------------------------------

    def _add_jira(self, issue: JiraMemoryIssue) -> None:
        entities, summary = extract_jira_entities(issue)
        self.graph.add_node(
            issue.jira_shadow_issue_id,
            kind="jira",
            domain="jira",
            attrs={
                "affected_service": issue.affected_service,
                "severity": issue.severity,
                "fault_class": issue.fault_compatibility_class,
                "available_as_memory_from": issue.available_as_memory_from,
                "dataset_run_id": issue.dataset_run_id,
                "labels_kept": summary.get("kept_labels", []),
            },
            source=issue.jira_shadow_issue_id,
        )
        self.stats.n_jira_nodes += 1
        self.stats.dropped_lab_labels += len(summary.get("dropped_labels", []))
        for ent in entities:
            self._add_entity_node(ent, window_or_jira_id=issue.jira_shadow_issue_id)

    def _add_entity_node(self, entity: Entity, *, window_or_jira_id: str) -> None:
        key = entity.id.key()
        if key not in self.graph.nodes:
            self.graph.add_node(
                key,
                kind="entity",
                domain="shared",
                attrs={"entity_kind": entity.id.kind, "value": entity.id.value},
            )
            self.stats.n_entity_nodes += 1
            self.stats.entities_per_kind[entity.id.kind] = (
                self.stats.entities_per_kind.get(entity.id.kind, 0) + 1
            )
        # owner index by domain
        self.graph.entity_owners[key][entity.domain].add(window_or_jira_id)
        # parent -> entity membership edge
        self.graph.add_edge(
            Edge(
                src=window_or_jira_id,
                dst=key,
                relation="has",
                weight=1.0,
                attributes=dict(entity.attributes),
            )
        )
        self.stats.n_membership_edges += 1

    def _materialize_bridges(self) -> None:
        """Create entity<->entity edges of type 'bridge' on the Jira side.

        At corpus-load time only Jira owners exist; obs owners get added
        when windows are ingested. The bridges (cross-domain edges) are
        the edges between entities that have BOTH obs and jira owners.
        We re-evaluate them every time a new window is added — see
        `_materialize_bridges_for_entity`.
        """
        # Co-occurrence within Jira: for every Jira issue, every pair of
        # its entities forms a within-jira bridge. These are useful for
        # graph_traverse explanations even before any window is ingested.
        # Snapshot first — we're about to add edges to self.graph.out so
        # we can't iterate its live view.
        jira_node_ids = [
            nid for nid, n in self.graph.nodes.items() if n["kind"] == "jira"
        ]
        for jira_id in jira_node_ids:
            entity_keys = [
                e.dst for e in self.graph.out.get(jira_id, []) if e.relation == "has"
            ]
            for i in range(len(entity_keys)):
                for j in range(i + 1, len(entity_keys)):
                    a, b = entity_keys[i], entity_keys[j]
                    self.graph.add_edge(
                        Edge(a, b, relation="co_in_jira", weight=1.0)
                    )
                    self.graph.add_edge(
                        Edge(b, a, relation="co_in_jira", weight=1.0)
                    )
                    self.stats.n_relation_edges += 2

    def _materialize_bridges_for_entity(self, eid: EntityId) -> None:
        """When a new obs side touches an entity, add the obs<->jira bridge.

        We don't create one bridge per (window, jira) pair — that would
        explode the graph. Instead we create logical "this entity is the
        bridge" edges with relation='bridge', weight proportional to how
        rare the entity is in the Jira corpus (rare = informative).
        """
        key = eid.key()
        owners = self.graph.entity_owners.get(key)
        if not owners or not owners["obs"] or not owners["jira"]:
            return
        # Has this bridge already been recorded? Look for an existing
        # 'bridge' self-edge on the entity node.
        existing = [e for e in self.graph.out.get(key, []) if e.relation == "bridge"]
        if existing:
            return
        n_jira_total = self.stats.n_jira_nodes or 1
        n_jira_with = len(owners["jira"])
        rarity = 1.0 - (n_jira_with / n_jira_total)
        # Self-edge encodes the bridge attribute — cheap to query.
        self.graph.add_edge(
            Edge(
                src=key,
                dst=key,
                relation="bridge",
                weight=max(0.05, rarity),
                attributes={
                    "kind": eid.kind,
                    "n_jira_owners": n_jira_with,
                    "n_obs_owners": len(owners["obs"]),
                },
            )
        )
        self.stats.bridges_per_kind[eid.kind] = (
            self.stats.bridges_per_kind.get(eid.kind, 0) + 1
        )
        self.stats.n_relation_edges += 1

    # -- scoring helpers used by skills.py -------------------------------

    def bridge_weight(self, eid: EntityId) -> float:
        """How discriminative is this entity as a cross-domain bridge?

        Returns 0.0 if the entity has no bridge edge (i.e. only one
        domain has discovered it).
        """
        for edge in self.graph.out.get(eid.key(), []):
            if edge.relation == "bridge":
                return edge.weight
        return 0.0

    def severity_compatibility(self, window_severity: str | None, jira_severity: str | None) -> float:
        """Coarse severity alignment between an inferred window severity and a Jira severity.

        We never trust the window's own `triage_severity` (eval-only).
        The window severity here is *inferred* from k8s + trace features
        by the relevant skill; this method just compares the two
        ordinals.
        """
        a = SEVERITY_ORDINAL.get((window_severity or "").lower(), 0)
        b = SEVERITY_ORDINAL.get((jira_severity or "").lower(), 0)
        if a == 0 or b == 0:
            return 0.0
        delta = abs(a - b)
        if delta == 0:
            return 1.0
        if delta == 1:
            return 0.5
        return 0.0
