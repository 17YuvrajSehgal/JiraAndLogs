# Annotation packet: MDEV-11553  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Can't restore a PERSISTENT column that uses DATE_FORMAT()

I’m in the process of moving to 10.2, starting with slaving to my operational master (10.1.12). So I dumped the master, and started a restore on the 10.2.2 slave.

But the restore fails with:

	ERROR 1901 (HY000) at line 7140: Function or expression 'date_format()' cannot be used in the GENERATED ALWAYS AS clause of `start_day`

I use PERSISTENT columns with the day of the week next to date columns quite heavily. This particular one looks like:

{code:sql}
CREATE TABLE `a_nuke_counts` (
  `time_start` timestamp NOT NULL DEFAULT '0000-00-00 00:00:00',
  `start_day` enum('Sun','Mon','Tue','Wed','Thu','Fri','Sat') AS (DATE_FORMAT(`time_start`, '%a')) PERSISTENT,
  `time_end` timestamp NOT NULL DEFAULT '0000-00-00 00:00:00',
  `end_day` enum('Sun','Mon','Tue','Wed','Thu','Fri','Sat') AS (DATE_FORMAT(`time_end`, '%a')) PERSISTENT,
  `count_start` int(10) unsigned NOT NULL,
  `count_end` int(10) unsigned NOT NULL,
  `location` enum('indoor','outdoor','paper sample') NOT NULL DEFAULT 'indoor',
  `note` varchar(255) NOT NULL
) ENGINE=MyISAM DEFAULT CHARSET=utf8;
{code}
but there are many more.

Should I simply be using VARCHAR(3) instead of ENUM for these? In this case, it's a bug that MDEV 10.1.12 allowed me define and use it as an ENUM.

(Please don’t tell me to use emacs on the 9.1GB dump… :-)

----------------
UPDATE: I just tried executing the above table schema, adding a few records, exporting, DROPping, and importing on MDEV 10.1.12, using Sequel Pro (Mac MySQL GUI). No problem. So it may be a problem with 10.2.2 only. Or perhaps mysqldump.
```

## Fix commit message(s)

`80b9ce359312`

```
MDEV-11553 Can't restore a PERSISTENT column that uses DATE_FORMAT()

3-argument form of DATE_FORMAT
```

## Files the fix changed

Snapshot holds 3,530 non-test source files. The fix changed 16 file(s); 10 of them are non-test source files (listed below as gold).

- `sql/item.cc`
- `sql/item.h`
- `sql/item_create.cc`
- `sql/item_strfunc.cc`
- `sql/item_strfunc.h`
- `sql/item_timefunc.cc`
- `sql/item_timefunc.h`
- `sql/lex.h`
- `sql/sql_yacc.yy`
- `sql/sql_yacc_ora.yy`

## The fix diff

### `sql/item.cc`

```diff
diff --git a/sql/item.cc b/sql/item.cc
index 4a3847f800e..9dcc81bbae7 100644
--- a/sql/item.cc
+++ b/sql/item.cc
@@ -1449,10 +1449,29 @@ bool Item::get_seconds(ulonglong *sec, ulong *sec_part)
   if (!dec)
     return 0;
   return my_decimal2seconds(dec, sec, sec_part);
 }
 
+const MY_LOCALE *Item::locale_from_val_str()
+{
+  StringBuffer<MAX_FIELD_WIDTH> tmp;
+  String *locale_name= val_str_ascii(&tmp);
+  const MY_LOCALE *lc;
+  if (!locale_name ||
+      !(lc= my_locale_by_name(locale_name->c_ptr_safe())))
+  {
+    THD *thd= current_thd;
+    push_warning_printf(thd, Sql_condition::WARN_LEVEL_WARN,
+                        ER_UNKNOWN_LOCALE,
+                        ER_THD(thd, ER_UNKNOWN_LOCALE),
+                        locale_name ? locale_name->c_ptr_safe() : "NULL");
+    lc= &my_locale_en_US;
+  }
+  return lc;
+}
+
+
 CHARSET_INFO *Item::default_charset()
 {
   return current_thd->variables.collation_connection;
 }
```

### `sql/item.h`

```diff
diff --git a/sql/item.h b/sql/item.h
index 3f8ccb88392..04dad5265d3 100644
--- a/sql/item.h
+++ b/sql/item.h
@@ -489,10 +489,12 @@ struct find_selective_predicates_list_processor_data
 {
   TABLE *table;
   List<st_cond_statistic> list;
 };
 
+class MY_LOCALE;
+
 class Item_equal;
 class COND_EQUAL;
 
 class st_select_lex_unit;
 
@@ -642,10 +644,12 @@ public:
     Cache val_str() into the own buffer, e.g. to evaluate constant
     expressions with subqueries in the ORDER/GROUP clauses.
   */
   String *val_str() { return val_str(&str_value); }
 
+  const MY_LOCALE *locale_from_val_str();
+
   LEX_CSTRING name;			/* Name of item */
   /* Original item name (if it was renamed)*/
   const char *orig_name;
   /**
      Intrusive list pointer for free list. If not null, points to the next
```

### `sql/item_create.cc`

```diff
diff --git a/sql/item_create.cc b/sql/item_create.cc
index b0b33041383..5f1485a1336 100644
--- a/sql/item_create.cc
+++ b/sql/item_create.cc
@@ -781,23 +781,10 @@ protected:
   virtual ~Create_func_crosses() {}
 };
 #endif
 
 
-class Create_func_date_format : public Create_func_arg2
-{
-public:
-  virtual Item *create_2_arg(THD *thd, Item *arg1, Item *arg2);
-
-  static Create_func_date_format s_singleton;
-
-protected:
-  Create_func_date_format() {}
-  virtual ~Create_func_date_format() {}
-};
-
-
 class Create_func_datediff : public Create_func_arg2
 {
 public:
   virtual Item *create_2_arg(THD *thd, Item *arg1, Item *arg2);
 
@@ -4049,19 +4036,10 @@ Create_func_crosses::create_2_arg(THD *thd, Item *arg1, Item *arg2)
                                                    Item_func::SP_CROSSES_FUNC);
 }
 #endif
 
 
-Create_func_date_format Create_func_date_format::s_singleton;
-
-Item*
-Create_func_date_format::create_2_arg(THD *thd, Item *arg1, Item *arg2)
-{
-  return new (thd->mem_root) Item_func_date_format(thd, arg1, arg2, 0);
-}
-
-
 Create_func_datediff Create_func_datediff::s_singleton;
 
 Item*
 Create_func_datediff::create_2_arg(THD *thd, Item *arg1, Item *arg2)
 {
@@ -4556,11 +4534,11 @@ Create_func_from_unixtime::create_native(THD *thd, LEX_CSTRING *name,
   case 2:
   {
     Item *param_1= item_list->pop();
     Item *param_2= item_list->pop();
     Item *ut= new (thd->mem_root) Item_func_from_unixtime(thd, param_1);
-    func= new (thd->mem_root) Item_func_date_format(thd, ut, param_2, 0);
+    func= new (thd->mem_root) Item_func_date_format(thd, ut, param_2);
     break;
   }
   default:
   {
     my_error(ER_WRONG_PARAMCOUNT_TO_NATIVE_FCT, MYF(0), name->str);
@@ -6509,11 +6487,11 @@ Create_func_tan::create_1_arg(THD *thd, Item *arg1)
 Create_func_time_format Create_func_time_format::s_singleton;
 
 Item*
 Create_func_time_format::create_2_arg(THD *thd, Item *arg1, Item *arg2)
 {
-  return new (thd->mem_root) Item_func_date_format(thd, arg1, arg2, 1);
+  return new (thd->mem_root) Item_func_time_format(thd, arg1, arg2);
 }
 
 
 Create_func_time_to_sec Create_func_time_to_sec::s_singleton;
 
@@ -6870,11 +6848,10 @@ static Native_func_registry func_array[] =
   { { C_STRING_WITH_LEN("COS") }, BUILDER(Create_func_cos)},
   { { C_STRING_WITH_LEN("COT") }, BUILDER(Create_func_cot)},
   { { C_STRING_WITH_LEN("CRC32") }, BUILDER(Create_func_crc32)},
   { { C_STRING_WITH_LEN("CROSSES") }, GEOM_BUILDER(Create_func_crosses)},
   { { C_STRING_WITH_LEN("DATEDIFF") }, BUILDER(Create_func_datediff)},
-  { { C_STRING_WITH_LEN("DATE_FORMAT") }, BUILDER(Create_func_date_format)},
   { { C_STRING_WITH_LEN("DAYNAME") }, BUILDER(Create_func_dayname)},
   { { C_STRING_WITH_LEN("DAYOFMONTH") }, BUILDER(Create_func_dayofmonth)},
   { { C_STRING_WITH_LEN("DAYOFWEEK") }, BUILDER(Create_func_dayofweek)},
   { { C_STRING_WITH_LEN("DAYOFYEAR") }, BUILDER(Create_func_dayofyear)},
   { { C_STRING_WITH_LEN("DEGREES") }, BUILDER(Create_func_degrees)},
```

### `sql/item_strfunc.cc`

```diff
diff --git a/sql/item_strfunc.cc b/sql/item_strfunc.cc
index 83432f95612..d29e579bcd9 100644
--- a/sql/item_strfunc.cc
+++ b/sql/item_strfunc.cc
@@ -2666,36 +2666,18 @@ String *Item_func_soundex::val_str(String *str)
 */
 
 const int FORMAT_MAX_DECIMALS= 30;
 
 
-MY_LOCALE *Item_func_format::get_locale(Item *item)
-{
-  DBUG_ASSERT(arg_count == 3);
-  String tmp, *locale_name= args[2]->val_str_ascii(&tmp);
-  MY_LOCALE *lc;
-  if (!locale_name ||
-      !(lc= my_locale_by_name(locale_name->c_ptr_safe())))
-  {
-    THD *thd= current_thd;
-    push_warning_printf(thd, Sql_condition::WARN_LEVEL_WARN,
-                        ER_UNKNOWN_LOCALE,
-                        ER_THD(thd, ER_UNKNOWN_LOCALE),
-                        locale_name ? locale_name->c_ptr_safe() : "NULL");
-    lc= &my_locale_en_US;
-  }
-  return lc;
-}
-
 void Item_func_format::fix_length_and_dec()
 {
   uint32 char_length= args[0]->max_char_length();
   uint32 max_sep_count= (char_length / 3) + (decimals ? 1 : 0) + /*sign*/1;
   collation.set(default_charset());
   fix_char_length(char_length + max_sep_count + decimals);
   if (arg_count == 3)
-    locale= args[2]->basic_const_item() ? get_locale(args[2]) : NULL;
+    locale= args[2]->basic_const_item() ? args[2]->locale_from_val_str() : NULL;
   else
     locale= &my_locale_en_US; /* Two arguments */
 }
 
 
@@ -2710,21 +2692,21 @@ String *Item_func_format::val_str_ascii(String *str)
   uint32 str_length;
   /* Number of decimal digits */
   int dec;
   /* Number of characters used to represent the decimals, including '.' */
   uint32 dec_length;
-  MY_LOCALE *lc;
+  const MY_LOCALE *lc;
   DBUG_ASSERT(fixed == 1);
 
   dec= (int) args[1]->val_int();
   if (args[1]->null_value)
   {
     null_value=1;
     return NULL;
   }
 
-  lc= locale ? locale : get_locale(args[2]);
+  lc= locale ? locale : args[2]->locale_from_val_str();
 
   dec= set_zone(dec, 0, FORMAT_MAX_DECIMALS);
   dec_length= dec ? dec+1 : 0;
   null_value=0;
```

### `sql/item_strfunc.h`

```diff
diff --git a/sql/item_strfunc.h b/sql/item_strfunc.h
index a7cad234893..d73bd0b76d7 100644
--- a/sql/item_strfunc.h
+++ b/sql/item_strfunc.h
@@ -25,12 +25,10 @@
 #pragma interface			/* gcc class implementation */
 #endif
 
 extern size_t username_char_length;
 
-class MY_LOCALE;
-
 class Item_str_func :public Item_func
 {
 protected:
   /**
      Sets the result value of the function an empty string, using the current
@@ -930,18 +928,17 @@ public:
 };
 
 
 class Item_func_format :public Item_str_ascii_func
 {
-  MY_LOCALE *locale;
+  const MY_LOCALE *locale;
 public:
   Item_func_format(THD *thd, Item *org, Item *dec):
     Item_str_ascii_func(thd, org, dec) {}
   Item_func_format(THD *thd, Item *org, Item *dec, Item *lang):
     Item_str_ascii_func(thd, org, dec, lang) {}
 
-  MY_LOCALE *get_locale(Item *item);
   String *val_str_ascii(String *);
   void fix_length_and_dec();
   const char *func_name() const { return "format"; }
   Item *get_copy(THD *thd, MEM_ROOT *mem_root)
   { return get_item_copy<Item_func_format>(thd, mem_root, this); }
```

### `sql/item_timefunc.cc`

```diff
diff --git a/sql/item_timefunc.cc b/sql/item_timefunc.cc
index 86bde00cced..189addc767b 100644
--- a/sql/item_timefunc.cc
+++ b/sql/item_timefunc.cc
@@ -453,11 +453,12 @@ err:
 /**
   Create a formated date/time value in a string.
 */
 
 static bool make_date_time(DATE_TIME_FORMAT *format, MYSQL_TIME *l_time,
-                           timestamp_type type, MY_LOCALE *locale, String *str)
+                           timestamp_type type, const MY_LOCALE *locale,
+                           String *str)
 {
   char intbuff[15];
   uint hours_i;
   uint weekday;
   ulong length;
@@ -1831,11 +1832,18 @@ overflow:
 }
 
 void Item_func_date_format::fix_length_and_dec()
 {
   THD* thd= current_thd;
-  locale= thd->variables.lc_time_names;
+  if (!is_time_format)
+  {
+    if (arg_count < 3)
+      locale= thd->variables.lc_time_names;
+    else
+      if (args[2]->basic_const_item())
+        locale= args[2]->locale_from_val_str();
+  }
 
   /*
     Must use this_item() in case it's a local SP variable
     (for ->max_length and ->str_value)
   */
@@ -1873,19 +1881,23 @@ bool Item_func_date_format::eq(const Item *item, bool binary_cmp) const
   if (func_name() != ((Item_func*) item)->func_name())
     return 0;
   if (this == item)
     return 1;
   item_func= (Item_func_date_format*) item;
+  if (arg_count != item_func->arg_count)
+    return 0;
   if (!args[0]->eq(item_func->args[0], binary_cmp))
     return 0;
   /*
     We must compare format string case sensitive.
     This needed because format modifiers with different case,
     for example %m and %M, have different meaning.
   */
   if (!args[1]->eq(item_func->args[1], 1))
     return 0;
+  if (arg_count > 2 && !args[2]->eq(item_func->args[2], 1))
+    return 0;
   return 1;
 }
 
 
 
@@ -1965,19 +1977,22 @@ uint Item_func_date_format::format_length(const String *format)
 String *Item_func_date_format::val_str(String *str)
 {
   String *format;
   MYSQL_TIME l_time;
   uint size;
-  int is_time_flag = is_time_format ? TIME_TIME_ONLY : 0;
+  const MY_LOCALE *lc= 0;
   DBUG_ASSERT(fixed == 1);
   
-  if (get_arg0_date(&l_time, is_time_flag))
+  if (get_arg0_date(&l_time, is_time_format ? TIME_TIME_ONLY : 0))
     return 0;
   
   if (!(format = args[1]->val_str(str)) || !format->length())
     goto null_date;
 
+  if (!is_time_format && !(lc= locale) && !(lc= args[2]->locale_from_val_str()))
+    goto null_date; // invalid locale
+
   if (fixed_length)
     size=max_length;
   else
     size=format_length(format);
 
@@ -1996,11 +2011,11 @@ String *Item_func_date_format::val_str(String *str)
   /* Create the result string */
   str->set_charset(collation.collation);
   if (!make_date_time(&date_time_format, &l_time,
                       is_time_format ? MYSQL_TIMESTAMP_TIME :
                                        MYSQL_TIMESTAMP_DATE,
-                      locale, str))
+                      lc, str))
     return str;
 
 null_date:
   null_value=1;
   return 0;
```

### `sql/item_timefunc.h`

```diff
diff --git a/sql/item_timefunc.h b/sql/item_timefunc.h
index 7d2fe46b644..20ecb4774b3 100644
--- a/sql/item_timefunc.h
+++ b/sql/item_timefunc.h
@@ -795,33 +795,46 @@ public:
 };
 
 
 class Item_func_date_format :public Item_str_func
 {
-  MY_LOCALE *locale;
+  const MY_LOCALE *locale;
   int fixed_length;
-  const bool is_time_format;
   String value;
+protected:
+  bool is_time_format;
 public:
-  Item_func_date_format(THD *thd, Item *a, Item *b, bool is_time_format_arg):
-    Item_str_func(thd, a, b), is_time_format(is_time_format_arg) {}
+  Item_func_date_format(THD *thd, Item *a, Item *b):
+    Item_str_func(thd, a, b), locale(0), is_time_format(false) {}
+  Item_func_date_format(THD *thd, Item *a, Item *b, Item *c):
+    Item_str_func(thd, a, b, c), locale(0), is_time_format(false) {}
   String *val_str(String *str);
-  const char *func_name() const
-    { return is_time_format ? "time_format" : "date_format"; }
+  const char *func_name() const { return "date_format"; }
   void fix_length_and_dec();
   uint format_length(const String *format);
   bool eq(const Item *item, bool binary_cmp) const;
   bool check_vcol_func_processor(void *arg)
   {
-    if (is_time_format)
+    if (arg_count > 2)
       return false;
     return mark_unsupported_function(func_name(), "()", arg, VCOL_SESSION_FUNC);
   }
   Item *get_copy(THD *thd, MEM_ROOT *mem_root)
   { return get_item_copy<Item_func_date_format>(thd, mem_root, this); }
 };
 
+class Item_func_time_format: public Item_func_date_format
+{
+public:
+  Item_func_time_format(THD *thd, Item *a, Item *b):
+    Item_func_date_format(thd, a, b) { is_time_format= true; }
+  const char *func_name() const { return "time_format"; }
+  bool check_vcol_func_processor(void *arg) { return false; }
+  Item *get_copy(THD *thd, MEM_ROOT *mem_root)
+  { return get_item_copy<Item_func_time_format>(thd, mem_root, this); }
+};
+
 
 class Item_func_from_unixtime :public Item_datetimefunc
 {
   Time_zone *tz;
  public:
```

### `sql/lex.h`

```diff
diff --git a/sql/lex.h b/sql/lex.h
index f2dac95fce5..67c3bc8620d 100644
--- a/sql/lex.h
+++ b/sql/lex.h
@@ -724,10 +724,11 @@ static SYMBOL sql_functions[] = {
   { "CUME_DIST",        SYM(CUME_DIST_SYM)},
   { "CURDATE",		SYM(CURDATE)},
   { "CURTIME",		SYM(CURTIME)},
   { "DATE_ADD",		SYM(DATE_ADD_INTERVAL)},
   { "DATE_SUB",		SYM(DATE_SUB_INTERVAL)},
+  { "DATE_FORMAT",      SYM(DATE_FORMAT_SYM)},
   { "DECODE",           SYM(DECODE_SYM)},
   { "DENSE_RANK",       SYM(DENSE_RANK_SYM)},
   { "EXTRACT",		SYM(EXTRACT_SYM)},
   { "FIRST_VALUE",      SYM(FIRST_VALUE_SYM)},
   { "GROUP_CONCAT",	SYM(GROUP_CONCAT_SYM)},
```

### `sql/sql_yacc.yy`

```diff
diff --git a/sql/sql_yacc.yy b/sql/sql_yacc.yy
index 7e89ad91a17..17d6f016b2c 100644
--- a/sql/sql_yacc.yy
+++ b/sql/sql_yacc.yy
@@ -873,11 +873,11 @@ bool my_yyoverflow(short **a, YYSTYPE **b, ulong *yystacksize);
 
 /*
    Comments for TOKENS.
    For each token, please include in the same line a comment that contains
    the following tags:
-   SQL-2011-N : Non Reserved keywird as per SQL-2011
+   SQL-2011-N : Non Reserved keyword as per SQL-2011
    SQL-2003-R : Reserved keyword as per SQL-2003
    SQL-2003-N : Non Reserved keyword as per SQL-2003
    SQL-1999-R : Reserved keyword as per SQL-1999
    SQL-1999-N : Non Reserved keyword as per SQL-1999
    MYSQL      : MySQL extention (unspecified)
@@ -1008,10 +1008,11 @@ bool my_yyoverflow(short **a, YYSTYPE **b, ulong *yystacksize);
 %token  DATABASES
 %token  DATAFILE_SYM
 %token  DATA_SYM                      /* SQL-2003-N */
 %token  DATETIME
 %token  DATE_ADD_INTERVAL             /* MYSQL-FUNC */
+%token  DATE_FORMAT_SYM               /* MYSQL-FUNC */
 %token  DATE_SUB_INTERVAL             /* MYSQL-FUNC */
 %token  DATE_SYM                      /* SQL-2003-R */
 %token  DAY_HOUR_SYM
 %token  DAY_MICROSECOND_SYM
 %token  DAY_MINUTE_SYM
@@ -9804,10 +9805,22 @@ function_call_nonkeyword:
           {
             $$= new (thd->mem_root) Item_date_add_interval(thd, $3, $6, $7, 1);
             if ($$ == NULL)
               MYSQL_YYABORT;
           }
+        | DATE_FORMAT_SYM '(' expr ',' expr ')'
+          {
+            $$= new (thd->mem_root) Item_func_date_format(thd, $3, $5);
+            if ($$ == NULL)
+              MYSQL_YYABORT;
+          }
+        | DATE_FORMAT_SYM '(' expr ',' expr ',' expr ')'
+          {
+            $$= new (thd->mem_root) Item_func_date_format(thd, $3, $5, $7);
+            if ($$ == NULL)
+              MYSQL_YYABORT;
+          }
         | DECODE_SYM '(' expr ',' expr ')'
           {
             $$= new (thd->mem_root) Item_func_decode(thd, $3, $5);
             if ($$ == NULL)
               MYSQL_YYABORT;
@@ -14717,10 +14730,11 @@ keyword_sp_not_data_type:
         | CURRENT_SYM              {}
         | CURSOR_NAME_SYM          {}
         | CYCLE_SYM                {}
         | DATA_SYM                 {}
         | DATAFILE_SYM             {}
+        | DATE_FORMAT_SYM          {}
         | DAY_SYM                  {}
         | DECODE_SYM               {}
         | DEFINER_SYM              {}
         | DELAY_KEY_WRITE_SYM      {}
         | DES_KEY_FILE             {}
```

### `sql/sql_yacc_ora.yy`

```diff
diff --git a/sql/sql_yacc_ora.yy b/sql/sql_yacc_ora.yy
index 8d250abd994..052c219a7a4 100644
--- a/sql/sql_yacc_ora.yy
+++ b/sql/sql_yacc_ora.yy
@@ -282,11 +282,11 @@ bool my_yyoverflow(short **a, YYSTYPE **b, ulong *yystacksize);
 
 /*
    Comments for TOKENS.
    For each token, please include in the same line a comment that contains
    the following tags:
-   SQL-2011-N : Non Reserved keywird as per SQL-2011
+   SQL-2011-N : Non Reserved keyword as per SQL-2011
    SQL-2003-R : Reserved keyword as per SQL-2003
    SQL-2003-N : Non Reserved keyword as per SQL-2003
    SQL-1999-R : Reserved keyword as per SQL-1999
    SQL-1999-N : Non Reserved keyword as per SQL-1999
    MYSQL      : MySQL extention (unspecified)
@@ -417,10 +417,11 @@ bool my_yyoverflow(short **a, YYSTYPE **b, ulong *yystacksize);
 %token  DATABASES
 %token  DATAFILE_SYM
 %token  DATA_SYM                      /* SQL-2003-N */
 %token  DATETIME
 %token  DATE_ADD_INTERVAL             /* MYSQL-FUNC */
+%token  DATE_FORMAT_SYM               /* MYSQL-FUNC */
 %token  DATE_SUB_INTERVAL             /* MYSQL-FUNC */
 %token  DATE_SYM                      /* SQL-2003-R */
 %token  DAY_HOUR_SYM
 %token  DAY_MICROSECOND_SYM
 %token  DAY_MINUTE_SYM
@@ -9460,10 +9461,22 @@ column_default_non_parenthesized_expr:
           {
             $$= new (thd->mem_root) Item_func_conv_charset(thd, $3, $5);
             if ($$ == NULL)
               MYSQL_YYABORT;
           }
+        | DATE_FORMAT_SYM '(' expr ',' expr ')'
+          {
+            $$= new (thd->mem_root) Item_func_date_format(thd, $3, $5);
+            if ($$ == NULL)
+              MYSQL_YYABORT;
+          }
+        | DATE_FORMAT_SYM '(' expr ',' expr ',' expr ')'
+          {
+            $$= new (thd->mem_root) Item_func_date_format(thd, $3, $5, $7);
+            if ($$ == NULL)
+              MYSQL_YYABORT;
+          }
         | DECODE_SYM '(' expr ',' decode_when_list ')'
           {
             $5->push_front($3, thd->mem_root);
             if (!($$= new (thd->mem_root) Item_func_decode_oracle(thd, *$5)))
               MYSQL_YYABORT;
@@ -14891,10 +14904,11 @@ keyword_sp_not_data_type:
         | CURRENT_SYM              {}
         | CURSOR_NAME_SYM          {}
         | CYCLE_SYM                {}
         | DATA_SYM                 {}
         | DATAFILE_SYM             {}
+        | DATE_FORMAT_SYM          {}
         | DAY_SYM                  {}
         | DECODE_SYM               {}
         | DEFINER_SYM              {}
         | DELAY_KEY_WRITE_SYM      {}
         | DES_KEY_FILE             {}
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
