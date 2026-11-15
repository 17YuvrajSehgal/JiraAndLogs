"""What the model is actually given, and how much of it is useful.

Reads the main-run rows and the decision digest (trace_decisions.py) and
answers: how big is the first prompt, where do the input tokens of a run
go, how much is the same code sent again, and how the model reads a file.

Usage:
    python industry-c7/scripts/input_analysis.py
"""

from __future__ import annotations

import collections as C
import json
import statistics as S
import sys
from pathlib import Path

FULL = Path(__file__).resolve().parents[1] / "data/agent/full"


def main() -> int:
    D = [json.loads(l) for l in open(FULL / "trace-decisions.jsonl", encoding="utf-8")]
    D = [d for d in D if d.get("turns")]
    N = len(D)

    def pct(x, n):
        return f"{100 * x / n:.1f}%" if n else "-"

    first = [d["turns"][0]["in"] for d in D]
    total = [sum(t["in"] for t in d["turns"]) for d in D]
    last = [d["turns"][-1]["in"] for d in D]
    out = [sum(t["out"] for t in d["turns"]) for d in D]
    print(f"runs {N}")
    print("\n1. SIZE of what the model is sent (input tokens)")
    print(f"  first prompt (system + briefing): median {S.median(first):.0f}, p90 "
          f"{sorted(first)[int(.9 * N)]}, max {max(first)}")
    print(f"  final prompt:                     median {S.median(last):.0f}, p90 "
          f"{sorted(last)[int(.9 * N)]}")
    print(f"  whole run, summed over calls:     median {S.median(total):.0f}, mean {S.mean(total):.0f}")
    print(f"  output tokens per run:            median {S.median(out):.0f}")
    print(f"  the briefing is re-sent on every call: {pct(sum(f * len(d['turns']) for f, d in zip(first, D)), sum(total))} "
          f"of all input tokens are the first prompt repeated")

    print("\n2. TOOL OUTPUT: characters returned per run, by tool")
    chars, calls = C.Counter(), C.Counter()
    for d in D:
        for t in d["turns"]:
            for c in t["calls"]:
                chars[c["tool"]] += c["chars"]
                calls[c["tool"]] += 1
    tot = sum(chars.values())
    for tool, ch in chars.most_common():
        print(f"  {tool:17s} {ch / N:8.0f} chars/run  ({pct(ch, tot)})  "
              f"{ch / calls[tool]:6.0f} chars/call  {calls[tool] / N:5.2f} calls/run")
    print(f"  total {tot / N:.0f} chars/run (~{tot / N / 4:.0f} tokens)")

    print("\n3. HOW A FILE IS READ: windows per file, and overlap")
    win, files_n, style = [], [], C.Counter()
    seq_pages = whole = 0
    for d in D:
        per = C.defaultdict(list)
        for t in d["turns"]:
            for c in t["calls"]:
                if c["tool"] == "read_code":
                    per[c["arg"].get("path", "")].append(c)
        files_n.append(len(per))
        for p, cs in per.items():
            win.append(len(cs))
            lines = sorted(int(c["arg"]["line"]) for c in cs if "line" in c["arg"])
            # paging: 3+ line-addressed reads of one file
            if len(lines) >= 3:
                seq_pages += 1
            whole += 1
    print(f"  files opened per run: median {S.median(files_n)}; windows read per opened file: "
          f"mean {S.mean(win):.1f}, median {S.median(win)}, p90 {sorted(win)[int(.9 * len(win))]}")
    print(f"  opened files that were PAGED through by line number (3+ line reads): "
          f"{pct(seq_pages, whole)}")
    print(f"  files read in 1 window {pct(sum(w == 1 for w in win), len(win))}, "
          f"2-3 windows {pct(sum(2 <= w <= 3 for w in win), len(win))}, "
          f"4-7 {pct(sum(4 <= w <= 7 for w in win), len(win))}, "
          f"8+ {pct(sum(w >= 8 for w in win), len(win))}")

    print("\n4. HOW MUCH is gone when the answer is written")
    cut = sorted(d["turns"][-1]["cut"] for d in D)
    dropped = [d["turns"][-1]["dropped"] for d in D]
    print(f"  share of tool output no longer in context: median {S.median(cut)}%, "
          f"p90 {cut[int(.9 * N)]}%; tool results dropped: median {S.median(dropped)}")

    print("\n5. SEARCH RESULTS: are they acted on?")
    named = opened = 0
    for d in D:
        seen = set()
        read = {c["arg"].get("path", "") for t in d["turns"] for c in t["calls"]
                if c["tool"] == "read_code"}
        for t in d["turns"]:
            for c in t["calls"]:
                if c["tool"] in ("search_text", "search_symbol") and c["gold_in_out"] > 0:
                    named += 1
                    # was ANY gold file read later in the run?
                    opened += any(cc["path_is_gold"] for tt in d["turns"]
                                  for cc in tt["calls"] if cc["tool"] == "read_code")
                    break
            else:
                continue
            break
    print(f"  runs where a search named a gold file: {named} ({pct(named, N)}); "
          f"a gold file was then opened in {pct(opened, named)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
