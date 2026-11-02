# How RUBRIC.md has been applied (interpretation notes)

**Not a rule change.** RUBRIC.md is frozen and governs. This file records how
its rules were applied across the first 89 labels, so that the remaining
labels are decided the same way. If a case is not covered here, follow
RUBRIC.md and say in `notes` what was decided and why.

**Disclose this file in the paper** alongside the rubric. A reader must know
that the annotator worked from the rubric plus these recorded interpretations.

## Role calls that recur

- **A caller that passes a wrong or missing argument is `causal`**, not the
  callee that received it, when the callee behaves correctly. KAFKA-9743,
  MDEV-21983, MDEV-11780.
- **Adding a check for a legal-but-unhandled input is `causal`** when the
  changed file owns that feature, even though the change looks like a guard.
  The test is whether anything elsewhere was treated as broken: if no other
  file was changed, the unguarded code is the defect. HIVE-2334, KAFKA-6250,
  KEYCLOAK-2362, MDEV-14684.
- **`symptom-handling` is for a change that only detects or reports**, where
  the production code was right and nothing it does was corrected. The clearest
  group is MDEV-12600, where one capacity check is `causal` and a dozen files
  only learn to notice and propagate an allocation failure.
- **Extending a fix to a path the report never exercises is `preventive`**,
  not causal: a sibling operator, a second encoder, another overload.
  DRILL-6710, HBASE-12102, KAFKA-4893, ISPN-8568, MDEV-16980.
- **Call-site adaptation to a changed signature is `refactor`**, including
  moved methods, hoisted fields, removed builders, and declaration-only
  headers. This is the largest refactor group.
- **A header is `causal` only if it holds logic** (an inline body that
  changed behaviour, a new predicate with a body). A header that only declares
  is `refactor`. Compare MDEV-11780 and MDEV-22867 (causal headers) against
  fil0fil.h and buf0dblwr.h (refactor).
- **Duplicated engine or grammar copies take the same role as their
  original**, and both are `causal` when either could have produced the report
  and the packet cannot say which. MDEV-12609, MDEV-13333, HBASE-10330.
  Say so in `notes`.
- **More than one file may be `causal`** when the wrong logic genuinely spans
  them (a non-atomic check-then-act, a missing capability plus its missing
  use). Do not force one. KAFKA-5449, ISPN-8568, MDEV-17849.
- **An instance with no `causal` file is a real outcome** (rubric rule 3).
  It has happened six times so far; do not reach for a causal label to avoid it.

## Symptom and log locations

- Record the **deepest project-owned frame**, not the JDK, libc or generated
  frame above it.
- An **assertion message that names file, line and function places the site**,
  even though the text is emitted by libc. MDEV-14684, MDEV-22734.
- A **logger tag in brackets places the emitting class** even when the message
  text lives in a shared helper. KAFKA-6051.
- **JMX attribute values, SHOW output and test-harness assertions are not
  logs**: `log_location.determinable = false`, and say so in `notes`.
- If the enclosing function is not visible in the hunk, set `function` to null
  and record only the file. Do not guess a name.
- Paths inferred from a package or a build layout are allowed; say in `notes`
  that the packet did not show the tree.

## Things to record in `notes` (these are counted later)

- `REPORT-NAMES-FIX:` when the report names the faulty code, quotes the line,
  or prescribes the adopted fix. Use this exact tag.
- The report names a **culprit commit** rather than a location (bisect result).
- The pasted log belongs to **another project** or to the reporter's own code.
- The gold file **does not appear in the trace at all**, or appears at a
  **different function** than the fix.
- The gold set contains a file whose whole change is **cosmetic** (a semicolon,
  a copyright year, a message rewording, `static`).
- The instance has **no failure** (a typo, log noise, a usability complaint).
- The fix ships with **no regression test**, where the commit or report says so.

## Confidence

- `high`: the diff plainly corrects wrong logic and every gold file's role is
  clear.
- `medium`: at least one role rests on an inference the packet cannot settle
  (which operator, which engine copy, which error path), or the mechanism is
  taken from the commit message rather than shown. Say which in `notes`.
- `low`: used only if the main role would be a guess. Prefer `unclear` on the
  individual file instead.

## Mechanics

- Write labels with Python and `json.dumps`, not a shell heredoc. A heredoc
  mangles backslashes and produced one invalid file.
- Read the packet in full before labelling. Quote exact code in `evidence`.
- Never consult git, the repository, or anything outside the packet. The
  packet is the frozen evidence and blindness depends on it.
