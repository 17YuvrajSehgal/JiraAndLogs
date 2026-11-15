"""Sanity baselines for module-level results (reviewer W5).

For each eval instance:
  random@K  = expected Acc@K of uniform random module ranking, computed
              analytically: 1 - prod_{i=0..K-1} (M-G-i)/(M-i), where M =
              number of modules in the instance's snapshot universe and
              G = number of gold modules.
  frequent@K = Acc@K of ranking modules by how often they were gold in the
              DEV split (the "most frequent module" baseline).

M is exact: ls-tree of the snapshot, non-test source files collapsed with
the same per-project module depth as module_metrics.py.

Usage:
    python industry-c7/scripts/module_baselines.py
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import BENCH, FULL_REPOS, OUT, Snapshot  # noqa: E402
from mine_benchmark import PROJECTS  # noqa: E402
from module_metrics import DEPTH, module_of  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", force=True)
log = logging.getLogger("c7-modbase")

KS = (1, 3, 5)


def random_acc(M: int, G: int, k: int) -> float:
    if G <= 0 or M <= 0:
        return 0.0
    k = min(k, M)
    p_miss = 1.0
    for i in range(k):
        p_miss *= max(0, M - G - i) / max(1, M - i)
    return 1.0 - p_miss


def main() -> int:
    out = {}
    for proj, depth in DEPTH.items():
        cfg = PROJECTS[proj]
        git_dir = FULL_REPOS[proj]
        bench = {b["issue_key"]: b for b in
                 (json.loads(l) for l in
                  (BENCH / f"{proj}.jsonl").open(encoding="utf-8"))}
        rows = [json.loads(l) for l in
                (OUT / f"{proj}-instances.jsonl").open(encoding="utf-8")]
        n_dev = json.load((OUT / f"{proj}-summary.json").open())["n_dev"]
        rows.sort(key=lambda r: r["fix_time"])
        dev, ev = rows[:n_dev], rows[n_dev:]

        # most-frequent modules from dev gold
        freq = Counter()
        for r in dev:
            for m in {module_of(f, depth) for f in r["gold_files"]}:
                freq[m] += 1
        frequent = [m for m, _ in freq.most_common(max(KS))]
        # The ranked dev order in full, so the "still exists" variant below
        # can walk past modules the repository has since removed.
        freq_all = [m for m, _ in freq.most_common()]

        rnd = {k: 0.0 for k in KS}
        frq = {k: 0.0 for k in KS}
        frq_live = {k: 0.0 for k in KS}
        n_stale = 0
        m_counts = []
        for i, r in enumerate(ev):
            b = bench[r["issue_key"]]
            snap = Snapshot(git_dir, b["snapshot_sha"], cfg["src_ext"])
            mods = {module_of(f, depth) for f in snap.files}
            gold = {module_of(f, depth) for f in r["gold_files"]}
            M, G = len(mods), len(gold & mods) or len(gold)
            m_counts.append(M)
            # A repository that reorganises between the dev and eval halves
            # hands the plain baseline a module that no longer exists, and
            # then it cannot be right at rank 1 whatever it does. HBase is
            # the case: its dev split is dominated by `src` (615 instances,
            # the pre-split single tree) and NO eval instance has a `src`
            # module, so frequent@1 is exactly 0.000 over 2,272 instances
            # while frequent@3 is 0.883. That understates the baseline for a
            # reason unrelated to the task, which flatters us. Report both:
            # the plain one, and one restricted to modules the eval snapshot
            # still contains, which is the stronger bar to clear.
            live = [m for m in freq_all if m in mods][:max(KS)]
            n_stale += int(bool(frequent) and frequent[0] not in mods)
            for k in KS:
                rnd[k] += random_acc(M, G, k)
                frq[k] += float(any(m in gold for m in frequent[:k]))
                frq_live[k] += float(any(m in gold for m in live[:k]))
            if i % 400 == 0:
                log.info("%s %d/%d", proj, i, len(ev))

        n = len(ev)
        out[proj] = {
            "module_depth": depth,
            "n_eval": n,
            "modules_per_snapshot": {
                "min": min(m_counts), "median": sorted(m_counts)[n // 2],
                "max": max(m_counts)},
            "random": {f"acc@{k}": round(rnd[k] / n, 4) for k in KS},
            "most_frequent": {f"acc@{k}": round(frq[k] / n, 4) for k in KS},
            "most_frequent_live": {f"acc@{k}": round(frq_live[k] / n, 4)
                                   for k in KS},
            "eval_instances_where_top_dev_module_is_gone": n_stale,
        }
        log.info("%s done: %s", proj, out[proj])

    (OUT / "module-baselines.json").write_text(json.dumps(out, indent=2),
                                               encoding="utf-8")
    for proj, r in out.items():
        print(f"{proj:<9} modules median={r['modules_per_snapshot']['median']:<5}"
              f" random@5={r['random']['acc@5']:<7} frequent@5={r['most_frequent']['acc@5']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
