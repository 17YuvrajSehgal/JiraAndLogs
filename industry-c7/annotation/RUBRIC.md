# Causal role annotation rubric (pre-registered)

**Frozen 2026-11-02, before any instance was seen.** Do not edit after
annotation begins. If a case genuinely cannot be decided under these rules,
label it `unclear` and say why; do not widen the rules mid-pass.

## Why this exists

The benchmark's ground truth is "files the fix commit modified". The reviewer's
central objection is that this conflates four different things:

> A file may contain the underlying defect. A file may detect or report the
> failure. A file may be modified to prevent the failure from recurring. A file
> may be modified as part of a broader refactoring or cleanup.

This annotation measures how often those coincide, and produces a second,
narrower ground truth (`causal-gold`) that every system is re-scored against.

## Who annotates, and what that costs

Annotation is performed by a large language model (Claude Opus 5) following
this rubric, blind to every system's output. **This is model-assisted
annotation, not human annotation, and the paper must say so.**

Three specific threats follow, each with a stated control:

1. **Correlated errors.** Two passes by the same model are not two independent
   raters. A second pass is reported as *self-consistency*, never as
   inter-rater reliability.
2. **Circularity.** The system under test (REMEMBER) is also a language model.
   If the annotator labels causality the way a language model would, causal-gold
   could be biased toward what such systems find. Controls: the annotator is a
   different model family from the system under test (Claude vs Qwen), and a
   human-verified subset is the headline reliability number.
3. **Unverifiable labels.** Every label must cite the specific diff hunk, log
   line or report sentence that supports it, so a human can audit a label in
   seconds instead of redoing the analysis.

**The human-verified subset is what makes this defensible.** An author
independently labels a random subset without seeing the model's labels;
agreement on that subset is reported as the reliability estimate. If agreement
is poor, that is the finding and the causal claim is withdrawn.

## What the annotator sees

Only this, rendered into a frozen evidence packet:

- the issue summary and description, including pasted logs and stack traces
- the fix commit message(s)
- the fix diff, per gold file
- the file list with change status, and the snapshot size

**Never shown:** any system's ranking, score or evidence; whether an instance
is in the easy or hard stratum; whether REMEMBER got it right. Blindness is
enforced by the renderer, not by intention.

## Per-file role labels

Assign exactly one role to **each gold file**.

### `causal`
The file contains the defect that produced the reported failure. The change
here alters logic that was wrong. Had this code been correct originally, the
reported failure would not have occurred.

### `symptom-handling`
The file is where the failure surfaced, was detected, or was reported. The
change adds or improves error handling, a guard, a log message or a diagnostic
at the detection site, while the bad state originated elsewhere.

Hard case, decide it this way: if the report is "X crashes on a null value"
and the fix adds a null check in X, then X is `causal` **only if X owns the
invariant** that was violated. If the null came from another file and that
file was also changed, the other file is `causal` and X is `symptom-handling`.

### `preventive`
The change stops the failure from recurring or spreading, without being where
the defect lived: a downstream validation, a retry, a timeout, a defensive
fallback, a configuration tightening.

### `refactor`
Incidental to the fix: rename, move, formatting, imports, comments, generated
code, or an API adaptation forced by the real fix elsewhere.

### `test`
A test file. These should already be filtered out; label and flag any that leak
through, because that is a benchmark defect worth knowing about.

### `unclear`
The evidence does not support a decision. Use this rather than guessing. State
what additional evidence would have settled it.

## Per-instance fields

- **`symptom_location`** — file, and function if determinable, where the failure
  surfaced. May be outside the gold set, and often is; that is the point.
- **`log_location`** — where the reported log line or stack-trace frame was
  emitted. May be outside the gold set.
- **`relation`** — how the symptom site relates to the causal site:
  `same-location` · `caller-callee` · `state-producer` (bad state created
  earlier, consumed at the symptom) · `config-build` · `concurrency`
  (ordering or locking spanning sites) · `unrelated` · `unclear`
- **`rationale`** — two or three sentences citing concrete evidence.
- **`confidence`** — `high` · `medium` · `low`.

## Decision rules

1. **Narrowest attribution the diff supports.** Do not label a file `causal`
   because it is plausibly involved. Label it `causal` because the diff shows
   the wrong logic being corrected there.
2. **More than one file may be `causal`.** Do not force a single answer.
3. **A fix with no `causal` file is a real outcome**, not a failed annotation.
   It means the fix was entirely defensive or incidental, which is exactly the
   gap the reviewer is pointing at.
4. **The commit message is evidence, not truth.** "Fix NPE in X" tells you where
   the author thought the problem was; the diff tells you what changed.
5. **Ignore how hard the instance looks.** Difficulty is not a label.
6. **Low confidence is informative.** Report it; do not inflate to `high` for a
   tidier table.

## Outputs

`annotation/labels/<project>-<key>.json`, one per instance, matching
`annotation/schema.json`. From these:

- **T3** — the share of fix-modified gold files that are `causal`.
- **T4** — `causal-gold` = the `causal` subset; every system re-scored on it,
  reported beside fix-gold.

## Reporting requirements

The paper must state, without softening:

- annotation was model-assisted, naming the model;
- the size of the human-verified subset and the agreement on it;
- that the second model pass is self-consistency, not inter-rater reliability;
- the `unclear` rate;
- that a low human-agreement figure invalidates the causal claim, and what the
  measured figure was.
