# Annotation packet: SERVER-12128  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Inconsistent Earth radius used in tests / documentation

MongoDB tests and documentation utilize mean Earth radius (6371km) rather than equatorial radius (6378.1km). Because Earth is not a perfect sphere, mean radius may be a more appropriate constant.

The constant within MongoDB source code is 6378.1 km (equatorial).
```

## Fix commit message(s)

`565f050f4148`

```
(empty)
```

## Files the fix changed

Snapshot holds 6,732 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/geo/geoconstants.h`

## The fix diff

### `src/mongo/db/geo/geoconstants.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
