"""Render frozen evidence packets for causal annotation (T1).

One markdown packet per sampled instance, containing exactly what the rubric
says the annotator may see:

  - the issue summary and description, with pasted logs and stack traces
  - the fix commit message(s)
  - the fix diff, per gold file
  - the file list with change status, and the snapshot size

BLINDNESS IS ENFORCED HERE, NOT BY INTENTION. This script reads only the
benchmark files and git. It never opens agent output, system rankings, or
the stratum label. assert_blind() re-reads every packet before it is
accepted and fails the run if a banned term appears, so a packet cannot
silently leak a system's answer into the annotation.

Usage:
    python industry-c7/scripts/annotation_render.py
    python industry-c7/scripts/annotation_render.py --only kafka:KAFKA-6624
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "industry-c7/data/benchmark-v2"
SAMPLE = ROOT / "industry-c7/annotation/sample.json"
PACKETS = ROOT / "industry-c7/annotation/packets"
REPOS = ROOT / "data/c7-repos"

MAX_REPORT_CHARS = 12_000       # keep logs; drop the long tail
MAX_DIFF_LINES_PER_FILE = 120
MAX_FILES_SHOWN = 25

# Terms that would mean a system's answer leaked into a packet.
BANNED = re.compile(
    r"\b(remember|acc@|mrr|rrf|ranking|ranked\s+list|agent|baseline|"
    r"retrieval\s+layer|bm25|gold_named_in_text|stratum|easy_gold|hard_gold|"
    r"predicted|prediction)\b", re.I)


def git(gd: Path, *a: str, timeout: int = 300) -> str:
    r = subprocess.run(["git", "--git-dir", str(gd), *a], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return r.stdout if r.returncode == 0 else ""


def shorten(text: str, limit: int) -> str:
    """Trim the middle, never the start or end: logs and stack traces tend to
    sit early, and the reporter's conclusion tends to sit last."""
    if len(text) <= limit:
        return text
    head = int(limit * 0.7)
    tail = limit - head
    return (text[:head] + f"\n\n[... {len(text) - limit:,} characters omitted "
            f"from the middle ...]\n\n" + text[-tail:])


def render(rec: dict, inst: dict) -> str:
    p = rec["project"]
    gd = REPOS / f"{p}-full.git"
    L = [f"# Annotation packet: {rec['issue_key']}  ({p})", ""]
    L += ["Label this against `annotation/RUBRIC.md`. You are seeing the issue "
          "as the reporter filed it, plus the change that eventually fixed it.",
          ""]

    L += ["## Issue report (as filed)", "",
          "```", shorten(inst["query_text"], MAX_REPORT_CHARS).strip(), "```", ""]

    L += ["## Fix commit message(s)", ""]
    for sha in inst["fix_shas"]:
        msg = git(gd, "log", "-1", "--format=%s%n%n%b", sha).strip()
        L += [f"`{sha[:12]}`", "", "```", shorten(msg, 3000).strip() or
              "(empty)", "```", ""]

    L += ["## Files the fix changed", "",
          f"Snapshot holds {inst.get('n_universe', 0):,} non-test source files. "
          f"The fix changed {inst['n_all_changed_files']} file(s); "
          f"{len(inst['gold_files'])} of them are non-test source files "
          f"(listed below as gold).", ""]
    # The LIST is never truncated: a label must carry a role for every gold
    # file, and annotation_validate.py rejects one that does not, so hiding
    # files here would make a complete label impossible to write. Only the
    # diffs below are capped, for packet size.
    for f in inst["gold_files"]:
        L.append(f"- `{f}`")
    if len(inst["gold_files"]) > MAX_FILES_SHOWN:
        L.append("")
        L.append(f"Diffs are shown for the first {MAX_FILES_SHOWN} of these "
                 f"{len(inst['gold_files'])} files.")
    L.append("")

    L += ["## The fix diff", ""]
    shown = 0
    for f in inst["gold_files"][:MAX_FILES_SHOWN]:
        # Gold is the UNION of the files these commits touched, and a single
        # file is often changed by more than one of them. Showing only the
        # first commit's diff hid the change that actually mattered: on
        # BEAM-4798 the first commit fixes a test and the second fixes the
        # reported IndexOutOfBoundsException. Show every commit that touched
        # the file, labelled, so the annotator sees the whole fix.
        parts = []
        for sha in inst["fix_shas"]:
            d = git(gd, "show", "--format=", "--unified=5", sha, "--", f)
            if d.strip():
                if len(inst["fix_shas"]) > 1:
                    parts.append(f"--- from commit {sha[:12]} ---")
                parts.append(d.rstrip())
        d = "\n".join(parts)
        lines = d.splitlines()
        if len(lines) > MAX_DIFF_LINES_PER_FILE:
            lines = lines[:MAX_DIFF_LINES_PER_FILE] + [
                f"[... {len(lines) - MAX_DIFF_LINES_PER_FILE} more diff lines ...]"]
        L += [f"### `{f}`", "", "```diff",
              "\n".join(lines) if lines else "(no diff retrieved)", "```", ""]
        shown += 1

    L += ["---", "",
          "## What to produce", "",
          "A JSON object matching `annotation/schema.json`: a role for every "
          "gold file above, the symptom and log locations, the relation, a "
          "rationale citing specific diff hunks or report lines, and a "
          "confidence. Use `unclear` rather than guessing.", ""]
    return "\n".join(L)


def assert_blind(path: Path) -> list[str]:
    """Re-read a written packet and report any banned term with context.

    Scans only prose this script generates. Fenced blocks hold the report,
    the commit message and the diff, which are quoted source evidence: a
    Kafka issue may legitimately say "agent" or "ranking", and flagging that
    would be a false positive. The footer after the final separator is
    instructions, not evidence.
    """
    txt = path.read_text(encoding="utf-8").rsplit("\n---\n", 1)[0]
    prose = re.sub(r"```.*?```", "", txt, flags=re.S)
    # Inline code spans are quoted evidence too: the gold file list renders
    # real repository paths in backticks, and Ambari ships a component called
    # "ambari-agent", which tripped \bagent\b on every Ambari packet. Strip
    # them for the same reason fenced blocks are stripped.
    prose = re.sub(r"`[^`\n]*`", "", prose)
    hits = []
    for m in BANNED.finditer(prose):
        s = max(0, m.start() - 40)
        hits.append(f"{m.group(0)!r} in ...{prose[s:m.end() + 40]!r}...")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    if not SAMPLE.exists():
        print("no sample.json; run annotation_sample.py first")
        return 2
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))

    v2 = {}
    for f in sorted(glob.glob(str(V2 / "*.jsonl"))):
        p = os.path.basename(f)[:-6]
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            v2[f"{p}:{r['issue_key']}"] = r

    PACKETS.mkdir(parents=True, exist_ok=True)
    todo = [r for r in sample["instances"]
            if not a.only or r["id"] == a.only]
    n_leak = 0
    for rec in todo:
        inst = v2.get(rec["id"])
        if inst is None:
            print(f"  MISSING from v2: {rec['id']}")
            continue
        out = PACKETS / f"{rec['project']}-{rec['issue_key']}.md"
        out.write_text(render(rec, inst), encoding="utf-8")
        leaks = assert_blind(out)
        if leaks:
            n_leak += 1
            print(f"  LEAK in {out.name}:")
            for h in leaks[:3]:
                print(f"     {h}")
    print(f"\nrendered {len(todo)} packets -> {PACKETS}")
    if n_leak:
        print(f"BLINDNESS CHECK FAILED on {n_leak} packets")
        return 1
    print("blindness check passed: no system output in any packet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
