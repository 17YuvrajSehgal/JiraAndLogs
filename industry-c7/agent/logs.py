"""Log layer: select failure-relevant log events, and find the code that
printed them (T30, T31).

The challenge's first requirement is retrieval that "jointly understands log
semantics and code semantics". Before this module the agent saw the report
as one blob, cut at 18,000 characters, and searched code with BM25 over whole
files. Nothing knew which statement in the code printed a given log line.

Two pieces, both deterministic (no model), so a transcript still replays to
the same tool results:

  select_events   mask variables -> template, collapse repeats, rank events.
                  Ranking encodes the challenge's "noisy and incomplete logs":
                  the FIRST error is preferred over later ones (later errors
                  are usually downstream), and generic timeout / retry /
                  heartbeat lines are pushed down.
  LogIndex        every logging call and exception message in the snapshot,
                  as constant string fragments. A log line matches a
                  statement when the statement's fragments appear in it.

Matching is literal-fragment containment, the idea behind log-template
recovery from source (Xu et al., SOSP 2009) without the static analysis.
ponytail: one-line statements only; a call whose string literal starts on
the next line is missed. Add `git grep -A2` stitching if recall is low.
"""

from __future__ import annotations

import math
import re
import subprocess
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------
LEVEL_RE = re.compile(
    r"\b(FATAL|SEVERE|CRITICAL|PANIC|ERROR|ERR|WARN|WARNING|Warning|INFO|"
    r"Note|DEBUG|TRACE)\b")
TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}:\d{2}"     # 2020-11-12 08:43:30
    r"|\b\d{6}\s+\d{1,2}:\d{2}:\d{2}\b"             # mysqld 200101 10:00:00
    r"|\b\d{1,2}:\d{2}:\d{2}[.,]\d{3}\b"            # 08:43:30,351
    r'|"t":\{"\$date"')                             # mongod JSON log
JSON_SEV_RE = re.compile(r'"s":"([FEWID])\d?"')
EXC_RE = re.compile(r"\b[\w.$]*(?:Exception|Error)\b(?::\s*\S.*)?$")
ASSERT_RE = re.compile(r"Assertion\b.*failed|Invariant failure|"
                       r"\bfassert|\bmassert|\buassert|tassert|Segmentation fault"
                       r"|got signal \d+|\bSIG(?:SEGV|ABRT|BUS)\b")
FRAME_LINE_RE = re.compile(
    r"^\s*(?:at\s+[\w.$<>]+\(|#\d+\s+0x[0-9a-f]+|\.\.\.\s*\d+\s+more|"
    r"Caused by:\s*$|\S+\(\+0x[0-9a-f]+\))")
# Downstream consequences, not causes. Same family as the noise experiment's
# GENERIC_LINES and CASCADE_LINES (T14), which is the point: these lines are
# what the noise arms add.
GENERIC_RE = re.compile(
    r"time[sd]?\s*out|timeout|retry|retrying|reconnect|heartbeat|health\s*check"
    r"|backing off|backoff|GC pause|connection reset|circuit breaker"
    r"|rejecting|unavailable|exhausted", re.I)

LEVEL_W = {"FATAL": 4, "SEVERE": 4, "CRITICAL": 4, "PANIC": 4, "F": 4,
           "ERROR": 3, "ERR": 3, "E": 3, "WARN": 2, "WARNING": 2, "Warning": 2,
           "W": 2, "INFO": 1, "Note": 1, "I": 1, "DEBUG": 0.5, "TRACE": 0.5,
           "D": 0.5}

_MASKS = [
    # identifier-ish values: replica_VIT->replica_UGO, topic-0, a/b, k=v.
    # First, so it never re-masks the <n>/<hex> placeholders below.
    (re.compile(r"(?<!\S)(?=\S*[_\-/>=@:.])(?=\S*[A-Za-z])\S+(?!\S)"), "<v>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
                r"[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (TS_RE, "<ts>"),
    (re.compile(r"\b\d+(?:[.,]\d+)?\b"), "<n>"),
]


JIRA_MARKUP_RE = re.compile(r"\{(?:quote|code|noformat|panel|color)[^}]*\}")


def template(line: str) -> str:
    """Variables masked, so repeats of one statement share a key."""
    t = JIRA_MARKUP_RE.sub("", line).strip()
    for rx, tok in _MASKS:
        t = rx.sub(tok, t)
    return re.sub(r"\s+", " ", t)


def classify(line: str) -> str | None:
    """'frame', 'event', or None for prose."""
    s = line.strip()
    if not s:
        return None
    if FRAME_LINE_RE.search(s):
        return "frame"
    if (TS_RE.search(s) or ASSERT_RE.search(s) or JSON_SEV_RE.search(s)
            or (LEVEL_RE.search(s) and len(s) < 600)
            or EXC_RE.search(s[:300])):
        return "event"
    return None


def _level(s: str) -> float:
    if ASSERT_RE.search(s):
        return 4.0
    m = JSON_SEV_RE.search(s)
    if m:
        return LEVEL_W[m.group(1)]
    m = LEVEL_RE.search(s)
    if m:
        return LEVEL_W.get(m.group(1), 1.0)
    if EXC_RE.search(s[:300]):
        return 3.0
    return 1.0


def select_events(text: str, k: int = 12) -> list[dict]:
    """The k most failure-relevant distinct log events, in report order.

    Each event: id (E1..), line (first occurrence, verbatim), count (how many
    lines share its template), level, score, generic (bool).
    """
    groups: dict[str, dict] = {}
    order = 0
    for i, raw in enumerate(text.splitlines()):
        if classify(raw) != "event":
            continue
        line = raw.strip()[:400]
        t = template(line)
        g = groups.get(t)
        if g:
            g["count"] += 1
            continue
        groups[t] = {"line": line, "pos": i, "count": 1,
                     "level": _level(line), "order": order,
                     "generic": bool(GENERIC_RE.search(line))}
        order += 1
    if not groups:
        return []
    evs = list(groups.values())
    # first-error bonus: among error-level events, earlier ranks higher,
    # because a later error is more often a consequence than a cause
    errs = sorted((e for e in evs if e["level"] >= 3), key=lambda e: e["order"])
    for r, e in enumerate(errs):
        e["first_err_bonus"] = 1.5 / (1 + r)
    for e in evs:
        s = e["level"] + e.get("first_err_bonus", 0.0)
        if e["generic"]:
            s *= 0.5
        e["score"] = round(s, 3)
    top = sorted(evs, key=lambda e: (-e["score"], e["order"]))[:k]
    top.sort(key=lambda e: e["order"])
    return [{"id": f"E{n + 1}", "line": e["line"], "count": e["count"],
             "level": e["level"], "score": e["score"], "generic": e["generic"]}
            for n, e in enumerate(top)]


def compress_report(text: str, limit: int = 18000) -> tuple[str, dict]:
    """Collapse repeated log and frame lines, then cut head + tail.

    The old cut was text[:18000]: a 700k-char MongoDB bundle lost everything
    after its first repeats. Repeats go first now; prose is never collapsed.
    """
    seen: Counter = Counter()
    first_idx: dict[str, int] = {}
    out: list[str] = []
    for raw in text.splitlines():
        kind = classify(raw)
        if kind is None:
            out.append(raw)
            continue
        t = template(raw)
        seen[t] += 1
        if seen[t] == 1:
            first_idx[t] = len(out)
            out.append(raw)
    for t, n in seen.items():
        if n > 1:
            out[first_idx[t]] += f"   [x{n} similar lines]"
    body = "\n".join(out)
    stats = {"chars_in": len(text), "chars_collapsed": len(body),
             "lines_dropped_as_repeats": sum(n - 1 for n in seen.values())}
    if len(body) > limit:
        head, tail = int(limit * 0.7), int(limit * 0.3)
        body = (body[:head] + f"\n[... {len(body) - head - tail} chars omitted; "
                "the selected log events below are taken from the FULL "
                "report ...]\n" + body[-tail:])
    stats["chars_out"] = len(body)
    return body, stats


# ---------------------------------------------------------------------------
# log statements in the code
# ---------------------------------------------------------------------------
# Coarse ERE for git grep (portable; the cluster's git may lack PCRE), then
# the precise Python regex below decides. Run with -A2 so a call whose
# message literal sits on the next line (MongoDB's LOGV2(id,\n "msg")) is kept.
GREP_ERE = (r'(log|LOG|Log|logger|Logger|LOGGER|LOGV2|throw|assert|sql_print_|'
            r'my_error|my_printf_error|ib::|qWarning|qCritical|qFatal|qDebug|'
            r'qInfo|qCWarning|qCCritical|qCDebug|qCInfo|fprintf|error|warn|'
            r'fatal|panic|raise|invariant|verify)[A-Za-z0-9_]*[ \t]*'
            r'(\(|\.|->|::| new)')
CTX_RE = re.compile(r"^[0-9a-f]+:(.+?)-(\d+)-(.*)$")
CALL_RE = re.compile(
    r"\b(?:log|LOG|Log|logger|Logger|LOGGER|_log|_logger|log_|logger_)\w*\s*"
    r"(?:\.|->|::)\s*(?:trace|debug|info|warn|warning|error|fatal|severe)\w*\s*\("
    r"|\bLOGV2\w*\s*\(|\bthrow\s+new\s+\w+|\bthrow\s+\w+\s*\("
    r"|\b(?:uasserted|uassert|massert|msgasserted|fassert\w*|tassert|iassert"
    r"|invariant\w*|verify)\s*\("
    r"|\bsql_print_\w+\s*\(|\bmy_(?:printf_)?error\s*\(|\bib::\w+\s*\(\s*\)"
    r"|\bqC?(?:Warning|Critical|Fatal|Debug|Info)\s*\("
    r"|\bfprintf\s*\(\s*stderr|\b(?:error|warn|fatal|panic)\s*\("
    r"|\braise\s+\w+")
STR_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
# printf specifiers, {} / {0} placeholders, Qt %1, Scala $x / ${x}
FMT_RE = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?(?:hh|h|ll|l|z|j|t|L|I64)?"
                    r"[diouxXeEfgGcspn]|\{\d*\}|%\d|\$\{[^}]*\}|\$\w+|\\[ntr]")
WORD_RE = re.compile(r"[A-Za-z]{4,}")
MAX_DF = 1500


def fragments(code_line: str) -> list[str]:
    frags = []
    for lit in STR_RE.findall(code_line):
        for f in FMT_RE.split(lit):
            f = f.strip(" :=,;.'()[]")
            if sum(c.isalpha() for c in f) >= 3:
                frags.append(f)
    return frags


class LogIndex:
    """Logging statements and exception messages of ONE snapshot."""

    def __init__(self, ws):
        self.ws = ws
        self.stmts: list[dict] = []
        self.by_word: dict[str, list[int]] = defaultdict(list)
        try:
            r = subprocess.run(
                ["git", "--git-dir", str(ws.git_dir), "grep", "-n", "-I", "-E",
                 "-A2", "-e", GREP_ERE, ws.sha],
                capture_output=True, timeout=300)
            out = r.stdout.decode("utf-8", "replace").splitlines()
        except Exception:  # noqa: BLE001 - no index is a weaker run, not a dead one
            out = []
        # context lines that follow each match, keyed by (path, line)
        ctx: dict[tuple, str] = {}
        for row in out:
            m = CTX_RE.match(row)
            # a misparsed match line yields "path:12:..." as the path,
            # which is never a snapshot file
            if m and m.group(1) in ws.snap.blob_of:
                ctx[(m.group(1), int(m.group(2)))] = m.group(3)
        for row in out:
            try:
                _sha, path, lno, text = row.split(":", 3)
                lno = int(lno)
            except ValueError:
                continue
            if path not in ws.snap.blob_of or not CALL_RE.search(text):
                continue
            frags = fragments(text)
            if not frags and not text.rstrip().endswith(";"):
                frags = fragments(" ".join(ctx.get((path, lno + d), "")
                                           for d in (1, 2)))
            if not frags:
                continue
            sid = len(self.stmts)
            self.stmts.append({"file": path, "line": int(lno),
                               "code": text.strip()[:200], "frags": frags,
                               "total": sum(len(f) for f in frags)})
            for w in {w.lower() for f in frags for w in WORD_RE.findall(f)}:
                self.by_word[w].append(sid)

    def match(self, line: str, k: int = 5) -> list[dict]:
        """Statements whose constant text appears in this log line."""
        low = line.lower()
        cand: set[int] = set()
        for w in set(WORD_RE.findall(low)):
            ids = self.by_word.get(w)
            if ids and len(ids) <= MAX_DF:
                cand.update(ids)
        # log4j/logback print the logger, which is usually the class name
        classes = {c.rsplit(".", 1)[-1].lower()
                   for c in re.findall(r"\b(?:[a-z]\w*\.)+([A-Z]\w+)\b", line)}
        scored = []
        for sid in cand:
            s = self.stmts[sid]
            cov = sum(len(f) for f in s["frags"] if f.lower() in low)
            if cov < 8:
                continue
            frac = cov / s["total"]
            if cov < 15 and frac < 1.0:
                continue
            stem = s["file"].rsplit("/", 1)[-1].split(".")[0].lower()
            score = cov * (0.5 + frac) + (20 if stem in classes else 0)
            scored.append((score, frac, sid))
        scored.sort(key=lambda x: -x[0])
        out, seen = [], set()
        for score, frac, sid in scored:
            s = self.stmts[sid]
            key = (s["file"], s["line"])
            if key in seen:
                continue
            seen.add(key)
            fn = next((f for f, a, b in self.ws._funcs_of(s["file"])
                       if a <= s["line"] <= b), None)
            out.append({"file": s["file"], "line": s["line"],
                        "function": fn or "(file scope)", "code": s["code"],
                        "coverage": round(frac, 2), "score": round(score, 1)})
            if len(out) >= k:
                break
        return out


def _selfcheck() -> None:
    rep = ("Consumer stops\n"
           "[2020-11-12 08:43:30,351] INFO creating herder for a->b (org.x.MirrorMaker)\n"
           "[2020-11-12 08:43:33,697] INFO creating herder for c->d (org.x.MirrorMaker)\n"
           "[2020-11-12 08:44:00,000] WARN request timed out after 3000 ms, retrying\n"
           "[2020-11-12 08:44:01,000] ERROR Failed to assign partition 7 to member x\n"
           "java.lang.IllegalStateException: No current assignment for partition t-0\n"
           "\tat org.x.SubscriptionState.assignedState(SubscriptionState.java:1)\n")
    ev = select_events(rep, k=3)
    lines = [e["line"] for e in ev]
    assert any("Failed to assign" in l for l in lines), lines
    assert any("IllegalStateException" in l for l in lines), lines
    assert not any("timed out" in l for l in lines), "generic line ranked top-3"
    assert template("x 12 at 0x1f") == "x <n> at <hex>"
    body, st = compress_report(rep)
    assert st["lines_dropped_as_repeats"] == 1 and "[x2 similar" in body, st
    assert classify("\tat a.b.C.d(C.java:1)") == "frame"
    assert fragments('log.info("creating herder for {}->{}", a, b);') == \
        ["creating herder for"]
    assert fragments('throw new IllegalStateException("No current assignment '
                     'for partition " + tp);') == ["No current assignment for partition"]
    assert fragments('sql_print_error("InnoDB: Cannot open %s.", name);') == \
        ["InnoDB: Cannot open"]
    assert CALL_RE.search('LOGV2_ERROR(4615, "Failed to refresh", "e"_attr=e);')
    assert math.isclose(LEVEL_W["ERROR"], 3)
    print("logs.py selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
