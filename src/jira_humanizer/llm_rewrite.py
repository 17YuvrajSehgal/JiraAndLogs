#!/usr/bin/env python3
"""LLM-driven Jira humanizer — Qwen-generated per-issue content.

Goes beyond the template humanizer in `rewrite.py` by asking a local
chat model (via LM Studio's OpenAI-compatible API) to write a unique
description + 3-comment thread per issue. Each ticket reads like an
actual on-call engineer wrote it, not a template fill-in.

The template humanizer in `rewrite.py` remains the deterministic
fallback when LM Studio is unreachable or returns malformed output —
this script just adds the "best-quality, slower" path on top of the
existing scaffolding (label cleanup, name pool, history rewrite).

Cost: ~5s per issue on Qwen 2.5 Coder 14B locally. 48 issues = ~4 min
for v5-quick; ~600 issues = ~50 min for v5-large.

Usage:
    # Single file, rewrite in place with backup
    python -m src.jira_humanizer.llm_rewrite \\
        --in data/runs/<run>/jira_shadow_issues.jsonl --in-place

    # All matching runs under a prefix
    python -m src.jira_humanizer.llm_rewrite \\
        --run-prefix 2026-05-25-dataset-v5-quick --in-place

    # Use a different model
    python -m src.jira_humanizer.llm_rewrite \\
        --in ... --model qwen/qwen2.5-coder-14b --base-url http://localhost:1234

    # Dry-run without LM (uses template fallback for everything)
    python -m src.jira_humanizer.llm_rewrite \\
        --in ... --no-llm --out preview.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Re-use the existing scaffolding
from .rewrite import (
    REPO_ROOT,
    _NAMES,
    _humanize_labels,
    _pick,
    _pick_n_distinct,
    _process_file as _template_process_file,
    _humanize_issue as _template_humanize_issue,
    _SCENARIO_FAMILIES,
)


# ---------------------------------------------------------------------------
# LLM client (uses src/comparison/retrievers.py — already wired for LM Studio)
# ---------------------------------------------------------------------------

# Lazy-import the chat client so importing this module doesn't fail when
# src/comparison isn't on the path (e.g., running stand-alone).
def _chat(base_url: str, model: str, system: str, user: str,
          *, temperature: float = 0.4, max_tokens: int = 800) -> str:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from comparison.retrievers import chat_via_lm_studio
    return chat_via_lm_studio(
        base_url, model,
        [{"role": "system", "content": system},
         {"role": "user", "content": user}],
        temperature=temperature, max_tokens=max_tokens,
    )


_MD_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S | re.I)


def _parse_lm_json(response: str) -> dict | None:
    """Tolerant JSON parser — strips ```json fences and trims."""
    r = response.strip()
    m = _MD_FENCE_RE.match(r)
    if m:
        r = m.group(1).strip()
    try:
        obj = json.loads(r)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are an on-call site reliability engineer writing a real Jira ticket "
    "during an incident. Respond with JSON only — no prose, no markdown "
    "fences. NEVER mention 'synthetic', 'lab', 'research', 'dataset', "
    "'scenario', or any identifier that looks like a UUID, a timestamp, or "
    "a numeric run id. Write the way an engineer would actually type into "
    "Jira at 2am: short, direct, first-person where it fits."
)


def _build_user_prompt(
    family: str,
    severity: str | None,
    services: list[str],
    summary_hint: str,
    primary_service: str,
) -> str:
    services_csv = ", ".join(services) if services else primary_service
    sev = severity or "unknown"
    family_hint = _FAMILY_BRIEFS.get(family, "")
    return (
        f"Incident context (DO NOT echo this back literally):\n"
        f"- Severity: {sev}\n"
        f"- Affected services: {services_csv}\n"
        f"- Primary failing service: {primary_service}\n"
        f"- Symptom: {family_hint or family}\n"
        f"- Summary hint (you may rephrase): {summary_hint}\n"
        f"\n"
        f"Write the Jira ticket. Output strict JSON with exactly these keys:\n"
        f"  description: 1-3 sentences in the FIRST person (\"I see\", "
        f"\"we've got\", etc.), describing what's broken and what you're "
        f"about to do. NO metadata, NO IDs, NO times.\n"
        f"  comments: a list of EXACTLY 3 strings, simulating different "
        f"team members commenting over the incident lifetime:\n"
        f"    1st: someone picks it up / asks a question / shares first "
        f"observations\n"
        f"    2nd: investigation finding / hypothesis / coordination with "
        f"another team\n"
        f"    3rd: resolution + next steps (fix deployed / rollback / "
        f"closing with follow-up filed)\n"
        f"  Each comment should be 1-2 sentences, conversational, like "
        f"Slack-style chat. NO log queries, NO trace IDs, NO metric names.\n"
        f"\n"
        f"Example shape (different content):\n"
        f'{{"description": "Payment service is dropping connections. '
        f"Customers can't complete checkout — we've got tickets piling up "
        f'in support. Looking at the pod logs now.", '
        f'"comments": ["Picked up. Anyone touched payments today?", '
        f'"Found a connection pool exhaustion — last config push bumped '
        f"max_idle too low. Reverting now.\", "
        f'"Rolled back. Checkout volume back to normal. Will file a follow-up '
        f'for the config validation gap."]}}'
    )


# Per-family English summaries Qwen uses as ground truth for what to write
# about. Keeps the LLM from inventing the wrong fault shape.
_FAMILY_BRIEFS: dict[str, str] = {
    "cart-redis":
        "the cart store backend (Redis) is unhealthy — connection timeouts or "
        "intermittent failures; customers see cart-add errors and lost carts",
    "payment-outage":
        "payment service is failing — charge attempts return errors, customers "
        "cannot complete purchases, revenue impact",
    "currency-outage":
        "currency conversion service is down — prices may display wrong or "
        "international checkout breaks",
    "shipping-outage":
        "shipping quote service is unavailable — customers see 'shipping "
        "unavailable' at checkout, conversion drops",
    "checkout-outage":
        "checkout / order placement service is failing end-to-end — no orders "
        "completing, P0 revenue issue",
    "checkout-restart":
        "checkout service pods restarted — brief downtime, some in-flight "
        "orders may have dropped, need to find restart cause",
    "productcatalog-outage":
        "product catalog service is down or returning 503 — product pages "
        "broken, downstream services impacted",
    "productcatalog-latency":
        "product catalog response times are degraded — pages load slowly, "
        "checkout flow sluggish, recent deploy possibly to blame",
    "recommendation-outage":
        "recommendations API failing — 'you might also like' is empty; "
        "lower priority than checkout but impacts conversion",
    "ad-outage":
        "ad service not serving — banner slots empty; small revenue impact",
    "email-outage":
        "email service queuing not sending — order confirmation emails not "
        "going out, risk of duplicate orders from confused customers",
    "frontend-restart":
        "frontend pods cycled — brief HTTP 502s; need to find rollout or "
        "crash cause",
    "frontend-traffic-pressure":
        "frontend under traffic load — latency holding but error rate up; "
        "may need scale-out",
    "post-deploy-churn":
        "brief errors right after a deploy — usually transient connection "
        "churn that resolves itself within a minute",
    "recovered-in-window":
        "saw a brief blip but it self-recovered before customer impact; "
        "tracking for awareness",
    "single-pod-restart-healthy-replication":
        "one pod restarted but replicas absorbed traffic — no customer impact, "
        "filing as noise",
    "third-party-blip":
        "upstream third-party dependency had a brief failure; recovered "
        "quickly, no customer-visible impact",
    "scheduled-job-spike":
        "traffic spike on the service tied to a scheduled batch job — not "
        "real user traffic, no production impact",
    "latency-near-miss-partial-recovery":
        "latency wobble — self-recovered before paging; tracking",
    "flapping-pod":
        "service pod restarting repeatedly in quick succession — smells like "
        "a crash loop, need to find exit reason",
    "slow-leak-saturation":
        "service memory climbing all day, OOM looks imminent — suspect leak, "
        "investigating recent code changes",
    "baseline-normal":
        "routine health check — no issue, closing",
}


# ---------------------------------------------------------------------------
# Main rewriter
# ---------------------------------------------------------------------------


def _humanize_issue_with_llm(
    issue: dict[str, Any], base_url: str, model: str
) -> tuple[dict[str, Any], bool]:
    """Returns (humanized_issue, used_llm). used_llm=False means we fell
    back to template humanizer (LM error / malformed JSON / etc.)."""
    metadata = issue.get("metadata") or {}
    episode_id = issue.get("incident_episode_id") or issue.get("jira_shadow_issue_id") or ""
    components = list(metadata.get("components") or [])
    primary_service = components[0] if components else "the service"
    severity = (metadata.get("priority") or "").lower() if metadata.get("priority") else None
    summary_hint = metadata.get("summary") or ""

    # Resolve family the same way as the template humanizer
    family = None
    for lbl in metadata.get("labels") or []:
        if lbl.startswith("scenario-"):
            sid = lbl[len("scenario-"):]
            family = _SCENARIO_FAMILIES.get(sid)
            if family:
                break
    if family is None:
        family = "recovered-in-window"

    user_prompt = _build_user_prompt(
        family, severity, components, summary_hint, primary_service
    )

    response = _chat(base_url, model, _SYSTEM, user_prompt)
    if response.startswith("__ERROR__"):
        # Fall back to template humanizer
        return _template_humanize_issue(issue), False
    parsed = _parse_lm_json(response)
    if not parsed:
        return _template_humanize_issue(issue), False
    description = parsed.get("description")
    comments = parsed.get("comments")
    if not (isinstance(description, str) and isinstance(comments, list)
            and len(comments) == 3 and all(isinstance(c, str) for c in comments)):
        return _template_humanize_issue(issue), False

    # Apply the existing label cleanup + name assignment from the template
    # humanizer, then swap in LLM-generated text
    base = _template_humanize_issue(issue)
    new_metadata = dict(base["metadata"])
    new_metadata["description"] = description.strip()

    # Build conversational comments with names + timestamps
    try:
        start = datetime.fromisoformat(metadata.get("created_at", "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        start = datetime.now(timezone.utc)
    names = _pick_n_distinct(episode_id + "llm-comment-authors", _NAMES, 3)
    new_comments = []
    for i, (name, body) in enumerate(zip(names, comments)):
        new_comments.append({
            "author": name,
            "body": body.strip(),
            "created": (start + timedelta(minutes=6 + i * 18)).isoformat(),
        })
    new_metadata["comments_body"] = "\n\n---\n\n".join(
        f"[{c['author']} @ {c['created'][:16]}]\n{c['body']}"
        for c in new_comments
    )
    new_metadata["comments_id"] = [
        f"{issue.get('jira_issue_key','')}-c{i+1}" for i in range(len(new_comments))
    ]

    # Replace activity events of type "comment" with our new ones
    new_activity = []
    for day in base["activity"]:
        new_events = []
        comment_idx = 0
        for ev in day["events"]:
            if ev.get("type") == "comment" and comment_idx < len(new_comments):
                c = new_comments[comment_idx]
                new_events.append({
                    **ev,
                    "author": c["author"],
                    "body": c["body"],
                    "timestamp": c["created"],
                    "created": c["created"],
                    "description": f"{c['author']} commented on {issue.get('jira_issue_key','')}",
                })
                comment_idx += 1
            else:
                new_events.append(ev)
        new_activity.append({**day, "events": new_events})

    base["metadata"] = new_metadata
    base["activity"] = new_activity
    return base, True


def _process_file(
    path: Path, *, in_place: bool, out_path: Path | None,
    base_url: str, model: str, use_llm: bool,
) -> tuple[int, int, int]:
    """Returns (issues_read, issues_written, llm_used)."""
    issues = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                issues.append(json.loads(line))

    rewritten = []
    n_llm = 0
    t0 = time.time()
    for i, issue in enumerate(issues, start=1):
        if use_llm:
            new_issue, used_llm = _humanize_issue_with_llm(issue, base_url, model)
            if used_llm:
                n_llm += 1
        else:
            new_issue = _template_humanize_issue(issue)
            used_llm = False
        rewritten.append(new_issue)
        if i % 5 == 0:
            elapsed = time.time() - t0
            eta = (elapsed / i) * (len(issues) - i)
            print(
                f"    [{i}/{len(issues)}] elapsed={elapsed:.0f}s eta={eta:.0f}s "
                f"llm_used={n_llm}",
                file=sys.stderr,
            )

    if in_place:
        backup = path.with_suffix(path.suffix + ".pre-humanize.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        target = path
    else:
        target = out_path or path

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        for i in rewritten:
            f.write(json.dumps(i, ensure_ascii=False) + "\n")
    return len(issues), len(rewritten), n_llm


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--in", dest="in_path", help="Single jsonl to rewrite")
    src_group.add_argument("--run-prefix", help="Run prefix")
    parser.add_argument("--runs-root", default=str(REPO_ROOT / "data" / "runs"))
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--out", help="When not --in-place, output path")
    parser.add_argument("--base-url", default="http://localhost:1234")
    parser.add_argument("--model", default="qwen/qwen2.5-coder-14b")
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LM calls entirely (use template fallback for everything)",
    )
    args = parser.parse_args()

    targets: list[Path] = []
    if args.in_path:
        targets.append(Path(args.in_path))
    else:
        runs_root = Path(args.runs_root)
        for run_dir in sorted(runs_root.iterdir()):
            if not run_dir.is_dir() or not run_dir.name.startswith(args.run_prefix):
                continue
            jsonl = run_dir / "jira_shadow_issues.jsonl"
            if jsonl.exists():
                targets.append(jsonl)

    if not targets:
        print("No jsonl files matched.", file=sys.stderr)
        return 2

    total_read = total_written = total_llm = 0
    for t in targets:
        if not t.exists() or t.stat().st_size == 0:
            print(f"  SKIP empty/missing: {t}", file=sys.stderr)
            continue
        out = Path(args.out) if (args.out and not args.in_place) else None
        n_read, n_wrote, n_llm = _process_file(
            t, in_place=args.in_place, out_path=out,
            base_url=args.base_url, model=args.model,
            use_llm=not args.no_llm,
        )
        total_read += n_read
        total_written += n_wrote
        total_llm += n_llm
        rel = t.relative_to(REPO_ROOT) if REPO_ROOT in t.parents else t
        print(f"  rewrote {n_wrote}/{n_read} ({n_llm} via LLM) from {rel}", file=sys.stderr)

    print(
        f"\nDone. {total_written} issues rewritten across {len(targets)} files "
        f"({total_llm} via LLM, {total_written - total_llm} via template fallback).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
