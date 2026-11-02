# Annotation packet: SERVER-14268  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Potential information leak

{panel:title=Issue Status as of Aug 08, 2014|borderColor=#ccc|titleBGColor=#6CB33F|bgColor=#EEEEEE}

*ISSUE SUMMARY*
Using a specially crafted message, a remote user could obtain a limited amount of information from the server heap memory.

*USER IMPACT*
Potentially sensitive information could be disclosed from the server.

*WORKAROUNDS*
Implement *[MongoDB Security Best Practices|http://docs.mongodb.org/manual/core/security-network/]* and ensure access to the database server is restricted.

*AFFECTED VERSIONS*
MongoDB production releases up to 2.6.3 are affected by this issue.

*FIX VERSION*
The fix is included in the 2.6.4 production release.

*RESOLUTION DETAILS*
The response sent by the server returns only validated data.

{panel}
```

## Fix commit message(s)

`dac9ac4a4634`

```
(empty)
```

## Files the fix changed

Snapshot holds 7,705 non-test source files. The fix changed 12 file(s); 9 of them are non-test source files (listed below as gold).

- `src/mongo/db/catalog/collection_cursor_cache.cpp`
- `src/mongo/db/catalog/collection_cursor_cache.h`
- `src/mongo/db/dbmessage.cpp`
- `src/mongo/db/dbmessage.h`
- `src/mongo/db/instance.cpp`
- `src/mongo/s/cursors.cpp`
- `src/mongo/s/request.cpp`
- `src/mongo/tools/sniffer.cpp`
- `src/mongo/util/net/message.h`

## The fix diff

### `src/mongo/db/catalog/collection_cursor_cache.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/catalog/collection_cursor_cache.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/dbmessage.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/dbmessage.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/instance.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/s/cursors.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/s/request.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/tools/sniffer.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/util/net/message.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
