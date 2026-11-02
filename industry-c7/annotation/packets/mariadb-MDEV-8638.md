# Annotation packet: MDEV-8638  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
REVOKE ALL PRIVILEGES, GRANT OPTION FROM CURRENT_ROLE breaks replication

Replication has some magic that (normally) allows to work correctly with such functions as {{CURRENT_USER}} and {{CURRENT_ROLE}} (see MDEV-8628, MDEV-8631). However, for {{REVOKE ALL PRIVILEGES, GRANT OPTION FROM CURRENT_ROLE}} this magic fails.

{noformat:title=Test case}
--source include/master-slave.inc
--source include/have_binlog_format_mixed.inc

--enable_connect_log

create role r1;
set role r1;
grant select on db.* to current_role;
revoke all privileges, grant option from current_role;

--sync_slave_with_master
{noformat}

{noformat}
Last_SQL_Errno	1269
Last_SQL_Error	Error 'Can't revoke all privileges for one or more of the requested users' on query. Default database: 'test'. Query: 'revoke all privileges, grant option from current_role'
{noformat}
```

## Fix commit message(s)

`b449612907bd`

```
MDEV-8638: REVOKE ALL PRIVILEGES, GRANT OPTION FROM CURRENT_ROLE breaks replication

Fix the replication failure caused by incorect initialization of
THD::invoker_host && THD::invoker_user.

Breakdown of the failure is this:
Query_log_event::host and Query_log_event::user can have their
LEX_STRING's set to length 0, but the actual str member points to
garbage. Code afterwards copies Query_log_event::host and user to
THD::invoker_host and THD::invoker_user.

Calling code for these members expects both members to be initialized.
Eg. the str member be a NULL terminated string and length have
appropriate size.
```

## Files the fix changed

Snapshot holds 3,990 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/log_event.cc`

## The fix diff

### `sql/log_event.cc`

```diff
diff --git a/sql/log_event.cc b/sql/log_event.cc
index 82cd82b5e7a..4a1d13a8004 100644
--- a/sql/log_event.cc
+++ b/sql/log_event.cc
@@ -3629,14 +3629,29 @@ Query_log_event::Query_log_event(const char* buf, uint event_len,
     }
   }
   if (time_zone_len)
     copy_str_and_move(&time_zone_str, &start, time_zone_len);
 
-  if (user.length > 0)
+  if (user.length)
+  {
     copy_str_and_move((const char **)&(user.str), &start, user.length);
-  if (host.length > 0)
+  }
+  else
+  {
+    user.str= (char *) start++;
+    user.str[0]= '\0';
+  }
+
+  if (host.length)
+  {
     copy_str_and_move((const char **)&(host.str), &start, host.length);
+  }
+  else
+  {
+    host.str= (char *) start++;
+    host.str[0]= '\0';
+  }
 
   /**
     if time_zone_len or catalog_len are 0, then time_zone and catalog
     are uninitialized at this point.  shouldn't they point to the
     zero-length null-terminated strings we allocated space for in the
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
