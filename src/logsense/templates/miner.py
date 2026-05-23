"""Drain-lite template mining.

Real Drain builds a token-prefix tree per length bucket and merges similar
lines. For a v4-pilot-sized dataset (576 windows, hundreds of unique lines
each) that's overkill - regex masking + length bucketing gives us templates
stable enough for fingerprinting and BM25 retrieval, in maybe 60 lines of
code.

Masking pass (order matters - more specific first):
  <UUID>     - 8-4-4-4-12 hex
  <HEX>      - 0x-prefix or >=8 hex chars
  <IP>       - dotted-quad with optional :port
  <TS>       - ISO-8601-ish or epoch-millis timestamps
  <DUR>      - "123ms" / "45s" / "1.2h"
  <PATH>     - unix or windows path with extension or 2+ separators
  <NUM>      - any standalone integer or decimal of length >=2
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from ..data.schema import LogLine


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<HEX>"),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<HEX>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    (re.compile(r"\bhttps?://[^\s\"'<>]+"), "<URL>"),
    (re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]+)?\b"), "<IP>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"), "<TS>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:ns|us|ms|s|m|h)\b"), "<DUR>"),
    (re.compile(r"(?:[A-Za-z]:)?[\\/](?:[\w.-]+[\\/])+[\w.-]+(?::\d+)?"), "<PATH>"),
    # Quoted string literals are usually values, not the template
    (re.compile(r'"[^"]{1,200}"'), '"<STR>"'),
    (re.compile(r"'[^']{1,200}'"), "'<STR>'"),
    (re.compile(r"\b\d{2,}\b"), "<NUM>"),
]
_WHITESPACE_RE = re.compile(r"\s+")
_LEADING_BRACKET_RE = re.compile(r"^\s*(?:\[[^\]]+\]\s*)+")


_JSON_MESSAGE_KEYS = ("message", "msg", "log", "event", "body")


def _extract_message_from_json(body: str) -> str | None:
    """If body is a JSON object, return its message-like field (or a short
    join of its values). Otherwise None."""
    s = body.strip()
    if not s or s[0] != "{":
        return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    for key in _JSON_MESSAGE_KEYS:
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # No canonical message field - synthesize a short fingerprint from the
    # non-timestamp string values so the template still reflects content.
    pieces: list[str] = []
    for k, v in obj.items():
        if k in {"timestamp", "time", "ts", "@timestamp"}:
            continue
        if isinstance(v, (str, int, float, bool)) and len(str(v)) < 120:
            pieces.append(f"{k}={v}")
    return " ".join(pieces) if pieces else None


def mask_line(body: str, *, strip_leading_brackets: bool = True) -> str:
    """Turn a raw log body into a template string.

    For JSON-shaped bodies, mask only the message field instead of the
    whole serialized object (otherwise the JSON braces and key names
    swamp the template inventory).
    """
    if not body:
        return ""
    s = body.strip()
    # JSON-aware: pull the message field out before masking
    extracted = _extract_message_from_json(s)
    if extracted is not None:
        s = extracted
    if strip_leading_brackets:
        s = _LEADING_BRACKET_RE.sub("", s).strip()
    for pat, repl in _PATTERNS:
        s = pat.sub(repl, s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    if len(s) > 240:
        s = s[:240] + "..."
    return s


def mine_templates(lines: Iterable[LogLine]) -> Counter[str]:
    """Return template -> count over a stream of LogLine."""
    out: Counter[str] = Counter()
    for ln in lines:
        out[mask_line(ln.body)] += 1
    return out


@dataclass
class TemplateMiner:
    """Stateful miner that keeps a global template inventory across windows.

    Used during training to decide which templates form the fingerprint
    vocabulary (top-K most frequent templates across the train split).
    """

    global_counts: Counter[str] = field(default_factory=Counter)
    template_to_severity_mode: dict[str, Counter[str]] = field(default_factory=dict)

    def fit_line(self, line: LogLine) -> str:
        tmpl = mask_line(line.body)
        if not tmpl:
            return ""
        self.global_counts[tmpl] += 1
        bucket = self.template_to_severity_mode.setdefault(tmpl, Counter())
        bucket[line.severity] += 1
        return tmpl

    def fit_lines(self, lines: Iterable[LogLine]) -> None:
        for ln in lines:
            self.fit_line(ln)

    def vocabulary(self, top_k: int) -> list[str]:
        return [tmpl for tmpl, _ in self.global_counts.most_common(top_k)]

    def severity_of(self, template: str) -> str:
        bucket = self.template_to_severity_mode.get(template)
        if not bucket:
            return "unknown"
        return bucket.most_common(1)[0][0]
