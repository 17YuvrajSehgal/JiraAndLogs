# Annotation packet: MDEV-14730  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Assertion `m_lock_type == 2' failed in handler::ha_close

_Note: This is a non-deterministic test case, for reproducing only, don't put it into the regression suite. Run with --repeat=N (N == 5 was always enough on my machine, YMMV._

{code:sql}
--source include/have_innodb.inc
--source include/have_partition.inc

SET @innodb_stats_persistent.save= @@innodb_stats_persistent;
SET GLOBAL innodb_stats_persistent= ON;
SET system_versioning_alter_history= KEEP;

CREATE OR REPLACE TABLE t1 (a INT) ENGINE=InnoDB WITH SYSTEM VERSIONING;
CREATE OR REPLACE TABLE t2 (b INT) ENGINE=InnoDB PARTITION BY HASH(b) PARTITIONS 2;

--connect (con1,localhost,root,,test)
SET innodb_lock_wait_timeout= 3;
--send
	ALTER TABLE t2 ORDER BY b;

--connection default
SET max_statement_time= 1;
ALTER TABLE t1 PARTITION BY system_time INTERVAL 1 HOUR (PARTITION p1 HISTORY, PARTITION pn CURRENT);

# Cleanup
--connection con1
--reap
--disconnect con1
--connection default
DROP TABLE t1, t2;
SET GLOBAL innodb_stats_persistent= @innodb_stats_persistent.save;
{code}

{noformat:title=bb-10.3-temporal 6e530d4df548cd}
2017-12-21  1:48:26 10 [ERROR] InnoDB: Cannot save table statistics for table `test`.`#sql-151a_a#P#p0` /* Partition `p0` */: Lock wait timeout
mysqld: /data/src/bb-10.3-temporal/sql/handler.cc:2612: int handler::ha_close(): Assertion `m_lock_type == 2' failed.
171221  1:48:26 [ERROR] mysqld got signal 6 ;

#7  0x00007f1ad9b20ee2 in __assert_fail () from /lib/x86_64-linux-gnu/libc.so.6
#8  0x000055f7f5608efc in handler::ha_close (this=0x7f1a7c03ca98) at /data/src/bb-10.3-temporal/sql/handler.cc:2612
#9  0x000055f7f5da3ab4 in ha_partition::close (this=0x7f1a7c03c228) at /data/src/bb-10.3-temporal/sql/ha_partition.cc:3817
#10 0x000055f7f5608f5c in handler::ha_close (this=0x7f1a7c03c228) at /data/src/bb-10.3-temporal/sql/handler.cc:2614
#11 0x000055f7f5435bc5 in open_table_from_share (thd=0x7f1a7c000b00, share=0x7f1a7c039560, alias=0x7f1acc6fe0b0 "#sql-151a_9", db_stat=1, prgflag=8, ha_open_flags=4114, outparam=0x7f1a7c03b5e0, is_create_table=false) at /data/src/bb-10.3-temporal/sql/table.cc:3535
#12 0x000055f7f55449ab in THD::open_temporary_table (this=0x7f1a7c000b00, share=0x7f1a7c039560, alias=0x7f1acc6fe0b0 "#sql-151a_9", open_in_engine=true) at /data/src/bb-10.3-temporal/sql/temporary_tables.cc:1112
#13 0x000055f7f55427cf in THD::create_and_open_tmp_table (this=0x7f1a7c000b00, hton=0x55f7f805edb0, frm=0x7f1acc6fd220, path=0x7f1acc6fe91c "./test/#sql-151a_9", db=0x7f1a7c015408 "test", table_name=0x7f1acc6fe0b0 "#sql-151a_9", open_in_engine=true) at /data/src/bb-10.3-temporal/sql/temporary_tables.cc:78
#14 0x000055f7f5401ea1 in mysql_alter_table (thd=0x7f1a7c000b00, new_db=0x7f1a7c015408 "test", new_name=0x0, create_info=0x7f1acc6fec90, table_list=0x7f1a7c014dd0, alter_info=0x7f1acc6febe0, order_num=0, order=0x0, ignore=false) at /data/src/bb-10.3-temporal/sql/sql_table.cc:9773
#15 0x000055f7f548a75f in Sql_cmd_alter_table::execute (this=0x7f1a7c015928, thd=0x7f1a7c000b00) at /data/src/bb-10.3-temporal/sql/sql_alter.cc:331
#16 0x000055f7f532ca37 in mysql_execute_command (thd=0x7f1a7c000b00) at /data/src/bb-10.3-temporal/sql/sql_parse.cc:6258
#17 0x000055f7f5331576 in mysql_parse (thd=0x7f1a7c000b00, rawbuf=0x7f1a7c014c58 "ALTER TABLE t1 PARTITION BY system_time INTERVAL 1 HOUR (PARTITION p1 HISTORY, PARTITION pn CURRENT)", length=100, parser_state=0x7f1acc7005f0, is_com_multi=false, is_next_command=false) at /data/src/bb-10.3-temporal/sql/sql_parse.cc:7988
#18 0x000055f7f531ed39 in dispatch_command (command=COM_QUERY, thd=0x7f1a7c000b00, packet=0x7f1a7c161211 "ALTER TABLE t1 PARTITION BY system_time INTERVAL 1 HOUR (PARTITION p1 HISTORY, PARTITION pn CURRENT)", packet_length=100, is_com_multi=false, is_next_command=false) at /data/src/bb-10.3-temporal/sql/sql_parse.cc:1826
#19 0x000055f7f531d76d in do_command (thd=0x7f1a7c000b00) at /data/src/bb-10.3-temporal/sql/sql_parse.cc:1371
#20 0x000055f7f54852d8 in do_handle_one_connection (connect=0x55f7f85a8c00) at /data/src/bb-10.3-temporal/sql/sql_connect.cc:1420
#21 0x000055f7f5485065 in handle_one_connection (arg=0x55f7f85a8c00) at /data/src/bb-10.3-temporal/sql/sql_connect.cc:1326
#22 0x000055f7f591b58e in pfs_spawn_thread (arg=0x55f7f864b3d0) at /data/src/bb-10.3-temporal/storage/perfschema/pfs.cc:1863
#23 0x00007f1adb7f7494 in start_thread (arg=0x7f1acc701700) at pthread_create.c:333
#24 0x00007f1ad9bdd93f in clone () from /lib/x86_64-linux-gnu/libc.so.6
{noformat}

_Note: The problem apparently starts with a (timed) deadlock between these two threads. The deadlock itself should probably be looked into too, but it is not specific to versioning, while {{m_lock_type}} issue seems to only affect versioning partitioning._
```

## Fix commit message(s)

`e6c5eb5c583b`

```
MDEV-14730 Assertion `m_lock_type == 2' failed in handler::ha_close

SQL: class Table_locker
```

## Files the fix changed

Snapshot holds 3,327 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `sql/partition_info.cc`
- `sql/table.h`

## The fix diff

### `sql/partition_info.cc`

```diff
diff --git a/sql/partition_info.cc b/sql/partition_info.cc
index a25ee53cbab..ec6cebcafb8 100644
--- a/sql/partition_info.cc
+++ b/sql/partition_info.cc
@@ -32,10 +32,11 @@
 #include "sql_parse.h"
 #include "sql_acl.h"                          // *_ACL
 #include "sql_base.h"                         // fill_record
 #include "sql_statistics.h"                   // vers_stat_end
 #include "vers_utils.h"
+#include "lock.h"
 
 #ifdef WITH_PARTITION_STORAGE_ENGINE
 #include "ha_partition.h"
 
 
@@ -1028,36 +1029,81 @@ bool partition_info::vers_setup_expression(THD * thd, uint32 alter_add)
   }
   return false;
 }
 
 
+class Table_locker
+{
+  THD *thd;
+  TABLE &table;
+  thr_lock_type saved_mode;
+  TABLE_LIST table_list;
+  MYSQL_LOCK *saved_lock;
+  bool locked;
+
+public:
+  Table_locker(THD *_thd, TABLE &_table, thr_lock_type lock_type) :
+    thd(_thd),
+    table(_table),
+    saved_mode(table.reginfo.lock_type),
+    table_list(_table, lock_type),
+    saved_lock(_thd->lock),
+    locked(false)
+  {
+    table.reginfo.lock_type= lock_type;
+  }
+  bool lock()
+  {
+    DBUG_ASSERT(table.file);
+    // FIXME: check consistency with table.reginfo.lock_type
+    if (table.file->get_lock_type() != F_UNLCK)
+      return false;
+    thd->lock= NULL;
+    bool res= lock_tables(thd, &table_list, 1, 0);
+    locked= !res;
+    return res;
+  }
+  ~Table_locker()
+  {
+    if (locked)
+      mysql_unlock_tables(thd, thd->lock);
+    table.reginfo.lock_type= saved_mode;
+    thd->lock= saved_lock;
+    if (locked && !thd->in_sub_stmt)
+      ha_commit_trans(thd, false);
+  }
+};
+
+
 // scan table for min/max sys_trx_end
 inline
 bool partition_info::vers_scan_min_max(THD *thd, partition_element *part)
 {
   uint32 sub_factor= num_subparts ? num_subparts : 1;
   uint32 part_id= part->id * sub_factor;
   uint32 part_id_end= part_id + sub_factor;
   DBUG_ASSERT(part->empty);
   DBUG_ASSERT(part->type() == partition_element::HISTORY);
   DBUG_ASSERT(table->s->stat_trx);
+
+  Table_locker l(thd, *table, TL_READ);
+  if (l.lock())
+  {
+    my_error(ER_INTERNAL_ERROR, MYF(0), "min/max scan failed on lock_tables()");
+    return true;
+  }
+
   for (; part_id < part_id_end; ++part_id)
   {
     handler *file= table->file->part_handler(part_id); // requires update_partition() for ha_innopart
     DBUG_ASSERT(file);
-    int rc= file->ha_external_lock(thd, F_RDLCK); // requires ha_commit_trans() for ha_innobase
-    if (rc)
-    {
-      file->update_partition(part_id);
-      goto lock_fail;
-    }
 
     table->default_column_bitmaps();
     bitmap_set_bit(table->read_set, table->vers_end_field()->field_index);
     file->column_bitmaps_signal();
 
-    rc= file->ha_rnd_init(true);
+    int rc= file->ha_rnd_init(true);
     if (!rc)
     {
       while ((rc= file->ha_rnd_next(table->record[0])) != HA_ERR_END_OF_FILE)
       {
         if (part->empty)
@@ -1099,24 +1145,18 @@ bool partition_info::vers_scan_min_max(THD *thd, partition_element *part)
           vers_stat_trx(STAT_TRX_END, part).update_unguarded(table->vers_end_field());
         }
       }
       file->ha_rnd_end();
     }
-    file->ha_external_lock(thd, F_UNLCK);
     file->update_partition(part_id);
     if (rc != HA_ERR_END_OF_FILE)
     {
-      if (!thd->in_sub_stmt)
-        ha_commit_trans(thd, false);
-    lock_fail:
       // TODO: print rc code
       my_error(ER_INTERNAL_ERROR, MYF(0), "min/max scan failed in versioned partitions setup (see warnings)");
       return true;
     }
   }
-  if (!thd->in_sub_stmt)
-    ha_commit_trans(thd, false);
   return false;
 }
 
 void partition_info::vers_update_col_vals(THD *thd, partition_element *el0, partition_element *el1)
 {
@@ -1169,17 +1209,11 @@ bool partition_info::vers_setup_stats(THD * thd, bool is_create_table_ind)
   DBUG_ASSERT(vers_info && vers_info->initialized(false));
   DBUG_ASSERT(table && table->s);
 
   bool error= false;
 
-  TABLE_LIST tl;
-  tl.init_one_table(
-    LEX_STRING_WITH_LEN(table->s->db),
-    LEX_STRING_WITH_LEN(table->s->table_name),
-    table->s->table_name.str,
-    TL_WRITE);
-
+  TABLE_LIST tl(*table, TL_READ);
   MDL_auto_lock mdl_lock(thd, tl);
   if (mdl_lock.acquire_error())
     return true;
 
   mysql_mutex_lock(&table->s->LOCK_rotation);
```

### `sql/table.h`

```diff
diff --git a/sql/table.h b/sql/table.h
index 862268b3c75..656f4ae06a3 100644
--- a/sql/table.h
+++ b/sql/table.h
@@ -1928,10 +1928,20 @@ struct TABLE_LIST
                      (lock_type >= TL_WRITE_ALLOW_WRITE) ?
                      MDL_SHARED_WRITE : MDL_SHARED_READ,
                      MDL_TRANSACTION);
   }
 
+  TABLE_LIST(TABLE &_table, thr_lock_type lock_type)
+  {
+    DBUG_ASSERT(_table.s);
+    init_one_table(
+      LEX_STRING_WITH_LEN(_table.s->db),
+      LEX_STRING_WITH_LEN(_table.s->table_name),
+      _table.s->table_name.str, lock_type);
+    table= &_table;
+  }
+
   inline void init_one_table_for_prelocking(const char *db_name_arg,
                              size_t db_length_arg,
                              const char *table_name_arg,
                              size_t table_name_length_arg,
                              const char *alias_arg,
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
