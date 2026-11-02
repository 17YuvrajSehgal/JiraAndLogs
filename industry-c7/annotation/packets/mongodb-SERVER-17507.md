# Annotation packet: SERVER-17507  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
MongoDB3 enterprise AuditLog

 The AuditLog is not logging authentication failures in 3.0 enterprise and only logging the successes. This was working fine in version 2.6 enterprise.
```

## Fix commit message(s)

`cb126b88afd7`

```
(empty)
```

## Files the fix changed

Snapshot holds 6,730 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/auth/native_sasl_authentication_session.cpp`

## The fix diff

### `src/mongo/db/auth/native_sasl_authentication_session.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
