# Annotation packet: QTBUG-96285  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
QProcess can't be restarted

If the example application is built with MSVC2019 64bit, the QProcess can't be restarted.

To reproduce
1) build the example in release with MSVC2019.
2) run the project
3) Go to task manager and kill the cmd.exe process
    -> the process is restarted
4) Repeat kill 2-3 more times - the application crashes:

{code:java}
ProcessTest::processFinished  30
ProcessTest::processFinished  29
21:31:46: The program has unexpectedly finished.
{code}

In debug it hardly crashes.
Not reproducible with MinGW.
```

## Fix commit message(s)

`4e0082a9cacf`

```
(empty)
```

## Files the fix changed

Snapshot holds 5,886 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/kernel/qwineventnotifier.cpp`

## The fix diff

### `src/corelib/kernel/qwineventnotifier.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
