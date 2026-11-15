# Annotation packet: SERVER-23901  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
bypassDocumentValidation no longer accepts numeric types

Perl driver nightly Jenkins runs started failing a few days ago with this error message: {{Wrong type for 'bypassDocumentValidation'. Expected a bool, got a int}}

It looks like the master branch tightened the acceptable types for this option compared to previously released versions of the server.
```

## Fix commit message(s)

`d2ca3517188d`

```
SERVER-23901 make write commands accept any type for bypassDocumentValidation
```

## Files the fix changed

Snapshot holds 10,005 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/ops/write_ops_parsers.cpp`

## The fix diff

### `src/mongo/db/ops/write_ops_parsers.cpp`

```diff
diff --git a/src/mongo/db/ops/write_ops_parsers.cpp b/src/mongo/db/ops/write_ops_parsers.cpp
index 6a7102d4dc1..88b13f4f9fa 100644
--- a/src/mongo/db/ops/write_ops_parsers.cpp
+++ b/src/mongo/db/ops/write_ops_parsers.cpp
@@ -94,12 +94,11 @@ void parseWriteCommand(StringData dbName,
             continue;
         }
 
         const StringData fieldName = field.fieldNameStringData();
         if (fieldName == "bypassDocumentValidation") {
-            checkType(Bool, field);
-            op->bypassDocumentValidation = field.Bool();
+            op->bypassDocumentValidation = field.trueValue();
         } else if (fieldName == "ordered") {
             checkType(Bool, field);
             op->continueOnError = !field.Bool();
         } else if (fieldName == uniqueFieldName) {
             haveUniqueField = true;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
