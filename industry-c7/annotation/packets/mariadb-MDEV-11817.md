# Annotation packet: MDEV-11817  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Altering a table with more rows than wsrep_max_ws_rows causes cluster to break when running Galera cluster in TOI mode

Reproduce steps:
1. Create a 3 node galera cluster
2. Set wsrep_max_ws_rows to a non-zero value
3. Create a table with more than wsrep_max_ws_rows in it
4. Perform an alter table statement on that table. It will get rejected with:
   ERROR 1180 (HY000): wsrep_max_ws_rows exceeded done
5. The node you were connected to will still have the old table schema, but the other nodes have successfully applied the alter table changes.

At that point any data written to that table will cause the other nodes to terminate due to inconsistency.

Codership was able to verify the issue, but say it is a MariaDB specific bug:
https://groups.google.com/forum/#!topic/codership-team/TDscBC_oAk4
```

## Fix commit message(s)

`aa9db4c162e9`

```
MDEV-11817: Altering a table with more rows than ..

.. wsrep_max_ws_rows causes cluster to break when running
Galera cluster in TOI mode

Problem:
While copying records to temporary table during ALTER TABLE,
if there are more than wsrep_max_wsrep_rows records, the
command fails.

Fix:
Since, the temporary table records are not placed into the
binary log, wsrep_affected_rows must not be incremented.
Added a test.
```

## Files the fix changed

Snapshot holds 3,316 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/handler.cc`

## The fix diff

### `sql/handler.cc`

```diff
diff --git a/sql/handler.cc b/sql/handler.cc
index af06427ff19..cca77eece48 100644
--- a/sql/handler.cc
+++ b/sql/handler.cc
@@ -5724,10 +5724,12 @@ static int write_locked_table_maps(THD *thd)
 }
 
 
 typedef bool Log_func(THD*, TABLE*, bool, const uchar*, const uchar*);
 
+static int check_wsrep_max_ws_rows();
+
 static int binlog_log_row(TABLE* table,
                           const uchar *before_record,
                           const uchar *after_record,
                           Log_func *log_func)
 {
@@ -5763,10 +5765,17 @@ static int binlog_log_row(TABLE* table,
          binlog.
          */
       bool const has_trans= thd->lex->sql_command == SQLCOM_CREATE_TABLE ||
                             table->file->has_transactions();
       error= (*log_func)(thd, table, has_trans, before_record, after_record);
+
+      /*
+        Now that the record has been logged, increment wsrep_affected_rows and
+        also check whether its within the allowable limits (wsrep_max_ws_rows).
+      */
+      if (error == 0)
+        error= check_wsrep_max_ws_rows();
     }
   }
   return error ? HA_ERR_RBR_LOGGING_FAILED : 0;
 }
 
@@ -5921,11 +5930,11 @@ int handler::ha_write_row(uchar *buf)
   rows_changed++;
   if (unlikely(error= binlog_log_row(table, 0, buf, log_func)))
     DBUG_RETURN(error); /* purecov: inspected */
 
   DEBUG_SYNC_C("ha_write_row_end");
-  DBUG_RETURN(check_wsrep_max_ws_rows());
+  DBUG_RETURN(0);
 }
 
 
 int handler::ha_update_row(const uchar *old_data, uchar *new_data)
 {
@@ -5952,11 +5961,11 @@ int handler::ha_update_row(const uchar *old_data, uchar *new_data)
   if (unlikely(error))
     return error;
   rows_changed++;
   if (unlikely(error= binlog_log_row(table, old_data, new_data, log_func)))
     return error;
-  return check_wsrep_max_ws_rows();
+  return 0;
 }
 
 int handler::ha_delete_row(const uchar *buf)
 {
   int error;
@@ -5979,11 +5988,11 @@ int handler::ha_delete_row(const uchar *buf)
   if (unlikely(error))
     return error;
   rows_changed++;
   if (unlikely(error= binlog_log_row(table, buf, 0, log_func)))
     return error;
-  return check_wsrep_max_ws_rows();
+  return 0;
 }
 
 
 
 /** @brief
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
