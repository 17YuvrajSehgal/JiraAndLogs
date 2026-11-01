"""Score the LLM localization responses against the benchmark gold.

Maps each model-returned path string onto a real file in that instance's
snapshot (models paraphrase paths), then computes the same Acc@K / MRR /
Recall@K as the lexical pipeline, on the same evaluation split.

Path resolution is reported, not hidden: exact hit, resolved by unique
basename, resolved by unique suffix, or dropped. A dropped path is never
silently replaced; it simply does not occupy a rank.

Instances whose response failed to parse keep an EMPTY ranking and are
scored as misses, and the failure rate is reported, so the headline
numbers never flatter the LLM by discarding its bad cases. A
parsed-only view is reported alongside for the opposite reading.

Usage:
    python industry-c7/scripts/llm_score.py --stage a2 \
        --responses industry-c7/data/llm/resp-a2.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import (BENCH, FULL_REPOS, OUT, PROJECTS,  # noqa: E402
                      KS, Snapshot, evaluate)

P = ("kafka", "mariadb", "mongodb", "qt")
LLM = Path(__file__).resolve().parents[1] / "data/llm"


class Resolver:
    """Map model path strings onto real snapshot paths."""

    def __init__(self, files: list[str]):
        self.exact = set(files)
        self.by_base: dict[str, list[str]] = defaultdict(list)
        for f in files:
            self.by_base[f.rsplit("/", 1)[-1]].append(f)
        self.files = files

    def resolve(self, raw: str, stats: Counter) -> str | None:
        if not isinstance(raw, str) or not raw.strip():
            stats["dropped"] += 1
            return None
        s = raw.strip().replace("\\", "/").lstrip("./").lstrip("/")
        if s in self.exact:
            stats["exact"] += 1
            return s
        # a leading repo-name component the model invented
        for cut in range(1, 3):
            t = "/".join(s.split("/")[cut:])
            if t and t in self.exact:
                stats["exact_after_prefix_strip"] += 1
                return t
        hits = self.by_base.get(s.rsplit("/", 1)[-1], [])
        if len(hits) == 1:
            stats["by_basename"] += 1
            return hits[0]
        if len(hits) > 1:  # ambiguous basename: prefer longest common suffix
            best = [f for f in hits if f.endswith(s)]
            if len(best) == 1:
                stats["by_suffix"] += 1
                return best[0]
        suf = [f for f in self.files if f.endswith(s)]
        if len(suf) == 1:
            stats["by_suffix"] += 1
            return suf[0]
        stats["dropped"] += 1
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--responses", required=True)
    ap.add_argument("--field", default="files")
    ap.add_argument("--tag", default="", help="suffix for the output name")
    args = ap.parse_args()

    resp: dict[str, dict] = {}
    for line in open(args.responses, encoding="utf-8"):
        d = json.loads(line)
        resp.setdefault(d["id"], d)

    bench = {}
    results = {}
    for p in P:
        for b in (json.loads(l) for l in
                  (BENCH / f"{p}.jsonl").open(encoding="utf-8")):
            bench[f"{p}:{b['issue_key']}"] = (p, b)
        rows = [json.loads(l) for l in
                (OUT / f"{p}-instances.jsonl").open(encoding="utf-8")]
        rows.sort(key=lambda r: r["fix_time"])
        n_dev = json.load((OUT / f"{p}-summary.json").open())["n_dev"]
        for i, r in enumerate(rows):
            results[f"{p}:{r['issue_key']}"] = (r, i >= n_dev)

    pstats, out_rows = Counter(), []
    fails = Counter()
    snap_cache: dict[tuple[str, str], Resolver] = {}  # cp has 2 rows/instance
    for rid, d in resp.items():
        base_id = rid.rsplit(":", 1)[0] if d.get("variant") else rid
        if base_id not in bench:
            continue
        project, b = bench[base_id]
        row, is_eval = results[base_id]
        parsed = d.get("parsed") or {}
        raw_list = parsed.get(args.field) or []
        if not isinstance(raw_list, list):
            raw_list = []
        if d.get("error") or not d.get("parsed"):
            fails[f"{project}:failed"] += 1
        ck = (project, b["snapshot_sha"])
        res = snap_cache.get(ck)
        if res is None:
            res = Resolver(Snapshot(FULL_REPOS[project], b["snapshot_sha"],
                                    PROJECTS[project]["src_ext"]).files)
            if len(snap_cache) < 4000:
                snap_cache[ck] = res
        ranking, seen = [], set()
        for raw in raw_list[:20]:
            f = res.resolve(raw, pstats)
            if f and f not in seen:
                seen.add(f)
                ranking.append(f)
        out_rows.append({
            "id": rid, "project": project, "issue_key": b["issue_key"],
            "variant": d.get("variant"), "is_eval": is_eval,
            "strata": row["strata"], "fix_time": row["fix_time"],
            "n_returned": len(raw_list), "n_resolved": len(ranking),
            "parse_ok": bool(d.get("parsed")),
            "recalled": parsed.get("recalled"),
            "ranking": ranking, "gold_files": b["gold_files"],
            "metrics": evaluate(ranking, b["gold_files"]),
            "ours_metrics": row["metrics"]["cond_ours"],
        })

    def agg(sub):
        if not sub:
            return {}
        ms = list(sub[0]["metrics"])
        return {m: round(sum(x["metrics"][m] for x in sub) / len(sub), 4)
                for m in ms}

    summary = {"stage": args.stage, "n_responses": len(resp),
               "n_scored": len(out_rows),
               "path_resolution": dict(pstats), "parse_failures": dict(fails),
               "by_project": {}}
    for p in P:
        ev = [x for x in out_rows if x["project"] == p and x["is_eval"]
              and not x["variant"]]
        summary["by_project"][p] = {
            "n_eval": len(ev), "all": agg(ev),
            "parsed_only": agg([x for x in ev if x["parse_ok"]]),
            "easy": agg([x for x in ev if x["strata"]["easy"]]),
            "hard": agg([x for x in ev if not x["strata"]["easy"]]),
            "ours_same_instances": {
                m: round(sum(x["ours_metrics"][m] for x in ev) / len(ev), 4)
                for m in (f"acc@{k}" for k in KS)} if ev else {},
            "ours_mrr": (round(sum(x["ours_metrics"]["mrr"] for x in ev)
                               / len(ev), 4) if ev else None),
        }
    if any(x["variant"] for x in out_rows):
        summary["by_variant"] = {}
        for v in sorted({x["variant"] for x in out_rows if x["variant"]}):
            sub = [x for x in out_rows if x["variant"] == v and x["is_eval"]]
            summary["by_variant"][v] = {
                "n": len(sub), "all": agg(sub),
                "claimed_recall_rate": round(
                    sum(1 for x in sub if x["recalled"]) / len(sub), 4)
                if sub else None,
                "by_project": {p: agg([x for x in sub if x["project"] == p])
                               for p in P}}
    tag = args.tag or args.stage
    (OUT / f"llm-{tag}-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    with (LLM / f"scored-{tag}.jsonl").open("w", encoding="utf-8") as f:
        for x in out_rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(json.dumps({k: summary[k] for k in
                      ("n_scored", "path_resolution", "parse_failures")},
                     indent=1))
    for p in P:
        s = summary["by_project"][p]
        if s["n_eval"]:
            print(f"{p:<9} n={s['n_eval']:<5} llm acc@5={s['all'].get('acc@5')}"
                  f" mrr={s['all'].get('mrr')}   ours acc@5="
                  f"{s['ours_same_instances'].get('acc@5')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
