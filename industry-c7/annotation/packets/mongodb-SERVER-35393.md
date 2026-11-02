# Annotation packet: SERVER-35393  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Go Driver Unit Tests receive error code 9001 when doing a large insert many

When running the {{TestCollection_InsertMany_Batches}} unit test the Go driver returns the following error:
{code:go}
mongo.BulkWriteError{WriteErrors:mongo.WriteErrors{mongo.WriteError{Index:0, Code:9001, Message:"Write results unavailable from localhost:27026 :: caused by :: asio.ssl stream truncated"}}, WriteConcernError:(*mongo.WriteConcernError)(nil)}
{code}

This only occurs when for that test and the remainder of the tests pass. This only occurs on macOS.
```

## Fix commit message(s)

`99ac27f83e67`

```
(empty)
```

`573ebb251784`

```
(empty)
```

## Files the fix changed

Snapshot holds 11,581 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/util/net/ssl/detail/io.hpp`

## The fix diff

### `src/mongo/util/net/ssl/detail/io.hpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
