"""Vocabulary firewall: lab-leakage detector for LLM inputs.

Implements Rule 1 from LLM-Jira-enhancement.md §3. **Fails loud** when
any lab-only token appears in a string that's about to be sent to the
LLM. Loud failure is a feature: silent stripping would let leaks
through, and we'd never notice until a held-out family scored
suspiciously well.

Three modes:
  * `assert_clean(text)` — raise on any lab token. Use on the final
    composed prompt before .complete().
  * `find_lab_tokens(text) -> list[str]` — return the matches without
    raising. Use in audit code paths and test fixtures.
  * `redact(text) -> str` — soft-replace lab tokens with `<REDACTED>`.
    Use only when re-flowing legacy text through the pipeline; never on
    fresh LLM input.

The token list is the union of:
  1. Exact strings from triage_labels.py taxonomies (scenario_id /
     scenario_family / fault_type / reason_class enums)
  2. Substring patterns (`scenario-`, `dataset-`, `synthetic-`, …)
  3. Lab-only vocabulary (`fault`, `injected`, `chaos-mesh`, …)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

# Pull the canonical scenario taxonomies from triage_labels.py if
# available. If not (e.g., when running the unit tests in isolation),
# we still have the curated string lists below as a fallback.
_REPO_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts" / "research-lab"
if str(_REPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_REPO_SCRIPTS))

try:
    from triage_labels import SCENARIO_FAMILIES as _SCENARIO_FAMILIES  # type: ignore[no-redef]
except ImportError:
    _SCENARIO_FAMILIES = {}  # type: ignore[assignment]


# Version this file. Bump when the leakage detector's vocabulary
# changes so generation manifests can record which sanitizer was used.
SANITIZER_VERSION = "v1.0.0"


# Substring patterns. Any occurrence (case-insensitive) is a leak.
_LEAK_PREFIXES: tuple[str, ...] = (
    "scenario-",
    "scenario_id",
    "scenario_family",
    "dataset-",
    "dataset_run",
    "fault.injected",
    "fault_injected",
    "fault_compatibility",
    "expected_severity",
    "expected_in_memory",
    "triage_label",
    "triage_severity",
    "triage_components",
    "triage_reason_class",
    "is_hard_case",
    "is_novel",
    "incident_type",
    "root_cause_category",
    "synthetic-incident",
    "synthetic_incident",
    "telemetry-linked",
    "telemetry_linked",
    "chaos-mesh",
    "chaosmesh",
    "chaos_mesh",
    "networkchaos",
    "dnschaos",
    "stresschaos",
    "iochaos",
    "podchaos",
)


# Whole-word patterns that are too generic to use as substring matches.
# `fault` is a real engineering word — we ban it as a standalone token
# only, not as part of `default` or `faulty`.
_LEAK_WORDS: tuple[str, ...] = (
    "fault",
    "injected",
    "lab",
    "labonly",
    "nearmiss",
    "near-miss",
    "borderline",     # eval-only label
    "ticket_worthy",  # eval-only label
    "noise_window",
)


def _leak_taxonomy_tokens() -> set[str]:
    """Pull the SCENARIO_FAMILIES taxonomy in as exact-match tokens.

    These are strings like `cart-redis`, `payment-outage`, … that name
    the lab fault families. Any of them appearing in an LLM input would
    be a perfect oracle.
    """
    out: set[str] = set()
    for family_name in _SCENARIO_FAMILIES.keys():
        out.add(str(family_name).lower())
        # Family names with dashes also leak as underscore variants.
        out.add(str(family_name).replace("-", "_").lower())
    # Scenario IDs are inside the values; pull those too.
    for value in _SCENARIO_FAMILIES.values():
        if isinstance(value, (list, tuple, set)):
            for sid in value:
                out.add(str(sid).lower())
                out.add(str(sid).replace("-", "_").lower())
    return out


_TAXONOMY_TOKENS = _leak_taxonomy_tokens()


# Pre-compile a single regex for substring patterns.
_LEAK_PREFIX_RE = re.compile(
    "|".join(re.escape(p) for p in _LEAK_PREFIXES),
    re.IGNORECASE,
)
_LEAK_WORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _LEAK_WORDS) + r")\b",
    re.IGNORECASE,
)


class LabLeakError(Exception):
    """Raised by assert_clean when the input contains lab vocabulary."""


def find_lab_tokens(text: str) -> list[str]:
    """Return every lab-leakage token found in `text` (deduped, in order)."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for m in _LEAK_PREFIX_RE.finditer(text):
        tok = m.group(0).lower()
        if tok not in seen:
            seen.add(tok)
            found.append(tok)
    for m in _LEAK_WORD_RE.finditer(text):
        tok = m.group(0).lower()
        if tok not in seen:
            seen.add(tok)
            found.append(tok)
    # Taxonomy tokens — also lowercase whole-word check.
    lowered = text.lower()
    for token in _TAXONOMY_TOKENS:
        if not token:
            continue
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            if token not in seen:
                seen.add(token)
                found.append(token)
    return found


def assert_clean(text: str, *, context: str = "LLM input") -> None:
    """Raise LabLeakError if `text` contains any lab-leakage token.

    `context` is included in the error message so the caller can tell
    which prompt segment leaked (system message vs evidence vs prior
    conversation).
    """
    found = find_lab_tokens(text)
    if found:
        sample = ", ".join(repr(t) for t in found[:6])
        more = "" if len(found) <= 6 else f" (+{len(found)-6} more)"
        raise LabLeakError(
            f"Lab-leakage tokens found in {context}: {sample}{more}"
        )


def redact(text: str) -> str:
    """Soft-replace lab tokens with `<REDACTED>`. NOT for fresh LLM input.

    Use for re-flowing legacy descriptions or comments where we know the
    text was written by the old generator. Prefer to regenerate from
    scratch when possible.
    """
    if not text:
        return ""
    out = _LEAK_PREFIX_RE.sub("<REDACTED>", text)
    out = _LEAK_WORD_RE.sub("<REDACTED>", out)
    if _TAXONOMY_TOKENS:
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(t) for t in _TAXONOMY_TOKENS if t) + r")\b",
            re.IGNORECASE,
        )
        out = pattern.sub("<REDACTED>", out)
    return out


def assert_all_clean(texts: Iterable[str], *, context: str = "LLM input") -> None:
    """Convenience: validate a sequence of strings (e.g. every evidence quote)."""
    for i, t in enumerate(texts):
        assert_clean(t, context=f"{context}[{i}]")
