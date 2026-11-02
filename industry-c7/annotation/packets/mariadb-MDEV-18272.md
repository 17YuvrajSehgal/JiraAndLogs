# Annotation packet: MDEV-18272  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
InnoDB fails to rollback after exceeding FOREIGN KEY recursion depth

_Note: Possibly it is related to the numerous existing bugs known as "MDEV-9663 family" or MDEV-14643 family". But there have been false relations before, I don't want to pollute the bug reports any further, so I'm filing this one separately. If you find a true relation, feel free to close this one as a duplicate._

{code:sql}
--source include/have_innodb.inc

CREATE TABLE t1 (
  pk INT,
  a INT,
  b INT,
  PRIMARY KEY (pk),
  KEY (b)
) ENGINE=InnoDB;

INSERT INTO t1 VALUES  
(1,9,4),(2,0,0),(3,0,0),(4,5,0),(5,0,0),(6,0,3),(7,0,4),(8,3,9),(9,0,0),
(10,0,0),(11,9,0),(12,0,9),(13,9,0),(14,4,5),(15,0,0),(16,0,0);

ALTER TABLE t1 ADD CONSTRAINT FOREIGN KEY (a) REFERENCES t1 (b) ON DELETE CASCADE;
DELETE IGNORE FROM t1 WHERE b = 4;

INSERT IGNORE INTO t1 VALUES  
(1,9,4),(2,0,0),(3,0,0),(4,5,0),(5,0,0),(6,0,3),(7,0,4),(8,3,9),(9,0,0),
(10,0,0),(11,9,0),(12,0,9),(13,9,0),(14,4,5),(15,0,0),(16,0,0);

# Cleanup
DROP TABLE t1;
{code}

On 10.2-10.4 *RelWithDebInfo* builds it produces numerous errors and eventually the very same assertion failure:
{noformat:title=10.2 non-debug a8a27e65a8d2}
2019-01-16 20:34:23 139880853542656 [ERROR] InnoDB: Cannot delete/update rows with cascading foreign key constraints that exceed max depth of 15. Please drop excessive foreign constraints and try again
2019-01-16 20:34:23 139880633984768 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000010)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000010)}
2019-01-16 20:34:23 139880617199360 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x8000000C)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x8000000C)}
2019-01-16 20:34:23 139880625592064 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x8000000F)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x8000000F)}
2019-01-16 20:34:23 139880617199360 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000009),[4]    (0x8000000B)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000009),[4]    (0x8000000B)}
2019-01-16 20:34:23 139880625592064 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000009)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000009)}
2019-01-16 20:34:23 139880617199360 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000003)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000003)}
2019-01-16 20:34:23 139880633984768 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x8000000A)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x8000000A)}
2019-01-16 20:34:23 139880608806656 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000009),[4]    (0x8000000D)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000009),[4]    (0x8000000D)}
2019-01-16 20:34:23 139880633984768 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000003),[4]    (0x80000008)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000003),[4]    (0x80000008)}
2019-01-16 20:34:23 139880633984768 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000002)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000002)}
2019-01-16 20:34:23 139880608806656 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000005)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000005)}
2019-01-16 20:34:23 139880625592064 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000006)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000006)}
2019-01-16 20:34:23 139880608806656 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000004),[4]    (0x8000000E)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000004),[4]    (0x8000000E)}
2019-01-16 20:34:23 139880625592064 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000005),[4]    (0x80000004)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000005),[4]    (0x80000004)}
2019-01-16 20:34:23 0x7f388c961700  InnoDB: Assertion failure in file /data/src/10.2/storage/innobase/row/row0ins.cc line 262
InnoDB: Failing assertion: !cursor->index->is_committed()
InnoDB: We intentionally generate a memory trap.

#5  0x0000561975aa9993 in ut_dbg_assertion_failed (expr=expr@entry=0x5619762f6670 "!cursor->index->is_committed()", file=file@entry=0x5619762f6520 "/data/src/10.2/storage/innobase/row/row0ins.cc", line=line@entry=262) at /data/src/10.2/storage/innobase/ut/ut0dbg.cc:60
#6  0x0000561975fb0ccd in row_ins_sec_index_entry_by_modify (mtr=0x7f388c95d890, thr=0x7f38400b7938, entry=0x7f38400943a8, heap=0x7f38400a2220, offsets_heap=0x7f38400bb900, offsets=0x7f388c95c980, cursor=0x7f388c95ca00, mode=2, flags=0) at /data/src/10.2/storage/innobase/row/row0ins.cc:262
#7  row_ins_sec_index_entry_low (flags=flags@entry=0, mode=<optimized out>, mode@entry=2, index=index@entry=0x7f3840095bb0, offsets_heap=offsets_heap@entry=0x7f38400bb900, heap=heap@entry=0x7f38400a2220, entry=entry@entry=0x7f38400943a8, trx_id=0, thr=0x7f38400b7938, dup_chk_only=false) at /data/src/10.2/storage/innobase/row/row0ins.cc:3054
#8  0x0000561975fb3a2c in row_ins_sec_index_entry (index=0x7f3840095bb0, entry=0x7f38400943a8, thr=0x7f38400b7938, dup_chk_only=<optimized out>) at /data/src/10.2/storage/innobase/row/row0ins.cc:3248
#9  0x0000561975fb5ddf in row_ins_index_entry (thr=0x7f38400b7938, entry=<optimized out>, index=0x7f3840095bb0) at /data/src/10.2/storage/innobase/row/row0ins.cc:3294
#10 row_ins_index_entry_step (thr=0x7f38400b7938, node=<optimized out>) at /data/src/10.2/storage/innobase/row/row0ins.cc:3442
#11 row_ins (thr=<optimized out>, node=<optimized out>) at /data/src/10.2/storage/innobase/row/row0ins.cc:3585
#12 row_ins_step (thr=thr@entry=0x7f38400b7938) at /data/src/10.2/storage/innobase/row/row0ins.cc:3811
#13 0x0000561975fc5098 in row_insert_for_mysql (mysql_rec=mysql_rec@entry=0x7f3840093cf8 "\371\002", prebuilt=0x7f38400b6af0) at /data/src/10.2/storage/innobase/row/row0mysql.cc:1413
#14 0x0000561975f14d41 in ha_innobase::write_row (this=0x7f3840091cf0, record=0x7f3840093cf8 "\371\002") at /data/src/10.2/storage/innobase/handler/ha_innodb.cc:8234
#15 0x0000561975cf44ea in handler::ha_write_row (this=0x7f3840091cf0, buf=0x7f3840093cf8 "\371\002") at /data/src/10.2/sql/handler.cc:5961
#16 0x0000561975b39ecb in write_record (thd=thd@entry=0x7f38400009a8, table=table@entry=0x7f38400b5b18, info=info@entry=0x7f388c95e8f0) at /data/src/10.2/sql/sql_insert.cc:1930
#17 0x0000561975b4027a in mysql_insert (thd=0x7f38400009a8, table_list=<optimized out>, fields=..., values_list=..., update_fields=..., update_values=..., duplic=DUP_ERROR, ignore=true) at /data/src/10.2/sql/sql_insert.cc:1057
#18 0x0000561975b56691 in mysql_execute_command (thd=0x7f38400009a8) at /data/src/10.2/sql/sql_parse.cc:4438
#19 0x0000561975b5cbfa in mysql_parse (thd=0x7f38400009a8, rawbuf=<optimized out>, length=<optimized out>, parser_state=<optimized out>, is_com_multi=<optimized out>, is_next_command=<optimized out>) at /data/src/10.2/sql/sql_parse.cc:8015
#20 0x0000561975b60774 in dispatch_command (command=command@entry=COM_QUERY, thd=thd@entry=0x7f38400009a8, packet=packet@entry=0x7f3840006ce9 "INSERT IGNORE INTO t1 VALUES  \n(1,9,4),(2,0,0),(3,0,0),(4,5,0),(5,0,0),(6,0,3),(7,0,4),(8,3,9),(9,0,0),\n(10,0,0),(11,9,0),(12,0,9),(13,9,0),(14,4,5),(15,0,0),(16,0,0)", packet_length=packet_length@entry=166, is_com_multi=is_com_multi@entry=false, is_next_command=is_next_command@entry=false) at /data/src/10.2/sql/sql_parse.cc:1826
#21 0x0000561975b611a9 in do_command (thd=0x7f38400009a8) at /data/src/10.2/sql/sql_parse.cc:1379
#22 0x0000561975c2a604 in do_handle_one_connection (connect=connect@entry=0x561977d66b28) at /data/src/10.2/sql/sql_connect.cc:1335
#23 0x0000561975c2a7a4 in handle_one_connection (arg=arg@entry=0x561977d66b28) at /data/src/10.2/sql/sql_connect.cc:1241
#24 0x0000561975eef254 in pfs_spawn_thread (arg=0x561977d28ba8) at /data/src/10.2/storage/perfschema/pfs.cc:1862
#25 0x00007f389aef4494 in start_thread (arg=0x7f388c961700) at pthread_create.c:333
#26 0x00007f38992da93f in clone () from /lib/x86_64-linux-gnu/libc.so.6
{noformat}

Reproducible on older 10.2, at least 10.2.15 (I didn't check earlier versions).

On a debug build, it fails earlier:
{noformat:title=10.2 debug a8a27e65a8}
2019-01-16 20:46:15 140694608205568 [ERROR] InnoDB: Cannot delete/update rows with cascading foreign key constraints that exceed max depth of 15. Please drop excessive foreign constraints and try again
2019-01-16 20:46:15 140694312175360 [ERROR] InnoDB: tried to purge non-delete-marked record in index `a` of table `test`.`t1`: tuple: TUPLE (info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000010)}, record: COMPACT RECORD(info_bits=0, 2 fields): {[4]    (0x80000000),[4]    (0x80000010)}
mysqld: /data/src/10.2/storage/innobase/row/row0purge.cc:621: bool row_purge_remove_sec_if_poss_leaf(purge_node_t*, dict_index_t*, const dtuple_t*): Assertion `0' failed.
190116 20:46:15 [ERROR] mysqld got signal 6 ;

#7  0x00007ff60c5e1ee2 in __assert_fail () from /lib/x86_64-linux-gnu/libc.so.6
#8  0x000055f464b8ac87 in row_purge_remove_sec_if_poss_leaf (node=0x55f468938fb0, index=0x7ff5b8091638, entry=0x7ff5e8016a38) at /data/src/10.2/storage/innobase/row/row0purge.cc:621
#9  0x000055f464b8aff2 in row_purge_remove_sec_if_poss (node=0x55f468938fb0, index=0x7ff5b8091638, entry=0x7ff5e8016a38) at /data/src/10.2/storage/innobase/row/row0purge.cc:717
#10 0x000055f464b8b1ff in row_purge_del_mark (node=0x55f468938fb0) at /data/src/10.2/storage/innobase/row/row0purge.cc:791
#11 0x000055f464b8be4a in row_purge_record_func (node=0x55f468938fb0, undo_rec=0x7ff5e8014ab8 "", thr=0x55f468938ef8, updated_extern=false) at /data/src/10.2/storage/innobase/row/row0purge.cc:1102
#12 0x000055f464b8c0c1 in row_purge (node=0x55f468938fb0, undo_rec=0x7ff5e8014ab8 "", thr=0x55f468938ef8) at /data/src/10.2/storage/innobase/row/row0purge.cc:1163
#13 0x000055f464b8c400 in row_purge_step (thr=0x55f468938ef8) at /data/src/10.2/storage/innobase/row/row0purge.cc:1249
#14 0x000055f464b1c65b in que_thr_step (thr=0x55f468938ef8) at /data/src/10.2/storage/innobase/que/que0que.cc:1045
#15 0x000055f464b1c859 in que_run_threads_low (thr=0x55f468938ef8) at /data/src/10.2/storage/innobase/que/que0que.cc:1107
#16 0x000055f464b1ca02 in que_run_threads (thr=0x55f468938ef8) at /data/src/10.2/storage/innobase/que/que0que.cc:1147
#17 0x000055f464c06747 in trx_purge (n_purge_threads=4, batch_size=300, truncate=false) at /data/src/10.2/storage/innobase/trx/trx0purge.cc:1733
#18 0x000055f464bd8222 in srv_do_purge (n_total_purged=0x7ff5f27fbed0) at /data/src/10.2/storage/innobase/srv/srv0srv.cc:2688
#19 0x000055f464bd878b in srv_purge_coordinator_thread (arg=0x0) at /data/src/10.2/storage/innobase/srv/srv0srv.cc:2830
#20 0x00007ff60e2b8494 in start_thread (arg=0x7ff5f27fc700) at pthread_create.c:333
#21 0x00007ff60c69e93f in clone () from /lib/x86_64-linux-gnu/libc.so.6
{noformat}

No failure on 10.1.
```

## Fix commit message(s)

`8024f8c6b86b`

```
MDEV-18272 InnoDB fails to rollback after exceeding FOREIGN KEY recursion depth

row_mysql_handle_errors(): Correct the wrong error handling for
the code DB_FOREIGN_EXCEED_MAX_CASCADE that was introduced in

https://github.com/mysql/mysql-server/commit/c0923d396aef46799883390e9dcf7bbf173e4a03

    commit 35f5429eda94f2ce87e453653cd22298d5851cfa
    Author: Jimmy Yang <jimmy.yang@oracle.com>
    Date:   Wed Oct 6 06:55:34 2010 -0700

        Manual port Bug #Bug #54582 "stack overflow when opening many tables
        linked with foreign keys at once" from mysql-5.1-security to
        mysql-5.5-security again.

        rb://391 approved by Heikki

No known test case exists for repeating the bug before MariaDB 10.2.
The scenario should be that DB_FOREIGN_EXCEED_MAX_CASCADE is returned,
then InnoDB wrongly skips the rollback to the start of the current
row operation, and finally the SQL layer commits the transaction.
Normally the SQL layer would roll back either the entire transaction or
to the start of the statement. In the faulty scenario, InnoDB would
leave the transaction in an inconsistent state, and the SQL layer could
commit the transaction.
```

`f855ec24d7bd`

```
MDEV-18272: Add the test case

The test case was accidentally omitted from the merge
commit 913e33e423b434712a9d708cd0f0244d2f03cb0b.
```

## Files the fix changed

Snapshot holds 3,118 non-test source files. The fix changed 4 file(s); 2 of them are non-test source files (listed below as gold).

- `storage/innobase/row/row0mysql.c`
- `storage/xtradb/row/row0mysql.c`

## The fix diff

### `storage/innobase/row/row0mysql.c`

```diff
--- from commit 8024f8c6b86b ---
diff --git a/storage/innobase/row/row0mysql.c b/storage/innobase/row/row0mysql.c
index 8804e2c4e03..c16d1b8ea36 100644
--- a/storage/innobase/row/row0mysql.c
+++ b/storage/innobase/row/row0mysql.c
@@ -1,8 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 2000, 2014, Oracle and/or its affiliates. All Rights Reserved.
+Copyright (c) 2019, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -570,12 +571,11 @@ handle_new_error:
 	trx->error_state = DB_SUCCESS;
 
 	switch (err) {
 	case DB_LOCK_WAIT_TIMEOUT:
 		if (row_rollback_on_timeout) {
-			trx_general_rollback_for_mysql(trx, NULL);
-			break;
+			goto rollback;
 		}
 		/* fall through */
 	case DB_DUPLICATE_KEY:
 	case DB_FOREIGN_DUPLICATE_KEY:
 	case DB_TOO_BIG_RECORD:
@@ -584,10 +584,11 @@ handle_new_error:
 	case DB_NO_REFERENCED_ROW:
 	case DB_CANNOT_ADD_CONSTRAINT:
 	case DB_TOO_MANY_CONCURRENT_TRXS:
 	case DB_OUT_OF_FILE_SPACE:
 	case DB_INTERRUPTED:
+	rollback_to_savept:
 		if (savept) {
 			/* Roll back the latest, possibly incomplete
 			insertion or update */
 
 			trx_general_rollback_for_mysql(trx, savept);
@@ -607,10 +608,11 @@ handle_new_error:
 
 		return(TRUE);
 
 	case DB_DEADLOCK:
 	case DB_LOCK_TABLE_FULL:
+	rollback:
 		/* Roll back the whole transaction; this resolution was added
 		to version 3.23.43 */
 
 		trx_general_rollback_for_mysql(trx, NULL);
 		break;
@@ -636,18 +638,18 @@ handle_new_error:
 		      "InnoDB: If the mysqld server crashes"
 		      " after the startup or when\n"
 		      "InnoDB: you dump the tables, look at\n"
 		      "InnoDB: " REFMAN "forcing-innodb-recovery.html"
 		      " for help.\n", stderr);
-		break;
+		goto rollback_to_savept;
 	case DB_FOREIGN_EXCEED_MAX_CASCADE:
 		fprintf(stderr, "InnoDB: Cannot delete/update rows with"
 			" cascading foreign key constraints that exceed max"
 			" depth of %lu\n"
 			"Please drop excessive foreign constraints"
 			" and try again\n", (ulong) DICT_FK_MAX_RECURSIVE_LOAD);
-		break;
+		goto rollback_to_savept;
 	default:
 		fprintf(stderr, "InnoDB: unknown error code %lu\n",
 			(ulong) err);
 		ut_error;
 	}
```

### `storage/xtradb/row/row0mysql.c`

```diff
--- from commit 8024f8c6b86b ---
diff --git a/storage/xtradb/row/row0mysql.c b/storage/xtradb/row/row0mysql.c
index 5b01adf7c82..a17a8d59b83 100644
--- a/storage/xtradb/row/row0mysql.c
+++ b/storage/xtradb/row/row0mysql.c
@@ -1,8 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 2000, 2014, Oracle and/or its affiliates. All Rights Reserved.
+Copyright (c) 2019, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -572,12 +573,11 @@ handle_new_error:
 	trx->error_state = DB_SUCCESS;
 
 	switch (err) {
 	case DB_LOCK_WAIT_TIMEOUT:
 		if (row_rollback_on_timeout) {
-			trx_general_rollback_for_mysql(trx, NULL);
-			break;
+			goto rollback;
 		}
 		/* fall through */
 	case DB_DUPLICATE_KEY:
 	case DB_FOREIGN_DUPLICATE_KEY:
 	case DB_TOO_BIG_RECORD:
@@ -586,10 +586,11 @@ handle_new_error:
 	case DB_NO_REFERENCED_ROW:
 	case DB_CANNOT_ADD_CONSTRAINT:
 	case DB_TOO_MANY_CONCURRENT_TRXS:
 	case DB_OUT_OF_FILE_SPACE:
 	case DB_INTERRUPTED:
+	rollback_to_savept:
 		if (savept) {
 			/* Roll back the latest, possibly incomplete
 			insertion or update */
 
 			trx_general_rollback_for_mysql(trx, savept);
@@ -609,10 +610,11 @@ handle_new_error:
 
 		return(TRUE);
 
 	case DB_DEADLOCK:
 	case DB_LOCK_TABLE_FULL:
+	rollback:
 		/* Roll back the whole transaction; this resolution was added
 		to version 3.23.43 */
 
 		trx_general_rollback_for_mysql(trx, NULL);
 		break;
@@ -638,18 +640,18 @@ handle_new_error:
 		      "InnoDB: If the mysqld server crashes"
 		      " after the startup or when\n"
 		      "InnoDB: you dump the tables, look at\n"
 		      "InnoDB: " REFMAN "forcing-innodb-recovery.html"
 		      " for help.\n", stderr);
-		break;
+		goto rollback_to_savept;
 	case DB_FOREIGN_EXCEED_MAX_CASCADE:
 		fprintf(stderr, "InnoDB: Cannot delete/update rows with"
 			" cascading foreign key constraints that exceed max"
 			" depth of %lu\n"
 			"Please drop excessive foreign constraints"
 			" and try again\n", (ulong) DICT_FK_MAX_RECURSIVE_LOAD);
-		break;
+		goto rollback_to_savept;
 	default:
 		fprintf(stderr, "InnoDB: unknown error code %lu\n",
 			(ulong) err);
 		ut_error;
 	}
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
