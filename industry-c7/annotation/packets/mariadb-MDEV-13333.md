# Annotation packet: MDEV-13333  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Deadlock failure that does not occur elsewhere

MariaDB gets the following deadlock error:

localhost-dir: sql_create.c:837-5 Fill File table Query failed: INSERT INTO File
(FileIndex, JobId, PathId, FilenameId, LStat, MD5, DeltaSeq) SELECT
batch.FileIndex, batch.JobId, Path.PathId, Filename.FilenameId,batch.LStat,
batch.MD5, batch.DeltaSeq FROM batch JOIN Path ON (batch.Path = Path.Path) JOIN
Filename ON (batch.Name = Filename.Name): ERR=Deadlock found when trying to get
lock;

When running the Bacula 9.0.1 regression script named: three-pool-virtual-test
This does not occur on any version of MySQL, nor the Ubuntu version 10.0 of MariaDB.  The code has been stable for many years.  

I am running all instances of MariaDB and MySQL out of the box.  I have changed no parameters.

This appears to be a false deadlock detection.  Note, it is 100% reproducible.
```

## Fix commit message(s)

`3b37edee1a51`

```
MDEV-13333: Deadlock failure that does not occur elsewhere

InnoDB executed code that is mean to execute only when Galera
is used and in bad luck one of the transactions is selected
incorrectly as deadlock victim. Fixed by adding wsrep_on_trx()
condition before entering actual Galera transaction handling.

No always repeatable test case for this issue is known.
```

`4caf3e08a853`

```
Add MDEV-11080, MDEV-16709 tests for the MDEV-13333 fix

The regression that was introduced in
commit 723f87e9d318aedad30dfb9dde104312d6612662
was fixed as part of MDEV-13333
(commit 3b37edee1a5121e9523fa8a7f483185f402905e2)
without a test case, because the MDEV-13333 test case
is even less deterministic than these ones.
```

## Files the fix changed

Snapshot holds 3,625 non-test source files. The fix changed 4 file(s); 2 of them are non-test source files (listed below as gold).

- `storage/innobase/lock/lock0lock.cc`
- `storage/xtradb/lock/lock0lock.cc`

## The fix diff

### `storage/innobase/lock/lock0lock.cc`

```diff
--- from commit 3b37edee1a51 ---
diff --git a/storage/innobase/lock/lock0lock.cc b/storage/innobase/lock/lock0lock.cc
index 441fcace7c3..3970a559a4c 100644
--- a/storage/innobase/lock/lock0lock.cc
+++ b/storage/innobase/lock/lock0lock.cc
@@ -4961,11 +4961,11 @@ lock_table_create(
 	ut_ad(table->n_ref_count > 0 || !table->can_be_evicted);
 
 	UT_LIST_ADD_LAST(trx_locks, trx->lock.trx_locks, lock);
 
 #ifdef WITH_WSREP
-	if (c_lock) {
+	if (c_lock && wsrep_on_trx(trx)) {
 		if (wsrep_thd_is_wsrep(trx->mysql_thd)
 		    && wsrep_thd_is_BF(trx->mysql_thd, FALSE)) {
 			UT_LIST_INSERT_AFTER(
 				un_member.tab_lock.locks, table->locks, c_lock, lock);
 		} else {
@@ -5200,13 +5200,14 @@ lock_table_enqueue_waiting(
 	}
 
 	/* Enqueue the lock request that will wait to be granted */
 
 #ifdef WITH_WSREP
-	if (trx->lock.was_chosen_as_deadlock_victim) {
+	if (trx->lock.was_chosen_as_deadlock_victim && wsrep_on_trx(trx)) {
 		return(DB_DEADLOCK);
 	}
+
 	lock = lock_table_create(c_lock, table, mode | LOCK_WAIT, trx);
 #else
  	lock = lock_table_create(table, mode | LOCK_WAIT, trx);
 #endif /* WITH_WSREP */
```

### `storage/xtradb/lock/lock0lock.cc`

```diff
--- from commit 3b37edee1a51 ---
diff --git a/storage/xtradb/lock/lock0lock.cc b/storage/xtradb/lock/lock0lock.cc
index 549cc411f69..2183d281b78 100644
--- a/storage/xtradb/lock/lock0lock.cc
+++ b/storage/xtradb/lock/lock0lock.cc
@@ -5001,11 +5001,11 @@ lock_table_create(
 	ut_ad(table->n_ref_count > 0 || !table->can_be_evicted);
 
 	UT_LIST_ADD_LAST(trx_locks, trx->lock.trx_locks, lock);
 
 #ifdef WITH_WSREP
-	if (c_lock) {
+	if (c_lock && wsrep_on_trx(trx)) {
 		if (wsrep_thd_is_wsrep(trx->mysql_thd)
 		    && wsrep_thd_is_BF(trx->mysql_thd, FALSE)) {
 			UT_LIST_INSERT_AFTER(
 				un_member.tab_lock.locks, table->locks, c_lock, lock);
 		} else {
@@ -5242,13 +5242,14 @@ lock_table_enqueue_waiting(
 	}
 
 	/* Enqueue the lock request that will wait to be granted */
 
 #ifdef WITH_WSREP
-	if (trx->lock.was_chosen_as_deadlock_victim) {
+	if (trx->lock.was_chosen_as_deadlock_victim && wsrep_on_trx(trx)) {
 		return(DB_DEADLOCK);
 	}
+
 	lock = lock_table_create(c_lock, table, mode | LOCK_WAIT, trx);
 #else
 	lock = lock_table_create(table, mode | LOCK_WAIT, trx);
 #endif /* WITH_WSREP */
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
