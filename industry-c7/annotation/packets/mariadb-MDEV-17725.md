# Annotation packet: MDEV-17725  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Assertion `!is_set() || (m_status == DA_OK_BULK && is_bulk_op())' failed in Diagnostics_area::set_ok_status upon ALTER failing due to error from engine

{code:sql}
--source include/have_innodb.inc

CREATE TABLE t1 (pk INT PRIMARY KEY) ENGINE=InnoDB;
ALTER TABLE t1 ORDER BY a;

# Cleanup
DROP TABLE t1;
{code}

{noformat:title=10.2 32bebfeefb2}
mysqld: /data/src/10.2/sql/sql_error.cc:380: void Diagnostics_area::set_ok_status(ulonglong, ulonglong, const char*): Assertion `!is_set() || (m_status == DA_OK_BULK && is_bulk_op())' failed.
181115 14:43:37 [ERROR] mysqld got signal 6 ;

#7  0x00007fd087c01ee2 in __assert_fail () from /lib/x86_64-linux-gnu/libc.so.6
#8  0x000055ccd93bba47 in Diagnostics_area::set_ok_status (this=0x7fd024005c98, affected_rows=0, last_insert_id=0, message=0x7fd08006b280 "Records: 0  Duplicates: 0  Warnings: 1") at /data/src/10.2/sql/sql_error.cc:380
#9  0x000055ccd936e2b1 in my_ok (thd=0x7fd024000b00, affected_rows=0, id=0, message=0x7fd08006b280 "Records: 0  Duplicates: 0  Warnings: 1") at /data/src/10.2/sql/sql_class.h:4506
#10 0x000055ccd94c0549 in mysql_alter_table (thd=0x7fd024000b00, new_db=0x7fd024012b38 "test", new_name=0x0, create_info=0x7fd08006be50, table_list=0x7fd024012528, alter_info=0x7fd08006bda0, order_num=1, order=0x7fd024012c40, ignore=false) at /data/src/10.2/sql/sql_table.cc:9766
#11 0x000055ccd953a3d7 in Sql_cmd_alter_table::execute (this=0x7fd024012c98, thd=0x7fd024000b00) at /data/src/10.2/sql/sql_alter.cc:329
#12 0x000055ccd93f1a04 in mysql_execute_command (thd=0x7fd024000b00) at /data/src/10.2/sql/sql_parse.cc:6225
#13 0x000055ccd93f6865 in mysql_parse (thd=0x7fd024000b00, rawbuf=0x7fd024012448 "ALTER TABLE t1 ORDER BY a", length=25, parser_state=0x7fd08006d200, is_com_multi=false, is_next_command=false) at /data/src/10.2/sql/sql_parse.cc:8012
#14 0x000055ccd93e41af in dispatch_command (command=COM_QUERY, thd=0x7fd024000b00, packet=0x7fd0240966a1 "ALTER TABLE t1 ORDER BY a", packet_length=25, is_com_multi=false, is_next_command=false) at /data/src/10.2/sql/sql_parse.cc:1824
#15 0x000055ccd93e2b12 in do_command (thd=0x7fd024000b00) at /data/src/10.2/sql/sql_parse.cc:1378
#16 0x000055ccd953506d in do_handle_one_connection (connect=0x55ccdc00fda0) at /data/src/10.2/sql/sql_connect.cc:1335
#17 0x000055ccd9534dfa in handle_one_connection (arg=0x55ccdc00fda0) at /data/src/10.2/sql/sql_connect.cc:1241
#18 0x000055ccd995845c in pfs_spawn_thread (arg=0x55ccdc015bb0) at /data/src/10.2/storage/perfschema/pfs.cc:1862
#19 0x00007fd0896bd494 in start_thread (arg=0x7fd08006e700) at pthread_create.c:333
#20 0x00007fd087cbe93f in clone () from /lib/x86_64-linux-gnu/libc.so.6
{noformat}

Non-debug build produces the error:
{noformat}
query 'ALTER TABLE t1 ORDER BY a' failed: 1105: ORDER BY ignored as there is a user-defined clustered index in the table 't1'
{noformat}
```

## Fix commit message(s)

`cac14b92252b`

```
MDEV-17725 Assertion `!is_set() || (m_status == DA_OK_BULK && is_bulk_op())' failed in Diagnostics_area::set_ok_status upon ALTER failing due to error from engine
```

## Files the fix changed

Snapshot holds 3,686 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/sql_table.cc`

## The fix diff

### `sql/sql_table.cc`

```diff
diff --git a/sql/sql_table.cc b/sql/sql_table.cc
index 1227f144348..af40ae23a6c 100644
--- a/sql/sql_table.cc
+++ b/sql/sql_table.cc
@@ -10019,15 +10019,18 @@ copy_data_between_tables(THD *thd, TABLE *from, TABLE *to,
   {
     if (to->s->primary_key != MAX_KEY &&
         to->file->ha_table_flags() & HA_TABLE_SCAN_ON_INDEX)
     {
       char warn_buff[MYSQL_ERRMSG_SIZE];
+      bool save_abort_on_warning= thd->abort_on_warning;
+      thd->abort_on_warning= false;
       my_snprintf(warn_buff, sizeof(warn_buff), 
                   "ORDER BY ignored as there is a user-defined clustered index"
                   " in the table '%-.192s'", from->s->table_name.str);
       push_warning(thd, Sql_condition::WARN_LEVEL_WARN, ER_UNKNOWN_ERROR,
                    warn_buff);
+      thd->abort_on_warning= save_abort_on_warning;
     }
     else
     {
       bzero((char *) &tables, sizeof(tables));
       tables.table= from;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
