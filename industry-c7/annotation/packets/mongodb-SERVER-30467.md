# Annotation packet: SERVER-30467  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Extend $_internalSchemaMinLength and $_internalSchemaMaxLength to count lengths of Unicode strings

{{$_internalSchemaMinLength}} and {{$_internalSchemaMaxLength}} must be updated to properly count the lengths of Unicode strings, which may contain multibyte characters.
```

## Fix commit message(s)

`83e1ff54a1ef`

```
(empty)
```

## Files the fix changed

Snapshot holds 10,935 non-test source files. The fix changed 6 file(s); 3 of them are non-test source files (listed below as gold).

- `src/mongo/db/matcher/schema/expression_internal_schema_str_length.h`
- `src/mongo/db/pipeline/expression.cpp`
- `src/mongo/util/mongoutils/str.h`

## The fix diff

### `src/mongo/db/matcher/schema/expression_internal_schema_str_length.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/pipeline/expression.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/util/mongoutils/str.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
