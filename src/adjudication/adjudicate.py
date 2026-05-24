#!/usr/bin/env python3
"""D0.2 CLI: blind-review one telemetry window and capture a human label.

Usage examples
--------------

Interactive review of the next unadjudicated borderline window in a run::

    python -m src.adjudication.adjudicate \\
        --run 2026-05-22-dataset-v4-large-compact-a-r01 \\
        --next borderline \\
        --adjudicator yuvraj

Non-interactive (one-shot label, useful for D0.3 LLM-as-first-reviewer
integration or for scripted test runs)::

    python -m src.adjudication.adjudicate \\
        --window <telemetry_window_id> \\
        --label borderline \\
        --rationale "near-miss latency, recovered within SLO" \\
        --adjudicator llm-claude-opus-4-7

Status / dry-run::

    python -m src.adjudication.adjudicate --status \\
        --run 2026-05-22-dataset-v4-large-compact-a-r01
    python -m src.adjudication.adjudicate --window <id> --dry-run

Per docs/triage-task-contract.md, the schema's `source` enum and the
human_adjudicated guards (require adjudicator + adjudicated_at) are
enforced here so the resulting jsonl validates against
`schemas/triage_window_label.schema.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VALID_LABELS = ("ticket_worthy", "borderline", "noise")
VALID_SEVERITIES = ("minor", "major", "critical")
VALID_REASON_CLASSES = (
    "outage",
    "latency_regression",
    "restart_with_impact",
    "bad_config",
    "capacity",
    "dependency_failure",
    "data_consistency",
)


# ----------------------------------------------------------------------------
# I/O helpers
# ----------------------------------------------------------------------------


def repo_root(start: Path | None = None) -> Path:
    p = (start or Path(__file__).resolve()).parent
    while p != p.parent:
        if (p / "dataset-todo.md").exists() and (p / "scripts").exists():
            return p
        p = p.parent
    raise RuntimeError("Could not locate JiraAndLogs repo root")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True))
            f.write("\n")


# ----------------------------------------------------------------------------
# Window discovery
# ----------------------------------------------------------------------------


@dataclass
class WindowRecord:
    run_id: str
    window_id: str
    triage_example: dict
    label_row: dict | None  # existing entry in triage_window_labels.jsonl
    runs_dir: Path
    derived_dir: Path


def list_runs(repo: Path) -> list[str]:
    return sorted(p.name for p in (repo / "data" / "derived").glob("*") if p.is_dir())


def load_triage_examples(repo: Path, run_id: str) -> list[dict]:
    return load_jsonl(repo / "data" / "derived" / run_id / "triage_examples.jsonl")


def load_label_rows(repo: Path, run_id: str) -> list[dict]:
    return load_jsonl(
        repo / "data" / "derived" / run_id / "triage_window_labels.jsonl"
    )


def find_window(repo: Path, run_id: str, window_id: str) -> WindowRecord | None:
    examples = load_triage_examples(repo, run_id)
    ex = next(
        (
            e
            for e in examples
            if e.get("telemetry_window_id") == window_id
            or e.get("window_id") == window_id
        ),
        None,
    )
    if not ex:
        return None
    labels = load_label_rows(repo, run_id)
    label_row = next(
        (l for l in labels if l.get("telemetry_window_id") == window_id), None
    )
    return WindowRecord(
        run_id=run_id,
        window_id=window_id,
        triage_example=ex,
        label_row=label_row,
        runs_dir=repo / "data" / "runs" / run_id,
        derived_dir=repo / "data" / "derived" / run_id,
    )


def find_next_unadjudicated(
    repo: Path,
    run_id: str,
    candidate: str,  # "borderline" | "hard"
) -> WindowRecord | None:
    examples = load_triage_examples(repo, run_id)
    labels = {l.get("telemetry_window_id"): l for l in load_label_rows(repo, run_id)}
    for ex in examples:
        wid = ex.get("telemetry_window_id") or ex.get("window_id")
        if not wid:
            continue
        match candidate:
            case "borderline":
                ok = ex.get("triage_label") == "borderline"
            case "hard":
                ok = bool(ex.get("is_hard_case"))
            case _:
                ok = False
        if not ok:
            continue
        lr = labels.get(wid)
        if lr and lr.get("source") == "human_adjudicated":
            continue
        return find_window(repo, run_id, wid)
    return None


# ----------------------------------------------------------------------------
# Evidence presentation (scenario-blinded)
# ----------------------------------------------------------------------------


# Fields removed from presentation so the reviewer can't peek at the
# scenario-authored ground truth. These are still kept in the underlying
# data; the adjudicator just doesn't see them at prompt time.
BLINDED_FIELDS = (
    "scenario_id",
    "scenario_family",
    "triage_label",
    "triage_severity",
    "triage_components",
    "triage_reason_class",
    "is_hard_case",
    "incident_episode_id",
    "source",
    "rationale",
)


def _summarise_loki(loki_path: Path) -> dict:
    """Return a tiny structured summary of the Loki export for a window."""
    if not loki_path.exists():
        return {"available": False}
    try:
        with loki_path.open() as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"available": False, "error": "parse"}
    sw = doc.get("service_window", {})
    if not sw.get("ok"):
        return {"available": False, "error": "loki_export_failed"}
    resp = sw.get("response", {})
    streams = resp.get("data", {}).get("result", []) or []
    n_lines = 0
    severity_counts: dict[str, int] = {}
    sample_errors: list[str] = []
    for s in streams:
        for entry in s.get("values", []) or []:
            if not (isinstance(entry, list) and len(entry) == 2):
                continue
            line = entry[1]
            n_lines += 1
            # Severity heuristics
            lo = line.lower()
            for tag in ("error", "warn", "info", "debug"):
                if tag in lo:
                    severity_counts[tag] = severity_counts.get(tag, 0) + 1
                    break
            if "error" in lo and len(sample_errors) < 5:
                sample_errors.append(line[:240])
    return {
        "available": True,
        "n_lines": n_lines,
        "severity_counts": severity_counts,
        "sample_errors": sample_errors,
    }


def _find_global_memory_corpus(repo: Path) -> Path | None:
    """Find the newest global jira-memory-corpus.jsonl (cross-run, time-ordered)."""
    cands = sorted(
        (repo / "data" / "derived" / "global").glob("*/jira-memory-corpus.jsonl"),
        key=lambda p: p.parent.name,
        reverse=True,
    )
    return cands[0] if cands else None


def _summarise_jira_memory_hits(repo: Path, rec: WindowRecord) -> dict:
    """Look up retrieved Jira-memory hits for this window."""
    matchings_path = rec.derived_dir / "window_memory_matchings.jsonl"
    if not matchings_path.exists():
        return {"available": False, "error": "no_matchings"}
    matching = None
    for row in load_jsonl(matchings_path):
        if row.get("window_id") == rec.window_id:
            matching = row
            break
    if matching is None:
        return {"available": False, "error": "window_not_in_matchings"}
    ids = list(matching.get("matched_memory_issue_ids") or [])
    is_novel = bool(matching.get("is_novel"))
    if not ids:
        return {"available": True, "is_novel": is_novel, "n_hits": 0, "hits": []}
    corpus_path = _find_global_memory_corpus(repo)
    if not corpus_path:
        return {
            "available": True,
            "is_novel": is_novel,
            "n_hits": len(ids),
            "hits": [{"issue_id": i, "summary": "<corpus not found>"} for i in ids[:5]],
        }
    # Corpus rows are keyed by jira_shadow_issue_id (which matches the
    # values in matched_memory_issue_ids); jira_issue_key is the rendered
    # Jira ticket id for display.
    by_id = {
        r.get("jira_shadow_issue_id"): r for r in load_jsonl(corpus_path)
    }
    hits = []
    for i in ids[:5]:  # show top 5
        e = by_id.get(i, {})
        # The corpus stores a "summary" template instance under different
        # keys depending on which build script wrote it; try common ones.
        summary = (
            e.get("summary")
            or e.get("title")
            or e.get("jira_issue_key")
            or "<not in corpus>"
        )
        body = e.get("memory_text") or e.get("description") or ""
        hits.append(
            {
                "issue_id": i,
                "jira_key": e.get("jira_issue_key", ""),
                "summary": summary,
                "memory_text": body[:300],
            }
        )
    return {
        "available": True,
        "is_novel": is_novel,
        "n_hits": len(ids),
        "hits": hits,
    }


def _summarise_tempo(tempo_path: Path) -> dict:
    if not tempo_path.exists():
        return {"available": False}
    try:
        with tempo_path.open() as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"available": False, "error": "parse"}
    traces = doc.get("traces", {})
    if not isinstance(traces, dict):
        return {"available": False, "error": "no_traces"}
    n_spans = 0
    n_err = 0
    err_names: dict[str, int] = {}
    for _tid, t in traces.items():
        resp = t.get("response", {}) if isinstance(t, dict) else {}
        for batch in (resp.get("batches", []) if isinstance(resp, dict) else []) or []:
            for ss in batch.get("scopeSpans", []) or []:
                for span in ss.get("spans", []) or []:
                    n_spans += 1
                    status = span.get("status", {})
                    if isinstance(status, dict) and status.get("code") in (
                        "ERROR",
                        "STATUS_CODE_ERROR",
                        2,
                    ):
                        n_err += 1
                        nm = span.get("name", "?")
                        err_names[nm] = err_names.get(nm, 0) + 1
    top_err = sorted(err_names.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "available": True,
        "n_spans": n_spans,
        "n_error_spans": n_err,
        "top_error_spans": top_err,
    }


def render_evidence(rec: WindowRecord) -> str:
    ex = rec.triage_example
    safe = {k: v for k, v in ex.items() if k not in BLINDED_FIELDS}

    # Tier 1: window identification (no scenario info)
    head = [
        "=" * 72,
        f"WINDOW {rec.window_id}",
        "=" * 72,
        f"run_id      : {rec.run_id}",
        f"service     : {safe.get('service_name')}",
        f"window_type : {safe.get('window_type')}",
        f"start_time  : {safe.get('start_time')}",
        f"end_time    : {safe.get('end_time')}",
        "",
    ]

    # Tier 2: triage features (current vs delta)
    feats = sorted(k for k in safe if k.startswith("triage_feature_"))
    if feats:
        head.append("--- triage features (current value | delta from baseline) ---")
        for fk in feats:
            if fk.startswith("triage_feature_delta_"):
                continue
            cur = safe.get(fk)
            delta_key = "triage_feature_delta_" + fk[len("triage_feature_") :]
            delta = safe.get(delta_key)
            head.append(f"  {fk[len('triage_feature_'):]:30} {str(cur):>12} | {str(delta):>10}")
        head.append("")

    # Tier 3: log + trace summaries
    loki_path = rec.runs_dir / "raw" / "loki" / f"{rec.window_id}.json"
    tempo_path = rec.runs_dir / "raw" / "tempo" / f"{rec.window_id}.json"
    lsum = _summarise_loki(loki_path)
    tsum = _summarise_tempo(tempo_path)
    head.append("--- log summary (Loki) ---")
    if lsum.get("available"):
        head.append(f"  n_lines={lsum['n_lines']}  severity={lsum['severity_counts']}")
        if lsum["sample_errors"]:
            head.append("  sample error lines:")
            for s in lsum["sample_errors"]:
                head.append(f"    - {s}")
    else:
        head.append(f"  unavailable ({lsum.get('error', 'missing')})")
    head.append("")
    head.append("--- trace summary (Tempo) ---")
    if tsum.get("available"):
        head.append(
            f"  n_spans={tsum['n_spans']}  n_error_spans={tsum['n_error_spans']}"
        )
        if tsum["top_error_spans"]:
            head.append("  top error span names:")
            for nm, n in tsum["top_error_spans"]:
                head.append(f"    {n:>5}  {nm}")
    else:
        head.append(f"  unavailable ({tsum.get('error', 'missing')})")
    head.append("")

    # Tier 3.5: Jira memory hits (retrieval candidates)
    msum = _summarise_jira_memory_hits(rec.derived_dir.parent.parent.parent, rec)
    head.append("--- Jira memory hits (retrieval candidates) ---")
    if msum.get("available"):
        head.append(
            f"  is_novel={msum['is_novel']}  n_hits={msum['n_hits']}"
        )
        for h in msum.get("hits", []):
            key_label = h.get("jira_key") or h["issue_id"][:40]
            head.append(f"    [{key_label}] {h.get('summary', '')[:80]}")
            if h.get("memory_text"):
                head.append(f"      {h['memory_text'][:160]}")
    else:
        head.append(f"  unavailable ({msum.get('error', 'missing')})")
    head.append("")

    # Tier 4: existing-label provenance (if any)
    if rec.label_row:
        head.append(
            f"--- existing label provenance: source={rec.label_row.get('source')} "
            f"adjudicator={rec.label_row.get('adjudicator')} ---"
        )
    else:
        head.append("--- no existing label row ---")
    head.append("")
    return "\n".join(head)


# ----------------------------------------------------------------------------
# Capture + writeback
# ----------------------------------------------------------------------------


def prompt_label() -> dict:
    """Interactive prompt — returns a dict with label fields."""
    def _ask(prompt: str, valid: tuple[str, ...] | None = None) -> str:
        while True:
            v = input(prompt).strip()
            if not v:
                continue
            if valid and v not in valid:
                print(f"  invalid; expected one of {valid}")
                continue
            return v

    label = _ask(
        f"triage_label {VALID_LABELS}: ",
        VALID_LABELS,
    )
    out: dict[str, Any] = {"triage_label": label}
    if label == "ticket_worthy":
        out["triage_severity"] = _ask(
            f"triage_severity {VALID_SEVERITIES}: ",
            VALID_SEVERITIES,
        )
        out["triage_reason_class"] = _ask(
            f"triage_reason_class {VALID_REASON_CLASSES}: ",
            VALID_REASON_CLASSES,
        )
        comps = _ask("triage_components (comma-separated, >=1): ")
        out["triage_components"] = [c.strip() for c in comps.split(",") if c.strip()]
        if not out["triage_components"]:
            print("  must give at least one component for ticket_worthy")
            return prompt_label()
    else:
        out["triage_severity"] = None
        out["triage_reason_class"] = None
        out["triage_components"] = None
    out["rationale"] = input("rationale (free text): ").strip() or None
    return out


def build_label_row(
    rec: WindowRecord, label_fields: dict, adjudicator: str
) -> dict:
    ex = rec.triage_example
    base = dict(rec.label_row or {})
    # Required fields per schema
    base.update(
        {
            "telemetry_window_id": rec.window_id,
            "dataset_run_id": rec.run_id,
            "incident_episode_id": ex.get("incident_episode_id"),
            # Scenario info is preserved from the underlying example — we
            # blinded it from the reviewer's view but it stays in the labels
            # file for downstream comparison with the human label.
            "scenario_id": ex.get("scenario_id"),
            "scenario_family": ex.get("scenario_family"),
            "window_type": ex.get("window_type"),
            "is_hard_case": ex.get("is_hard_case", False),
            "source": "human_adjudicated",
            "adjudicator": adjudicator,
            "adjudicated_at": utc_now(),
            "derived_rule_id": None,
        }
    )
    base.update(label_fields)
    # Preserve labels:{} provenance bucket from existing row, or initialise.
    base.setdefault("labels", {})
    return base


def upsert_label(repo: Path, rec: WindowRecord, new_row: dict) -> None:
    path = repo / "data" / "derived" / rec.run_id / "triage_window_labels.jsonl"
    rows = load_label_rows(repo, rec.run_id)
    replaced = False
    out = []
    for r in rows:
        if r.get("telemetry_window_id") == rec.window_id:
            out.append(new_row)
            replaced = True
        else:
            out.append(r)
    if not replaced:
        out.append(new_row)
    write_jsonl(path, out)


# ----------------------------------------------------------------------------
# Status reporting
# ----------------------------------------------------------------------------


def status_summary(repo: Path, run_id: str | None) -> str:
    runs = [run_id] if run_id else list_runs(repo)
    lines = ["adjudication status:"]
    for rid in runs:
        examples = load_triage_examples(repo, rid)
        if not examples:
            continue
        labels = {
            l.get("telemetry_window_id"): l for l in load_label_rows(repo, rid)
        }
        n_total = len(examples)
        n_borderline = sum(1 for e in examples if e.get("triage_label") == "borderline")
        n_hard = sum(1 for e in examples if e.get("is_hard_case"))
        n_targets = n_borderline + n_hard  # may double-count overlap
        n_adj = sum(
            1
            for e in examples
            if (
                lr := labels.get(e.get("telemetry_window_id") or e.get("window_id"))
            )
            and lr.get("source") == "human_adjudicated"
        )
        lines.append(
            f"  {rid}: total={n_total} borderline={n_borderline} "
            f"hard={n_hard} human_adjudicated={n_adj}"
        )
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo-root", type=Path, default=None,
                   help="Repo root (default: auto-detect)")
    p.add_argument("--run", type=str, default=None,
                   help="Dataset run id")
    p.add_argument("--window", type=str, default=None,
                   help="Telemetry window id to adjudicate")
    p.add_argument("--next", dest="next_kind", choices=["borderline", "hard"],
                   help="Pick the next unadjudicated window of the given kind")
    p.add_argument("--adjudicator", type=str, default=None,
                   help="Reviewer identifier (required for non-dry runs)")
    p.add_argument("--label", choices=VALID_LABELS,
                   help="Non-interactive: assign this label without prompting")
    p.add_argument("--severity", choices=VALID_SEVERITIES,
                   help="Non-interactive: required when --label ticket_worthy")
    p.add_argument("--reason-class", choices=VALID_REASON_CLASSES,
                   help="Non-interactive: required when --label ticket_worthy")
    p.add_argument("--components", type=str,
                   help="Non-interactive: comma-separated, required when --label ticket_worthy")
    p.add_argument("--rationale", type=str, default=None,
                   help="Non-interactive: free-text rationale")
    p.add_argument("--dry-run", action="store_true",
                   help="Render evidence but do not prompt or write")
    p.add_argument("--status", action="store_true",
                   help="Print per-run adjudication status and exit")
    args = p.parse_args(argv)

    repo = args.repo_root.resolve() if args.repo_root else repo_root()

    if args.status:
        print(status_summary(repo, args.run))
        return 0

    if not args.run and args.window:
        print("ERROR: --window also requires --run (the script can't auto-locate without it)",
              file=sys.stderr)
        return 2
    if not args.run:
        print("ERROR: --run is required (or use --status)", file=sys.stderr)
        return 2

    if args.next_kind:
        rec = find_next_unadjudicated(repo, args.run, args.next_kind)
        if not rec:
            print(f"No unadjudicated {args.next_kind} windows remaining in {args.run}.")
            return 0
    else:
        if not args.window:
            print("ERROR: provide --window <id> or --next {borderline,hard}",
                  file=sys.stderr)
            return 2
        rec = find_window(repo, args.run, args.window)
        if not rec:
            print(f"ERROR: window {args.window} not found in run {args.run}",
                  file=sys.stderr)
            return 2

    print(render_evidence(rec))

    if args.dry_run:
        return 0

    if not args.adjudicator:
        print("ERROR: --adjudicator is required for non-dry runs", file=sys.stderr)
        return 2

    if args.label is None:
        label_fields = prompt_label()
    else:
        # Non-interactive path
        label_fields: dict[str, Any] = {"triage_label": args.label}
        if args.label == "ticket_worthy":
            if not (args.severity and args.reason_class and args.components):
                print("ERROR: --label ticket_worthy requires --severity, --reason-class, --components",
                      file=sys.stderr)
                return 2
            label_fields["triage_severity"] = args.severity
            label_fields["triage_reason_class"] = args.reason_class
            label_fields["triage_components"] = [
                c.strip() for c in args.components.split(",") if c.strip()
            ]
        else:
            label_fields["triage_severity"] = None
            label_fields["triage_reason_class"] = None
            label_fields["triage_components"] = None
        label_fields["rationale"] = args.rationale

    new_row = build_label_row(rec, label_fields, args.adjudicator)
    upsert_label(repo, rec, new_row)

    # Reveal the scenario-authored ground-truth label AFTER the human commits
    # — useful for the reviewer to spot-check their own calibration.
    print()
    print("--- written ---")
    print(
        f"  blind label     : {new_row['triage_label']}"
        + (f" ({new_row.get('triage_severity')})"
           if new_row.get("triage_severity") else "")
    )
    print(
        f"  scenario truth  : {rec.triage_example.get('triage_label')}"
        + (f" ({rec.triage_example.get('triage_severity')})"
           if rec.triage_example.get('triage_severity') else "")
    )
    print(f"  scenario_id     : {rec.triage_example.get('scenario_id')}")
    print(f"  scenario_family : {rec.triage_example.get('scenario_family')}")
    print(f"  source written  : human_adjudicated (adjudicator={args.adjudicator})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
