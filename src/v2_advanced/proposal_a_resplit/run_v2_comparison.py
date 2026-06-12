"""Driver — run the existing comparison harness against the v2 (window-
level) split manifest instead of the v1 (family-level) manifest.

Strategy: monkey-patch `core.data.splits.iter_split` at runtime
so that every pipeline that calls it sees the v2 assignments. This
leaves the v1 panel completely untouched — the patch is scoped to this
process, and the v1 CLI still works exactly as before.

Usage:
    PYTHONPATH=src python -m v2_advanced.proposal_a_resplit.run_v2_comparison \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --runs-root data/runs \\
        --pipelines hgb,tab_transformer,memorygraph_v2_sota_nw080,bi_encoder_retrieval \\
        --n-bootstrap 1000 \\
        --output-dir data/derived/global/2026-05-25-dataset-v5-large-global/comparison/v2a-resplit
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from v2_advanced.shared import get_logger, log_step
from v2_advanced.proposal_a_resplit.window_split import (
    WindowSplitManifest,
    load_v2_manifest,
)

log = get_logger("phase_a.run_v2")


def patch_iter_split(v2_manifest: WindowSplitManifest) -> None:
    """Replace core.data.splits.iter_split with a window-level
    version. Idempotent within a process.
    """
    import core.data.splits as splits_mod

    if getattr(splits_mod.iter_split, "_v2_patched", False):
        log.info("iter_split already patched; skipping")
        return

    original = splits_mod.iter_split

    def iter_split_v2(windows, manifest, split):
        for w in windows:
            if v2_manifest.split_of(w.window_id) == split:
                yield w

    iter_split_v2._v2_patched = True
    iter_split_v2._original = original
    splits_mod.iter_split = iter_split_v2

    # Also patch the symbols that already imported the v1 binding.
    # Pipelines do `from core.data.splits import iter_split` at
    # module load time, so we have to rebind those too.
    import sys
    rebound = 0
    for mod_name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        if hasattr(mod, "iter_split") and getattr(mod, "iter_split") is original:
            setattr(mod, "iter_split", iter_split_v2)
            rebound += 1
    log.info("patched iter_split", rebound_in_modules=rebound)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--runs-root", type=Path, required=True)
    p.add_argument("--pipelines", type=str, required=True,
                   help="comma-separated pipeline names")
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument("--target-fpr", type=float, default=0.05)
    p.add_argument("--manifest", type=str,
                   default="triage-split-manifest-v2-resplit.json")
    p.add_argument("--no-ensemble", action="store_true")
    p.add_argument("--no-lofo", action="store_true",
                   help="LOFO is meaningless under in-distribution split; default off")
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()

    # Load v2 manifest + patch
    with log_step(log, "patch_split", manifest=args.manifest):
        v2 = load_v2_manifest(args.global_dir, filename=args.manifest)
        patch_iter_split(v2)

    # Run the comparison. Imports happen AFTER the patch so any late-bound
    # iter_split resolves to v2.
    from comparison.runner import run_comparison, render_report_md

    pipelines = [s.strip() for s in args.pipelines.split(",") if s.strip()]
    log.info("running v2 comparison", pipelines=pipelines, n_bootstrap=args.n_bootstrap)

    with log_step(log, "run_comparison", pipelines=len(pipelines)):
        # NOTE: LOFO is family-based and doesn't make sense for v2 (every
        # family appears in train). Pass include_lofo=False by default.
        include_lofo = not args.no_lofo
        if include_lofo:
            log.warning("LOFO on v2 split — questionable semantics; consider --no-lofo")
        report = run_comparison(
            global_dir=args.global_dir,
            runs_root=args.runs_root,
            pipelines=pipelines,
            include_ensemble=not args.no_ensemble,
            n_bootstrap=args.n_bootstrap,
            target_fpr=args.target_fpr,
            include_lofo=include_lofo,
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(
        json.dumps(report.as_dict(), indent=2, default=str),
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(render_report_md(report), encoding="utf-8")

    # Per-window predictions
    pwp_path = args.output_dir / "per-window-predictions.jsonl"
    with pwp_path.open("w", encoding="utf-8") as fh:
        for result in report.results:
            for pred in result.predictions:
                fh.write(json.dumps(pred.as_dict()) + "\n")

    log.info(
        "v2 comparison done",
        output_dir=str(args.output_dir),
        pipelines=len(report.results),
        report_kb=round((args.output_dir / "report.json").stat().st_size / 1024, 1),
    )


if __name__ == "__main__":
    main()
