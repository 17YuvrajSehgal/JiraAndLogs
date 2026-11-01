---
name: log-guided-fault-localization
version: 1
authored_by: human
---

## Problem signature

A production issue report with logs, and a source snapshot as it was
when the issue was filed. No failing test, no reproduction. The logs
show where the failure was DETECTED. The fault usually lives somewhere
else.

## Investigation blueprint

Work in this order. Do not skip to an answer from path names alone:
that is how a weaker method loses, because the file whose name matches
the error is usually the victim, not the cause.

1. **Pull the symbols out of the report.** Stack frames, exception
   types, error strings, config keys, identifiers. A frame names a
   symbol, not a file.

2. **Resolve the symbols to code.** `search_symbol` on the most
   specific names. This tells you the file that raises or declares the
   thing the log mentions. Treat that file as the *detection site*.

3. **Search for the behaviour, not the symptom.** `search_text` with
   words describing what went wrong (what was null, what was closed,
   what was assigned twice). This often lands on the cause directly,
   because the code that creates the bad state usually contains the
   vocabulary of the bug.

4. **Walk from detection to cause.** Read the detection site with
   `read_code`. Ask: where does this bad value come from? Who sets this
   field, closes this handle, assigns this partition? Use `callers_of`
   on the failing symbol to step one hop back towards the code that
   created the bad state, then read that code. One or two hops is
   usually enough; do not wander further.

5. **Ask the project's history.** `recall_incidents` with a short
   description. If a past incident that reads like this one was fixed
   in some file, that file is a strong candidate. The history only
   contains incidents resolved before this report existed.

6. **Record as you go.** Call `note_candidate` for every file you
   seriously consider, with the evidence and your confidence, including
   files you rule out and why. A file you considered but never recorded
   cannot be ranked.

## Resolution template

Rank by evidence quality, strongest first:

- code that CREATES the bad state (assigns, closes, frees, mutates) is
  a stronger candidate than code that merely observes it
- a file a similar past incident was fixed in is strong, especially
  when the report names no file at all
- a file whose content matches the behaviour description beats a file
  whose path matches a word in the title
- the file named in the stack trace is a weak candidate on its own:
  include it, but rarely first, unless you read it and the fault is
  visibly there

Submit up to 10 files, most likely first. Prefer a diverse list over
ten variations of one guess: if two candidates come from different
evidence (one from a trace, one from history), include both.
