# Annotation packet: SERVER-60958  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Avoid server hang in chunk migration when step-down event occurs
```

## Fix commit message(s)

`dc5de6843f2e`

```
(empty)
```

## Files the fix changed

Snapshot holds 16,556 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/s/migration_chunk_cloner_source_legacy.cpp`

## The fix diff

### `src/mongo/db/s/migration_chunk_cloner_source_legacy.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
