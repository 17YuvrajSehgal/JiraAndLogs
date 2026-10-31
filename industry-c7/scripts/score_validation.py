"""Score the gold-validation sheets: per-question agreement + Cohen's
kappa, and the headline rates (link precision, root-cause rate).

Usage:
    python industry-c7/scripts/score_validation.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

VAL = Path(__file__).resolve().parents[1] / "validation"


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in set(a) | set(b))
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def load(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    hdr = lines[0].split("\t")
    return [dict(zip(hdr, l.split("\t"))) for l in lines[1:] if l.strip()]


def main() -> int:
    r1 = load(VAL / "gold-validation-rater1.tsv")
    r2 = load(VAL / "gold-validation-rater2.tsv")
    q1a = [r["Q1_link_ok"].strip().lower() for r in r1]
    q1b = [r["Q1_link_ok"].strip().lower() for r in r2]
    if not all(q1a) or not all(q1b):
        done = sum(bool(x) for x in q1a), sum(bool(x) for x in q1b)
        print(f"sheets incomplete: rater1 {done[0]}, rater2 {done[1]} of {len(r1)}")
        return 1
    q2a = [r["Q2_gold_kind"].strip().lower() for r in r1]
    q2b = [r["Q2_gold_kind"].strip().lower() for r in r2]
    print(f"n={len(r1)}")
    print(f"Q1 kappa {kappa(q1a, q1b):.3f}  rater1 {Counter(q1a)}  rater2 {Counter(q1b)}")
    both_y = [i for i in range(len(r1)) if q1a[i] == q1b[i] == "y"]
    print(f"link precision (both y): {len(both_y) / len(r1):.3f}")
    k2a, k2b = [q2a[i] for i in both_y], [q2b[i] for i in both_y]
    if k2a:
        print(f"Q2 kappa {kappa(k2a, k2b):.3f}  rater1 {Counter(k2a)}  rater2 {Counter(k2b)}")
        root_both = sum(1 for x, y in zip(k2a, k2b) if x == y == "root")
        print(f"root-cause rate (both 'root', of linked): {root_both / len(k2a):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
