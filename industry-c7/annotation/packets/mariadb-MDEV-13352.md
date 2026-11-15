# Annotation packet: MDEV-13352  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Server crashes in st_join_table::remove_duplicates

{code:sql}
CREATE TABLE t1 (i INT);
INSERT INTO t1 VALUES (1),(2);
SELECT DISTINCT ROW_NUMBER() OVER(), i FROM t1 WHERE 0;
{code}

{noformat:title=10.2 bc75c57cfc18be64f167d91c431076f581b0382b}
#3  <signal handler called>
#4  0x00007fe7a608f32e in st_join_table::remove_duplicates (this=0x7fe78c0136e0) at /data/src/10.2/sql/sql_select.cc:21785
#5  0x00007fe7a608965d in join_init_read_record (tab=0x7fe78c0136e0) at /data/src/10.2/sql/sql_select.cc:19449
#6  0x00007fe7a609bf7e in AGGR_OP::end_send (this=0x7fe78c013c20) at /data/src/10.2/sql/sql_select.cc:26432
#7  0x00007fe7a6087192 in sub_select_postjoin_aggr (join=0x7fe78c013020, join_tab=0x7fe78c0136e0, end_of_records=true) at /data/src/10.2/sql/sql_select.cc:18263
#8  0x00007fe7a6086cce in do_select (join=0x7fe78c013020, procedure=0x0) at /data/src/10.2/sql/sql_select.cc:18094
#9  0x00007fe7a6061527 in JOIN::exec_inner (this=0x7fe78c013020) at /data/src/10.2/sql/sql_select.cc:3477
#10 0x00007fe7a60609f6 in JOIN::exec (this=0x7fe78c013020) at /data/src/10.2/sql/sql_select.cc:3278
#11 0x00007fe7a6061b9f in mysql_select (thd=0x7fe78c000b00, tables=0x7fe78c012878, wild_num=0, fields=..., conds=0x7fe78c012ea8, og_num=0, order=0x0, group=0x0, having=0x0, proc_param=0x0, select_options=2147748609, result=0x7fe78c013000, unit=0x7fe78c0045e8, select_lex=0x7fe78c004d20) at /data/src/10.2/sql/sql_select.cc:3672
#12 0x00007fe7a60564ea in handle_select (thd=0x7fe78c000b00, lex=0x7fe78c004520, result=0x7fe78c013000, setup_tables_done_option=0) at /data/src/10.2/sql/sql_select.cc:373
#13 0x00007fe7a60223c8 in execute_sqlcom_select (thd=0x7fe78c000b00, all_tables=0x7fe78c012878) at /data/src/10.2/sql/sql_parse.cc:6443
#14 0x00007fe7a6018407 in mysql_execute_command (thd=0x7fe78c000b00) at /data/src/10.2/sql/sql_parse.cc:3458
#15 0x00007fe7a6025d88 in mysql_parse (thd=0x7fe78c000b00, rawbuf=0x7fe78c012378 "SELECT DISTINCT ROW_NUMBER() OVER(), i FROM t1 WHERE 0", length=54, parser_state=0x7fe79dc0f200, is_com_multi=false, is_next_command=false) at /data/src/10.2/sql/sql_parse.cc:7879
#16 0x00007fe7a6013e34 in dispatch_command (command=COM_QUERY, thd=0x7fe78c000b00, packet=0x7fe78c168011 "", packet_length=54, is_com_multi=false, is_next_command=false) at /data/src/10.2/sql/sql_parse.cc:1817
#17 0x00007fe7a6012775 in do_command (thd=0x7fe78c000b00) at /data/src/10.2/sql/sql_parse.cc:1362
#18 0x00007fe7a615e4e7 in do_handle_one_connection (connect=0x7fe7a9a8b760) at /data/src/10.2/sql/sql_connect.cc:1354
#19 0x00007fe7a615e274 in handle_one_connection (arg=0x7fe7a9a8b760) at /data/src/10.2/sql/sql_connect.cc:1260
#20 0x00007fe7a64a5922 in pfs_spawn_thread (arg=0x7fe7a9b2df40) at /data/src/10.2/storage/perfschema/pfs.cc:1862
#21 0x00007fe7a5635064 in start_thread (arg=0x7fe79dc10700) at pthread_create.c:309
#22 0x00007fe7a381a62d in clone () at ../sysdeps/unix/sysv/linux/x86_64/clone.S:111
{noformat}
```

## Fix commit message(s)

`17fc288b3054`

```
MDEV-13352: Server crashes in st_join_table::remove_duplicates

Do not run the window function computation step when the select
produces no rows (zero_result_cause!=NULL).
This may cause reads from uninitialized memory.

We still need to run the window function computation step when
the output includes just one row  (for example
SELECT MAX(col), RANK() OVER (...) FROM t1 WHERE 1=0).

This fix also resolves an issue with queries with window functions
producing an output row where should be none, like in
SELECT ROW_NUMBER() FROM t1 WHERE 1=0.

Updated a few test results in the existing tests to reflect this.
```

## Files the fix changed

Snapshot holds 3,525 non-test source files. The fix changed 4 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/sql_select.cc`

## The fix diff

### `sql/sql_select.cc`

```diff
diff --git a/sql/sql_select.cc b/sql/sql_select.cc
index e8e399868db..90f5e11dd16 100644
--- a/sql/sql_select.cc
+++ b/sql/sql_select.cc
@@ -3396,12 +3396,18 @@ void JOIN::exec_inner()
     DBUG_VOID_RETURN;
   }
 
   if (zero_result_cause)
   {
-    if (select_lex->have_window_funcs())
+    if (select_lex->have_window_funcs() && send_row_on_empty_set())
     {
+      /*
+        The query produces just one row but it has window functions.
+
+        The only way to compute the value of window function(s) is to
+        run the entire window function computation step (there is no shortcut).
+      */
       const_tables= table_count;
       first_select= sub_select_postjoin_aggr;
     }
     else
     {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
