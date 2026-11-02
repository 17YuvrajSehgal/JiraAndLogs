# Annotation packet: MDEV-20821  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
mariadb parallel slave server shutdown hang - v10.4.8

During on-site engagement, I installed master-slave configuration with MaxScale v2.3 on top of master node.

OS: CentOS 7.4.1708
MariaDB: v10.4.8
MaxScale: v2.3.11

Customer is using GTID to utilize auto failover of MaxScale and HA test has been done successfully.

But when I tried to shutdown mariadb server it failed with timeout.
I tried 
$ systemctl stop mysql 
and 
$ mysqladmin shutdown and the result is the same.

The last error log is follows..
...
[Note] Slave I/O thread: connected to master 'xxx@xxxx:3306', replication starts at GTID position '0-1000-382'
----------------------------------------------

So If I stop the slave with "mysql> stop slave;" and then tried to stop the mariadb server, it stops immediately.
It looks like shutdown never stops "Slave I/O thread"... and got timeout.

Is it a known issue of v10.4.8 or any OS setting dependancies ? 

FYI. innodb-thread-concurrency is set to 0.

Thanks
```

## Fix commit message(s)

`5cd21ac20225`

```
MDEV-20821 parallel slave server shutdown hang

Parallel slave server shutdown found to be hanging in
close_connections() triggered by shutdown due to a slave worker thread
would not be notified to exit in case the worker was sitting idle.

Fixed with destroying the worker pool earlier that is in
slave_prepare_for_shutdown() when all their driver threads have already left.
A test file is added to simulate the bug condition as well as check
multi-sourced and not-idle worker cases.
```

## Files the fix changed

Snapshot holds 3,263 non-test source files. The fix changed 4 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/slave.cc`

## The fix diff

### `sql/slave.cc`

```diff
diff --git a/sql/slave.cc b/sql/slave.cc
index d39e17baadc..87c43ad64aa 100644
--- a/sql/slave.cc
+++ b/sql/slave.cc
@@ -1441,10 +1441,13 @@ int start_slave_threads(THD *thd,
 void slave_prepare_for_shutdown()
 {
   mysql_mutex_lock(&LOCK_active_mi);
   master_info_index->free_connections();
   mysql_mutex_unlock(&LOCK_active_mi);
+  // It's safe to destruct worker pool now when
+  // all driver threads are gone.
+  global_rpl_thread_pool.destroy();
   stop_slave_background_thread();
 }
 
 /*
   Release slave threads at time of executing shutdown.
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
