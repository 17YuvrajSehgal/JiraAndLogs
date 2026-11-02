# Annotation packet: SERVER-15763  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Ensure readable state while draining and becoming primary

Check to make sure that isMaster returns something readable, {{ismaster:true, secondary:false }}, when transitioning to primary, during draining stage esp.
```

## Fix commit message(s)

`ede05b3fc832`

```
(empty)
```

## Files the fix changed

Snapshot holds 8,767 non-test source files. The fix changed 3 file(s); 2 of them are non-test source files (listed below as gold).

- `src/mongo/db/repl/repl_coordinator_impl.cpp`
- `src/mongo/db/repl/repl_coordinator_test_fixture.cpp`

## The fix diff

### `src/mongo/db/repl/repl_coordinator_impl.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/repl/repl_coordinator_test_fixture.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
