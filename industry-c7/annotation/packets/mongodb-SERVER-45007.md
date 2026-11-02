# Annotation packet: SERVER-45007  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
PBWM acquisition in GlobalLock constructor ignores deadline

[This PBWM lock acquisition|https://github.com/mongodb/mongo/blob/c4a5310c8037c075cde7a0a1a32a7f00bfc19746/src/mongo/db/concurrency/d_concurrency.cpp#L153] ignores the passed in deadline. A consequence is that [this {{GlobalLock}} construction|https://github.com/mongodb/mongo/blob/c4a5310c8037c075cde7a0a1a32a7f00bfc19746/src/mongo/db/curop.cpp#L444-L447] can hang waiting for the PBWM lock.
```

## Fix commit message(s)

`25ffb326e1ec`

```
(empty)
```

`0f502c28c373`

```
(empty)
```

`73acb91e3989`

```
(empty)
```

## Files the fix changed

Snapshot holds 14,754 non-test source files. The fix changed 4 file(s); 3 of them are non-test source files (listed below as gold).

- `src/mongo/db/commands/sleep_command.cpp`
- `src/mongo/db/concurrency/d_concurrency.cpp`
- `src/mongo/db/concurrency/d_concurrency.h`

## The fix diff

### `src/mongo/db/commands/sleep_command.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/concurrency/d_concurrency.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/concurrency/d_concurrency.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
