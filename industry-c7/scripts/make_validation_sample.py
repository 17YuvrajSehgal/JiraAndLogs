"""Build the manual gold-validation sample (reviewer: 'ground truth
quality is not measured').

Draws a seeded 50-instance sample per project and writes one TSV sheet
per rater plus a protocol. Two raters answer, per instance:
  Q1 link_ok   is the commit really the fix for this issue? (y/n/unsure)
  Q2 gold_kind are the gold files the ROOT CAUSE site, or only the
               repair site? (root/repair/unsure)
Agreement is scored with Cohen's kappa by score_validation.py once both
sheets are filled.

Usage:
    python industry-c7/scripts/make_validation_sample.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import BENCH  # noqa: E402

SEED = 42
N = 50
OUT_DIR = Path(__file__).resolve().parents[1] / "validation"
TRACKER = {"kafka": "https://issues.apache.org/jira/browse/",
           "mariadb": "https://jira.mariadb.org/browse/",
           "mongodb": "https://jira.mongodb.org/browse/",
           "qt": "https://bugreports.qt.io/browse/"}
COMMIT = {"kafka": "https://github.com/apache/kafka/commit/",
          "mariadb": "https://github.com/MariaDB/server/commit/",
          "mongodb": "https://github.com/mongodb/mongo/commit/",
          "qt": "https://github.com/qt/qtbase/commit/"}


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    rng = random.Random(SEED)
    rows = []
    for p in TRACKER:
        bench = [json.loads(l) for l in
                 (BENCH / f"{p}.jsonl").open(encoding="utf-8")]
        for b in rng.sample(bench, N):
            rows.append({
                "project": p, "issue": b["issue_key"],
                "issue_url": TRACKER[p] + b["issue_key"],
                "commit_urls": " ".join(COMMIT[p] + s for s in b["fix_shas"]),
                "gold_files": "; ".join(b["gold_files"]),
            })
    hdr = ("project\tissue\tissue_url\tcommit_urls\tgold_files"
           "\tQ1_link_ok\tQ2_gold_kind\tnotes")
    body = "\n".join("\t".join(r.values()) + "\t\t\t" for r in rows)
    for rater in ("rater1", "rater2"):
        (OUT_DIR / f"gold-validation-{rater}.tsv").write_text(
            hdr + "\n" + body + "\n", encoding="utf-8")
    (OUT_DIR / "PROTOCOL.md").write_text("""# Gold-validation protocol

200 instances (50 per project, seed 42, drawn from the full benchmark).
Each rater fills their own TSV independently; do not discuss instances
before both sheets are complete.

Open `issue_url` and every `commit_urls` entry, then answer:

- **Q1_link_ok** - `y` if the commit(s) clearly fix THIS issue (the
  commit message, diff, or linked review makes it evident); `n` if the
  link is wrong (unrelated change, wrong ticket); `unsure` otherwise.
- **Q2_gold_kind** - `root` if the listed gold files contain the code
  that CAUSED the failure; `repair` if they only contain a workaround or
  a guard somewhere else (the cause lives in a file not listed);
  `unsure` otherwise. Answer only when Q1 is `y`.
- **notes** - optional free text.

When both sheets are filled, run:
    python industry-c7/scripts/score_validation.py
""", encoding="utf-8")
    print(f"wrote {len(rows)} rows x 2 sheets + PROTOCOL.md -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
