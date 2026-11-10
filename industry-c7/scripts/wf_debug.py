"""Read a workflow-arm pilot: what each stage did and what it cost.

Usage:
    python industry-c7/scripts/wf_debug.py data/agent/login/agent-login-wf.jsonl \
        [data/agent/login/login-wf]
"""

from __future__ import annotations

import collections as C
import json
import sys
from pathlib import Path


def main() -> int:
    rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
    runs = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    for r in rows:
        if not r.get("ranking"):
            print(r["id"], "DEAD", r.get("error") or r.get("stop_detail"))
            continue
        gold = set(r["gold_files"])
        cards = r.get("wf_cards") or []
        print(f"\n=== {r['id']}  route={r.get('wf_route')}  hit@1={r['metrics']['hit@1']:.0f} "
              f"hit@5={r['metrics']['hit@5']:.0f}  lexical@1={r['metrics_lexical']['hit@1']:.0f}  "
              f"calls={r['cost']['llm_calls']} tok_in={r['cost']['prompt_tokens']} "
              f"wall={r['cost']['wall_s']}s  module={r.get('module')!r}")
        print(f"   gold: {[g.rsplit('/', 1)[-1] for g in gold]}  in table: "
              f"{bool(gold & set(r.get('wf_table') or []))} ({len(r.get('wf_table') or [])} files)")
        for d in r.get("wf_decisions") or []:
            if d["stage"] == "shortlist":
                print(f"   shortlist answered={d['answered']} picked={len(d['picked'])} "
                      f"found_by_search={d['n_found_by_search']} queue={len(d['queue'])}")
            elif d["stage"] == "walk_back":
                print(f"   walk_back added {[f.rsplit('/', 1)[-1] for f in d['added']]}")
            elif d["stage"] == "rank":
                print(f"   rank answered={d['answered']} moved_by_tier_rule={d['moved_by_tier_rule']}")
        for c in cards:
            print(f"   {'GOLD' if c['path'] in gold else '    '} {c['role']:9s} "
                  f"answered={c['answered']!s:5s} fn={(c['function_resolved'] or '?' + c['function'])[:40]:40s} "
                  f"{c['path'].rsplit('/', 1)[-1]}")
        print("   final order:", [("GOLD:" if f in gold else "") + f.rsplit("/", 1)[-1]
                                  for f in r["ranking"][:5]])
        if runs:
            t = runs / (r["id"].replace(":", "_") + ".jsonl")
            if t.exists():
                ev = [json.loads(l) for l in t.open(encoding="utf-8")]
                mc = [e for e in ev if e["kind"] == "model_call"]
                stage = C.Counter()
                for e in mc:
                    off = e.get("tools_offered") or []
                    # which step: by the tools it was offered
                    s = ("shortlist" if "search_text" in off else "examine" if "read_code" in off
                         else "answer-only")
                    stage[s] += 1
                print(f"   model calls by step: {dict(stage)}; finish: "
                      f"{dict(C.Counter(e.get('finish_reason') for e in mc))}; "
                      f"latency mean {sum(e['latency_s'] for e in mc) / len(mc):.1f}s "
                      f"max {max(e['latency_s'] for e in mc):.0f}s; out tokens mean "
                      f"{sum((e.get('usage') or {}).get('output_tokens', 0) for e in mc) / len(mc):.0f}; "
                      f"in tokens mean {sum((e.get('usage') or {}).get('input_tokens', 0) for e in mc) / len(mc):.0f}")
                print("   tool calls:", dict(C.Counter(e["tool"] for e in ev if e["kind"] == "tool_call")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
