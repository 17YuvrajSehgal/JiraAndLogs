"""Offline tests for Phase 1.6: Skill ABC + SkillCache + SkillRegistry.

Covers:
    - Skill subclass identity (name validation, can_invoke logic).
    - cache_key stability across same inputs + sensitivity to version bump.
    - SkillCache disk roundtrip, hit/miss counters, version isolation.
    - NullSkillCache always-miss behaviour.
    - SkillRegistry register / get / try_get / copy_without / copy_only.

Run:
    PYTHONPATH=src python -m unittest agent.tests.test_skills_base -v
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from agent import (
    Capabilities,
    InputBundle,
    NUMERIC_FEATURES,
    SkillCallCost,
    SkillOutput,
    TEXT_EVIDENCE,
)
from agent.skills import (
    AgentContext,
    FailureMode,
    MemoryView,
    NullSkillCache,
    Skill,
    SkillCache,
    SkillRegistry,
    make_cost,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class _StubMemoryIssue:
    """Stand-in for core.data.schema.JiraMemoryIssue with a stable id."""
    def __init__(self, issue_id: str):
        self.jira_shadow_issue_id = issue_id


class _SimpleSkill(Skill):
    name = "simple"
    version = "1.0.0"
    required_flags = frozenset()
    cost_class = "cheap"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            triage_score=0.5, matched_issue_ids=("PROJ-1",),
            confidence=0.5,
            cost=make_cost(llm_tokens=0, wall_seconds=0.001),
        )


class _RequiringSkill(Skill):
    name = "requires_text"
    version = "1.0.0"
    required_flags = frozenset({TEXT_EVIDENCE})
    cost_class = "medium"

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(skill=self.name, skill_version=self.version)


class _ExpensiveSkill(Skill):
    name = "expensive"
    version = "1.0.0"
    cost_class = "expensive_llm"
    failure_modes = (
        FailureMode(
            kind="ood",
            description="Tuned on OB; degrades on WoL.",
            citation="DOCS/docs7/MODE3-TCH-LITE-WoL-RESULTS.md §3.9",
        ),
    )

    def invoke(self, bundle, memory, ctx) -> SkillOutput:
        return SkillOutput(
            skill=self.name, skill_version=self.version,
            cost=make_cost(llm_tokens=1000, usd=0.001, wall_seconds=5.0),
        )


def _make_bundle(window_id: str = "w1") -> InputBundle:
    return InputBundle(window_id=window_id, dataset="ob", text_evidence="evidence text")


def _make_memory(*ids: str) -> MemoryView:
    return MemoryView([_StubMemoryIssue(i) for i in ids])


# ---------------------------------------------------------------------------
# Skill ABC
# ---------------------------------------------------------------------------


class TestSkillABC(unittest.TestCase):
    def test_concrete_skill_must_have_name(self):
        with self.assertRaises(TypeError):
            class _NoName(Skill):
                # no `name` attr
                version = "1.0.0"
                def invoke(self, bundle, memory, ctx):
                    return SkillOutput(skill="")

    def test_can_invoke_when_required_flags_present(self):
        s = _RequiringSkill()
        caps_yes = Capabilities(flags=frozenset({TEXT_EVIDENCE}))
        caps_no = Capabilities(flags=frozenset({NUMERIC_FEATURES}))
        self.assertTrue(s.can_invoke(caps_yes))
        self.assertFalse(s.can_invoke(caps_no))

    def test_can_invoke_empty_required_flags_always_true(self):
        s = _SimpleSkill()
        self.assertTrue(s.can_invoke(Capabilities()))

    def test_invoke_returns_skill_output(self):
        s = _SimpleSkill()
        out = s.invoke(_make_bundle(), _make_memory("M-1"), AgentContext(bundle_id="w1"))
        self.assertEqual(out.skill, "simple")
        self.assertEqual(out.matched_issue_ids, ("PROJ-1",))

    def test_describe_carries_metadata(self):
        s = _ExpensiveSkill()
        d = s.describe()
        self.assertEqual(d["name"], "expensive")
        self.assertEqual(d["cost_class"], "expensive_llm")
        self.assertEqual(len(d["failure_modes"]), 1)
        self.assertIn("citation", d["failure_modes"][0])

    def test_repr_contains_name_and_version(self):
        s = _SimpleSkill()
        r = repr(s)
        self.assertIn("simple", r)
        self.assertIn("1.0.0", r)


# ---------------------------------------------------------------------------
# Skill.cache_key
# ---------------------------------------------------------------------------


class TestCacheKey(unittest.TestCase):
    def test_same_inputs_same_key(self):
        s = _SimpleSkill()
        b = _make_bundle()
        m = _make_memory("M-1", "M-2")
        self.assertEqual(s.cache_key(b, m), s.cache_key(b, m))

    def test_different_bundle_different_key(self):
        s = _SimpleSkill()
        m = _make_memory("M-1")
        k1 = s.cache_key(_make_bundle("w1"), m)
        k2 = s.cache_key(_make_bundle("w2"), m)
        self.assertNotEqual(k1, k2)

    def test_different_memory_different_key(self):
        s = _SimpleSkill()
        b = _make_bundle()
        k1 = s.cache_key(b, _make_memory("M-1"))
        k2 = s.cache_key(b, _make_memory("M-2"))
        self.assertNotEqual(k1, k2)

    def test_version_bump_invalidates_key(self):
        class _V1(Skill):
            name = "x"; version = "1.0.0"
            def invoke(self, b, m, c): return SkillOutput(skill="x")
        class _V2(Skill):
            name = "x"; version = "2.0.0"
            def invoke(self, b, m, c): return SkillOutput(skill="x")
        # Use different subclass names so the registry conflict check
        # doesn't fire — they ARE different skill objects.
        b, m = _make_bundle(), _make_memory("M-1")
        self.assertNotEqual(_V1().cache_key(b, m), _V2().cache_key(b, m))

    def test_extra_inputs_change_key(self):
        s = _SimpleSkill()
        b, m = _make_bundle(), _make_memory("M-1")
        k_base = s.cache_key(b, m)
        k_retry1 = s.cache_key(b, m, extra_inputs={"retry": 1})
        k_retry2 = s.cache_key(b, m, extra_inputs={"retry": 2})
        self.assertNotEqual(k_base, k_retry1)
        self.assertNotEqual(k_retry1, k_retry2)


# ---------------------------------------------------------------------------
# MemoryView
# ---------------------------------------------------------------------------


class TestMemoryView(unittest.TestCase):
    def test_signature_stable_across_construction(self):
        m1 = _make_memory("A", "B", "C")
        m2 = _make_memory("A", "B", "C")
        self.assertEqual(m1.signature(), m2.signature())

    def test_signature_sensitive_to_order(self):
        # The cascade's MemoryCorpus.visible_to is deterministic in order,
        # so order changes ARE meaningful — they indicate a different
        # visibility subset (different bundle).
        m_abc = _make_memory("A", "B", "C")
        m_acb = _make_memory("A", "C", "B")
        self.assertNotEqual(m_abc.signature(), m_acb.signature())

    def test_iteration_returns_issues(self):
        m = _make_memory("A", "B")
        ids = [iss.jira_shadow_issue_id for iss in m]
        self.assertEqual(ids, ["A", "B"])
        self.assertEqual(len(m), 2)

    def test_issues_returns_copy(self):
        m = _make_memory("A")
        lst = m.issues()
        lst.append("hacker")            # mutate the copy
        # Original view is unchanged
        self.assertEqual(len(m.issues()), 1)

    def test_signature_override(self):
        m = MemoryView([], signature_override="custom-sig")
        self.assertEqual(m.signature(), "custom-sig")


# ---------------------------------------------------------------------------
# SkillCache
# ---------------------------------------------------------------------------


class TestSkillCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = SkillCache(root=Path(self.tmp.name))
        self.skill = _SimpleSkill()
        self.key = "abc123"
        self.output = SkillOutput(
            skill="simple", skill_version="1.0.0",
            triage_score=0.42, matched_issue_ids=("PROJ-7",),
            cost=SkillCallCost(llm_tokens=10),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_miss_returns_none(self):
        self.assertIsNone(self.cache.get(self.skill, "nope"))
        self.assertEqual(self.cache.stats()["misses"], 1)
        self.assertEqual(self.cache.stats()["hits"], 0)

    def test_put_then_get_roundtrip(self):
        path = self.cache.put(self.skill, self.key, self.output)
        self.assertTrue(path.exists())

        loaded = self.cache.get(self.skill, self.key)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.triage_score, 0.42)
        self.assertEqual(loaded.matched_issue_ids, ("PROJ-7",))
        self.assertEqual(loaded.cost.llm_tokens, 10)

    def test_hit_increments_counter(self):
        self.cache.put(self.skill, self.key, self.output)
        self.cache.get(self.skill, self.key)
        self.cache.get(self.skill, self.key)
        s = self.cache.stats()
        self.assertEqual(s["hits"], 2)
        self.assertEqual(s["misses"], 0)
        self.assertAlmostEqual(s["hit_rate"], 1.0)

    def test_version_isolation(self):
        # Same skill name, different versions: two distinct directories.
        class _V1(Skill):
            name = "iso"; version = "1.0.0"
            def invoke(self, b, m, c): return SkillOutput(skill="iso")
        class _V2(Skill):
            name = "iso"; version = "2.0.0"
            def invoke(self, b, m, c): return SkillOutput(skill="iso")

        out = SkillOutput(skill="iso", triage_score=0.9)
        self.cache.put(_V1(), "k", out)
        # V2 doesn't see V1's entry
        self.assertIsNone(self.cache.get(_V2(), "k"))
        # V1 still sees its own
        self.assertIsNotNone(self.cache.get(_V1(), "k"))

    def test_invalidate_removes_skill_entries(self):
        self.cache.put(self.skill, "k1", self.output)
        self.cache.put(self.skill, "k2", self.output)
        n = self.cache.invalidate(self.skill)
        self.assertEqual(n, 2)
        self.assertIsNone(self.cache.get(self.skill, "k1"))

    def test_corrupt_entry_treated_as_miss(self):
        path = self.cache.put(self.skill, self.key, self.output)
        # Corrupt the file
        path.write_text("not valid json{", encoding="utf-8")
        result = self.cache.get(self.skill, self.key)
        self.assertIsNone(result)
        # Stats reflect this as a miss
        self.assertEqual(self.cache.stats()["misses"], 1)

    def test_disabled_cache_always_misses(self):
        cache = SkillCache(root=self.tmp.name, enabled=False)
        self.assertIsNone(cache.get(self.skill, "anything"))
        path = cache.put(self.skill, "k", self.output)
        self.assertEqual(path, Path())     # null path
        self.assertIsNone(cache.get(self.skill, "k"))

    def test_atomic_put_under_concurrent_writes(self):
        # Multiple threads put different keys; no corruption, all entries present.
        n = 30
        threads = []
        for i in range(n):
            t = threading.Thread(
                target=lambda i=i: self.cache.put(
                    self.skill, f"key{i}",
                    SkillOutput(skill="simple", triage_score=float(i)),
                ),
            )
            threads.append(t); t.start()
        for t in threads:
            t.join()
        for i in range(n):
            out = self.cache.get(self.skill, f"key{i}")
            self.assertIsNotNone(out, f"missing key{i}")
            self.assertEqual(out.triage_score, float(i))


class TestNullSkillCache(unittest.TestCase):
    def test_null_cache_always_misses(self):
        c = NullSkillCache()
        s = _SimpleSkill()
        self.assertIsNone(c.get(s, "k"))
        c.put(s, "k", SkillOutput(skill="simple"))
        self.assertIsNone(c.get(s, "k"))                 # still a miss
        self.assertGreater(c.stats()["misses"], 0)


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------


class TestSkillRegistry(unittest.TestCase):
    def test_register_and_get(self):
        r = SkillRegistry()
        s = _SimpleSkill()
        r.register(s)
        self.assertEqual(r.get("simple"), s)
        self.assertIn("simple", r)
        self.assertEqual(len(r), 1)

    def test_register_conflict_raises(self):
        r = SkillRegistry()
        r.register(_SimpleSkill())
        with self.assertRaises(ValueError) as ctx:
            r.register(_SimpleSkill())
        self.assertIn("conflict", str(ctx.exception).lower())

    def test_register_empty_name_raises(self):
        class _Empty(Skill):
            name = "placeholder"; version = "1.0"
            def invoke(self, b, m, c): return SkillOutput(skill="placeholder")
        skill = _Empty()
        skill.name = ""              # force empty post-construction
        r = SkillRegistry()
        with self.assertRaises(ValueError):
            r.register(skill)

    def test_get_missing_raises(self):
        r = SkillRegistry()
        with self.assertRaises(KeyError):
            r.get("nope")
        # Helpful error message lists known
        try:
            r.register(_SimpleSkill())
            r.get("nope")
        except KeyError as e:
            self.assertIn("simple", str(e))

    def test_try_get_returns_none(self):
        r = SkillRegistry()
        self.assertIsNone(r.try_get("nope"))

    def test_copy_shares_skills(self):
        r = SkillRegistry()
        s = _SimpleSkill()
        r.register(s)
        r2 = r.copy()
        self.assertIs(r2.get("simple"), s)            # same instance

    def test_copy_without(self):
        r = SkillRegistry()
        r.register(_SimpleSkill())
        r.register(_RequiringSkill())
        r2 = r.copy_without({"simple"})
        self.assertNotIn("simple", r2)
        self.assertIn("requires_text", r2)
        # Original unchanged
        self.assertIn("simple", r)

    def test_copy_only(self):
        r = SkillRegistry()
        r.register(_SimpleSkill())
        r.register(_RequiringSkill())
        r.register(_ExpensiveSkill())
        r2 = r.copy_only({"simple", "expensive"})
        self.assertEqual(set(r2.names()), {"simple", "expensive"})

    def test_copy_only_unknown_raises(self):
        r = SkillRegistry()
        r.register(_SimpleSkill())
        with self.assertRaises(KeyError):
            r.copy_only({"nope"})

    def test_clear_empties_registry(self):
        r = SkillRegistry()
        r.register(_SimpleSkill())
        r.clear()
        self.assertEqual(len(r), 0)
        self.assertNotIn("simple", r)


# ---------------------------------------------------------------------------
# AgentContext
# ---------------------------------------------------------------------------


class TestAgentContext(unittest.TestCase):
    def test_construction(self):
        ctx = AgentContext(bundle_id="w1")
        self.assertEqual(ctx.bundle_id, "w1")
        self.assertEqual(ctx.experiment, "")
        # default budget is permissive
        self.assertGreater(ctx.budget.max_llm_tokens, 0)

    def test_extra_slot_is_writable(self):
        ctx = AgentContext(bundle_id="w1")
        ctx.extra["custom"] = "value"
        self.assertEqual(ctx.extra["custom"], "value")


if __name__ == "__main__":
    unittest.main()
