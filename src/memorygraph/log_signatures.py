"""Move A — characteristic log line extractor.

For each window's raw/loki/<window_id>.json file:
  1. Filter to error/warning-level structured log lines.
  2. Normalize each into a deterministic template — handles both the
     Go convention (structured fields at top-level) and the .NET
     convention (the L2 fields are embedded in the `Message` string as
     k=v pairs).
  3. Strip volatile substrings (trace_id, span_id, ISO/epoch timestamps,
     pod-name hash suffixes, IPv4 + ports, big numbers) so templates
     dedup the way an engineer would group them.
  4. Drop any template the sanitizer flags as lab-leakage — these
     never enter the signature.
  5. Dedup + count + return the top-K most-frequent templates.

The output is what Move A in `ML-NEW-IDEAS.MD` calls the
"characteristic log line signature" — the engineer-vocabulary query
that replaces the trace-aggregate `triage_evidence_text` for
retrieval. Two readers of v5-large telemetry would write the same
output for the same window, which is what makes it a stable feature.

Hypothesis (per ML-NEW-IDEAS.MD §8): an engineer-vocabulary query
against natural-language Jira memory text scores meaningfully higher
Recall@5 than a trace-aggregate query does. E5 + E6 already showed
both BM25 and dense embeddings cap at Recall@5 ≈ 0.07 on the clean
humanized corpus when the source-side query is `evidence_text`.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Make `src/` importable so we can use the shared sanitizer catalog.
_REPO_SRC = Path(__file__).resolve().parent.parent
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from jira_humanizer.sanitizer import find_lab_tokens  # noqa: E402


# Severity tokens (case-insensitive) that mark a line as error-class.
# "info"/"information" lines are excluded — they're the L1 RPC trace
# logs that dominate the dump but don't carry fault content.
_ERROR_SEVERITIES = frozenset({"error", "err", "warn", "warning", "fatal"})


# Volatile-substring patterns. Stripped before dedup so identical
# templates with different per-request IDs collapse into one bucket.
_TRACE_ID = re.compile(r"\b[0-9a-f]{32}\b")
_SPAN_ID = re.compile(r"\b[0-9a-f]{16}\b")
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
_ISO_TS = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?\b"
)
_EPOCH_LARGE = re.compile(r"\b1\d{12,18}\b")  # ms / ns since epoch
_LATENCY_KV = re.compile(r"latency_ms=\d+(?:\.\d+)?")
_IPV4_PORT = re.compile(
    r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{1,5}\b"
)
_IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_PORT_SUFFIX = re.compile(r":\d{4,5}\b")
# Pod hash suffix pattern (k8s replicas like cartservice-7b9c4f8d6-xz9pq).
_POD_HASH_SUFFIX = re.compile(r"-[a-f0-9]{8,10}-[a-z0-9]{5}\b")
# Online Boutique product SKUs are 10-char uppercase alphanumeric tokens
# (e.g. 9SIQT8TOJO, OLJCESPC7Z). They appear in three forms across logs:
#   * /product/SKU            (HTTP path)
#   * product #SKU            (Go error chain — frontend, checkoutservice)
#   * product #"SKU"          (same with quote escape)
# Without stripping, identical "product fetch failed" templates blow up
# into N near-duplicate rows that fill the top-K and crowd out other
# distinct templates from the signature.
_PRODUCT_SKU_PATH = re.compile(r"(/product/)[A-Z0-9]{8,16}\b")
_PRODUCT_SKU_HASH = re.compile(r"(product\s+#\"?)[A-Z0-9]{8,16}(\")?")


def _strip_volatile(text: str) -> str:
    """Remove per-request / per-instance bits before dedup."""
    text = _ISO_TS.sub("<ts>", text)
    text = _TRACE_ID.sub("<tid>", text)
    text = _SPAN_ID.sub("<sid>", text)
    text = _UUID.sub("<uuid>", text)
    text = _EPOCH_LARGE.sub("<epoch>", text)
    text = _LATENCY_KV.sub("latency_ms=<n>", text)
    text = _IPV4_PORT.sub("<ip:port>", text)
    text = _IPV4.sub("<ip>", text)
    text = _PORT_SUFFIX.sub(":<port>", text)
    text = _POD_HASH_SUFFIX.sub("-<pod>", text)
    text = _PRODUCT_SKU_PATH.sub(r"\1<sku>", text)
    text = _PRODUCT_SKU_HASH.sub(r"\1<sku>", text)
    return text


# Field-extractor for .NET's k=v message strings. Captures
# `dep=redis-cart`, `op=AddItem`, etc.
_MSG_KV = re.compile(r"(\w+)=([^\s]+)")


# Top-level keys we may find in Go-style L2 logs and pull into the
# template. Order in this list is irrelevant; the emitted template
# uses the fixed order below.
_STRUCTURED_KEYS: tuple[str, ...] = (
    "dep", "op", "err_class", "err", "peer_service",
    "method", "status_code", "kind", "category", "Category",
    "retry_attempt", "exception",
)


def _normalize_severity(obj: dict[str, Any]) -> str:
    """Pull severity across language conventions."""
    for key in ("severity", "LogLevel", "level", "Level"):
        val = obj.get(key)
        if val:
            return str(val).lower().strip()
    return ""


def _build_template(obj: dict[str, Any]) -> str:
    """Turn one structured log object into a stable, deduplicatable
    engineer-vocabulary template.

    Strategy:
      * Pull canonical fields from the top level (Go services emit
        them there; frontend also emits http.req.method/path).
      * Pull the rich content from BOTH `message` and `error` keys
        — frontend logs have a thin `message="request error"` and the
        full chain in `error`; .NET logs have everything in `Message`.
      * Parse k=v pairs out of the message body too (the .NET pattern).
      * Emit a fixed-order single line, then strip volatile bits.
    """
    msg_short = (
        obj.get("message") or obj.get("Message")
        or obj.get("msg") or obj.get("body") or ""
    )
    msg_short = str(msg_short).strip()
    # `error` (lowercase) is the rich error-chain field on Go HTTP servers
    # (frontend in particular). Include it; otherwise the dedup buckets
    # everything as "request error".
    msg_long = obj.get("error") or obj.get("Error") or ""
    msg_long = str(msg_long).strip()

    fields: dict[str, str] = {}
    for key in _STRUCTURED_KEYS:
        v = obj.get(key)
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            fields[key.lower()] = str(v)
    # frontend HTTP method + path are great discriminators across
    # endpoints — POST /cart/checkout vs GET /product/X.
    for k in ("http.req.method", "http.req.path"):
        v = obj.get(k)
        if v:
            fields[k.replace(".", "_")] = str(v)

    # Parse k=v pairs from the message-short string for .NET style.
    msg_no_kv = msg_short
    if msg_short and "=" in msg_short:
        for m in _MSG_KV.finditer(msg_short):
            k = m.group(1).lower()
            v = m.group(2)
            if k not in fields:
                fields[k] = v
        msg_no_kv = _MSG_KV.sub("", msg_short).strip()

    parts: list[str] = []
    # Lead with categorical-anchor (kind / category) so the most
    # discriminative token is first.
    head = fields.get("kind") or fields.get("category", "")
    if head:
        parts.append(f"kind={head}")
    for key in (
        "dep", "op", "err_class", "err", "peer_service",
        "method", "status_code", "retry_attempt",
        "http_req_method", "http_req_path",
    ):
        if key in fields:
            parts.append(f"{key}={fields[key]}")

    # Include any non-k=v residue of the short message body. Captures
    # both the leading word (.NET: "dep_error") and free-form text.
    if msg_no_kv and len(msg_no_kv) > 3:
        parts.append(msg_no_kv[:100])

    # The rich `error` chain — keep first ~120 chars after stripping
    # volatile bits. This is where frontend lines carry their signal.
    if msg_long:
        parts.append(msg_long[:140])

    if not parts and msg_short:
        parts.append(msg_short[:160])

    return _strip_volatile(" ".join(parts).strip())


def _parse_loki_dump(path: Path) -> list[dict[str, Any]]:
    """Read raw/loki/<window>.json and yield each structured object.

    Skips entries that aren't JSON (e.g. raw .NET stack-trace lines —
    those are caller-info, not the error itself, so dropping them is
    correct).
    """
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[dict[str, Any]] = []
    for sub_key in ("service_window", "service_context"):
        sub = data.get(sub_key)
        if not isinstance(sub, dict):
            continue
        response = sub.get("response") or {}
        result = (response.get("data") or {}).get("result") or []
        for stream in result:
            for value in stream.get("values") or []:
                if not isinstance(value, (list, tuple)) or len(value) < 2:
                    continue
                line = str(value[1])
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    return out


def _count_templates(
    loki_path: Path,
    *,
    max_chars_per_template: int = 220,
) -> Counter[str]:
    """Build a `{template -> count}` map for error/warn lines in one window.

    Shared internals for `extract_log_signature` (top-K in this window)
    and `extract_characteristic_signature` (active-vs-baseline diff).
    Lab-token-bearing templates are dropped here so they cannot leak
    through either entry point.
    """
    counter: Counter[str] = Counter()
    log_objs = _parse_loki_dump(loki_path)
    if not log_objs:
        return counter
    for obj in log_objs:
        if _normalize_severity(obj) not in _ERROR_SEVERITIES:
            continue
        template = _build_template(obj)
        if not template:
            continue
        if len(template) > max_chars_per_template:
            template = template[:max_chars_per_template]
        if find_lab_tokens(template):
            continue
        counter[template] += 1
    return counter


def extract_log_signature(
    loki_path: Path,
    *,
    top_k: int = 10,
    max_chars_per_template: int = 220,
) -> list[str]:
    """Return up to top_k characteristic log templates for one window.

    Templates are ordered by frequency in this window descending.
    Lines containing lab-vocabulary tokens are silently dropped —
    they never enter the signature, satisfying Move A's "every
    persisted line passes through the sanitizer" rule.

    For V2 humanizer use, prefer `signature_for_episode()` which adds
    active-vs-baseline diff scoring + cross-service fallback. This
    plain function remains the fallback when no baseline is available.
    """
    counter = _count_templates(
        loki_path, max_chars_per_template=max_chars_per_template
    )
    return [t for t, _ in counter.most_common(top_k)]


def extract_characteristic_signature(
    active_path: Path,
    baseline_path: Path,
    *,
    top_k: int = 5,
    min_score: float = 2.0,
    min_active_count: int = 2,
    max_chars_per_template: int = 220,
) -> list[tuple[str, float, int, int]]:
    """Return templates in `active` that are characteristic vs `baseline`.

    Score formula: ``(active_count + 1) / (baseline_count + 1)``.
    Smoothing keeps templates absent from baseline from dividing by
    zero, and keeps low-count templates from dominating.

    A template is returned only if:
      * its active count is >= `min_active_count` (drops 1-shot noise)
      * its score is >= `min_score` (drops templates equally present
        in baseline — those are background chatter, not fault signal)

    Returns up to `top_k` tuples of
    ``(template, score, active_count, baseline_count)``, ordered by
    score descending then by active_count descending.

    Empty result is meaningful — it means this window has no
    distinguishing error templates vs the pre-fault baseline (either
    because the fault wasn't error-class on this service, or because
    background error chatter dominates). Callers should use the
    `signature_for_episode()` cross-service fallback before treating
    the ticket as "no log signature".
    """
    active_c = _count_templates(
        active_path, max_chars_per_template=max_chars_per_template
    )
    if not active_c:
        return []
    baseline_c = _count_templates(
        baseline_path, max_chars_per_template=max_chars_per_template
    )
    scored: list[tuple[str, float, int, int]] = []
    for template, a_count in active_c.items():
        if a_count < min_active_count:
            continue
        b_count = baseline_c.get(template, 0)
        score = (a_count + 1) / (b_count + 1)
        if score < min_score:
            continue
        scored.append((template, score, a_count, b_count))
    scored.sort(key=lambda x: (-x[1], -x[2]))
    return scored[:top_k]


def signature_for_episode(
    run_dir: Path,
    episode_id: str,
    components: list[str],
    *,
    top_k: int = 5,
    min_score: float = 2.0,
    min_active_count: int = 2,
) -> tuple[str | None, list[str], str]:
    """Pick the best log signature for an episode across its components.

    Two-pass algorithm:

      1. **Gather diff across all components.** For each component
         with an active+baseline pair, run
         `extract_characteristic_signature`. Collect all surviving
         templates with their (score, active_count) into one pool.
         Sort by score descending, dedup identical templates that
         appear on multiple services, return the top-K. The
         "service_used" returned is whichever component produced the
         top-1 template.
      2. **Plain fallback when no diff hits anywhere.** If pass 1
         returned nothing, walk components in order and return the
         plain top-K from the first component whose active window has
         any error templates. This handles restart / silent-fault
         cases where no template clears the diff bar.

    Picking globally-best diff across components matters in practice:
    `productcatalog-latency` has `checkoutservice` first in components
    with a single low-information plain template (`dep=productcatalog
    op=GetProduct err_class=Unavailable`), but `frontend` further down
    has 5 high-score diff templates with the full user-facing error
    chain. The two-pass approach picks the frontend diff, which is
    strictly more informative for retrieval.

    Returns a tuple ``(service_used, signature_lines, source)`` where:
      * `service_used` is the component name whose dumps produced the
        top-1 template in the result (or the fallback service), or
        `None` if every component was empty
      * `signature_lines` is the list of raw template strings to feed
        to `description_code` and per-step evidence
      * `source` is `"diff"` (preferred) or `"plain_fallback"` (when
        no diff hits anywhere but plain has content) or `"empty"`
    """
    loki_dir = run_dir / "raw" / "loki"

    # Pass 1: gather all diff hits across all components.
    # Each entry: (score, active_count, template, svc).
    pooled: list[tuple[float, int, str, str]] = []
    for svc in components:
        active_path = loki_dir / f"{episode_id}-active_fault-{svc}.json"
        baseline_path = loki_dir / f"{episode_id}-pre_fault_baseline-{svc}.json"
        if not active_path.exists() or not baseline_path.exists():
            continue
        diff = extract_characteristic_signature(
            active_path, baseline_path,
            top_k=top_k, min_score=min_score,
            min_active_count=min_active_count,
        )
        for template, score, a_count, _b_count in diff:
            pooled.append((score, a_count, template, svc))

    if pooled:
        pooled.sort(key=lambda x: (-x[0], -x[1]))
        seen: set[str] = set()
        chosen_templates: list[str] = []
        chosen_svcs: list[str] = []
        for _score, _a_count, template, svc in pooled:
            if template in seen:
                continue
            seen.add(template)
            chosen_templates.append(template)
            chosen_svcs.append(svc)
            if len(chosen_templates) >= top_k:
                break
        primary_svc = chosen_svcs[0] if chosen_svcs else None
        return primary_svc, chosen_templates, "diff"

    # Pass 2: no diff anywhere — fall back to plain top-K from the
    # first component with any error content.
    for svc in components:
        active_path = loki_dir / f"{episode_id}-active_fault-{svc}.json"
        if not active_path.exists():
            continue
        plain = extract_log_signature(active_path, top_k=top_k)
        if plain:
            return svc, plain, "plain_fallback"

    return None, [], "empty"


# ---------------------------------------------------------------------------
# CLI for quick eyeballing
# ---------------------------------------------------------------------------


def _main() -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--loki-path", required=True, type=Path)
    p.add_argument("--top-k", type=int, default=10)
    args = p.parse_args()
    sig = extract_log_signature(args.loki_path, top_k=args.top_k)
    if not sig:
        print("(no signature — no error-level lines in this file)")
        return 1
    for i, line in enumerate(sig, 1):
        print(f"{i:2d}. {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
