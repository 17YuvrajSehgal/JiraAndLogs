"""RQ-B4 — reformulation Hit@1 recovery.

The agent's `ReformulateQuerySkill` produces a reformulated query
string when the cheap-path retrieval is low-confidence. To MEASURE
whether this would recover Hit@1 misses, we run live retrieval on
the reformulated query and compare:

  - Original-query top-1 (from cached BiEncoder predictions)
  - Reformulated-query top-1 (re-computed via TF-IDF over memory)

Why TF-IDF for the re-retrieve: BiEncoder requires a fitted model +
PyTorch + sentence-transformers. TF-IDF is fast, no model fit, and
responds to vocabulary-level edits (which is exactly what the
bounded-action reformulator produces: drop_token / add_service /
substitute_synonym). For paper-grade evidence we'd swap in live
BiEncoder; for closure the TF-IDF answer is "does this work in
principle".

For each gate-firing window in the agent's trace:
  1. Get the original prediction's top-K
  2. Invoke ReformulateQuerySkill (stub or LLM mode) → reformulated_query
  3. Run TF-IDF over memory with the new query → new top-K
  4. Compare: did gold move into top-1? Stay where it was? Get worse?

Output: a per-window analysis with original vs reformulated top-1 vs
gold, aggregated as recovery rate.

Usage:
    PYTHONPATH=src python scripts/agent/reformulation_recovery.py \\
        --dataset ob \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --output data/agent_runs/ob-reformulation-recovery.json \\
        [--use-llm]  # requires LM Studio
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent.skills import (
    AgentContext,
    MemoryView,
    ReformulateQuerySkill,
)
from agent.types import InputBundle


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _load_predictions(path: Path, pipeline_name: str) -> dict[str, dict]:
    """Index predictions by window_id; filter to one pipeline."""
    out: dict[str, dict] = {}
    for row in _iter_jsonl(path):
        if row.get("pipeline_name") != pipeline_name:
            continue
        wid = row.get("window_id")
        if wid:
            out[wid] = row
    return out


def _load_memory_texts(memory_path: Path) -> tuple[list[str], list[str]]:
    ids, texts = [], []
    for row in _iter_jsonl(memory_path):
        tid = row.get("jira_shadow_issue_id") or row.get("issue_id")
        text = row.get("memory_text") or ""
        if tid and text:
            ids.append(tid)
            texts.append(text)
    return ids, texts


def _load_windows(examples_path: Path) -> dict[str, dict]:
    """Index windows by window_id."""
    out: dict[str, dict] = {}
    for row in _iter_jsonl(examples_path):
        wid = row.get("window_id")
        if wid:
            out[wid] = row
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=["ob", "wol", "otel"], required=True)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--biencoder-predictions", type=Path, default=None,
                   help="cached BiEncoder predictions JSONL "
                        "(default: comparison/v2a-resplit/per-window-predictions.jsonl)")
    p.add_argument("--biencoder-pipeline-name", default="bi_encoder_retrieval")
    p.add_argument("--confidence-floor", type=float, default=0.5,
                   help="windows below this triage_score are gate-firing candidates")
    p.add_argument("--use-llm", action="store_true",
                   help="invoke the reformulator with LM Studio (vs stub mode)")
    p.add_argument("--lm-studio-url", default="http://localhost:1234")
    p.add_argument("--lm-studio-model", default="local-model")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--limit", type=int, default=0,
                   help="0 = all gate-firing windows")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("reformulation_recovery")

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        raise SystemExit("scikit-learn required: pip install scikit-learn")

    # ----- Resolve paths
    biencoder_path = args.biencoder_predictions or (
        args.global_dir / "comparison" / "v2a-resplit" / "per-window-predictions.jsonl"
    )
    if not biencoder_path.exists():
        raise SystemExit(f"missing {biencoder_path}; run the cascade first")
    memory_path = args.global_dir / "jira-memory-corpus.jsonl"
    examples_path = args.global_dir / "global-triage-examples.jsonl"

    # ----- Load predictions, memory, windows
    log.info("loading BiEncoder predictions from %s", biencoder_path)
    preds = _load_predictions(biencoder_path, args.biencoder_pipeline_name)
    log.info("loaded %d predictions", len(preds))

    log.info("loading memory from %s", memory_path)
    memory_ids, memory_texts = _load_memory_texts(memory_path)
    log.info("memory: %d tickets", len(memory_ids))

    log.info("loading windows from %s", examples_path)
    windows = _load_windows(examples_path)
    log.info("windows: %d", len(windows))

    # ----- Identify gate-firing windows
    candidates: list[tuple[str, dict, dict]] = []
    for wid, pred in preds.items():
        triage = float(pred.get("triage_score") or 0.0)
        if triage >= args.confidence_floor:
            continue
        win = windows.get(wid)
        if not win or not win.get("triage_evidence_text"):
            continue
        candidates.append((wid, pred, win))

    if args.limit and len(candidates) > args.limit:
        candidates = candidates[: args.limit]

    log.info("%d gate-firing windows (triage_score < %.2f)",
             len(candidates), args.confidence_floor)

    if not candidates:
        print("[reformulation_recovery] no gate-firing windows; nothing to do.")
        return

    # ----- Fit TF-IDF over (memory + all window texts) once
    log.info("fitting TF-IDF over memory + window texts")
    all_window_texts = [w.get("triage_evidence_text") or "" for _, _, w in candidates]
    vec = TfidfVectorizer(
        max_features=10_000, min_df=2, lowercase=True, stop_words="english",
    )
    X = vec.fit_transform(memory_texts + all_window_texts)
    M = X[: len(memory_texts)]
    log.info("TF-IDF done; vocab=%d", len(vec.vocabulary_))

    # ----- Reformulator
    skill = ReformulateQuerySkill(use_llm=args.use_llm)
    llm = None
    if args.use_llm:
        try:
            from v2_advanced.shared import LMStudioClient
            from v2_advanced.shared.lm_studio import LMStudioConfig
            llm = LMStudioClient(LMStudioConfig(
                base_url=args.lm_studio_url, model=args.lm_studio_model,
            ))
            if not llm.is_available():
                log.warning("LM Studio not reachable; falling back to stub mode")
                llm = None
                skill = ReformulateQuerySkill(use_llm=False)
        except ImportError:
            log.warning("v2_advanced.shared not importable; stub mode")
            skill = ReformulateQuerySkill(use_llm=False)

    # ----- For each candidate window: reformulate + re-retrieve
    n_total = 0
    n_with_gold = 0
    n_orig_top1_hit = 0
    n_reform_top1_hit = 0
    n_recovered = 0     # was not top-1 originally; IS top-1 after
    n_regressed = 0     # was top-1 originally; not top-1 after
    n_no_change = 0
    action_counts: Counter = Counter()
    detail_rows: list[dict] = []

    for i, (wid, pred, win) in enumerate(candidates):
        gold = list(pred.get("gold_matched_issue_ids") or [])
        if not gold:
            # Skip windows without gold — Hit@1 isn't measurable
            continue

        original_query = win.get("triage_evidence_text") or ""
        original_top = list(pred.get("matched_issue_ids") or [])

        # Build a synthetic InputBundle + AgentContext for the skill
        bundle = InputBundle(
            window_id=wid,
            dataset=args.dataset,
            text_evidence=original_query,
            service_name=win.get("service_name"),
            scenario_family=win.get("scenario_family"),
            window_type=win.get("window_type"),
        )
        ctx = AgentContext(
            bundle_id=wid, llm=llm,
            extra={"retry_count": 0},
        )
        out = skill.invoke(bundle, MemoryView([]), ctx)
        action = out.extra.get("action_applied", {})
        reformulated = out.extra.get("reformulated_query", original_query)
        action_counts[action.get("action") or "noop"] += 1

        n_total += 1
        n_with_gold += 1

        # Re-retrieve with reformulated query via TF-IDF
        # (Use the SAME fitted TF-IDF — transform only)
        new_vec = vec.transform([reformulated])
        new_sims = (new_vec @ M.T).toarray()[0]
        top_idx = sorted(range(len(memory_ids)),
                         key=lambda k: -new_sims[k])[: args.top_k]
        reform_top = [memory_ids[k] for k in top_idx]

        gold_set = set(gold)
        orig_top1 = original_top[0] if original_top else None
        reform_top1 = reform_top[0] if reform_top else None

        orig_hit1 = orig_top1 in gold_set if orig_top1 else False
        reform_hit1 = reform_top1 in gold_set if reform_top1 else False

        if orig_hit1:
            n_orig_top1_hit += 1
        if reform_hit1:
            n_reform_top1_hit += 1

        if not orig_hit1 and reform_hit1:
            n_recovered += 1
        elif orig_hit1 and not reform_hit1:
            n_regressed += 1
        else:
            n_no_change += 1

        detail_rows.append({
            "window_id": wid,
            "original_query_chars": len(original_query),
            "reformulated_query_chars": len(reformulated),
            "action": action.get("action"),
            "action_argument": action.get("argument"),
            "original_top1": orig_top1,
            "reformulated_top1": reform_top1,
            "gold": gold[:3],
            "original_hit1": orig_hit1,
            "reformulated_hit1": reform_hit1,
            "outcome": (
                "recovered" if (not orig_hit1 and reform_hit1) else
                "regressed" if (orig_hit1 and not reform_hit1) else
                "no_change"
            ),
        })

        if (i + 1) % 25 == 0:
            log.info("processed %d / %d candidates", i + 1, len(candidates))

    # ----- Aggregate
    recovery_rate = n_recovered / n_with_gold if n_with_gold else 0.0
    regression_rate = n_regressed / n_with_gold if n_with_gold else 0.0
    net = recovery_rate - regression_rate

    print()
    print("=" * 80)
    print(f"  Reformulation Hit@1 recovery — RQ-B4")
    print("=" * 80)
    print(f"  gate-firing windows tested: {n_total}")
    print(f"  with gold (evaluable):      {n_with_gold}")
    print(f"  original Hit@1:             {n_orig_top1_hit} ({n_orig_top1_hit*100/max(1,n_with_gold):.1f}%)")
    print(f"  reformulated Hit@1:         {n_reform_top1_hit} ({n_reform_top1_hit*100/max(1,n_with_gold):.1f}%)")
    print(f"  recovered (was miss → hit): {n_recovered} ({recovery_rate*100:.1f}%)")
    print(f"  regressed (was hit → miss): {n_regressed} ({regression_rate*100:.1f}%)")
    print(f"  no change:                  {n_no_change}")
    print(f"  net (recovery − regression): {net*100:+.1f}%")
    print()
    print(f"  Action distribution:")
    for action, count in action_counts.most_common():
        print(f"    {action:<22} {count:>5}")
    print("=" * 80)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "n_gate_firing": n_total,
        "n_with_gold": n_with_gold,
        "n_original_hit1": n_orig_top1_hit,
        "n_reformulated_hit1": n_reform_top1_hit,
        "n_recovered": n_recovered,
        "n_regressed": n_regressed,
        "n_no_change": n_no_change,
        "recovery_rate": recovery_rate,
        "regression_rate": regression_rate,
        "net_change": net,
        "action_distribution": dict(action_counts),
        "method": ("live_llm" if args.use_llm and llm else "stub")
                  + "_reformulator_with_tfidf_retrieval",
        "details_first_50": detail_rows[:50],
    }, indent=2), encoding="utf-8")
    print(f"\n[reformulation_recovery] wrote -> {args.output}")


if __name__ == "__main__":
    main()
