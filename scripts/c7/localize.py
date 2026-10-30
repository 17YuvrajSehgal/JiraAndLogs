"""Challenge #7 localizer v0: rank snapshot files for each benchmark issue.

Signals, each producing a ranked file list over the snapshot universe
(non-test source files at the PARENT of the fix commit):

  trace_grep    files whose basename stem is mentioned in the issue text
                (mandatory baseline: the easy stratum is easy by construction)
  path_bm25     BM25 over path tokens vs. query tokens
  content_bm25  BM25 over file content, re-ranking a candidate pool
                (trace hits + top path hits + memory votes); DF computed
                within the pool, so no cross-snapshot statistics leak
  memory_vote   ARISE hybrid top-5 past incidents vote with their own fix
                commits' files, weight 1/rank. Firewall: the query's twin
                ticket, every twin in its duplicate cluster, any memory
                resolved after the query's fix time, and any memory sharing
                the query's fix commit.

Systems scored: each signal alone, RRF fusion without memory, RRF with
memory (ours). Metrics: Acc@K (any gold in top K), Recall@K, MRR; overall
and per stratum. Per-instance top-20 ranks persisted for paired stats.

Usage:
    python scripts/c7/localize.py --project kafka
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import pickle
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mine_benchmark import PROJECTS, TEST_PATH, link_commits, run_git  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", force=True)
log = logging.getLogger("c7-localize")

ROOT = Path(__file__).resolve().parents[2]
G = ROOT / "data/derived/global/2026-06-17-wol-real-v3-global"
PRED = ROOT / "paper-results-v2/multiseed-hybrid/wol-v3/seed42/hybrid-rrf-predictions.jsonl"
BENCH = ROOT / "data/c7-benchmark"
OUT = ROOT / "data/c7-results"

FULL_REPOS = {"kafka": ROOT / "data/c7-repos/kafka-full.git",
              "mariadb": ROOT / "data/c7-repos/mariadb-full.git"}

KS = (1, 5, 10)
RRF_K = 60
PATH_POOL = 200          # top path-BM25 hits admitted to the content pool
MAX_BLOB_BYTES = 500_000
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def tokenize(text: str) -> list[str]:
    toks = []
    for raw in TOKEN_RE.findall(text):
        for part in CAMEL_RE.split(raw):
            for piece in part.split("_"):
                if len(piece) >= 3:
                    toks.append(piece.lower())
    return toks


def bm25_rank(query_toks: list[str], docs: dict[str, Counter],
              k1: float = 1.2, b: float = 0.75) -> list[tuple[str, float]]:
    """Score docs (id -> token Counter) against the query; DF from the pool."""
    if not docs:
        return []
    n = len(docs)
    df = Counter()
    for c in docs.values():
        df.update(set(c))
    avgdl = sum(sum(c.values()) for c in docs.values()) / n or 1.0
    q = Counter(query_toks)
    scored = []
    for doc_id, c in docs.items():
        dl = sum(c.values())
        s = 0.0
        for t, qtf in q.items():
            tf = c.get(t, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl)) * min(qtf, 3)
        if s > 0:
            scored.append((doc_id, s))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[str]:
    s: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for r, f in enumerate(ranking):
            s[f] += 1.0 / (k + r + 1)
    return [f for f, _ in sorted(s.items(), key=lambda x: (-x[1], x[0]))]


class Snapshot:
    """File universe + lazy content access for one snapshot sha."""

    def __init__(self, git_dir: Path, sha: str, src_ext: tuple[str, ...]):
        self.git_dir = git_dir
        out = run_git(git_dir, "ls-tree", "-r", sha)
        self.blob_of: dict[str, str] = {}
        for line in out.splitlines():
            try:
                meta, path = line.split("\t", 1)
                _, otype, blob = meta.split()
            except ValueError:
                continue
            if otype == "blob" and path.endswith(src_ext) and not TEST_PATH.search(path):
                self.blob_of[path] = blob
        self.files = sorted(self.blob_of)

    def contents(self, paths: list[str], cache: dict[str, Counter]) -> dict[str, Counter]:
        need = [(p, self.blob_of[p]) for p in paths
                if p in self.blob_of and self.blob_of[p] not in cache]
        if need:
            inp = "\n".join(b for _, b in need)
            r = subprocess.run(["git", "--git-dir", str(self.git_dir),
                                "cat-file", "--batch"],
                               input=inp, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            pos, out = 0, r.stdout
            for _, blob in need:
                header_end = out.find("\n", pos)
                if header_end < 0:
                    break
                header = out[pos:header_end].split()
                size = int(header[2]) if len(header) == 3 and header[1] != "missing" else 0
                body = out[header_end + 1:header_end + 1 + size]
                pos = header_end + 1 + size + 1
                cache[blob] = Counter(tokenize(body[:MAX_BLOB_BYTES]))
        return {p: cache[self.blob_of[p]] for p in paths
                if p in self.blob_of and self.blob_of[p] in cache}


def load_support(project: str, key_prefix: str):
    mem = {}
    for line in (G / "jira-memory-corpus.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        ts = d.get("available_as_memory_from") or ""
        try:
            epoch = datetime.fromisoformat(ts.replace("+0000", "+00:00")).timestamp()
        except ValueError:
            epoch = None
        mem[d["jira_shadow_issue_id"]] = {"key": d.get("jira_issue_key"),
                                          "resolved": epoch}
    clusters = defaultdict(list)
    for line in (G / "global-triage-examples.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("triage_label") != "ticket_worthy":
            continue
        clusters[d.get("incident_episode_id") or d["window_id"]].append(d["window_id"])
    preds = {}
    for line in PRED.open(encoding="utf-8"):
        d = json.loads(line)
        preds[d["window_id"]] = list(d.get("matched_issue_ids") or [])
    # issue_key -> {fix_time, fix_shas, gold_files} for every linked issue,
    # from the miner's treeless clone + on-disk cache (no network when cached)
    cfg = PROJECTS[project]
    linked, _ = link_commits(cfg["git_dir"], key_prefix)
    cache_path = ROOT / f"data/c7-repos/cache-{project}.json"
    file_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    linkage = {}
    for key, commits in linked.items():
        if not (1 <= len(commits) <= 3):
            continue
        gold, shas = set(), []
        for c in sorted(commits, key=lambda c: c["ts"]):
            shas.append(c["sha"])
            for status, path in file_cache.get(c["sha"], []):
                if (status == "M" and path.endswith(cfg["src_ext"])
                        and not TEST_PATH.search(path)):
                    gold.add(path)
        linkage[key] = {"fix_time": max(c["ts"] for c in commits),
                        "fix_shas": shas, "gold_files": sorted(gold)}
    return mem, clusters, preds, linkage


def evaluate(ranks: dict[str, list[str]], gold: list[str]) -> dict:
    gset = set(gold)
    out = {}
    for name, ranking in ranks.items():
        hit_rank = next((i for i, f in enumerate(ranking) if f in gset), None)
        m = {"mrr": 1.0 / (hit_rank + 1) if hit_rank is not None else 0.0}
        for k in KS:
            top = ranking[:k]
            m[f"acc@{k}"] = float(any(f in gset for f in top))
            m[f"recall@{k}"] = len(gset.intersection(top)) / len(gset)
        out[name] = m
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, choices=list(FULL_REPOS))
    ap.add_argument("--limit", type=int, default=0, help="debug: first N instances")
    args = ap.parse_args()

    cfg = PROJECTS[args.project]
    git_dir = FULL_REPOS[args.project]
    bench = [json.loads(l) for l in
             (BENCH / f"{args.project}.jsonl").open(encoding="utf-8")]
    if args.limit:
        bench = bench[:args.limit]
    mem, clusters, preds, linkage = load_support(args.project, cfg["key_prefix"])
    log.info("instances=%d memory=%d linkage=%d", len(bench), len(mem), len(linkage))

    tok_cache_path = OUT / f"blob-tokens-{args.project}.pkl"
    OUT.mkdir(parents=True, exist_ok=True)
    tok_cache: dict[str, Counter] = (pickle.loads(tok_cache_path.read_bytes())
                                     if tok_cache_path.exists() else {})

    window_episode = {}
    for ep, members in clusters.items():
        for w in members:
            window_episode[w] = ep

    per_instance, t0 = [], time.time()
    memory_vote_stats = Counter()
    for i, b in enumerate(bench):
        snap = Snapshot(git_dir, b["snapshot_sha"], cfg["src_ext"])
        qtoks = tokenize(b["query_text"])
        text = b["query_text"]

        # --- trace_grep ------------------------------------------------------
        stem_hits = []
        for f in snap.files:
            stem = Path(f).stem
            n = text.count(stem) if len(stem) >= 4 else 0
            if n:
                stem_hits.append((f, n * 1000 - text.find(stem)))
        stem_hits.sort(key=lambda x: (-x[1], x[0]))
        trace_grep = [f for f, _ in stem_hits]

        # --- path_bm25 -------------------------------------------------------
        path_docs = {f: Counter(tokenize(f) + [Path(f).stem.lower()] * 2)
                     for f in snap.files}
        path_ranked = [f for f, _ in bm25_rank(qtoks, path_docs)]

        # --- memory_vote (firewalled) ---------------------------------------
        own_twin = "wol-m-" + b["window_id"][len("wol-q-"):]
        fw = {own_twin}
        for member in clusters.get(window_episode.get(b["window_id"], ""), []):
            fw.add("wol-m-" + member[len("wol-q-"):])
        votes: dict[str, float] = defaultdict(float)
        for r, mid in enumerate(preds.get(b["window_id"], [])):
            if mid in fw:
                memory_vote_stats["fw_twin_or_cluster"] += 1
                continue
            info = mem.get(mid)
            if not info or not info["key"]:
                continue
            link = linkage.get(info["key"])
            if not link:
                memory_vote_stats["no_linkage"] += 1
                continue
            if set(link["fix_shas"]) & set(b["fix_shas"]):
                memory_vote_stats["fw_same_fix_commit"] += 1
                continue
            if info["resolved"] is not None and info["resolved"] > b["fix_time"]:
                memory_vote_stats["fw_resolved_later"] += 1
                continue
            memory_vote_stats["voted"] += 1
            for f in link["gold_files"]:
                if f in snap.blob_of:
                    votes[f] += 1.0 / (r + 1)
                else:
                    memory_vote_stats["vote_file_not_in_snapshot"] += 1
        memory_vote = [f for f, _ in
                       sorted(votes.items(), key=lambda x: (-x[1], x[0]))]

        # --- content_bm25 over the candidate pool ----------------------------
        pool = list(dict.fromkeys(trace_grep + path_ranked[:PATH_POOL] + memory_vote))
        docs = snap.contents(pool, tok_cache)
        content_ranked = [f for f, _ in bm25_rank(qtoks, docs)]

        ranks = {
            "trace_grep": trace_grep,
            "path_bm25": path_ranked,
            "content_bm25": content_ranked,
            "memory_vote": memory_vote,
            "fused_no_memory": rrf([trace_grep, path_ranked, content_ranked]),
            "fused_ours": rrf([trace_grep, path_ranked, content_ranked, memory_vote]),
        }
        per_instance.append({
            "issue_key": b["issue_key"],
            "strata": {"easy": b["gold_named_in_text"], "trace": b["has_stack_trace"]},
            "n_universe": len(snap.files),
            "gold_files": b["gold_files"],
            "metrics": evaluate(ranks, b["gold_files"]),
            "top20": {s: r[:20] for s, r in ranks.items()},
        })
        if i % 25 == 0:
            log.info("  %d/%d (%.0fs, blob cache %d)", i, len(bench),
                     time.time() - t0, len(tok_cache))
            tok_cache_path.write_bytes(pickle.dumps(tok_cache))
    tok_cache_path.write_bytes(pickle.dumps(tok_cache))

    # ---- aggregate ----------------------------------------------------------
    systems = list(per_instance[0]["metrics"])
    metrics = list(per_instance[0]["metrics"][systems[0]])

    def agg(rows):
        return {s: {m: round(sum(r["metrics"][s][m] for r in rows) / len(rows), 4)
                    for m in metrics} for s in systems}

    summary = {
        "project": args.project, "n": len(per_instance),
        "memory_vote_stats": dict(memory_vote_stats),
        "overall": agg(per_instance),
        "easy": agg([r for r in per_instance if r["strata"]["easy"]]),
        "hard": agg([r for r in per_instance if not r["strata"]["easy"]]),
        "trace_present": agg([r for r in per_instance if r["strata"]["trace"]]),
        "trace_absent": agg([r for r in per_instance if not r["strata"]["trace"]]),
    }
    (OUT / f"{args.project}-v0-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    with (OUT / f"{args.project}-v0-instances.jsonl").open("w", encoding="utf-8") as f:
        for r in per_instance:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    hdr = f"{'system':<18}" + "".join(f"{m:>10}" for m in metrics)
    for part in ("overall", "easy", "hard"):
        rows = summary[part]
        print(f"\n--- {part} (n={len([r for r in per_instance if part=='overall' or r['strata']['easy']==(part=='easy')])}) ---")
        print(hdr)
        for s in systems:
            print(f"{s:<18}" + "".join(f"{rows[s][m]:>10.3f}" for m in metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
