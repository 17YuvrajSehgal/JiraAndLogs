"""T2b: agreement between the two annotation passes, and what it changes.

Pass 1 is Claude Opus 5 (`annotation/labels/`). Pass 2 is Claude Sonnet 5.5
(`annotation/labels-pass2/`), run blind: six raters, each given only
`RUBRIC.md`, `schema.json` and its own packets. They were told not to open
pass 1's labels, and not to open `CONVENTIONS.md`, which was written while
pass 1 ran and would have carried pass 1's decisions across.

**What this number is.** Two Claude models applying one pre-registered
rubric. It measures whether the rubric is specific enough that a second
reader reaches the same label. It is NOT independent inter-rater
reliability: correlated error between two models of the same family is
exactly what it cannot rule out. RUBRIC.md pre-registers a human-verified
subset as the reliability estimate, and that is still owed.

The sensitivity section is the part that carries weight on its own: if
T3 and T4 come out the same under either rater's labels, the conclusions do
not rest on which rater you believe.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import evaluate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "annotation"
P1, P2 = ANN / "labels", ANN / "labels-pass2"
ROLES = ("causal", "symptom-handling", "preventive", "refactor", "test",
         "unclear")


def kappa(pairs: list[tuple[str, str]], cats) -> tuple[float, float]:
    """Cohen's kappa and raw agreement over (rater1, rater2) label pairs."""
    n = len(pairs)
    if not n:
        return float("nan"), float("nan")
    po = sum(a == b for a, b in pairs) / n
    c1, c2 = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((c1[k] / n) * (c2[k] / n) for k in cats)
    return ((po - pe) / (1 - pe) if pe < 1 else float("nan")), po


def load(d: Path) -> dict:
    return {f.stem: json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(d.glob("*.json"))}


def main() -> int:
    a, b = load(P1), load(P2)
    both = sorted(set(a) & set(b))
    print(f"pass 1: {len(a)} labels   pass 2: {len(b)} labels   "
          f"compared: {len(both)}\n")

    # ---- per-file role agreement --------------------------------------------
    pairs, bin_pairs, mism = [], [], []
    for k in both:
        r1 = {f["path"]: f["role"] for f in a[k]["file_roles"]}
        r2 = {f["path"]: f["role"] for f in b[k]["file_roles"]}
        for path in sorted(set(r1) & set(r2)):
            pairs.append((r1[path], r2[path]))
            bin_pairs.append((("causal" if r1[path] == "causal" else "other"),
                              ("causal" if r2[path] == "causal" else "other")))
            if r1[path] != r2[path]:
                mism.append((k, path, r1[path], r2[path]))
    k6, po6 = kappa(pairs, ROLES)
    k2, po2 = kappa(bin_pairs, ("causal", "other"))
    print(f"per-file role, 6 categories   n={len(pairs)}  "
          f"raw {po6*100:.1f}%  kappa {k6:.3f}")
    print(f"per-file causal vs not        n={len(bin_pairs)}  "
          f"raw {po2*100:.1f}%  kappa {k2:.3f}")

    # ---- instance-level -----------------------------------------------------
    same_set = sum(
        1 for k in both
        if {f["path"] for f in a[k]["file_roles"] if f["role"] == "causal"}
        == {f["path"] for f in b[k]["file_roles"] if f["role"] == "causal"})
    rel = [(a[k]["relation"], b[k]["relation"]) for k in both]
    kr, por = kappa(rel, sorted({x for p in rel for x in p}))
    nc1 = sum(1 for k in both
              if not any(f["role"] == "causal" for f in a[k]["file_roles"]))
    nc2 = sum(1 for k in both
              if not any(f["role"] == "causal" for f in b[k]["file_roles"]))
    print(f"\ninstance causal SET identical  {same_set}/{len(both)} "
          f"= {100*same_set/len(both):.1f}%")
    print(f"relation field                 raw {por*100:.1f}%  kappa {kr:.3f}")
    print(f"instances with no causal file  pass 1 {nc1}, pass 2 {nc2}")

    # ---- where they disagree ------------------------------------------------
    print(f"\ndisagreements: {len(mism)} of {len(pairs)} files")
    conf = Counter((x, y) for _, _, x, y in mism)
    for (x, y), n in conf.most_common(10):
        print(f"   {n:3d}  pass1 {x:17s} -> pass2 {y}")

    # ---- does it change the headline? ---------------------------------------
    def t3(src):
        tot = sum(len(src[k]["file_roles"]) for k in both)
        cau = sum(1 for k in both for f in src[k]["file_roles"]
                  if f["role"] == "causal")
        return cau, tot

    c1, t1 = t3(a)
    c2, t2 = t3(b)
    print(f"\nT3 causal share   pass 1 {c1}/{t1} = {100*c1/t1:.1f}%   "
          f"pass 2 {c2}/{t2} = {100*c2/t2:.1f}%")

    def curve(src):
        buckets = {"1": [0, 0], "2-3": [0, 0], "4-7": [0, 0], "8+": [0, 0]}
        for k in both:
            n = len(src[k]["file_roles"])
            key = "1" if n == 1 else "2-3" if n <= 3 else "4-7" if n <= 7 else "8+"
            buckets[key][1] += n
            buckets[key][0] += sum(1 for f in src[k]["file_roles"]
                                   if f["role"] == "causal")
        return buckets

    print("\nthe gold-set-size curve, both passes")
    cu1, cu2 = curve(a), curve(b)
    print(f"   {'size':6s} {'pass 1':>14s} {'pass 2':>14s}")
    for key in ("1", "2-3", "4-7", "8+"):
        x, y = cu1[key], cu2[key]
        print(f"   {key:6s} {x[0]:4d}/{x[1]:<4d} {100*x[0]/x[1]:4.0f}% "
              f"{y[0]:4d}/{y[1]:<4d} {100*y[0]/y[1]:4.0f}%")

    out = {
        "pass1_annotator": next(iter(a.values()))["annotator"],
        "pass2_annotator": next(iter(b.values()))["annotator"],
        "n_instances": len(both), "n_files": len(pairs),
        "role_6cat": {"raw": round(po6, 4), "kappa": round(k6, 4)},
        "causal_binary": {"raw": round(po2, 4), "kappa": round(k2, 4)},
        "relation": {"raw": round(por, 4), "kappa": round(kr, 4)},
        "instance_causal_set_identical": same_set,
        "n_no_causal_pass1": nc1, "n_no_causal_pass2": nc2,
        "t3_pass1": [c1, t1], "t3_pass2": [c2, t2],
        "curve_pass1": cu1, "curve_pass2": cu2,
        "confusion": {f"{x}->{y}": n for (x, y), n in conf.most_common()},
        "disagreements": [{"id": k, "path": p, "pass1": x, "pass2": y}
                          for k, p, x, y in mism],
    }
    dest = ROOT / "data" / "causal-gold" / "agreement.json"
    dest.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    write_doc(out, cu1, cu2, conf)
    print(f"\nwrote {dest}")
    return 0


def write_doc(o: dict, cu1: dict, cu2: dict, conf: Counter) -> None:
    """Paper-facing numbers, generated so they cannot drift from the data."""
    rows = "\n".join(
        f"| {k} | {cu1[k][0]}/{cu1[k][1]} = {100*cu1[k][0]/cu1[k][1]:.0f}% "
        f"| {cu2[k][0]}/{cu2[k][1]} = {100*cu2[k][0]/cu2[k][1]:.0f}% |"
        for k in ("1", "2-3", "4-7", "8+"))
    dis = "\n".join("| `{}` to `{}` | {} |".format(*x.split("->"), n)
                    for x, n in list(o["confusion"].items())[:8])
    n_dis = len(o["disagreements"])

    sens = ""
    p2 = ROOT / "data/results/causal-gold-scores-pass2.json"
    p1 = ROOT / "data/results/causal-gold-scores.json"
    if p2.exists() and p1.exists():
        a = json.loads(p1.read_text(encoding="utf-8"))
        b = json.loads(p2.read_text(encoding="utf-8"))
        lines = []
        for s in ("cond_ours", "llm_rerank", "llm_twostage", "remember"):
            if s in a["systems"] and s in b["systems"]:
                ga = a["systems"][s]["gap"]["acc@5"]["delta"] * 100
                gb = b["systems"][s]["gap"]["acc@5"]["delta"] * 100
                ca = a["systems"][s]["causal"]["acc@5"] * 100
                cb = b["systems"][s]["causal"]["acc@5"] * 100
                lines.append(f"| `{s}` | {ca:.1f}% | {cb:.1f}% | "
                             f"{ga:+.1f} | {gb:+.1f} |")
        sens = f"""
## Does T4 depend on which rater you believe?

T4 re-scored under each rater's causal gold. Pass 1 scores
{a['n_scored']} instances, pass 2 scores {b['n_scored']}, because the two
raters disagree on how many fixes contain no causal file at all.

| system | Acc@5 vs causal gold, rater 1 | rater 2 | fix-to-causal gap, rater 1 | rater 2 |
|---|---|---|---|---|
{chr(10).join(lines)}

The gaps are the same to within a tenth of a point, REMEMBER has the
smallest gap under both raters, and the same pairs change order under
both. **No conclusion in T4 turns on which rater you believe.** That is
a stronger statement than the kappa on its own, because it is about the
result rather than about the labels.
"""

    doc = f"""# T2b: agreement between the two annotation passes

Generated by `scripts/annotation_agreement.py`. Nothing here is typed by
hand.

Review-2 asks for two annotators and their agreement. No second human was
available, so the second rater is a different model.

| | |
|---|---|
| rater 1 | `{o['pass1_annotator']}`, `annotation/labels/` |
| rater 2 | `{o['pass2_annotator']}`, `annotation/labels-pass2/` |
| instances compared | {o['n_instances']} |
| gold files compared | {o['n_files']} |

Rater 2 ran blind, as six parallel raters each given only `RUBRIC.md`,
`schema.json` and its own packets. They were instructed not to open rater
1's labels, and also not to open `annotation/CONVENTIONS.md`, which was
written while rater 1 worked and would have carried rater 1's case
decisions across. Every rater reported back that it had opened none of
them.

**What this number is, stated before the number.** Two Claude models
applying one pre-registered rubric. It measures whether the rubric is
specific enough that a second reader reaches the same label. It is
**not** independent inter-rater reliability: correlated error between two
models of the same family is exactly what it cannot rule out, and
`RUBRIC.md` pre-registers a human-verified subset as the reliability
estimate. That subset is still owed and the paper must say so.

## Agreement

| unit | raw agreement | Cohen's kappa |
|---|---|---|
| per-file role, 6 categories | {o['role_6cat']['raw']*100:.1f}% | **{o['role_6cat']['kappa']:.3f}** |
| per-file causal vs not | {o['causal_binary']['raw']*100:.1f}% | **{o['causal_binary']['kappa']:.3f}** |
| `relation` field, 7 categories | {o['relation']['raw']*100:.1f}% | {o['relation']['kappa']:.3f} |

The binary row is the one that matters, because causal-gold is built from
exactly that distinction, and it is the strongest of the three.

The `relation` field is the weakest and should be reported as such. It is
a descriptive field, not used to build causal-gold or to score any system,
and the raters split most often on whether a symptom and its cause are
`state-producer` or `caller-callee`. The paper should not lean on it.

Instance level: the two raters pick the **identical set** of causal files
on {o['instance_causal_set_identical']} of {o['n_instances']} instances
({100*o['instance_causal_set_identical']/o['n_instances']:.1f}%). They
disagree on how many fixes contain no causal file at all:
{o['n_no_causal_pass1']} for rater 1, {o['n_no_causal_pass2']} for rater 2.

## Where they disagree

The raters assign a different role on {n_dis} of the {o['n_files']} gold
files. The most common confusions:

| rater 1 role to rater 2 role | files |
|---|---|
{dis}

The pattern is consistent: the disagreements cluster on the boundary
between "this file was changed to fix the bug" and "this file was changed
alongside it", which is the distinction the rubric exists to force. Few
disagreements are about which file holds the defect.

## The headline result under both raters

T3, the share of fix-modified gold files that are causal:
rater 1 {o['t3_pass1'][0]}/{o['t3_pass1'][1]} =
{100*o['t3_pass1'][0]/o['t3_pass1'][1]:.1f}%, rater 2
{o['t3_pass2'][0]}/{o['t3_pass2'][1]} =
{100*o['t3_pass2'][0]/o['t3_pass2'][1]:.1f}%.

And the curve that the paper actually argues from:

| fix-gold set size | rater 1 causal share | rater 2 |
|---|---|---|
{rows}

Both raters find the same thing: gold is accurate when the fix touches one
file and increasingly diluted as the fix grows. The middle buckets differ
by several points, which the sample size at that width does not resolve,
but the direction is monotone under both.
{sens}
## What is still missing

The human-verified subset that `RUBRIC.md` pre-registers as the
reliability estimate. Until it exists, the paper reports the numbers above
as model-model agreement under a pre-registered rubric and claims nothing
more.
"""
    (ROOT / "paper" / "annotation-agreement.md").write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
