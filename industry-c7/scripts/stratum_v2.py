"""Second hard-stratum definition (reviewer: the 28% vs 68% hard gap may
be a language artifact -- Java traces name files, C++ traces name
functions).

Definition 1 (paper): easy iff the report text names a gold FILE.
Definition 2 (here):  easy iff definition 1 holds, OR the text contains
the basename stem of a gold file, OR the name of any function/method
DEFINED in a gold file (from the tree-sitter inventories; names shorter
than 4 chars are ignored to avoid trivial matches like `get`).

Reads funcs-{p}.pkl (function_stage.py cache); parses any missing gold
blob on the fly.

Usage:
    python industry-c7/scripts/stratum_v2.py
"""

from __future__ import annotations

import json
import pickle
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from function_stage import list_functions, parser_for, raw_blobs  # noqa: E402
from localize import BENCH, FULL_REPOS, OUT  # noqa: E402
from mine_benchmark import run_git  # noqa: E402

P = ("kafka", "mariadb", "mongodb", "qt")
MIN_NAME = 4


def main() -> int:
    out = {}
    for p in P:
        git_dir = FULL_REPOS[p]
        bench = [json.loads(l) for l in
                 (BENCH / f"{p}.jsonl").open(encoding="utf-8")]
        fcache = pickle.loads((OUT / f"funcs-{p}.pkl").read_bytes())
        n = len(bench)
        hard1 = hard2 = 0
        for b in bench:
            text = b["query_text"]
            if b["gold_named_in_text"]:
                continue  # easy under both definitions
            hard1 += 1
            names: set[str] = set()
            paths = [f for f in b["gold_files"] if parser_for(f)]
            if paths:
                ls = run_git(git_dir, "ls-tree", b["snapshot_sha"], "--", *paths)
                blob_of = {}
                for line in ls.splitlines():
                    meta, path = line.split("\t", 1)
                    _, otype, blob = meta.split()
                    if otype == "blob":
                        blob_of[path] = blob
                missing = [bl for bl in set(blob_of.values()) if bl not in fcache]
                texts = raw_blobs(git_dir, missing)
                for path, bl in blob_of.items():
                    if bl not in fcache:
                        fcache[bl] = list_functions(path, texts.get(bl, b""))
                    for name, _s, _e in fcache[bl]:
                        # qualified C++ names vote with their last component too
                        names.add(name)
                        names.add(name.rsplit("::", 1)[-1])
            for f in b["gold_files"]:
                names.add(Path(f).stem)
            names = {x for x in names if len(x) >= MIN_NAME}
            if not any(re.search(rf"\b{re.escape(x)}\b", text) for x in names):
                hard2 += 1
        out[p] = {"n": n, "hard_def1": hard1, "hard_def2": hard2,
                  "hard1_pct": round(100 * hard1 / n),
                  "hard2_pct": round(100 * hard2 / n)}
        print(f"{p:<9} hard def1 {100 * hard1 / n:5.1f}%   "
              f"def2 (+stems+functions) {100 * hard2 / n:5.1f}%")
    (OUT / "stratum-v2.json").write_text(json.dumps(out, indent=2),
                                         encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
