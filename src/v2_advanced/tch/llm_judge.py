"""G5 — Per-window LLM judge reranker.

For each test window, ask Qwen 35B (with thinking enabled) which of the
cascade's top-5 candidates best matches the window evidence. Use the
answer to confidence-gate-override position 1.

Output: <out>/llm_judge_outputs.jsonl with rows
  {window_id, best_idx, confidence, reasoning, original_top5, suggested_top5}

The cascade integration is handled separately via build_cascade.py's
TCH_LLM_JUDGE_PATH env var (added in this commit).

Usage:
    PYTHONPATH=src python -m v2_advanced.tch.llm_judge \\
        --cascade-predictions data/derived/global/.../v2g-final-models/g4-agent-phase3/cascade/per-window-predictions.jsonl \\
        --extractions data/derived/global/.../v2_kg_extractions/all_extractions.jsonl \\
        --humanized-dir data/derived/global/.../jira-shadow-humanized-v2/bulk-20260531 \\
        --out data/derived/global/.../v2g-final-models/g5-llm-judge-reranker/llm_judge_outputs.jsonl
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from v2_advanced.shared import LMStudioClient, get_logger, log_step
from v2_advanced.shared.lm_studio import LMStudioConfig, LMStudioError
from v2_advanced.shared.json_schemas import response_format

log = get_logger("tch.llm_judge")


JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "best_idx": {
            "type": "integer",
            "minimum": 0,
            "maximum": 4,
            "description": "0-based index of the candidate that BEST matches the window evidence.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "0-1 confidence in your choice. 1.0 = certain, 0.5 = could be either.",
        },
        "reasoning": {
            "type": "string",
            "description": "One short sentence explaining the pick.",
        },
    },
    "required": ["best_idx", "confidence", "reasoning"],
    "additionalProperties": False,
}

JUDGE_RF = response_format(JUDGE_SCHEMA, name="tch_llm_judge")


JUDGE_SYSTEM = """You are an SRE incident-matching assistant.

Given:
  - A window of live telemetry (logs + metrics).
  - 5 candidate past Jira tickets (each with id, root cause summary, affected services).

Your job: pick the candidate whose root cause is MOST CONSISTENT with the live evidence. If multiple candidates are plausible, pick the most specific match.

Output EXACTLY this JSON shape:
{
  "best_idx": 0-4,
  "confidence": 0.0-1.0,
  "reasoning": "one short sentence"
}

Output VALID JSON only — no markdown, no extra text."""


def _load_humanized_titles(humanized_dir: Path) -> dict[str, str]:
    """Map ticket_id -> short title from humanized timeline."""
    titles: dict[str, str] = {}
    timeline_path = humanized_dir / "timeline.jsonl"
    if not timeline_path.exists():
        return titles
    with timeline_path.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            tid = d.get("ticket_id")
            title = (d.get("title") or "").strip()
            if tid and title:
                titles[tid] = title[:120]
    return titles


def _load_extractions(extractions_path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not extractions_path.exists():
        return out
    with extractions_path.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            tid = d.get("ticket_id")
            if tid:
                out[tid] = d
    return out


def _build_judge_user(
    window_evidence: str,
    candidates: list[dict[str, Any]],
    max_evidence_chars: int = 4000,
) -> str:
    cand_lines = []
    for i, c in enumerate(candidates):
        ticket_id = c.get("ticket_id", "")
        title = c.get("title", "")
        root_cause = c.get("root_cause", "")
        services = ",".join(c.get("affected_services") or []) or "(none)"
        cand_lines.append(
            f"[{i}] {ticket_id}\n"
            f"    title: {title[:120]}\n"
            f"    root_cause: {root_cause[:200]}\n"
            f"    services: {services[:80]}"
        )
    cand_text = "\n\n".join(cand_lines)
    return (
        f"WINDOW EVIDENCE:\n{window_evidence[:max_evidence_chars]}\n\n"
        f"CANDIDATES (5):\n{cand_text}\n\n"
        f"Pick the best match. Return JSON."
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cascade-predictions", type=Path, required=True,
                   help="JSONL with the cascade's top-5 per window")
    p.add_argument("--extractions", type=Path, required=True,
                   help="LLM ticket extractions JSONL (for root_cause/services)")
    p.add_argument("--humanized-dir", type=Path, required=True,
                   help="dir with timeline.jsonl for ticket titles")
    p.add_argument("--global-dir", type=Path, required=True,
                   help="root global dir (for loading window evidence text)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--lm-studio-url", default="http://localhost:1234")
    p.add_argument("--model", default="local-model")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--max-tokens", type=int, default=1500)
    args = p.parse_args()

    # Load supporting data
    log.info("loading humanized titles", path=str(args.humanized_dir))
    titles = _load_humanized_titles(args.humanized_dir)
    log.info("titles loaded", n=len(titles))

    log.info("loading ticket extractions", path=str(args.extractions))
    extractions = _load_extractions(args.extractions)
    log.info("extractions loaded", n=len(extractions))

    # Load cascade predictions
    cascade_rows = []
    with args.cascade_predictions.open(encoding="utf-8") as fh:
        for line in fh:
            cascade_rows.append(json.loads(line))
    log.info("cascade predictions loaded", n=len(cascade_rows))

    if args.limit > 0:
        cascade_rows = cascade_rows[: args.limit]

    # Load windows to get evidence text
    from core.data.loaders import load_dataset
    from core.features.text import build_window_query_text
    ds = load_dataset(args.global_dir)
    window_by_id = {w.window_id: w for w in ds.windows}

    cfg = LMStudioConfig(base_url=args.lm_studio_url, model=args.model)
    client = LMStudioClient(cfg)
    if not client.is_available():
        raise SystemExit(
            f"LM Studio not reachable at {args.lm_studio_url}"
        )
    log.info("LM Studio reachable")

    args.out.parent.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    n_judged = n_skipped = n_failed = 0
    n_override = 0

    with args.out.open("w", encoding="utf-8") as out_fh:
        for i, row in enumerate(cascade_rows, start=1):
            wid = row.get("window_id")
            top5 = row.get("matched_issue_ids") or []
            if not wid or len(top5) < 2:
                n_skipped += 1
                continue
            window = window_by_id.get(wid)
            if window is None:
                n_skipped += 1
                continue
            evidence = build_window_query_text(window) or ""
            if not evidence:
                n_skipped += 1
                continue

            # Build candidate context
            candidates = []
            for tid in top5[:5]:
                ext = extractions.get(tid, {})
                candidates.append({
                    "ticket_id": tid,
                    "title": titles.get(tid, ""),
                    "root_cause": ext.get("root_cause", ""),
                    "affected_services": ext.get("affected_services") or [],
                })

            user_msg = _build_judge_user(evidence, candidates)

            try:
                obj = client.chat_json(
                    system=JUDGE_SYSTEM,
                    user=user_msg,
                    temperature=0.0,
                    max_tokens=args.max_tokens,
                    response_format=JUDGE_RF,
                    enable_thinking=True,
                )
            except LMStudioError as e:
                log.warning("judge failed", window=wid, err=str(e)[:120])
                n_failed += 1
                continue

            best_idx = int(obj.get("best_idx", 0))
            best_idx = max(0, min(4, best_idx))
            confidence = float(obj.get("confidence", 0.0))
            reasoning = str(obj.get("reasoning", "") or "")[:300]

            # Build suggested top-5 (swap if judge picked non-0)
            if best_idx != 0:
                suggested_top5 = [top5[best_idx]] + [t for t in top5 if t != top5[best_idx]][:4]
                n_override += 1
            else:
                suggested_top5 = list(top5)

            out_fh.write(json.dumps({
                "window_id": wid,
                "best_idx": best_idx,
                "confidence": confidence,
                "reasoning": reasoning,
                "original_top5": list(top5),
                "suggested_top5": suggested_top5,
            }) + "\n")
            n_judged += 1

            if i % 25 == 0:
                elapsed = time.time() - t_start
                avg = elapsed / i
                eta_min = (len(cascade_rows) - i) * avg / 60.0
                log.info(
                    "judge progress",
                    done=i,
                    total=len(cascade_rows),
                    judged=n_judged,
                    failed=n_failed,
                    skipped=n_skipped,
                    override_so_far=n_override,
                    avg_s_per_window=round(avg, 2),
                    eta_min=round(eta_min, 1),
                )

    log.info(
        "judge done",
        total=len(cascade_rows),
        judged=n_judged,
        failed=n_failed,
        skipped=n_skipped,
        override=n_override,
        elapsed_min=round((time.time() - t_start) / 60.0, 1),
    )


if __name__ == "__main__":
    main()
