"""Consolidate per-pipeline `training_runs/.../predictions.jsonl` outputs
into the multi-pipeline `comparison/v2{a..e}-*/per-window-predictions.jsonl`
layout that `v2_advanced.tch.build_cascade` expects.

Background. `run_v2_comparison` writes one predictions file per training
run (in `training_runs/<pipeline>__<ts>__<sha>/predictions.jsonl`). The
cascade builder reads the legacy aggregated layout:

    comparison/v2a-resplit/per-window-predictions.jsonl    # HGB + BiEncoder + memorygraph
    comparison/v2b-logseq2vec/per-window-predictions.jsonl # LogSeq2Vec
    comparison/v2c-hybrid/per-window-predictions.jsonl     # hybrid_rrf_no_graph + rule
    comparison/v2c-hybrid-llm/per-window-predictions.jsonl # hybrid_rrf_retrieval_llm
    comparison/v2d-kg-rulebased/per-window-predictions.jsonl # kg_retrieval_rulebased
    comparison/v2e-agent-llm/per-window-predictions.jsonl  # diagnosis_agent

This script bridges the two layouts without re-running anything.

Rename rules (so build_cascade's pipeline_name filter accepts them):
- `hybrid_rrf_retrieval_g3`     -> `hybrid_rrf_retrieval_llm`
  (g3 = symmetric LLM extraction on both sides; semantically the "LLM" slot)
- `kg_retrieval_g3` is already aliased to `kg_retrieval_rulebased` by
  build_cascade's CANONICAL_ALIASES, so no rename needed.

Usage:
    PYTHONPATH=src python scripts/agent/consolidate_pipeline_predictions.py \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Per-pipeline source -> (destination relative path, optional pipeline_name rename)
# Multiple pipelines can share the same destination file; they get concat'd.
MAPPING: dict[str, tuple[str, str | None]] = {
    # pipeline name on disk -> (dest_rel_path, rename_to_or_None)
    "hist_gradient_boosting_numeric": ("v2a-resplit/per-window-predictions.jsonl", None),
    "bi_encoder_retrieval":           ("v2a-resplit/per-window-predictions.jsonl", None),
    "tab_transformer":                ("v2a-resplit/per-window-predictions.jsonl", None),  # extra; cascade ignores
    "logseq2vec_retrieval_pretrained":("v2b-logseq2vec/per-window-predictions.jsonl", None),
    "hybrid_rrf_no_graph":            ("v2c-hybrid/per-window-predictions.jsonl", None),
    # Rename to plain "hybrid_rrf_retrieval" — accepted by both consumers:
    # build_cascade aliases {hybrid_rrf_retrieval, hybrid_rrf_retrieval_llm}
    # to the same slot, and the agent's RetrieveHybridFusionLLMSkill
    # filters on plain "hybrid_rrf_retrieval" (it disambiguates by subdir).
    "hybrid_rrf_retrieval_g3":        ("v2c-hybrid-llm/per-window-predictions.jsonl", "hybrid_rrf_retrieval"),
    "kg_retrieval_g3":                ("v2d-kg-rulebased/per-window-predictions.jsonl", None),  # alias-handled
    "kg_retrieval_rulebased":         ("v2d-kg-rulebased/per-window-predictions.jsonl", None),
    "diagnosis_agent":                ("v2e-agent-llm/per-window-predictions.jsonl", None),
    "bm25_retrieval":                 ("v2f-bm25/per-window-predictions.jsonl", None),       # extra; cascade ignores
}


_TS_RE = re.compile(r"__\d{8}T\d{6}Z__")


def _latest_run_for(training_runs: Path, pipeline_name_on_disk: str) -> Path | None:
    """Return the most recent training_runs/<pipeline>__<ts>__<sha>/ dir,
    or None if no run exists for this pipeline."""
    # Map the cascade's canonical name back to the on-disk run-dir prefix.
    # On-disk, `hist_gradient_boosting_numeric` is named `hgb`.
    disk_prefix = {
        "hist_gradient_boosting_numeric": "hgb",
    }.get(pipeline_name_on_disk, pipeline_name_on_disk)

    candidates = [
        d for d in training_runs.iterdir()
        if d.is_dir() and d.name.startswith(disk_prefix + "__")
    ]
    if not candidates:
        return None
    # Sort by timestamp embedded in the name; newest last.
    def _ts(d: Path) -> str:
        m = _TS_RE.search(d.name)
        return m.group(0) if m else ""
    candidates.sort(key=_ts)
    return candidates[-1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--mirror-to", type=Path, default=None,
                   help="Optional second destination root — same files "
                        "with `v2X-...-per-window-predictions.jsonl` "
                        "(flat-name, dash-joined). Used to publish into "
                        "the results/<dataset>/3.3-cascade/consolidated/ tree.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan + counts, don't write files.")
    args = p.parse_args()

    training_runs = args.global_dir / "training_runs"
    comparison    = args.global_dir / "comparison"

    if not training_runs.is_dir():
        print(f"ERROR: missing {training_runs}", file=sys.stderr)
        sys.exit(2)

    # Group source files by destination so multiple pipelines feed the same file
    dest_to_sources: dict[str, list[tuple[str, Path, str | None]]] = {}
    for pipe_name, (dest_rel, rename) in MAPPING.items():
        run_dir = _latest_run_for(training_runs, pipe_name)
        if run_dir is None:
            print(f"  skip  {pipe_name}: no training_runs dir found")
            continue
        preds = run_dir / "predictions.jsonl"
        if not preds.is_file():
            print(f"  skip  {pipe_name}: no predictions.jsonl in {run_dir.name}")
            continue
        dest_to_sources.setdefault(dest_rel, []).append((pipe_name, preds, rename))

    for dest_rel, sources in sorted(dest_to_sources.items()):
        dest = comparison / dest_rel
        n_total = 0
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            out_lines: list[str] = []
            for pipe_name, src, rename in sources:
                with src.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.rstrip("\n")
                        if not line:
                            continue
                        if rename is not None:
                            row = json.loads(line)
                            row["pipeline_name"] = rename
                            line = json.dumps(row, ensure_ascii=False)
                        out_lines.append(line)
                        n_total += 1
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
            tmp.replace(dest)
            # Optional mirror to results/<dataset>/3.3-cascade/consolidated/
            # with flat dash-joined names (no nested v2X-xxx subdirs).
            if args.mirror_to is not None:
                args.mirror_to.mkdir(parents=True, exist_ok=True)
                flat_name = dest_rel.replace("/", "-")
                mirror_path = args.mirror_to / flat_name
                mirror_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        else:
            for pipe_name, src, rename in sources:
                n = sum(1 for _ in src.open(encoding="utf-8"))
                n_total += n
        src_summary = ", ".join(
            f"{p}{'->'+r if r else ''}({src.parent.name})"
            for p, src, r in sources
        )
        print(f"  {'(dry)' if args.dry_run else ' wrote'} {dest_rel}: {n_total} rows  <-  {src_summary}")


if __name__ == "__main__":
    main()
