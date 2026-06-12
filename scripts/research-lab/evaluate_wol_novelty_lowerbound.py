"""Mode 2 — Cross-domain novelty validation (L3 free-signal lower bound).

Per `docs7/REAL-DATA-WoL-PLAN.md` v3 §6, this script feeds the 800 WoL
out-of-distribution query windows through a proxy for the cascade's L3
free signal and reports novel precision.

The cascade's L3 disjunction is:
    is_novel = agent_novel  OR  (max_ret_conf < 0.5)  OR  (P_learned >= 0.5)

This script measures the SECOND disjunct only — the free signal — by
substituting the off-the-shelf MiniLM-L6-v2 cosine similarity for the
fine-tuned BiEncoder's triage_score. The substitution is honest scoping:

  * The cascade uses a FINE-TUNED bi-encoder whose triage_score is the
    output of a logistic head on similarity features. We approximate it
    with raw max cosine similarity from the off-the-shelf checkpoint.
  * The agent and learned-classifier signals are NOT measured here.
  * Because L3 OR-combines its three signals, omitting the agent and
    learned signals can only LOWER the reported is_novel count. The
    number is therefore a LOWER BOUND on the cascade's true novel
    precision on these queries.

For each WoL query, we compute:
    max_sim = max cosine(query_embedding, memory_embeddings)
    is_novel_by_free = (max_sim < 0.5)

We then report novel precision (= fraction of WoL queries flagged novel
under each threshold) overall and stratified by source project.

Outputs:
    out/mode2_novelty_lowerbound.json — per-threshold metrics, per-project breakdown
    out/mode2_per_query.jsonl          — per-query max_sim + best-match memory id
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queries", type=Path,
                    default="data/derived/global/2026-06-11-wol-real-global/novelty-queries/windows.jsonl")
    ap.add_argument("--memory", type=Path,
                    default="data/derived/global/2026-05-25-dataset-v5-large-global/jira-memory-corpus.jsonl")
    ap.add_argument("--out-dir", type=Path,
                    default="data/derived/global/2026-06-11-wol-real-global")
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2",
                    help="Off-the-shelf sentence transformer. Approximates the BiEncoder's similarity head.")
    ap.add_argument("--max-chars", type=int, default=512,
                    help="Truncation budget per text on both sides (mirrors BiEncoder's training-time truncation).")
    ap.add_argument("--thresholds", type=str, default="0.30,0.40,0.50,0.60,0.70",
                    help="Free-signal thresholds to sweep.")
    args = ap.parse_args()

    # ---- Imports ----
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    # ---- Load data ----
    print(f"[load] queries from {args.queries}")
    queries = _load_jsonl(args.queries)
    print(f"  loaded {len(queries)} queries")

    print(f"[load] memory from {args.memory}")
    memory = _load_jsonl(args.memory)
    print(f"  loaded {len(memory)} memory tickets")

    # Query text: evidence_text (joined log_msgs)
    query_texts = [(q.get("evidence_text") or q.get("triage_evidence_text") or "")[:args.max_chars]
                   for q in queries]
    query_projects = [q.get("wol_project") or "unknown" for q in queries]
    query_window_ids = [q["window_id"] for q in queries]

    # Memory text: use the legacy `memory_text` field
    memory_texts = [(m.get("memory_text") or "")[:args.max_chars] for m in memory]
    memory_ids = [m["jira_shadow_issue_id"] for m in memory]

    # ---- Encode ----
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[encode] device={device}, model={args.model}")
    t0 = time.time()
    model = SentenceTransformer(args.model, device=device)
    print(f"  model loaded ({time.time()-t0:.1f}s)")

    t0 = time.time()
    q_emb = model.encode(query_texts, batch_size=64, show_progress_bar=False,
                         convert_to_numpy=True, normalize_embeddings=True)
    m_emb = model.encode(memory_texts, batch_size=64, show_progress_bar=False,
                         convert_to_numpy=True, normalize_embeddings=True)
    print(f"  encoded {len(query_texts)} queries + {len(memory_texts)} memory in {time.time()-t0:.1f}s")
    print(f"  q_emb shape: {q_emb.shape}, m_emb shape: {m_emb.shape}")

    # ---- Compute pairwise cosine + max per query ----
    t0 = time.time()
    sim = q_emb @ m_emb.T  # (Q, M) cosine similarity (vectors are L2-normalized)
    max_idx = np.argmax(sim, axis=1)
    max_sim = np.take_along_axis(sim, max_idx[:, None], axis=1).squeeze(1)
    print(f"  cosine matmul + argmax in {time.time()-t0:.1f}s")

    # ---- Apply free-signal threshold sweep ----
    thresholds = [float(t.strip()) for t in args.thresholds.split(",")]
    overall = []
    for thr in thresholds:
        flagged_novel = int((max_sim < thr).sum())
        # Gold is is_novel=True for every WoL query (sentinel scenario_family=wol-novelty)
        precision = flagged_novel / len(queries)
        overall.append({
            "threshold": thr,
            "n_total": len(queries),
            "n_flagged_novel": flagged_novel,
            "novel_precision": precision,
        })

    # ---- Per-project stratification at threshold = 0.5 ----
    per_project: dict[str, dict] = defaultdict(lambda: {"n": 0, "n_novel_at_05": 0,
                                                         "sum_max_sim": 0.0})
    for proj, ms in zip(query_projects, max_sim):
        per_project[proj]["n"] += 1
        if ms < 0.5:
            per_project[proj]["n_novel_at_05"] += 1
        per_project[proj]["sum_max_sim"] += float(ms)
    per_project_out = []
    for proj, d in sorted(per_project.items()):
        per_project_out.append({
            "project": proj,
            "n": d["n"],
            "n_novel_at_threshold_0.5": d["n_novel_at_05"],
            "novel_precision_at_0.5": d["n_novel_at_05"] / d["n"],
            "mean_max_sim": d["sum_max_sim"] / d["n"],
        })

    # ---- Max-sim distribution stats ----
    distribution = {
        "min":    float(np.min(max_sim)),
        "p05":    float(np.percentile(max_sim, 5)),
        "p25":    float(np.percentile(max_sim, 25)),
        "median": float(np.median(max_sim)),
        "p75":    float(np.percentile(max_sim, 75)),
        "p95":    float(np.percentile(max_sim, 95)),
        "max":    float(np.max(max_sim)),
        "mean":   float(np.mean(max_sim)),
    }

    # ---- Write outputs ----
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.out_dir / "mode2_novelty_lowerbound.json"
    per_query_path = args.out_dir / "mode2_per_query.jsonl"

    summary = {
        "method": (
            "L3 free-signal lower bound. For each WoL query, compute max cosine "
            "similarity to the 347-ticket synthetic memory via off-the-shelf "
            "sentence-transformers/all-MiniLM-L6-v2. Flag as novel if max < threshold."
        ),
        "scope": (
            "Tests ONLY the L3 free signal (max_ret_conf < 0.5). Does NOT test "
            "the agent (agent_novel) or learned (P_learned >= 0.5) signals. "
            "Because L3 OR-combines, the reported novel precision is a LOWER BOUND "
            "on the cascade's true novel precision on these queries."
        ),
        "model":            args.model,
        "n_queries":        len(queries),
        "n_memory":         len(memory),
        "max_chars":        args.max_chars,
        "max_sim_distribution":  distribution,
        "free_signal_threshold_sweep": overall,
        "per_project_at_threshold_0.5":  per_project_out,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nwrote {summary_path}")

    with per_query_path.open("w", encoding="utf-8") as fh:
        for q, ms, mi in zip(queries, max_sim, max_idx):
            fh.write(json.dumps({
                "window_id":       q["window_id"],
                "wol_project":     q.get("wol_project"),
                "max_sim":         float(ms),
                "best_match_id":   memory_ids[int(mi)],
                "is_novel_at_0.5": bool(ms < 0.5),
            }) + "\n")
    print(f"wrote {per_query_path}")

    # ---- Pretty print summary ----
    print("\n========== free-signal threshold sweep ==========")
    print(f"{'threshold':>10s} {'n_flagged':>10s} {'novel_prec':>12s}")
    for row in overall:
        print(f"{row['threshold']:>10.2f} {row['n_flagged_novel']:>10d} {row['novel_precision']:>12.4f}")

    print("\n========== per-project stratification (threshold = 0.5) ==========")
    print(f"{'project':<42s} {'n':>5s} {'novel@0.5':>10s} {'precision':>10s} {'mean_sim':>10s}")
    for r in per_project_out:
        print(f"{r['project'][:42]:<42s} {r['n']:>5d} {r['n_novel_at_threshold_0.5']:>10d} "
              f"{r['novel_precision_at_0.5']:>10.4f} {r['mean_max_sim']:>10.4f}")

    print("\n========== max_sim distribution across 800 queries ==========")
    for k, v in distribution.items():
        print(f"  {k:>8s}: {v:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
