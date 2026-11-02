# Annotation packet: SERVER-24739  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Unhandled duration_cast exception in DataFileSync::run can terminate server

It's possible for the server to terminate with an unhandled duration_cast exception if an invalid syncdelay value is specified:

{noformat}
d20000| 2016-06-22T17:25:51.587-0400 E COMMAND  [DataFileSync] backgroundjob DataFileSync exception: Overflow casting from a lower-precision duration to a higher-precision duration
d20000| 2016-06-22T17:25:51.588-0400 F -        [DataFileSync] terminate() called. An exception is active; attempting to gather more information
d20000| 2016-06-22T17:25:51.590-0400 F -        [DataFileSync] DBException::toString(): 159 Overflow casting from a lower-precision duration to a higher-precision duration
d20000| Actual exception type: mongo::UserException
{noformat}

This bug seems to have been introduced after 3.3.6.
```

## Fix commit message(s)

`df8ee2e1ffcf`

```
(empty)
```

## Files the fix changed

Snapshot holds 10,463 non-test source files. The fix changed 5 file(s); 3 of them are non-test source files (listed below as gold).

- `src/mongo/db/mongod_options.cpp`
- `src/mongo/db/storage/storage_options.cpp`
- `src/mongo/db/storage/storage_options.h`

## The fix diff

### `src/mongo/db/mongod_options.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/storage_options.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/storage_options.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
