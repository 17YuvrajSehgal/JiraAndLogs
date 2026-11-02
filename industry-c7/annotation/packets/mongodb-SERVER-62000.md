# Annotation packet: SERVER-62000  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Do not generate "unique" field in oplog if collMod "unique" parameter is a no-op

If we use the collMod "unique" parameter, which currently has to be set to {{true}}, on a index that is already unique, the primary still generates the following oplog entry that will cause oplog application on a secondary to fail:
{noformat}
{collMod: 'mycoll', index: {name: 'myidx', unique: false}}
{noformat}

For a no-op "unique" collMod request, we should apply a strategy similar to that implemented in SERVER-48047.

This is follow-up work to SERVER-61980 where we addressed a gap in the no-op "hidden" parameter when "unique" is also provided.

This applies to a flag-guarded feature that is still under development.
```

## Fix commit message(s)

`5e5230ee102f`

```
(empty)
```

`a4387740aa41`

```
(empty)
```

`88390273fec7`

```
(empty)
```

## Files the fix changed

Snapshot holds 16,633 non-test source files. The fix changed 4 file(s); 2 of them are non-test source files (listed below as gold).

- `src/mongo/db/catalog/coll_mod.cpp`
- `src/mongo/db/catalog/coll_mod_index.cpp`

## The fix diff

### `src/mongo/db/catalog/coll_mod.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/catalog/coll_mod_index.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
