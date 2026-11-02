# Annotation packet: SERVER-26389  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Make javascript periodic interrupts disabled by default
```

## Fix commit message(s)

`cb9e5e2f0a8e`

```
(empty)
```

## Files the fix changed

Snapshot holds 10,289 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `src/mongo/scripting/deadline_monitor.cpp`
- `src/mongo/scripting/deadline_monitor.h`

## The fix diff

### `src/mongo/scripting/deadline_monitor.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/scripting/deadline_monitor.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
