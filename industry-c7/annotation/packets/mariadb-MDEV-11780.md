# Annotation packet: MDEV-11780  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Crash with PREPARE + SP out parameter + literal

This script:
{code:sql}
DELIMITER $$
CREATE OR REPLACE PROCEDURE p1(OUT a INT)
BEGIN
  SET a= 10;
END;
$$
DELIMITER ;
PREPARE stmt FROM 'CALL p1(?)';
EXECUTE stmt USING 10;
{code}
crashes with the following stack trace:
{noformat}
#0  0x00007ffff5994a28 in raise () from /lib64/libc.so.6
#1  0x00007ffff599662a in abort () from /lib64/libc.so.6
#2  0x00007ffff598d227 in __assert_fail_base () from /lib64/libc.so.6
#3  0x00007ffff598d2d2 in __assert_fail () from /lib64/libc.so.6
#4  0x0000555555a2a58c in Protocol_text::send_out_parameters (
    this=0x7ffeb1016600, sp_params=0x7ffeb110def8)
    at /home/bar/maria-git/server.10.2/sql/protocol.cc:1326
#5  0x0000555555b1a2fd in Prepared_statement::execute (this=0x7ffeb101da70, 
    expanded_query=0x7ffff7f2f0c0, open_cursor=false)
    at /home/bar/maria-git/server.10.2/sql/sql_prepare.cc:4698
#6  0x0000555555b184c8 in Prepared_statement::execute_loop (
    this=0x7ffeb101da70, expanded_query=0x7ffff7f2f0c0, open_cursor=false, 
    packet=0x0, packet_end=0x0)
    at /home/bar/maria-git/server.10.2/sql/sql_prepare.cc:4083
#7  0x0000555555b16246 in mysql_sql_stmt_execute (thd=0x7ffeb1016070)
    at /home/bar/maria-git/server.10.2/sql/sql_prepare.cc:3193
#8  0x0000555555aef38f in mysql_execute_command (thd=0x7ffeb1016070)
    at /home/bar/maria-git/server.10.2/sql/sql_parse.cc:3445
#9  0x0000555555afcf83 in mysql_parse (thd=0x7ffeb1016070, 
    rawbuf=0x7ffeb1063088 "EXECUTE stmt USING 10", length=21, 
    parser_state=0x7ffff7f2fd20, is_com_multi=false, is_next_command=false)
{noformat}

{noformat}
mysqld: /data/src/10.2/sql/protocol.cc:1326: virtual Protocol_text::send_out_parameters(List<Item_param>*): Assertion `0' failed.
170112 12:44:08 [ERROR] mysqld got signal 6 ;
{noformat}
```

## Fix commit message(s)

`ae91690d893c`

```
MDEV-11780 Crash with PREPARE + SP out parameter + literal

Before "MDEV-10709 Expressions as parameters to Dynamic SQL" only
user variables were syntactically allowed as EXECUTE parameters.
User variables were OK as both IN and OUT parameters.
When Item_param was bound to an actual parameter (a user variable),
it automatically meant that the bound Item was settable.
The DBUG_ASSERT() in Protocol_text::send_out_parameters() guarded that
the actual parameter is really settable.

After MDEV-10709, any kind of expressions are allowed as EXECUTE IN parameters.
But the patch for MDEV-10709 forgot to check that only descendants of
Settable_routine_parameter should be allowed as OUT parameters.
So an attempt to pass a non-settable parameter as an OUT parameter
made server crash on the above mentioned DBUG_ASSERT.

This patch changes Item_param::get_settable_routine_parameter(),
which previously always returned "this". Now, when Item_param is bound
to some Item, it caches if the bound Item is settable.
Item_param::get_settable_routine_parameter() now returns "this" only
if the bound actual parameter is settable, and returns NULL otherwise.
```

## Files the fix changed

Snapshot holds 3,348 non-test source files. The fix changed 4 file(s); 2 of them are non-test source files (listed below as gold).

- `sql/item.cc`
- `sql/item.h`

## The fix diff

### `sql/item.cc`

```diff
diff --git a/sql/item.cc b/sql/item.cc
index bab49115482..369b2df2675 100644
--- a/sql/item.cc
+++ b/sql/item.cc
@@ -3311,11 +3311,19 @@ Item_param::Item_param(THD *thd, uint pos_in_query_arg):
   state(NO_VALUE),
   /* Don't pretend to be a literal unless value for this item is set. */
   item_type(PARAM_ITEM),
   indicators(0), indicator(STMT_INDICATOR_NONE),
   set_param_func(default_set_param_func),
-  m_out_param_info(NULL)
+  m_out_param_info(NULL),
+  /*
+    Set m_is_settable_routine_parameter to "true" by default.
+    This is needed for client-server protocol,
+    whose parameters are always settable.
+    For dynamic SQL, settability depends on the type of Item passed
+    as an actual parameter. See Item_param::set_from_item().
+  */
+  m_is_settable_routine_parameter(true)
 {
   name= (char*) "?";
   /* 
     Since we can't say whenever this item can be NULL or cannot be NULL
     before mysql_stmt_execute(), so we assuming that it can be NULL until
@@ -3555,10 +3563,11 @@ bool Item_param::CONVERSION_INFO::convert(THD *thd, String *str)
 */
 
 bool Item_param::set_from_item(THD *thd, Item *item)
 {
   DBUG_ENTER("Item_param::set_from_item");
+  m_is_settable_routine_parameter= item->get_settable_routine_parameter();
   if (limit_clause_param)
   {
     longlong val= item->val_int();
     if (item->null_value)
     {
@@ -4130,10 +4139,11 @@ Item_param::set_param_type_and_swap_value(Item_param *src)
 }
 
 
 void Item_param::set_default()
 {
+  m_is_settable_routine_parameter= false;
   state= DEFAULT_VALUE;
   fixed= true;
   /*
     When Item_param is set to DEFAULT_VALUE:
     - its val_str() and val_decimal() return NULL
@@ -4145,10 +4155,11 @@ void Item_param::set_default()
   null_value= true;
 }
 
 void Item_param::set_ignore()
 {
+  m_is_settable_routine_parameter= false;
   state= IGNORE_VALUE;
   fixed= true;
   null_value= true;
 }
```

### `sql/item.h`

```diff
diff --git a/sql/item.h b/sql/item.h
index f9efd104b04..bb2f05b4c6d 100644
--- a/sql/item.h
+++ b/sql/item.h
@@ -2980,11 +2980,11 @@ public:
   void set_param_type_and_swap_value(Item_param *from);
 
   Rewritable_query_parameter *get_rewritable_query_parameter()
   { return this; }
   Settable_routine_parameter *get_settable_routine_parameter()
-  { return this; }
+  { return m_is_settable_routine_parameter ? this : NULL; }
 
   bool append_for_log(THD *thd, String *str);
   bool check_vcol_func_processor(void *int_arg) {return FALSE;}
   Item *get_copy(THD *thd, MEM_ROOT *mem_root) { return 0; }
 
@@ -3000,10 +3000,11 @@ public:
 
   virtual void make_field(THD *thd, Send_field *field);
 
 private:
   Send_field *m_out_param_info;
+  bool m_is_settable_routine_parameter;
 };
 
 
 class Item_int :public Item_num
 {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
