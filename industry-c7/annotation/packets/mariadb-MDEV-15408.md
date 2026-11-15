# Annotation packet: MDEV-15408  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Confusing error message upon ER_VERS_FIELD_WRONG_TYPE while omitting UNSIGNED in BIGINT

{code:sql|title=bb-10.3-release 9b59f78d16fb000ad}
MariaDB [test]> create or replace table t3( id int, row_start bigint as row start, row_end bigint as row end, period for system_time (row_start, row_end) ) with system versioning;
ERROR 4108 (HY000): `row_start` must be of type TIMESTAMP(6) for system-versioned table `t3`
{code}

It took me a while to figure why it wasn't accepting my explicitly defined {{BIGINT}} and insisting on {{TIMESTAMP}} instead; it turns out that I've actually missed {{UNSIGNED}}. While I understand that the server can't guess what the user implied, maybe it could be made better somehow.
```

## Fix commit message(s)

`3d649c6e37de`

```
MDEV-15408 Confusing error message upon ER_VERS_FIELD_WRONG_TYPE while omitting UNSIGNED in BIGINT

Improve diagnostics. Try to guess what type user tried to type.
```

## Files the fix changed

Snapshot holds 3,331 non-test source files. The fix changed 4 file(s); 2 of them are non-test source files (listed below as gold).

- `sql/handler.cc`
- `sql/handler.h`

## The fix diff

### `sql/handler.cc`

```diff
diff --git a/sql/handler.cc b/sql/handler.cc
index 3e1cbc117a9..957e1ba0e19 100644
--- a/sql/handler.cc
+++ b/sql/handler.cc
@@ -7209,12 +7209,13 @@ bool Table_scope_and_contents_source_st::vers_fix_system_fields(
 bool Table_scope_and_contents_source_st::vers_check_system_fields(
        THD *thd, Alter_info *alter_info, const TABLE_LIST &create_table)
 {
   if (!(options & HA_VERSIONED_TABLE))
     return false;
-  return vers_info.check_sys_fields(create_table.table_name, create_table.db,
-                                    alter_info);
+  return vers_info.check_sys_fields(
+      create_table.table_name, create_table.db, alter_info,
+      ha_check_storage_engine_flag(db_type, HTON_NATIVE_SYS_VERSIONING));
 }
 
 
 bool Vers_parse_info::fix_alter_info(THD *thd, Alter_info *alter_info,
                                      HA_CREATE_INFO *create_info, TABLE *table)
@@ -7319,11 +7320,15 @@ bool Vers_parse_info::fix_alter_info(THD *thd, Alter_info *alter_info,
   if (fix_implicit(thd, alter_info))
     return true;
 
   if (alter_info->flags & ALTER_ADD_SYSTEM_VERSIONING)
   {
-    if (check_sys_fields(table_name, share->db, alter_info))
+    const bool can_native=
+        ha_check_storage_engine_flag(create_info->db_type,
+                                     HTON_NATIVE_SYS_VERSIONING) ||
+        create_info->db_type->db_type == DB_TYPE_PARTITION_DB;
+    if (check_sys_fields(table_name, share->db, alter_info, can_native))
       return true;
   }
 
   return false;
 }
@@ -7424,80 +7429,85 @@ bool Vers_parse_info::check_conditions(const Lex_table_name &table_name,
     return true;
   }
   return false;
 }
 
+static bool is_versioning_timestamp(const Create_field *f)
+{
+  return (f->type_handler() == &type_handler_datetime2 ||
+          f->type_handler() == &type_handler_timestamp2) &&
+         f->length == MAX_DATETIME_FULL_WIDTH;
+}
+
+static bool is_some_bigint(const Create_field *f)
+{
+  return f->type_handler() == &type_handler_longlong ||
+         f->type_handler() == &type_handler_vers_trx_id;
+}
+
+static bool is_versioning_bigint(const Create_field *f)
+{
+  return is_some_bigint(f) && f->flags & UNSIGNED_FLAG &&
+         f->length == MY_INT64_NUM_DECIMAL_DIGITS - 1;
+}
+
+static bool require_timestamp(const Create_field *f, Lex_table_name table_name)
+{
+  my_error(ER_VERS_FIELD_WRONG_TYPE, MYF(0), f->field_name.str, "TIMESTAMP(6)",
+           table_name.str);
+  return true;
+}
+static bool require_bigint(const Create_field *f, Lex_table_name table_name)
+{
+  my_error(ER_VERS_FIELD_WRONG_TYPE, MYF(0), f->field_name.str,
+           "BIGINT(20) UNSIGNED", table_name.str);
+  return true;
+}
+
 bool Vers_parse_info::check_sys_fields(const Lex_table_name &table_name,
                                        const Lex_table_name &db,
-                                       Alter_info *alter_info)
+                                       Alter_info *alter_info, bool can_native)
 {
   if (check_conditions(table_name, db))
     return true;
 
+  const Create_field *row_start= NULL;
+  const Create_field *row_end= NULL;
+
   List_iterator<Create_field> it(alter_info->create_list);
-  uint found_flag= 0;
   while (Create_field *f= it++)
   {
-    vers_sys_type_t f_check_unit= VERS_UNDEFINED;
-    uint sys_flag= f->flags & VERS_SYSTEM_FIELD;
+    if (!row_start && f->flags & VERS_SYS_START_FLAG)
+      row_start= f;
+    else if (!row_end && f->flags & VERS_SYS_END_FLAG)
+      row_end= f;
+  }
 
-    if (!sys_flag)
-      continue;
+  const bool expect_timestamp=
+      !can_native || !is_some_bigint(row_start) || !is_some_bigint(row_end);
 
-    if (sys_flag & found_flag)
-    {
-      my_error(ER_VERS_DUPLICATE_ROW_START_END, MYF(0),
-                found_flag & VERS_SYS_START_FLAG ? "START" : "END",
-               f->field_name.str);
-      return true;
-    }
+  if (expect_timestamp)
+  {
+    if (!is_versioning_timestamp(row_start))
+      return require_timestamp(row_start, table_name);
 
-    sys_flag|= found_flag;
+    if (!is_versioning_timestamp(row_end))
+      return require_timestamp(row_end, table_name);
+  }
+  else
+  {
+    if (!is_versioning_bigint(row_start))
+      return require_bigint(row_start, table_name);
 
-    if ((f->type_handler() == &type_handler_datetime2 ||
-          f->type_handler() == &type_handler_timestamp2) &&
-        f->length == MAX_DATETIME_FULL_WIDTH)
-    {
-      f_check_unit= VERS_TIMESTAMP;
-    }
-    else if (f->type_handler() == &type_handler_longlong
-      && (f->flags & UNSIGNED_FLAG)
-      && f->length == (MY_INT64_NUM_DECIMAL_DIGITS - 1))
-    {
-      f_check_unit= VERS_TRX_ID;
-    }
-    else
-    {
-      if (!check_unit)
-        check_unit= VERS_TIMESTAMP;
-      goto error;
-    }
+    if (!is_versioning_bigint(row_end))
+      return require_bigint(row_end, table_name);
+  }
 
-    if (f_check_unit)
-    {
-      if (check_unit)
-      {
-        if (check_unit == f_check_unit)
-        {
-          if (check_unit == VERS_TRX_ID && !TR_table::use_transaction_registry)
-          {
-            my_error(ER_VERS_TRT_IS_DISABLED, MYF(0));
-            return true;
-          }
-          return false;
-        }
-      error:
-        my_error(ER_VERS_FIELD_WRONG_TYPE, MYF(0), f->field_name.str,
-                 check_unit == VERS_TIMESTAMP ?
-                 "TIMESTAMP(6)" :
-                 "BIGINT(20) UNSIGNED",
-                 table_name.str);
-        return true;
-      }
-      check_unit= f_check_unit;
-    }
+  if (is_versioning_bigint(row_start) && is_versioning_bigint(row_end) &&
+      !TR_table::use_transaction_registry)
+  {
+    my_error(ER_VERS_TRT_IS_DISABLED, MYF(0));
+    return true;
   }
 
-  my_error(ER_MISSING, MYF(0), table_name.str, found_flag & VERS_SYS_START_FLAG ?
-           "ROW END" : found_flag ? "ROW START" : "ROW START/END");
-  return true;
+  return false;
 }
```

### `sql/handler.h`

```diff
diff --git a/sql/handler.h b/sql/handler.h
index 1c336e7e35f..2209bd4071c 100644
--- a/sql/handler.h
+++ b/sql/handler.h
@@ -1922,20 +1922,18 @@ enum vers_sys_type_t
 extern const LEX_CSTRING null_clex_str;
 
 struct Vers_parse_info
 {
   Vers_parse_info() :
-    check_unit(VERS_UNDEFINED),
     versioned_fields(false),
     unversioned_fields(false)
   {}
 
   void init() // Deep initialization
   {
     system_time= start_end_t(null_clex_str, null_clex_str);
     as_row= start_end_t(null_clex_str, null_clex_str);
-    check_unit= VERS_UNDEFINED;
     versioned_fields= false;
     unversioned_fields= false;
   }
 
   struct start_end_t
@@ -1949,11 +1947,10 @@ struct Vers_parse_info
     Lex_ident end;
   };
 
   start_end_t system_time;
   start_end_t as_row;
-  vers_sys_type_t check_unit;
 
   void set_system_time(Lex_ident start, Lex_ident end)
   {
     system_time.start= start;
     system_time.end= end;
@@ -1991,11 +1988,11 @@ public:
                        HA_CREATE_INFO *create_info, TABLE *table);
   bool fix_create_like(Alter_info &alter_info, HA_CREATE_INFO &create_info,
                        TABLE_LIST &src_table, TABLE_LIST &table);
   bool check_sys_fields(const Lex_table_name &table_name,
                         const Lex_table_name &db,
-                        Alter_info *alter_info);
+                        Alter_info *alter_info, bool can_native);
 
   /**
      At least one field was specified 'WITH/WITHOUT SYSTEM VERSIONING'.
      Useful for error handling.
   */
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
