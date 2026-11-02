# Annotation packet: MDEV-20831  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Table partitioned by LIST/RANGE COLUMNS(inet6) can be created, but not inserted into

{code:sql}
create or replace table t1 (a inet6) partition by list columns(a) (partition p1 values in ('::'));
insert into t1 values ('::');
{code}
{code:sql|title=10.5 fa843790}
> insert into t1 values ('::');
ERROR 1654 (HY000): Partition column values of incorrect type
{code}

I am not sure whether such partitioning is supposed to be supported. Since it works for {{BINARY}} and {{CHAR}}, I would expect yes; but if it doesn't work, it should be failing upon table creation, like with other data types:

{code:sql}
> create or replace table t1 (a decimal) partition by list columns(a) (partition p1 values in (0));
ERROR 1659 (HY000): Field 'a' is of a not allowed type for this type of partitioning
{code}
```

## Fix commit message(s)

`22b645ef5292`

```
MDEV-20831 Table partitioned by LIST/RANGE COLUMNS(inet6) can be created, but not inserted into

This clause in CREATE TABLE:

  PARTITION BY LIST COLUMNS (inet6column)
    (PARTITION p1 VALUES IN ('::'))

was erroneously written to frm file as:

  PARTITION BY LIST COLUMNS(inet6column)
    (PARTITION p1 VALUES IN (_binary 0x3A3A))

I.e. the text value '::' was converted to HEX representation
and prefixed with _binary.

A simple fix could write `_latin1 0x3A3A` instead of `_binary 0x3A3A`,
but in case of INET6 we don't need neither character set introducers,
nor HEX encoding, because text representation of INET6 values consist
of pure ASCII characters.

So this patch changes the above clause to be printed as:

  PARTITION BY LIST COLUMNS(inet6column)
    (PARTITION p1 VALUES IN ('::'))

Details:

The old code in check_part_field() was not friendly to pluggable data types.
Replacing this function to two new virtual methods in Type_handler:

  virtual bool partition_field_check(const LEX_CSTRING &field_name,
                                     Item *item_expr) const;

  virtual bool partition_field_append_value(String *str,
                                            Item *item_expr,
                                            CHARSET_INFO *field_cs,
                                            partition_value_print_mode_t mode)
                                            const;

so data type plugins can decide whether they need to use character set
introducer and/or hex encoding when printing partition values.
```

## Files the fix changed

Snapshot holds 3,286 non-test source files. The fix changed 6 file(s); 4 of them are non-test source files (listed below as gold).

- `plugin/type_inet/sql_type_inet.cc`
- `plugin/type_inet/sql_type_inet.h`
- `sql/sql_partition.cc`
- `sql/sql_type.h`

## The fix diff

### `plugin/type_inet/sql_type_inet.cc`

```diff
diff --git a/plugin/type_inet/sql_type_inet.cc b/plugin/type_inet/sql_type_inet.cc
index d6c6703aaa3..0502cde4f7b 100644
--- a/plugin/type_inet/sql_type_inet.cc
+++ b/plugin/type_inet/sql_type_inet.cc
@@ -1447,10 +1447,44 @@ Field *Type_handler_inet6::make_conversion_table_field(MEM_ROOT *root,
   const Record_addr tmp(NULL, Bit_addr(true));
   return new (table->in_use->mem_root) Field_inet6(&empty_clex_str, tmp);
 }
 
 
+bool Type_handler_inet6::partition_field_check(const LEX_CSTRING &field_name,
+                                               Item *item_expr) const
+{
+  if (item_expr->cmp_type() != STRING_RESULT)
+  {
+    my_error(ER_WRONG_TYPE_COLUMN_VALUE_ERROR, MYF(0));
+    return true;
+  }
+  return false;
+}
+
+
+bool
+Type_handler_inet6::partition_field_append_value(
+                                          String *to,
+                                          Item *item_expr,
+                                          CHARSET_INFO *field_cs,
+                                          partition_value_print_mode_t mode)
+                                          const
+{
+  StringBufferInet6 inet6str;
+  Inet6_null inet6(item_expr);
+  if (inet6.is_null())
+  {
+    my_error(ER_PARTITION_FUNCTION_IS_NOT_ALLOWED, MYF(0));
+    return true;
+  }
+  return inet6.to_string(&inet6str) ||
+         to->append('\'') ||
+         to->append(inet6str) ||
+         to->append('\'');
+}
+
+
 /***************************************************************/
 
 
 class Type_collection_inet: public Type_collection
 {
```

### `plugin/type_inet/sql_type_inet.h`

```diff
diff --git a/plugin/type_inet/sql_type_inet.h b/plugin/type_inet/sql_type_inet.h
index c00237cf4fc..430f7ec30c0 100644
--- a/plugin/type_inet/sql_type_inet.h
+++ b/plugin/type_inet/sql_type_inet.h
@@ -476,10 +476,19 @@ public:
   {
     def->pack_flag= FIELDFLAG_BINARY;
     return false;
   }
 
+  bool partition_field_check(const LEX_CSTRING &field_name,
+                             Item *item_expr) const override;
+
+  bool partition_field_append_value(String *to,
+                                    Item *item_expr,
+                                    CHARSET_INFO *field_cs,
+                                    partition_value_print_mode_t mode)
+                                    const override;
+
   Field *make_table_field(MEM_ROOT *root,
                           const LEX_CSTRING *name,
                           const Record_addr &addr,
                           const Type_all_attributes &attr,
                           TABLE_SHARE *table) const override;
```

### `sql/sql_partition.cc`

```diff
diff --git a/sql/sql_partition.cc b/sql/sql_partition.cc
index 802e62585d4..d95b14c437c 100644
--- a/sql/sql_partition.cc
+++ b/sql/sql_partition.cc
@@ -2238,81 +2238,37 @@ static int add_partition_options(String *str, partition_element *p_elem)
                          ha_resolve_storage_engine_name(p_elem->engine_type));
   return err;
 }
 
 
-/*
-  Check partition fields for result type and if they need
-  to check the character set.
-
-  SYNOPSIS
-    check_part_field()
-    sql_type              Type provided by user
-    field_name            Name of field, used for error handling
-    result_type           Out value: Result type of field
-    need_cs_check         Out value: Do we need character set check
+void
+Type_handler::partition_field_type_not_allowed(const LEX_CSTRING &field_name)
+{
+  my_error(ER_FIELD_TYPE_NOT_ALLOWED_AS_PARTITION_FIELD, MYF(0),
+           field_name.str);
+}
 
-  RETURN VALUES
-    TRUE                  Error
-    FALSE                 Ok
-*/
 
-static int check_part_field(enum_field_types sql_type,
-                            const char *field_name,
-                            Item_result *result_type,
-                            bool *need_cs_check)
+bool
+Type_handler::partition_field_check_result_type(Item *item,
+                                                Item_result expected_type)
 {
-  if (sql_type >= MYSQL_TYPE_TINY_BLOB &&
-      sql_type <= MYSQL_TYPE_BLOB)
+  if (item->result_type() != expected_type)
   {
-    my_error(ER_BLOB_FIELD_IN_PART_FUNC_ERROR, MYF(0));
+    my_error(ER_WRONG_TYPE_COLUMN_VALUE_ERROR, MYF(0));
     return TRUE;
   }
-  switch (sql_type)
-  {
-    case MYSQL_TYPE_TINY:
-    case MYSQL_TYPE_SHORT:
-    case MYSQL_TYPE_LONG:
-    case MYSQL_TYPE_LONGLONG:
-    case MYSQL_TYPE_INT24:
-      *result_type= INT_RESULT;
-      *need_cs_check= FALSE;
-      return FALSE;
-    case MYSQL_TYPE_NEWDATE:
-    case MYSQL_TYPE_DATE:
-    case MYSQL_TYPE_TIME:
-    case MYSQL_TYPE_DATETIME:
-    case MYSQL_TYPE_TIME2:
-    case MYSQL_TYPE_DATETIME2:
-      *result_type= STRING_RESULT;
-      *need_cs_check= TRUE;
-      return FALSE;
-    case MYSQL_TYPE_VARCHAR:
-    case MYSQL_TYPE_STRING:
-    case MYSQL_TYPE_VAR_STRING:
-      *result_type= STRING_RESULT;
-      *need_cs_check= TRUE;
-      return FALSE;
-    case MYSQL_TYPE_NEWDECIMAL:
-    case MYSQL_TYPE_DECIMAL:
-    case MYSQL_TYPE_TIMESTAMP:
-    case MYSQL_TYPE_TIMESTAMP2:
-    case MYSQL_TYPE_NULL:
-    case MYSQL_TYPE_FLOAT:
-    case MYSQL_TYPE_DOUBLE:
-    case MYSQL_TYPE_BIT:
-    case MYSQL_TYPE_ENUM:
-    case MYSQL_TYPE_SET:
-    case MYSQL_TYPE_GEOMETRY:
-      goto error;
-    default:
-      goto error;
-  }
-error:
-  my_error(ER_FIELD_TYPE_NOT_ALLOWED_AS_PARTITION_FIELD, MYF(0),
-           field_name);
-  return TRUE;
+  return false;
+}
+
+
+bool
+Type_handler_blob_common::partition_field_check(const LEX_CSTRING &field_name,
+                                                Item *item_expr) const
+{
+  my_error(ER_BLOB_FIELD_IN_PART_FUNC_ERROR, MYF(0));
+  return true;
 }
 
 
 /*
   Find the given field's Create_field object using name of field
@@ -2345,10 +2301,62 @@ static Create_field* get_sql_field(const char *field_name,
   }
   DBUG_RETURN(NULL);
 }
 
 
+bool
+Type_handler_general_purpose_int::partition_field_append_value(
+                                            String *str,
+                                            Item *item_expr,
+                                            CHARSET_INFO *field_cs,
+                                            partition_value_print_mode_t mode)
+                                            const
+{
+  DBUG_ASSERT(item_expr->cmp_type() == INT_RESULT);
+  StringBuffer<21> tmp;
+  longlong value= item_expr->val_int();
+  tmp.set(value, system_charset_info);
+  return str->append(tmp);
+}
+
+
+bool Type_handler::partition_field_append_value(
+                                            String *str,
+                                            Item *item_expr,
+                                            CHARSET_INFO *field_cs,
+                                            partition_value_print_mode_t mode)
+                                            const
+{
+  DBUG_ASSERT(cmp_type() != INT_RESULT);
+
+  if (field_cs && field_cs != item_expr->collation.collation)
+  {
+    if (!(item_expr= convert_charset_partition_constant(item_expr,
+                                                        field_cs)))
+    {
+      my_error(ER_PARTITION_FUNCTION_IS_NOT_ALLOWED, MYF(0));
+      return true;
+    }
+  }
+  StringBuffer<MAX_KEY_LENGTH> buf;
+  String val_conv, *res;
+  val_conv.set_charset(system_charset_info);
+  if (!(res= item_expr->val_str(&buf)))
+  {
+    my_error(ER_PARTITION_FUNCTION_IS_NOT_ALLOWED, MYF(0));
+    return true;
+  }
+  if (get_cs_converted_part_value_from_string(current_thd,
+                                              item_expr, res,
+                                              &val_conv, field_cs,
+                                              mode ==
+                                              PARTITION_VALUE_PRINT_MODE_FRM))
+    return true;
+  return str->append(val_conv);
+}
+
+
 static int add_column_list_values(String *str, partition_info *part_info,
                                   part_elem_value *list_value,
                                   HA_CREATE_INFO *create_info,
                                   Alter_info *alter_info)
 {
@@ -2375,12 +2383,11 @@ static int add_column_list_values(String *str, partition_info *part_info,
       if (item_expr->null_value)
         err+= str->append(STRING_WITH_LEN("NULL"));
       else
       {
         CHARSET_INFO *field_cs;
-        bool need_cs_check= FALSE;
-        Item_result result_type= STRING_RESULT;
+        const Type_handler *th= NULL;
 
         /*
           This function is called at a very early stage, even before
           we have prepared the sql_field objects. Thus we have to
           find the proper sql_field object and get the character set
@@ -2394,61 +2401,28 @@ static int add_column_list_values(String *str, partition_info *part_info,
                                          alter_info)))
           {
             my_error(ER_FIELD_NOT_FOUND_PART_ERROR, MYF(0));
             return 1;
           }
-          if (check_part_field(sql_field->real_field_type(),
-                               sql_field->field_name.str,
-                               &result_type,
-                               &need_cs_check))
+          th= sql_field->type_handler();
+          if (th->partition_field_check(sql_field->field_name, item_expr))
             return 1;
-          if (need_cs_check)
-            field_cs= get_sql_field_charset(sql_field, create_info);
-          else
-            field_cs= NULL;
+          field_cs= get_sql_field_charset(sql_field, create_info);
         }
         else
         {
           Field *field= part_info->part_field_array[i];
-          result_type= field->result_type();
-          if (check_part_field(field->real_type(),
-                               field->field_name.str,
-                               &result_type,
-                               &need_cs_check))
+          th= field->type_handler();
+          if (th->partition_field_check(field->field_name, item_expr))
             return 1;
-          DBUG_ASSERT(result_type == field->result_type());
-          if (need_cs_check)
-            field_cs= field->charset();
-          else
-            field_cs= NULL;
+          field_cs= field->charset();
         }
-        if (result_type != item_expr->result_type())
-        {
-          my_error(ER_WRONG_TYPE_COLUMN_VALUE_ERROR, MYF(0));
+        if (th->partition_field_append_value(str, item_expr, field_cs,
+                                             alter_info == NULL ?
+                                             PARTITION_VALUE_PRINT_MODE_SHOW:
+                                             PARTITION_VALUE_PRINT_MODE_FRM))
           return 1;
-        }
-        if (field_cs && field_cs != item_expr->collation.collation)
-        {
-          if (!(item_expr= convert_charset_partition_constant(item_expr,
-                                                              field_cs)))
-          {
-            my_error(ER_PARTITION_FUNCTION_IS_NOT_ALLOWED, MYF(0));
-            return 1;
-          }
-        }
-        {
-          StringBuffer<MAX_KEY_LENGTH> buf;
-          String val_conv, *res;
-          val_conv.set_charset(system_charset_info);
-          res= item_expr->val_str(&buf);
-          if (get_cs_converted_part_value_from_string(current_thd,
-                                                      item_expr, res,
-                                                      &val_conv, field_cs,
-                                                   (bool)(alter_info != NULL)))
-            return 1;
-          err+= str->append(val_conv);
-        }
       }
     }
     if (i != (num_elements - 1))
       err+= str->append(',');
   }
```

### `sql/sql_type.h`

```diff
diff --git a/sql/sql_type.h b/sql/sql_type.h
index 54356c09b09..d8ed51bfea1 100644
--- a/sql/sql_type.h
+++ b/sql/sql_type.h
@@ -117,10 +117,17 @@ enum scalar_comparison_op
   SCALAR_CMP_GE,
   SCALAR_CMP_GT
 };
 
 
+enum partition_value_print_mode_t
+{
+  PARTITION_VALUE_PRINT_MODE_SHOW= 0,
+  PARTITION_VALUE_PRINT_MODE_FRM= 1
+};
+
+
 class Data_type_statistics
 {
 public:
   uint m_uneven_bit_length;
   uint m_fixed_string_total_length;
@@ -3355,11 +3362,13 @@ public:
                                     const Type_handler *h2);
   virtual const Type_collection *type_collection() const;
   static const
   Type_handler *aggregate_for_result_traditional(const Type_handler *h1,
                                                  const Type_handler *h2);
-
+  static void partition_field_type_not_allowed(const LEX_CSTRING &field_name);
+  static bool partition_field_check_result_type(Item *item,
+                                                Item_result expected_type);
   virtual const Name name() const= 0;
   virtual const Name version() const;
   virtual const Name &default_value() const= 0;
   virtual uint32 flags() const { return 0; }
   virtual ulong KEY_pack_flags(uint column_nr) const { return 0; }
@@ -3493,10 +3502,21 @@ public:
   }
   virtual const Type_handler *type_handler_signed() const
   {
     return this;
   }
+  virtual bool partition_field_check(const LEX_CSTRING &field_name,
+                                     Item *item_expr) const
+  {
+    partition_field_type_not_allowed(field_name);
+    return true;
+  }
+  virtual bool partition_field_append_value(String *str,
+                                            Item *item_expr,
+                                            CHARSET_INFO *field_cs,
+                                            partition_value_print_mode_t mode)
+                                            const;
   virtual int
   stored_field_cmp_to_item(THD *thd, Field *field, Item *item) const= 0;
   virtual CHARSET_INFO *charset_for_protocol(const Item *item) const;
   virtual const Type_handler*
   type_handler_adjusted_to_max_octet_length(uint max_octet_length,
@@ -4863,10 +4883,20 @@ public:
   virtual const Type_limits_int *type_limits_int() const= 0;
   uint32 max_display_length(const Item *item) const override
   {
     return type_limits_int()->char_length();
   }
+  bool partition_field_check(const LEX_CSTRING &field_name,
+                             Item *item_expr) const override
+  {
+    return partition_field_check_result_type(item_expr, INT_RESULT);
+  }
+  bool partition_field_append_value(String *str,
+                                    Item *item_expr,
+                                    CHARSET_INFO *field_cs,
+                                    partition_value_print_mode_t)
+                                    const override;
   const Vers_type_handler *vers() const override { return &vers_type_trx; }
 };
 
 
 class Type_handler_temporal_result: public Type_handler
@@ -5657,10 +5687,15 @@ public:
   }
   enum_mysql_timestamp_type mysql_timestamp_type() const override
   {
     return MYSQL_TIMESTAMP_TIME;
   }
+  bool partition_field_check(const LEX_CSTRING &field_name,
+                             Item *item_expr) const override
+  {
+    return partition_field_check_result_type(item_expr, STRING_RESULT);
+  }
   Field *make_schema_field(MEM_ROOT *root,
                            TABLE *table,
                            const Record_addr &addr,
                            const ST_FIELD_INFO &def,
                            bool show_field) const override;
@@ -5863,10 +5898,15 @@ public:
   }
   bool cond_notnull_field_isnull_to_field_eq_zero() const override
   {
     return true;
   }
+  bool partition_field_check(const LEX_CSTRING &field_name,
+                             Item *item_expr) const override
+  {
+    return partition_field_check_result_type(item_expr, STRING_RESULT);
+  }
   Field *make_schema_field(MEM_ROOT *root,
                            TABLE *table,
                            const Record_addr &addr,
                            const ST_FIELD_INFO &def,
                            bool show_field) const override;
@@ -5985,10 +6025,15 @@ public:
   }
   bool cond_notnull_field_isnull_to_field_eq_zero() const override
   {
     return true;
   }
+  bool partition_field_check(const LEX_CSTRING &field_name,
+                             Item *item_expr) const override
+  {
+    return partition_field_check_result_type(item_expr, STRING_RESULT);
+  }
   Field *make_schema_field(MEM_ROOT *root,
                            TABLE *table,
                            const Record_addr &addr,
                            const ST_FIELD_INFO &def,
                            bool show_field) const override;
@@ -6430,10 +6475,15 @@ public:
   uint32 calc_pack_length(uint32 length) const override { return length; }
   const Type_handler *type_handler_for_tmp_table(const Item *item) const override
   {
     return varstring_type_handler(item);
   }
+  bool partition_field_check(const LEX_CSTRING &field_name,
+                             Item *item_expr) const override
+  {
+    return partition_field_check_result_type(item_expr, STRING_RESULT);
+  }
   void show_binlog_type(const Conv_source &src, const Field &dst, String *str)
     const override;
   Field *make_conversion_table_field(MEM_ROOT *root,
                                      TABLE *table, uint metadata,
                                      const Field *target) const override;
@@ -6518,10 +6568,15 @@ public:
   const Type_handler *type_handler_for_union(const Item *item) const override
   {
     return varstring_type_handler(item);
   }
   bool is_param_long_data_type() const override { return true; }
+  bool partition_field_check(const LEX_CSTRING &field_name,
+                             Item *item_expr) const override
+  {
+    return partition_field_check_result_type(item_expr, STRING_RESULT);
+  }
   void show_binlog_type(const Conv_source &src, const Field &dst, String *str)
     const override;
   Field *make_conversion_table_field(MEM_ROOT *root,
                                      TABLE *table, uint metadata,
                                      const Field *target) const override;
@@ -6572,10 +6627,16 @@ public:
   {
     DBUG_ASSERT(0);
     return 0;
   }
   uint32 max_display_length_for_field(const Conv_source &src) const override;
+  bool partition_field_check(const LEX_CSTRING &field_name,
+                             Item *item_expr) const override
+  {
+    partition_field_type_not_allowed(field_name);
+    return true;
+  }
   void show_binlog_type(const Conv_source &src, const Field &dst, String *str)
     const override;
   Field *make_conversion_table_field(MEM_ROOT *root,
                                      TABLE *table, uint metadata,
                                      const Field *target) const override;
@@ -6646,10 +6707,12 @@ public:
                                        Type_all_attributes *atrr,
                                        Item **items, uint nitems) const
     override;
   void Item_param_setup_conversion(THD *thd, Item_param *) const override;
 
+  bool partition_field_check(const LEX_CSTRING &field_name,
+                        Item *item_expr) const override;
   Field *make_schema_field(MEM_ROOT *root,
                            TABLE *table,
                            const Record_addr &addr,
                            const ST_FIELD_INFO &def,
                            bool show_field) const override;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
