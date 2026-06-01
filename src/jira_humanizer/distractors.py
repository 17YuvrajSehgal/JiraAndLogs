"""V2 distractor minting (LLM-Jira-enhancement.md §13.5 + §13.8 step 5).

Distractors are well-formed Jira issues describing incidents that
**never happened** in our v5-large run. They exist to test retrieval
PRECISION — does the agent retrieve the right ticket for a window, or
does a plausible-looking distractor confuse it? Without distractors,
"coverage" tells us if a ticket exists but not whether retrieval is
discriminating.

Three sourcing strategies per §13.5:

  1. **TAWOS-sampled** — real bug reports pulled from `tawos.issue` for
     infra-shaped projects (MongoDB SERVER, Mesos, Mule, Hyperledger).
     Project-specific nouns scrubbed; resolution_time_s resampled to
     our V2 distribution per §13.9 #2. NO LLM involved — these are
     the "gold standard" distractors precisely because their voice is
     real engineer prose, not synthetic. ~60 of the corpus.

  2. **In-arch-never-happened** — fake incidents in our actual services
     (cartservice, paymentservice, etc.) that were never injected.
     Hardest distractors because service names match real V2 tickets;
     the model has to discriminate on log/metric content, not on
     service-name lexical overlap. ~25 of the corpus.

  3. **Cross-arch** — plausible incidents in components we don't have
     (Kafka consumer lag, Spark OOM, Elasticsearch red cluster). High
     retrieval-confusion potential with infra-flavored vocabulary.
     ~25 of the corpus.

All distractors carry `is_distractor=true` in the schema. The agent
never sees this flag at retrieval — it's evaluation-only metadata.
Distractors are written to a SEPARATE subdir
(`jira-shadow-humanized-v2-distractors/<minted_at>/`) so they can be
mixed into the main corpus at evaluation time without polluting the
real-ticket subdir.

§13.9 #1 — distractors share the V1 persona catalog (voice must not
be a tell). TAWOS distractors skip our persona system entirely
because their voice is already real. LLM distractors use the same
prompt scaffolding as real tickets but with `evidence_bundle=None` —
no real telemetry to ground them.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_SRC = Path(__file__).resolve().parent.parent
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from .personas import persona_for  # noqa: E402
from .rewrite import _NAMES  # noqa: E402  (avatar name pool)
from .sanitizer import find_lab_tokens, assert_clean  # noqa: E402
from .timeline_schema import (  # noqa: E402
    DESCRIPTION_MAX_CHARS,
    EvidenceSlice,
    StepKind,
    TicketTimeline,
    TimelineStep,
)


DISTRACTOR_GENERATOR_VERSION = "v2.1.0-distractors-step5"


# ---------------------------------------------------------------------------
# Resolution-time resample for distractors per §13.9 #2 — same empirical
# distribution as real V2 tickets. Imported lazily to avoid a cycle
# (timeline_generator imports from this module would loop).
# ---------------------------------------------------------------------------


def _sample_distractor_resolution_time(seed: str) -> int:
    """Same distribution as V2 real tickets — full empirical range so
    a model can't shortcut on resolution_time."""
    from .timeline_generator import _sample_resolution_time_s
    return _sample_resolution_time_s(f"distractor::{seed}")


# ---------------------------------------------------------------------------
# Avatar picker — rotates from the wider _NAMES pool with a distractor
# salt so the same name doesn't appear on real cart-redis tickets AND
# Kafka distractors (per §13.9 #1 rationale).
# ---------------------------------------------------------------------------


def _distractor_avatar(persona_role: str, seed: str, salt: str) -> str:
    """Deterministic avatar pick rotated by `seed`+`salt`. Uses a
    DIFFERENT seed namespace than real-ticket avatars so the same
    person doesn't 'handle' both a real cart-redis incident and a
    fake Kafka one."""
    h = int(hashlib.sha256(
        f"distractor-avatar::{persona_role}::{seed}::{salt}".encode("utf-8")
    ).hexdigest()[:8], 16)
    return _NAMES[h % len(_NAMES)]


# ---------------------------------------------------------------------------
# TAWOS-sampled distractors — pull real engineer prose from local MySQL,
# scrub project-specific nouns, write as TicketTimeline rows.
# ---------------------------------------------------------------------------


# Project nouns to scrub. Order matters: longer patterns first so
# "Atlassian Jira" matches before "Jira" alone.
_TAWOS_SCRUB_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bMongoDB\b", re.IGNORECASE), "datastore"),
    (re.compile(r"\bmongod\b", re.IGNORECASE), "datastore daemon"),
    (re.compile(r"\bMesos\b", re.IGNORECASE), "scheduler"),
    (re.compile(r"\bHyperledger Fabric\b", re.IGNORECASE), "blockchain platform"),
    (re.compile(r"\bHyperledger\b", re.IGNORECASE), "blockchain platform"),
    (re.compile(r"\bAtlassian Confluence\b", re.IGNORECASE), "wiki platform"),
    (re.compile(r"\bConfluence\b", re.IGNORECASE), "wiki platform"),
    (re.compile(r"\bAtlassian Jira\b", re.IGNORECASE), "ticketing tool"),
    (re.compile(r"\bAtlassian\b", re.IGNORECASE), "vendor"),
    (re.compile(r"\bJira\b", re.IGNORECASE), "ticketing tool"),
    (re.compile(r"\bMule\b", re.IGNORECASE), "integration platform"),
    (re.compile(r"\bMoodle\b", re.IGNORECASE), "lms platform"),
    (re.compile(r"\bTitanium\b", re.IGNORECASE), "mobile sdk"),
    (re.compile(r"\bLucene\b", re.IGNORECASE), "search engine"),
    # Project-key prefixes
    (re.compile(r"\b(SERVER|MESOS|MULE|FAB|CONFSERVER|JRASERVER|MDL|TIMOB)-\d+\b"),
     "TICKET-XXXXX"),
)


def _scrub_tawos_text(text: str) -> str:
    """Replace project-specific nouns with generic equivalents."""
    if not text:
        return ""
    out = text
    for pattern, repl in _TAWOS_SCRUB_RULES:
        out = pattern.sub(repl, out)
    return out


@dataclass
class TawosDistractorRow:
    """Subset of TAWOS `issue` columns we need for a distractor."""
    issue_id: int
    project_key: str
    title: str
    description_text: str
    description_code: str
    priority: str
    resolution: str
    comments: list[dict[str, str]]   # [{"body": str, "body_code": str | None}]


def _pull_tawos_distractors(
    n: int,
    *,
    mysql_conn: Any,
    seed: int = 0,
    min_desc_len: int = 200,
    max_desc_len: int = 1500,
) -> list[TawosDistractorRow]:
    """Pull N realistic bug reports from TAWOS via existing pymysql conn.

    Filters to infra-shaped projects (MongoDB SERVER / Mesos / Mule /
    Hyperledger Fabric) — these align with our SRE evaluation context
    and have engineer-voice descriptions that scrub cleanly.
    """
    cur = mysql_conn.cursor()
    sql = """
        SELECT i.ID, p.Project_Key AS project_key, i.Title,
               COALESCE(i.Description_Text, '') AS description_text,
               COALESCE(i.Description_Code, '') AS description_code,
               COALESCE(i.Priority, 'Major') AS priority,
               COALESCE(i.Resolution, 'Fixed') AS resolution
        FROM issue i JOIN project p ON p.ID = i.Project_ID
        WHERE i.Type IN ('Bug','Defect')
          AND i.Description_Text IS NOT NULL
          AND CHAR_LENGTH(i.Description_Text) BETWEEN %s AND %s
          AND p.Project_Key IN ('SERVER','MESOS','MULE','FAB')
        ORDER BY RAND(%s)
        LIMIT %s
    """
    cur.execute(sql, (min_desc_len, max_desc_len, seed, n * 3))   # over-fetch for sanitizer filter
    rows: list[TawosDistractorRow] = []
    for row in cur.fetchall():
        if len(rows) >= n:
            break
        # Pull a few comments for this issue.
        cur2 = mysql_conn.cursor()
        cur2.execute(
            "SELECT COALESCE(Comment_Text, '') AS body, "
            "       COALESCE(Comment_Code, '') AS body_code "
            "FROM comment WHERE Issue_ID=%s ORDER BY Creation_Date LIMIT 6",
            (row["ID"],),
        )
        comments = [
            {
                "body": _scrub_tawos_text(str(c.get("body") or "")),
                "body_code": (
                    _scrub_tawos_text(str(c.get("body_code") or ""))
                    if c.get("body_code") else None
                ),
            }
            for c in cur2.fetchall()
        ]
        cur2.close()

        title = _scrub_tawos_text(str(row["Title"] or ""))
        desc_text = _scrub_tawos_text(str(row["description_text"]))
        desc_code = _scrub_tawos_text(str(row["description_code"]))
        # Last-mile leak check on the whole concatenated text.
        joined = "\n".join([
            title, desc_text, desc_code,
            *(c["body"] for c in comments),
            *(c["body_code"] or "" for c in comments),
        ])
        if find_lab_tokens(joined):
            # Skip this row — would contaminate the corpus.
            continue
        rows.append(TawosDistractorRow(
            issue_id=int(row["ID"]),
            project_key=str(row["project_key"]),
            title=title[:140],
            description_text=desc_text,
            description_code=desc_code,
            priority=str(row["priority"]),
            resolution=str(row["resolution"]),
            comments=comments,
        ))
    cur.close()
    return rows


def tawos_row_to_ticket(row: TawosDistractorRow) -> TicketTimeline:
    """Convert a TAWOS distractor row into a TicketTimeline.

    Maps:
      - Title          → first line of report step (the summary)
      - Description    → report step body
      - Description_Code → ticket-level description_code
      - Comments       → ack / hypothesis / resolve steps (assigned by index)
      - Resolution     → resolution field
      - resolution_time_s → resampled per §13.9 #2
    """
    seed = f"tawos-{row.issue_id}"
    ticket_id = f"DIST-TAWOS-{row.issue_id}"

    # Build the report step. The "title" is the summary line; the prose
    # body is the description_text. No real persona — author is "real
    # engineer from TAWOS, name scrubbed".
    report_avatar = _distractor_avatar("backend-eng", seed, "report")
    report_text = f"{row.title}\n\n{row.description_text}"
    report_evidence = EvidenceSlice(symptom_phrase=row.title)
    report_step = TimelineStep(
        step_kind=StepKind.REPORT,
        persona_role="backend-eng",   # TAWOS reporters are usually engineers
        persona_avatar=report_avatar,
        t_offset_s=0,
        context_window_s=30,
        evidence=report_evidence,
        text=report_text,
        body_code=row.description_code or None,
        prompt_hash="",   # not generated by LLM
    )
    steps: list[TimelineStep] = [report_step]

    # Comments become ack / hypothesis / resolve steps. The last
    # comment maps to the resolve step.
    comment_personas = (
        "oncall-sre", "backend-eng", "senior-sre", "db-team",
        "fix-author",
    )
    for i, c in enumerate(row.comments):
        body = c["body"]
        if not body or len(body.strip()) < 5:
            continue
        is_last = (i == len(row.comments) - 1)
        step_kind = StepKind.RESOLVE if is_last else (
            StepKind.ACK if i == 0 else StepKind.HYPOTHESIS
        )
        persona_role = (
            "fix-author" if is_last else
            comment_personas[min(i, len(comment_personas) - 2)]
        )
        avatar = _distractor_avatar(persona_role, seed, f"c{i}")
        steps.append(TimelineStep(
            step_kind=step_kind,
            persona_role=persona_role,
            persona_avatar=avatar,
            t_offset_s=180 + i * 600,   # spread comments across the timeline
            context_window_s=180 + i * 600,
            evidence=EvidenceSlice(symptom_phrase=row.title),
            text=body,
            body_code=c.get("body_code") or None,
            prompt_hash="",
        ))

    # If there are no comments, mint a tiny synthetic resolve step
    # ("Closing as resolved.") so the timeline has a terminal step.
    if len(steps) == 1:
        steps.append(TimelineStep(
            step_kind=StepKind.RESOLVE,
            persona_role="fix-author",
            persona_avatar=_distractor_avatar("fix-author", seed, "resolve"),
            t_offset_s=1800,
            context_window_s=1800,
            evidence=EvidenceSlice(symptom_phrase=row.title),
            text="Closing as resolved.",
            body_code=None,
            prompt_hash="",
        ))

    # Normalize TAWOS resolution vocabulary to the V2 set.
    resolution_map = {
        "Fixed":              "Fixed",
        "Done":               "Fixed",
        "Won't Fix":          "Won't Fix",
        "Wont Fix":           "Won't Fix",
        "Won't Do":           "Won't Fix",
        "Duplicate":          "Duplicate",
        "Cannot Reproduce":   "Cannot Reproduce",
        "Not A Bug":          "Not A Bug",
        "Timed out":          "Timed out",
        "Answered":           "Won't Fix",
        "Complete":           "Fixed",
        "Incomplete":         "Cannot Reproduce",
    }
    resolution = resolution_map.get(row.resolution, "Fixed")

    return TicketTimeline(
        ticket_id=ticket_id,
        source_episode_id=f"distractor-tawos-{row.issue_id}",
        source_dataset_run_id="",
        source_injection_id=None,   # distractors have no injection
        affected_services_seen=[],
        severity_seen=row.priority.lower() if row.priority else "medium",
        components_seen=[],
        is_misattributed=False,
        closed_as_noise=(resolution != "Fixed"),
        steps=steps,
        description_code=row.description_code or "",
        resolution=resolution,
        resolution_time_s=_sample_distractor_resolution_time(seed),
        is_distractor=True,
        is_followup_of=None,
        log_signature_source="empty",   # TAWOS distractors aren't sourced from our raw logs
        evidence_bundle_hash="",
        generator_version=DISTRACTOR_GENERATOR_VERSION,
        sanitizer_version="v1.0.0",
        symptom_map_version="",
    )


# ---------------------------------------------------------------------------
# LLM-generated distractors — cross-architecture and in-architecture-but-
# never-happened. Use a small ad-hoc 3-step LLM pipeline (report → ack →
# resolve) since there's no real evidence to ground a full V2 timeline.
# ---------------------------------------------------------------------------


@dataclass
class SyntheticDistractorSpec:
    """One LLM distractor archetype. Curated by hand; LLM generates the
    actual prose around the symptom_phrase + component.
    """
    distractor_id: str          # stable id, becomes ticket_id suffix
    kind: str                   # "cross-arch" | "in-arch-never"
    symptom_phrase: str         # what the reporter would describe
    component: str              # service / system name to attribute it to
    severity: str               # "low" | "medium" | "high"


# In-arch-but-never-happened — fake incidents in OUR services that we
# never injected. Service names match real V2 tickets — the hardest
# distractors because the agent must discriminate on log/metric content,
# not on service-name lexical overlap.
IN_ARCH_DISTRACTOR_SPECS: tuple[SyntheticDistractorSpec, ...] = (
    SyntheticDistractorSpec(
        "in-arch-001", "in-arch-never",
        "payment service rate limiter dropping legitimate charges",
        "paymentservice", "high"),
    SyntheticDistractorSpec(
        "in-arch-002", "in-arch-never",
        "shipping service emitting order-shipped events out of sequence",
        "shippingservice", "medium"),
    SyntheticDistractorSpec(
        "in-arch-003", "in-arch-never",
        "currency service serving stale exchange rates after API key rotation",
        "currencyservice", "high"),
    SyntheticDistractorSpec(
        "in-arch-004", "in-arch-never",
        "email template render hitting recursion limit on long order lists",
        "emailservice", "medium"),
    SyntheticDistractorSpec(
        "in-arch-005", "in-arch-never",
        "ad service ML inference timing out on cold-start of new model version",
        "adservice", "medium"),
    SyntheticDistractorSpec(
        "in-arch-006", "in-arch-never",
        "recommendation personalization features missing for first-time users",
        "recommendationservice", "low"),
    SyntheticDistractorSpec(
        "in-arch-007", "in-arch-never",
        "cart user-session collision between two browser tabs on same account",
        "cartservice", "low"),
    SyntheticDistractorSpec(
        "in-arch-008", "in-arch-never",
        "frontend SPA bundle size regression doubling time-to-interactive",
        "frontend", "medium"),
    SyntheticDistractorSpec(
        "in-arch-009", "in-arch-never",
        "checkout order-id collision under concurrent submission burst",
        "checkoutservice", "high"),
    SyntheticDistractorSpec(
        "in-arch-010", "in-arch-never",
        "product catalog image CDN returning stale assets after deploy",
        "productcatalogservice", "low"),
    SyntheticDistractorSpec(
        "in-arch-011", "in-arch-never",
        "payment webhook retry storm hitting downstream rate limits",
        "paymentservice", "medium"),
    SyntheticDistractorSpec(
        "in-arch-012", "in-arch-never",
        "shipping address cache returning previous customer address",
        "shippingservice", "high"),
    SyntheticDistractorSpec(
        "in-arch-013", "in-arch-never",
        "currency decimal-precision bug rounding small purchases to zero",
        "currencyservice", "medium"),
    SyntheticDistractorSpec(
        "in-arch-014", "in-arch-never",
        "recommendation batch job overrunning into business hours",
        "recommendationservice", "low"),
    SyntheticDistractorSpec(
        "in-arch-015", "in-arch-never",
        "checkout fulfillment callback retrying past success",
        "checkoutservice", "medium"),
    SyntheticDistractorSpec(
        "in-arch-016", "in-arch-never",
        "cart item-count overflow when user adds 9999+ of same SKU",
        "cartservice", "low"),
    SyntheticDistractorSpec(
        "in-arch-017", "in-arch-never",
        "frontend asset CDN edge cache poisoning on rollback",
        "frontend", "medium"),
    SyntheticDistractorSpec(
        "in-arch-018", "in-arch-never",
        "ad service slot-fill returning empty when targeting data is stale",
        "adservice", "low"),
    SyntheticDistractorSpec(
        "in-arch-019", "in-arch-never",
        "email service SMTP rate-limit hit during nightly digest burst",
        "emailservice", "medium"),
    SyntheticDistractorSpec(
        "in-arch-020", "in-arch-never",
        "product catalog SKU naming collision between vendor catalogs",
        "productcatalogservice", "low"),
    SyntheticDistractorSpec(
        "in-arch-021", "in-arch-never",
        "currency conversion cache invalidating too eagerly on minor rate moves",
        "currencyservice", "low"),
    SyntheticDistractorSpec(
        "in-arch-022", "in-arch-never",
        "cart abandoned-cart email triggering on active sessions",
        "cartservice", "medium"),
    SyntheticDistractorSpec(
        "in-arch-023", "in-arch-never",
        "frontend search autocomplete leaking PII into query params",
        "frontend", "high"),
    SyntheticDistractorSpec(
        "in-arch-024", "in-arch-never",
        "checkout tax-rate lookup defaulting on missing zip codes",
        "checkoutservice", "medium"),
    SyntheticDistractorSpec(
        "in-arch-025", "in-arch-never",
        "shipping rate calculator returning negative shipping cost on coupon stack",
        "shippingservice", "high"),
)


# Cross-architecture — bugs in components we don't have. Easier
# distractors because service names don't match real V2 tickets, but
# infra-flavored vocabulary still has retrieval-confusion potential.
CROSS_ARCH_DISTRACTOR_SPECS: tuple[SyntheticDistractorSpec, ...] = (
    SyntheticDistractorSpec(
        "cross-001", "cross-arch",
        "Kafka consumer group lag exceeding alert threshold for analytics topic",
        "kafka-analytics", "high"),
    SyntheticDistractorSpec(
        "cross-002", "cross-arch",
        "Spark batch job OOM killed mid-execution on nightly aggregation",
        "spark-cluster", "medium"),
    SyntheticDistractorSpec(
        "cross-003", "cross-arch",
        "Postgres read replica lag spiking during peak write load",
        "postgres-primary", "high"),
    SyntheticDistractorSpec(
        "cross-004", "cross-arch",
        "Elasticsearch cluster red status after disk pressure on data node",
        "elasticsearch", "high"),
    SyntheticDistractorSpec(
        "cross-005", "cross-arch",
        "RabbitMQ queue backing up due to slow consumer on payment events",
        "rabbitmq-broker", "high"),
    SyntheticDistractorSpec(
        "cross-006", "cross-arch",
        "ZooKeeper ensemble split-brain after network partition",
        "zookeeper-ensemble", "high"),
    SyntheticDistractorSpec(
        "cross-007", "cross-arch",
        "Hadoop NameNode failover taking longer than RTO",
        "hadoop-namenode", "medium"),
    SyntheticDistractorSpec(
        "cross-008", "cross-arch",
        "Vault token TTL exhaustion blocking service-to-service auth",
        "vault", "high"),
    SyntheticDistractorSpec(
        "cross-009", "cross-arch",
        "Consul agent disconnections cascading into service-discovery flaps",
        "consul-agent", "medium"),
    SyntheticDistractorSpec(
        "cross-010", "cross-arch",
        "Memcached pool exhaustion during cache stampede after deploy",
        "memcached-pool", "medium"),
    SyntheticDistractorSpec(
        "cross-011", "cross-arch",
        "Cassandra repair operation stuck on token range",
        "cassandra-cluster", "low"),
    SyntheticDistractorSpec(
        "cross-012", "cross-arch",
        "Couchbase XDCR replication lag between primary and DR cluster",
        "couchbase-xdcr", "medium"),
    SyntheticDistractorSpec(
        "cross-013", "cross-arch",
        "Druid historical node OOM during large segment loading",
        "druid-historical", "medium"),
    SyntheticDistractorSpec(
        "cross-014", "cross-arch",
        "Solr index corruption requiring rebuild from source",
        "solr-search", "low"),
    SyntheticDistractorSpec(
        "cross-015", "cross-arch",
        "Spark structured streaming job restart loop on checkpoint mismatch",
        "spark-streaming", "high"),
    SyntheticDistractorSpec(
        "cross-016", "cross-arch",
        "Kafka MirrorMaker stopped replicating after cluster upgrade",
        "kafka-mirrormaker", "medium"),
    SyntheticDistractorSpec(
        "cross-017", "cross-arch",
        "InfluxDB shard compaction blocking writes during retention enforcement",
        "influxdb-cluster", "medium"),
    SyntheticDistractorSpec(
        "cross-018", "cross-arch",
        "Argo workflow controller stuck retrying failed pipeline step",
        "argo-workflows", "low"),
    SyntheticDistractorSpec(
        "cross-019", "cross-arch",
        "MinIO object store returning 503 under sustained PUT load",
        "minio-storage", "high"),
    SyntheticDistractorSpec(
        "cross-020", "cross-arch",
        "Prometheus rule evaluation lagging during cardinality spike",
        "prometheus-eval", "medium"),
    SyntheticDistractorSpec(
        "cross-021", "cross-arch",
        "Jaeger collector dropping spans under burst from a new service",
        "jaeger-collector", "low"),
    SyntheticDistractorSpec(
        "cross-022", "cross-arch",
        "Linkerd proxy injection failing on new namespace after operator upgrade",
        "linkerd-proxy", "medium"),
    SyntheticDistractorSpec(
        "cross-023", "cross-arch",
        "ETCD compaction running too aggressively, causing read latency spikes",
        "etcd-cluster", "medium"),
    SyntheticDistractorSpec(
        "cross-024", "cross-arch",
        "HAProxy frontend connection limit reached during marketing campaign",
        "haproxy-frontend", "high"),
    SyntheticDistractorSpec(
        "cross-025", "cross-arch",
        "Pinot real-time table query failures due to stale segment metadata",
        "pinot-realtime", "low"),
)


# ---------------------------------------------------------------------------
# LLM client (duplicates the timeline_generator's wrapper but stays
# local so we don't import the heavy module just for the HTTP call)
# ---------------------------------------------------------------------------


@dataclass
class DistractorLLMConfig:
    base_url: str = "http://localhost:1234"
    model: str = "qwen/qwen2.5-coder-14b"
    temperature: float = 0.7
    max_tokens_report: int = 140
    max_tokens_ack: int = 70
    max_tokens_resolve: int = 90
    timeout_s: float = 60.0


@dataclass
class DistractorUsageStats:
    n_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    n_errors: int = 0
    n_leak_rejections: int = 0
    wall_time_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_calls": self.n_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "n_errors": self.n_errors,
            "n_leak_rejections": self.n_leak_rejections,
            "wall_time_s": round(self.wall_time_s, 2),
        }


def _chat_simple(
    cfg: DistractorLLMConfig,
    system: str,
    user: str,
    *,
    max_tokens: int,
    stats: DistractorUsageStats,
) -> str:
    """Stripped-down chat call that accumulates into a passed-in stats
    object. Kept separate from timeline_generator's tracker so the
    distractor manifest reports its own numbers."""
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": cfg.temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        f"{cfg.base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            data = json.load(resp)
    except urllib.error.URLError as e:
        stats.n_errors += 1
        return f"__ERROR__ {e}"
    elapsed = time.time() - t0
    usage = data.get("usage") or {}
    stats.n_calls += 1
    stats.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
    stats.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
    stats.total_tokens = stats.prompt_tokens + stats.completion_tokens
    stats.wall_time_s += elapsed
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""


def _redact(text: str) -> str:
    """Same pre-sanitizer cleanup as timeline_generator._redact_lab_tokens."""
    from .timeline_generator import _redact_lab_tokens
    return _redact_lab_tokens(text)


def generate_synthetic_distractor(
    spec: SyntheticDistractorSpec,
    *,
    cfg: DistractorLLMConfig,
    stats: DistractorUsageStats,
) -> TicketTimeline | None:
    """Generate one LLM-driven distractor ticket.

    Three-step structure: report (cs-agent or oncall-sre), ack
    (oncall-sre), resolve (fix-author). No multi-channel evidence —
    distractors don't have raw telemetry to ground them; that's the
    point. They're well-formed Jira issues describing incidents that
    never happened.

    Returns None on LLM failure or unrecoverable sanitizer leak.
    """
    seed = spec.distractor_id

    # Reporter persona — same severity weighting as real V2 tickets
    # (high → 70% oncall, medium → 50/50, low → 20% oncall).
    sev_probs = {"high": 0.70, "medium": 0.50, "low": 0.20}.get(
        spec.severity, 0.50,
    )
    h_reporter = int(hashlib.sha256(
        f"distractor-reporter::{seed}".encode("utf-8")
    ).hexdigest()[:8], 16)
    reporter_role = (
        "oncall-sre" if (h_reporter / 0xFFFFFFFF) < sev_probs else "cs-agent"
    )

    # ---- REPORT step
    reporter_persona = persona_for(reporter_role)
    report_system = (
        f"You are writing a Jira ticket at a large software company. "
        f"Write as a {reporter_persona.role}: {reporter_persona.style_descriptor}\n\n"
        "Style rules:\n"
        "- HARD LENGTH LIMIT: keep total output under 500 characters.\n"
        "- Do NOT prefix with 'Summary:' or 'Description:' field labels.\n"
        "- Do NOT start with greetings like 'Hi team' or 'Hey team'.\n"
        "- Do NOT end with sign-offs like 'Thanks,' or '[Your Name]'.\n"
        "- No markdown headers (### or **bold**).\n"
        "- Write as if typing directly into a Jira comment box."
    )
    report_user = (
        f"What you observed:\n  {spec.symptom_phrase}\n\n"
        f"Affected component / system: {spec.component}\n"
        f"Urgency: {spec.severity}\n\n"
        "Write the opening Jira ticket. One-line summary on its own line, "
        "then a short body paragraph — that's it."
    )

    report_text = _chat_simple(
        cfg, report_system, report_user,
        max_tokens=cfg.max_tokens_report, stats=stats,
    )
    if not report_text or report_text.startswith("__ERROR__"):
        return None
    report_text = _redact(report_text).strip()
    if find_lab_tokens(report_text):
        stats.n_leak_rejections += 1
        return None

    # ---- ACK step
    ack_system = (
        "You are continuing a Jira ticket at a large software company. "
        "Write as oncall-sre: terse pager-speak, lowercase ok, "
        "abbreviations ok. State what dashboard or metric you're "
        "checking next.\n\n"
        "Style rules:\n"
        "- HARD LENGTH LIMIT: keep total output under 300 characters.\n"
        "- No 'Summary:' / 'Description:' labels.\n"
        "- No greetings or sign-offs.\n"
        "- Reference the component and the symptom specifically."
    )
    ack_user = (
        f"Component / system: {spec.component}\n"
        f"Reported symptom: {spec.symptom_phrase}\n\n"
        f"Prior message (from reporter):\n{report_text[:400]}\n\n"
        "Now write your one-message acknowledgement in pager-speak. "
        "Just the comment body."
    )
    ack_text = _chat_simple(
        cfg, ack_system, ack_user,
        max_tokens=cfg.max_tokens_ack, stats=stats,
    )
    if not ack_text or ack_text.startswith("__ERROR__"):
        return None
    ack_text = _redact(ack_text).strip()
    if find_lab_tokens(ack_text):
        stats.n_leak_rejections += 1
        return None

    # ---- RESOLVE step
    resolve_system = (
        "You are closing out a Jira ticket. Write as fix-author: "
        "resolution-focused, terse close note. State what was done "
        "(rollback, config change, restart, etc.) or 'self-resolved, "
        "monitoring' if no clear root cause.\n\n"
        "Style rules:\n"
        "- HARD LENGTH LIMIT: under 350 characters.\n"
        "- One or two sentences max.\n"
        "- No labels, no greetings, no sign-offs."
    )
    resolve_user = (
        f"Component / system: {spec.component}\n"
        f"Reported symptom: {spec.symptom_phrase}\n\n"
        f"Prior thread:\n[reporter]: {report_text[:300]}\n"
        f"[oncall-sre]: {ack_text[:200]}\n\n"
        "Write the resolution comment. Just the comment body."
    )
    resolve_text = _chat_simple(
        cfg, resolve_system, resolve_user,
        max_tokens=cfg.max_tokens_resolve, stats=stats,
    )
    if not resolve_text or resolve_text.startswith("__ERROR__"):
        return None
    resolve_text = _redact(resolve_text).strip()
    if find_lab_tokens(resolve_text):
        stats.n_leak_rejections += 1
        return None

    # Assemble the timeline
    from .timeline_generator import _sample_resolution
    resolution = _sample_resolution(f"distractor::{seed}")

    steps = [
        TimelineStep(
            step_kind=StepKind.REPORT,
            persona_role=reporter_role,
            persona_avatar=_distractor_avatar(reporter_role, seed, "report"),
            t_offset_s=0,
            context_window_s=30,
            evidence=EvidenceSlice(symptom_phrase=spec.symptom_phrase),
            text=report_text,
            body_code=None,
            prompt_hash=hashlib.sha256(
                (report_system + report_user).encode("utf-8")
            ).hexdigest()[:16],
        ),
        TimelineStep(
            step_kind=StepKind.ACK,
            persona_role="oncall-sre",
            persona_avatar=_distractor_avatar("oncall-sre", seed, "ack"),
            t_offset_s=180,
            context_window_s=180,
            evidence=EvidenceSlice(symptom_phrase=spec.symptom_phrase),
            text=ack_text,
            body_code=None,
            prompt_hash=hashlib.sha256(
                (ack_system + ack_user).encode("utf-8")
            ).hexdigest()[:16],
        ),
        TimelineStep(
            step_kind=StepKind.RESOLVE,
            persona_role="fix-author",
            persona_avatar=_distractor_avatar("fix-author", seed, "resolve"),
            t_offset_s=1800,
            context_window_s=1800,
            evidence=EvidenceSlice(symptom_phrase=spec.symptom_phrase),
            text=resolve_text,
            body_code=None,
            prompt_hash=hashlib.sha256(
                (resolve_system + resolve_user).encode("utf-8")
            ).hexdigest()[:16],
        ),
    ]

    return TicketTimeline(
        ticket_id=f"DIST-{spec.kind.upper()}-{spec.distractor_id}",
        source_episode_id=f"distractor-{spec.kind}-{spec.distractor_id}",
        source_dataset_run_id="",
        source_injection_id=None,
        affected_services_seen=[spec.component],
        severity_seen=spec.severity,
        components_seen=[spec.component],
        is_misattributed=False,
        closed_as_noise=(resolution != "Fixed"),
        steps=steps,
        description_code="",   # synthetic distractors have no real logs
        resolution=resolution,
        resolution_time_s=_sample_distractor_resolution_time(seed),
        is_distractor=True,
        is_followup_of=None,
        log_signature_source="empty",
        evidence_bundle_hash="",
        generator_version=DISTRACTOR_GENERATOR_VERSION,
        sanitizer_version="v1.0.0",
        symptom_map_version="",
    )
