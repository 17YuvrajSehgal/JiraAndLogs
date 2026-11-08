"""Snapshot of a running agent batch: progress, health, and whether it
will finish before the server's walltime.

Health is not just the row count. A run whose rows keep appearing while
the model has stopped answering looks fine by row count and is producing
lexical fallbacks, so stop_reason and the v3 behaviour fields are the
things worth watching.

Usage:
    python industry-c7/scripts/run_status.py [--tag v3-full] [--n 26544]
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

AG = Path(__file__).resolve().parents[1] / "data/agent"
# 26,544 is the 27-project eval split; it was 4,409, the old four.
tag, total = "v3-full", 26544
for i, a in enumerate(sys.argv):
    if a == "--tag" and i + 1 < len(sys.argv):
        tag = sys.argv[i + 1]
    if a == "--n" and i + 1 < len(sys.argv):
        total = int(sys.argv[i + 1])

f = AG / f"agent-{tag}.jsonl"
if not f.exists():
    print(f"no rows yet for tag {tag}")
    raise SystemExit(0)
rows = []
for line in f.open(encoding="utf-8"):
    try:
        rows.append(json.loads(line))
    except Exception:  # noqa: BLE001 - a half-written last line is normal
        pass
n = len(rows)
good = [r for r in rows if not r.get("error")]
hard_err = [r for r in rows if r.get("error")]
stop = Counter(r.get("stop_reason") for r in good)
llm_err = stop.get("llm_error", 0)

# Rate from the file's own growth: mtime minus the earliest wall_s sum is
# unreliable with 24 workers, so use elapsed wall of the file.
started = f.stat().st_ctime
elapsed_min = max((time.time() - started) / 60, 0.1)
rate = n / elapsed_min
left = total - n
eta_min = left / rate if rate > 0 else float("inf")

chain = [r for r in good if r.get("causal_chain")]
prewalk = [r for r in good if r.get("prewalk_symbols")]
acc1 = sum(r["metrics"]["acc@1"] for r in good) / max(len(good), 1)
acc5 = sum(r["metrics"]["acc@5"] for r in good) / max(len(good), 1)
by_proj = Counter(r["project"] for r in rows)

print(f"progress     {n}/{total}  ({n/total*100:.1f}%)   {left} left")
print(f"rate         {rate:.1f}/min over {elapsed_min:.0f} min"
      f"   ETA {eta_min/60:.1f} h")
print(f"by project   {dict(by_proj)}")
print(f"stop reasons {dict(stop)}")
print(f"health       hard errors {len(hard_err)}   llm_error {llm_err}")
print(f"v3 fields    causal_chain {len(chain)}/{len(good)}"
      f"   prewalk fired {len(prewalk)}/{len(good)}")
print(f"accuracy     acc@1 {acc1:.3f}   acc@5 {acc5:.3f}")

flags = []
if llm_err:
    flags.append(f"{llm_err} rows have stop_reason=llm_error -- the server "
                 f"was unreachable for those; they will be retried on resume")
if len(good) and len(chain) / len(good) < 0.8:
    flags.append("under 80% of submissions carry a causal_chain")
if len(hard_err) > n * 0.05:
    flags.append("over 5% hard errors")
for fl in flags:
    print(f"WARN {fl}")
if not flags:
    print("OK no warnings")
