"""Hand-checked cases for localize.evaluate().

Every number below was worked out by hand first, then compared. These are
the definitions the paper states, so a silent change to any of them is a
change to a reported claim.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import evaluate  # noqa: E402

ok = bad = 0


def chk(name, got, want, tol=1e-4):
    global ok, bad
    good = abs(got - want) < tol
    ok += good
    bad += not good
    print(f"{'PASS' if good else 'FAIL'}  {name}: {got:.4f}"
          + ("" if good else f"  expected {want:.4f}"))


# --- one fix-touched file, ranked first -------------------------------------
# The trap case. A perfect answer scores 0.2 precision@5 and can never do
# better, because there is only one right answer to put in five slots.
m = evaluate(["A", "B", "C", "D", "E"], ["A"])
chk("1-file, rank 1: hit@5", m["hit@5"], 1.0)
chk("1-file, rank 1: acc@5 is an alias of hit@5", m["acc@5"], m["hit@5"])
chk("1-file, rank 1: recall@5", m["recall@5"], 1.0)
chk("1-file, rank 1: precision@5", m["precision@5"], 0.2)
chk("1-file, rank 1: precision_ceiling@5", m["precision_ceiling@5"], 0.2)
chk("1-file, rank 1: r_precision", m["r_precision"], 1.0)
chk("1-file, rank 1: ap", m["ap"], 1.0)
chk("1-file, rank 1: mrr", m["mrr"], 1.0)

# --- three fix-touched files, two found at ranks 1 and 3 --------------------
m = evaluate(["A", "X", "B", "Y", "Z"], ["A", "B", "C"])
chk("3-file, 2 found: hit@5", m["hit@5"], 1.0)
chk("3-file, 2 found: recall@5", m["recall@5"], 2 / 3)
chk("3-file, 2 found: precision@5", m["precision@5"], 0.4)
chk("3-file, 2 found: precision_ceiling@5", m["precision_ceiling@5"], 0.6)
chk("3-file, 2 found: r_precision (top 3)", m["r_precision"], 2 / 3)
chk("3-file, 2 found: ap", m["ap"], (1 / 1 + 2 / 3) / 3)
chk("3-file, 2 found: mrr", m["mrr"], 1.0)

# --- nothing found ----------------------------------------------------------
m = evaluate(["X", "Y", "Z"], ["A"])
for key in ("hit@5", "recall@5", "precision@5", "r_precision", "ap", "mrr"):
    chk(f"miss: {key}", m[key], 0.0)
chk("miss: the ceiling does not depend on the answer",
    m["precision_ceiling@5"], 0.2)

# --- hit@1 is strictly harder than hit@5 ------------------------------------
m = evaluate(["X", "A"], ["A"])
chk("gold at rank 2: hit@1", m["hit@1"], 0.0)
chk("gold at rank 2: hit@5", m["hit@5"], 1.0)
chk("gold at rank 2: mrr", m["mrr"], 0.5)

# --- an empty ranking must not divide by zero -------------------------------
m = evaluate([], ["A"])
chk("empty ranking: hit@5", m["hit@5"], 0.0)
chk("empty ranking: ap", m["ap"], 0.0)

# --- more gold than k: the ceiling caps at 1.0, never above ----------------
m = evaluate(["A", "B", "C", "D", "E"], ["A", "B", "C", "D", "E", "F", "G"])
chk("7 gold, k=5: precision@5", m["precision@5"], 1.0)
chk("7 gold, k=5: precision_ceiling@5", m["precision_ceiling@5"], 1.0)
chk("7 gold, k=5: recall@5 cannot reach 1", m["recall@5"], 5 / 7)

print(f"\n{ok}/{ok + bad} checks passed")
raise SystemExit(1 if bad else 0)
