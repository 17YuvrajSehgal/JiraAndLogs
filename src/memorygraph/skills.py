"""Semantic skills — the composable tools the Agent picks from.

Each Skill is a small, self-describing operation. The agent passes a
mutable AgentContext into every skill in the chosen chain; each skill
reads from and writes to the same context. That is the only contract
between skills — they don't call each other directly.

This file deliberately keeps each skill under ~40 lines so the agent's
chain is auditable: a reviewer should be able to read all the skills in
one pass and know exactly what knobs the pipeline exposes.

The Skill protocol mirrors the shape of MCP tools / LLM function-calls
(name + description + input_schema + run), so a future LLMPlanner can
hand the skill list to a model and get back a JSON chain.
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from core.data.schema import JiraMemoryIssue, TriageWindow

from .entities import (
    BRIDGEABLE_KINDS,
    EntityId,
    EntityKind,
    SEVERITY_ORDINAL,
    extract_obs_entities,
)
from .graph import MemoryGraph, MemoryGraphBuilder


# ---------------------------------------------------------------------------
# Context + result types
# ---------------------------------------------------------------------------


@dataclass
class AgentContext:
    """Shared mutable state passed through the skill chain.

    Skills read from earlier writes (`candidate_jira_ids` from a filter
    skill, `similarity_scores` from a similarity skill, etc.) and write
    new keys for downstream skills. The final agent decision is
    materialized by `triage_decide` from the accumulated state.
    """

    window: TriageWindow
    graph: MemoryGraph
    visible_jira: dict[str, JiraMemoryIssue]  # jira_shadow_issue_id -> issue
    # Outputs accumulated across the chain:
    candidate_jira_ids: list[str] = field(default_factory=list)
    similarity_scores: dict[str, float] = field(default_factory=dict)
    graph_scores: dict[str, float] = field(default_factory=dict)
    combined_scores: dict[str, float] = field(default_factory=dict)
    # Single per-window probability written by NumericBlendSkill. Stays
    # `None` when the hybrid path is disabled — TriageDecideSkill checks
    # for that and skips the numeric blend cleanly.
    numeric_score: float | None = None
    triage_score: float | None = None
    decision: str | None = None
    explanation: str = ""
    # Debug / audit:
    skill_trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SkillResult:
    """What a Skill returns — the agent records it in the trace."""

    name: str
    ok: bool
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Skill protocol
# ---------------------------------------------------------------------------


class Skill(ABC):
    """Base class for every semantic skill.

    Subclasses set `name` (string) and `description` (one-line). The
    optional `input_schema` is a JSON-schema-ish dict describing what
    keys in AgentContext the skill consumes; the LLMPlanner uses it to
    decide ordering.
    """

    name: str = "abstract"
    description: str = ""
    input_schema: dict[str, Any] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    @abstractmethod
    def run(self, ctx: AgentContext) -> SkillResult: ...

    def fit(self, train_windows: list[TriageWindow], feature_columns: list[str]) -> None:
        """Optional hook for trainable skills.

        Most skills are stateless and override this with a no-op (the
        default). Skills that hold a model (e.g. NumericBlendSkill) use
        this to learn from the train split before any window is scored.
        Called once per pipeline run; arguments are the training windows
        and the production-safe feature column catalog from
        `triage-feature-columns.json`.
        """
        return None


# ---------------------------------------------------------------------------
# Entity-extraction skill (idempotent — done in the builder, surfaced here)
# ---------------------------------------------------------------------------


class EntityExtractSkill(Skill):
    name = "entity_extract"
    description = (
        "Re-extract observability entities from the current window and "
        "annotate the context with their kinds + counts. Idempotent — the "
        "graph builder already did this; this skill exists so the planner "
        "can see what the agent is reasoning over."
    )
    input_schema = {"reads": ["window"], "writes": ["entity_summary"]}

    def run(self, ctx: AgentContext) -> SkillResult:
        entities, summary = extract_obs_entities(ctx.window)
        kind_counts = Counter(e.id.kind for e in entities)
        ctx.skill_trace.append(
            {"skill": self.name, "kinds": dict(kind_counts), "summary": summary}
        )
        return SkillResult(
            name=self.name,
            ok=True,
            summary=f"extracted {len(entities)} obs entities across {len(kind_counts)} kinds",
            metrics={"n_entities": len(entities), "kinds": dict(kind_counts)},
        )


# ---------------------------------------------------------------------------
# Direct-mapping pre-filter skills (these implement the "exclude logs not
# related to that component" idea from the project sketch)
# ---------------------------------------------------------------------------


class ComponentFilterSkill(Skill):
    name = "component_filter"
    description = (
        "Pre-filter Jira candidates to those sharing at least one component "
        "or service entity with the window. This is the direct-mapping "
        "filter — it discards candidates the model has no structural reason "
        "to consider before any similarity computation runs."
    )
    input_schema = {"reads": ["window", "graph", "visible_jira"], "writes": ["candidate_jira_ids"]}

    def run(self, ctx: AgentContext) -> SkillResult:
        share_any = ctx.graph.jira_candidates_for(ctx.window.window_id)
        # Intersect with visible_jira to enforce time-ordering — the
        # graph itself does not know about timestamps; the corpus does.
        visible = set(ctx.visible_jira.keys())
        kept = [j for j in share_any if j in visible]
        ctx.candidate_jira_ids = kept
        return SkillResult(
            name=self.name,
            ok=True,
            summary=f"kept {len(kept)}/{len(share_any)} candidates (visible={len(visible)})",
            metrics={
                "n_visible": len(visible),
                "n_share_entity": len(share_any),
                "n_after_filter": len(kept),
            },
        )


class ServiceFilterSkill(Skill):
    name = "service_filter"
    description = (
        "Narrower filter: only Jira candidates whose affected_service is the "
        "same as the window service. Use after component_filter when the "
        "candidate set is still large."
    )
    input_schema = {"reads": ["candidate_jira_ids"], "writes": ["candidate_jira_ids"]}

    def run(self, ctx: AgentContext) -> SkillResult:
        svc = (ctx.window.service_name or "").lower()
        if not svc or not ctx.candidate_jira_ids:
            return SkillResult(self.name, True, "noop", {"n": len(ctx.candidate_jira_ids)})
        before = len(ctx.candidate_jira_ids)
        kept = [
            cid for cid in ctx.candidate_jira_ids
            if (ctx.visible_jira[cid].affected_service or "").lower() == svc
        ]
        # Only apply the narrower filter if it leaves at least 3 candidates
        # — otherwise we're being too aggressive on small corpora.
        if len(kept) >= 3:
            ctx.candidate_jira_ids = kept
            return SkillResult(
                self.name, True, f"narrowed {before}->{len(kept)} by service={svc}",
                {"n_after": len(kept)},
            )
        return SkillResult(
            self.name, True, f"skipped (would leave only {len(kept)} candidates)",
            {"n_after": before, "would_have_been": len(kept)},
        )


# ---------------------------------------------------------------------------
# Severity / fault-class alignment skills
# ---------------------------------------------------------------------------


class SeverityAlignSkill(Skill):
    name = "severity_align"
    description = (
        "Infer a severity for the current window from numeric features (no "
        "label leakage) and add a graph_score bonus to candidates whose "
        "Jira severity ordinal is within 1 step."
    )
    input_schema = {"reads": ["window", "candidate_jira_ids"], "writes": ["graph_scores"]}

    def _infer_window_severity(self, window: TriageWindow) -> str | None:
        raw = window.raw or {}
        err_rate = float(raw.get("triage_feature_trace_error_rate", 0) or 0)
        p95 = float(raw.get("triage_feature_trace_latency_p95_ms", 0) or 0)
        restarts = float(raw.get("triage_feature_k8s_restart_count", 0) or 0)
        unavail = float(raw.get("triage_feature_k8s_pod_unavailable_count", 0) or 0)
        # Coarse rules — calibrated to the lab's order of magnitudes, not
        # to the lab's labels.
        if err_rate >= 0.5 or unavail >= 1:
            return "critical"
        if err_rate >= 0.1 or p95 >= 2000 or restarts >= 1:
            return "major"
        if err_rate >= 0.01 or p95 >= 500:
            return "minor"
        return None

    def run(self, ctx: AgentContext) -> SkillResult:
        w_sev = self._infer_window_severity(ctx.window)
        if not w_sev:
            return SkillResult(self.name, True, "no severity inferred", {})
        n_aligned = 0
        for cid in ctx.candidate_jira_ids:
            jira_sev = ctx.visible_jira[cid].severity
            score = ctx.graph.severity_compatibility(w_sev, jira_sev)
            if score > 0:
                ctx.graph_scores[cid] = ctx.graph_scores.get(cid, 0.0) + score
                n_aligned += 1
        return SkillResult(
            self.name, True,
            f"window_severity={w_sev}; bonused {n_aligned}/{len(ctx.candidate_jira_ids)} candidates",
            {"window_severity": w_sev, "n_aligned": n_aligned},
        )


class ErrorClassAlignSkill(Skill):
    name = "error_class_align"
    description = (
        "Bonus candidates whose graph node shares an error_class entity "
        "(timeout, redis_failure, dns_failure, oom, …) with the window."
    )
    input_schema = {"reads": ["window", "graph", "candidate_jira_ids"], "writes": ["graph_scores"]}

    def run(self, ctx: AgentContext) -> SkillResult:
        win_kinds = {
            e.id.key()
            for e in ctx.graph.entities_of(ctx.window.window_id)
            if e.id.kind == EntityKind.ERROR_CLASS
        }
        if not win_kinds:
            return SkillResult(self.name, True, "no error_class entities on window", {})
        n_hits = 0
        for cid in ctx.candidate_jira_ids:
            jira_kinds = {
                e.id.key()
                for e in ctx.graph.entities_of(cid)
                if e.id.kind == EntityKind.ERROR_CLASS
            }
            shared = win_kinds & jira_kinds
            if not shared:
                continue
            # Weight by bridge rarity — rare error_classes are more informative
            bonus = 0.0
            for key in shared:
                kind, value = key.split(":", 1)
                rarity = ctx.graph.bridge_weight(EntityId(kind, value))
                bonus += 0.5 + 0.5 * rarity
            ctx.graph_scores[cid] = ctx.graph_scores.get(cid, 0.0) + bonus
            n_hits += 1
        return SkillResult(
            self.name, True,
            f"matched {n_hits}/{len(ctx.candidate_jira_ids)} candidates on error_class",
            {"n_hits": n_hits, "window_error_classes": sorted(win_kinds)},
        )


# ---------------------------------------------------------------------------
# Similarity skills
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _strip_window_header(text: str) -> str:
    return "\n".join(l for l in (text or "").splitlines() if not l.startswith("WINDOW "))


class LexicalSimilaritySkill(Skill):
    name = "lexical_similarity"
    description = (
        "BM25 over the candidate Jira memory_text using the window "
        "evidence text as the query. Writes a normalized [0,1] score per "
        "candidate into similarity_scores. Runs over the filtered "
        "candidate set, NOT the full corpus."
    )
    input_schema = {"reads": ["window", "candidate_jira_ids", "visible_jira"], "writes": ["similarity_scores"]}

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def _bm25_scores(self, query: list[str], docs: list[list[str]]) -> list[float]:
        n = len(docs)
        if n == 0:
            return []
        doc_lens = [len(d) for d in docs]
        avg = sum(doc_lens) / n
        tfs = [Counter(d) for d in docs]
        df: Counter[str] = Counter()
        for d in docs:
            for t in set(d):
                df[t] += 1
        idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1) for t, c in df.items()}
        scores = [0.0] * n
        for q in query:
            i = idf.get(q, 0.0)
            if i == 0:
                continue
            for di, tf in enumerate(tfs):
                f = tf.get(q, 0)
                if f == 0:
                    continue
                norm = self.k1 * (1 - self.b + self.b * doc_lens[di] / avg)
                scores[di] += i * (f * (self.k1 + 1)) / (f + norm)
        return scores

    def run(self, ctx: AgentContext) -> SkillResult:
        if not ctx.candidate_jira_ids:
            return SkillResult(self.name, True, "no candidates", {})
        query = _tokenize(_strip_window_header(ctx.window.evidence_text or ""))
        docs = [
            _tokenize(
                f"{ctx.visible_jira[cid].memory_text} {ctx.visible_jira[cid].resolution_notes}"
            )
            for cid in ctx.candidate_jira_ids
        ]
        raw_scores = self._bm25_scores(query, docs)
        # Normalize to [0, 1] by max-score scaling — that keeps the
        # combined skill's downstream blend interpretable.
        peak = max(raw_scores) if raw_scores else 0.0
        for cid, s in zip(ctx.candidate_jira_ids, raw_scores):
            ctx.similarity_scores[cid] = (s / peak) if peak > 0 else 0.0
        return SkillResult(
            self.name, True,
            f"scored {len(raw_scores)} candidates (peak={peak:.2f})",
            {"peak_score": peak, "n_scored": len(raw_scores)},
        )


class LogSignatureSimilaritySkill(Skill):
    """BM25 over the candidate Jira memory_text using the window's
    characteristic log lines as the query, replacing the trace-
    aggregate evidence_text query.

    Move A from ML-NEW-IDEAS.MD. E5 + E6 showed that on the clean
    humanized corpus, both BM25 and Nomic dense embeddings cap at
    Recall@5 ≈ 0.07 when the source-side query is `evidence_text`.
    The hypothesis: an engineer-vocabulary query against natural-
    language Jira memory text should score meaningfully higher
    because the two sides finally share the same words.

    Output policy: OVERWRITE similarity_scores rather than blend.
    The whole point is "swap the query vocabulary"; running both
    queries and blending would dilute the test.
    """

    name = "log_signature_similarity"
    description = (
        "BM25 over candidate Jira memory_text using the window's "
        "characteristic log lines (top-K rare error templates) as the "
        "query, replacing the trace-aggregate evidence_text query."
    )
    input_schema = {
        "reads": ["window", "candidate_jira_ids", "visible_jira"],
        "writes": ["similarity_scores"],
    }

    def __init__(
        self,
        *,
        runs_root: Any = None,
        top_k_lines: int = 10,
        k1: float = 1.5,
        b: float = 0.75,
        progress_every: int = 100,
    ) -> None:
        # runs_root is set by the pipeline (or left None to silently
        # disable the skill — same fail-soft pattern as EmbeddingSimilarity).
        self.runs_root = runs_root
        self.top_k_lines = top_k_lines
        self.k1 = k1
        self.b = b
        self.progress_every = progress_every
        # Per-window cache so re-querying the same window (val + test)
        # doesn't re-parse the raw Loki dump.
        self._sig_cache: dict[str, list[str]] = {}
        self._n_run_calls = 0
        self._n_signatures_extracted = 0
        self._n_empty_signatures = 0
        self._start_ts: float | None = None

    def _signature_for(self, window: TriageWindow) -> list[str]:
        cache_key = window.window_id
        if cache_key in self._sig_cache:
            return self._sig_cache[cache_key]
        if self.runs_root is None:
            self._sig_cache[cache_key] = []
            return []
        from pathlib import Path as _Path
        runs_root = _Path(self.runs_root)
        loki_path = (
            runs_root / window.dataset_run_id / "raw" / "loki"
            / f"{window.window_id}.json"
        )
        from .log_signatures import extract_log_signature
        sig = extract_log_signature(loki_path, top_k=self.top_k_lines)
        self._sig_cache[cache_key] = sig
        if sig:
            self._n_signatures_extracted += 1
        else:
            self._n_empty_signatures += 1
        return sig

    def _bm25_scores(self, query: list[str], docs: list[list[str]]) -> list[float]:
        n = len(docs)
        if n == 0:
            return []
        doc_lens = [len(d) for d in docs]
        avg = sum(doc_lens) / n
        tfs = [Counter(d) for d in docs]
        df: Counter[str] = Counter()
        for d in docs:
            for t in set(d):
                df[t] += 1
        idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1) for t, c in df.items()}
        scores = [0.0] * n
        for q in query:
            i = idf.get(q, 0.0)
            if i == 0:
                continue
            for di, tf in enumerate(tfs):
                f = tf.get(q, 0)
                if f == 0:
                    continue
                norm = self.k1 * (1 - self.b + self.b * doc_lens[di] / avg)
                scores[di] += i * (f * (self.k1 + 1)) / (f + norm)
        return scores

    def run(self, ctx: AgentContext) -> SkillResult:
        import sys, time
        if self._start_ts is None:
            self._start_ts = time.time()
        self._n_run_calls += 1

        if self.runs_root is None:
            return SkillResult(
                self.name, True, "disabled (no runs_root configured)",
                {"enabled": False},
            )
        if not ctx.candidate_jira_ids:
            return SkillResult(self.name, True, "no candidates", {})

        sig_lines = self._signature_for(ctx.window)
        if not sig_lines:
            # No error-level lines in this window — leave existing
            # similarity_scores untouched so the chain still has signal
            # from lexical_similarity / embedding_similarity.
            return SkillResult(
                self.name, True, "no error-level lines in window",
                {"n_sig_lines": 0},
            )

        query = _tokenize(" ".join(sig_lines))
        docs = [
            _tokenize(
                f"{ctx.visible_jira[cid].memory_text} "
                f"{ctx.visible_jira[cid].resolution_notes}"
            )
            for cid in ctx.candidate_jira_ids
        ]
        raw_scores = self._bm25_scores(query, docs)
        peak = max(raw_scores) if raw_scores else 0.0
        # OVERWRITE similarity_scores with the log-signature BM25 scores.
        # Replacing the query vocabulary is the whole point of this
        # experiment.
        for cid, s in zip(ctx.candidate_jira_ids, raw_scores):
            ctx.similarity_scores[cid] = (s / peak) if peak > 0 else 0.0

        if self.progress_every and (self._n_run_calls % self.progress_every == 0):
            elapsed = time.time() - self._start_ts
            avg = elapsed / max(self._n_run_calls, 1)
            print(
                f"[{self.name}] scored {self._n_run_calls} windows "
                f"(sig_extracted={self._n_signatures_extracted} "
                f"empty={self._n_empty_signatures}) "
                f"elapsed={elapsed:.0f}s avg={avg:.3f}s/window",
                file=sys.stderr, flush=True,
            )
        return SkillResult(
            self.name, True,
            f"replaced similarity_scores with log-signature query "
            f"({len(sig_lines)} lines, peak={peak:.2f})",
            {"n_sig_lines": len(sig_lines), "peak_score": peak},
        )


class EmbeddingSimilaritySkill(Skill):
    """Dense semantic similarity over the filtered candidate pool.

    Uses Nomic embeddings via LM Studio's OpenAI-compatible /v1/embeddings
    endpoint — the same backend the existing `nomic_retrieval` pipeline
    uses. The skill caches all visible Jira memory embeddings once at
    `.fit()` time so per-window cost is one query embed + a small cosine
    loop over the post-filter candidate set (typically ≤ 15 items on
    v5-quick).

    Fail-soft: when LM Studio is unreachable at fit time, the skill stays
    a no-op and the chain still runs (similarity_scores are written only
    by LexicalSimilaritySkill in that case). When the embedding probe
    fails mid-window, the skill returns without touching state.

    Why fold dense similarity in alongside BM25 instead of replacing it:
    BM25 wins on exact-token matches (service names, error class
    strings); dense embedding wins on paraphrase ("deadline exceeded" ≈
    "request timed out"). We blend the two normalized scores 50/50 into
    `similarity_scores` so downstream triage_decide sees one number.
    """

    name = "embedding_similarity"
    description = (
        "Nomic dense embedding cosine over the filtered candidate pool. "
        "Blends 50/50 into similarity_scores alongside the BM25 score. "
        "Silently noops when LM Studio is unreachable."
    )
    input_schema = {
        "reads": ["window", "candidate_jira_ids", "visible_jira"],
        "writes": ["similarity_scores"],
    }

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:1234",
        model: str = "text-embedding-nomic-embed-text-v1.5",
        blend_weight: float = 0.5,
        progress_every: int = 100,
        cache_root: Any = None,
    ) -> None:
        self.base_url = base_url
        self.model = model
        # blend_weight = how much of the final similarity_score comes
        # from the embedding signal vs the BM25 signal already in
        # similarity_scores. 0.5 is the cheap baseline; future work
        # could tune per-family.
        self.blend_weight = blend_weight
        # Print a progress line every N run() calls so a piped run
        # shows it's making forward progress instead of looking hung.
        # Cost: one fputs per N windows; negligible.
        self.progress_every = progress_every
        self._cache: dict[str, list[float]] = {}
        self._enabled: bool = False
        # O6 persistent embedding cache (util.embedding_cache). When
        # cache_root is set, every memory-doc and query embedding is
        # also persisted to disk (content-addressed by sha256(text)),
        # so re-running the pipeline against the same corpus + same
        # windows hits the cache in ~1ms each instead of ~50-200ms via
        # the network. On v5-large this cuts a re-run from ~75 min to
        # ~30 seconds. Default None = no persistence (legacy behavior).
        self.cache_root = cache_root
        self._cached_embedder: Any = None
        self._n_cache_hits = 0
        self._n_cache_misses = 0
        # Lightweight counters surfaced in the progress logs so a
        # reviewer can tell whether the skill is mostly embedding new
        # corpus docs (cold cache) or just doing query embeds (warm).
        self._n_run_calls = 0
        self._n_query_embeds = 0
        self._n_corpus_embeds = 0
        self._start_ts: float | None = None

    def fit(self, train_windows: list[TriageWindow], feature_columns: list[str]) -> None:
        """Pre-embed every Jira memory entry we'll later see.

        We don't actually have the memory corpus at fit time through this
        signature, so we leave caching to the first run() call. We DO
        probe LM Studio here so we can disable the skill cleanly when
        the backend is unreachable, without paying the probe cost on
        every window.
        """
        del train_windows, feature_columns  # not used directly
        try:
            from comparison.retrievers import embed_via_lm_studio
        except ImportError:
            self._enabled = False
            return
        try:
            probe = embed_via_lm_studio(
                self.base_url, self.model, ["probe"], timeout=5.0
            )
        except Exception:
            self._enabled = False
            return
        self._enabled = bool(probe and probe[0])

        # Wire the persistent embedding cache if cache_root was set.
        # Lazy because we don't need it when the skill is disabled.
        if self._enabled and self.cache_root is not None and self._cached_embedder is None:
            try:
                from pathlib import Path as _Path
                _SRC_ROOT = _Path(__file__).resolve().parent.parent
                import sys as _sys
                if str(_SRC_ROOT) not in _sys.path:
                    _sys.path.insert(0, str(_SRC_ROOT))
                from util.embedding_cache import make_nomic_cached_embedder
                self._cached_embedder = make_nomic_cached_embedder(
                    _Path(self.cache_root),
                    base_url=self.base_url,
                    model_id=self.model,
                )
                _sys.stderr.write(
                    f"[{self.name}] persistent cache wired at "
                    f"{self.cache_root} (model={self.model})\n"
                )
                _sys.stderr.flush()
            except Exception as exc:
                import sys as _sys
                _sys.stderr.write(
                    f"[{self.name}] could not wire embedding cache "
                    f"({exc!r}); falling back to direct calls\n"
                )
                _sys.stderr.flush()
                self._cached_embedder = None

    def _embed_one(self, text: str) -> list[float]:
        """Embed one text. Cache-aware: tries persistent disk cache
        first when wired; falls back to direct LM Studio call.

        Returns [] on failure rather than raising — callers handle the
        empty case by skipping the candidate / query.
        """
        if self._cached_embedder is not None:
            try:
                arr = self._cached_embedder.embed(text)
                if hasattr(arr, "tolist"):
                    return arr.tolist()
                return list(arr)
            except Exception:
                # Fall through to direct call below.
                pass
        try:
            from comparison.retrievers import embed_via_lm_studio
            vecs = embed_via_lm_studio(self.base_url, self.model, [text])
            return list(vecs[0]) if vecs and vecs[0] else []
        except Exception:
            return []

    def _ensure_cached(self, jira_ids: list[str], visible: dict[str, JiraMemoryIssue]) -> None:
        """Embed any Jira memory entries we haven't seen yet.

        When persistent cache is wired, this is mostly disk reads on
        re-runs (~1ms/doc). Cold-cache path falls back to the network
        but persists each result for next time.
        """
        if not self._enabled:
            return
        missing = [jid for jid in jira_ids if jid not in self._cache]
        if not missing:
            return
        import sys, time
        t0 = time.time()
        use_cache = self._cached_embedder is not None
        n_disk_hits = 0
        if use_cache:
            # One-at-a-time via the persistent cache — hits read from
            # disk, misses fall through to the LM Studio backend and
            # persist for next time.
            pre_hits = int(self._cached_embedder.stats.hits)
            pre_misses = int(self._cached_embedder.stats.misses)
            for jid in missing:
                text = (
                    f"{visible[jid].memory_text} "
                    f"{visible[jid].resolution_notes}"
                )
                vec = self._embed_one(text)
                if vec:
                    self._cache[jid] = vec
                    self._n_corpus_embeds += 1
            post_hits = int(self._cached_embedder.stats.hits)
            n_disk_hits = post_hits - pre_hits
            self._n_cache_hits += n_disk_hits
            self._n_cache_misses += (
                int(self._cached_embedder.stats.misses) - pre_misses
            )
            print(
                f"[{self.name}] embedded {len(missing)} memory docs "
                f"({n_disk_hits} disk-cache hits, "
                f"{len(missing) - n_disk_hits} network calls) "
                f"in {time.time() - t0:.1f}s "
                f"(in-memory cache now {len(self._cache)})",
                file=sys.stderr,
                flush=True,
            )
        else:
            # Legacy bulk-network path (no persistent cache wired).
            print(
                f"[{self.name}] bulk-embedding {len(missing)} memory docs ...",
                file=sys.stderr,
                flush=True,
            )
            try:
                from comparison.retrievers import embed_via_lm_studio
                texts = [
                    f"{visible[jid].memory_text} {visible[jid].resolution_notes}"
                    for jid in missing
                ]
                vecs = embed_via_lm_studio(self.base_url, self.model, texts)
            except Exception as exc:
                print(
                    f"[{self.name}] memory-embed failed: {type(exc).__name__}: {exc}; "
                    f"disabling skill for the rest of the run",
                    file=sys.stderr,
                    flush=True,
                )
                self._enabled = False
                return
            for jid, vec in zip(missing, vecs):
                if vec:
                    self._cache[jid] = vec
                    self._n_corpus_embeds += 1
            print(
                f"[{self.name}] bulk-embedded {len(missing)} docs in "
                f"{time.time() - t0:.1f}s (cache size now {len(self._cache)})",
                file=sys.stderr,
                flush=True,
            )

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def run(self, ctx: AgentContext) -> SkillResult:
        import sys, time
        if self._start_ts is None:
            self._start_ts = time.time()
        self._n_run_calls += 1
        if not self._enabled or not ctx.candidate_jira_ids:
            return SkillResult(
                self.name, True,
                "skipped" if not self._enabled else "no candidates",
                {"enabled": self._enabled},
            )
        self._ensure_cached(ctx.candidate_jira_ids, ctx.visible_jira)
        query_text = _strip_window_header(ctx.window.evidence_text or "")
        # Query embed: when persistent cache is wired, repeated runs
        # of the same query hit the disk (~1ms) instead of the network.
        q_vec = self._embed_one(query_text)
        self._n_query_embeds += 1
        if not q_vec:
            return SkillResult(self.name, False, "empty query embedding", {})
        n_blended = 0
        for cid in ctx.candidate_jira_ids:
            doc_vec = self._cache.get(cid)
            if not doc_vec:
                continue
            sim = max(0.0, self._cosine(q_vec, doc_vec))  # cosine -> [-1,1], clamp
            existing = ctx.similarity_scores.get(cid, 0.0)
            ctx.similarity_scores[cid] = (
                (1.0 - self.blend_weight) * existing + self.blend_weight * sim
            )
            n_blended += 1

        # Print a one-liner every progress_every windows so a piped run
        # shows it's actually moving. Includes elapsed + avg/window so a
        # reviewer can spot Nomic slowdowns.
        if self.progress_every and (self._n_run_calls % self.progress_every == 0):
            elapsed = time.time() - self._start_ts
            avg = elapsed / max(self._n_run_calls, 1)
            print(
                f"[{self.name}] scored {self._n_run_calls} windows "
                f"(query_embeds={self._n_query_embeds} "
                f"corpus_embeds={self._n_corpus_embeds} "
                f"cache={len(self._cache)}) "
                f"elapsed={elapsed:.0f}s avg={avg:.2f}s/window",
                file=sys.stderr,
                flush=True,
            )
        return SkillResult(
            self.name, True,
            f"blended dense similarity into {n_blended} candidates",
            {"n_blended": n_blended, "n_cached": len(self._cache)},
        )


# ---------------------------------------------------------------------------
# Cross-encoder reranker — sentence-transformers MS-MARCO MiniLM-L-6-v2
# ---------------------------------------------------------------------------


class CrossEncoderRerankSkill(Skill):
    """Rerank the top-K candidates with a pretrained cross-encoder.

    Runs AFTER lexical_similarity / log_signature_similarity /
    embedding_similarity have populated `similarity_scores`. Takes the
    top-K candidates by current score, jointly scores (query, doc)
    pairs with `cross-encoder/ms-marco-MiniLM-L-6-v2`, and REPLACES
    the similarity_scores for those K candidates with normalized
    cross-encoder scores (others stay at 0).

    Why cross-encoder and not another bi-encoder layer:
        Bi-encoders (BM25, Nomic dense) encode query and doc
        independently and score by cosine — cheap to index but lossy.
        Cross-encoders feed [CLS] query [SEP] doc through the model
        jointly so attention can directly compare every token pair.
        On MS-MARCO passage ranking, the cross-encoder is +5-10 pts
        nDCG over the bi-encoder. The cost is O(K) forward passes
        per query, which is bounded by our component-filter
        producing ~15 candidates per window.

    Fail-soft: if sentence_transformers isn't importable or the model
    fails to load on .fit(), the skill self-disables (logs once, then
    is a no-op for every window). The pipeline still runs.

    Operating point: top_k_to_rerank=20 (the reranker only sees the
    top-20 by upstream similarity). On v5-large that's ~15 effective
    per window after the component filter. Total cost ~10-30 ms per
    window on CPU, ~3-5 ms on GPU.
    """

    name = "cross_encoder_rerank"
    description = (
        "Rerank top-K candidates with a pretrained cross-encoder "
        "(MS-MARCO MiniLM-L-6-v2). Replaces similarity_scores for the "
        "reranked candidates with normalized cross-encoder scores."
    )
    input_schema = {
        "reads": ["window", "candidate_jira_ids", "visible_jira", "similarity_scores"],
        "writes": ["similarity_scores"],
    }

    def __init__(
        self,
        *,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        top_k_to_rerank: int = 20,
        max_chars_per_doc: int = 800,
        progress_every: int = 200,
        # Blend weight: final = blend_weight * crossenc + (1-blend_weight) * bi_encoder.
        # 1.0 = REPLACE bi-encoder (lost the R@5 game in initial test);
        # 0.6 = strong cross-encoder authority while preserving bi-
        # encoder's broader recall — recommended.
        blend_weight: float = 0.6,
    ) -> None:
        self.model_name = model_name
        self.top_k_to_rerank = top_k_to_rerank
        self.max_chars_per_doc = max_chars_per_doc
        self.progress_every = progress_every
        self.blend_weight = max(0.0, min(1.0, blend_weight))
        # Loaded on first call. None = "tried and failed" after first
        # attempt, so we don't re-try the import every window.
        self._model: Any = None
        self._tried_load = False
        self._enabled = True
        self._scored_windows = 0
        self._reranked_total = 0

    def _ensure_model(self) -> bool:
        """Lazy-load. Returns False if loading fails (skill becomes no-op)."""
        if self._tried_load:
            return self._enabled
        self._tried_load = True
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except ImportError as e:
            import sys
            print(
                f"[cross_encoder_rerank] sentence_transformers not "
                f"importable: {e}; skill disabled.",
                file=sys.stderr, flush=True,
            )
            self._enabled = False
            return False
        try:
            import sys
            from pathlib import Path as _Path
            # Local fine-tuned model: accept either a directory or HF hub ID.
            # If the path exists on disk, sentence_transformers loads it
            # directly; otherwise it falls through to the hub.
            mname = self.model_name
            is_local = _Path(mname).exists()
            print(
                f"[cross_encoder_rerank] loading "
                f"{'local: ' if is_local else 'hub: '}{mname} ... "
                "(first hub run downloads ~80MB)",
                file=sys.stderr, flush=True,
            )
            self._model = CrossEncoder(mname, max_length=512)
            print(
                f"[cross_encoder_rerank] model ready; device={self._model._target_device}",
                file=sys.stderr, flush=True,
            )
        except Exception as e:  # network errors, OOM, etc.
            import sys
            print(
                f"[cross_encoder_rerank] model load failed: {e!r}; "
                "skill disabled.",
                file=sys.stderr, flush=True,
            )
            self._enabled = False
            self._model = None
            return False
        return True

    def _build_query(self, ctx: AgentContext) -> str:
        """Build the query text. Prefer the log signature when present
        (Move A), otherwise fall back to evidence_text. The cross-
        encoder works best on shorter, focused queries — large prose
        wastes attention on boilerplate."""
        # Log signature is populated by LogSignatureSimilaritySkill into
        # ctx.skill_trace; we don't have direct access here. Use the
        # window's evidence_text as the default and let the
        # log-signature variant of the pipeline produce its own
        # similarity_scores upstream.
        text = _strip_window_header(ctx.window.evidence_text or "")
        # Cap at a sensible length — MiniLM's max_length=512 tokens
        # ≈ 2000 chars; longer queries get truncated by the tokenizer
        # anyway, so explicit char cap keeps logs noise-free.
        return text[: 2000]

    def run(self, ctx: AgentContext) -> SkillResult:
        if not ctx.candidate_jira_ids:
            return SkillResult(self.name, True, "no candidates", {})
        if not self._ensure_model():
            return SkillResult(
                self.name, True, "skill disabled (model unavailable)",
                {"disabled": True},
            )
        # Pick top-K by current similarity_scores.
        ranked = sorted(
            ctx.candidate_jira_ids,
            key=lambda cid: ctx.similarity_scores.get(cid, 0.0),
            reverse=True,
        )
        topk = ranked[: self.top_k_to_rerank]
        if not topk:
            return SkillResult(
                self.name, True, "empty top-K",
                {"reranked": 0},
            )

        query = self._build_query(ctx)
        if not query.strip():
            return SkillResult(
                self.name, True, "empty query (no evidence_text)",
                {"reranked": 0},
            )

        # Build (query, doc) pairs. memory_text already includes V2's
        # description_code at the front per humanized_loader changes.
        pairs: list[list[str]] = []
        for cid in topk:
            jira = ctx.visible_jira[cid]
            doc = (jira.memory_text or "")[: self.max_chars_per_doc]
            pairs.append([query, doc])

        # Score. show_progress_bar=False to keep logs clean — we emit
        # our own progress every N windows.
        try:
            scores = self._model.predict(pairs, show_progress_bar=False)
        except Exception as e:
            import sys
            print(
                f"[cross_encoder_rerank] predict failed: {e!r}; "
                "leaving similarity_scores unchanged",
                file=sys.stderr, flush=True,
            )
            return SkillResult(
                self.name, False, f"predict error: {e!r}",
                {"reranked": 0},
            )

        # Convert to float list (predict returns numpy by default).
        try:
            scores = [float(s) for s in scores]
        except (TypeError, ValueError):
            scores = list(scores)

        # Normalize within the top-K to [0, 1] so downstream blend
        # behavior matches lexical_similarity / embedding_similarity.
        peak = max(scores) if scores else 0.0
        floor = min(scores) if scores else 0.0
        span = peak - floor if (peak > floor) else 1.0
        # BLEND policy: keep bi-encoder scores for ALL candidates;
        # for the reranked top-K, blend `blend_weight * cross_encoder
        # + (1 - blend_weight) * bi_encoder`. The "replace top-20,
        # zero everything else" policy from the initial implementation
        # lifted R@1 but hurt R@5 because true matches at bi-encoder
        # rank 6-20 sometimes got moved out of top-5 by the cross-
        # encoder. The blend preserves bi-encoder's broader recall
        # while letting cross-encoder dominate top-1 selection.
        w = self.blend_weight
        for cid, s in zip(topk, scores):
            ce_norm = (s - floor) / span if span > 0 else 1.0
            bi_norm = ctx.similarity_scores.get(cid, 0.0)
            ctx.similarity_scores[cid] = w * ce_norm + (1.0 - w) * bi_norm
        # Candidates outside the rerank top-K keep their bi-encoder
        # scores unchanged — they remain in the candidate pool for the
        # downstream graph_score + triage_decide blends.

        self._scored_windows += 1
        self._reranked_total += len(topk)
        if self._scored_windows % self.progress_every == 0:
            import sys
            print(
                f"[cross_encoder_rerank] reranked {self._scored_windows} "
                f"windows ({self._reranked_total} total pair scorings)",
                file=sys.stderr, flush=True,
            )

        return SkillResult(
            self.name, True,
            f"reranked top-{len(topk)} (raw_peak={peak:.3f} raw_floor={floor:.3f})",
            {"reranked": len(topk), "peak": peak, "floor": floor},
        )


# ---------------------------------------------------------------------------
# Graph-aware scoring + traversal skills
# ---------------------------------------------------------------------------


class GraphScoreSkill(Skill):
    """Per-candidate score from sum-of-bridge-weights × per-kind weight.

    Per-kind weights default to a hand-coded prior (SERVICE/COMPONENT
    most important, SEVERITY least). When the pipeline calls
    `fit_on_pairs(train_windows, memory_by_id, graph)` after the corpus
    loads, the priors are replaced with **precision-per-kind learned
    from the training split**: for each entity kind K, look at all
    (train_window, candidate_jira) pairs where the two share an entity
    of kind K, and compute the fraction where the candidate is in the
    window's gold `matched_memory_issue_ids`. Kinds that bridge true
    positives more often than false positives get higher weights.

    This is the "automatically learn edge weights from the training
    split" hook the project sketch calls out — instead of asserting that
    `component_match > severity_align`, we measure it on training data
    and let the data decide.
    """

    name = "graph_score"
    description = (
        "For each candidate, sum the bridge weights of entities that bridge "
        "the window to that candidate. Per-kind weights default to a hand "
        "prior but are overridden with training-set precision when "
        "fit_on_pairs is called. Writes graph_scores."
    )
    input_schema = {"reads": ["window", "graph", "candidate_jira_ids"], "writes": ["graph_scores"]}

    # Hand-coded priors used until fit_on_pairs replaces them with
    # learned weights.
    DEFAULT_KIND_WEIGHTS: dict[str, float] = {
        EntityKind.SERVICE: 1.0,
        EntityKind.COMPONENT: 1.0,
        EntityKind.FAULT_CLASS: 0.8,
        EntityKind.REASON_CLASS: 0.7,
        EntityKind.ERROR_CLASS: 0.6,
        EntityKind.LATENCY_BAND: 0.5,
        EntityKind.K8S_SIGNAL: 0.5,
        EntityKind.SATURATION: 0.4,
        EntityKind.SEVERITY: 0.3,
    }

    def __init__(self, *, min_kind_weight: float = 0.05) -> None:
        # Floor below which we won't drop a learned weight (so kinds
        # that happen to have 0 TP on a small train split don't disable
        # themselves entirely).
        self.min_kind_weight = min_kind_weight
        self.kind_weights: dict[str, float] = dict(self.DEFAULT_KIND_WEIGHTS)
        self.learned: bool = False
        # Diagnostic: how many TP/FP each kind saw at fit time. The
        # pipeline persists this to graph-stats.json so a reviewer can
        # see which kinds the data actually liked.
        self.learn_stats: dict[str, dict[str, int]] = {}

    def fit_on_pairs(
        self,
        train_windows: list[TriageWindow],
        memory_by_id: dict[str, JiraMemoryIssue],
        builder: MemoryGraphBuilder,
    ) -> None:
        """Compute precision-per-kind on (train_window, candidate) pairs.

        Uses `window.matched_memory_issue_ids` (gold) — allowed at fit
        time because it's the training-set retrieval label. Pipeline
        scoring never reads gold matched ids at predict time.

        The window node is added to the graph transiently during the
        fit pass so `jira_candidates_for` returns the right pool, then
        removed before the next window is processed. The pipeline's
        per-query add/remove cycle does the same thing at predict time.
        """
        tp: Counter[str] = Counter()
        fp: Counter[str] = Counter()
        graph = builder.graph
        for w in train_windows:
            gold = set(w.matched_memory_issue_ids or [])
            if not gold:
                continue  # ranking ground-truth missing — skip
            builder.add_window(w)
            try:
                candidate_ids = graph.jira_candidates_for(w.window_id)
                for cid in candidate_ids:
                    if cid not in memory_by_id:
                        continue
                    shared = graph.shared_entities(w.window_id, cid)
                    if not shared:
                        continue
                    hit = cid in gold
                    for ent in shared:
                        if hit:
                            tp[ent.id.kind] += 1
                        else:
                            fp[ent.id.kind] += 1
            finally:
                builder.remove_window(w.window_id)

        weights: dict[str, float] = {}
        stats: dict[str, dict[str, int]] = {}
        for kind in set(tp) | set(fp):
            t, f = tp[kind], fp[kind]
            total = t + f
            precision = (t / total) if total else 0.0
            weights[kind] = max(self.min_kind_weight, precision)
            stats[kind] = {"tp": t, "fp": f, "precision_pct": int(precision * 100)}
        # Fill any kind we know about (BRIDGEABLE_KINDS is the canonical
        # whitelist) with the floor so they still contribute something —
        # being absent from the train set's bridges isn't evidence of
        # irrelevance.
        for kind in BRIDGEABLE_KINDS:
            if kind not in weights:
                weights[kind] = self.min_kind_weight
        if weights:
            self.kind_weights = weights
            self.learned = True
            self.learn_stats = stats

    def run(self, ctx: AgentContext) -> SkillResult:
        if not ctx.candidate_jira_ids:
            return SkillResult(self.name, True, "no candidates", {})
        total_added = 0.0
        per_candidate: dict[str, float] = {}
        for cid in ctx.candidate_jira_ids:
            shared = ctx.graph.shared_entities(ctx.window.window_id, cid)
            score = 0.0
            for ent in shared:
                w = ctx.graph.bridge_weight(ent.id)
                kind_bonus = self.kind_weights.get(ent.id.kind, self.min_kind_weight)
                score += w * kind_bonus
            per_candidate[cid] = score
            total_added += score
        # Normalize to [0, 1] for blending parity with similarity scores
        peak = max(per_candidate.values()) if per_candidate else 0.0
        for cid, s in per_candidate.items():
            normed = (s / peak) if peak > 0 else 0.0
            ctx.graph_scores[cid] = ctx.graph_scores.get(cid, 0.0) + normed
        return SkillResult(
            self.name, True,
            f"graph-scored {len(per_candidate)} candidates (peak={peak:.2f}, learned={self.learned})",
            {
                "peak_score": peak,
                "total_score_added": total_added,
                "kind_weights_learned": self.learned,
            },
        )


class GraphTraverseExplainSkill(Skill):
    name = "graph_traverse_explain"
    description = (
        "Build a human-readable explanation for the top candidate by "
        "listing the shared entity nodes and their kinds — i.e. exactly "
        "which graph join produced the match. Writes explanation."
    )
    input_schema = {"reads": ["window", "graph", "combined_scores"], "writes": ["explanation"]}

    def run(self, ctx: AgentContext) -> SkillResult:
        if not ctx.combined_scores:
            ctx.explanation = (
                f"No matching past Jira ticket found for {ctx.window.service_name}. "
                "Treating as a potentially novel incident."
            )
            return SkillResult(self.name, True, "no candidates -> novel", {})
        top_cid = max(ctx.combined_scores, key=lambda k: ctx.combined_scores[k])
        top_issue = ctx.visible_jira.get(top_cid)
        shared = ctx.graph.shared_entities(ctx.window.window_id, top_cid)
        if not top_issue:
            return SkillResult(self.name, False, "top candidate not in visible_jira", {})
        by_kind: dict[str, list[str]] = {}
        for ent in shared:
            by_kind.setdefault(ent.id.kind, []).append(ent.id.value)
        if not by_kind:
            ctx.explanation = (
                f"Top match {top_issue.jira_issue_key} ({top_issue.affected_service}, "
                f"{top_issue.fault_type}) chosen on lexical similarity alone — no "
                f"shared entity bridges."
            )
            return SkillResult(self.name, True, "no graph bridges -> text-only", {})
        # Order kinds by discriminative power
        kind_priority = [
            EntityKind.COMPONENT, EntityKind.SERVICE, EntityKind.FAULT_CLASS,
            EntityKind.REASON_CLASS, EntityKind.ERROR_CLASS,
            EntityKind.LATENCY_BAND, EntityKind.K8S_SIGNAL,
            EntityKind.SATURATION, EntityKind.SEVERITY,
        ]
        bullets: list[str] = []
        for k in kind_priority:
            if k in by_kind:
                bullets.append(f"{k}={','.join(by_kind[k])}")
        text = (
            f"Most likely matches {top_issue.jira_issue_key} "
            f"({top_issue.affected_service} / {top_issue.fault_type}). "
            f"Graph evidence: {' | '.join(bullets)}. "
            f"Resolution note: {(top_issue.resolution_notes or '')[:140]}."
        )
        ctx.explanation = text
        return SkillResult(
            self.name, True,
            f"explained top match {top_issue.jira_issue_key} with {len(shared)} bridges",
            {"n_bridges": len(shared), "by_kind": {k: len(v) for k, v in by_kind.items()}},
        )


class NoveltyCheckSkill(Skill):
    name = "novelty_check"
    description = (
        "Decide whether the window should be treated as novel: true when "
        "no candidate accumulated a combined score above novelty_min."
    )
    input_schema = {"reads": ["combined_scores"], "writes": ["is_novel"]}

    def __init__(self, *, novelty_min: float = 0.15) -> None:
        self.novelty_min = novelty_min

    def run(self, ctx: AgentContext) -> SkillResult:
        if not ctx.combined_scores:
            return SkillResult(self.name, True, "no candidates", {"is_novel": True})
        top_score = max(ctx.combined_scores.values())
        is_novel = top_score < self.novelty_min
        ctx.skill_trace.append({"skill": self.name, "is_novel": is_novel, "top_score": top_score})
        return SkillResult(
            self.name, True,
            f"top_score={top_score:.3f} -> is_novel={is_novel}",
            {"top_score": top_score, "is_novel": is_novel},
        )


# ---------------------------------------------------------------------------
# Decision skill — combines accumulated state into a triage score
# ---------------------------------------------------------------------------


class NumericBlendSkill(Skill):
    """Window-global numeric classifier head.

    Holds a HistGradientBoostingClassifier fit on the production-safe
    `triage_feature_*` columns from the train split. At `.run` time it
    writes a single scalar `ctx.numeric_score` in [0, 1] — the model's
    estimate of P(ticket_worthy | numeric features) for the window.

    This skill is the "did anything actually bad happen?" signal. The
    similarity + graph skills together are the "if so, which past Jira?"
    signal. TriageDecideSkill blends both: a window can only score high
    if BOTH (a) the numeric features look ticket-worthy AND (b) some
    past Jira matches structurally — which is the right product
    behavior. (Avoids the "high numeric score but no plausible past
    Jira" false positive AND the "great retrieval match but no actual
    incident" false positive.)

    Production-realism: reads only `triage_feature_*` columns from
    `window.raw` and `service_name` is NOT used as a feature here
    (already encoded in graph entities elsewhere). Never reads
    `triage_label`, `triage_severity`, `is_hard_case`, etc.
    """

    name = "numeric_blend"
    description = (
        "Score the current window with a HistGradientBoosting head trained "
        "on the production-safe numeric features. Writes a per-window "
        "scalar in [0,1] that triage_decide consumes alongside per-candidate "
        "similarity/graph scores."
    )
    input_schema = {"reads": ["window"], "writes": ["numeric_score"]}

    def __init__(
        self,
        *,
        max_iter: int = 300,
        learning_rate: float = 0.05,
        max_depth: int = 8,
        l2_regularization: float = 0.1,
        min_samples_leaf: int = 20,
        random_state: int = 42,
    ) -> None:
        self.max_iter = max_iter
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.l2_regularization = l2_regularization
        # Exposed so smoke tests (tiny synthetic datasets) can lower it
        # without affecting the production default. HGB's default of 20
        # is right for v4/v5 corpora (3000+ rows); tests use ~30 rows.
        self.min_samples_leaf = min_samples_leaf
        self.random_state = random_state
        self._model: Any = None
        self._feature_columns: list[str] = []

    def fit(self, train_windows: list[TriageWindow], feature_columns: list[str]) -> None:
        if not train_windows or not feature_columns:
            return
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier
        except ImportError:
            # Graceful degradation: hybrid pipeline still runs without
            # sklearn — just without the numeric signal.
            self._model = None
            return
        self._feature_columns = list(feature_columns)
        X = [
            [float(w.raw.get(c, 0.0) or 0.0) for c in feature_columns]
            for w in train_windows
        ]
        y = [1 if w.triage_label == "ticket_worthy" else 0 for w in train_windows]
        # Need at least one positive AND one negative or HGB raises.
        if sum(y) == 0 or sum(y) == len(y):
            self._model = None
            return
        model = HistGradientBoostingClassifier(
            max_iter=self.max_iter,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            l2_regularization=self.l2_regularization,
            min_samples_leaf=self.min_samples_leaf,
            class_weight="balanced",
            random_state=self.random_state,
        )
        model.fit(X, y)
        self._model = model

    def run(self, ctx: AgentContext) -> SkillResult:
        if self._model is None or not self._feature_columns:
            ctx.numeric_score = None
            return SkillResult(self.name, True, "no model fit -> skipping numeric blend", {})
        x = [
            [float(ctx.window.raw.get(c, 0.0) or 0.0) for c in self._feature_columns]
        ]
        proba = float(self._model.predict_proba(x)[0][1])
        ctx.numeric_score = proba
        return SkillResult(
            self.name, True,
            f"numeric_score={proba:.3f}",
            {"numeric_score": proba, "n_features": len(self._feature_columns)},
        )


class TriageDecideSkill(Skill):
    name = "triage_decide"
    description = (
        "Combine similarity_scores + graph_scores into combined_scores and "
        "set triage_score. If numeric_score is present (hybrid path), it is "
        "blended with the top per-candidate score; otherwise the skill "
        "falls back to a graph+similarity-only score."
    )
    input_schema = {
        "reads": ["window", "similarity_scores", "graph_scores", "numeric_score"],
        "writes": ["combined_scores", "triage_score", "decision"],
    }

    def __init__(
        self,
        *,
        sim_weight: float = 0.55,
        graph_weight: float = 0.45,
        bridge_bonus: float = 0.05,
        numeric_weight: float = 0.7,
    ) -> None:
        self.sim_weight = sim_weight
        self.graph_weight = graph_weight
        self.bridge_bonus = bridge_bonus
        # Only used when ctx.numeric_score is not None.
        # numeric_weight = how much of the final score comes from the
        # window-global numeric model vs the per-candidate graph score.
        # 0.7 matches the project's existing observation that numeric
        # features dominate triage PR-AUC.
        self.numeric_weight = numeric_weight

    def run(self, ctx: AgentContext) -> SkillResult:
        all_cids = set(ctx.similarity_scores) | set(ctx.graph_scores)
        # ---- per-candidate combined score ----
        if all_cids:
            for cid in all_cids:
                sim = ctx.similarity_scores.get(cid, 0.0)
                gr = ctx.graph_scores.get(cid, 0.0)
                n_bridges = len(ctx.graph.shared_entities(ctx.window.window_id, cid))
                ctx.combined_scores[cid] = (
                    self.sim_weight * sim
                    + self.graph_weight * gr
                    + self.bridge_bonus * min(n_bridges, 5)
                )
            top_candidate = max(ctx.combined_scores.values())
        else:
            top_candidate = 0.0

        # ---- final triage score: blend numeric + per-candidate ----
        if ctx.numeric_score is not None:
            # Hybrid blend. The numeric signal dominates the headline
            # score; the per-candidate score still moves the needle
            # enough that two windows with identical numeric output get
            # ranked by their retrieval quality.
            triage = (
                self.numeric_weight * ctx.numeric_score
                + (1.0 - self.numeric_weight) * top_candidate
            )
            mode = "hybrid"
        else:
            triage = top_candidate
            mode = "graph_only"

        ctx.triage_score = float(max(0.0, min(1.0, triage)))
        ctx.decision = "ticket_worthy" if ctx.triage_score >= 0.5 else "noise"
        return SkillResult(
            self.name, True,
            (
                f"mode={mode} top_candidate={top_candidate:.3f} "
                f"numeric={ctx.numeric_score} triage_score={ctx.triage_score:.3f} "
                f"decision={ctx.decision}"
            ),
            {
                "mode": mode,
                "top_candidate": top_candidate,
                "numeric_score": ctx.numeric_score,
                "n_combined": len(ctx.combined_scores),
            },
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def default_skill_registry() -> dict[str, Skill]:
    """The set of skills the default RulePlanner picks from.

    Order matters only insofar as the planner uses these as building
    blocks. The planner is what fixes the execution order.
    """
    return {
        EntityExtractSkill.name: EntityExtractSkill(),
        ComponentFilterSkill.name: ComponentFilterSkill(),
        ServiceFilterSkill.name: ServiceFilterSkill(),
        SeverityAlignSkill.name: SeverityAlignSkill(),
        ErrorClassAlignSkill.name: ErrorClassAlignSkill(),
        LexicalSimilaritySkill.name: LexicalSimilaritySkill(),
        LogSignatureSimilaritySkill.name: LogSignatureSimilaritySkill(),
        EmbeddingSimilaritySkill.name: EmbeddingSimilaritySkill(),
        CrossEncoderRerankSkill.name: CrossEncoderRerankSkill(),
        GraphScoreSkill.name: GraphScoreSkill(),
        NumericBlendSkill.name: NumericBlendSkill(),
        TriageDecideSkill.name: TriageDecideSkill(),
        NoveltyCheckSkill.name: NoveltyCheckSkill(),
        GraphTraverseExplainSkill.name: GraphTraverseExplainSkill(),
    }


def available_skills() -> list[dict[str, Any]]:
    """Self-describing skill manifest the LLMPlanner sends to the model."""
    registry = default_skill_registry()
    return [
        {
            "name": s.name,
            "description": s.description,
            "input_schema": s.input_schema,
        }
        for s in registry.values()
    ]
