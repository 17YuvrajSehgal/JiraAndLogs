"""Classic IRBL baselines (BugLocator, BRTracer-style) + the firewall-
leakage experiment.

BugLocator (Zhou et al., ICSE'12), re-implemented from the replication
descriptions (Bench4BL configs; ABLoTS replication; deep-IRBL survey):
  rVSM(f)      = g(|f|) * cosine_tfidf(query, file content), g = logistic
                 over min-max-normalized token length (favors large files)
  SimiScore(f) = sum over admissible past reports b that fixed f of
                 sim(query, b) / n_b,  n_b = |gold files of b|
  final        = (1-alpha) * N(rVSM) + alpha * N(SimiScore), min-max N,
                 alpha in {0.2, 0.3, 0.5}; 0.3 is the Bench4BL default,
                 best-on-dev reported as "tuned".

BRTracer-style = BugLocator + stack-trace boost (file at trace rank r
gets +1/r for r<=10, +0.1 beyond; Pathidea's restatement). NOTE: original
BRTracer also segments files (800-token max-segment scoring); we omit
segmentation and say so -- this is "BRTracer-style trace boost".

THE LEAKAGE EXPERIMENT -- SimiScore under five admissibility conditions:
  fw        all firewall rules (self, duplicate cluster, shared fix
            commit, resolved-after-query-creation)
  noR4      future reports admissible (no time cutoff)       -- rule 4 off
  noR2      duplicate cluster admissible                     -- rule 2 off
  noR3      shared-fix-commit reports admissible             -- rule 3 off
  leaky     only the query's own report excluded (the naive
            retrospective implementation)
The published IRBL literature never describes rules 2-4 (Bench4BL, ABLoTS
replication); "leaky" is therefore the literature-faithful setting.

Rankings for every (variant, alpha) are evaluated on the SAME eval split
and strata as the main system; per-instance metrics persisted for paired
bootstraps.

Usage:
    python industry-c7/scripts/baselines_irbl.py --project kafka
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import pickle
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import (BENCH, FULL_REPOS, OUT, Snapshot, evaluate, load_bench,  # noqa: E402
                      load_support, parse_iso_epoch, tokenize, trace_rank,
                      DEV_FRACTION)
from mine_benchmark import PROJECTS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", force=True)
log = logging.getLogger("c7-irbl")

ALPHAS = (0.2, 0.3, 0.5)
CONDITIONS = ("fw", "noR4", "noR2", "noR3", "leaky")
QUERY_TERM_CAP = 400       # keep the most informative query terms (by idf)
LIST_LEN = 50
TRACE_BOOST_CAP = 10


def norm(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    if hi <= lo:
        return {k: 0.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


class CosineIndex:
    """Inverted-index tf-idf cosine over a fixed report corpus (memory)."""

    def __init__(self, docs: dict[str, Counter]):
        self.n = len(docs)
        df = Counter()
        for c in docs.values():
            df.update(set(c))
        self.idf = {t: math.log(1 + self.n / d) for t, d in df.items()}
        self.vecs: dict[str, dict[str, float]] = {}
        self.post: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for doc_id, c in docs.items():
            w = {t: (1 + math.log(tf)) * self.idf.get(t, 0.0) for t, tf in c.items()}
            nrm = math.sqrt(sum(x * x for x in w.values())) or 1.0
            for t, x in w.items():
                self.post[t].append((doc_id, x / nrm))

    def sims(self, qtoks: list[str]) -> dict[str, float]:
        q = Counter(qtoks)
        qw = {t: (1 + math.log(tf)) * self.idf.get(t, 0.0) for t, tf in q.items()
              if t in self.post}
        qn = math.sqrt(sum(x * x for x in qw.values())) or 1.0
        out: dict[str, float] = defaultdict(float)
        for t, x in qw.items():
            for doc_id, dn in self.post[t]:
                out[doc_id] += (x / qn) * dn
        return out


def rvsm_scores(qtoks: list[str], docs: dict[str, Counter]) -> dict[str, float]:
    """rVSM: logistic length factor x tf-idf cosine, idf within the snapshot."""
    n = len(docs)
    df = Counter()
    for c in docs.values():
        df.update(set(c))
    idf = {t: math.log(1 + n / d) for t, d in df.items()}
    # cap query terms at the most informative ones
    q = Counter(qtoks)
    qterms = sorted(q, key=lambda t: -idf.get(t, 0.0))[:QUERY_TERM_CAP]
    qw = {t: (1 + math.log(q[t])) * idf.get(t, 0.0) for t in qterms}
    qn = math.sqrt(sum(x * x for x in qw.values())) or 1.0

    lens = {f: sum(c.values()) for f, c in docs.items()}
    lo, hi = min(lens.values()), max(lens.values())
    span = (hi - lo) or 1

    scores = {}
    for f, c in docs.items():
        dot = 0.0
        for t, w in qw.items():
            tf = c.get(t, 0)
            if tf:
                dot += w * (1 + math.log(tf)) * idf[t]
        if dot <= 0:
            continue
        dn = math.sqrt(sum(((1 + math.log(tf)) * idf.get(t, 0.0)) ** 2
                           for t, tf in c.items())) or 1.0
        g = 1.0 / (1.0 + math.exp(-6.0 * ((lens[f] - lo) / span - 0.5)))
        scores[f] = g * dot / (qn * dn)
    return scores


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, choices=list(FULL_REPOS))
    ap.add_argument("--limit", type=int, default=0)
    # T4 needs the IRBL rankings, not just their metrics, so they can be
    # re-scored against causal gold. Storing rankings for the whole benchmark
    # would multiply the file size by the number of baselines, so this stores
    # them only for the issue keys named in the file, into a side artifact.
    ap.add_argument("--rankings-for", type=Path, default=None,
                    help="file of issue keys, one per line; run only those "
                         "and write {project}-irbl-rankings.jsonl")
    args = ap.parse_args()

    cfg = PROJECTS[args.project]
    git_dir = FULL_REPOS[args.project]
    bench = load_bench(args.project)
    want = None
    if args.rankings_for:
        want = {k.strip() for k in args.rankings_for.read_text(
            encoding="utf-8").split() if k.strip()}
        bench = [b for b in bench if b["issue_key"] in want]
        log.info("--rankings-for: %d of the requested keys found", len(bench))
    if args.limit:
        bench = bench[:args.limit]
    mem_by_key, dupclusters, created_map, _ = load_support(
        args.project, cfg["key_prefix"])
    log.info("instances=%d memory-pool=%d", len(bench), len(mem_by_key))
    mem_index = CosineIndex({k: r["toks"] for k, r in mem_by_key.items()})

    tok_cache_path = OUT / f"blob-tokens-{args.project}.pkl"
    tok_cache: dict[str, Counter] = (pickle.loads(tok_cache_path.read_bytes())
                                     if tok_cache_path.exists() else {})

    rows, t0 = [], time.time()
    for i, b in enumerate(bench):
        snap = Snapshot(git_dir, b["snapshot_sha"], cfg["src_ext"])
        qtoks = tokenize(b["query_text"])
        cutoff = (parse_iso_epoch(b.get("created"))
                  or created_map.get(b["issue_key"]) or b["fix_time"])
        qcluster = dupclusters.get(b["issue_key"])
        qfix = set(b["fix_shas"])

        # --- rVSM over the FULL snapshot universe -------------------------
        docs = snap.contents(snap.files, tok_cache)
        rv = norm(rvsm_scores(qtoks, docs))

        # --- report-report similarities, then SimiScore per condition -----
        sims = mem_index.sims(qtoks)
        simi: dict[str, dict[str, float]] = {c: defaultdict(float)
                                             for c in CONDITIONS}
        for key, s in sims.items():
            rec = mem_by_key[key]
            if key == b["issue_key"]:
                continue  # excluded in every condition incl. leaky
            is_dup = qcluster is not None and dupclusters.get(key) == qcluster
            is_shared = bool(rec["fix_shas"] & qfix)
            is_future = rec["resolved"] is not None and rec["resolved"] > cutoff
            vote = s / max(1, len(rec["gold_files"]))
            for cond in CONDITIONS:
                if cond == "fw" and (is_dup or is_shared or is_future):
                    continue
                if cond == "noR4" and (is_dup or is_shared):
                    continue
                if cond == "noR2" and (is_shared or is_future):
                    continue
                if cond == "noR3" and (is_dup or is_future):
                    continue
                tgt = simi[cond]
                for f in rec["gold_files"]:
                    if f in snap.blob_of:
                        tgt[f] += vote
        simi_n = {c: norm(dict(v)) for c, v in simi.items()}

        # --- trace boost (BRTracer-style) ---------------------------------
        trace_list, _, _ = trace_rank(b["query_text"], snap)
        boost: dict[str, float] = {}
        for r, f in enumerate(trace_list[:LIST_LEN], start=1):
            boost[f] = (1.0 / r) if r <= TRACE_BOOST_CAP else 0.1

        # --- assemble rankings --------------------------------------------
        rankings: dict[str, list[str]] = {}

        def top(scores: dict[str, float]) -> list[str]:
            return [f for f, _ in sorted(scores.items(),
                                         key=lambda x: (-x[1], x[0]))][:LIST_LEN]

        rankings["rvsm"] = top(rv)
        for cond in CONDITIONS:
            rankings[f"simiscore_{cond}"] = top(simi_n[cond])
            for a in ALPHAS:
                comb = defaultdict(float)
                for f, v in rv.items():
                    comb[f] += (1 - a) * v
                for f, v in simi_n[cond].items():
                    comb[f] += a * v
                rankings[f"buglocator_{cond}_a{int(a*10)}"] = top(comb)
                if cond in ("fw", "leaky") and a == 0.3:
                    combt = dict(comb)
                    for f, v in boost.items():
                        combt[f] = combt.get(f, 0.0) + v
                    rankings[f"brtracer_{cond}"] = top(combt)

        rows.append({
            "issue_key": b["issue_key"],
            "fix_time": b["fix_time"],
            "strata": {"easy": b["gold_named_in_text"], "trace": b["has_stack_trace"]},
            "gold_files": b["gold_files"],
            "metrics": {name: evaluate(rk, b["gold_files"])
                        for name, rk in rankings.items()},
            **({"rankings": rankings} if want else {}),
        })
        if i % 25 == 0:
            log.info("  %d/%d (%.0fs, blob cache %d)", i, len(bench),
                     time.time() - t0, len(tok_cache))
        if i and i % 300 == 0:
            tok_cache_path.write_bytes(pickle.dumps(tok_cache))
    tok_cache_path.write_bytes(pickle.dumps(tok_cache))

    if want:
        out = OUT / f"{args.project}-irbl-rankings.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        log.info("wrote %s (%d rows); summary not touched", out, len(rows))
        return 0

    # --- aggregate on the same eval split as the main system ----------------
    rows.sort(key=lambda r: r["fix_time"])
    n_dev = int(len(rows) * DEV_FRACTION)
    dev, ev = rows[:n_dev], rows[n_dev:]

    sys_names = list(rows[0]["metrics"])
    metric_names = list(rows[0]["metrics"][sys_names[0]])

    def agg(subset):
        return {s: {m: round(sum(r["metrics"][s][m] for r in subset)
                             / max(1, len(subset)), 4)
                    for m in metric_names} for s in sys_names}

    # pick alpha on dev (acc@5) per condition for the "tuned" row
    tuned = {}
    for cond in CONDITIONS:
        best = max(ALPHAS, key=lambda a: sum(
            r["metrics"][f"buglocator_{cond}_a{int(a*10)}"]["acc@5"]
            for r in dev) / max(1, len(dev)))
        tuned[cond] = best

    summary = {
        "project": args.project, "n_total": len(rows),
        "n_dev": len(dev), "n_eval": len(ev),
        "tuned_alpha": tuned,
        "eval": agg(ev),
        "eval_hard": agg([r for r in ev if not r["strata"]["easy"]]),
        "eval_easy": agg([r for r in ev if r["strata"]["easy"]]),
    }
    (OUT / f"{args.project}-irbl-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    with (OUT / f"{args.project}-irbl-instances.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n--- {args.project} eval (n={len(ev)}), acc@5 / mrr ---")
    for s in sys_names:
        m = summary["eval"][s]
        print(f"{s:<24}{m['acc@5']:>8.3f}{m['mrr']:>8.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
