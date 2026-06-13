"""RQ-A5 agent signal — run DiagnosisAgent on the 800 WoL OOD queries.

The agent's `compose_novelty` skill combines three signals:
  is_novel = free_signal ∨ agent_signal ∨ learned_signal

For WoL the agent's deployed runtime DOESN'T invoke the verifier
(RQ-A8 structural skip via VerifierCalibration). But to MEASURE the
agent signal's value on OOD queries (the L3 disjunction lower-bound
removal), we run DiagnosisAgent in isolation, feeding it the 800 OOD
queries + TF-IDF top-K candidates from the WoL memory.

For OOD queries, DiagnosisAgent's verify stage should mostly emit
"no candidate consistent → novel". That's the agent signal we want.

Why TF-IDF candidates: OOD queries by construction don't match
anything specifically, so any reasonable retrieval (BiEncoder,
TF-IDF, BM25) returns plausible-but-wrong candidates. The verifier's
job is to say "none of these match" — the SHAPE of candidates
matters less than that there ARE candidates to evaluate. TF-IDF is
fast, no model fit needed.

Output JSONL (one row per OOD query):
  {
    "window_id": "wol-q-...",
    "is_novel": true/false,                  # agent's decision
    "ranked_top5": [{"ticket_id": ..., "confidence": ..., "consistent": ...}],
    "hypothesis": "...",
    "wol_project": "Spark"
  }

Usage:
    PYTHONPATH=src python scripts/agent/run_diagnosis_on_ood.py \\
        --global-dir data/derived/global/2026-06-11-wol-real-global \\
        --queries novelty-queries/windows.jsonl \\
        --output data/derived/global/2026-06-11-wol-real-global/ood-diagnosis-predictions.jsonl \\
        [--limit 50]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


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


def _load_memory(memory_path: Path) -> tuple[list[str], list[str], dict[str, dict]]:
    """Return (ticket_ids, memory_texts, ticket_metadata)."""
    ids: list[str] = []
    texts: list[str] = []
    meta: dict[str, dict] = {}
    for row in _iter_jsonl(memory_path):
        tid = row.get("jira_shadow_issue_id") or row.get("issue_id")
        text = row.get("memory_text") or ""
        if tid and text:
            ids.append(tid)
            texts.append(text)
            meta[tid] = row
    return ids, texts, meta


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True,
                   help="WoL dataset root")
    p.add_argument("--queries", type=str, default="novelty-queries/windows.jsonl",
                   help="OOD query JSONL relative to global-dir")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--top-k", type=int, default=10,
                   help="candidates per query for the verifier")
    p.add_argument("--lm-studio-url", default="http://localhost:1234")
    p.add_argument("--lm-studio-model", default="local-model")
    p.add_argument("--novelty-threshold", type=float, default=0.4)
    p.add_argument("--limit", type=int, default=0, help="0 = all 800")
    p.add_argument("--max-chars-evidence", type=int, default=3000)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("ood_diagnosis")

    queries_path = args.global_dir / args.queries
    memory_path = args.global_dir / "jira-memory-corpus.jsonl"
    if not queries_path.exists():
        raise SystemExit(f"missing {queries_path}")
    if not memory_path.exists():
        raise SystemExit(f"missing {memory_path}")

    # ----- Load
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        raise SystemExit("scikit-learn required: pip install scikit-learn")

    from v2_advanced.shared import LMStudioClient
    from v2_advanced.shared.lm_studio import LMStudioConfig
    from v2_advanced.proposal_e_agent.agent import DiagnosisAgent
    from v2_advanced.proposal_d_knowledge_graph.schema import IncidentExtraction

    log.info("loading memory from %s", memory_path)
    memory_ids, memory_texts, memory_meta = _load_memory(memory_path)
    log.info("memory: %d tickets", len(memory_ids))

    # Optional: load LLM extractions to pass richer candidates to the
    # verifier (root_cause, affected_services). Falls back to plain
    # memory_text if extractions don't exist.
    extractions_map: dict[str, IncidentExtraction] = {}
    ext_path = args.global_dir / "v2_kg_extractions" / "all_extractions.jsonl"
    if ext_path.exists():
        for row in _iter_jsonl(ext_path):
            try:
                ext = IncidentExtraction.from_dict(row)
                extractions_map[ext.ticket_id] = ext
            except (KeyError, TypeError):
                continue
        log.info("loaded %d extractions for candidate enrichment",
                 len(extractions_map))

    # ----- TF-IDF over memory + queries
    log.info("loading queries from %s", queries_path)
    queries: list[dict] = []
    for q in _iter_jsonl(queries_path):
        wid = q.get("window_id")
        text = q.get("triage_evidence_text") or q.get("evidence_text") or ""
        if wid and text:
            queries.append({
                "window_id": wid,
                "text": text[: args.max_chars_evidence],
                "wol_project": q.get("wol_project"),
                "scenario_family": q.get("scenario_family"),
            })
        if args.limit and len(queries) >= args.limit:
            break
    log.info("queries: %d", len(queries))

    log.info("fitting TF-IDF (cheap candidate signal for OOD)...")
    vec = TfidfVectorizer(
        max_features=8000, min_df=2, lowercase=True, stop_words="english",
    )
    X = vec.fit_transform(memory_texts + [q["text"] for q in queries])
    M = X[: len(memory_texts)]
    Q = X[len(memory_texts):]
    sims = (Q @ M.T).toarray()
    log.info("TF-IDF sim matrix: %s", sims.shape)

    # ----- LM Studio
    lm_cfg = LMStudioConfig(base_url=args.lm_studio_url, model=args.lm_studio_model)
    lm = LMStudioClient(lm_cfg)
    if not lm.is_available():
        raise SystemExit(
            f"LM Studio not reachable at {args.lm_studio_url}. "
            "Start it with a model loaded.",
        )
    log.info("LM Studio ready at %s", args.lm_studio_url)

    agent = DiagnosisAgent(
        lm, top_k_input=args.top_k, top_k_output=5,
        novelty_threshold=args.novelty_threshold,
    )

    # ----- Run per query
    args.output.parent.mkdir(parents=True, exist_ok=True)
    n_done = 0
    n_novel = 0
    t_start = time.time()
    with args.output.open("w", encoding="utf-8") as out_fh:
        for i, q in enumerate(queries):
            # Top-K candidates by TF-IDF
            sim_row = sims[i]
            top_idx = sorted(range(len(memory_ids)),
                             key=lambda k: -sim_row[k])[: args.top_k]
            candidates: list[dict[str, Any]] = []
            for k in top_idx:
                tid = memory_ids[k]
                ext = extractions_map.get(tid)
                if ext is not None:
                    candidates.append({
                        "ticket_id": tid,
                        "root_cause": getattr(ext, "root_cause", "") or
                                      (memory_texts[k][:200]),
                        "affected_services": list(
                            getattr(ext, "affected_services", []) or ()
                        ),
                    })
                else:
                    candidates.append({
                        "ticket_id": tid,
                        "root_cause": memory_texts[k][:200],
                        "affected_services": [],
                    })

            try:
                diagnosis = agent.diagnose(
                    window_id=q["window_id"],
                    evidence_text=q["text"],
                    candidates=candidates,
                )
            except Exception as e:                                   # noqa: BLE001
                log.warning("diagnose failed for %s: %s", q["window_id"], e)
                # Conservative default: treat as novel (the cascade does this too)
                diagnosis_dict = {
                    "is_novel": True, "ranked_top5": [],
                    "hypothesis": "", "error": str(e)[:120],
                }
            else:
                diagnosis_dict = {
                    "is_novel": diagnosis.is_novel,
                    "ranked_top5": [
                        {
                            "ticket_id": r.ticket_id,
                            "confidence": r.confidence,
                            "consistent": r.consistent,
                            "reason": (r.reason or "")[:200],
                        }
                        for r in diagnosis.ranked[: 5]
                    ],
                    "hypothesis": diagnosis.hypothesis.root_cause_hypothesis or "",
                }

            row = {
                "window_id": q["window_id"],
                "wol_project": q.get("wol_project"),
                "scenario_family": q.get("scenario_family"),
                **diagnosis_dict,
            }
            out_fh.write(json.dumps(row) + "\n")
            n_done += 1
            if diagnosis_dict.get("is_novel"):
                n_novel += 1

            if (i + 1) % 10 == 0:
                elapsed = time.time() - t_start
                avg = elapsed / (i + 1)
                eta_min = (len(queries) - (i + 1)) * avg / 60.0
                log.info(
                    "progress: %d/%d (%.1f%%); novel=%d; avg=%.2fs/window; eta=%.1fmin",
                    i + 1, len(queries),
                    (i + 1) / len(queries) * 100,
                    n_novel, avg, eta_min,
                )

    print()
    print("=" * 70)
    print(f"  DiagnosisAgent on OOD queries — RQ-A5 agent signal")
    print("=" * 70)
    print(f"  queries:    {n_done}")
    print(f"  agent_novel: {n_novel} ({n_novel * 100 / n_done:.1f}%)")
    print(f"  output:     {args.output}")
    print(f"  wall time:  {(time.time() - t_start) / 60:.1f} min")
    print("=" * 70)


if __name__ == "__main__":
    main()
