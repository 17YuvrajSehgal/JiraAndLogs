# Annotation packet: SERVER-26259  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Add --redactClientLogData to mongos

Add --redactClientLogData to mongos, so that database contents passing through mongos will experience the same log preprocessing they will receive on the underlying mongod.
```

## Fix commit message(s)

`dfb56737ec85`

```
(empty)
```

## Files the fix changed

Snapshot holds 10,291 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/server_options_helpers.cpp`

## The fix diff

### `src/mongo/db/server_options_helpers.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
