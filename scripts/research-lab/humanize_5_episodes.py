#!/usr/bin/env python3
"""Phase-2 atomic-PR driver: humanize 5 stratified episodes.

Picks one active-fault window from each of 5 families covering the
diversity of v5-large (cart-redis, baseline-normal, productcatalog-
latency, payment-outage, recovered-in-window), runs the report-step
generator end-to-end, and writes:

  data/derived/global/<global-id>/jira-shadow-humanized-v1/
    timeline.jsonl            -- one humanized ticket per row
    generation-manifest.json  -- which episodes, prompts, hashes
    sample-comparison.md      -- legacy shadow vs humanized side-by-side

Acceptance for the PR (per LLM-Jira-enhancement.md §9):
  * sanitizer detects 0 lab-leakage tokens at LLM input
  * sanitizer detects 0 lab-leakage tokens in any LLM output
  * lexical overlap between any two report steps is < 0.7
  * humanized text reads as plausibly written by 5 different humans

Usage:
    python scripts/research-lab/humanize_5_episodes.py
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import OrderedDict
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_humanizer.sanitizer import find_lab_tokens  # noqa: E402
from jira_humanizer.timeline_generator import (  # noqa: E402
    LLMConfig,
    ReportContext,
    build_report_evidence,
    generate_report_step,
    stamp_versions,
)
from jira_humanizer.timeline_schema import (  # noqa: E402
    TicketTimeline,
)
from jira_humanizer.timeline_generator import WindowEvidenceInputs  # noqa: E402


# Strata: pick one active_fault window per family. The list is ordered
# by what makes the comparison readable, not by criticality.
_STRATA: tuple[str, ...] = (
    "cart-redis",                # largest family, classic dep failure
    "baseline-normal",           # control — no real incident
    "productcatalog-latency",    # cross-service blame potential
    "payment-outage",            # cleanest ticket-worthy
    "recovered-in-window",       # borderline — symptom-only ticket
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--global-id",
        default="2026-05-25-dataset-v5-large-global",
        help="Global derived dataset id under data/derived/global/.",
    )
    p.add_argument(
        "--runs-root",
        default=str(_REPO_ROOT / "data" / "runs"),
        help="Root of data/runs/.",
    )
    p.add_argument(
        "--derived-root",
        default=str(_REPO_ROOT / "data" / "derived" / "global"),
        help="Root of data/derived/global/.",
    )
    p.add_argument(
        "--llm-base-url",
        default="http://localhost:1234",
        help="LM Studio endpoint.",
    )
    p.add_argument(
        "--llm-model",
        default="qwen/qwen2.5-coder-14b",
        help="Chat model id served by LM Studio.",
    )
    p.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="LLM sampling temperature.",
    )
    return p.parse_args()


def _pick_one_window_per_family(
    global_examples_path: Path,
    strata: tuple[str, ...],
) -> list[dict]:
    """Walk global-triage-examples.jsonl until we have one active_fault
    (or observation_window for baseline-normal) row from each family in
    `strata`. Picks the FIRST match for determinism.
    """
    needed = OrderedDict((f, None) for f in strata)
    with global_examples_path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            family = row.get("scenario_family")
            if family not in needed or needed[family] is not None:
                continue
            wt = row.get("window_type")
            if family == "baseline-normal":
                if wt != "observation_window":
                    continue
            else:
                if wt != "active_fault":
                    continue
            needed[family] = row
            if all(v is not None for v in needed.values()):
                break
    missing = [f for f, v in needed.items() if v is None]
    if missing:
        raise RuntimeError(
            f"Could not find an active_fault window in v5-large for families: {missing}"
        )
    return list(needed.values())


def _lexical_overlap(a: str, b: str) -> float:
    """Tiny Jaccard over lowercased word sets — for the acceptance gate
    'two report steps differ measurably'."""
    sa = set((a or "").lower().split())
    sb = set((b or "").lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _humanize_one(window_row: dict, runs_root: Path, llm: LLMConfig) -> TicketTimeline:
    run_id = window_row["dataset_run_id"]
    run_dir = runs_root / run_id
    inputs = WindowEvidenceInputs(
        run_dir=run_dir,
        window_id=window_row["window_id"],
        service_name=window_row["service_name"],
        window_start_iso=window_row["start_time"],
        window_end_iso=window_row["end_time"],
    )
    evidence = build_report_evidence(inputs)
    ctx = ReportContext(
        episode_id=window_row["incident_episode_id"],
        affected_service=window_row["service_name"],
        scenario_family=window_row["scenario_family"],
        # The reporter does not know the eval-only severity — they assign
        # a public-facing one. For Phase 2 we map family to a coarse
        # public severity (Phase 3 will derive it from observed metrics).
        severity_seen=_coarse_public_severity(window_row["scenario_family"]),
        evidence=evidence,
    )
    step = generate_report_step(ctx, llm=llm)
    versions = stamp_versions()
    return TicketTimeline(
        ticket_id=f"HMN-{window_row['incident_episode_id']}",
        source_episode_id=window_row["incident_episode_id"],
        source_dataset_run_id=run_id,
        affected_services_seen=[window_row["service_name"]],
        severity_seen=ctx.severity_seen,
        components_seen=[window_row["service_name"]],
        is_misattributed=False,    # Phase 3+ introduces Rule 3
        closed_as_noise=False,     # Phase 4+ introduces Rule 5
        steps=[step],
        **versions,
    )


def _coarse_public_severity(family: str) -> str:
    """Public-facing severity the reporter would write down — not the
    eval-only `triage_severity`. Defaults conservatively so we never
    over-claim urgency."""
    fam = (family or "").lower()
    if fam in {"payment-outage", "checkout-outage", "cart-redis"}:
        return "high"
    if fam in {"recovered-in-window", "post-deploy-churn",
               "single-pod-restart-healthy-replication", "baseline-normal"}:
        return "low"
    return "medium"


def main() -> int:
    args = _parse_args()
    runs_root = Path(args.runs_root)
    derived_root = Path(args.derived_root)
    global_dir = derived_root / args.global_id
    if not global_dir.exists():
        print(f"ERROR: global derived dir not found: {global_dir}", file=sys.stderr)
        return 2
    examples_path = global_dir / "global-triage-examples.jsonl"

    out_dir = global_dir / "jira-shadow-humanized-v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = LLMConfig(
        base_url=args.llm_base_url,
        model=args.llm_model,
        temperature=args.temperature,
    )

    print(f"[humanize] picking one active_fault window per family ...", file=sys.stderr)
    picks = _pick_one_window_per_family(examples_path, _STRATA)

    timelines: list[TicketTimeline] = []
    for row in picks:
        family = row["scenario_family"]
        episode_id = row["incident_episode_id"]
        print(f"[humanize] family={family} episode={episode_id[-60:]}", file=sys.stderr)
        try:
            timeline = _humanize_one(row, runs_root, llm)
            timelines.append(timeline)
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue

    if not timelines:
        print("ERROR: no timelines generated", file=sys.stderr)
        return 1

    # Write timeline.jsonl
    timeline_path = out_dir / "timeline.jsonl"
    with timeline_path.open("w", encoding="utf-8") as fh:
        for t in timelines:
            fh.write(json.dumps(t.as_jsonl_row()) + "\n")
    print(f"[humanize] wrote {timeline_path} ({len(timelines)} rows)", file=sys.stderr)

    # Acceptance checks
    print(f"[humanize] checking acceptance gates ...", file=sys.stderr)
    leaks_per_ticket: list[list[str]] = [
        find_lab_tokens(t.steps[0].text) for t in timelines
    ]
    leak_total = sum(len(lst) for lst in leaks_per_ticket)
    overlaps: list[tuple[str, str, float]] = []
    for i in range(len(timelines)):
        for j in range(i + 1, len(timelines)):
            o = _lexical_overlap(timelines[i].steps[0].text, timelines[j].steps[0].text)
            overlaps.append((
                timelines[i].source_episode_id[-30:],
                timelines[j].source_episode_id[-30:],
                o,
            ))
    max_overlap = max((o for *_, o in overlaps), default=0.0)
    pass_leak = leak_total == 0
    pass_variance = max_overlap < 0.7

    # generation-manifest.json
    manifest = {
        "global_id": args.global_id,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "llm": {
            "base_url": llm.base_url,
            "model": llm.model,
            "temperature": llm.temperature,
        },
        "stratification": list(_STRATA),
        "tickets": [
            {
                "ticket_id": t.ticket_id,
                "source_episode_id": t.source_episode_id,
                "source_dataset_run_id": t.source_dataset_run_id,
                "report_prompt_hash": t.steps[0].prompt_hash,
                "reporter_avatar": t.steps[0].persona_avatar,
                "reporter_role": t.steps[0].persona_role,
                "log_quotes_used": t.steps[0].evidence.log_quotes,
                "lab_leak_tokens": leaks_per_ticket[i],
            }
            for i, t in enumerate(timelines)
        ],
        "acceptance": {
            "pass_no_leak": pass_leak,
            "pass_variance": pass_variance,
            "total_leak_tokens": leak_total,
            "max_pairwise_overlap": max_overlap,
        },
        "versions": stamp_versions(),
    }
    manifest_path = out_dir / "generation-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[humanize] wrote {manifest_path}", file=sys.stderr)

    # sample-comparison.md — side-by-side with the legacy shadow
    legacy_path = global_dir / "jira-memory-corpus.jsonl"
    legacy_by_episode: dict[str, dict] = {}
    if legacy_path.exists():
        with legacy_path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    issue = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ep = issue.get("incident_episode_id") or ""
                legacy_by_episode.setdefault(ep, issue)

    lines: list[str] = []
    lines.append("# Humanized vs legacy shadow: 5-episode comparison")
    lines.append("")
    lines.append(f"_Generated {manifest['generated_at']} with {llm.model}._")
    lines.append("")
    for t in timelines:
        legacy = legacy_by_episode.get(t.source_episode_id, {})
        family = next(
            (row["scenario_family"] for row in picks
             if row["incident_episode_id"] == t.source_episode_id),
            "?",
        )
        lines.append(f"## {family} — {t.source_episode_id[-40:]}")
        lines.append("")
        lines.append(f"**Reporter:** {t.steps[0].persona_avatar} ({t.steps[0].persona_role})  ")
        lines.append(f"**Severity seen:** {t.severity_seen}  ")
        lines.append(f"**Log lines used as evidence:** {len(t.steps[0].evidence.log_quotes)}")
        lines.append("")
        lines.append("### Humanized (Phase 2)")
        lines.append("")
        lines.append("```")
        lines.append(t.steps[0].text)
        lines.append("```")
        lines.append("")
        lines.append("### Legacy shadow")
        lines.append("")
        lines.append("```")
        legacy_text = (legacy.get("memory_text") or "")[:1200]
        lines.append(legacy_text or "(no legacy shadow found for this episode)")
        lines.append("```")
        lines.append("")
    md_path = out_dir / "sample-comparison.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[humanize] wrote {md_path}", file=sys.stderr)

    print()
    print(f"[humanize] ACCEPTANCE: leak_tokens={leak_total} (want=0)  max_overlap={max_overlap:.3f} (want<0.7)")
    print(f"[humanize] {'PASS' if pass_leak and pass_variance else 'FAIL'}")
    return 0 if (pass_leak and pass_variance) else 1


if __name__ == "__main__":
    sys.exit(main())
