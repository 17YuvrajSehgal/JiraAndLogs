#!/usr/bin/env python3
"""Rewrite synthetic Jira shadow issues so they read like real human tickets.

The original generator (scripts/research-lab/generate-shadow-jira-issues.ps1)
dumps lab metadata into user-visible fields: the description includes
`Dataset run`, `Episode`, full telemetry window IDs, alert fingerprints,
and trace IDs; the single comment body includes raw LogQL/PromQL queries
and a comma-separated trace-ID list; labels include
`synthetic-incident`, `telemetry-linked`, `dataset-<run-id>`, and
`scenario-<scenario-id>`.

None of that is what a human writes. Any corporate reviewer reading these
tickets would (correctly) reject them as obviously synthetic.

This rewriter fixes existing jira_shadow_issues.jsonl files in place
(with backup) so the same memory corpus can be reused without
re-collecting telemetry. It:

  * REPLACES description with a short human-style narrative templated
    by scenario_family + affected_service. No lab metadata, no IDs.
  * REPLACES the single mechanical comment with 2-4 conversational
    multi-author comments referencing the symptom in natural language.
  * STRIPS lab-only labels (dataset-*, scenario-*, synthetic-incident,
    telemetry-linked, severity-*, root-*) and replaces with semantic
    labels (bug, production, customer-impact, etc.).
  * REASSIGNS reporter/assignee from a fictional human name pool
    (deterministic by episode_id so repeat runs give the same names).
  * REGENERATES activity events so the discussion timeline reads
    naturally — 2-3 humans collaborating over an incident.
  * KEEPS the telemetry_links sibling intact — that field is the
    retrieval ground truth and is not user-visible in real Jira.

Usage:
    # Single file, rewrite in place with backup
    python -m src.jira_humanizer.rewrite \\
        --in data/runs/<run-id>/jira_shadow_issues.jsonl --in-place

    # Whole prefix (every run under the prefix)
    python -m src.jira_humanizer.rewrite \\
        --run-prefix 2026-05-25-dataset-v5-quick \\
        --runs-root data/runs --in-place

    # Output to a separate file for diffing
    python -m src.jira_humanizer.rewrite \\
        --in data/runs/<run-id>/jira_shadow_issues.jsonl \\
        --out /tmp/humanized.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# Re-use the canonical scenario_id -> family taxonomy so descriptions
# match the actual fault shape, not just a substring guess.
sys.path.insert(0, str(REPO_ROOT / "scripts" / "research-lab"))
try:
    from triage_labels import SCENARIO_FAMILIES as _SCENARIO_FAMILIES
except ImportError:
    _SCENARIO_FAMILIES = {}


# ---------------------------------------------------------------------------
# Name pool — fictional but realistic-sounding
# ---------------------------------------------------------------------------

_NAMES: tuple[str, ...] = (
    "Sarah Chen", "Marcus Williams", "Priya Patel", "Diego Hernandez",
    "Emma Schmidt", "Alex Tanaka", "Maya Johnson", "Wei Zhang",
    "Olivia Brennan", "Raj Kumar", "Sofia Rossi", "James O'Connor",
    "Ananya Gupta", "Carlos Mendes", "Hannah Yoon", "Tom Fitzgerald",
    "Aisha Rahman", "Liam Walsh", "Mei Lin", "Daniel Vasquez",
    "Lena Kowalski", "Noah Becker", "Zara Khalil", "Ben Carlsson",
    "Naomi Cohen", "Felipe Souza",
)


def _pick(seed: str, options: list | tuple) -> Any:
    """Deterministic pick from a list given a seed string. Same seed gives
    same result across runs — important for reproducibility when we re-run
    the humanizer."""
    h = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return options[h % len(options)]


def _pick_n_distinct(seed: str, options: tuple, n: int) -> list:
    """Deterministic pick of N distinct values."""
    rng = random.Random(seed)
    pool = list(options)
    rng.shuffle(pool)
    return pool[:n]


# ---------------------------------------------------------------------------
# Description templates — keyed by scenario_family
# ---------------------------------------------------------------------------
#
# Each family has 3-4 description variants. Picked deterministically by
# episode_id so repeat runs give the same description. Placeholders are
# filled at render time:
#   {service}      = primary affected service
#   {services_csv} = comma-list of affected services
#   {ago}          = human time-ago phrasing ("10 min ago", "this afternoon")
#

_DESCRIPTION_TEMPLATES: dict[str, tuple[str, ...]] = {
    "cart-redis": (
        "Our cart store backend (Redis) started failing about {ago}. "
        "Several customers reported 'could not add to cart' errors. "
        "{service} is the immediate caller — investigating whether it's "
        "a Redis instance issue or our connection-pool config.",
        "Cart errors spiking. {service} can't reach redis-cart. Pages "
        "still load but the cart icon hangs and orders cannot complete. "
        "Need to determine if this is connectivity vs auth vs Redis "
        "instance health.",
        "Multiple support tickets about cart loss in the last "
        "{ago_short}. Backing store appears intermittent. "
        "Going to flush + restart Redis if we can't get clean diagnosis "
        "in the next 10 minutes.",
    ),
    "payment-outage": (
        "Payment processing is failing. Charge attempts return Internal "
        "errors. Customers cannot complete purchases. Revenue-impacting "
        "— treating as P1.",
        "{service} is unhealthy. Order placement blocked. Looking at "
        "logs now — see a sustained spike of timeouts. Reached out to "
        "the payment-provider on-call.",
        "Reports of failed checkouts coming in via support and Twitter. "
        "Charge endpoint is returning errors. Will update once we know "
        "if this is upstream (provider) or our integration.",
    ),
    "currency-outage": (
        "{service} is unavailable. Currency conversion calls are timing "
        "out, which is blocking price display on product pages. "
        "Customer-facing — needs immediate attention.",
        "Conversion API down. Catalog falls back to USD-only mode but "
        "international customers are getting weird prices. Investigating.",
    ),
    "shipping-outage": (
        "Shipping quotes are failing — {service} is returning errors. "
        "Customers see 'shipping unavailable' at checkout, which is "
        "killing conversion.",
        "Shipping API not responding. We've gone into degraded mode "
        "(default shipping rate) but that's not sustainable. Need root "
        "cause.",
    ),
    "checkout-outage": (
        "Checkout is broken end-to-end. {service} returning Internal "
        "errors on every PlaceOrder. This is P0 — revenue stopped.",
        "Cart -> Checkout flow failing. No one can complete an order. "
        "Likely root cause in {service} but the failure mode is opaque "
        "from upstream traces.",
    ),
    "checkout-restart": (
        "{service} pods restarted unexpectedly. Some in-flight orders "
        "may have been dropped. Investigating restart reason — could be "
        "OOM, liveness probe, or config push.",
        "Brief outage on {service}, ~30s downtime. Looks like a pod "
        "restart. Customer impact was limited but we should understand "
        "why it happened.",
    ),
    "productcatalog-outage": (
        "Product catalog service is down. Catalog reads are failing "
        "across the board. PagerDuty fired {ago}. Going to roll back "
        "the most recent deploy if we can't get a quick diagnosis.",
        "{service} returning 503. Product pages broken. Checkout and "
        "recommendations both depend on this so customer impact is broad.",
    ),
    "productcatalog-latency": (
        "Catalog pages are slow this afternoon. Checkout team has been "
        "flagging. P95 latency on {service} has tripled. Need to look "
        "at recent deploys or upstream DB.",
        "{service} response times are degraded. Not failing outright "
        "but checkout flow is sluggish enough that customers are "
        "abandoning carts. Owners please take a look.",
    ),
    "recommendation-outage": (
        "{service} not returning recommendations. Product pages render "
        "but the 'you might also like' section is empty. Lower-priority "
        "than checkout but conversion takes a hit.",
        "Recommendations API failing. Falling back to popular-items "
        "list. Investigating whether the model server is down or just "
        "slow.",
    ),
    "ad-outage": (
        "{service} not serving. Banner slots empty on product pages. "
        "Revenue impact is small but tracking it.",
    ),
    "email-outage": (
        "{service} unhealthy. Order confirmation emails are queuing "
        "but not sending. Customers will assume orders failed and "
        "double-charge themselves trying again. Important to fix soon.",
    ),
    "frontend-restart": (
        "{service} pods cycled. Brief HTTP 502s for ~30s. Investigating "
        "whether this was a planned rollout we missed or something "
        "unexpected.",
    ),
    "frontend-traffic-pressure": (
        "Traffic spike on {service}. Latency holding but error rate "
        "ticked up. Watching to see if we need to scale.",
    ),
    "post-deploy-churn": (
        "Brief errors after the {service} rollout. Looks like the usual "
        "post-deploy connection churn — settled within a minute. "
        "Tracking just in case it's a pattern.",
    ),
    "recovered-in-window": (
        "Saw a brief blip on {service} but it self-recovered. No "
        "customer-visible impact in monitoring. Logging for awareness.",
    ),
    "single-pod-restart-healthy-replication": (
        "Single pod restart on {service}. Other replicas handled "
        "traffic — no customer impact. Resolving as noise.",
    ),
    "third-party-blip": (
        "Brief failure from {service}'s upstream dependency. Recovered "
        "quickly. No customer-visible impact but the on-call dashboard "
        "lit up.",
    ),
    "scheduled-job-spike": (
        "Spike on {service} traffic. Looks like the scheduled batch "
        "job ran. No impact on production traffic.",
    ),
    "latency-near-miss-partial-recovery": (
        "Latency wobble on {service}. Self-recovered before we got "
        "paged. Worth tracking.",
    ),
    "flapping-pod": (
        "{service} pod restarted multiple times in quick succession. "
        "Smells like a crash loop. Need to look at the container "
        "exit code and any panic logs.",
    ),
    "slow-leak-saturation": (
        "{service} memory has been climbing all day. Pod restart looks "
        "imminent. Suspect a leak — looking at recent code changes.",
    ),
    "baseline-normal": (
        "Routine health check — no issue reported. Closing.",
    ),
}


def _description_for_family(
    family: str, primary_service: str, services_csv: str, episode_id: str
) -> str:
    templates = _DESCRIPTION_TEMPLATES.get(family) or _DESCRIPTION_TEMPLATES.get(
        "recovered-in-window"
    )
    chosen = _pick(episode_id, templates)
    ago = _pick(episode_id + "ago", ["10 min ago", "an hour ago", "this afternoon", "around lunch"])
    ago_short = _pick(episode_id + "ago_short", ["20 min", "30 min", "an hour"])
    return chosen.format(
        service=primary_service,
        services_csv=services_csv or primary_service,
        ago=ago,
        ago_short=ago_short,
    )


# ---------------------------------------------------------------------------
# Comment templates — pool of conversational fragments, picked in pairs
# ---------------------------------------------------------------------------

_COMMENT_TEMPLATES_INITIAL = (
    "On it. Anyone seen this pattern before?",
    "Looking at the rollback timeline — most recent deploy was about an hour ago.",
    "Bumping priority — multiple customers complaining in #support.",
    "Pretty sure this is related to the {service} side. Will dig in.",
    "Picking this up. Will update once I have a clean diagnosis.",
    "Same symptoms as last week. Let me check what changed.",
)

_COMMENT_TEMPLATES_INVESTIGATION = (
    "Looks like it started right around {start_h}:00. No obvious correlating deploy.",
    "Found the failing call path. Stack trace points at the {service} client. Pulling logs.",
    "Confirmed it's not customer traffic — request rate is flat. Internal issue.",
    "Reaching out to the {service} team to confirm if they're aware.",
    "Reproduced in staging. Have a fix candidate.",
    "Not seeing this in the canary fleet, only the older release. Investigating.",
)

_COMMENT_TEMPLATES_RESOLVE = (
    "Fix deployed. Watching for recurrence. Marking resolved.",
    "Restarted the affected pods. Symptoms cleared. Will follow up on root cause separately.",
    "Confirmed back to normal. Thanks for the quick turnaround team.",
    "Rolled back the bad deploy. Service stable. Need a postmortem.",
    "Closing — recovered on its own. Filed a follow-up to add an alert so we catch this faster next time.",
)


def _comments_for_issue(
    episode_id: str, primary_service: str, created_at_iso: str
) -> list[dict[str, Any]]:
    """Return 2-3 conversational comment events. Multi-author, deterministic
    by episode_id. Spaced naturally over the incident lifetime."""
    initial = _pick(episode_id + "comment-init", _COMMENT_TEMPLATES_INITIAL)
    investigation = _pick(episode_id + "comment-inv", _COMMENT_TEMPLATES_INVESTIGATION)
    resolve = _pick(episode_id + "comment-res", _COMMENT_TEMPLATES_RESOLVE)
    try:
        start = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        start = datetime.now(timezone.utc)
    start_h = start.hour
    names = _pick_n_distinct(episode_id + "comment-authors", _NAMES, 3)
    return [
        {
            "body": initial.format(service=primary_service),
            "author": names[0],
            "created": (start + timedelta(minutes=6)).isoformat(),
        },
        {
            "body": investigation.format(service=primary_service, start_h=start_h),
            "author": names[1],
            "created": (start + timedelta(minutes=24)).isoformat(),
        },
        {
            "body": resolve.format(service=primary_service),
            "author": names[2],
            "created": (start + timedelta(minutes=42)).isoformat(),
        },
    ]


# ---------------------------------------------------------------------------
# Label cleanup
# ---------------------------------------------------------------------------

_LAB_LABEL_PREFIXES = ("dataset-", "scenario-")
_LAB_LABEL_LITERALS = {
    "synthetic-incident", "telemetry-linked",
}
# severity-* / root-* are lab-only too but we'll replace them with
# semantic labels (bug, production, etc.) below.
_LAB_PREFIX_REPLACE = ("severity-", "root-")


def _humanize_labels(
    original_labels: list[str], severity: str | None, family: str | None
) -> list[str]:
    out: set[str] = set()
    for label in original_labels or []:
        if label in _LAB_LABEL_LITERALS:
            continue
        if any(label.startswith(p) for p in _LAB_LABEL_PREFIXES + _LAB_PREFIX_REPLACE):
            continue
        out.add(label)
    # Add semantic labels real teams use
    out.add("production")
    out.add("incident")
    if severity in ("critical", "major"):
        out.add("customer-impact")
    if severity == "critical":
        out.add("p0")
    elif severity == "major":
        out.add("p1")
    elif severity == "minor":
        out.add("p3")
    # Family-derived semantic tag (without "scenario-" prefix leakage)
    if family and family not in {"baseline-normal"}:
        # Keep simple — frontend-restart -> frontend, cart-redis -> cart-redis
        out.add(family.split("-")[0])
    return sorted(out)


# ---------------------------------------------------------------------------
# Main rewriter
# ---------------------------------------------------------------------------


def _humanize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Return a new issue dict with humanized user-visible fields."""
    metadata = issue.get("metadata") or {}
    episode_id = issue.get("incident_episode_id") or issue.get("jira_shadow_issue_id") or ""
    # Source-of-truth fields
    components = list(metadata.get("components") or [])
    primary_service = components[0] if components else "the service"
    services_csv = ", ".join(components) if components else primary_service
    severity = (metadata.get("priority") or "").lower() if metadata.get("priority") else None
    # Infer family. Prefer the canonical SCENARIO_FAMILIES lookup from
    # triage_labels.py when the original `scenario-<sid>` label is still
    # present; fall back to substring heuristic otherwise.
    family = None
    scenario_id = None
    for lbl in metadata.get("labels") or []:
        if lbl.startswith("scenario-"):
            scenario_id = lbl[len("scenario-"):]
            break
    if scenario_id and scenario_id in _SCENARIO_FAMILIES:
        family = _SCENARIO_FAMILIES[scenario_id]
    elif scenario_id:
        # Substring search over known families
        for known_family in _DESCRIPTION_TEMPLATES.keys():
            if known_family in scenario_id:
                family = known_family
                break
    if family is None:
        old_desc = (metadata.get("description") or "").lower()
        for known_family in _DESCRIPTION_TEMPLATES.keys():
            if known_family in old_desc:
                family = known_family
                break
    family = family or "recovered-in-window"

    new_metadata = dict(metadata)
    new_metadata["description"] = _description_for_family(
        family, primary_service, services_csv, episode_id
    )
    new_metadata["labels"] = _humanize_labels(metadata.get("labels") or [], severity, family)
    new_metadata["reporter"] = _pick(episode_id + "reporter", _NAMES)
    new_metadata["assignee"] = _pick(episode_id + "assignee", _NAMES)
    # Drop the realism_profile marker — leaks generation provenance
    new_metadata.pop("realism_profile", None)

    # Replace single mechanical comment with 3 conversational ones
    new_comments = _comments_for_issue(
        episode_id, primary_service, metadata.get("created_at", "")
    )
    new_metadata["comments_id"] = [f"{issue.get('jira_issue_key','')}-c{i+1}" for i in range(len(new_comments))]
    new_metadata["comments_body"] = "\n\n---\n\n".join(
        f"[{c['author']} @ {c['created'][:16]}]\n{c['body']}"
        for c in new_comments
    )

    # Regenerate activity — keep status/priority/component history events
    # (they're informative + human), but replace any "comment" type event
    # whose body had lab metadata with our new conversational comments.
    new_activity = []
    for day in issue.get("activity") or []:
        new_events = []
        comment_idx = 0
        for ev in day.get("events") or []:
            ev_type = ev.get("type")
            if ev_type == "comment" and comment_idx < len(new_comments):
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
                # Status/priority events: reassign author from name pool too
                new_ev = dict(ev)
                if ev.get("author") == "Research Lab Automation":
                    new_ev["author"] = new_metadata["reporter"]
                elif ev.get("author") == "Service Owner":
                    new_ev["author"] = new_metadata["assignee"]
                new_events.append(new_ev)
        new_activity.append({**day, "events": new_events})

    # Any leftover synthesized comments not yet placed in activity — append
    # to the first day's events so they're not lost.
    while comment_idx < len(new_comments) and new_activity:
        c = new_comments[comment_idx]
        new_activity[0]["events"].append({
            "type": "comment",
            "id": f"{issue.get('jira_issue_key','')}-c{comment_idx+1}",
            "author": c["author"],
            "created": c["created"],
            "timestamp": c["created"],
            "field": "",
            "from": "",
            "to": "",
            "body": c["body"],
            "description": f"{c['author']} commented on {issue.get('jira_issue_key','')}",
        })
        comment_idx += 1

    # History: reassign Research Lab Automation / Service Owner to real names
    new_history = []
    for h in issue.get("history") or []:
        new_h = dict(h)
        if h.get("author") == "Research Lab Automation":
            new_h["author"] = new_metadata["reporter"]
        elif h.get("author") == "Service Owner":
            new_h["author"] = new_metadata["assignee"]
        new_history.append(new_h)

    new_issue = dict(issue)
    new_issue["metadata"] = new_metadata
    new_issue["activity"] = new_activity
    new_issue["history"] = new_history
    # telemetry_links: leave intact — it's the retrieval ground truth and
    # is NOT user-visible in production Jira.
    return new_issue


def _process_file(path: Path, *, in_place: bool, out_path: Path | None) -> tuple[int, int]:
    """Returns (issues_read, issues_written)."""
    issues = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                issues.append(json.loads(line))
    rewritten = [_humanize_issue(i) for i in issues]

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
    return len(issues), len(rewritten)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--in", dest="in_path", help="Single jsonl to rewrite")
    src_group.add_argument("--run-prefix",
                            help="Run prefix — rewrite jira_shadow_issues.jsonl "
                                 "for every matching run under --runs-root")
    parser.add_argument("--runs-root", default=str(REPO_ROOT / "data" / "runs"))
    parser.add_argument("--in-place", action="store_true",
                        help="Rewrite the source file in place; backup as <file>.pre-humanize.bak")
    parser.add_argument("--out", help="When not --in-place, path to write the new jsonl")
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

    total_read = total_written = 0
    for t in targets:
        if not t.exists() or t.stat().st_size == 0:
            print(f"  SKIP empty/missing: {t}", file=sys.stderr)
            continue
        out = Path(args.out) if (args.out and not args.in_place) else None
        n_read, n_wrote = _process_file(t, in_place=args.in_place, out_path=out)
        total_read += n_read
        total_written += n_wrote
        print(f"  rewrote {n_wrote}/{n_read} from {t.relative_to(REPO_ROOT) if REPO_ROOT in t.parents else t}", file=sys.stderr)

    print(f"\nDone. {total_written} issues rewritten across {len(targets)} files.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
