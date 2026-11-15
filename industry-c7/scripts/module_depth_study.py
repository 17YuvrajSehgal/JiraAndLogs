"""Choose a module depth per project from the project's own build system.

Module-level metrics need a depth D per repository: how many leading path
components name one module. Picking D by eye is the part a reviewer
attacks, so D is chosen here against evidence the project itself ships.

A multi-module build DECLARES its modules. Maven puts a pom.xml at each
module root, Gradle a build.gradle, CMake a CMakeLists.txt, SCons a
SConscript, autotools a Makefile.am, qmake a .pro. So for every gold file
we can ask what module its own build system says it belongs to: the
deepest build-file directory that is a prefix of its path. Then D is the
depth whose module_of() agrees most often with that answer.

Also reported, because both are threats to validity a reviewer will raise:

  n_modules   how many modules D produces over the source universe. Too
              few and module accuracy is near-trivial.
  random      1/n_modules, the accuracy of guessing. A metric whose
              random baseline is 0.33 cannot carry a claim.

Usage:
    python industry-c7/scripts/module_depth_study.py
    python industry-c7/scripts/module_depth_study.py --project hive
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from localize import BENCH, FULL_REPOS, PROJECTS, load_bench  # noqa: E402
from module_metrics import module_of  # noqa: E402

BUILD_FILES = {"pom.xml", "build.gradle", "build.gradle.kts", "CMakeLists.txt",
               "SConscript", "SConstruct", "Makefile.am", "build.xml",
               "setup.py", "Cargo.toml", "meson.build"}
# Up to 7, not 4. Depth is NOT comparable across projects: Cassandra keeps
# source under src/java/org/apache/cassandra/, so five components pass
# before the first component that names a component an engineer would
# recognise, while Kafka's clients/ is a module at depth 1. A range that
# stops at 4 cannot even express Cassandra's answer.
DEPTHS = (1, 2, 3, 4, 5, 6, 7)


def tree(git_dir: Path, sha: str) -> list[str]:
    cp = subprocess.run(["git", "--git-dir", str(git_dir), "ls-tree", "-r",
                         "--name-only", sha], capture_output=True, text=True,
                        errors="replace", timeout=900)
    if cp.returncode != 0:
        return []
    return cp.stdout.splitlines()


def build_roots(paths: list[str], git_dir=None, sha=None) -> set[str]:
    """Directories a build file sits in. '' is the repo root.

    Gradle is the exception that matters: Kafka declares every subproject in
    a single settings.gradle at the root, so its module directories hold no
    build file of their own and a file-presence scan finds nothing. Those
    include lines are read directly.
    """
    out = set()
    for p in paths:
        i = p.rfind("/")
        name = p[i + 1:] if i >= 0 else p
        if name in BUILD_FILES or name.endswith(".pro"):
            out.add(p[:i] if i >= 0 else "")
    for p in paths:
        if p.rsplit("/", 1)[-1] in ("settings.gradle", "settings.gradle.kts")                 and git_dir is not None:
            cp = subprocess.run(["git", "--git-dir", str(git_dir), "cat-file",
                                 "-p", f"{sha}:{p}"], capture_output=True,
                                text=True, errors="replace", timeout=120)
            base = p.rsplit("/", 1)[0] + "/" if "/" in p else ""
            for m in re.finditer(r"""include\s*\(?\s*['"]:?([A-Za-z0-9_.:\-]+)""",
                                 cp.stdout):
                out.add(base + m.group(1).replace(":", "/"))
    return out


def declared_module(path: str, roots: set[str]) -> str | None:
    """Deepest build-file directory that is a prefix of path, excluding the
    repo root: the root declares the project, not a module within it."""
    best = None
    parts = path.split("/")
    for n in range(len(parts) - 1, 0, -1):
        cand = "/".join(parts[:n])
        if cand in roots:
            best = cand
            break
    return best


def analyse(project: str) -> dict:
    cfg = PROJECTS[project]
    rows = load_bench(project)
    # the newest snapshot: closest to the repo layout a reader would see
    sha = max(rows, key=lambda b: b["fix_time"])["snapshot_sha"]
    paths = tree(FULL_REPOS[project], sha)
    if not paths:
        return {"project": project, "error": "tree unreadable"}
    src = [p for p in paths if p.endswith(tuple(cfg["src_ext"]))]
    roots = build_roots(paths, FULL_REPOS[project], sha)
    gold = sorted({f for b in rows for f in b["gold_files"]})

    # how often each depth reproduces the build system's own answer
    agree, n_declared = {}, 0
    for d in DEPTHS:
        agree[d] = 0
    for f in gold:
        dm = declared_module(f, roots)
        if dm is None:
            continue
        n_declared += 1
        for d in DEPTHS:
            if module_of(f, d) == dm:
                agree[d] += 1

    per_depth = {}
    for d in DEPTHS:
        mods = {module_of(p, d) for p in src}
        gmods = collections.Counter()
        for b in rows:
            for m in {module_of(f, d) for f in b["gold_files"]}:
                gmods[m] += 1
        sizes = collections.Counter(module_of(p, d) for p in src)
        # majority baseline: always answer the single most common gold module.
        # If this is high the metric is close to free and a system beating it
        # only slightly has shown nothing.
        top = gmods.most_common(1)[0][0] if gmods else None
        maj = sum(1 for b in rows
                  if top in {module_of(f, d) for f in b["gold_files"]})
        per_depth[d] = {
            "n_modules": len(mods),
            "random": round(1 / max(len(mods), 1), 4),
            "majority": round(maj / max(len(rows), 1), 4),
            "median_files_per_module": sorted(sizes.values())[len(sizes) // 2]
            if sizes else 0,
            "singleton_modules": sum(1 for v in sizes.values() if v == 1),
            "n_gold_modules": len(gmods),
            "agree_with_build": round(agree[d] / n_declared, 4) if n_declared else None,
        }
    rootdepths = collections.Counter(r.count("/") + 1 for r in roots if r)
    return {"project": project, "snapshot": sha[:12], "n_paths": len(paths),
            "build_root_depths": dict(sorted(rootdepths.items())),
            "modal_build_depth": (rootdepths.most_common(1)[0][0]
                                  if rootdepths else None),
            "n_src": len(src), "n_build_roots": len(roots),
            "n_gold_files": len(gold), "n_gold_with_declared_module": n_declared,
            "declared_coverage": round(n_declared / max(len(gold), 1), 4),
            "depths": per_depth}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", action="append", choices=sorted(PROJECTS))
    ap.add_argument("--out", default="data/results/module-depth-study.json")
    args = ap.parse_args()
    projects = args.project or sorted(PROJECTS)

    out = {}
    print(f"{'project':12s} {'src':>7s} {'roots':>6s} {'decl':>6s}  "
          + "  ".join(f"d{d}:mods/agree" for d in DEPTHS))
    print("-" * 86)
    for p in projects:
        r = analyse(p)
        out[p] = r
        if "error" in r:
            print(f"{p:12s} ERROR {r['error']}")
            continue
        cells = []
        for d in DEPTHS:
            x = r["depths"][d]
            a = x["agree_with_build"]
            cells.append(f"{x['n_modules']:5d}/{'' if a is None else f'{a:.2f}'}")
        print(f"{p:12s} {r['n_src']:7d} {r['n_build_roots']:6d} "
              f"{r['declared_coverage']:6.2f}  " + "  ".join(cells), flush=True)
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
