"""Did a v3 run actually behave like v3? Read a result file and say.

v3's two changes are things the model can quietly not do. A run where
every instance returns an empty causal_chain, or where the tool parser
silently returns null tool_calls, looks exactly like a working run: rows
appear, metrics compute, nothing errors. This separates the two.

Usage:
    python industry-c7/scripts/check_v3_run.py v3-smoke
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

AG = Path(__file__).resolve().parents[1] / "data/agent"
import sys as _s; _s.path.insert(0, str(Path(__file__).resolve().parents[0]))
from localize import is_dead_row  # noqa: E402
tag = sys.argv[1] if len(sys.argv) > 1 else "v3-full"
rows = [json.loads(l) for l in
        (AG / f"agent-{tag}.jsonl").open(encoding="utf-8")]
good = [r for r in rows if not is_dead_row(r)]
err = [r for r in rows if is_dead_row(r)]

print(f"rows {len(rows)}   ok {len(good)}   errored {len(err)}")
if err:
    print("  errors:", Counter(str(r["error"])[:60] for r in err).most_common(3))
if not good:
    print("FAIL no usable rows")
    sys.exit(1)

stop = Counter(r["stop_reason"] for r in good)
chain = [r.get("causal_chain") or [] for r in good]
with_chain = [c for c in chain if c]
cited = Counter(s.get("cited_from", "") for c in with_chain for s in c)
tools = Counter(t for r in good for t in r.get("tools_used", []))
prewalk = [r for r in good if r.get("prewalk_symbols")]
ver = Counter(r.get("version") for r in good)
acc1 = sum(r["metrics"]["acc@1"] for r in good) / len(good)
acc5 = sum(r["metrics"]["acc@5"] for r in good) / len(good)
wall = sum(r["cost"]["wall_s"] for r in good) / len(good)
calls = sum(r["cost"]["llm_calls"] for r in good) / len(good)

print(f"version tag        {dict(ver)}")
print(f"stop reasons       {dict(stop)}")
print(f"causal_chain       {len(with_chain)}/{len(good)} non-empty, "
      f"mean {sum(len(c) for c in with_chain)/max(len(with_chain),1):.1f} steps")
print(f"  cited_from       {dict(cited.most_common(6))}")
print(f"phase-0 prewalk    {len(prewalk)}/{len(good)} had frames to walk")
print(f"tool calls         {dict(tools.most_common(10))}")
print(f"acc@1 {acc1:.3f}   acc@5 {acc5:.3f}")
print(f"mean wall {wall:.0f}s   mean llm calls {calls:.1f}")

fails = []
if stop.get("submitted", 0) < len(good) * 0.8:
    fails.append("fewer than 80% of runs reached submit_ranking")
if len(with_chain) < len(good) * 0.8:
    fails.append("fewer than 80% of submissions carried a causal_chain "
                 "(the required field is not being filled)")
if not tools:
    fails.append("no tool calls at all -- the tool parser is probably wrong "
                 "(qwen3_xml, not hermes)")
if len(err) > len(rows) * 0.1:
    fails.append("more than 10% of instances errored")
for f in fails:
    print(f"FAIL {f}")
print("OK v3 behaved like v3" if not fails else "")
sys.exit(1 if fails else 0)
