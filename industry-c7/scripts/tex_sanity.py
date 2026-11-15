"""Structural checks on the LaTeX sources, for when no toolchain is around.

This is not a compiler and does not pretend to be. It catches the small
class of mistakes that hand-editing tables and sections actually produces,
each of which fails the build or silently renders wrong:

  - unbalanced braces in a file
  - \\begin{X} without a matching \\end{X}
  - a tabular row whose cell count does not match its column spec
  - \\cref / \\ref to a label that does not exist
  - an undefined \\macro that looks like one of ours

Usage:
    python industry-c7/scripts/tex_sanity.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "paper"
B = chr(92)
LABEL = re.compile(B + B + r"label\{([^}]+)\}")
REF = re.compile(B + B + r"[cC]?ref\{([^}]+)\}")
NEWCMD = re.compile(B + B + r"newcommand\{" + B + B + r"([A-Za-z]+)\}")
USED = re.compile(B + B + r"([A-Za-z]+)\{?\}?")
BEGIN = re.compile(B + B + r"begin\{([A-Za-z*]+)\}")
END = re.compile(B + B + r"end\{([A-Za-z*]+)\}")
COLSPEC = re.compile(B + B + r"begin\{tabular\}(?:\[[^\]]*\])?\{([^}]*)\}")

fails: list[str] = []


def fail(msg: str) -> None:
    fails.append(msg)
    print(f"FAIL  {msg}")


def strip_comments(t: str) -> str:
    out = []
    for line in t.split("\n"):
        i, esc = 0, False
        while i < len(line):
            if line[i] == B and not esc:
                esc = True
            elif line[i] == "%" and not esc:
                line = line[:i]
                break
            else:
                esc = False
            i += 1
        out.append(line)
    return "\n".join(out)


def check_braces(name: str, t: str) -> None:
    depth, esc = 0, False
    for ch in t:
        if esc:
            esc = False
            continue
        if ch == B:
            esc = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                fail(f"{name}: a closing brace with nothing open")
                return
    if depth:
        fail(f"{name}: {depth} unclosed brace(s)")


def check_envs(name: str, t: str) -> None:
    stack = []
    for m in re.finditer(BEGIN.pattern + "|" + END.pattern, t):
        s = m.group(0)
        env = (m.group(1) or m.group(2))
        if "begin" in s:
            stack.append(env)
        else:
            if not stack:
                fail(f"{name}: end{{{env}}} with nothing open")
                return
            top = stack.pop()
            if top != env:
                fail(f"{name}: begin{{{top}}} closed by end{{{env}}}")
                return
    if stack:
        fail(f"{name}: unclosed environment(s) {stack}")


def balanced(t: str, i: int) -> tuple[str, int]:
    """The {...} starting at i, respecting nesting. A column spec like
    `{@{}lcccc@{}}` contains braces, so a non-greedy regex stops at the
    first one and reports zero columns."""
    assert t[i] == "{"
    depth, j = 0, i
    while j < len(t):
        if t[j] == "{":
            depth += 1
        elif t[j] == "}":
            depth -= 1
            if depth == 0:
                return t[i + 1:j], j + 1
        j += 1
    return "", len(t)


def check_tabulars(name: str, t: str) -> None:
    marker = B + "begin{tabular}"
    for m in re.finditer(re.escape(marker), t):
        k = m.end()
        if k < len(t) and t[k] == "[":            # optional [pos]
            k = t.find("]", k) + 1
        if k >= len(t) or t[k] != "{":
            continue
        spec, k = balanced(t, k)
        ncol = len(re.sub(r"[^lcrp]", "", re.sub(r"@\{[^}]*\}", "", spec)))
        if not ncol:
            fail(f"{name}: could not read a column spec from {spec!r}")
            continue
        body = t[k:]
        stop = body.find(B + "end{tabular}")
        if stop < 0:
            continue
        for raw in body[:stop].split(B + B):
            row = raw.strip()
            if not row or row.startswith(B + "toprule") or "rule" in row[:12]:
                continue
            row = re.sub(r"\\multicolumn\{(\d+)\}", "", row)
            if "multicolumn" in raw:
                continue
            cells = row.count("&") + 1
            if row and cells != ncol and "&" in row:
                fail(f"{name}: tabular wants {ncol} columns, row has {cells}: "
                     f"{row[:60]}")


def main() -> int:
    files = sorted(ROOT.glob("sections/*.tex")) + [ROOT / "main.tex"]
    texts = {f.name: strip_comments(f.read_text(encoding="utf-8")) for f in files}
    whole = "\n".join(texts.values())

    for name, t in texts.items():
        check_braces(name, t)
        check_envs(name, t)
        check_tabulars(name, t)

    labels = set(LABEL.findall(whole))
    for name, t in texts.items():
        for m in REF.finditer(t):
            for r in m.group(1).split(","):
                if r.strip() not in labels:
                    fail(f"{name}: reference to undefined label {r.strip()}")

    defined = set(NEWCMD.findall(texts["main.tex"]))
    # Only our own macros; anything from a package is out of scope here.
    ours = {"sys", "retr", "nInstances", "nProjects", "nHardPct", "nEval",
            "accFive", "accOne", "nAnnotated", "nCausalPct", "nCausalOne",
            "nCausalEight"}
    for name, t in texts.items():
        for m in USED.finditer(t):
            cmd = m.group(1)
            if cmd in ours and cmd not in defined:
                fail(f"{name}: uses \\{cmd} but main.tex does not define it")
    unused = sorted(ours & defined - set(USED.findall(whole)))
    if unused:
        print(f"note  defined but never used: {', '.join(unused)}")

    print(f"\n{len(files)} files, {len(labels)} labels, "
          f"{len(defined)} macros -- {len(fails)} problem(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
