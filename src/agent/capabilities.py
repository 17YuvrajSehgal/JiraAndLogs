"""Capabilities — what evidence the current InputBundle carries.

Used by the controller to decide which skills can run. Skills declare
their `required_flags`; the runner skips skills whose flags aren't in
the current Capabilities.

Adding a new evidence modality:
    1. Add the constant below (with a brief comment about what populates it).
    2. Extend `InputBundle` with the matching optional field (`agent.types`).
    3. Wire the modality into `CapabilitiesObserver` (`capabilities_observer.py`)
       so the flag fires when the field is non-empty or when the bundle
       carries an `*_fetchable` marker on `extra`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Capability-flag constants
# ---------------------------------------------------------------------------
# Each flag describes one *kind of evidence*. Skills check membership;
# the controller picks plans; the ablation harness can mask any subset.

#: Window has the 94 triage_feature_* numeric columns (OB / OTel Demo).
NUMERIC_FEATURES = "NUMERIC_FEATURES"

#: Window has a natural-language summary in `text_evidence`.
TEXT_EVIDENCE = "TEXT_EVIDENCE"

#: Window has log lines in chronological order (Loki-style).
ORDERED_LOGS = "ORDERED_LOGS"

#: Window has log lines WITHOUT temporal order (e.g. WoL `log_quotes`).
UNORDERED_LOGS = "UNORDERED_LOGS"

#: Window has a distributed-trace anomaly summary.
TRACE_SUMMARY = "TRACE_SUMMARY"

#: Window has Kubernetes events (pod restarts, OOMKilled, etc.).
K8S_EVENTS = "K8S_EVENTS"

#: Window has Prometheus-style metric snapshots.
METRIC_SNAPSHOTS = "METRIC_SNAPSHOTS"

#: Memory side has `memory_text` populated per ticket.
MEMORY_TEXT = "MEMORY_TEXT"

#: Neo4j has Incident nodes for the memory side of retrieval.
KG_GRAPH_MEMORY = "KG_GRAPH_MEMORY"

#: Per-window LLM-extracted entities exist (closes RQ-A6 when present).
KG_GRAPH_WINDOW = "KG_GRAPH_WINDOW"

#: Dataset is in `verifier_calibration.known_helpful_distributions`.
#: Controls whether `verify_with_llm` runs (closes RQ-A8 on WoL).
VERIFIER_KNOWN_HELPFUL = "VERIFIER_KNOWN_HELPFUL"


#: All standard flags. Useful for ablation studies that mask a subset.
ALL_FLAGS: frozenset[str] = frozenset({
    NUMERIC_FEATURES,
    TEXT_EVIDENCE,
    ORDERED_LOGS,
    UNORDERED_LOGS,
    TRACE_SUMMARY,
    K8S_EVENTS,
    METRIC_SNAPSHOTS,
    MEMORY_TEXT,
    KG_GRAPH_MEMORY,
    KG_GRAPH_WINDOW,
    VERIFIER_KNOWN_HELPFUL,
})


# ---------------------------------------------------------------------------
# Capabilities dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Capabilities:
    """Per-bundle map of available evidence.

    `flags` — the *presence* set. Skills consult this via
    `required_flags.issubset(capabilities.flags)`.

    `richness` — optional secondary detail per flag. Example:
        ``capabilities.richness["ORDERED_LOGS"] = {"n_lines": 47,
                                                    "max_span_s": 312}``
    Controllers use richness for soft thresholds (e.g. skip
    LogSeq2Vec when `n_lines < 8`).

    Instances are frozen; produce a new instance with `with_flags()` /
    `without_flags()` / `with_richness()` helpers. The richness dict is
    shallow-copied to keep the public surface immutable in practice
    even though Python dicts are technically mutable.
    """

    flags: frozenset[str] = field(default_factory=frozenset)
    richness: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ------------------------------------------------------------------ query

    def has(self, flag: str) -> bool:
        return flag in self.flags

    def has_all(self, flags) -> bool:
        return frozenset(flags).issubset(self.flags)

    def has_any(self, flags) -> bool:
        return bool(frozenset(flags) & self.flags)

    def get_richness(self, flag: str, key: str, default: Any = None) -> Any:
        return self.richness.get(flag, {}).get(key, default)

    # ------------------------------------------------------------------ construction helpers

    def with_flags(self, *new_flags: str) -> "Capabilities":
        return Capabilities(
            flags=self.flags | frozenset(new_flags),
            richness=dict(self.richness),
        )

    def without_flags(self, *drop_flags: str) -> "Capabilities":
        return Capabilities(
            flags=self.flags - frozenset(drop_flags),
            richness={k: v for k, v in self.richness.items() if k not in drop_flags},
        )

    def with_richness(self, flag: str, **details: Any) -> "Capabilities":
        new_rich = {k: dict(v) for k, v in self.richness.items()}
        new_rich.setdefault(flag, {}).update(details)
        return Capabilities(flags=self.flags, richness=new_rich)

    def mask(self, drop_flags) -> "Capabilities":
        """Return a copy with the given flags removed.

        Used by the ablation harness — `agent --mask-capabilities ORDERED_LOGS`
        produces a Capabilities without ORDERED_LOGS without touching the
        raw InputBundle.
        """
        return self.without_flags(*drop_flags)

    # ------------------------------------------------------------------ serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "flags": sorted(self.flags),
            "richness": {k: dict(v) for k, v in self.richness.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Capabilities":
        return cls(
            flags=frozenset(d.get("flags") or ()),
            richness=dict(d.get("richness") or {}),
        )

    # ------------------------------------------------------------------ debug

    def __repr__(self) -> str:
        flags_str = ", ".join(sorted(self.flags))
        return f"Capabilities({{{flags_str}}})"
