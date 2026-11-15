# Annotation packet: MDEV-15812  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Assertion `m_lock_type == 2' failed in handler::~handler on dropping a sequence after ER_BINLOG_STMT_MODE_AND_ROW_ENGINE

{code:sql}
--source include/have_innodb.inc
--source include/have_binlog_format_statement.inc

CREATE SEQUENCE seq ENGINE=InnoDB;
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
--error ER_BINLOG_STMT_MODE_AND_ROW_ENGINE
INSERT INTO seq VALUES (1,1,100,1,1,1,1,1);

# Cleanup
DROP SEQUENCE seq;
{code}

{noformat:title=10.3 1730ac5c4ae}
mysqld: /data/src/10.3/sql/handler.h:3011: virtual handler::~handler(): Assertion `m_lock_type == 2' failed.
180408 16:14:49 [ERROR] mysqld got signal 6 ;

#7  0x00007fa20af10ee2 in __assert_fail () from /lib/x86_64-linux-gnu/libc.so.6
#8  0x00005560d104114d in handler::~handler (this=0x7fa1b0075568, __in_chrg=<optimized out>) at /data/src/10.3/sql/handler.h:3011
#9  0x00005560d115de8c in ha_innobase::~ha_innobase (this=0x7fa1b0075568, __in_chrg=<optimized out>) at /data/src/10.3/storage/innobase/handler/ha_innodb.cc:2964
#10 0x00005560d115dec0 in ha_innobase::~ha_innobase (this=0x7fa1b0075568, __in_chrg=<optimized out>) at /data/src/10.3/storage/innobase/handler/ha_innodb.cc:2967
#11 0x00005560d15c606c in ha_sequence::~ha_sequence (this=0x7fa1b009d958, __in_chrg=<optimized out>) at /data/src/10.3/sql/ha_sequence.cc:62
#12 0x00005560d15c60ce in ha_sequence::~ha_sequence (this=0x7fa1b009d958, __in_chrg=<optimized out>) at /data/src/10.3/sql/ha_sequence.cc:63
#13 0x00005560d0c7527d in closefrm (table=0x7fa1b000d560) at /data/src/10.3/sql/table.cc:3574
#14 0x00005560d0d81610 in intern_close_table (table=0x7fa1b000d560) at /data/src/10.3/sql/table_cache.cc:222
#15 0x00005560d0d84551 in tdc_remove_table (thd=0x7fa1b0000b00, remove_type=TDC_RT_REMOVE_ALL, db=0x7fa1b0015578 "test", table_name=0x7fa1b0014ef0 "seq", kill_delayed_threads=false) at /data/src/10.3/sql/table_cache.cc:1151
#16 0x00005560d0c2c287 in mysql_rm_table_no_locks (thd=0x7fa1b0000b00, tables=0x7fa1b0014f28, if_exists=false, drop_temporary=false, drop_view=false, drop_sequence=true, dont_log_query=false, dont_free_locks=false) at /data/src/10.3/sql/sql_table.cc:2504
#17 0x00005560d0c2b37c in mysql_rm_table (thd=0x7fa1b0000b00, tables=0x7fa1b0014f28, if_exists=false, drop_temporary=false, drop_sequence=true) at /data/src/10.3/sql/sql_table.cc:2128
#18 0x00005560d0b670ce in mysql_execute_command (thd=0x7fa1b0000b00) at /data/src/10.3/sql/sql_parse.cc:5052
#19 0x00005560d0b703fc in mysql_parse (thd=0x7fa1b0000b00, rawbuf=0x7fa1b0014e58 "DROP SEQUENCE seq", length=17, parser_state=0x7fa20420c5d0, is_com_multi=false, is_next_command=false) at /data/src/10.3/sql/sql_parse.cc:8013
#20 0x00005560d0b5daaf in dispatch_command (command=COM_QUERY, thd=0x7fa1b0000b00, packet=0x7fa1b0126101 "DROP SEQUENCE seq", packet_length=17, is_com_multi=false, is_next_command=false) at /data/src/10.3/sql/sql_parse.cc:1842
#21 0x00005560d0b5c4ee in do_command (thd=0x7fa1b0000b00) at /data/src/10.3/sql/sql_parse.cc:1387
#22 0x00005560d0cc0ed7 in do_handle_one_connection (connect=0x5560d45302d0) at /data/src/10.3/sql/sql_connect.cc:1402
#23 0x00005560d0cc0c64 in handle_one_connection (arg=0x5560d45302d0) at /data/src/10.3/sql/sql_connect.cc:1308
#24 0x00005560d114867d in pfs_spawn_thread (arg=0x5560d4538690) at /data/src/10.3/storage/perfschema/pfs.cc:1862
#25 0x00007fa20cbe7494 in start_thread (arg=0x7fa20420d700) at pthread_create.c:333
#26 0x00007fa20afcd93f in clone () from /lib/x86_64-linux-gnu/libc.so.6
{noformat}

No visible effect on a non-debug build.
```

## Fix commit message(s)

`0bfd45f63419`

```
Fix for MDEV-15812 Assert in SEQUENCE when forcing STATEMEMT format

The bug was the we copied the lock type to the underlying engine even when
external_lock failed.
```

## Files the fix changed

Snapshot holds 3,323 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/ha_sequence.cc`

## The fix diff

### `sql/ha_sequence.cc`

```diff
diff --git a/sql/ha_sequence.cc b/sql/ha_sequence.cc
index df9d9656c56..8bb5a98e39b 100644
--- a/sql/ha_sequence.cc
+++ b/sql/ha_sequence.cc
@@ -320,11 +320,12 @@ int ha_sequence::external_lock(THD *thd, int lock_type)
 
   /*
     Copy lock flag to satisfy DBUG_ASSERT checks in ha_* functions in
     handler.cc when we later call it with file->ha_..()
   */
-  file->m_lock_type= lock_type;
+  if (!error)
+    file->m_lock_type= lock_type;
   return error;
 }
 
 /*
   Squence engine error deal method
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
