"""Compile validated labels into the released causal-gold dataset.

Produces, under industry-c7/data/causal-gold/:

  causal-gold.jsonl   one row per annotated instance: the fix-gold set, the
                      causal subset, per-file roles with their evidence, the
                      symptom and log locations, and the relation. This is
                      the artifact other researchers reuse, so it carries its
                      own provenance rather than depending on this repo's
                      layout.
  datasheet.json      counts, role distribution, the T3 headline, agreement
                      between passes, and the caveats that must travel with
                      the data.
  DATASHEET.md        the same, readable, including what this dataset is NOT.

T3 headline: the share of fix-modified gold files that are actually causal.
T4 then re-scores every system against the causal subset.

Usage:
    python industry-c7/scripts/annotation_compile.py
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "industry-c7/data/benchmark"
ANN = ROOT / "industry-c7/annotation"
LABELS = ANN / "labels"
OUT = ROOT / "industry-c7/data/causal-gold"
MODEL_ANNOTATOR = "claude-opus-5"


def load_v2() -> dict[str, dict]:
    out = {}
    for f in sorted(glob.glob(str(V2 / "*.jsonl"))):
        p = os.path.basename(f)[:-6]
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            out[f"{p}:{r['issue_key']}"] = r
    return out


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Agreement corrected for chance. Returns nan if undefined."""
    if not a or len(a) != len(b):
        return float("nan")
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(a) | set(b))
    return float("nan") if pe == 1 else (po - pe) / (1 - pe)


def main() -> int:
    # T2b compiles a second causal-gold from the blind pass-2 labels, so T4
    # can be re-scored under the other rater and we can say whether the
    # conclusions depend on which rater you believe.
    labels_dir = LABELS
    out_dir = OUT
    if "--pass2" in sys.argv:
        labels_dir = ANN / "labels-pass2"
        out_dir = OUT.parent / "causal-gold-pass2"
        out_dir.mkdir(parents=True, exist_ok=True)
    globals()["OUT"] = out_dir

    v2 = load_v2()
    by_pass: dict[tuple, dict] = defaultdict(dict)
    for f in sorted(glob.glob(str(labels_dir / "*.json"))):
        lab = json.loads(Path(f).read_text(encoding="utf-8"))
        by_pass[(lab["annotator"], lab["pass"])][lab["id"]] = lab

    annot, passno = ((MODEL_ANNOTATOR, 1) if labels_dir == LABELS
                     else ("claude-sonnet-5-5", 2))
    primary = by_pass.get((annot, passno), {})
    if not primary:
        print(f"no primary labels (annotator={annot}, pass={passno})")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    roles = Counter()
    rel = Counter()
    conf = Counter()
    n_gold = n_causal = 0
    no_causal = 0

    for i, lab in sorted(primary.items()):
        inst = v2[i]
        causal = [fr["path"] for fr in lab["file_roles"]
                  if fr["role"] == "causal"]
        for fr in lab["file_roles"]:
            roles[fr["role"]] += 1
        rel[lab["relation"]] += 1
        conf[lab["confidence"]] += 1
        n_gold += len(inst["gold_files"])
        n_causal += len(causal)
        if not causal:
            no_causal += 1
        rows.append({
            "id": i,
            "project": lab["project"],
            "issue_key": lab["issue_key"],
            "fix_gold": sorted(inst["gold_files"]),
            "causal_gold": sorted(causal),
            "file_roles": lab["file_roles"],
            "symptom_location": lab["symptom_location"],
            "log_location": lab["log_location"],
            "relation": lab["relation"],
            "rationale": lab["rationale"],
            "confidence": lab["confidence"],
            "annotator": lab["annotator"],
            "snapshot_sha": inst["snapshot_sha"],
            "fix_sha": inst["fix_sha"],
            "n_universe": inst.get("n_universe", 0),
            "gold_named_in_text": inst["gold_named_in_text"],
        })

    (OUT / "causal-gold.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")

    # --- agreement between passes -----------------------------------------
    agreement = {}
    for (ann, ps), labs in sorted(by_pass.items()):
        # skip the pass we are compiling FROM: comparing it with itself
        # produced a bogus kappa of 1.0 in the pass-2 datasheet
        if (ann, ps) == (annot, passno):
            continue
        shared = sorted(set(labs) & set(primary))
        if not shared:
            continue
        a, b = [], []
        for i in shared:
            pa = {fr["path"]: fr["role"] for fr in primary[i]["file_roles"]}
            pb = {fr["path"]: fr["role"] for fr in labs[i]["file_roles"]}
            for p in sorted(set(pa) & set(pb)):
                a.append(pa[p])
                b.append(pb[p])
        kind = ("self-consistency (same model, NOT inter-rater reliability)"
                if ann == MODEL_ANNOTATOR
                else "verification agreement, review-style (annotator saw the "
                     "model labels first, so this is biased upward and is NOT "
                     "independent inter-rater reliability)")
        agreement[f"{ann}/pass{ps}"] = {
            "instances": len(shared), "files_compared": len(a),
            "raw_agreement": round(sum(1 for x, y in zip(a, b) if x == y)
                                   / len(a), 3) if a else None,
            "cohen_kappa": round(cohen_kappa(a, b), 3) if a else None,
            "interpretation": kind,
        }

    causal_share = round(n_causal / n_gold, 3) if n_gold else 0.0
    ds = {
        "name": "C7 causal-gold",
        "built": str(date.today()),
        "instances": len(rows),
        "projects": len(Counter(r["project"] for r in rows)),
        "fix_gold_files": n_gold,
        "causal_gold_files": n_causal,
        "T3_causal_share_of_fix_gold": causal_share,
        "instances_with_no_causal_file": no_causal,
        "role_distribution": dict(roles.most_common()),
        "relation_distribution": dict(rel.most_common()),
        "confidence_distribution": dict(conf),
        "annotation": {
            "primary_annotator": annot,
            "method": "model-assisted, pre-registered rubric "
                      "(annotation/RUBRIC.md), blind to all system output",
            "human_annotation": False,
            "agreement": agreement,
        },
        "caveats": [
            "Labels are model-assisted, not human annotation.",
            "The system under test is also a language model, so causal-gold "
            "may be biased toward what such systems find. The annotator is a "
            "different model family (Claude vs the Qwen under test).",
            "Verification was review-style: the human saw the model labels "
            "before judging, which biases agreement upward.",
            "A second model pass measures self-consistency, not inter-rater "
            "reliability.",
        ],
    }
    (OUT / "datasheet.json").write_text(json.dumps(ds, indent=1),
                                        encoding="utf-8")

    rl = "\n".join(f"| {r} | {n} | {100 * n / sum(roles.values()):.1f}% |"
                   for r, n in roles.most_common())
    ag = "\n".join(
        f"- **{k}**: {v['raw_agreement']} raw, kappa {v['cohen_kappa']}, "
        f"over {v['files_compared']} files. {v['interpretation']}"
        for k, v in agreement.items()) or "- none yet"
    (OUT / "DATASHEET.md").write_text(f"""# C7 causal-gold

Built {date.today()} by `scripts/annotation_compile.py` from labels under
`annotation/labels/`, against the rubric frozen in `annotation/RUBRIC.md`.

{len(rows)} instances across {len(Counter(r['project'] for r in rows))} projects.

## The headline (T3)

Of {n_gold} files modified by the fix commits, **{n_causal} ({100 * causal_share:.1f}%)
contain the defect**. {no_causal} instances have no causal file at all: the fix
was entirely defensive or incidental.

This is the number the reviewer's objection asks for. Fix-modified files are
not the same thing as causal files, and this quantifies the gap.

## Role distribution

| role | files | share |
|---|---|---|
{rl}

## Agreement

{ag}

## What this dataset is NOT

- **Not human annotation.** Labels come from a language model following a
  pre-registered rubric. The paper must say so.
- **Not independent inter-rater reliability.** Verification was review-style,
  so the human saw the model's label first. That biases agreement upward.
- **Not free of circularity.** The system under test is a language model too.
  A different model family was used for annotation, and the human-verified
  subset is the control, but the risk is real and is reported rather than
  argued away.

## Fields

`fix_gold` is the benchmark's original ground truth. `causal_gold` is the
subset labelled `causal`. Every file carries its role and the evidence cited
for it, so any label can be audited without redoing the analysis.
""", encoding="utf-8")

    print(f"wrote {OUT}")
    print(f"  {len(rows)} instances, {n_gold} gold files")
    print(f"  T3: {n_causal}/{n_gold} = {100 * causal_share:.1f}% of fix-gold "
          f"is causal")
    print(f"  {no_causal} instances with no causal file")
    for k, v in agreement.items():
        print(f"  {k}: kappa {v['cohen_kappa']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
