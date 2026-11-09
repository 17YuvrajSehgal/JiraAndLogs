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
import pathlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mine_benchmark import PROJECTS, TEST_PATH, link_commits, run_git  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", force=True)
log = logging.getLogger("c7-localize")

ROOT = Path(__file__).resolve().parents[2]
G = ROOT / "data/derived/global/2026-06-17-wol-real-v3-global"
PRED = ROOT / "paper-results-v2/multiseed-hybrid/wol-v3/seed42/hybrid-rrf-predictions.jsonl"
BENCH = ROOT / "industry-c7/data/benchmark"
OUT = ROOT / "industry-c7/data/results"

# Derived from the miner's own PROJECTS rather than retyped. This was a
# hand-written map of four repos while the benchmark had four projects;
# at 27 it silently capped --project to the original four, so every new
# project was unreachable by the retrieval pipeline. Verified identical
# on the four they shared before the switch.
FULL_REPOS = {p: pathlib.Path(cfg["git_dir"])
              for p, cfg in PROJECTS.items()}

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


_PATH_TOKS: dict[str, Counter] = {}


def path_tokens(path: str) -> Counter:
    """Memoized path tokenization -- file paths repeat across the thousands
    of snapshots, so tokenizing each distinct path once removes the hottest
    per-instance loop."""
    c = _PATH_TOKS.get(path)
    if c is None:
        c = Counter(tokenize(path) + [Path(path).stem.lower()] * 2)
        _PATH_TOKS[path] = c
    return c


def tokenize(text: str) -> list[str]:
    toks = []
    for raw in TOKEN_RE.findall(text):
        for part in CAMEL_RE.split(raw):
            for piece in part.split("_"):
                if len(piece) >= 3:
                    toks.append(piece.lower())
    return toks


def bm25_rank(query_toks: list[str], docs: dict[str, Counter],
              k1: float = 1.2, b: float = 0.75,
              explain: dict[str, list[str]] | None = None) -> list[tuple[str, float]]:
    """Score docs (id -> token Counter) against the query; DF from the pool.
    If `explain` is given, it is filled with each doc's top-3 contributing
    terms. Scores and ordering are unaffected (provenance only)."""
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
        contrib: list[tuple[float, str]] = []
        for t, qtf in q.items():
            tf = c.get(t, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            w = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl)) * min(qtf, 3)
            s += w
            if explain is not None:
                contrib.append((w, t))
        if s > 0:
            scored.append((doc_id, s))
            if explain is not None:
                contrib.sort(reverse=True)
                explain[doc_id] = [t for _, t in contrib[:3]]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


class BM25Index:
    """Inverted-index BM25 for large fixed corpora (the per-call DF scan in
    bm25_rank is fine for a few hundred docs, hopeless for 40k memory docs)."""

    def __init__(self, docs: dict[str, Counter], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.dl = {d: sum(c.values()) for d, c in docs.items()}
        self.avgdl = (sum(self.dl.values()) / len(docs)) if docs else 1.0
        self.n = len(docs)
        self.post: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for d, c in docs.items():
            for t, tf in c.items():
                self.post[t].append((d, tf))

    def rank(self, qtoks: list[str], topn: int) -> list[str]:
        q = Counter(qtoks)
        scores: dict[str, float] = defaultdict(float)
        for t, qtf in q.items():
            plist = self.post.get(t)
            if not plist:
                continue
            df = len(plist)
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            w = idf * min(qtf, 3)
            for d, tf in plist:
                dl = self.dl[d]
                scores[d] += w * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return [d for d, _ in sorted(scores.items(),
                                     key=lambda x: (-x[1], x[0]))[:topn]]


def parse_iso_epoch(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("+0000", "+00:00")).timestamp()
    except ValueError:
        return None


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


def trace_rank(text: str, snap: Snapshot) -> tuple[list[str], bool, dict]:
    """Explicit file mentions first (extension or JVM frame), stem counts after.
    Returns (ranking, has_explicit_mention, detail) where detail maps each
    ranked file to how S1 found it ("explicit"/"stem") and the character
    offset of its first mention. has_explicit_mention is observable at
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
    detail = {f: {"kind": "explicit", "pos": int(p)} for f, p in explicit.items()}
    stems = []
    for f in snap.files:
        if f in explicit:
            continue
        stem = Path(f).stem
        n = text.count(stem) if len(stem) >= 4 else 0
        if n:
            stems.append((f, n * 1000 - text.find(stem)))
            detail[f] = {"kind": "stem", "pos": text.find(stem)}
    stems.sort(key=lambda x: (-x[1], x[0]))
    return (ranked + [f for f, _ in stems])[:LIST_LEN], bool(ranked), detail


def load_support(project: str, key_prefix: str):
    """Memory pool + firewall data.

    Preferred source: the PJD-derived pool (build_memory_pools.py) -- every
    fixed, fix-linked tracker issue votes, logs not required; true creation
    and resolution times; duplicate clusters from PJD issue links. Falls
    back to the old WoL-slice-derived pool when the files are absent.
    """
    pool_path = BENCH / f"{project}-memory.jsonl"
    mem_by_key: dict[str, dict] = {}
    if pool_path.exists():
        for line in pool_path.open(encoding="utf-8"):
            d = json.loads(line)
            mem_by_key[d["key"]] = {
                "key": d["key"],
                "resolved": parse_iso_epoch(d.get("resolved")) or d["fix_time"],
                "fix_shas": set(d["fix_shas"]),
                "gold_files": d["gold_files"],
                "toks": Counter(tokenize(f"{d.get('summary') or ''}\n{d.get('text') or ''}")),
            }
        dup = json.loads((BENCH / f"{project}-dupclusters.json")
                         .read_text(encoding="utf-8"))
        created = {k: parse_iso_epoch(v) for k, v in
                   json.loads((BENCH / f"{project}-created.json")
                              .read_text(encoding="utf-8")).items()}
        log.info("PJD memory pool: %d entries; dup-cluster keys: %d",
                 len(mem_by_key), len(dup))
    else:  # legacy WoL-slice pool (kafka/mariadb before build_memory_pools)
        cfg = PROJECTS[project]
        linked, _ = link_commits(cfg["git_dir"], key_prefix,
                                 cfg.get("link_via", "subject"))
        file_cache = json.loads((ROOT / f"data/c7-repos/cache-{project}.json")
                                .read_text(encoding="utf-8"))
        texts = {}
        for line in (G / "jira-memory-corpus.jsonl").open(encoding="utf-8"):
            d = json.loads(line)
            k = d.get("jira_issue_key") or ""
            # key_prefix may be a LIST: hadoop is one tracker with four
            # prefixes (HADOOP, HDFS, YARN, MAPREDUCE). list + "-" is a
            # TypeError, so this path would crash rather than mislead,
            # but it still has to work.
            if any(k.startswith(x + "-") for x in
                   ([key_prefix] if isinstance(key_prefix, str)
                    else key_prefix)):
                texts[k] = ((d.get("memory_text") or "")[:MEM_TEXT_CHARS],
                            parse_iso_epoch(d.get("available_as_memory_from")))
        for key, commits in linked.items():
            if not (1 <= len(commits) <= 3) or key not in texts:
                continue
            gold, shas = set(), []
            for c in sorted(commits, key=lambda c: c["ts"]):
                shas.append(c["sha"])
                for status, path in file_cache.get(c["sha"], []):
                    if (status == "M" and path.endswith(cfg["src_ext"])
                            and not TEST_PATH.search(path)):
                        gold.add(path)
            if gold:
                text, resolved = texts[key]
                mem_by_key[key] = {"key": key,
                                   "resolved": resolved or max(c["ts"] for c in commits),
                                   "fix_shas": set(shas),
                                   "gold_files": sorted(gold),
                                   "toks": Counter(tokenize(text))}
        dup, created = {}, {}
        log.info("legacy WoL-slice memory pool: %d entries", len(mem_by_key))

    # ARISE predictions exist only for the WoL-slice projects' windows
    wolm_to_key = {}
    preds: dict[str, list[str]] = {}
    if PROJECTS[project].get("source") != "wolv2":
        for line in (G / "jira-memory-corpus.jsonl").open(encoding="utf-8"):
            d = json.loads(line)
            wolm_to_key[d["jira_shadow_issue_id"]] = d.get("jira_issue_key") or ""
        for line in PRED.open(encoding="utf-8"):
            d = json.loads(line)
            preds[d["window_id"]] = [wolm_to_key.get(m, "")
                                     for m in (d.get("matched_issue_ids") or [])]
    return mem_by_key, dup, created, preds


def evaluate(ranking: list[str], gold: list[str]) -> dict:
    """Score one ranking against the files the fix commit touched.

    Definitions, stated here because the paper has to state them and
    because one of them is a trap:

      hit@k         at least one fix-touched file in the top k. This is
                    what the tables used to call acc@k; identical rule,
                    the name just says what it measures.
      recall@k      what FRACTION of the fix-touched files are in the
                    top k. The one that falls when an issue has many.
      precision@k   |gold & top-k| / k, textbook IR precision. CANNOT
                    REACH 1.0 on this benchmark: 51.3% of our issues
                    touched exactly one file, so a perfect answer
                    ranked first scores 1/5 = 0.2 at k=5. Reporting it
                    bare understates the system by a factor it has no
                    way to earn back, so precision_ceiling@k is emitted
                    beside it and the two must be read together.
      r_precision   |gold & top-R| / R where R is the number of
                    fix-touched files. Self-normalising: a one-file
                    issue is judged on the top 1, a six-file issue on
                    the top 6, and 1.0 is reachable for every instance.
                    This is the honest precision number for a benchmark
                    with a variable number of right answers.
      ap            average precision over the returned list: the mean
                    of precision@i at every rank i holding a gold file,
                    divided by min(len(ranking), |gold|) so the
                    denominator is what the list length allows. Rewards
                    putting ALL the fix-touched files high, which is
                    exactly what hit@k ignores.
      mrr           1/rank of the first gold file.

    acc@k is kept as an alias of hit@k so older result files, figures
    and the 417 pinned claims keep resolving.
    """
    gset = set(gold)
    n_gold = max(1, len(gset))
    hit_rank = next((i for i, f in enumerate(ranking) if f in gset), None)
    m = {"mrr": 1.0 / (hit_rank + 1) if hit_rank is not None else 0.0}
    for k in KS:
        top = ranking[:k]
        found = len(gset.intersection(top))
        m[f"acc@{k}"] = float(any(f in gset for f in top))
        m[f"hit@{k}"] = m[f"acc@{k}"]
        m[f"recall@{k}"] = found / n_gold
        m[f"precision@{k}"] = found / k
        # the most any system could score here, given how many files
        # this fix actually touched
        m[f"precision_ceiling@{k}"] = min(k, n_gold) / k
    r = len(gset)
    m["r_precision"] = len(gset.intersection(ranking[:r])) / n_gold
    hits = [i for i, f in enumerate(ranking, start=1) if f in gset]
    m["ap"] = (sum((j + 1) / i for j, i in enumerate(hits))
               / min(len(ranking), n_gold)) if hits and ranking else 0.0
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



def load_bench(project: str) -> list[dict]:
    """Benchmark rows for a project, minus the instances whose gold is only
    test code (see scripts/scored_set.py). Those are rankable -- the test
    files sit in the universe -- but a hit there means retrieving the test
    the fix edited, not localizing a defect. They are easier than average,
    so dropping them moves our own numbers down.
    Every system loads through here so they are all scored on one population.
    """
    from scored_set import load as _load_excluded
    excl = _load_excluded(BENCH)
    return [b for b in
            (json.loads(l) for l in
             (BENCH / f"{project}.jsonl").open(encoding="utf-8"))
            if f"{project}:{b['issue_key']}" not in excl]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, choices=list(FULL_REPOS))
    ap.add_argument("--limit", type=int, default=0, help="debug: first N instances")
    args = ap.parse_args()

    cfg = PROJECTS[args.project]
    git_dir = FULL_REPOS[args.project]
    bench = load_bench(args.project)
    if args.limit:
        bench = bench[:args.limit]
    mem_by_key, dupclusters, created_map, preds = load_support(
        args.project, cfg["key_prefix"])
    log.info("instances=%d memory-pool=%d", len(bench), len(mem_by_key))
    t_mi = time.perf_counter()
    mem_index = BM25Index({k: r["toks"] for k, r in mem_by_key.items()})
    mem_index_build_s = time.perf_counter() - t_mi

    tok_cache_path = OUT / f"blob-tokens-{args.project}.pkl"
    OUT.mkdir(parents=True, exist_ok=True)
    tok_cache: dict[str, Counter] = (pickle.loads(tok_cache_path.read_bytes())
                                     if tok_cache_path.exists() else {})

    rows, t0 = [], time.time()
    vote_stats = Counter()

    def memory_votes(candidate_keys: list[str], b: dict, cutoff: float,
                     qcluster, snap: Snapshot, tag: str
                     ) -> tuple[list[str], dict[str, list[str]]]:
        """Firewall: the query issue itself, its PJD duplicate cluster, any
        memory sharing a fix commit, any memory resolved after the query's
        creation (cutoff). Also returns {file: [voter issue keys]} for the
        provenance output."""
        votes: dict[str, float] = defaultdict(float)
        voters: dict[str, list[str]] = defaultdict(list)
        rank = 0
        for key in candidate_keys:
            rec = mem_by_key.get(key)
            if not rec:
                vote_stats[f"{tag}_not_in_pool"] += 1
                continue
            if key == b["issue_key"]:
                vote_stats[f"{tag}_fw_self"] += 1
                continue
            if qcluster is not None and dupclusters.get(key) == qcluster:
                vote_stats[f"{tag}_fw_dup_cluster"] += 1
                continue
            if rec["fix_shas"] & set(b["fix_shas"]):
                vote_stats[f"{tag}_fw_same_fix_commit"] += 1
                continue
            if rec["resolved"] is not None and rec["resolved"] > cutoff:
                vote_stats[f"{tag}_fw_resolved_later"] += 1
                continue
            vote_stats[f"{tag}_voted"] += 1
            rank += 1
            for f in rec["gold_files"]:
                if f in snap.blob_of:
                    votes[f] += 1.0 / rank
                    voters[f].append(key)
            if rank >= MEM_DEPTH:
                break
        ranking = [f for f, _ in
                   sorted(votes.items(), key=lambda x: (-x[1], x[0]))][:LIST_LEN]
        return ranking, dict(voters)

    for i, b in enumerate(bench):
        t_inst = time.perf_counter()
        snap = Snapshot(git_dir, b["snapshot_sha"], cfg["src_ext"])
        qtoks = tokenize(b["query_text"])
        # visibility cutoff: what an engineer could search when the bug
        # arrived -- true creation time when known, else fix time
        cutoff = (parse_iso_epoch(b.get("created"))
                  or created_map.get(b["issue_key"]) or b["fix_time"])
        qcluster = dupclusters.get(b["issue_key"])

        trace_grep, has_mention, s1_detail = trace_rank(b["query_text"], snap)
        path_docs = {f: path_tokens(f) for f in snap.files}
        path_ranked = [f for f, _ in bm25_rank(qtoks, path_docs)][:LIST_LEN]
        memory_arise, arise_voters = memory_votes(
            preds.get(b["window_id"], []), b, cutoff, qcluster, snap, "arise")
        memory_bm25, bm25_voters = memory_votes(
            mem_index.rank(qtoks, MEM_DEPTH * 4), b, cutoff, qcluster, snap, "bm25")

        pool = list(dict.fromkeys(trace_grep + path_ranked[:PATH_POOL]
                                  + memory_arise + memory_bm25))
        docs = snap.contents(pool, tok_cache)
        s3_terms: dict[str, list[str]] = {}
        content_ranked = [f for f, _ in
                          bm25_rank(qtoks, docs, explain=s3_terms)][:LIST_LEN]

        qtok_set = set(qtoks)
        rows.append({
            "_sig_s": time.perf_counter() - t_inst,
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
            # raw provenance, slimmed to the final top-20 at write time
            "_prov": {
                "s1": s1_detail,
                "s3_terms": s3_terms,
                "path_terms": {f: sorted(qtok_set & set(path_tokens(f)))[:3]
                               for f in path_ranked[:LIST_LEN]},
                "voters": {f: (bm25_voters.get(f, []) + arise_voters.get(f, []))[:5]
                           for f in set(bm25_voters) | set(arise_voters)},
            },
        })
        if i % 50 == 0:
            log.info("  %d/%d (%.0fs, blob cache %d)", i, len(bench),
                     time.time() - t0, len(tok_cache))
        # the pickle reaches hundreds of MB -- rewriting it every 50
        # instances dominated wall time once the cache warmed up
        if i and i % 500 == 0:
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
        t_f = time.perf_counter()
        systems = systems_for(r)
        # per-issue latency: signal computation + fusion, warm caches
        r["latency_s"] = round(r.pop("_sig_s") + time.perf_counter() - t_f, 6)
        r["metrics"] = {name: evaluate(ranking, r["gold_files"])
                        for name, ranking in systems.items()}

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
        "latency": (lambda ls: {
            "mem_index_build_s": round(mem_index_build_s, 3),
            "per_issue_median_s": round(ls[len(ls) // 2], 4),
            "per_issue_p95_s": round(ls[int(len(ls) * 0.95)], 4),
            "per_issue_mean_s": round(sum(ls) / len(ls), 4),
        })(sorted(r["latency_s"] for r in rows)),
    }
    (OUT / f"{args.project}-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    with (OUT / f"{args.project}-instances.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            slim = dict(r)
            # persist ALL systems' top-20 (incl. fused/conditioned) so
            # downstream aggregation (module metrics, stats) never has to
            # re-derive a fusion approximately
            systems = systems_for(r)
            slim["rankings"] = {s: lst[:20] for s, lst in systems.items()}
            # provenance for the final system's top-20: which signals ranked
            # each file (with rank), S1 mention detail, S2/S3 matching terms,
            # S4 voter issue keys (challenge output (iii))
            prov = slim.pop("_prov")
            out_prov = {}
            for file in systems["cond_ours"][:20]:
                entry = {"signals": {s: r["rankings"][s].index(file) + 1
                                     for s in r["rankings"]
                                     if file in r["rankings"][s]}}
                if file in prov["s1"]:
                    entry["mention"] = prov["s1"][file]
                if file in prov["path_terms"] and prov["path_terms"][file]:
                    entry["path_terms"] = prov["path_terms"][file]
                if file in prov["s3_terms"]:
                    entry["content_terms"] = prov["s3_terms"][file]
                if file in prov["voters"]:
                    entry["voted_by"] = prov["voters"][file]
                out_prov[file] = entry
            slim["provenance"] = out_prov
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


# A row whose ranking did not come from the model. On every such path the
# runner does NOT raise: it falls back to the lexical seed and writes a row
# with error=None, so the row looks finished and scores like a real answer.
#
# This used to be spelled inline as
#     r.get("error") or r.get("stop_reason") == "llm_error"
# in ten places. "llm_error" is what agent.py and baselines.py write. The
# LangChain arm (lc_agent.py, the arm the paper runs) writes
# "error:<ExceptionClass>" instead, which matches none of them. The result:
# a 30-instance pilot banked 5 rows of pure lexical baseline as agent
# results, resume refused to retry them, and the dead-server abort never
# fired. One mismatched string defeated three separate safeguards, so the
# predicate lives in one place now and every caller imports it.
#
# max_turns, no_tool_call, nudged and no_answer are real agent outcomes and
# are NOT dead: the model ran and simply did not finish well.
def is_dead_row(r: dict) -> bool:
    if r.get("error"):
        return True
    stop = r.get("stop_reason") or ""
    return stop == "llm_error" or stop.startswith("error:")


def match_symbol(funcs, symbol: str):
    """Match a submitted symbol against parsed (name, start, end) functions.

    ONE implementation, because there were nearly two. The agent resolves a
    submitted region at submit time (tools.Workspace.resolve_symbol) and the
    region scorer resolves it again at scoring time (function_stage.py). Two
    copies of a string-matching rule drift, and the last time a predicate
    was spelled out twice in this repo the two spellings disagreed and three
    safeguards silently stopped working.

    The rule: the model writes names the way a person would, so a few shapes
    are accepted. Arguments and template parameters are dropped, a fully
    qualified match wins over a bare one so Class::m does not collide with
    another class's m, and case is tried last. Anything else is a miss, and
    a miss is reported rather than repaired: a symbol the file does not
    contain is exactly what this field exists to expose.

    Returns the matching (name, start, end) tuple, or None.
    """
    if not funcs or not symbol:
        return None

    def strip_args(s: str) -> str:
        for cut in ("(", "<"):          # m(int a) -> m, f<T> -> f
            if cut in s:
                s = s.split(cut, 1)[0]
        return s.strip()

    def bare(s: str) -> str:
        for sep in ("::", "#", "."):    # Class::m, Class#m, Class.m -> m
            if sep in s:
                s = s.rsplit(sep, 1)[1].strip()
        return s

    want = strip_args(symbol.strip())
    if not want:
        return None
    names = [(f, strip_args(f[0])) for f in funcs]

    for f, n in names:                  # JOIN::exec == JOIN::exec
        if n == want:
            return f
    wl = want.lower()
    for f, n in names:
        if n.lower() == wl:
            return f

    wb = bare(want)                     # exec == JOIN::exec
    if not wb:
        return None
    hits = [f for f, n in names if bare(n) == wb]
    if not hits:
        wbl = wb.lower()
        hits = [f for f, n in names if bare(n).lower() == wbl]
    return hits[0] if hits else None


# ---- the main agent run, which is no longer one file --------------------
# It used to be data/agent/agent-v3-full.jsonl. The 26,544-instance run is
# now five project-disjoint shards, agent-full-s1..s5.jsonl, with s1
# historically named agent-full-trillium.jsonl. Eight scripts still opened
# the old name and died on FileNotFoundError, which is why this lives here
# instead of being pasted into each of them.
MAIN_RUN_GLOB = "agent-full-*.jsonl"


def agent_run_rows(agent_dir, glob_pat=None, drop_dead=True):
    """Every row of one agent run, read across its shards.

    glob_pat defaults to $C7_AGENT_GLOB, else the main run. That env var is
    how a caller scores a different seed: seed 7 writes agent-seed7-*.jsonl
    and seed 123 agent-seed123-*.jsonl, both outside the main-run glob on
    purpose, so no script needs editing to report a second seed.

    drop_dead removes rows the agent could not finish. It defaults to True
    because every caller wants that, and two of them had hand-written the
    test as `not r.get("error") and r.get("stop_reason") != "llm_error"`,
    which misses the error:<ClassName> that the lc arm actually writes.

    Refuses when one issue_key shows up in two files. That means the glob
    caught a second seed or two shards that overlap, and summing those
    would silently double-count instances.
    """
    import os as _os

    agent_dir = Path(agent_dir)
    pat = glob_pat or _os.environ.get("C7_AGENT_GLOB") or MAIN_RUN_GLOB
    files = sorted(agent_dir.glob(pat))
    if not files:
        raise FileNotFoundError(
            f"no agent run files matching {pat!r} in {agent_dir}. "
            f"The run is sharded now; set C7_AGENT_GLOB to pick another "
            f"seed, e.g. 'agent-seed7-*.jsonl'.")
    rows, seen, dead = [], {}, 0
    for f in files:
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                key = f"{r.get('project')}:{r.get('issue_key')}"
                if key in seen and seen[key] != f.name:
                    raise ValueError(
                        f"{key} appears in both {seen[key]} and {f.name}. "
                        f"Shards must be project-disjoint, so {pat!r} is "
                        f"matching more than one run.")
                seen[key] = f.name
                if drop_dead and is_dead_row(r):
                    dead += 1
                    continue
                rows.append(r)
    print(f"agent run: {len(rows)} rows from {len(files)} file(s) "
          f"matching {pat}" + (f", {dead} dead dropped" if dead else ""),
          flush=True)
    return rows
