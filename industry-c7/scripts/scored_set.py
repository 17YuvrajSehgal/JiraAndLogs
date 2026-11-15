"""The scored set: benchmark instances minus the ones no localizer can answer.

`mine_benchmark.TEST_PATH` keeps test code out of gold, but the annotation
pass found four conventions it does not know about (see
`paper/test-filter-gaps.md`). On a handful of instances EVERY gold file
matches one of them, so the answer key contains only test code and no
ranking over source files can score a hit.

Gold itself is left exactly as mined. Those instances are dropped at scoring
time instead, and every system is rescored on the reduced set, so the
same-population rule still holds. The excluded ids are written to a JSON file
next to the benchmark so the drop is auditable rather than a flag buried in
a script.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mine_benchmark import TEST_PATH  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# The four gaps measured over benchmark. Case-sensitive for the same
# reason TEST_PATH is: "IT.java" is a capital-I convention, and matching it
# case-insensitively would also eat Audit.java, Edit.java, Unit.java.
TEST_PATH_EXTRA = re.compile(
    # Maven Failsafe integration-test source root: phoenix-core/src/it/java/...
    r"(^|/)src/it/"
    # Failsafe naming convention: ImmutableIndexIT.java
    r"|IT\.(java|scala)$"
    # shipped test-support module directories
    r"|(^|/)test-framework/"
    # gtest-style fixtures: repl_coordinator_test_fixture.cpp
    r"|[_-]test[_-]fixture\.|(^|/)testfixture")

EXCL_NAME = "excluded-test-only-gold.json"


def is_test_file(path: str) -> bool:
    return bool(TEST_PATH.search(path) or TEST_PATH_EXTRA.search(path))


def test_only_gold(inst: dict) -> bool:
    gold = inst.get("gold_files") or []
    return bool(gold) and all(is_test_file(p) for p in gold)


def compute(bench: Path) -> dict:
    ids, per_project, n_total, part = [], {}, 0, {}
    for f in sorted(bench.glob("*.jsonl")):
        if "-" in f.stem:          # memory pools etc, not instance files
            continue
        for line in f.open(encoding="utf-8"):
            inst = json.loads(line)
            n_total += 1
            gold = inst.get("gold_files") or []
            if not gold:
                continue
            if test_only_gold(inst):
                ids.append(f"{inst['project']}:{inst['issue_key']}")
                per_project[inst["project"]] = per_project.get(inst["project"], 0) + 1
            elif any(is_test_file(p) for p in gold):
                part[inst["project"]] = part.get(inst["project"], 0) + 1
    return {
        "benchmark": bench.name,
        "rule": "every gold file matches TEST_PATH or TEST_PATH_EXTRA",
        "pattern_extra": TEST_PATH_EXTRA.pattern,
        "n_total": n_total,
        "n_excluded": len(ids),
        "n_scored": n_total - len(ids),
        "per_project": dict(sorted(per_project.items(), key=lambda kv: -kv[1])),
        "partial_test_gold_per_project": dict(sorted(part.items(), key=lambda kv: -kv[1])),
        "excluded_ids": sorted(ids),
    }


def load(bench: Path) -> set:
    """Scoring scripts call this. Returns {"project:KEY", ...}."""
    p = bench / EXCL_NAME
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run scripts/scored_set.py first")
    return set(json.loads(p.read_text(encoding="utf-8"))["excluded_ids"])


if __name__ == "__main__":
    for name in ("benchmark", "benchmark"):
        bench = ROOT / "data" / name
        if not bench.exists():
            continue
        out = compute(bench)
        (bench / EXCL_NAME).write_text(
            json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print(f"{name}: {out['n_excluded']} excluded of {out['n_total']} "
              f"-> {out['n_scored']} scored   {out['per_project']}")
        print(f"   some-test-gold (kept): {out['partial_test_gold_per_project']}")
