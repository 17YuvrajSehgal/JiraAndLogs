"""Challenge #7 localizer: rank snapshot files for each benchmark issue.

Signals, each producing a ranked file list over the snapshot universe
(non-test source files at the PARENT of the fix commit):

  trace_grep    explicit file mentions (Foo.java, foo.cc:123, JVM frames),
                falling back to basename-stem counting -- the mandatory
                baseline the easy stratum hands a win to by construction
  path_bm25     BM25 over path tokens vs. query tokens
  content_bm25  BM25 over file content, re-ranking a candidate pool
                (trace hits + top path hits + memory votes); DF computed
                within the pool, so no cross-snapshot statistics leak
  memory_arise  ARISE hybrid top-5 past incidents vote with their fix
                commits' files, weight 1/rank (depth capped by what the
                persisted predictions contain)
  memory_bm25   BM25 over past incidents' ticket text at depth 20,
                restricted to time-valid linked incidents -- fixes the
                depth starvation measured in v0 (34% of ARISE hits were
                future tickets the firewall rightly discarded)

Memory firewall (both memory signals): the query's twin ticket, every twin
in its duplicate cluster, any memory resolved after the query's fix time,
any memory sharing the query's fix commit.

Fusion: unweighted RRF, plus weighted RRF whose weights are grid-tuned on a
TIME-BASED dev split (earliest 30% by fix time) and reported on the later
70% only. The with/without-memory ablation is tuned per variant so the
comparison is fair.

Usage:
    python scripts/c7/localize.py --project kafka
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import pickle
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
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
MEM_DEPTH = 20
LIST_LEN = 50            # rankings stored/fused at this depth
MAX_BLOB_BYTES = 500_000
MEM_TEXT_CHARS = 4_000
DEV_FRACTION = 0.3
WEIGHT_GRID = (0.0, 0.5, 1.0, 2.0)
SIGNALS = ("trace_grep", "path_bm25", "content_bm25", "memory_arise", "memory_bm25")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
FILE_MENTION_RE = re.compile(r"\b([A-Za-z_][\w$\-]*\.(?:java|scala|cc?|cpp|h|hpp|ic|yy))\b")
JVM_FRAME_RE = re.compile(r"\bat\s+[\w.$]+\.([A-Z]\w*)[.$]")


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


def rrf(rankings: dict[str, list[str]], weights: dict[str, float]) -> list[str]:
    s: dict[str, float] = defaultdict(float)
    for name, ranking in rankings.items():
        w = weights.get(name, 0.0)
        if not w:
            continue
        for r, f in enumerate(ranking):
            s[f] += w / (RRF_K + r + 1)
    return [f for f, _ in sorted(s.items(), key=lambda x: (-x[1], x[0]))][:LIST_LEN]


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
            inp = "\n".join(b for _, b in need).encode()
            # binary mode: sizes are in BYTES, and text=True's CRLF->LF
            # translation silently desyncs the offsets on CRLF-bearing blobs
            r = subprocess.run(["git", "--git-dir", str(self.git_dir),
                                "cat-file", "--batch"],
                               input=inp, capture_output=True)
            pos, out = 0, r.stdout
            for _, blob in need:
                header_end = out.find(b"\n", pos)
                if header_end < 0:
                    break
                header = out[pos:header_end].split()
                if len(header) == 3 and header[1] == b"blob":
                    size = int(header[2])
                    body = out[header_end + 1:header_end + 1 + size]
                    pos = header_end + 1 + size + 1
                else:  # "<sha> missing" or error line: header only, no body
                    size, body = 0, b""
                    pos = header_end + 1
                text = body[:MAX_BLOB_BYTES].decode("utf-8", errors="replace")
                cache[blob] = Counter(tokenize(text))
        return {p: cache[self.blob_of[p]] for p in paths
                if p in self.blob_of and self.blob_of[p] in cache}


def trace_rank(text: str, snap: Snapshot) -> tuple[list[str], bool]:
    """Explicit file mentions first (extension or JVM frame), stem counts after.
    Returns (ranking, has_explicit_mention) -- the flag is observable at
    inference time (no gold knowledge), unlike the easy/hard stratum label."""
    by_base: dict[str, list[str]] = defaultdict(list)
    for f in snap.files:
        by_base[Path(f).name].append(f)
    explicit: dict[str, float] = {}
    for m in FILE_MENTION_RE.finditer(text):
        for f in by_base.get(m.group(1), []):
            explicit[f] = min(explicit.get(f, m.start()), m.start())
    for m in JVM_FRAME_RE.finditer(text):
        for ext in (".java", ".scala"):
            for f in by_base.get(m.group(1) + ext, []):
                explicit[f] = min(explicit.get(f, m.start()), m.start())
    ranked = [f for f, _ in sorted(explicit.items(), key=lambda x: (x[1], x[0]))]
    stems = []
    for f in snap.files:
        if f in explicit:
            continue
        stem = Path(f).stem
        n = text.count(stem) if len(stem) >= 4 else 0
        if n:
            stems.append((f, n * 1000 - text.find(stem)))
    stems.sort(key=lambda x: (-x[1], x[0]))
    return (ranked + [f for f, _ in stems])[:LIST_LEN], bool(ranked)


def load_support(project: str, key_prefix: str):
    mem = {}
    for line in (G / "jira-memory-corpus.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        ts = d.get("available_as_memory_from") or ""
        try:
            epoch = datetime.fromisoformat(ts.replace("+0000", "+00:00")).timestamp()
        except ValueError:
            epoch = None
        key = d.get("jira_issue_key") or ""
        rec = {"key": key, "resolved": epoch}
        if key.startswith(key_prefix + "-"):
            rec["text"] = (d.get("memory_text") or "")[:MEM_TEXT_CHARS]
        mem[d["jira_shadow_issue_id"]] = rec
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
        if gold:
            linkage[key] = {"fix_time": max(c["ts"] for c in commits),
                            "fix_shas": shas, "gold_files": sorted(gold)}
    return mem, clusters, preds, linkage


def evaluate(ranking: list[str], gold: list[str]) -> dict:
    gset = set(gold)
    hit_rank = next((i for i, f in enumerate(ranking) if f in gset), None)
    m = {"mrr": 1.0 / (hit_rank + 1) if hit_rank is not None else 0.0}
    for k in KS:
        top = ranking[:k]
        m[f"acc@{k}"] = float(any(f in gset for f in top))
        m[f"recall@{k}"] = len(gset.intersection(top)) / len(gset)
    return m


def tune_weights(rows: list[dict], signals: tuple[str, ...]) -> dict[str, float]:
    """Grid-search RRF weights maximizing mean acc@5 on the dev rows."""
    best, best_w = -1.0, {s: 1.0 for s in signals}
    for combo in itertools.product(WEIGHT_GRID, repeat=len(signals)):
        if not any(combo):
            continue
        w = dict(zip(signals, combo))
        score = 0.0
        for r in rows:
            fused = rrf(r["rankings"], w)
            gset = set(r["gold_files"])
            score += float(any(f in gset for f in fused[:5]))
        score /= len(rows)
        if score > best + 1e-9:
            best, best_w = score, w
    log.info("tuned weights %s -> dev acc@5 %.4f", best_w, best)
    return best_w


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
    log.info("instances=%d memory=%d linked-with-gold=%d", len(bench), len(mem), len(linkage))

    # BM25 memory pool: linked, time-stamped, same-project tickets
    mem_pool = {mid: Counter(tokenize(rec["text"]))
                for mid, rec in mem.items()
                if rec.get("text") and rec["resolved"] is not None
                and rec["key"] in linkage}
    log.info("BM25 memory pool: %d tickets", len(mem_pool))

    tok_cache_path = OUT / f"blob-tokens-{args.project}.pkl"
    OUT.mkdir(parents=True, exist_ok=True)
    tok_cache: dict[str, Counter] = (pickle.loads(tok_cache_path.read_bytes())
                                     if tok_cache_path.exists() else {})

    window_episode = {}
    for ep, members in clusters.items():
        for w in members:
            window_episode[w] = ep

    rows, t0 = [], time.time()
    vote_stats = Counter()

    def memory_votes(candidates: list[str], b: dict, fw: set[str],
                     snap: Snapshot, tag: str) -> list[str]:
        votes: dict[str, float] = defaultdict(float)
        rank = 0
        for mid in candidates:
            if mid in fw:
                vote_stats[f"{tag}_fw_twin_or_cluster"] += 1
                continue
            info = mem.get(mid)
            link = linkage.get((info or {}).get("key") or "")
            if not link:
                vote_stats[f"{tag}_no_linkage"] += 1
                continue
            if set(link["fix_shas"]) & set(b["fix_shas"]):
                vote_stats[f"{tag}_fw_same_fix_commit"] += 1
                continue
            if info["resolved"] is not None and info["resolved"] > b["fix_time"]:
                vote_stats[f"{tag}_fw_resolved_later"] += 1
                continue
            vote_stats[f"{tag}_voted"] += 1
            rank += 1
            for f in link["gold_files"]:
                if f in snap.blob_of:
                    votes[f] += 1.0 / rank
            if rank >= MEM_DEPTH:
                break
        return [f for f, _ in sorted(votes.items(), key=lambda x: (-x[1], x[0]))][:LIST_LEN]

    for i, b in enumerate(bench):
        snap = Snapshot(git_dir, b["snapshot_sha"], cfg["src_ext"])
        qtoks = tokenize(b["query_text"])

        own_twin = "wol-m-" + b["window_id"][len("wol-q-"):]
        fw = {own_twin}
        for member in clusters.get(window_episode.get(b["window_id"], ""), []):
            fw.add("wol-m-" + member[len("wol-q-"):])

        trace_grep, has_mention = trace_rank(b["query_text"], snap)
        path_docs = {f: Counter(tokenize(f) + [Path(f).stem.lower()] * 2)
                     for f in snap.files}
        path_ranked = [f for f, _ in bm25_rank(qtoks, path_docs)][:LIST_LEN]
        memory_arise = memory_votes(preds.get(b["window_id"], []), b, fw, snap, "arise")
        mem_ranked = [mid for mid, _ in bm25_rank(qtoks, mem_pool)[:MEM_DEPTH * 4]]
        memory_bm25 = memory_votes(mem_ranked, b, fw, snap, "bm25")

        pool = list(dict.fromkeys(trace_grep + path_ranked[:PATH_POOL]
                                  + memory_arise + memory_bm25))
        docs = snap.contents(pool, tok_cache)
        content_ranked = [f for f, _ in bm25_rank(qtoks, docs)][:LIST_LEN]

        rows.append({
            "issue_key": b["issue_key"],
            "fix_time": b["fix_time"],
            "strata": {"easy": b["gold_named_in_text"], "trace": b["has_stack_trace"]},
            "regime": "mention" if has_mention else "no_mention",
            "n_universe": len(snap.files),
            "gold_files": b["gold_files"],
            "rankings": {
                "trace_grep": trace_grep,
                "path_bm25": path_ranked,
                "content_bm25": content_ranked,
                "memory_arise": memory_arise,
                "memory_bm25": memory_bm25,
            },
        })
        if i % 50 == 0:
            log.info("  %d/%d (%.0fs, blob cache %d)", i, len(bench),
                     time.time() - t0, len(tok_cache))
            tok_cache_path.write_bytes(pickle.dumps(tok_cache))
    tok_cache_path.write_bytes(pickle.dumps(tok_cache))

    # ---- time-based dev/eval split, tuning, systems --------------------------
    rows.sort(key=lambda r: r["fix_time"])
    n_dev = int(len(rows) * DEV_FRACTION)
    dev, ev = rows[:n_dev], rows[n_dev:]
    log.info("dev=%d (fix_time <= %s)  eval=%d", len(dev),
             datetime.fromtimestamp(dev[-1]["fix_time"]).date() if dev else "-", len(ev))

    no_mem_signals = ("trace_grep", "path_bm25", "content_bm25")
    w_no_mem = tune_weights(dev, no_mem_signals) if dev else {}
    w_ours = tune_weights(dev, SIGNALS) if dev else {}
    # regime-conditioned weights: the regime flag (explicit file mention in the
    # text) is observable at inference, so per-regime tuning is legal
    w_cond, w_cond_nm = {}, {}
    for regime in ("mention", "no_mention"):
        sub = [r for r in dev if r["regime"] == regime]
        log.info("regime %s: dev n=%d", regime, len(sub))
        w_cond[regime] = tune_weights(sub, SIGNALS) if sub else {s: 1.0 for s in SIGNALS}
        w_cond_nm[regime] = (tune_weights(sub, no_mem_signals) if sub
                             else {s: 1.0 for s in no_mem_signals})

    def systems_for(r: dict) -> dict[str, list[str]]:
        rk = r["rankings"]
        return {
            **rk,
            "fused_no_memory": rrf(rk, {s: 1.0 for s in no_mem_signals}),
            "fused_ours": rrf(rk, {s: 1.0 for s in SIGNALS}),
            "tuned_no_memory": rrf(rk, w_no_mem),
            "tuned_ours": rrf(rk, w_ours),
            "cond_no_memory": rrf(rk, w_cond_nm[r["regime"]]),
            "cond_ours": rrf(rk, w_cond[r["regime"]]),
        }

    for r in rows:
        r["metrics"] = {name: evaluate(ranking, r["gold_files"])
                        for name, ranking in systems_for(r).items()}

    system_names = list(rows[0]["metrics"])
    metric_names = list(rows[0]["metrics"][system_names[0]])

    def agg(subset):
        if not subset:
            return {}
        return {s: {m: round(sum(r["metrics"][s][m] for r in subset) / len(subset), 4)
                    for m in metric_names} for s in system_names}

    summary = {
        "project": args.project, "n_total": len(rows),
        "n_dev": len(dev), "n_eval": len(ev),
        "tuned_weights": {"no_memory": w_no_mem, "ours": w_ours,
                          "cond": w_cond, "cond_no_memory": w_cond_nm},
        "regime_counts_eval": dict(Counter(r["regime"] for r in ev)),
        "memory_vote_stats": dict(vote_stats),
        "eval": agg(ev),
        "eval_easy": agg([r for r in ev if r["strata"]["easy"]]),
        "eval_hard": agg([r for r in ev if not r["strata"]["easy"]]),
        "eval_trace_present": agg([r for r in ev if r["strata"]["trace"]]),
        "eval_trace_absent": agg([r for r in ev if not r["strata"]["trace"]]),
        "dev": agg(dev),
        "overall_all_rows": agg(rows),
    }
    (OUT / f"{args.project}-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    with (OUT / f"{args.project}-instances.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            slim = dict(r)
            slim["rankings"] = {s: lst[:20] for s, lst in r["rankings"].items()}
            f.write(json.dumps(slim, ensure_ascii=False) + "\n")

    hdr = f"{'system':<18}" + "".join(f"{m:>10}" for m in metric_names)
    for part, subset in (("eval", ev),
                         ("eval_easy", [r for r in ev if r["strata"]["easy"]]),
                         ("eval_hard", [r for r in ev if not r["strata"]["easy"]])):
        table = summary[part]
        print(f"\n--- {part} (n={len(subset)}) ---")
        print(hdr)
        for s in system_names:
            print(f"{s:<18}" + "".join(f"{table[s][m]:>10.3f}" for m in metric_names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
