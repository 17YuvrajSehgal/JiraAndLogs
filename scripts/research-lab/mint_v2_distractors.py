#!/usr/bin/env python3
"""Mint V2 distractor tickets (LLM-Jira-enhancement.md §13.5 + §13.8 step 5).

Three sourcing strategies (per §13.5):
  - TAWOS-sampled    — real engineer prose pulled from local MySQL,
                       project nouns scrubbed. NO LLM. Fast.
  - in-arch-never    — LLM-generated fake incidents in OUR services
                       that we never injected. Hardest distractors.
  - cross-arch       — LLM-generated incidents in components we don't
                       have (Kafka, Spark, Postgres, etc.).

Output dir: `data/derived/global/<global-id>/jira-shadow-humanized-v2-distractors/mint-<UTC date>/`
  timeline.jsonl                # one row per distractor
  generation-manifest.json      # llm config, usage stats, source breakdown

All output rows carry `is_distractor=true`. Mix them into the main V2
corpus at evaluation time — the agent never sees the flag at retrieval.

Usage:
    # full mint targeting ~25% distractor share (110 distractors total)
    python scripts/research-lab/mint_v2_distractors.py

    # smoke test with small counts
    python scripts/research-lab/mint_v2_distractors.py --n-tawos 5 --n-in-arch 3 --n-cross-arch 3

    # TAWOS-only (no LLM call)
    python scripts/research-lab/mint_v2_distractors.py --n-in-arch 0 --n-cross-arch 0
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_humanizer.distractors import (  # noqa: E402
    CROSS_ARCH_DISTRACTOR_SPECS,
    DISTRACTOR_GENERATOR_VERSION,
    DistractorLLMConfig,
    DistractorUsageStats,
    IN_ARCH_DISTRACTOR_SPECS,
    _pull_tawos_distractors,
    generate_synthetic_distractor,
    tawos_row_to_ticket,
)
from jira_humanizer.sanitizer import find_lab_tokens  # noqa: E402
from jira_humanizer.timeline_schema import TicketTimeline  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-id",
                   default="2026-05-25-dataset-v5-large-global")
    p.add_argument("--derived-root",
                   default=str(_REPO_ROOT / "data" / "derived" / "global"))
    p.add_argument("--output-subdir", default=None,
                   help="Defaults to mint-<UTC date>.")
    p.add_argument("--n-tawos", type=int, default=60,
                   help="TAWOS-sampled distractor count.")
    p.add_argument("--n-in-arch", type=int, default=25,
                   help="In-arch-never-happened distractor count.")
    p.add_argument("--n-cross-arch", type=int, default=25,
                   help="Cross-arch distractor count.")
    p.add_argument("--llm-base-url", default="http://localhost:1234")
    p.add_argument("--llm-model", default="qwen/qwen2.5-coder-14b")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--mysql-host", default="127.0.0.1")
    p.add_argument("--mysql-user", default="root")
    p.add_argument("--mysql-password", default="root")
    p.add_argument("--mysql-database", default="tawos")
    p.add_argument("--tawos-seed", type=int, default=20260601,
                   help="ORDER BY RAND(seed) for deterministic re-runs.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    global_dir = Path(args.derived_root) / args.global_id
    if not global_dir.exists():
        print(f"ERROR: {global_dir} not found", file=sys.stderr)
        return 2

    if args.output_subdir is None:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        args.output_subdir = f"mint-{today}"
    out_dir = global_dir / "jira-shadow-humanized-v2-distractors" / args.output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    timeline_path = out_dir / "timeline.jsonl"

    print(f"[distractors] output: {out_dir.relative_to(global_dir)}",
          file=sys.stderr)
    print(
        f"[distractors] targets: tawos={args.n_tawos} "
        f"in-arch={args.n_in_arch} cross-arch={args.n_cross_arch}",
        file=sys.stderr,
    )

    all_tickets: list[TicketTimeline] = []
    source_counts = {"tawos": 0, "in-arch-never": 0, "cross-arch": 0}
    n_tawos_skipped_leak = 0

    # ---- Phase A — TAWOS-sampled
    if args.n_tawos > 0:
        import pymysql
        import pymysql.cursors
        conn = pymysql.connect(
            host=args.mysql_host, user=args.mysql_user,
            password=args.mysql_password, database=args.mysql_database,
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            print(f"[distractors] phase A: pulling {args.n_tawos} TAWOS rows ...",
                  file=sys.stderr)
            tawos_rows = _pull_tawos_distractors(
                args.n_tawos, mysql_conn=conn, seed=args.tawos_seed,
            )
            print(f"[distractors]   got {len(tawos_rows)} rows after sanitizer filter",
                  file=sys.stderr)
            for row in tawos_rows:
                ticket = tawos_row_to_ticket(row)
                # Final leak check — concat the user-visible TEXT fields
                # only (not JSON keys; `source_dataset_run_id` etc. are
                # field names that happen to contain banned tokens).
                text_only = "\n".join([
                    ticket.ticket_id,
                    ticket.description_code or "",
                    *[s.text or "" for s in ticket.steps],
                    *[s.body_code or "" for s in ticket.steps],
                ])
                if find_lab_tokens(text_only):
                    n_tawos_skipped_leak += 1
                    continue
                all_tickets.append(ticket)
                source_counts["tawos"] += 1
        finally:
            conn.close()

    # ---- Phase B — in-arch-never-happened (LLM)
    in_arch_stats = DistractorUsageStats()
    if args.n_in_arch > 0:
        llm_cfg = DistractorLLMConfig(
            base_url=args.llm_base_url, model=args.llm_model,
            temperature=args.temperature,
        )
        specs = IN_ARCH_DISTRACTOR_SPECS[: args.n_in_arch]
        print(f"[distractors] phase B: generating {len(specs)} in-arch-never via LLM ...",
              file=sys.stderr)
        for i, spec in enumerate(specs, 1):
            t = generate_synthetic_distractor(
                spec, cfg=llm_cfg, stats=in_arch_stats,
            )
            if t is not None:
                all_tickets.append(t)
                source_counts["in-arch-never"] += 1
            if i % 5 == 0:
                print(f"[distractors]   in-arch {i}/{len(specs)} done", file=sys.stderr)

    # ---- Phase C — cross-arch (LLM)
    cross_stats = DistractorUsageStats()
    if args.n_cross_arch > 0:
        llm_cfg = DistractorLLMConfig(
            base_url=args.llm_base_url, model=args.llm_model,
            temperature=args.temperature,
        )
        specs = CROSS_ARCH_DISTRACTOR_SPECS[: args.n_cross_arch]
        print(f"[distractors] phase C: generating {len(specs)} cross-arch via LLM ...",
              file=sys.stderr)
        for i, spec in enumerate(specs, 1):
            t = generate_synthetic_distractor(
                spec, cfg=llm_cfg, stats=cross_stats,
            )
            if t is not None:
                all_tickets.append(t)
                source_counts["cross-arch"] += 1
            if i % 5 == 0:
                print(f"[distractors]   cross-arch {i}/{len(specs)} done", file=sys.stderr)

    # ---- Write timeline.jsonl
    with timeline_path.open("w", encoding="utf-8") as fh:
        for t in all_tickets:
            fh.write(json.dumps(t.as_jsonl_row(), default=str) + "\n")
    print(
        f"[distractors] wrote {timeline_path.relative_to(global_dir)} "
        f"({len(all_tickets)} distractors)",
        file=sys.stderr,
    )

    # ---- Manifest
    manifest = {
        "global_id": args.global_id,
        "output_subdir": args.output_subdir,
        "minted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "generator_version": DISTRACTOR_GENERATOR_VERSION,
        "targets": {
            "n_tawos": args.n_tawos,
            "n_in_arch": args.n_in_arch,
            "n_cross_arch": args.n_cross_arch,
        },
        "actuals": {
            "n_total": len(all_tickets),
            **source_counts,
            "tawos_skipped_for_leak": n_tawos_skipped_leak,
        },
        "llm": {
            "base_url": args.llm_base_url,
            "model": args.llm_model,
            "temperature": args.temperature,
        },
        "llm_usage_in_arch":   in_arch_stats.as_dict(),
        "llm_usage_cross_arch": cross_stats.as_dict(),
        "tawos_query": {
            "host": args.mysql_host, "database": args.mysql_database,
            "rand_seed": args.tawos_seed,
        },
    }
    (out_dir / "generation-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8",
    )

    print(
        f"\n[distractors] DONE: {len(all_tickets)} distractors "
        f"(tawos={source_counts['tawos']}, "
        f"in-arch={source_counts['in-arch-never']}, "
        f"cross-arch={source_counts['cross-arch']})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
