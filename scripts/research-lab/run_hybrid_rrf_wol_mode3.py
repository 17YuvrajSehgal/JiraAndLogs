"""Run Hybrid-RRF (SPLADE + BiEncoder + Graph, RRF fusion) on WoL Mode 3.

Mirror of run_biencoder_wol_mode3.py / run_logseq2vec_wol_mode3.py.

Prerequisites:
    * LLM ticket extractions cached at v2_kg_extractions/ticket/*.json
    * `reload_neo4j.py` has populated Neo4j with the ticket entities
    * Neo4j reachable at neo4j://127.0.0.1:7687

The pipeline's `skip_window_extraction=True` default means window-side
entities come from rule-based extraction (no per-window LLM calls).

Outputs:
    <out>/hybrid-rrf-predictions.jsonl
    <out>/hybrid-rrf-mode3-results.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

# Configure root logger so every INFO from internal pipelines is visible on
# stdout. Without this, fine-tune / fusion progress is silently dropped.
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)


# Mutable singleton the main thread updates; heartbeat thread reads it.
_HEARTBEAT_PHASE: dict[str, str] = {"name": "starting"}


def _set_phase(name: str) -> None:
    _HEARTBEAT_PHASE["name"] = name
    print(f"[hybrid-rrf:phase] -> {name}", flush=True)


def _start_heartbeat(label: str = "hybrid-rrf", every_seconds: float = 30.0) -> threading.Event:
    """Spawn a daemon thread that prints "[<label>:heartbeat] ..." every
    `every_seconds` so the log file never goes silent for >30s during
    long internal training loops."""
    stop = threading.Event()
    t0 = time.time()

    try:
        import psutil  # type: ignore
        proc = psutil.Process(os.getpid())
    except Exception:                                                # noqa: BLE001
        proc = None

    def _ram_gb() -> str:
        if proc is None:
            return "?"
        try:
            return f"{proc.memory_info().rss / (1024**3):.2f}"
        except Exception:                                            # noqa: BLE001
            return "?"

    def _run() -> None:
        n = 0
        while not stop.wait(every_seconds):
            n += 1
            elapsed = time.time() - t0
            mins = elapsed / 60.0
            print(
                f"[{label}:heartbeat] tick={n} elapsed={mins:6.1f}min "
                f"rss={_ram_gb()}GB phase={_HEARTBEAT_PHASE['name']}",
                flush=True,
            )

    th = threading.Thread(target=_run, daemon=True, name="heartbeat")
    th.start()
    return stop


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global-dir", type=Path,
                    default=Path("data/derived/global/2026-06-15-wol-real-v2-global"))
    ap.add_argument("--out-dir", type=Path,
                    default=Path("data/derived/global/2026-06-15-wol-real-v2-global/tch-lite-refit"))
    ap.add_argument("--humanized-subdir", default="bulk-20260611")
    ap.add_argument("--humanized-root",   default="jira-shadow-humanized-v2")
    ap.add_argument("--biencoder-finetune-epochs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    heartbeat_stop = _start_heartbeat(label="hybrid-rrf", every_seconds=30.0)
    _set_phase("imports")

    sys.path.insert(0, "src")

    from v2_advanced.proposal_c_hybrid_retrieval.pipeline import HybridRRFRetrievalPipeline
    from core.data.loaders import load_dataset

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[hybrid-rrf] global_dir = {args.global_dir}")
    print(f"[hybrid-rrf] biencoder_finetune_epochs={args.biencoder_finetune_epochs}")
    print()

    _set_phase("instantiate_pipeline")
    pipeline = HybridRRFRetrievalPipeline(
        humanized_subdir=args.humanized_subdir,
        humanized_root=args.humanized_root,
        biencoder_finetune_epochs=args.biencoder_finetune_epochs,
        skip_window_extraction=True,  # rule-based windows (no LLM calls per window)
        skip_graph=False,
        seed=args.seed,
    )

    _set_phase(f"train_and_predict (bienc_epochs={args.biencoder_finetune_epochs})")
    t0 = time.time()
    result = pipeline.train_and_predict(
        global_dir=args.global_dir,
        runs_root=Path("data/runs"),
        target_fpr=0.05,
    )
    wall = time.time() - t0
    _set_phase("post_predict")
    print(f"\n[hybrid-rrf] fit+predict completed in {wall:.1f}s "
          f"(fit={result.fit_seconds:.1f}s, predict={result.predict_seconds:.1f}s)",
          flush=True)
    print(f"[hybrid-rrf] {len(result.predictions)} test predictions", flush=True)

    _set_phase("write_predictions")
    pred_path = args.out_dir / "hybrid-rrf-predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as fh:
        for p in result.predictions:
            fh.write(json.dumps(p.as_dict(), default=str, ensure_ascii=False) + "\n")
    print(f"[hybrid-rrf] wrote predictions to {pred_path}", flush=True)

    strong_path = args.global_dir / "window-memory-matchings-strong.jsonl"
    strong_gold = {}
    if strong_path.exists():
        for line in strong_path.open(encoding="utf-8"):
            d = json.loads(line)
            strong_gold[d["window_id"]] = set(d.get("matched_memory_issue_ids") or [])
    print(f"[hybrid-rrf] loaded strong-match gold for {len(strong_gold)} windows")

    def metrics(predictions, gold_lookup, label):
        h1 = h5 = n = 0
        mrr_sum = 0.0
        per_proj_stats = defaultdict(lambda: {"n": 0, "h1": 0, "h5": 0, "mrr_sum": 0.0})
        ds = load_dataset(args.global_dir)
        proj_by_wid = {w.window_id: getattr(w, "scenario_family", "?") for w in ds.windows}

        for p in predictions:
            wid = p.window_id
            gold = set(p.gold_matched_issue_ids or []) if gold_lookup is None else gold_lookup.get(wid, set())
            if not gold:
                continue
            n += 1
            top = list(p.matched_issue_ids or [])
            proj = proj_by_wid.get(wid, "?")
            per_proj_stats[proj]["n"] += 1
            for i, t in enumerate(top, 1):
                if t in gold:
                    if i == 1:
                        h1 += 1
                        per_proj_stats[proj]["h1"] += 1
                    if i <= 5:
                        h5 += 1
                        per_proj_stats[proj]["h5"] += 1
                    mrr_sum += 1.0 / i
                    per_proj_stats[proj]["mrr_sum"] += 1.0 / i
                    break

        return {
            "label":       label,
            "n_with_gold": n,
            "hit_at_1":    h1 / max(1, n),
            "hit_at_5":    h5 / max(1, n),
            "mrr":         mrr_sum / max(1, n),
            "per_project": {
                proj: {
                    "n":        v["n"],
                    "hit_at_1": v["h1"] / max(1, v["n"]),
                    "hit_at_5": v["h5"] / max(1, v["n"]),
                    "mrr":      v["mrr_sum"] / max(1, v["n"]),
                }
                for proj, v in per_proj_stats.items()
            },
        }

    _set_phase("compute_metrics_coarse")
    coarse_m = metrics(result.predictions, None,        "coarse")
    _set_phase("compute_metrics_strong")
    strong_m = metrics(result.predictions, strong_gold, "strong")
    _set_phase("write_results")

    results = {
        "config": {
            "global_dir":     str(args.global_dir),
            "humanized_root": args.humanized_root,
            "humanized_subdir": args.humanized_subdir,
            "biencoder_finetune_epochs": args.biencoder_finetune_epochs,
            "skip_window_extraction":   True,
            "skip_graph":     False,
            "seed":           args.seed,
        },
        "metadata": {
            "n_predictions":   len(result.predictions),
            "fit_seconds":     result.fit_seconds,
            "predict_seconds": result.predict_seconds,
            "wall_seconds":    wall,
            **result.metadata,
        },
        "coarse": coarse_m,
        "strong": strong_m,
    }

    out_path = args.out_dir / "hybrid-rrf-mode3-results.json"
    out_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"[hybrid-rrf] wrote results to {out_path}\n")

    print("=" * 78)
    print(f"{'metric':<20s}  {'coarse-match':>14s}  {'strong-match':>14s}")
    print("-" * 78)
    print(f"{'n test queries':<20s}  {coarse_m['n_with_gold']:>14d}  {strong_m['n_with_gold']:>14d}")
    print(f"{'Hit@1':<20s}  {coarse_m['hit_at_1']:>14.4f}  {strong_m['hit_at_1']:>14.4f}")
    print(f"{'Hit@5':<20s}  {coarse_m['hit_at_5']:>14.4f}  {strong_m['hit_at_5']:>14.4f}")
    print(f"{'MRR':<20s}  {coarse_m['mrr']:>14.4f}  {strong_m['mrr']:>14.4f}")
    print()
    print("=== per-project Hit@5 (coarse match) ===")
    for proj, v in sorted(coarse_m["per_project"].items()):
        print(f"  {proj:<30s}  n={v['n']:>4d}  Hit@1={v['hit_at_1']:>.4f}  "
              f"Hit@5={v['hit_at_5']:>.4f}  MRR={v['mrr']:>.4f}")

    _set_phase("done")
    heartbeat_stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
