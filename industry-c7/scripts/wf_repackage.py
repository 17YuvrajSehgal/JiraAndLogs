"""Re-run the code-only last stage of the workflow arm on rows already written.

EXAMINE and RANK are the model's work and are kept exactly as recorded
(the verdict cards and the file order). Only what code does afterwards is
redone: resolving each card's function names against the snapshot and
building the region list. No model call. Use it when that code changes,
so a fix to the checker does not need the GPU again.

Usage:
    python industry-c7/scripts/wf_repackage.py data/agent/login/agent-login3-wf.jsonl
    -> writes <stem>-repackaged.jsonl next to it
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "agent"))


def main() -> int:
    import lc_agent as LC
    import tools as T
    import workflow as WF
    from localize import evaluate, load_bench

    src = Path(sys.argv[1])
    out = src.with_name(src.stem + "-repackaged.jsonl")
    bench, fcache, n = {}, {}, 0
    with out.open("w", encoding="utf-8") as fh:
        for line in src.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("stop_reason") != "submitted" or not r.get("wf_cards"):
                fh.write(line)
                continue
            p = r["project"]
            if p not in bench:
                bench[p] = {b["issue_key"]: b for b in load_bench(p)}
            b = bench[p][r["issue_key"]]
            ws = T.Workspace(p, b["snapshot_sha"], b["query_text"], {}, {}, 0,
                             b["issue_key"], set(), fcache.setdefault(p, {}),
                             list(r["lexical_seed"]))
            ws.prepared = {"events": r.get("log_events") or []}
            cards = {c["path"]: c for c in r["wf_cards"]}
            order = [f for f in r["agent_ranking"] if f in cards]
            files = []
            for i, f in enumerate(order):
                c = cards[f]
                hits = list({h[1]: h for x in c["functions"]
                             for h in LC.resolve_region(ws, f, x)}.values())
                c["functions_resolved"] = list(dict.fromkeys(h[0] for h in hits))
                c["function_resolved"] = (c["functions_resolved"] or [""])[0]
                c["functions_at"] = [f"{h[0]}@{h[1]}" for h in hits]
                fns = (c["functions_at"]
                       or [x.partition("@")[0] for x in c["functions"]] or [""])
                for fn in fns[:2 if i < 3 else 1]:
                    files.append(LC.RankedFile(path=f, symbol=fn, evidence=c["evidence"]))
            ans = LC.Localization(
                module=r.get("module_raw") or "", files=files[:10],
                causal_chain=[LC.ChainStep(step=s["step"], cited_from=s["cited_from"],
                                           file=s["file"], log_event=s["log_event"])
                              for s in r["causal_chain"]])
            res = LC.package(ws, ans, "submitted", "", {}, r["seed"], r["log_layer"], arm="wf")
            # the file ranking must not move: only regions are rebuilt
            assert res["ranking"] == r["ranking"], (r["id"], "file ranking changed")
            r["regions"] = res["regions"]
            r["metrics"] = evaluate(res["ranking"], r["gold_files"])
            r["repackaged"] = True
            fh.write(json.dumps(r, default=str) + "\n")
            n += 1
    print(f"{n} rows repackaged -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
