# Annotation packet: MDEV-13712  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Spelling errors in the error message

{noformat}
MariaDB [test]> insert into v values (1,1,2,2,-1,1000,0,0);
ERROR 1030 (HY000): Got error 169 "Record was not update. Original values was same as new values" from storage engine InnoDB
{noformat}

update => updated
was the same => were the same

_... and maybe somebody can make it better in general_
```

## Fix commit message(s)

`6670b4e58ca1`

```
MDEV-13712 Spelling errors in the error message
```

## Files the fix changed

Snapshot holds 3,525 non-test source files. The fix changed 8 file(s); 1 of them are non-test source files (listed below as gold).

- `include/my_handler_errors.h`

## The fix diff

### `include/my_handler_errors.h`

```diff
diff --git a/include/my_handler_errors.h b/include/my_handler_errors.h
index bdea4f71eaf..082e6effdab 100644
--- a/include/my_handler_errors.h
+++ b/include/my_handler_errors.h
@@ -22,34 +22,34 @@
 */
 
 static const char *handler_error_messages[]=
 {
   /* 120 */
-  "Didn't find key on read or update",
+  "Didn't find the key on read or update",
   "Duplicate key on write or update",
   "Internal (unspecified) error in handler",
-  "Someone has changed the row since it was read (while the table was locked to prevent it)",
-  "Wrong index given to function",
+  "Someone has changed the row since it was read (even though the table was locked to prevent it)",
+  "Wrong index given to a function",
   "Undefined handler error 125",
   "Index is corrupted",
   "Table file is corrupted",
   "Out of memory in engine",
   "Undefined handler error 129",
   /* 130 */
   "Incorrect file format",
-  "Command not supported by database",
+  "Command not supported by the engine",
   "Old database file",
   "No record read before update",
   "Record was already deleted (or record file crashed)",
   "No more room in record file",
   "No more room in index file",
   "No more records (read after end of file)",
   "Unsupported extension used for table",
   "Too big row",
   /* 140 */
   "Wrong create options",
-  "Duplicate unique key or constraint on write or update",
+  "Duplicate unique key on write or update",
   "Unknown character set used in table",
   "Conflicting table definitions in sub-tables of MERGE table",
   "Table is crashed and last repair failed",
   "Table was marked as crashed and should be repaired",
   "Lock timed out; Retry transaction",
@@ -60,32 +60,32 @@ static const char *handler_error_messages[]=
   "Foreign key constraint is incorrectly formed",
   "Cannot add a child row",
   "Cannot delete a parent row",
   "No savepoint with that name",
   "Non unique key block size",
-  "The table does not exist in engine",
-  "The table already existed in storage engine",
-  "Could not connect to storage engine",
+  "The table does not exist in the storage engine",
+  "The table already existed in the storage engine",
+  "Could not connect to the storage engine",
   "Unexpected null pointer found when using spatial index",
-  "The table changed in storage engine",
+  "The table changed in the storage engine",
   /* 160 */
-  "There's no partition in table for the given value",
+  "There's no partition in the table for the given value",
   "Row-based binary logging of row failed",
   "Index needed in foreign key constraint",
   "Upholding foreign key constraints would lead to a duplicate key error in some other table",
   "Table needs to be upgraded before it can be used",
   "Table is read only",
   "Failed to get next auto increment value",
   "Failed to set row auto increment value",
   "Unknown (generic) error from engine",
-  "Record was not update. Original values was same as new values",
+  "Record was not updated. New values were the same as original values",
   /* 170 */
   "It is not possible to log this statement",
   "The event was corrupt, leading to illegal data being read",
   "The table is of a new format not supported by this version",
   "The event could not be processed. No other handler error happened",
-  "Got a fatal error during initialization of handler",
+  "Fatal error during initialization of handler",
   "File too short; Expected more data in file",
   "Read page with wrong checksum",
   "Too many active concurrent transactions",
   "Record not matching the given partition set",
   "Index column length exceeds limit",
@@ -103,9 +103,9 @@ static const char *handler_error_messages[]=
   /* 190 */
   "Incompatible key or row definition between the MariaDB .frm file and the information in the storage engine. You have to dump and restore the table to fix this",
   "Too many words in a FTS phrase or proximity search",
   "Table encrypted but decryption failed. This could be because correct encryption management plugin is not loaded, used encryption key is not available or encryption method does not match.",
   "Foreign key cascade delete/update exceeds max depth",
-  "Tablespace is missing for table"
+  "Tablespace is missing for a table"
 };
 
 #endif /* MYSYS_MY_HANDLER_ERRORS_INCLUDED */
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
