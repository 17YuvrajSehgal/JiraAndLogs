"""Generate a window-level stratified-random train/val/test split.

Reads the existing global dataset's `global-triage-examples.jsonl`,
groups by `scenario_family`, randomly assigns each window in each
group to train (70%) / validation (15%) / test (15%) using a fixed
seed for reproducibility, and writes a new manifest.

The output preserves the same JSON schema as the v1 manifest so
downstream code can drop it in as a replacement when wanted.

Usage:
    python -m v2_advanced.proposal_a_resplit.make_resplit \\
        --global-dir data/derived/global/2026-05-25-dataset-v5-large-global \\
        --out triage-split-manifest-v2-resplit.json \\
        --train 0.70 --val 0.15 --test 0.15 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from v2_advanced.shared import get_logger, log_step

log = get_logger("phase_a.resplit")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global-dir", type=Path, required=True)
    p.add_argument("--out", type=str,
                   default="triage-split-manifest-v2-resplit.json",
                   help="filename to write under <global-dir>")
    p.add_argument("--train", type=float, default=0.70)
    p.add_argument("--val", type=float, default=0.15)
    p.add_argument("--test", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    if abs(args.train + args.val + args.test - 1.0) > 1e-6:
        raise SystemExit("train+val+test must sum to 1.0")

    examples_path = args.global_dir / "global-triage-examples.jsonl"
    log.info("loading examples", path=str(examples_path))

    rows = []
    with examples_path.open(encoding="utf-8") as fh:
        for line in fh:
            rows.append(json.loads(line))
    log.info("loaded windows", n=len(rows))

    # Group by scenario_family
    by_family: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        fam = r.get("scenario_family") or "?"
        by_family[fam].append(r)
    log.info("families found", n=len(by_family))

    rng = random.Random(args.seed)
    window_assignment: dict[str, str] = {}
    label_counts: dict[str, Counter] = {
        "train": Counter(), "validation": Counter(), "test": Counter(),
    }
    per_family_counts: dict[str, dict[str, int]] = {}

    with log_step(log, "stratified_split", seed=args.seed):
        for fam, fam_rows in sorted(by_family.items()):
            # Stable per-family ordering for reproducibility
            fam_rows = sorted(fam_rows, key=lambda r: r["window_id"])
            shuffled = fam_rows[:]
            rng.shuffle(shuffled)

            n = len(shuffled)
            n_train = int(round(args.train * n))
            n_val = int(round(args.val * n))
            # n_test absorbs the rounding remainder
            n_test = n - n_train - n_val
            assert n_test >= 0, f"negative test split for family {fam}"

            train_set = shuffled[:n_train]
            val_set = shuffled[n_train:n_train + n_val]
            test_set = shuffled[n_train + n_val:]

            for r in train_set:
                window_assignment[r["window_id"]] = "train"
                label_counts["train"][r["triage_label"]] += 1
            for r in val_set:
                window_assignment[r["window_id"]] = "validation"
                label_counts["validation"][r["triage_label"]] += 1
            for r in test_set:
                window_assignment[r["window_id"]] = "test"
                label_counts["test"][r["triage_label"]] += 1

            per_family_counts[fam] = {
                "train": len(train_set),
                "validation": len(val_set),
                "test": len(test_set),
                "total": n,
            }
            log.info(
                f"family={fam}",
                n=n,
                tr=len(train_set), va=len(val_set), te=len(test_set),
            )

    n_total = len(window_assignment)
    log.info(
        "split totals",
        train=sum(1 for v in window_assignment.values() if v == "train"),
        val=sum(1 for v in window_assignment.values() if v == "validation"),
        test=sum(1 for v in window_assignment.values() if v == "test"),
        total=n_total,
    )

    manifest = {
        "schema_version": 2,
        "split_by": "window_id",
        "global_dataset_id": args.global_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "split_ratios": {
            "train": args.train,
            "validation": args.val,
            "test": args.test,
        },
        "window_assignment": window_assignment,
        "label_counts_by_split": {
            split: dict(counter) for split, counter in label_counts.items()
        },
        "per_family_counts": per_family_counts,
        # Carry through the LOFO folds in case downstream callers need them.
        "leave_one_family_out_folds": sorted(by_family),
    }

    out_path = args.global_dir / args.out
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("wrote v2 manifest", path=str(out_path), size_kb=round(out_path.stat().st_size / 1024, 1))


if __name__ == "__main__":
    main()
