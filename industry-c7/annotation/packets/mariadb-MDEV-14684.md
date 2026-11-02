# Annotation packet: MDEV-14684  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Assertion `table' failed in mysql_delete

{code:sql}
CREATE OR REPLACE TABLE t1 (i INT);
CREATE OR REPLACE VIEW v1 AS SELECT * FROM t1;
TRUNCATE v1 TO system_time NOW();
{code}

{noformat:title=bb-10.3-temporal 2ae2876a6ce4b1}
mysqld: /data/src/bb-10.3-temporal/sql/sql_delete.cc:316: bool mysql_delete(THD*, TABLE_LIST*, COND*, SQL_I_List<st_order>*, ha_rows, ulonglong, select_result*): Assertion `table' failed.
171216 23:50:53 [ERROR] mysqld got signal 6 ;

#7  0x00007f8f734d4ee2 in __assert_fail () from /lib/x86_64-linux-gnu/libc.so.6
#8  0x000056501d2293d9 in mysql_delete (thd=0x7f8f5c000b00, table_list=0x7f8f5c014d38, conds=0x0, order_list=0x0, limit=18446744073709551615, options=0, result=0x0) at /data/src/bb-10.3-temporal/sql/sql_delete.cc:316
#9  0x000056501d2618b4 in Sql_cmd_truncate_table::execute (this=0x7f8f5c015468, thd=0x7f8f5c000b00) at /data/src/bb-10.3-temporal/sql/sql_truncate.cc:503
#10 0x000056501cda05a5 in mysql_execute_command (thd=0x7f8f5c000b00) at /data/src/bb-10.3-temporal/sql/sql_parse.cc:6258
#11 0x000056501cda50e4 in mysql_parse (thd=0x7f8f5c000b00, rawbuf=0x7f8f5c014c48 "TRUNCATE v1 TO system_time NOW()", length=32, parser_state=0x7f8f6d7435f0, is_com_multi=false, is_next_command=false) at /data/src/bb-10.3-temporal/sql/sql_parse.cc:7988
#12 0x000056501cd928a7 in dispatch_command (command=COM_QUERY, thd=0x7f8f5c000b00, packet=0x7f8f5c11ee21 "TRUNCATE v1 TO system_time NOW()", packet_length=32, is_com_multi=false, is_next_command=false) at /data/src/bb-10.3-temporal/sql/sql_parse.cc:1826
#13 0x000056501cd912db in do_command (thd=0x7f8f5c000b00) at /data/src/bb-10.3-temporal/sql/sql_parse.cc:1371
#14 0x000056501cef7ada in do_handle_one_connection (connect=0x565020660620) at /data/src/bb-10.3-temporal/sql/sql_connect.cc:1420
#15 0x000056501cef7867 in handle_one_connection (arg=0x565020660620) at /data/src/bb-10.3-temporal/sql/sql_connect.cc:1326
#16 0x000056501d38dcfc in pfs_spawn_thread (arg=0x565020668590) at /data/src/bb-10.3-temporal/storage/perfschema/pfs.cc:1863
#17 0x00007f8f751ab494 in start_thread (arg=0x7f8f6d744700) at pthread_create.c:333
#18 0x00007f8f7359193f in clone () from /lib/x86_64-linux-gnu/libc.so.6
{noformat}
```

## Fix commit message(s)

`8ba06032aea4`

```
MDEV-14684 Assertion `table' failed in mysql_delete

SQL: disable TRUNCATE table_name TO statement for VIEWs
```

## Files the fix changed

Snapshot holds 3,328 non-test source files. The fix changed 4 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/sql_delete.cc`

## The fix diff

### `sql/sql_delete.cc`

```diff
diff --git a/sql/sql_delete.cc b/sql/sql_delete.cc
index 9c535e2124a..fcd5708863a 100644
--- a/sql/sql_delete.cc
+++ b/sql/sql_delete.cc
@@ -310,10 +310,16 @@ bool mysql_delete(THD *thd, TABLE_LIST *table_list, COND *conds,
   THD_STAGE_INFO(thd, stage_init_update);
 
   bool truncate_history= table_list->vers_conditions;
   if (truncate_history)
   {
+    if (table_list->is_view_or_derived())
+    {
+      my_error(ER_VERS_TRUNCATE_TO_VIEW, MYF(0));
+      DBUG_RETURN(true);
+    }
+
     TABLE *table= table_list->table;
     DBUG_ASSERT(table);
 
 #ifdef WITH_PARTITION_STORAGE_ENGINE
     if (table->part_info)
@@ -326,11 +332,12 @@ bool mysql_delete(THD *thd, TABLE_LIST *table_list, COND *conds,
     DBUG_ASSERT(!conds);
     if (select_lex->vers_setup_conds(thd, table_list, &conds))
       DBUG_RETURN(TRUE);
 
     // trx_sees() in InnoDB reads sys_trx_start
-    if (!table->versioned(VERS_TIMESTAMP)) {
+    if (!table->versioned(VERS_TIMESTAMP))
+    {
       DBUG_ASSERT(table_list->vers_conditions.type == SYSTEM_TIME_BEFORE);
       bitmap_set_bit(table->read_set, table->vers_end_field()->field_index);
     }
   }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
