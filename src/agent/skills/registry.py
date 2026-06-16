"""Skill registry — name → Skill instance lookup.

The runner never imports a concrete skill class. It calls
`registry.get("retrieve_dense")` and gets back a Skill instance. This
means:
    - New skills are added in their own file + one `register_skill()` line.
    - Ablations disable skills by removing them from the registry copy.
    - The controller sees the same registry, so plans can reference any
      registered skill by name.

The registry is a thin global-with-explicit-clear (good enough for v1).
v2 might swap to a per-Runner registry for parallel ablation runs.

Spec: `DOCS/docs7/AGENTIC-SYSTEM.md` §5.
"""

from __future__ import annotations

import logging
from copy import copy
from typing import Iterator

from .base import Skill


log = logging.getLogger(__name__)


class SkillRegistry:
    """Name → Skill mapping.

    Methods:
        register(skill)            — add a skill; raises on name conflict
        get(name)                  — fetch; raises KeyError on miss
        try_get(name)              — fetch; returns None on miss
        names()                    — list of registered skill names
        clear()                    — remove all entries (test hygiene)
        copy()                     — shallow copy for ablation re-config
        copy_without(names)        — copy with `names` removed (ablation API)
        copy_only(names)           — copy keeping only `names` (enable_skills_exact)
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    # ------------------------------------------------------------------ mutate

    def register(self, skill: Skill) -> None:
        if not skill.name:
            raise ValueError(f"Skill {type(skill).__name__} has empty `name`")
        if skill.name in self._skills:
            existing = self._skills[skill.name]
            raise ValueError(
                f"Skill name conflict: {skill.name!r} already registered as "
                f"{type(existing).__name__}@{existing.version}; "
                f"attempted re-registration with {type(skill).__name__}@{skill.version}",
            )
        self._skills[skill.name] = skill
        log.debug("registered skill: %s@%s", skill.name, skill.version)

    def unregister(self, name: str) -> Skill | None:
        return self._skills.pop(name, None)

    def clear(self) -> None:
        self._skills.clear()

    # ------------------------------------------------------------------ lookup

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise KeyError(f"Skill not registered: {name!r}. "
                           f"Known: {sorted(self._skills)}")
        return self._skills[name]

    def try_get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def __getitem__(self, name: str) -> Skill:
        return self.get(name)

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self) -> Iterator[Skill]:
        return iter(self._skills.values())

    def names(self) -> list[str]:
        return sorted(self._skills)

    # ------------------------------------------------------------------ copy / ablate

    def copy(self) -> "SkillRegistry":
        """Shallow copy; the underlying Skill instances are shared
        (skills are stateless, so this is safe)."""
        new = SkillRegistry()
        new._skills = dict(self._skills)
        return new

    def copy_without(self, names) -> "SkillRegistry":
        """Return a copy with the named skills removed.

        Used by the §9 ablation harness — `--disable-skills verify_with_llm`
        translates to `registry.copy_without({"verify_with_llm"})`."""
        drop = set(names)
        new = SkillRegistry()
        new._skills = {n: s for n, s in self._skills.items() if n not in drop}
        return new

    def copy_only(self, names) -> "SkillRegistry":
        """Return a copy keeping only the named skills.

        Used for `--enable-skills-exact retrieve_dense,compose_l2,...`
        ablations that test "what if only these skills existed?"."""
        keep = set(names)
        unknown = keep - set(self._skills)
        if unknown:
            raise KeyError(
                f"Cannot enable-exact unknown skills: {sorted(unknown)}",
            )
        new = SkillRegistry()
        new._skills = {n: s for n, s in self._skills.items() if n in keep}
        return new

    def __repr__(self) -> str:
        names = ",".join(self.names())
        return f"SkillRegistry({len(self._skills)} skills: {names})"


# ---------------------------------------------------------------------------
# Module-level default registry — convenient for production code that
# only ever needs one registry. Tests should use a local SkillRegistry()
# to avoid global-state cross-contamination.
# ---------------------------------------------------------------------------


_default_registry: SkillRegistry | None = None


def get_default_registry() -> SkillRegistry:
    """Lazy-initialise the process-wide default registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = SkillRegistry()
    return _default_registry


def reset_default_registry() -> None:
    """Drop the default registry (mainly for test setup/teardown)."""
    global _default_registry
    _default_registry = None


def register_skill(skill: Skill) -> Skill:
    """Convenience: register on the default registry; return the skill.

    Typical use at module import time::

        from agent.skills.registry import register_skill
        from agent.skills.base import Skill, SkillOutput

        class MyRetriever(Skill):
            name = "my_retriever"
            version = "1.0.0"
            def invoke(self, bundle, memory, ctx) -> SkillOutput:
                ...

        register_skill(MyRetriever())
    """
    get_default_registry().register(skill)
    return skill
