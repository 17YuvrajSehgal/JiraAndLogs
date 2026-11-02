# Annotation packet: MDEV-16980  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Wrongly set tablename len while opening the table for purge thread

_Note: Run with {{--repeat=N}}. For me, {{N=5}} has always been enough, but it can vary._

{code:sql}
--source include/have_innodb.inc
--source include/have_partition.inc

CREATE TABLE t1 ( 
  pk SERIAL,
  d DATE,
  vd DATE AS (d) VIRTUAL,
  PRIMARY KEY(pk),
  KEY (vd)
) ENGINE=InnoDB PARTITION BY HASH(pk) PARTITIONS 2;

INSERT IGNORE INTO t1 (d) VALUES ('2015-04-14');
SET sql_mode= '';
REPLACE INTO t1 SELECT * FROM t1;

# Cleanup
DROP TABLE t1;
{code}

{noformat:title=10.3 5e7496e2eaf0}
mysqld: /data/src/10.3/sql/table.h:1949: void TABLE_LIST::init_one_table(const LEX_CSTRING*, const LEX_CSTRING*, const LEX_CSTRING*, thr_lock_type): Assertion `!table_name_arg->str || strlen(table_name_arg->str) == table_name_arg->length' failed.
180814 23:32:33 [ERROR] mysqld got signal 6 ;

#7  0x00007fa998e94ee2 in __assert_fail () from /lib/x86_64-linux-gnu/libc.so.6
#8  0x000055ef8d9ce98c in TABLE_LIST::init_one_table (this=0x7fa96c00d2f8, db_arg=0x7fa97d7f7fb0, table_name_arg=0x7fa97d7f7fc0, alias_arg=0x0, lock_type_arg=TL_READ) at /data/src/10.3/sql/table.h:1949
#9  0x000055ef8da40011 in open_purge_table (thd=0x7fa96c000b00, db=0x7fa97d7f80a0 "test", dblen=4, tb=0x7fa97d7f8240 "t1", tblen=7) at /data/src/10.3/sql/sql_class.cc:4666
#10 0x000055ef8e0c672b in innodb_acquire_mdl (thd=0x7fa96c000b00, table=0x7fa9400a9b08) at /data/src/10.3/storage/innobase/handler/ha_innodb.cc:20738
#11 0x000055ef8e0c6926 in innodb_find_table_for_vc (thd=0x7fa96c000b00, table=0x7fa9400a9b08) at /data/src/10.3/storage/innobase/handler/ha_innodb.cc:20793
#12 0x000055ef8e0c6e99 in innobase_allocate_row_for_vcol (thd=0x7fa96c000b00, index=0x7fa94007a138, heap=0x7fa97d7f8670, table=0x7fa97d7f8680, record=0x7fa97d7f8688, storage=0x7fa97d7f8678) at /data/src/10.3/storage/innobase/handler/ha_innodb.cc:20947
#13 0x000055ef8e272324 in row_vers_build_clust_v_col (row=0x7fa96c0145f0, clust_index=0x7fa940078878, index=0x7fa94007a138, heap=0x7fa96c014520, vcol_info=0x55ef910d0208) at /data/src/10.3/storage/innobase/row/row0vers.cc:465
#14 0x000055ef8e2734b6 in row_vers_old_has_index_entry (also_curr=true, rec=0x7fa98e95807e "", mtr=0x7fa97d7f8ab0, index=0x7fa94007a138, ientry=0x7fa96c014038, roll_ptr=1407374904066874, trx_id=0, vcol_info=0x55ef910d0208) at /data/src/10.3/storage/innobase/row/row0vers.cc:959
#15 0x000055ef8e227cfe in row_purge_poss_sec (node=0x55ef910d0068, index=0x7fa94007a138, entry=0x7fa96c014038, sec_pcur=0x7fa97d7f9050, sec_mtr=0x7fa97d7f92b0, is_tree=false) at /data/src/10.3/storage/innobase/row/row0purge.cc:346
#16 0x000055ef8e2289d1 in row_purge_remove_sec_if_poss_leaf (node=0x55ef910d0068, index=0x7fa94007a138, entry=0x7fa96c014038) at /data/src/10.3/storage/innobase/row/row0purge.cc:597
#17 0x000055ef8e228eb9 in row_purge_remove_sec_if_poss (node=0x55ef910d0068, index=0x7fa94007a138, entry=0x7fa96c014038) at /data/src/10.3/storage/innobase/row/row0purge.cc:710
#18 0x000055ef8e2290c6 in row_purge_del_mark (node=0x55ef910d0068) at /data/src/10.3/storage/innobase/row/row0purge.cc:784
#19 0x000055ef8e22a5df in row_purge_record_func (node=0x55ef910d0068, undo_rec=0x55ef910d0618 "", thr=0x55ef910cfe98, updated_extern=false) at /data/src/10.3/storage/innobase/row/row0purge.cc:1178
#20 0x000055ef8e22a91c in row_purge (node=0x55ef910d0068, undo_rec=0x55ef910d0618 "", thr=0x55ef910cfe98) at /data/src/10.3/storage/innobase/row/row0purge.cc:1245
#21 0x000055ef8e22acca in row_purge_step (thr=0x55ef910cfe98) at /data/src/10.3/storage/innobase/row/row0purge.cc:1331
#22 0x000055ef8e1ae79c in que_thr_step (thr=0x55ef910cfe98) at /data/src/10.3/storage/innobase/que/que0que.cc:1046
#23 0x000055ef8e1ae9cf in que_run_threads_low (thr=0x55ef910cfe98) at /data/src/10.3/storage/innobase/que/que0que.cc:1108
#24 0x000055ef8e1aebc0 in que_run_threads (thr=0x55ef910cfe98) at /data/src/10.3/storage/innobase/que/que0que.cc:1148
#25 0x000055ef8e27bc01 in srv_task_execute () at /data/src/10.3/storage/innobase/srv/srv0srv.cc:2437
#26 0x000055ef8e27bda6 in srv_worker_thread (arg=0x0) at /data/src/10.3/storage/innobase/srv/srv0srv.cc:2485
#27 0x00007fa99ab6b494 in start_thread (arg=0x7fa97d7fa700) at pthread_create.c:333
#28 0x00007fa998f5193f in clone () from /lib/x86_64-linux-gnu/libc.so.6
{noformat}

Not reproducible with the provided test case on 10.2.
No visible (immediate) effect on a non-debug build.
```

## Fix commit message(s)

`7d4beb7286d5`

```
MDEV-16980	Wrongly set tablename len while opening the 		table for purge thread

Problem:
=======
	Purge tries to fetch mdl lock for the whole table even though it tries
to open one of the partition. But table name length was wrongly set to indicate
the partition name too.

Solution:
========
- Table name length should identify the table name only not the partition name.
```

`e9d9ca8c44c9`

```
MDEV-16980	Wrongly set tablename len while opening the 			table for purge thread

Problem:
=======
	Purge tries to fetch mdl lock for the whole table even though it tries
to open one of the partition. But table name length was wrongly set to indicate
the partition name too.

Solution:
========
- Table name length should identify the table name only not the partition name.
```

## Files the fix changed

Snapshot holds 3,323 non-test source files. The fix changed 4 file(s); 2 of them are non-test source files (listed below as gold).

- `sql/table.h`
- `storage/innobase/handler/ha_innodb.cc`

## The fix diff

### `sql/table.h`

```diff
--- from commit e9d9ca8c44c9 ---
diff --git a/sql/table.h b/sql/table.h
index fc3102fc9a5..33b921cd946 100644
--- a/sql/table.h
+++ b/sql/table.h
@@ -1763,10 +1763,12 @@ struct TABLE_LIST
       mdl_type= MDL_SHARED_NO_WRITE;
     else
       mdl_type= MDL_SHARED_READ;
 
     bzero((char*) this, sizeof(*this));
+    DBUG_ASSERT(!db_name_arg || strlen(db_name_arg) == db_length_arg);
+    DBUG_ASSERT(!table_name_arg || strlen(table_name_arg) == table_name_length_arg);
     db= (char*) db_name_arg;
     db_length= db_length_arg;
     table_name= (char*) table_name_arg;
     table_name_length= table_name_length_arg;
     alias= (char*) (alias_arg ? alias_arg : table_name_arg);
```

### `storage/innobase/handler/ha_innodb.cc`

```diff
--- from commit 7d4beb7286d5 ---
diff --git a/storage/innobase/handler/ha_innodb.cc b/storage/innobase/handler/ha_innodb.cc
index 4ad97597b8b..32c72ade7b2 100644
--- a/storage/innobase/handler/ha_innodb.cc
+++ b/storage/innobase/handler/ha_innodb.cc
@@ -20371,10 +20371,11 @@ static bool table_name_parse(
 		return false;
 	}
 
 	if (char *is_part = strchr(tbl_buf, '#')) {
 		*is_part = '\0';
+		tblnamelen = is_part - tbl_buf;
 	}
 
 	filename_to_tablename(tbl_buf, tblname, MAX_TABLE_NAME_LEN + 1, true);
 	return true;
 }
--- from commit e9d9ca8c44c9 ---
diff --git a/storage/innobase/handler/ha_innodb.cc b/storage/innobase/handler/ha_innodb.cc
index b7d3c6da099..49f51c78f73 100644
--- a/storage/innobase/handler/ha_innodb.cc
+++ b/storage/innobase/handler/ha_innodb.cc
@@ -21339,10 +21339,11 @@ static bool table_name_parse(
 		return false;
 	}
 
 	if (char *is_part = strchr(tbl_buf, '#')) {
 		*is_part = '\0';
+		tblnamelen = is_part - tbl_buf;
 	}
 
 	filename_to_tablename(tbl_buf, tblname, MAX_TABLE_NAME_LEN + 1, true);
 	return true;
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
