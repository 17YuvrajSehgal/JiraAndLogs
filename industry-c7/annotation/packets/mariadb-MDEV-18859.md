# Annotation packet: MDEV-18859  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Server crashes in bitmap_bits_set / pack_row / THD::binlog_write_row upon DELETE .. FOR PORTION with binary logging

{noformat}
$ perl ./mtr period.delete --mysqld=--log-bin
{noformat}

{noformat:title=10.4 5f34513c}
#3  <signal handler called>
#4  0x000055f9ce67da46 in bitmap_bits_set (map=0x0) at /data/src/10.4/mysys/my_bitmap.c:603
#5  0x000055f9ce01ea00 in pack_row (table=0x7f95ac07dff0, cols=0x0, row_data=0x7f95ac1d6240 "\370\001", record=0x7f95ac07ee60 "\375\001") at /data/src/10.4/sql/rpl_record.cc:65
#6  0x000055f9cdb16bff in THD::binlog_write_row (this=0x7f95ac000b00, table=0x7f95ac07dff0, is_trans=true, record=0x7f95ac07ee60 "\375\001") at /data/src/10.4/sql/sql_class.cc:6715
#7  0x000055f9cded93d5 in Write_rows_log_event::binlog_row_logging_function (thd=0x7f95ac000b00, table=0x7f95ac07dff0, is_transactional=true, before_record=0x0, after_record=0x7f95ac07ee60 "\375\001") at /data/src/10.4/sql/log_event.h:4796
#8  0x000055f9cded29a3 in binlog_log_row_internal (table=0x7f95ac07dff0, before_record=0x0, after_record=0x7f95ac07ee60 "\375\001", log_func=0x55f9cded9352 <Write_rows_log_event::binlog_row_logging_function(THD*, TABLE*, bool, unsigned char const*, unsigned char const*)>) at /data/src/10.4/sql/handler.cc:6375
#9  0x000055f9cded2ad5 in binlog_log_row (table=0x7f95ac07dff0, before_record=0x0, after_record=0x7f95ac07ee60 "\375\001", log_func=0x55f9cded9352 <Write_rows_log_event::binlog_row_logging_function(THD*, TABLE*, bool, unsigned char const*, unsigned char const*)>) at /data/src/10.4/sql/handler.cc:6395
#10 0x000055f9cded3f07 in handler::ha_write_row (this=0x7f95ac07f2b8, buf=0x7f95ac07ee60 "\375\001") at /data/src/10.4/sql/handler.cc:6709
#11 0x000055f9cdcac63c in TABLE::period_make_insert (this=0x7f95ac07dff0, src=0x7f95ac015dc8, dst=0x7f95ac07f068) at /data/src/10.4/sql/table.cc:8330
#12 0x000055f9cdcac7e3 in TABLE::insert_portion_of_time (this=0x7f95ac07dff0, thd=0x7f95ac000b00, period_conds=..., rows_inserted=0x7f95fc253d80) at /data/src/10.4/sql/table.cc:8353
#13 0x000055f9ce07be0d in mysql_delete (thd=0x7f95ac000b00, table_list=0x7f95ac015700, conds=0x7f95ac01b0f0, order_list=0x7f95ac005498, limit=18446744073709551615, options=0, result=0x0) at /data/src/10.4/sql/sql_delete.cc:849
#14 0x000055f9cdb81bab in mysql_execute_command (thd=0x7f95ac000b00) at /data/src/10.4/sql/sql_parse.cc:5032
#15 0x000055f9cdb8cb11 in mysql_parse (thd=0x7f95ac000b00, rawbuf=0x7f95ac0155c8 "delete from t1 for portion of APPTIME from '2000-01-01' to '2018-01-01'", length=71, parser_state=0x7f95fc255180, is_com_multi=false, is_next_command=false) at /data/src/10.4/sql/sql_parse.cc:8204
#16 0x000055f9cdb7813f in dispatch_command (command=COM_QUERY, thd=0x7f95ac000b00, packet=0x7f95ac13a0f1 "delete from t1 for portion of APPTIME from '2000-01-01' to '2018-01-01'", packet_length=71, is_com_multi=false, is_next_command=false) at /data/src/10.4/sql/sql_parse.cc:1829
#17 0x000055f9cdb76925 in do_command (thd=0x7f95ac000b00) at /data/src/10.4/sql/sql_parse.cc:1358
#18 0x000055f9cdcf06b1 in do_handle_one_connection (connect=0x55f9d04d55f0) at /data/src/10.4/sql/sql_connect.cc:1399
#19 0x000055f9cdcf0422 in handle_one_connection (arg=0x55f9d04d55f0) at /data/src/10.4/sql/sql_connect.cc:1302
#20 0x000055f9ce1e5edf in pfs_spawn_thread (arg=0x55f9d04e8140) at /data/src/10.4/storage/perfschema/pfs.cc:1862
#21 0x00007f96043fd494 in start_thread (arg=0x7f95fc256700) at pthread_create.c:333
#22 0x00007f96027e393f in clone () from /lib/x86_64-linux-gnu/libc.so.6
{noformat}
```

## Fix commit message(s)

`7e3e2d060b35`

```
MDEV-18859 Server crashes in bitmap_bits_set / pack_row / THD::binlog_write_row upon DELETE .. FOR PORTION with binary logging

rpl_write_set is initialized in TABLE::mark_columns_per_binlog_row_image.
Since we just call use_all_columns for PORTION OF case, no need in
column marking logic here. Instead, initialize table->rpl_write_set in
place.
```

## Files the fix changed

Snapshot holds 3,370 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/sql_delete.cc`

## The fix diff

### `sql/sql_delete.cc`

```diff
diff --git a/sql/sql_delete.cc b/sql/sql_delete.cc
index 42f96d876a9..d2e511b1d86 100644
--- a/sql/sql_delete.cc
+++ b/sql/sql_delete.cc
@@ -716,13 +716,18 @@ bool mysql_delete(THD *thd, TABLE_LIST *table_list, COND *conds,
   
   if (unlikely(init_ftfuncs(thd, select_lex, 1)))
     goto got_error;
 
   if (table_list->has_period())
+  {
     table->use_all_columns();
+    table->rpl_write_set= table->write_set;
+  }
   else
+  {
     table->mark_columns_needed_for_delete();
+  }
 
   if ((table->file->ha_table_flags() & HA_CAN_FORCE_BULK_DELETE) &&
       !table->prepare_triggers_for_delete_stmt_or_event())
     will_batch= !table->file->start_bulk_delete();
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
