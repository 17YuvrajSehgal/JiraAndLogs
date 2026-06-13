"""Integrity-layer exceptions — refusals at agent startup."""

from __future__ import annotations


class IntegrityError(RuntimeError):
    """Base class for all integrity failures.

    All subclasses are raised from `assert_loaded_dataset` (and its
    siblings) and propagate through `AgentRunner.__init__` as a hard
    refusal: the agent will not start with the wrong KG loaded."""


class MetadataMissingError(IntegrityError):
    """Neo4j has no `GraphMetadata` fingerprint node.

    Either Neo4j is empty (never loaded) or the load script predates
    the Phase 1.14 patch. Resolution: run `reload_neo4j --global-dir <X>`
    against the dataset you want to evaluate."""


class DatasetMismatchError(IntegrityError):
    """Neo4j has a different dataset loaded than the experiment expects.

    Carries `expected` and `actual` so callers (CI, scripts) can format
    a clear error. Resolution: re-run `reload_neo4j --global-dir <X>`
    with the right global dir."""

    def __init__(self, *, expected: str, actual: str, loaded_at: str = "") -> None:
        message = (
            f"Neo4j has dataset {actual!r} loaded; experiment expects {expected!r}. "
            f"Run reload_neo4j --global-dir <{expected}> first."
        )
        if loaded_at:
            message += f" (current load timestamp: {loaded_at})"
        super().__init__(message)
        self.expected = expected
        self.actual = actual
        self.loaded_at = loaded_at


class MultiTenancyForbiddenError(IntegrityError):
    """Option-B tenancy signals (nodes carrying a `.dataset` property)
    detected during a research run.

    IMPROVEMENTS §1.1 locks Option A (one dataset per graph). Option B
    is reserved for future production multi-tenancy and explicitly
    forbidden during research evaluation, since one missing `WHERE
    n.dataset = $ds` clause silently contaminates results.

    Resolution: clear the graph and reload with `reload_neo4j` (which
    doesn't write `.dataset` properties); if you genuinely need
    Option B, set NEO4J_DATASET_TAG and accept that the agent will
    refuse to start until you also flip
    `integrity.allow_multi_tenant_for_research_only` (intentionally
    awkward — there is no legitimate research use)."""

    def __init__(self, *, n_tagged_nodes: int) -> None:
        super().__init__(
            f"Multi-tenancy tags detected: {n_tagged_nodes} nodes carry a "
            f".dataset property. Research evaluation forbids Option B "
            f"(IMPROVEMENTS §1.1). Clear the graph and reload.",
        )
        self.n_tagged_nodes = n_tagged_nodes
