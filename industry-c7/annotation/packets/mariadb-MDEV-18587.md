# Annotation packet: MDEV-18587  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Galera: Rolling upgrade: cluster data incosistency with SR on upgraded 10.4 nodes during drop database

Upgrade scenario:
* Start 5 nodes of 10.3
* Upgrade sequentally from 10.3 to 10.4 starting from node5
- For each node run random values of:

{code:python}
size = [10, 20, 30]
unit = ['ROWS', 'STATEMENTS', 'bytes']
# Run set global wsrep_trx_fragment_size=10;
query = "set global wsrep_trx_fragment_size={}".format(choice(size))
start_obj.mysql_sql_runner(basedir_new, socket.format(cnt), query)
# Run set global wsrep_trx_fragment_unit='ROWS'
query = "set global wsrep_trx_fragment_unit='{}'".format(choice(unit))
start_obj.mysql_sql_runner(basedir_new, socket.format(cnt), query)
{code}

But  it happens even only with 'bytes' and size of 10.
* on node3 for eg, create database and then try to drop:


{code:sql}
MariaDB [(none)]> drop database sbtest;
ERROR 1235 (42000): Streaming replication not supported with binlog_format=STATEMENT

MariaDB [(none)]> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| mysql              |
| performance_schema |
| sbtest             |
| test               |
+--------------------+
5 rows in set (0.001 sec)
{code}

As you see it is not dropped. But instead it is dropped from other nodes:


{code:sql}
MariaDB [(none)]> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| mysql              |
| performance_schema |
| test               |
+--------------------+
4 rows in set (0.001 sec)
{code}

Which leads to data inconsistency.
```

## Fix commit message(s)

`4baab8697ac3`

```
MDEV-18587 Don't reject DDLs if streaming replication is on

The check for streaming replication logging format in
THD::decide_logging_format() did the check also for DDLs running
in TOI mode. This caused DROP DATABASE to fail if streaming
replication was enabled.

Added check for THD wsrep execution mode and perform the check
only if the THD is in local processing mode (i.e. not TOI).

Added galera_sr_create_drop test to verify that CREATE/DROP
statements pass even if streaming replication is on.
```

## Files the fix changed

Snapshot holds 3,369 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/sql_class.cc`

## The fix diff

### `sql/sql_class.cc`

```diff
diff --git a/sql/sql_class.cc b/sql/sql_class.cc
index bb0227df212..029da77761e 100644
--- a/sql/sql_class.cc
+++ b/sql/sql_class.cc
@@ -5985,11 +5985,12 @@ int THD::decide_logging_format(TABLE_LIST *tables)
     We should not decide logging format if the binlog is closed or
     binlogging is off, or if the statement is filtered out from the
     binlog by filtering rules.
   */
 #ifdef WITH_WSREP
-  if (WSREP_CLIENT_NNULL(this) && variables.wsrep_trx_fragment_size > 0)
+  if (WSREP_CLIENT_NNULL(this) && wsrep_thd_is_local(this) &&
+      variables.wsrep_trx_fragment_size > 0)
   {
     if (!is_current_stmt_binlog_format_row())
     {
       my_message(ER_NOT_SUPPORTED_YET,
                  "Streaming replication not supported with "
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
