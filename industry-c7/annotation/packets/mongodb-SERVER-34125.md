# Annotation packet: SERVER-34125  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Only RTT WT storage engines may call `getLastStableCheckpoint`.

In particular, {{inMemory}} does not take checkpoints.
```

## Fix commit message(s)

`57909b80fd32`

```
(empty)
```

## Files the fix changed

Snapshot holds 11,319 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `src/mongo/db/storage/wiredtiger/wiredtiger_record_store.cpp`
- `src/mongo/db/storage/wiredtiger/wiredtiger_record_store.h`

## The fix diff

### `src/mongo/db/storage/wiredtiger/wiredtiger_record_store.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_record_store.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
