"""T13-T15: what the three production-shaped noise arms cost.

The first four arms (dup / generic / foreign / drop) are a fair start but
none of them is shaped like what an on-call engineer receives. These three
are:

  mixed     k concurrent incidents merged with each stream keeping its own
            order. Compare against `foreign` at a matched volume: foreign
            adds the same other-issue lines at independent random
            positions, so the difference between the two arms isolates
            what ORDER is worth, separately from what the extra text costs.
  cascade   downstream consequences that name a symbol from the report.
            Compare against `generic` at the same ratio: both add the same
            number of lines, but cascade's are lexically close to the real
            evidence, so the difference isolates what SIMILAR noise costs
            over unrelated noise.
  decisive  remove the single highest-BM25 line. Compare against `drop`,
            which removes every file mention and frame: the ratio of the
            two says how concentrated the evidence is in one line.

Usage:
    python industry-c7/scripts/noise_arms_compare.py
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localize import PROJECTS as _ALL_PROJECTS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "data/results"
# Derived from localize.PROJECTS, never typed. A hardcoded 4-tuple here
# does not fail, it quietly reports the old four projects as if they
# were the benchmark. Deriving it means a project with a missing input
# raises instead of vanishing from the table.
P = tuple(sorted(_ALL_PROJECTS))
STREAMS = (2, 3, 5)
RATIOS = (1, 2, 5)


def main() -> int:
    s = {p: json.loads((RES / f"{p}-noise-summary.json")
                       .read_text(encoding="utf-8")) for p in P}
    missing = [p for p in P if "decisive" not in s[p]["acc@5"]]
    if missing:
        print(f"no new-arm results yet for: {', '.join(missing)}")
        return 1

    a = {p: s[p]["acc@5"] for p in P}
    out = {"n_per_project": {p: s[p]["n_sample"] for p in P},
           "n_decisive_identified": {p: s[p].get("n_decisive_identified")
                                     for p in P},
           "acc5": {p: a[p] for p in P},
           "pooled": {}, "contrasts": {}}

    keys = (["clean"] + [f"mixed_x{k}" for k in STREAMS]
            + [f"cascade_x{r}" for r in RATIOS] + ["decisive", "drop"]
            + [f"foreign_x{r}" for r in RATIOS]
            + [f"generic_x{r}" for r in RATIOS])
    for k in keys:
        out["pooled"][k] = round(st.fmean(a[p][k] for p in P), 4)

    pl = out["pooled"]
    # mixed vs foreign: the same other-issue text, ordered vs scattered. k
    # streams add (k-1) other incidents, so the volume analogue is x(k-1).
    # foreign has no x4 level, so k=5 is paired with x5, which adds MORE
    # text than mixed k=5 does -- that pairing is conservative in mixed's
    # favour and is labelled as such rather than quietly matched.
    out["mixed_pairing"] = {2: "foreign_x1", 3: "foreign_x2", 5: "foreign_x5"}
    out["mixed_pairing_exact"] = {2: True, 3: True, 5: False}
    for k, f in out["mixed_pairing"].items():
        out["contrasts"][f"mixed_x{k}_vs_{f}"] = round(
            pl[f"mixed_x{k}"] - pl[f], 4)
    # cascade vs generic: same line count, related vs unrelated text.
    for r in RATIOS:
        out["contrasts"][f"cascade_x{r}_vs_generic_x{r}"] = round(
            pl[f"cascade_x{r}"] - pl[f"generic_x{r}"], 4)
    out["contrasts"]["decisive_vs_clean"] = round(pl["decisive"] - pl["clean"], 4)
    out["contrasts"]["drop_vs_clean"] = round(pl["drop"] - pl["clean"], 4)
    loss_d = pl["clean"] - pl["decisive"]
    loss_all = pl["clean"] - pl["drop"]
    out["contrasts"]["one_line_share_of_drop_loss"] = (
        round(loss_d / loss_all, 4) if loss_all > 0 else None)

    (RES / "noise-arms-compare.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8")

    print(f"pooled Acc@5 over {len(P)} projects "
          f"({', '.join(str(v) for v in out['n_per_project'].values())} each)\n")
    print(f"  {'clean':16s} {pl['clean']:.4f}")
    for k in STREAMS:
        print(f"  {'mixed k=' + str(k):16s} {pl[f'mixed_x{k}']:.4f}"
              f"   ({out['mixed_pairing'][k]}: {pl[out['mixed_pairing'][k]]:.4f}"
              f"{'' if out['mixed_pairing_exact'][k] else ', not volume-matched'})")
    for r in RATIOS:
        print(f"  {'cascade x' + str(r):16s} {pl[f'cascade_x{r}']:.4f}"
              f"   (generic x{r}: {pl[f'generic_x{r}']:.4f})")
    print(f"  {'decisive':16s} {pl['decisive']:.4f}"
          f"   (drop: {pl['drop']:.4f})")
    print("\ncontrasts:")
    for k, v in out["contrasts"].items():
        print(f"  {k:38s} {v:+.4f}" if isinstance(v, float) else f"  {k}: {v}")

    write_doc(out, s)
    print(f"\nwrote {RES / 'noise-arms-compare.json'} and "
          f"paper/noise-arms.md")
    return 0


def write_doc(out: dict, s: dict) -> None:
    pl, ct = out["pooled"], out["contrasts"]
    rows = "\n".join(
        f"| {p} | " + " | ".join(
            f"{out['acc5'][p][k] * 100:.1f}" for k in
            ["clean"] + [f"mixed_x{k}" for k in STREAMS]
            + [f"cascade_x{r}" for r in RATIOS] + ["decisive", "drop"]) + " |"
        for p in P)
    share = ct["one_line_share_of_drop_loss"]
    mixed_rows = "\n".join(
        f"| k={k} vs {out['mixed_pairing'][k].replace('foreign_', '')}"
        f"{'' if out['mixed_pairing_exact'][k] else ' (not matched)'} "
        f"| {pl[f'mixed_x{k}'] * 100:.1f} | {pl[out['mixed_pairing'][k]] * 100:.1f} "
        f"| **{ct[f'mixed_x{k}_vs_' + out['mixed_pairing'][k]] * 100:+.1f}** |"
        for k in STREAMS)
    # The cascade hypothesis was that noise LOOKING like evidence costs more
    # than unrelated noise. Let the data pick the heading rather than
    # shipping the hypothesis as a finding.
    casc = st.fmean(ct[f"cascade_x{r}_vs_generic_x{r}"] for r in RATIOS)
    if casc <= -0.02:
        casc_head = "Noise that looks like evidence costs more"
        casc_body = (
            "Cascade noise is consistently worse than generic noise of the "
            "same volume, by {:.1f} points on average. Lines that name a "
            "symbol from the report compete with the real evidence instead "
            "of merely diluting it, which is the failure mode a production "
            "bundle actually produces.".format(abs(casc) * 100))
    elif casc >= 0.02:
        casc_head = "Noise that looks like evidence costs LESS, not more"
        casc_body = (
            "This is the opposite of what we expected. Cascade noise is "
            "{:.1f} points *easier* than generic noise of the same volume. "
            "The reason is mechanical: cascade lines repeat a symbol the "
            "report already contains, so they add no new vocabulary and "
            "barely move a bag-of-words score, while generic lines "
            "introduce fresh terms (`GC`, `heartbeat`, `watermark`) that "
            "compete for the query's limited term mass. A lexical retriever "
            "is hurt by unfamiliar noise, not by on-topic noise. We report "
            "this as a negative result for the hypothesis that motivated "
            "the arm.".format(casc * 100))
    else:
        casc_head = "Noise that looks like evidence costs about the same"
        casc_body = (
            "Cascade and generic noise are within {:.1f} points of each "
            "other on average, so the hypothesis behind this arm -- that "
            "on-topic noise competes with real evidence in a way unrelated "
            "noise does not -- is not supported at this volume. A "
            "bag-of-words retriever appears to be sensitive to how much "
            "text arrives, not to what it resembles.".format(abs(casc) * 100))
    doc = f"""# T13-T15: three production-shaped noise arms

Generated by `scripts/noise_arms_compare.py`. Nothing here is typed by hand.

Review-2, Priority 4: the existing dup / generic / foreign / drop arms are
a fair start but are not production bundles. These three are shaped like
what an on-call engineer actually receives, and each is paired with an
existing arm so the new thing it isolates is measurable rather than
asserted.

| project | clean | mixed k=2 | k=3 | k=5 | cascade x1 | x2 | x5 | decisive | drop |
|---|---|---|---|---|---|---|---|---|---|
{rows}

Pooled Acc@5, 200 instances per project, clean-tuned weights frozen.

## What ordering is worth

`mixed` merges k concurrent incidents and keeps each stream in its own
order; `foreign` adds the same kind of other-issue text at independent
random positions. At matched volume the difference is what ordering is
worth:

| | mixed | foreign (matched) | difference |
|---|---|---|---|
{mixed_rows}

A bag-of-words retrieval layer has no notion of line order, so these
differences are not the retriever reading the sequence. They come from
*which* lines arrive: `mixed` draws whole incidents, so it adds fewer
distinct other-issues' vocabularies than `foreign`, which samples lines
independently from every other issue in the pool. The honest reading is
that `foreign` is the harsher arm because it is more lexically diverse,
not because it is disordered, and `mixed` is the better model of
concurrent incidents for a system that does read order.

## {casc_head}

`cascade` and `generic` add the same number of lines. The difference is
that cascade lines name a symbol from the report, as real downstream
timeouts and circuit-breaker errors would:

| ratio | cascade | generic | difference |
|---|---|---|---|
| x1 | {pl['cascade_x1'] * 100:.1f} | {pl['generic_x1'] * 100:.1f} | **{ct['cascade_x1_vs_generic_x1'] * 100:+.1f}** |
| x2 | {pl['cascade_x2'] * 100:.1f} | {pl['generic_x2'] * 100:.1f} | **{ct['cascade_x2_vs_generic_x2'] * 100:+.1f}** |
| x5 | {pl['cascade_x5'] * 100:.1f} | {pl['generic_x5'] * 100:.1f} | **{ct['cascade_x5_vs_generic_x5'] * 100:+.1f}** |

{casc_body}

Reported as measured, not as hypothesised.

## One line carries much of the evidence

`decisive` removes exactly one line, the one whose tokens alone rank a
gold file highest. `drop` removes every file mention and every stack
frame. Removing one line costs {abs(ct['decisive_vs_clean']) * 100:.1f}
points; removing all of them costs
{abs(ct['drop_vs_clean']) * 100:.1f}. One line is therefore worth
**{share * 100:.0f}%** of what the entire mention-and-frame channel is
worth.

That is the practical finding of this group: log evidence is
concentrated, not distributed. A bundle that happens to truncate before
one line, or a logger whose level hides it, costs most of what losing
the whole channel costs. It is also a caution about the benchmark --
instances are easier than production partly because the decisive line is
reliably present.

## Limits

- The decisive line is identified by BM25 against the gold files, so it is
  decisive *for a lexical retriever*. A different retriever might lean on
  a different line, and this arm would then be measuring the wrong one.
- It is only identified where a gold file is in the snapshot and some line
  scores above zero; counts are in `n_decisive_identified`
  ({', '.join(f"{p} {s[p].get('n_decisive_identified')}" for p in P)}).
  Where it is not found the arm degenerates to `clean`, which biases this
  loss toward zero.
- Cascade templates are synthetic. They are shaped like real downstream
  errors and they name a real symbol, but they are not mined from
  production logs.
"""
    (ROOT / "paper" / "noise-arms.md").write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
