# Annotation packet: MDEV-21195  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
INSERT chooses wrong partition for RANGE partitioning by DECIMAL column

Starting from this revision, MariaDB 10.3+ allows partitioning by range of a decimal column:
{noformat}
commit c3f35ea55a7150b186284e2ef717d12e6f81e13e
Author: Aleksey Midenkov
Date:   Wed Aug 28 11:57:16 2019 +0300

    MDEV-18501 Partition pruning doesn't work for historical queries (refactoring)
    
    SYSTEM_TYPE partitioning: COLUMN properties removed. Partitioning is
    now pure RANGE based on UNIX_TIMESTAMP(row_end).
    
    DECIMAL type is now allowed as RANGE partitioning, we can partition by
    UNIX_TIMESTAMP() (but not for DATETIME which depends on local timezone
    of course).
{noformat}

However, the behavior looks strange.
{code:sql}
MariaDB [test]> create or replace table t (d decimal(2,1)) partition by range (d) (partition p1 values less than (10), partition p2 values less than (20));
Query OK, 0 rows affected (0.690 sec)

MariaDB [test]> insert into t values (9.9);
Query OK, 1 row affected (0.049 sec)

MariaDB [test]> select * from t partition (p1);
Empty set (0.000 sec)

MariaDB [test]> select * from t partition (p2);
+------+
| d    |
+------+
|  9.9 |
+------+
1 row in set (0.000 sec)
{code}

or another way to put it,
{code:sql}
MariaDB [test]> create or replace table t (d decimal(2,1)) partition by range (d) (partition p1 values less than (10));
Query OK, 0 rows affected (0.639 sec)

MariaDB [test]> insert into t values (9.9);
ERROR 1526 (HY000): Table has no partition for value 10
{code}

Obviously, it temporarily rounds the value before finding a partition, but I don't think the outcome is reasonable. I couldn't find any documentation, either in MariaDB KB or in the version of SQL standard which I have access to on how it should really behave (and MySQL doesn't support it even in 8.0, so can't compare with it either).
```

## Fix commit message(s)

`b0fa30808622`

```
MDEV-21195 INSERT chooses wrong partition for RANGE partitioning by DECIMAL column

Use FLOOR rounding for DECIMAL_RESULT item_expr in partition function.
```

## Files the fix changed

Snapshot holds 3,342 non-test source files. The fix changed 5 file(s); 3 of them are non-test source files (listed below as gold).

- `sql/my_decimal.cc`
- `sql/my_decimal.h`
- `sql/sql_partition.cc`

## The fix diff

### `sql/my_decimal.cc`

```diff
diff --git a/sql/my_decimal.cc b/sql/my_decimal.cc
index 01fad3dde37..8acb46b9ef2 100644
--- a/sql/my_decimal.cc
+++ b/sql/my_decimal.cc
@@ -343,16 +343,16 @@ void my_decimal_trim(ulonglong *precision, uint *scale)
 /*
   Convert a decimal to an ulong with a descriptive error message
 */
 
 int my_decimal2int(uint mask, const decimal_t *d, bool unsigned_flag,
-		   longlong *l)
+		   longlong *l, decimal_round_mode round_type)
 {
   int res;
   my_decimal rounded;
   /* decimal_round can return only E_DEC_TRUNCATED */
-  decimal_round(d, &rounded, 0, HALF_UP);
+  decimal_round(d, &rounded, 0, round_type);
   res= (unsigned_flag ?
         decimal2ulonglong(&rounded, (ulonglong *) l) :
         decimal2longlong(&rounded, l));
   if (res & mask)
   {
```

### `sql/my_decimal.h`

```diff
diff --git a/sql/my_decimal.h b/sql/my_decimal.h
index 6d6bb258293..b409a87bdd4 100644
--- a/sql/my_decimal.h
+++ b/sql/my_decimal.h
@@ -346,11 +346,11 @@ my_decimal *seconds2my_decimal(bool sign, ulonglong sec, ulong microsec,
 #define TIME_to_my_decimal(TIME, DECIMAL)                       \
      seconds2my_decimal((TIME)->neg, TIME_to_ulonglong(TIME),   \
                         (TIME)->second_part, (DECIMAL))
 
 int my_decimal2int(uint mask, const decimal_t *d, bool unsigned_flag,
-		   longlong *l);
+		   longlong *l, decimal_round_mode round_type= HALF_UP);
 
 inline
 int my_decimal2double(uint, const decimal_t *d, double *result)
 {
   /* No need to call check_result as this will always succeed */
```

### `sql/sql_partition.cc`

```diff
diff --git a/sql/sql_partition.cc b/sql/sql_partition.cc
index 00a78ce3199..febd88c4b9b 100644
--- a/sql/sql_partition.cc
+++ b/sql/sql_partition.cc
@@ -2838,18 +2838,38 @@ bool partition_key_modified(TABLE *table, const MY_BITMAP *fields)
     FALSE     ok
 */
 
 static inline int part_val_int(Item *item_expr, longlong *result)
 {
-  *result= item_expr->val_int();
+  switch (item_expr->cmp_type())
+  {
+  case DECIMAL_RESULT:
+  {
+    my_decimal buf;
+    my_decimal *val= item_expr->val_decimal(&buf);
+    if (val && my_decimal2int(E_DEC_FATAL_ERROR, val, item_expr->unsigned_flag,
+                              result, FLOOR) != E_DEC_OK)
+      return true;
+    break;
+  }
+  case INT_RESULT:
+    *result= item_expr->val_int();
+    break;
+  case STRING_RESULT:
+  case REAL_RESULT:
+  case ROW_RESULT:
+  case TIME_RESULT:
+    DBUG_ASSERT(0);
+    break;
+  }
   if (item_expr->null_value)
   {
     if (unlikely(current_thd->is_error()))
-      return TRUE;
+      return true;
     *result= LONGLONG_MIN;
   }
-  return FALSE;
+  return false;
 }
 
 
 /*
   The next set of functions are used to calculate the partition identity.
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
