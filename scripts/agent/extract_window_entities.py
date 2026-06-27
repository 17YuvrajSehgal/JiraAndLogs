"""Run LLM entity extraction over a dataset's test windows.

Closes the asymmetric-extraction gap from Phase 3.1 of AGENTIC-SYSTEM
(RQ-A6). Reads `<global_dir>/global-triage-examples.jsonl`, filters to
the requested split(s) (manifest-aware), and runs
`extract_from_window` on each. Output:

    <global_dir>/v2_kg_extractions_windows/all_extractions.jsonl
        (one JSON row per extracted window — schema matches
         v2_advanced.proposal_d_knowledge_graph.extractor.WindowExtraction)

Per-window caching: the extractor writes one file per window under
`v2_kg_extractions_windows/<window_id>.json`; re-running this script
skips already-extracted windows. Safe to interrupt and resume.

Parallelism: --workers N runs N concurrent LLM calls through a
ThreadPoolExecutor. LMStudioClient is documented thread-safe (one
urllib request per call). With OpenAI gpt-4o-mini and workers=8, expect
~3-5 calls/sec depending on rate-limit tier.

Dataset-agnostic: works on OB, OTel Demo, and WoL (anything that has
`global-triage-examples.jsonl` + the resplit manifest format).

Usage (OpenAI):
    PYTHONPATH=src python scripts/agent/extract_window_entities.py \\
        --global-dir data/derived/global/2026-06-17-wol-real-v3-global \\
        --split all --workers 8 \\
        --lm-studio-url https://api.openai.com --model gpt-4o-mini \\
        --api-key-env OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.data_loaders.split_manifest import load_split_manifest, resolve_split


def _iter_test_windows(global_dir: Path, split: str, limit: int | None = None):
    """Yield (window_id, evidence_text, scenario_family, window_type)
    for windows in the given split, applying the v2-resplit manifest
    when present.

    split = 'all' yields every window regardless of split assignment.
    """
    examples_path = global_dir / "global-triage-examples.jsonl"
    if not examples_path.exists():
        raise FileNotFoundError(f"missing {examples_path}")

    manifest = load_split_manifest(global_dir)

    n_kept = 0
    with examples_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if split != "all" and resolve_split(row, manifest) != split:
                continue
            window_id = row.get("window_id")
            text = row.get("triage_evidence_text") or ""
            if not window_id or not text:
                continue
            yield {
                "window_id": window_id,
                "evidence_text": text,
                "family": row.get("scenario_family") or "",
                "severity": row.get("window_type") or "",
            }
            n_kept += 1
            if limit is not None and n_kept >= limit:
                return


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--split", default="test",
                   choices=["train", "validation", "test", "all"],
                   help="Which split's windows to extract; 'all' = every window.")
    p.add_argument("--workers", type=int, default=1,
                   help="Concurrent LLM calls. >1 uses a ThreadPoolExecutor.")
    p.add_argument("--shard", default=None,
                   help="Process only windows where hash(window_id) %% N == M, "
                        "given as 'M/N' (e.g. '0/2' = first half). Used to split work "
                        "across parallel processes (e.g. OpenAI + LM Studio).")
    p.add_argument("--max-input-chars", type=int, default=50000,
                   help="Truncate evidence_text above this length before the LLM call. "
                        "Default 50000 (~12.5K tokens), safe under a 25K-context LM Studio.")
    p.add_argument("--timeout-s", type=float, default=120.0,
                   help="Per-request HTTP timeout in seconds. Default 120. "
                        "For LM Studio: drop to 60-90 to fail fast on stuck calls.")
    p.add_argument("--max-retries", type=int, default=3,
                   help="Generic-error retry budget. Set to 0 on LM Studio so stuck "
                        "calls fail in `timeout-s` seconds instead of 4*timeout.")
    p.add_argument("--lm-studio-url", default="http://localhost:1234",
                   help="Base URL for the OpenAI-compatible chat-completions server. "
                        "Use https://api.openai.com for OpenAI proper.")
    p.add_argument("--model", default="local-model")
    p.add_argument("--api-key-env", default=None,
                   help="Name of env var holding the Bearer API key (e.g. OPENAI_API_KEY). "
                        "Unset → no auth header (local LM Studio).")
    p.add_argument("--max-tokens", type=int, default=600)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="v2_kg_extractions_windows")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("extract_window_entities")
    # Routine 429 backoffs are emitted at DEBUG by LMStudioClient. Suppress
    # them unless --verbose. Real errors (4xx non-429, 5xx, network) still
    # log at WARNING and above.
    if not args.verbose:
        logging.getLogger("v2_advanced.lm_studio").setLevel(logging.WARNING)

    cache_dir = args.global_dir / args.out_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    log.info("output cache dir: %s", cache_dir)

    # Lazy import — only need v2_advanced when we actually run.
    from v2_advanced.proposal_d_knowledge_graph.extractor import (
        extract_from_window,
    )
    from v2_advanced.shared import LMStudioClient
    from v2_advanced.shared.lm_studio import LMStudioConfig

    import os
    api_key = None
    if args.api_key_env:
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise SystemExit(
                f"--api-key-env={args.api_key_env} set, but that env var is empty.",
            )
        log.info("Using API key from env var %s (Bearer auth enabled).", args.api_key_env)
    cfg = LMStudioConfig(
        base_url=args.lm_studio_url,
        model=args.model,
        api_key=api_key,
        timeout_s=args.timeout_s,
        max_retries=args.max_retries,
    )
    client = LMStudioClient(cfg)
    if not client.is_available():
        raise SystemExit(
            f"LLM endpoint not reachable at {args.lm_studio_url}. "
            "If using OpenAI: verify --api-key-env points to a valid key. "
            "If using LM Studio: start the local server with a model loaded first.",
        )
    log.info("LLM endpoint reachable at %s (model=%s)", args.lm_studio_url, args.model)

    shard_m: int | None = None
    shard_n: int | None = None
    if args.shard:
        try:
            m_str, n_str = args.shard.split("/")
            shard_m, shard_n = int(m_str), int(n_str)
            if shard_m < 0 or shard_n <= 0 or shard_m >= shard_n:
                raise ValueError("out of range")
        except ValueError:
            raise SystemExit(
                f"--shard must be 'M/N' with 0 <= M < N (got {args.shard!r})",
            )

    windows = list(_iter_test_windows(
        args.global_dir, args.split,
        limit=args.limit if args.limit > 0 else None,
    ))
    if shard_n is not None:
        import hashlib
        n_before = len(windows)
        windows = [
            w for w in windows
            if (int(hashlib.sha1(w["window_id"].encode("utf-8")).hexdigest(), 16) % shard_n) == shard_m
        ]
        log.info("shard %d/%d: %d/%d windows in this shard",
                 shard_m, shard_n, len(windows), n_before)

    # Truncate oversized evidence_text so LM Studio's 25K context isn't exceeded.
    n_trunc = 0
    if args.max_input_chars > 0:
        for w in windows:
            if len(w["evidence_text"]) > args.max_input_chars:
                w["evidence_text"] = (
                    w["evidence_text"][: args.max_input_chars]
                    + "\n[... truncated due to context limit]"
                )
                n_trunc += 1
        if n_trunc:
            log.info("truncated %d oversized windows to <= %d chars",
                     n_trunc, args.max_input_chars)
    log.info(
        "extracting from %d windows (split=%s) — output to %s",
        len(windows), args.split, cache_dir,
    )

    t_start = time.time()
    n_failed_or_empty = 0
    extractions: list[dict] = []

    def _extract_one(w):
        try:
            ext = extract_from_window(
                client,
                window_id=w["window_id"],
                evidence_text=w["evidence_text"],
                severity=w["severity"],
                family=w["family"],
                cache_dir=cache_dir,
                max_tokens=args.max_tokens,
            )
            return ext, None
        except Exception as e:                                       # noqa: BLE001
            return None, (w["window_id"], e)

    if args.workers <= 1:
        # Sequential path (legacy behaviour)
        for i, w in enumerate(windows, start=1):
            ext, err = _extract_one(w)
            if err is not None:
                log.warning("extraction failed for %s: %s", err[0], err[1])
                n_failed_or_empty += 1
                continue
            if not (ext.affected_services or ext.error_classes or ext.symptoms):
                n_failed_or_empty += 1
            extractions.append(ext.as_dict())
            if i % 10 == 0:
                elapsed = time.time() - t_start
                avg = elapsed / i
                eta_min = (len(windows) - i) * avg / 60.0
                log.info(
                    "progress: done=%d/%d empty_or_failed=%d avg=%.2fs/w eta=%.1fmin",
                    i, len(windows), n_failed_or_empty, avg, eta_min,
                )
    else:
        # Parallel path
        log.info("parallel mode: workers=%d", args.workers)
        n_done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_extract_one, w): w for w in windows}
            for fut in as_completed(futures):
                ext, err = fut.result()
                n_done += 1
                if err is not None:
                    log.warning("extraction failed for %s: %s", err[0], err[1])
                    n_failed_or_empty += 1
                    continue
                if not (ext.affected_services or ext.error_classes or ext.symptoms):
                    n_failed_or_empty += 1
                extractions.append(ext.as_dict())
                if n_done % 100 == 0:
                    elapsed = time.time() - t_start
                    rate = n_done / elapsed if elapsed > 0 else 0.0
                    eta_min = (len(windows) - n_done) / rate / 60.0 if rate > 0 else float("inf")
                    log.info(
                        "progress: done=%d/%d empty_or_failed=%d rate=%.2f/s eta=%.1fmin",
                        n_done, len(windows), n_failed_or_empty, rate, eta_min,
                    )

    # Consolidated output
    consolidated = cache_dir / "all_extractions.jsonl"
    with consolidated.open("w", encoding="utf-8") as fh:
        for ext in extractions:
            fh.write(json.dumps(ext) + "\n")
    log.info("wrote consolidated: %s (%d rows)",
             consolidated, len(extractions))

    n_with_services = sum(1 for e in extractions if e.get("affected_services"))
    n_with_errors = sum(1 for e in extractions if e.get("error_classes"))
    n_with_symptoms = sum(1 for e in extractions if e.get("symptoms"))
    print()
    print("=" * 70)
    print(f"  Window extraction — {args.global_dir.name} ({args.split})")
    print("=" * 70)
    print(f"  total                  {len(extractions)}")
    print(f"  with affected_services {n_with_services}")
    print(f"  with error_classes     {n_with_errors}")
    print(f"  with symptoms          {n_with_symptoms}")
    print(f"  empty / failed         {n_failed_or_empty}")
    print(f"  output                 {consolidated}")
    print("=" * 70)
    print(f"  Next step: re-run smoke_wol.py — the loader auto-detects")
    print(f"  v2_kg_extractions_windows/ and sets KG_GRAPH_WINDOW=True.")


if __name__ == "__main__":
    main()
