# Annotation packet: MDEV-13972  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
crash in Item_func_sec_to_time::get_date

{noformat}
Version: '10.2.9-MariaDB'  socket: ''  port: 3306  mariadb.org binary distribution
mysqld.exe!Item_func_sec_to_time::get_date()[item_timefunc.cc:1855]
mysqld.exe!Item::get_date_with_conversion()[item.cc:151]
mysqld.exe!Item_func_to_days::val_int()[item_timefunc.cc:783]
mysqld.exe!Item::update_null_value()[item.h:1454]
mysqld.exe!Item_avg_field::is_null()[item_sum.h:1244]
mysqld.exe!mysql_do()[sql_do.cc:34]
mysqld.exe!mysql_execute_command()[sql_parse.cc:3495]
mysqld.exe!mysql_parse()[sql_parse.cc:7880]
mysqld.exe!dispatch_command()[sql_parse.cc:1814]
mysqld.exe!do_command()[sql_parse.cc:1359]
mysqld.exe!threadpool_process_request()[threadpool_common.cc:366]
mysqld.exe!tp_callback()[threadpool_common.cc:192]
{noformat}

+*How to repeat*+
{code:sql}
do to_days(sec_to_time(time(ceiling(uuid())))); #sporadic
do to_days(sec_to_time(makedate('',rand(~('')))));
{code}
```

## Fix commit message(s)

`c2509a1588ee`

```
MDEV-13972 crash in Item_func_sec_to_time::get_date
```

## Files the fix changed

Snapshot holds 3,114 non-test source files. The fix changed 5 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/item_timefunc.cc`

## The fix diff

### `sql/item_timefunc.cc`

```diff
diff --git a/sql/item_timefunc.cc b/sql/item_timefunc.cc
index 0ed1506bbee..eeb373a75ee 100644
--- a/sql/item_timefunc.cc
+++ b/sql/item_timefunc.cc
@@ -1731,13 +1731,22 @@ overflow:
   char buf[100];
   String tmp(buf, sizeof(buf), &my_charset_bin), *err= args[0]->val_str(&tmp);
 
   ltime->hour= TIME_MAX_HOUR+1;
   check_time_range(ltime, decimals, &unused);
-  make_truncated_value_warning(current_thd, MYSQL_ERROR::WARN_LEVEL_WARN,
-                               err->ptr(), err->length(),
-                               MYSQL_TIMESTAMP_TIME, NullS);
+  if (!err)
+  {
+    ErrConvInteger err2(sec, unsigned_flag);
+    make_truncated_value_warning(current_thd, MYSQL_ERROR::WARN_LEVEL_WARN,
+                                 &err2, MYSQL_TIMESTAMP_TIME, NullS);
+  }
+  else
+  {
+    ErrConvString err2(err);
+    make_truncated_value_warning(current_thd, MYSQL_ERROR::WARN_LEVEL_WARN,
+                                 &err2, MYSQL_TIMESTAMP_TIME, NullS);
+  }
   return 0;
 }
 
 void Item_func_date_format::fix_length_and_dec()
 {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
