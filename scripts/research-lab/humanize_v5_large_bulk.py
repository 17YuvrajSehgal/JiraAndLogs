#!/usr/bin/env python3
"""Bulk-regenerate humanized Jira tickets for the full v5-large corpus.

Walks the 347-entry legacy `jira-memory-corpus.jsonl` and produces one
humanized TIMELINE per Jira shadow into a NEW subdirectory under
`jira-shadow-humanized-v1/`. The original legacy corpus and all
`data/runs/<id>/raw/` files are opened READ-ONLY; the script
explicitly refuses to write to any input path.

Safety properties (asserted at startup):
  * INPUT paths (jira-memory-corpus.jsonl, global-triage-examples.jsonl,
    data/runs/<id>/episodes.jsonl, data/runs/<id>/raw/loki/*.json) are
    only ever opened with `mode='r'`. The script does not call any
    write helper on these paths.
  * OUTPUT directory (default: jira-shadow-humanized-v1/bulk-<UTC date>/)
    is the only place this script creates or modifies files.
  * If the output directory already contains a partial timeline.jsonl,
    --resume picks up where it left off — each prior humanized ticket
    is keyed by ticket_id and skipped on re-run.

Output (per --output-subdir):
  timeline.jsonl              # one row per humanized ticket
  generation-manifest.json    # totals, failures, llm config, versions
  progress.log                # live tail-able progress log

Usage:
    python scripts/research-lab/humanize_v5_large_bulk.py
    python scripts/research-lab/humanize_v5_large_bulk.py --resume
    python scripts/research-lab/humanize_v5_large_bulk.py --limit 25  # smoke

Runtime estimate at 347 legacy shadows × ~4.3 LLM calls each:
  Local Qwen on RTX 5060   ~ 2 hours
  Claude Haiku             ~ 5 minutes, ~$1
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_humanizer.sanitizer import find_lab_tokens  # noqa: E402
from jira_humanizer.timeline_generator import (  # noqa: E402
    FullTimelineInputs,
    LLMConfig,
    WindowEvidenceInputs,
    generate_full_timeline,
    get_usage_stats,
    plan_closure,
    plan_misattribution,
    plan_wrong_hypothesis,
    reset_usage_stats,
    stamp_versions,
)
from jira_humanizer.timeline_schema import TicketTimeline  # noqa: E402


# ---------------------------------------------------------------------------
# Read-only helpers (these are the ONLY paths this script reads from)
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Open `path` strictly read-only. Caller asserts path is intended-input."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    # Mode "r" only — no write/append.
    with path.open(mode="r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _coarse_public_severity(family: str) -> str:
    fam = (family or "").lower()
    if fam in {"payment-outage", "checkout-outage", "cart-redis"}:
        return "high"
    if fam in {"recovered-in-window", "post-deploy-churn",
               "single-pod-restart-healthy-replication", "baseline-normal"}:
        return "low"
    return "medium"


# ---------------------------------------------------------------------------
# Window-by-episode index built once from global-triage-examples.jsonl
# ---------------------------------------------------------------------------


def _build_window_index(global_examples_path: Path) -> dict[tuple[str, str, str], dict]:
    """Return `{(episode_id, service_name, window_type): row}`.

    We use it twice per ticket:
      1. Preferred: pick the active_fault window matching the legacy
         shadow's affected_service.
      2. Fallback: any active_fault window for the same episode.
    """
    index: dict[tuple[str, str, str], dict] = {}
    with global_examples_path.open(mode="r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (
                row.get("incident_episode_id", ""),
                row.get("service_name", ""),
                row.get("window_type", ""),
            )
            if key[0]:
                index[key] = row
    return index


def _pick_window_for(
    legacy_entry: dict, window_index: dict[tuple[str, str, str], dict]
) -> dict | None:
    """Choose the active_fault window the reporter would have looked at.

    Strategy:
      1. Try the exact (episode_id, legacy.affected_service, active_fault).
      2. Fall back to any active_fault for that episode.
      3. Fall back to any observation_window (baseline cases).
    """
    ep = legacy_entry.get("incident_episode_id", "")
    svc = legacy_entry.get("affected_service", "")
    if not ep:
        return None
    hit = window_index.get((ep, svc, "active_fault"))
    if hit:
        return hit
    for (e, s, w), row in window_index.items():
        if e == ep and w == "active_fault":
            return row
    for (e, s, w), row in window_index.items():
        if e == ep and w == "observation_window":
            return row
    return None


# ---------------------------------------------------------------------------
# episodes.jsonl is consulted once per ticket to gather misattribution
# candidates. Build a cache so we open each file at most once.
# ---------------------------------------------------------------------------


class EpisodeIndex:
    """Cached read of `data/runs/<run>/episodes.jsonl`. READ-ONLY."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root
        self._cache: dict[str, dict[str, list[str]]] = {}

    def affected_services_for(self, run_id: str, episode_id: str) -> list[str]:
        run_map = self._cache.get(run_id)
        if run_map is None:
            run_map = {}
            ep_path = self.runs_root / run_id / "episodes.jsonl"
            for ep in _read_jsonl(ep_path):
                eid = ep.get("incident_episode_id")
                if not eid:
                    continue
                run_map[eid] = [str(s) for s in (ep.get("affected_services") or [])]
            self._cache[run_id] = run_map
        return list(run_map.get(episode_id, []))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


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
        help="data/runs root (READ-ONLY).",
    )
    p.add_argument(
        "--derived-root",
        default=str(_REPO_ROOT / "data" / "derived" / "global"),
        help="data/derived/global root.",
    )
    p.add_argument(
        "--output-subdir",
        default=None,
        help=("Subdirectory name under jira-shadow-humanized-v1/. "
              "Defaults to bulk-<UTC date>."),
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
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N legacy shadows (0 = all). Useful for smoke.",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip ticket_ids already present in the output timeline.jsonl.",
    )
    return p.parse_args()


def _declare_paths(
    *,
    legacy_path: Path,
    examples_path: Path,
    runs_root: Path,
    output_dir: Path,
) -> None:
    """Print + assert which paths are inputs vs outputs. Refuses if the
    declared output points at any of the declared inputs (paranoia)."""
    print("=== humanize_v5_large_bulk: path declaration ===", file=sys.stderr)
    print(f"  INPUT  (read-only): {legacy_path}", file=sys.stderr)
    print(f"  INPUT  (read-only): {examples_path}", file=sys.stderr)
    print(f"  INPUT  (read-only): {runs_root}/ (all subfiles)", file=sys.stderr)
    print(f"  OUTPUT (write):     {output_dir}/", file=sys.stderr)
    inputs = (legacy_path.resolve(), examples_path.resolve(), runs_root.resolve())
    out = output_dir.resolve()
    for inp in inputs:
        # Output can sit *next to* the input root (jira-shadow-humanized-v1/
        # is a sibling of jira-memory-corpus.jsonl), but it must never BE
        # one of the input paths nor a parent of them.
        if out == inp or inp == out:
            raise RuntimeError(
                f"Output path {out} is identical to input {inp}; refusing to run."
            )
        try:
            inp.relative_to(out)
        except ValueError:
            continue
        raise RuntimeError(
            f"Input path {inp} sits under output {out}; refusing to run."
        )


def _humanize_one(
    window_row: dict,
    runs_root: Path,
    episode_index: EpisodeIndex,
    global_triage_path: Path,
    llm: LLMConfig,
) -> TicketTimeline:
    run_id = window_row["dataset_run_id"]
    run_dir = runs_root / run_id
    inputs = WindowEvidenceInputs(
        run_dir=run_dir,
        window_id=window_row["window_id"],
        service_name=window_row["service_name"],
        window_start_iso=window_row["start_time"],
        window_end_iso=window_row["end_time"],
    )
    candidates = episode_index.affected_services_for(
        run_id, window_row["incident_episode_id"],
    )
    bundle = FullTimelineInputs(
        window_row=window_row,
        inputs=inputs,
        severity_seen=_coarse_public_severity(window_row["scenario_family"]),
        candidate_downstream_services=candidates,
        triage_label=window_row.get("triage_label", ""),
        # V2 wiring — routes through multi-channel evidence bundle.
        global_triage_path=global_triage_path,
        alerts_path=run_dir / "alerts.jsonl",
        source_injection_id=window_row["incident_episode_id"],
    )
    return generate_full_timeline(bundle, llm=llm)


def main() -> int:
    args = _parse_args()
    runs_root = Path(args.runs_root)
    derived_root = Path(args.derived_root)
    global_dir = derived_root / args.global_id
    if not global_dir.exists():
        print(f"ERROR: global derived dir not found: {global_dir}", file=sys.stderr)
        return 2

    legacy_path = global_dir / "jira-memory-corpus.jsonl"
    examples_path = global_dir / "global-triage-examples.jsonl"
    if not legacy_path.exists() or not examples_path.exists():
        print(f"ERROR: required inputs missing under {global_dir}", file=sys.stderr)
        return 2

    if args.output_subdir is None:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        args.output_subdir = f"bulk-{today}"
    # V2 corpus goes to jira-shadow-humanized-v2/; V1 stays untouched.
    output_dir = global_dir / "jira-shadow-humanized-v2" / args.output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    _declare_paths(
        legacy_path=legacy_path,
        examples_path=examples_path,
        runs_root=runs_root,
        output_dir=output_dir,
    )

    print(f"[bulk] loading legacy shadows ...", file=sys.stderr)
    legacy_entries = _read_jsonl(legacy_path)
    print(f"[bulk] {len(legacy_entries)} legacy shadows to humanize",
          file=sys.stderr)

    print(f"[bulk] building window index ...", file=sys.stderr)
    window_index = _build_window_index(examples_path)
    print(f"[bulk] indexed {len(window_index)} windows", file=sys.stderr)

    episode_index = EpisodeIndex(runs_root)

    timeline_path = output_dir / "timeline.jsonl"
    progress_path = output_dir / "progress.log"

    # Resume: load already-completed ticket_ids
    done_ticket_ids: set[str] = set()
    if args.resume and timeline_path.exists():
        for row in _read_jsonl(timeline_path):
            tid = row.get("ticket_id")
            if tid:
                done_ticket_ids.add(tid)
        print(f"[bulk] resume: {len(done_ticket_ids)} tickets already done",
              file=sys.stderr)

    # Optionally truncate to --limit
    work = legacy_entries[: args.limit] if args.limit > 0 else legacy_entries

    llm = LLMConfig(
        base_url=args.llm_base_url,
        model=args.llm_model,
        temperature=args.temperature,
    )
    # Reset usage counters so this run's manifest reports just this run.
    # (When --resume, prior tickets' tokens are NOT re-counted — fine; the
    # manifest documents the resumption call's stats specifically.)
    reset_usage_stats()

    n_ok = 0
    n_fail = 0
    n_skip = 0
    n_no_window = 0
    failures: list[dict[str, Any]] = []
    started_at = time.time()

    # Append mode when resuming; write mode otherwise. The output
    # is line-flushed per ticket so a kill mid-run leaves the prior
    # tickets intact.
    file_mode = "a" if args.resume else "w"
    progress_mode = "a" if args.resume else "w"

    with timeline_path.open(file_mode, encoding="utf-8") as out_f, \
         progress_path.open(progress_mode, encoding="utf-8") as prog_f:
        prog_f.write(
            f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] "
            f"bulk run started; n_legacy={len(legacy_entries)} "
            f"limit={args.limit} resume={args.resume}\n"
        )
        prog_f.flush()

        for i, entry in enumerate(work):
            ep_id = entry.get("incident_episode_id", "")
            ticket_id = f"HMN-{ep_id}"

            if ticket_id in done_ticket_ids:
                n_skip += 1
                continue

            window = _pick_window_for(entry, window_index)
            if window is None:
                n_no_window += 1
                failures.append({
                    "ticket_id": ticket_id,
                    "reason": "no_window_found_for_episode",
                })
                continue

            t0 = time.time()
            try:
                timeline = _humanize_one(
                    window, runs_root, episode_index,
                    examples_path, llm,
                )
                # Defence in depth: scan every step's text for leaks
                # before we serialize. This is paid for already inside
                # the generator but we re-check at the corpus boundary.
                for step in timeline.steps:
                    leaks = find_lab_tokens(step.text)
                    if leaks:
                        raise RuntimeError(
                            f"post-generation leak detected at "
                            f"step={step.step_kind}: {leaks[:4]}"
                        )
                out_f.write(json.dumps(timeline.as_jsonl_row()) + "\n")
                out_f.flush()
                n_ok += 1
                elapsed = time.time() - t0
                if n_ok == 1 or n_ok % 10 == 0:
                    avg = (time.time() - started_at) / max(n_ok, 1)
                    remaining = (len(work) - i - 1) * avg
                    eta = datetime.timedelta(seconds=int(remaining))
                    msg = (
                        f"[bulk] {i+1}/{len(work)} ok={n_ok} fail={n_fail} "
                        f"skip={n_skip} no_window={n_no_window} "
                        f"last={elapsed:.1f}s avg={avg:.1f}s eta={eta}"
                    )
                    print(msg, file=sys.stderr)
                    prog_f.write(
                        f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] "
                        f"{msg}\n"
                    )
                    prog_f.flush()
            except Exception as exc:
                n_fail += 1
                failures.append({
                    "ticket_id": ticket_id,
                    "reason": f"{type(exc).__name__}: {exc}",
                })
                msg = f"[bulk] FAIL {ticket_id[-50:]}: {type(exc).__name__}: {exc}"
                print(msg, file=sys.stderr)
                prog_f.write(
                    f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] "
                    f"{msg}\n"
                )
                prog_f.flush()

    duration_s = time.time() - started_at
    usage_stats = get_usage_stats().as_dict()

    manifest = {
        "global_id": args.global_id,
        "output_subdir": args.output_subdir,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "duration_s": int(duration_s),
        "llm": {
            "base_url": llm.base_url,
            "model": llm.model,
            "temperature": llm.temperature,
        },
        "llm_usage": usage_stats,
        "totals": {
            "n_legacy_total": len(legacy_entries),
            "n_processed": len(work),
            "n_ok": n_ok,
            "n_fail": n_fail,
            "n_skipped_resume": n_skip,
            "n_no_window": n_no_window,
        },
        "failures": failures[:50],   # cap to keep manifest readable
        "n_failures_total": len(failures),
        "versions": stamp_versions(),
        "input_paths_read_only": [
            str(legacy_path),
            str(examples_path),
            str(runs_root),
        ],
        "output_path": str(output_dir),
    }
    manifest_path = output_dir / "generation-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[bulk] wrote {manifest_path}", file=sys.stderr)
    print(
        f"[bulk] DONE in {datetime.timedelta(seconds=int(duration_s))}: "
        f"ok={n_ok} fail={n_fail} skip={n_skip} no_window={n_no_window}",
        file=sys.stderr,
    )
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
