"""Parallel driver for extract_from_ticket on WoL Mode 3.

The stock extract_tickets_cli runs sequentially — ~15 sec/ticket against
qwen/qwen3.6-35b-a3b on LM Studio means ~8 h for 2000 tickets. LM Studio
serves up to 4 parallel requests (`PARALLEL 4`). LMStudioClient is
documented thread-safe ("stateless; safe to share across threads — one
urllib request per call", src/v2_advanced/shared/lm_studio.py:87-89),
so a ThreadPoolExecutor with workers=4 gives a ~4× speedup → ~2 h ETA.

Output format is bit-identical to extract_tickets_cli:
    data/derived/global/<id>/v2_kg_extractions/ticket/*.json
    data/derived/global/<id>/v2_kg_extractions/all_extractions.jsonl

Cache hits short-circuit the LLM call (per extract_from_ticket), so
re-runs are cheap and interrupted runs resume by skipping cached tickets.

Usage:
    PYTHONPATH=src python scripts/research-lab/extract_tickets_parallel.py \\
        --global-dir data/derived/global/2026-06-15-wol-real-v2-global \\
        --humanized-subdir bulk-20260611 \\
        --model qwen/qwen3.6-35b-a3b \\
        --workers 4
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


_FAMILY_SLUG = re.compile(r"-r\d+-(.+?)-202\d{5}T\d{6}Z")


def _family_from_episode(eid: str) -> str:
    m = _FAMILY_SLUG.search(eid or "")
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path, required=True)
    ap.add_argument("--humanized-root",  default="jira-shadow-humanized-v2")
    ap.add_argument("--humanized-subdir", default="bulk-20260531")
    ap.add_argument("--lm-studio-url", default="http://localhost:1234")
    ap.add_argument("--model", default="local-model")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="v2_kg_extractions")
    args = ap.parse_args()

    sys.path.insert(0, "src")

    from memorygraph.humanized_loader import load_humanized_corpus
    from v2_advanced.shared.lm_studio import LMStudioConfig
    from v2_advanced.shared import LMStudioClient
    from v2_advanced.proposal_d_knowledge_graph.extractor import extract_from_ticket
    from v2_advanced.proposal_d_knowledge_graph.schema import IncidentExtraction

    cache_dir = args.global_dir / args.out
    (cache_dir / "ticket").mkdir(parents=True, exist_ok=True)

    issues = load_humanized_corpus(
        args.global_dir,
        humanized_subdir=args.humanized_subdir,
        humanized_root=args.humanized_root,
    )
    print(f"[parallel] loaded {len(issues)} humanized tickets", flush=True)

    tickets = []
    for iss in issues:
        tickets.append({
            "ticket_id":          iss.jira_shadow_issue_id,
            "memory_text":        iss.memory_text or "",
            "severity_seen":      iss.severity or "",
            "source_episode_id":  iss.incident_episode_id or "",
            "scenario_family":    iss.scenario_family or "",
        })

    if args.limit > 0:
        tickets = tickets[: args.limit]
        print(f"[parallel] limited to {len(tickets)} tickets", flush=True)

    cfg = LMStudioConfig(base_url=args.lm_studio_url, model=args.model)
    client = LMStudioClient(cfg)
    if not client.is_available():
        raise SystemExit(f"LM Studio unreachable at {args.lm_studio_url}")
    print(f"[parallel] LM Studio reachable; model={args.model}", flush=True)

    n_done = 0
    n_cached = 0
    n_failed = 0
    n_lock_progress = [0]
    t0 = time.time()

    def _extract_one(t: dict) -> IncidentExtraction:
        tid = t["ticket_id"]
        text = t["memory_text"]
        sev = t["severity_seen"]
        ts = t["source_episode_id"]
        fam = t["scenario_family"] or _family_from_episode(ts)
        # Pre-check cache so we account for cached vs fresh accurately.
        cf = cache_dir / "ticket" / f"{tid}__{__import__('hashlib').sha1(text.encode('utf-8')).hexdigest()[:8]}.json"
        was_cached = cf.exists()
        ext = extract_from_ticket(
            client,
            ticket_id=tid,
            ticket_text=text,
            severity=sev,
            family=fam,
            timestamp=ts,
            cache_dir=cache_dir,
        )
        return ext, was_cached

    extractions: list[IncidentExtraction] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_extract_one, t): t for t in tickets}
        for fut in as_completed(futures):
            try:
                ext, was_cached = fut.result()
            except Exception as e:
                t = futures[fut]
                print(f"[parallel] failed: {t['ticket_id']}: {type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
                n_failed += 1
                continue
            extractions.append(ext)
            n_done += 1
            if was_cached:
                n_cached += 1
            if n_done - n_lock_progress[0] >= 20:
                elapsed = time.time() - t0
                rate = n_done / elapsed if elapsed > 0 else 0.0
                remaining = len(tickets) - n_done
                eta_min = (remaining / rate / 60.0) if rate > 0 else float('inf')
                print(f"[parallel] progress  done={n_done}/{len(tickets)}  "
                      f"cached={n_cached}  fresh={n_done-n_cached}  failed={n_failed}  "
                      f"rate={rate:.2f}/s  eta_min={eta_min:.1f}",
                      flush=True)
                n_lock_progress[0] = n_done

    elapsed = time.time() - t0
    print(f"[parallel] done in {elapsed:.1f}s  total={len(extractions)}  "
          f"cached={n_cached}  fresh={len(extractions)-n_cached}  failed={n_failed}",
          flush=True)

    # Stats
    n_with_services = sum(1 for e in extractions if e.affected_services)
    n_with_errors = sum(1 for e in extractions if e.error_classes)
    n_with_root_cause = sum(1 for e in extractions if e.root_cause)
    n_with_symptoms = sum(1 for e in extractions if e.symptoms)
    n_empty = sum(1 for e in extractions
                  if not (e.affected_services or e.error_classes or e.root_cause or e.symptoms))
    print(f"[parallel] extraction summary  total={len(extractions)} "
          f"with_services={n_with_services} with_errors={n_with_errors} "
          f"with_root_cause={n_with_root_cause} with_symptoms={n_with_symptoms} "
          f"empty={n_empty}", flush=True)

    # Consolidate
    consolidated = cache_dir / "all_extractions.jsonl"
    with consolidated.open("w", encoding="utf-8") as fh:
        for ext in extractions:
            fh.write(json.dumps(ext.as_dict()) + "\n")
    print(f"[parallel] consolidated extractions written to {consolidated}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
