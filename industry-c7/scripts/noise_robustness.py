"""Noise-robustness experiment (reviewer W4: industrial bundles are noisy).

Re-runs the full signal pipeline on PERTURBED query text for a seeded
sample of eval instances, fusing with the CLEAN-tuned conditioned weights
(noise arrives at inference time; nothing is retuned). Conditions:

  clean    unmodified text (sanity anchor; must reproduce the main run)
  dup      every added line is a repeat of a random line of the same text
  foreign  added lines sampled from OTHER issues' texts (same project)
  generic  added lines from generic timeout/retry/GC/health templates
  drop     remove every line carrying a file mention or JVM frame
           (deletes the evidence S1 feeds on; no levels)

Add conditions run at noise ratios x1, x2, x5 (added lines = ratio x
original line count), interleaved at seeded random positions.

Three further arms model failures the first four do not (T13-T15). The
first four are a fair start but none of them is what an on-call engineer
actually receives:

  mixed    k concurrent incidents of the same project, merged so that
           each stream KEEPS ITS OWN ORDER. This is the difference from
           `foreign`, which splices other issues' lines in at random
           positions and so destroys the ordering a reader relies on.
           Levels are k = 2, 3, 5 streams.
  cascade  the downstream consequences of the primary fault: timeouts,
           retries, circuit breakers and health-check failures that name
           the SAME symbol as the report. Unlike `generic`, these are
           lexically close to the real evidence, so they compete with it
           instead of merely diluting it, and they are appended after the
           decisive content rather than scattered through it. Levels are
           the usual x1, x2, x5.
  decisive remove the SINGLE highest-signal line, the one line whose
           tokens alone score the gold file highest under BM25. Sharper
           than `drop`, which removes every file mention and frame at
           once and therefore cannot say what one line was worth.

Usage:
    python industry-c7/scripts/noise_robustness.py --project kafka
"""

from __future__ import annotations

import argparse
import json
import pickle
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import localize  # noqa: E402
from localize import (BENCH, FILE_MENTION_RE, FULL_REPOS, JVM_FRAME_RE,  # noqa: E402
                      LIST_LEN, MEM_DEPTH, OUT, PATH_POOL, PROJECTS,
                      BM25Index, Snapshot, bm25_rank, load_bench,
                      load_support,
                      parse_iso_epoch, path_tokens, rrf, tokenize, trace_rank)

SEED = 42
SAMPLE = 200
RATIOS = (1, 2, 5)
# How many concurrent incident streams the `mixed` arm merges, the query's
# own stream included.
STREAMS = (2, 3, 5)
# A consequence of the fault, not a random log line: each template names a
# symbol taken from the report itself, so it survives lexical filtering and
# competes with the real evidence.
CASCADE_LINES = [
    "WARN {s} call timed out after {i} ms, retrying 1/3",
    "WARN {s} call timed out after {i} ms, retrying 2/3",
    "ERROR {s} retries exhausted, failing request",
    "WARN circuit breaker for {s} transitioned CLOSED -> OPEN after {i} failures",
    "ERROR circuit breaker for {s} is OPEN, rejecting call",
    "WARN connection pool exhausted waiting for {s} ({i} waiters queued)",
    "ERROR health check for {s} failed, marking instance unhealthy",
    "WARN downstream dependency {s} returned 503, backing off {i} ms",
    "ERROR request aborted: upstream {s} unavailable",
    "WARN thread pool queue for {s} at {i} entries, rejecting new work",
]
# Identifiers worth putting into a cascade line: CamelCase types and
# dotted/qualified names, which is what a real downstream error would name.
SYM_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]{2,}(?:\.[a-zA-Z0-9_]+)?)\b")
GENERIC_LINES = [
    "WARN request timed out after 30000 ms, retrying (attempt {i} of 10)",
    "INFO health check ok latency={i}ms",
    "WARN GC pause detected: {i} ms total stop-the-world",
    "ERROR connection reset by peer, reconnecting in {i}s",
    "INFO heartbeat sent to coordinator ({i} ms)",
    "WARN slow operation detected: {i} ms over threshold",
    "INFO periodic flush completed in {i} ms",
    "WARN queue depth {i} above watermark, applying backpressure",
]


def report_symbol(text: str, rng: random.Random) -> str:
    """A symbol the report itself names, for the cascade arm to blame.

    Falls back to a neutral component word rather than inventing an
    identifier: a cascade line naming a symbol that appears nowhere would
    be `generic` noise under another name."""
    syms = SYM_RE.findall(text)
    return rng.choice(syms) if syms else "the upstream service"


def merge_streams(streams: list[list[str]], rng: random.Random) -> list[str]:
    """Interleave k streams, each keeping its own internal order.

    Concurrent incidents produce logs that are shuffled against each other
    but never against themselves, which is exactly what `foreign` destroys
    by inserting at independent random positions."""
    pos = [0] * len(streams)
    out: list[str] = []
    live = [i for i, s in enumerate(streams) if s]
    while live:
        # Weight by what each stream has left, so a long stream does not
        # finish early and leave a clean unmixed tail.
        i = rng.choices(live, weights=[len(streams[j]) - pos[j]
                                       for j in live])[0]
        out.append(streams[i][pos[i]])
        pos[i] += 1
        live = [j for j in range(len(streams)) if pos[j] < len(streams[j])]
    return out


def decisive_line(lines: list[str], gold_docs: dict) -> int | None:
    """Index of the line whose tokens alone rank a gold file highest.

    Scored one line at a time against the gold documents only, so the
    number is "what this line is worth as evidence for the right answer",
    not its contribution to a ranking it shares with every other line."""
    if not gold_docs:
        return None
    best, best_i = 0.0, None
    for i, l in enumerate(lines):
        toks = tokenize(l)
        if not toks:
            continue
        ranked = bm25_rank(toks, gold_docs)
        if ranked and ranked[0][1] > best:
            best, best_i = ranked[0][1], i
    return best_i


def perturb(text: str, cond: str, ratio: int, rng: random.Random,
            foreign_pool: list[str], stream_pool: list[list[str]] | None = None,
            drop_idx: int | None = None) -> str:
    lines = text.splitlines() or [text]
    if cond == "clean":
        return text
    if cond == "drop":
        kept = [l for l in lines
                if not (FILE_MENTION_RE.search(l) or JVM_FRAME_RE.search(l))]
        return "\n".join(kept) if kept else ""
    if cond == "decisive":
        if drop_idx is None:
            return text
        kept = [l for i, l in enumerate(lines) if i != drop_idx]
        return "\n".join(kept) if kept else ""
    if cond == "mixed":
        pool = list(stream_pool or [])
        rng.shuffle(pool)
        others = [s for s in pool[:max(0, ratio - 1)] if s]
        return "\n".join(merge_streams([lines] + others, rng))
    if cond == "cascade":
        sym = report_symbol(text, rng)
        n_add = max(1, int(len(lines) * ratio))
        add = [rng.choice(CASCADE_LINES).format(s=sym,
                                                i=rng.randrange(1, 60000))
               for _ in range(n_add)]
        # Consequences follow the fault. Appending rather than interleaving
        # is the point: the decisive line keeps its position and is buried
        # by what came after it, which is how a real incident reads.
        return "\n".join(lines + add)
    n_add = max(1, int(len(lines) * ratio))
    if cond == "dup":
        add = [rng.choice(lines) for _ in range(n_add)]
    elif cond == "foreign":
        add = [rng.choice(foreign_pool) for _ in range(n_add)]
    else:  # generic
        add = [rng.choice(GENERIC_LINES).format(i=rng.randrange(1, 60000))
               for _ in range(n_add)]
    out = list(lines)
    for l in add:
        out.insert(rng.randrange(len(out) + 1), l)
    return "\n".join(out)


def selfcheck() -> int:
    """The properties that make the three new arms different from the old
    ones. If any of these breaks, the arm is silently measuring something
    else and the numbers still look plausible."""
    t = "line A\nline B about FooBar\nline C\nline D"

    # mixed: every stream keeps its own order, and nothing is lost.
    m = merge_streams([["a1", "a2", "a3"], ["b1", "b2"]], random.Random(7))
    assert sorted(m) == ["a1", "a2", "a3", "b1", "b2"], m
    for s in (["a1", "a2", "a3"], ["b1", "b2"]):
        idx = [m.index(x) for x in s]
        assert idx == sorted(idx), f"{s} reordered in {m}"

    # mixed at k=1 must be a no-op, so the level axis starts from clean.
    assert perturb(t, "mixed", 1, random.Random(0), [],
                   stream_pool=[["x"]]) == t

    # cascade: names a symbol the report actually contains, appends rather
    # than interleaves, and leaves the original lines untouched and in order.
    c = perturb(t, "cascade", 1, random.Random(3), []).splitlines()
    assert c[:4] == t.splitlines(), c[:4]
    assert all("FooBar" in l for l in c[4:]), c[4:]

    # decisive: removes exactly one line, and is a no-op when none was found.
    d = perturb(t, "decisive", 0, random.Random(0), [], drop_idx=1).splitlines()
    assert d == ["line A", "line C", "line D"], d
    assert perturb(t, "decisive", 0, random.Random(0), [], drop_idx=None) == t

    # decisive picks the line that actually scores the gold file, not line 0.
    lines = ["unrelated prose here", "NullPointerException in LogCleaner grind"]
    gold = {"LogCleaner.scala": Counter(tokenize(
        "class LogCleaner grind NullPointerException cleaner"))}
    assert decisive_line(lines, gold) == 1
    assert decisive_line(lines, {}) is None

    print("selfcheck OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", choices=list(FULL_REPOS))
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        return selfcheck()
    if not args.project:
        ap.error("--project is required unless --selfcheck")
    cfg, git_dir = PROJECTS[args.project], FULL_REPOS[args.project]

    # Through load_bench, NOT the raw file. The scored set drops 123 MongoDB
    # instances and lowers its n_dev from 1085 to 1061; slicing the unfiltered
    # 3,618-row file with the lowered boundary yields 2,557 "eval" rows where
    # the real split has 2,434 -- 24 development instances leaking into eval
    # and 99 excluded instances being scored. The same defect was fixed in
    # run_agent.py; this script still had it, and MongoDB is the only project
    # where the scored set removes anything, which is why the other three
    # reproduce their published numbers exactly and MongoDB does not.
    bench = load_bench(args.project)
    bench.sort(key=lambda b: b["fix_time"])
    summ = json.load((OUT / f"{args.project}-summary.json").open())
    n_dev = summ["n_dev"]
    w_cond = summ["tuned_weights"]["cond"]
    ev = bench[n_dev:]
    rng = random.Random(SEED)
    sample = sorted(rng.sample(range(len(ev)), min(SAMPLE, len(ev))))
    sample_b = [ev[i] for i in sample]
    # foreign noise: lines from OTHER eval issues of the same project
    foreign_all = {b["issue_key"]: [l for l in b["query_text"].splitlines()
                                    if l.strip()] for b in sample_b}

    mem_by_key, dupclusters, created_map, preds = load_support(
        args.project, cfg["key_prefix"])
    mem_index = BM25Index({k: r["toks"] for k, r in mem_by_key.items()})
    tok_cache_path = OUT / f"blob-tokens-{args.project}.pkl"
    tok_cache: dict[str, Counter] = (pickle.loads(tok_cache_path.read_bytes())
                                     if tok_cache_path.exists() else {})

    def memory_votes(candidate_keys, b, cutoff, qcluster, snap):
        votes, rank = defaultdict(float), 0
        for key in candidate_keys:
            rec = mem_by_key.get(key)
            if (not rec or key == b["issue_key"]
                    or (qcluster is not None and dupclusters.get(key) == qcluster)
                    or rec["fix_shas"] & set(b["fix_shas"])
                    or (rec["resolved"] is not None and rec["resolved"] > cutoff)):
                continue
            rank += 1
            for f in rec["gold_files"]:
                if f in snap.blob_of:
                    votes[f] += 1.0 / rank
            if rank >= MEM_DEPTH:
                break
        return [f for f, _ in
                sorted(votes.items(), key=lambda x: (-x[1], x[0]))][:LIST_LEN]

    def localize_one(b, snap, text):
        qtoks = tokenize(text)
        cutoff = (parse_iso_epoch(b.get("created"))
                  or created_map.get(b["issue_key"]) or b["fix_time"])
        qcluster = dupclusters.get(b["issue_key"])
        trace_grep, has_mention, _ = trace_rank(text, snap)
        path_docs = {f: path_tokens(f) for f in snap.files}
        path_ranked = [f for f, _ in bm25_rank(qtoks, path_docs)][:LIST_LEN]
        memory_arise = memory_votes(preds.get(b["window_id"], []), b, cutoff,
                                    qcluster, snap)
        memory_bm25 = memory_votes(mem_index.rank(qtoks, MEM_DEPTH * 4), b,
                                   cutoff, qcluster, snap)
        pool = list(dict.fromkeys(trace_grep + path_ranked[:PATH_POOL]
                                  + memory_arise + memory_bm25))
        docs = snap.contents(pool, tok_cache)
        content_ranked = [f for f, _ in bm25_rank(qtoks, docs)][:LIST_LEN]
        rk = {"trace_grep": trace_grep, "path_bm25": path_ranked,
              "content_bm25": content_ranked, "memory_arise": memory_arise,
              "memory_bm25": memory_bm25}
        regime = "mention" if has_mention else "no_mention"
        fused = rrf(rk, w_cond[regime])
        gset = set(b["gold_files"])
        return float(any(f in gset for f in fused[:5])), regime

    conds = ([("clean", 0)]
             + [(c, r) for c in ("dup", "foreign", "generic") for r in RATIOS]
             + [("drop", 0)]
             + [("mixed", k) for k in STREAMS]
             + [("cascade", r) for r in RATIOS]
             + [("decisive", 0)])
    acc = {f"{c}_x{r}" if r else c: [] for c, r in conds}
    regime_flips = Counter()
    n_decisive_found = 0
    t0 = time.time()
    for i, b in enumerate(sample_b):
        snap = Snapshot(git_dir, b["snapshot_sha"], cfg["src_ext"])
        pool = [l for k, ls in foreign_all.items()
                if k != b["issue_key"] for l in ls]
        # Whole other incidents, each kept in order, for the `mixed` arm.
        streams = [ls for k, ls in foreign_all.items()
                   if k != b["issue_key"] and ls]
        # The one line worth most as evidence, scored against the gold files
        # only. Gold files absent from the snapshot cannot be scored.
        #
        # Deliberately a THROWAWAY cache, not tok_cache. Snapshot.contents
        # only fetches blobs it does not already hold, so warming the shared
        # cache here would change which blobs the candidate-pool fetch asks
        # for, hence its cat-file batch, hence -- on MariaDB -- four of the
        # pre-existing conditions by one instance each. The new arm must not
        # be able to move the old numbers.
        gold_docs = snap.contents([f for f in b["gold_files"]
                                   if f in snap.blob_of], {})
        q_lines = b["query_text"].splitlines() or [b["query_text"]]
        d_idx = decisive_line(q_lines, gold_docs)
        n_decisive_found += d_idx is not None
        base_regime = None
        for c, r in conds:
            prng = random.Random(f"{SEED}:{b['issue_key']}:{c}:{r}")
            text = perturb(b["query_text"], c, r, prng, pool,
                           stream_pool=streams, drop_idx=d_idx)
            a5, regime = localize_one(b, snap, text)
            key = f"{c}_x{r}" if r else c
            acc[key].append(a5)
            if c == "clean":
                base_regime = regime
            elif regime != base_regime:
                regime_flips[key] += 1
        if i % 25 == 0:
            print(f"  {i}/{len(sample_b)} ({time.time() - t0:.0f}s)", flush=True)

    summary = {"project": args.project, "seed": SEED, "n_sample": len(sample_b),
               "weights": "clean-tuned cond (frozen)",
               "acc@5": {k: round(sum(v) / len(v), 4) for k, v in acc.items()},
               "regime_flips": dict(regime_flips),
               # How often a decisive line could be identified at all. Where
               # no gold file is in the snapshot, or no line scores above
               # zero, `decisive` degenerates to `clean` and the arm is
               # reported over this denominator, not over n_sample.
               "n_decisive_identified": n_decisive_found,
               "clean_main_run_acc5": summ["eval"]["cond_ours"]["acc@5"]}
    (OUT / f"{args.project}-noise-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["acc@5"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
