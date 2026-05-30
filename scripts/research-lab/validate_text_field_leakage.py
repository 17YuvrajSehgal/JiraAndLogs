#!/usr/bin/env python3
"""Corpus-wide text-field leakage canary.

Sibling of validate_run_feature_distribution.py. That validator scans
numeric features for label-correlation leaks; this one scans **text
fields** for substring-token leaks.

Why this exists (per ML-NEW-IDEAS.MD Move C and todo-v5available.md
§3.1): a window's evidence_text can contain
`"scenario-cart-redis-degradation-critical"` and the numeric canary
won't notice — because correlated TEXT tokens don't show up in
numeric feature distributions. A pipeline that trains on such text
silently inflates PR-AUC on the lab while breaking on real data.

Scopes scanned (any/all via CLI flags):
  * `global-triage-examples.jsonl` -> `triage_evidence_text`
  * Humanized timeline JSONL -> every step's `text` field
  * Legacy `jira-memory-corpus.jsonl` -> `memory_text` (for baseline)

Bans (composed):
  - All sanitizer tokens (prefixes, words, scenario taxonomy)
  - Window-type strings: `active_fault`, `pre_fault_baseline`,
    `recovery_window`, `observation_window` — these never appear by
    chance in real production logs
  - Per-request id regexes — trace_id (32-hex), span_id (16-hex)
    that v5-quick caught dominating embeddings

Two-tier verdict:
  * Hard-ban tokens (scenario taxonomy, window types) → fail on >0
    occurrences. Zero tolerance.
  * Soft-ban tokens (lab words, prefixes) → warn on any occurrence;
    fail when rate > --threshold (default 1% of windows).

Outputs:
  * stdout: human-readable summary
  * <output-dir>/text-leakage-report.json: full per-token stats
  * <output-dir>/text-leakage-report.md: markdown report

Exit code: 0 = PASS, 1 = FAIL.

Usage:
    python scripts/research-lab/validate_text_field_leakage.py \\
        --global-id 2026-05-25-dataset-v5-large-global \\
        --humanized-subdir bulk-20260529 \\
        --scan-legacy
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

# Reuse the sanitizer's banned-token vocabulary as the base set.
from jira_humanizer.sanitizer import (  # noqa: E402
    SANITIZER_VERSION,
    _LEAK_PREFIXES,
    _LEAK_WORDS,
    _TAXONOMY_TOKENS,
)


CANARY_VERSION = "v1.0.0"


# ---------------------------------------------------------------------------
# Banned-token catalog (composed from sanitizer + extras for this validator)
# ---------------------------------------------------------------------------


# These are LAB-ONLY strings that should never appear in production-style
# evidence text. ZERO tolerance — any occurrence is a hard fail because
# none of them can plausibly arise organically.
_HARD_BAN_TOKENS: tuple[str, ...] = (
    "active_fault",
    "pre_fault_baseline",
    "recovery_window",
    "observation_window",
) + tuple(_TAXONOMY_TOKENS)


# Lab-vocabulary prefixes. Hard-ban as well — these never appear in real
# Jira / log text outside the lab harness.
_HARD_BAN_PREFIXES: tuple[str, ...] = _LEAK_PREFIXES


# Lab-vocabulary whole words like "fault", "injected". Real engineers
# DO say "fault" naturally, so we treat these as SOFT bans: warn on any
# occurrence, fail only when the rate exceeds --threshold (default 1%).
_SOFT_BAN_WORDS: tuple[str, ...] = _LEAK_WORDS


# Per-request id regexes. Each window's raw telemetry has trace IDs
# (W3C-format 32-hex) and span IDs (16-hex). If they show up in
# evidence_text or humanized memory text, the model can use them as a
# per-window oracle (every window has a unique pattern). Hard-ban.
_TRACE_ID_RE = re.compile(r"\b[0-9a-f]{32}\b")
_SPAN_ID_RE = re.compile(r"\b[0-9a-f]{16}\b")


def _compile_hard_substring_re() -> re.Pattern[str]:
    """Single regex matching any hard-banned substring or prefix.

    The hard pool is fixed at startup so we pay the compile cost once.
    """
    parts = [re.escape(p) for p in _HARD_BAN_PREFIXES]
    parts.extend(re.escape(t) for t in _HARD_BAN_TOKENS if t)
    return re.compile("|".join(parts), re.IGNORECASE)


def _compile_soft_word_re() -> re.Pattern[str]:
    return re.compile(
        r"\b(" + "|".join(re.escape(w) for w in _SOFT_BAN_WORDS) + r")\b",
        re.IGNORECASE,
    )


_HARD_SUBSTRING_RE = _compile_hard_substring_re()
_SOFT_WORD_RE = _compile_soft_word_re()


# ---------------------------------------------------------------------------
# Scan one text blob
# ---------------------------------------------------------------------------


@dataclass
class TextHit:
    """A single occurrence of a banned token inside one source text."""

    token: str
    severity: str  # "hard" | "soft" | "id"
    sample_context: str   # the surrounding 60 chars for diagnosis


def scan_text(text: str) -> list[TextHit]:
    """Return every banned-token occurrence in `text`.

    A single window can have multiple hits — we keep them all so the
    rollup can compute per-token rates and surface representative
    contexts.
    """
    if not text:
        return []
    hits: list[TextHit] = []
    lowered = text.lower()

    for m in _HARD_SUBSTRING_RE.finditer(text):
        token = m.group(0).lower()
        start = max(0, m.start() - 30)
        end = min(len(text), m.end() + 30)
        hits.append(TextHit(
            token=token,
            severity="hard",
            sample_context=text[start:end].replace("\n", " "),
        ))
    for m in _SOFT_WORD_RE.finditer(text):
        token = m.group(0).lower()
        start = max(0, m.start() - 30)
        end = min(len(text), m.end() + 30)
        hits.append(TextHit(
            token=token,
            severity="soft",
            sample_context=text[start:end].replace("\n", " "),
        ))
    for m in _TRACE_ID_RE.finditer(lowered):
        start = max(0, m.start() - 30)
        end = min(len(text), m.end() + 30)
        hits.append(TextHit(
            token="<trace_id-pattern>",
            severity="id",
            sample_context=text[start:end].replace("\n", " "),
        ))
    for m in _SPAN_ID_RE.finditer(lowered):
        # span_id matches a substring of trace_id, so a window with
        # trace_ids also gets a span_id hit. That's OK — they roll up
        # as separate findings.
        start = max(0, m.start() - 30)
        end = min(len(text), m.end() + 30)
        hits.append(TextHit(
            token="<span_id-pattern>",
            severity="id",
            sample_context=text[start:end].replace("\n", " "),
        ))
    return hits


# ---------------------------------------------------------------------------
# Scope-level rollups — one per source (legacy evidence, humanized, jira)
# ---------------------------------------------------------------------------


@dataclass
class ScopeStats:
    name: str
    n_units: int = 0          # rows scanned (windows / tickets / etc)
    n_with_any_hit: int = 0
    hits_per_token: Counter[str] = field(default_factory=Counter)
    units_per_token: Counter[str] = field(default_factory=Counter)
    sample_contexts: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    severity_of_token: dict[str, str] = field(default_factory=dict)


def _accumulate(scope: ScopeStats, hits: list[TextHit]) -> None:
    scope.n_units += 1
    if not hits:
        return
    scope.n_with_any_hit += 1
    seen_in_this_unit: set[str] = set()
    for h in hits:
        scope.hits_per_token[h.token] += 1
        scope.severity_of_token[h.token] = h.severity
        if h.token not in seen_in_this_unit:
            scope.units_per_token[h.token] += 1
            seen_in_this_unit.add(h.token)
            # Keep up to 3 distinct sample contexts per token
            if len(scope.sample_contexts[h.token]) < 3:
                scope.sample_contexts[h.token].append(h.sample_context)


def _verdict(scope: ScopeStats, *, soft_threshold: float) -> tuple[str, list[dict[str, Any]]]:
    """Return ("pass" | "fail", findings).

    Hard tokens fail on any occurrence. Soft tokens fail when rate
    over n_units exceeds soft_threshold.
    """
    findings: list[dict[str, Any]] = []
    fail = False
    for token, n_units_with in scope.units_per_token.items():
        rate = n_units_with / max(1, scope.n_units)
        sev = scope.severity_of_token.get(token, "hard")
        verdict = "warn"
        if sev in ("hard", "id"):
            verdict = "fail"
            fail = True
        elif sev == "soft" and rate > soft_threshold:
            verdict = "fail"
            fail = True
        findings.append({
            "token": token,
            "severity": sev,
            "verdict": verdict,
            "n_units_with_token": n_units_with,
            "n_total_units": scope.n_units,
            "rate": round(rate, 6),
            "n_total_hits": scope.hits_per_token[token],
            "sample_contexts": scope.sample_contexts[token][:3],
        })
    findings.sort(
        key=lambda f: (
            0 if f["verdict"] == "fail" else 1,
            -f["rate"],
        ),
    )
    return ("fail" if fail else "pass", findings)


# ---------------------------------------------------------------------------
# Per-source scanners
# ---------------------------------------------------------------------------


def scan_global_examples(path: Path) -> ScopeStats:
    """Walk `triage_evidence_text` for every row."""
    scope = ScopeStats(name="triage_evidence_text")
    if not path.exists():
        return scope
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = row.get("triage_evidence_text") or ""
            _accumulate(scope, scan_text(text))
    return scope


def scan_humanized_timeline(path: Path) -> ScopeStats:
    """Walk every step's text. Each step counts as one unit so the
    per-step leak rate is well-defined."""
    scope = ScopeStats(name="humanized_timeline_step_text")
    if not path.exists():
        return scope
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ticket = json.loads(line)
            except json.JSONDecodeError:
                continue
            for step in ticket.get("timeline") or []:
                text = step.get("text") or ""
                _accumulate(scope, scan_text(text))
    return scope


def scan_legacy_jira(path: Path) -> ScopeStats:
    """Baseline: scan the original Jira corpus so we can compare to the
    humanized corpus and quantify the *delta*."""
    scope = ScopeStats(name="legacy_jira_memory_text")
    if not path.exists():
        return scope
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = row.get("memory_text") or ""
            _accumulate(scope, scan_text(text))
    return scope


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _render_md(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Text-field leakage canary report",
        "",
        f"Generated: {report['generated_at']}",
        f"Soft-token rate threshold: {report['soft_threshold']:.4f}",
        f"Overall verdict: **{report['overall_verdict'].upper()}**",
        "",
    ]
    for scope_name, scope_data in report["scopes"].items():
        lines.append(f"## {scope_name}")
        lines.append("")
        lines.append(
            f"- units scanned: {scope_data['n_units']}  "
            f"units with any hit: {scope_data['n_with_any_hit']}"
        )
        baseline_note = (
            " _(baseline-only — informational; does not affect overall verdict)_"
            if scope_data.get("is_baseline_only") else ""
        )
        lines.append(f"- verdict: **{scope_data['verdict'].upper()}**{baseline_note}")
        lines.append("")
        if not scope_data["findings"]:
            lines.append("No banned tokens detected.")
            lines.append("")
            continue
        lines.append(
            "| Verdict | Severity | Token | Units w/ token | Rate | Total hits |"
        )
        lines.append("| --- | --- | --- | ---: | ---: | ---: |")
        for f in scope_data["findings"]:
            lines.append(
                f"| {f['verdict']} | {f['severity']} | `{f['token']}` | "
                f"{f['n_units_with_token']} / {f['n_total_units']} | "
                f"{f['rate']:.4%} | {f['n_total_hits']} |"
            )
        lines.append("")
        lines.append("### Sample contexts (first 3 per token)")
        lines.append("")
        for f in scope_data["findings"][:10]:
            if not f["sample_contexts"]:
                continue
            lines.append(f"- `{f['token']}`:")
            for ctx in f["sample_contexts"]:
                ctx_short = ctx[:120].replace("`", "'")
                lines.append(f"  - `…{ctx_short}…`")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--global-id",
        default="2026-05-25-dataset-v5-large-global",
        help="Global derived dataset id (under data/derived/global/).",
    )
    p.add_argument(
        "--derived-root",
        default=str(_REPO_ROOT / "data" / "derived" / "global"),
        help="Root of data/derived/global/.",
    )
    p.add_argument(
        "--humanized-subdir",
        default=None,
        help=("Optional: subdirectory under jira-shadow-humanized-v1/ "
              "containing timeline.jsonl. If omitted, humanized scan is "
              "skipped."),
    )
    p.add_argument(
        "--scan-legacy",
        action="store_true",
        help="Also scan the legacy jira-memory-corpus.jsonl for baseline.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.01,
        help="Soft-token rate threshold (fraction of units). Default 0.01 = 1%%.",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help=("Where to write the JSON + MD reports. Defaults to "
              "<global-dir>/text-leakage-report/."),
    )
    return p.parse_args()


def main() -> int:
    import datetime
    args = _parse_args()

    global_dir = Path(args.derived_root) / args.global_id
    if not global_dir.exists():
        print(f"ERROR: global derived dir not found: {global_dir}", file=sys.stderr)
        return 2

    examples_path = global_dir / "global-triage-examples.jsonl"
    if not examples_path.exists():
        print(f"ERROR: required input missing: {examples_path}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir) if args.output_dir else global_dir / "text-leakage-report"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[canary] scanning triage_evidence_text in {examples_path.name} ...",
          file=sys.stderr)
    scopes = {"triage_evidence_text": scan_global_examples(examples_path)}

    if args.humanized_subdir:
        humanized_path = (
            global_dir / "jira-shadow-humanized-v1" / args.humanized_subdir / "timeline.jsonl"
        )
        if humanized_path.exists():
            print(f"[canary] scanning humanized timeline at {humanized_path} ...",
                  file=sys.stderr)
            scopes["humanized_timeline_step_text"] = scan_humanized_timeline(humanized_path)
        else:
            print(f"[canary] WARNING: humanized timeline not found at {humanized_path}",
                  file=sys.stderr)

    if args.scan_legacy:
        legacy_path = global_dir / "jira-memory-corpus.jsonl"
        if legacy_path.exists():
            print(f"[canary] scanning legacy {legacy_path.name} ...", file=sys.stderr)
            scopes["legacy_jira_memory_text"] = scan_legacy_jira(legacy_path)

    # The legacy scope is by-design contaminated — it's the corpus the
    # humanizer replaces. Scanning it is diagnostic: we want the report
    # to show the delta, not to count its 100%-failure against the
    # overall production-facing verdict.
    BASELINE_SCOPES = {"legacy_jira_memory_text"}

    overall_fail = False
    report_scopes: dict[str, dict[str, Any]] = {}
    for name, scope in scopes.items():
        verdict, findings = _verdict(scope, soft_threshold=args.threshold)
        is_baseline = name in BASELINE_SCOPES
        if verdict == "fail" and not is_baseline:
            overall_fail = True
        report_scopes[name] = {
            "n_units": scope.n_units,
            "n_with_any_hit": scope.n_with_any_hit,
            "verdict": verdict,
            "is_baseline_only": is_baseline,
            "findings": findings,
        }

    report = {
        "validator": "validate_text_field_leakage.py",
        "validator_version": CANARY_VERSION,
        "sanitizer_version": SANITIZER_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "global_id": args.global_id,
        "soft_threshold": args.threshold,
        "n_hard_ban_tokens": len(set(_HARD_BAN_TOKENS) | set(_HARD_BAN_PREFIXES)),
        "n_soft_ban_words": len(_SOFT_BAN_WORDS),
        "overall_verdict": "fail" if overall_fail else "pass",
        "scopes": report_scopes,
    }

    json_path = output_dir / "text-leakage-report.json"
    md_path = output_dir / "text-leakage-report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")

    # Human-readable stdout summary
    print()
    print(f"=== Text-field leakage canary: {report['overall_verdict'].upper()} ===")
    for name, scope_data in report_scopes.items():
        tag = "  [baseline]" if scope_data.get("is_baseline_only") else ""
        print(f"  {name}: {scope_data['verdict']}{tag}  "
              f"units={scope_data['n_units']}  "
              f"units_with_any_hit={scope_data['n_with_any_hit']}  "
              f"distinct_tokens={len(scope_data['findings'])}")
        for f in scope_data["findings"][:8]:
            print(
                f"    [{f['verdict']}] {f['severity']:4s} `{f['token']}` "
                f"rate={f['rate']:.4%}  units={f['n_units_with_token']}/{f['n_total_units']}"
            )
        if len(scope_data["findings"]) > 8:
            print(f"    ... (+{len(scope_data['findings'])-8} more — see {md_path})")
    print()
    print(f"json: {json_path}")
    print(f"md:   {md_path}")
    return 0 if not overall_fail else 1


if __name__ == "__main__":
    sys.exit(main())
