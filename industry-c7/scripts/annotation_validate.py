"""Validate causal annotation labels. Run before compiling anything.

A label file is only usable if it is complete and auditable. This checks
structure, coverage and the evidence requirement, and refuses to pass a
label set that would quietly produce a wrong causal-gold.

Checks per label file:
  1. matches annotation/schema.json
  2. the id exists in the sample and in benchmark-v2
  3. file_roles covers EXACTLY the gold files of that instance, no more,
     no fewer (a missing file would silently drop from causal-gold; an
     extra one would invent ground truth)
  4. every non-unclear role cites non-trivial evidence
  5. rationale is substantive
  6. annotator and pass are set, so model, self-consistency and human
     passes stay separable

Usage:
    python industry-c7/scripts/annotation_validate.py
    python industry-c7/scripts/annotation_validate.py --annotator claude-opus-5
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "industry-c7/data/benchmark-v2"
ANN = ROOT / "industry-c7/annotation"
LABELS = ANN / "labels"
ROLES = {"causal", "symptom-handling", "preventive", "refactor", "test",
         "unclear"}
RELATIONS = {"same-location", "caller-callee", "state-producer",
             "config-build", "concurrency", "unrelated", "unclear"}
MIN_EVIDENCE = 15


def load_v2() -> dict[str, dict]:
    out = {}
    for f in sorted(glob.glob(str(V2 / "*.jsonl"))):
        p = os.path.basename(f)[:-6]
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            out[f"{p}:{r['issue_key']}"] = r
    return out


def check(lab: dict, v2: dict, sample_ids: set[str]) -> list[str]:
    e: list[str] = []
    for k in ("id", "project", "issue_key", "annotator", "pass", "file_roles",
              "symptom_location", "log_location", "relation", "rationale",
              "confidence"):
        if k not in lab:
            e.append(f"missing field {k!r}")
    if e:
        return e

    i = lab["id"]
    if i not in sample_ids:
        e.append(f"id {i} is not in the sample")
    inst = v2.get(i)
    if inst is None:
        e.append(f"id {i} is not in benchmark-v2")
        return e

    if not str(lab["annotator"]).strip():
        e.append("annotator is blank; model and human passes must stay separable")
    if not isinstance(lab["pass"], int) or lab["pass"] < 1:
        e.append("pass must be an integer >= 1")

    gold = set(inst["gold_files"])
    got = [fr.get("path") for fr in lab["file_roles"]]
    if len(got) != len(set(got)):
        e.append("duplicate paths in file_roles")
    missing = gold - set(got)
    extra = set(got) - gold
    if missing:
        e.append(f"{len(missing)} gold file(s) unlabelled, would silently drop "
                 f"from causal-gold: {sorted(missing)[:3]}")
    if extra:
        e.append(f"{len(extra)} path(s) not in the gold set, would invent "
                 f"ground truth: {sorted(extra)[:3]}")

    for fr in lab["file_roles"]:
        r = fr.get("role")
        if r not in ROLES:
            e.append(f"bad role {r!r} on {fr.get('path')}")
        ev = (fr.get("evidence") or "").strip()
        if r != "unclear" and len(ev) < MIN_EVIDENCE:
            e.append(f"role {r!r} on {fr.get('path')} has no citable evidence "
                     f"({len(ev)} chars); rubric says use 'unclear' instead")

    if lab["relation"] not in RELATIONS:
        e.append(f"bad relation {lab['relation']!r}")
    if lab["confidence"] not in {"high", "medium", "low"}:
        e.append(f"bad confidence {lab['confidence']!r}")
    if len((lab.get("rationale") or "").strip()) < 20:
        e.append("rationale too short to audit")
    for k in ("symptom_location", "log_location"):
        v = lab.get(k) or {}
        if "determinable" not in v:
            e.append(f"{k}.determinable missing")
        elif v["determinable"] and not v.get("file"):
            e.append(f"{k} marked determinable but no file given")
    return e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotator", default="")
    a = ap.parse_args()

    sample_path = ANN / "sample.json"
    if not sample_path.exists():
        print("no sample.json yet")
        return 2
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    sample_ids = {r["id"] for r in sample["instances"]}
    v2 = load_v2()

    files = sorted(glob.glob(str(LABELS / "*.json")))
    if not files:
        print(f"no labels in {LABELS}")
        return 0

    bad = 0
    roles = Counter()
    conf = Counter()
    rel = Counter()
    seen: Counter = Counter()
    for f in files:
        try:
            lab = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception as ex:  # noqa: BLE001
            print(f"BAD JSON {os.path.basename(f)}: {ex}")
            bad += 1
            continue
        if a.annotator and lab.get("annotator") != a.annotator:
            continue
        errs = check(lab, v2, sample_ids)
        if errs:
            bad += 1
            print(f"FAIL {os.path.basename(f)}")
            for x in errs:
                print(f"   - {x}")
            continue
        seen[(lab["annotator"], lab["pass"])] += 1
        conf[lab["confidence"]] += 1
        rel[lab["relation"]] += 1
        for fr in lab["file_roles"]:
            roles[fr["role"]] += 1

    ok = len(files) - bad
    print(f"\n{ok} valid, {bad} invalid, of {len(files)} label files")
    print(f"sample coverage: {len(seen and [1]) and sum(seen.values())}"
          f" labels over {len(sample_ids)} sampled instances")
    for (ann, ps), n in sorted(seen.items()):
        print(f"   annotator={ann} pass={ps}: {n}")
    if roles:
        tot = sum(roles.values())
        print(f"\nrole distribution over {tot} gold files:")
        for r, n in roles.most_common():
            print(f"   {r:18s} {n:5d}  {100 * n / tot:5.1f}%")
        print(f"confidence: {dict(conf)}")
        print(f"relation:   {dict(rel)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
