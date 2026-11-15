# Annotation packet: MDEV-17354  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Server crashes in add_key_field / .. / Item_func_null_predicate::add_key_fields upon INSERT .. SELECT

{code:sql}
CREATE TABLE t1 (f INT NOT NULL AUTO_INCREMENT PRIMARY KEY);
CREATE ALGORITHM = MERGE VIEW v1 AS SELECT * FROM ( SELECT * FROM t1 ) AS sq;
INSERT INTO t1 SELECT * FROM ( SELECT t1.f FROM v1 JOIN t1 ) AS sq WHERE f IS NOT NULL;
{code}
{noformat:title=10.2 b4e841648c}
#3  <signal handler called>
#4  0x000055b6de65a492 in Bitmap<64u>::merge (this=0x1b0, map2=...) at /data/src/10.2/sql/sql_bitmap.h:196
#5  0x000055b6de623297 in add_key_field (join=0x7f9da8165340, key_fields=0x7f9dc46de9f8, and_level=0, cond=0x7f9da8167a90, field=0x7f9da8034490, eq_func=false, value=0x7f9dc46de988, num_values=1, usable_tables=18446744073709551615, sargables=0x7f9dc46deb78, row_col_no=0) at /data/src/10.2/sql/sql_select.cc:4930
#6  0x000055b6de6236c6 in add_key_equal_fields (join=0x7f9da8165340, key_fields=0x7f9dc46de9f8, and_level=0, cond=0x7f9da8167a90, field_item=0x7f9da8167c68, eq_func=false, val=0x7f9dc46de988, num_values=1, usable_tables=18446744073709551615, sargables=0x7f9dc46deb78, row_col_no=0) at /data/src/10.2/sql/sql_select.cc:5051
#7  0x000055b6de624676 in Item_func_null_predicate::add_key_fields (this=0x7f9da8167a90, join=0x7f9da8165340, key_fields=0x7f9dc46de9f8, and_level=0x7f9dc46de9e8, usable_tables=18446744073709551615, sargables=0x7f9dc46deb78) at /data/src/10.2/sql/sql_select.cc:5354
#8  0x000055b6de625ac1 in update_ref_and_keys (thd=0x7f9da8000b00, keyuse=0x7f9da8165630, join_tab=0x7f9da8167d70, tables=1, cond=0x7f9da8167a90, normal_tables=18446744073709551615, select_lex=0x7f9da8016e58, sargables=0x7f9dc46deb78) at /data/src/10.2/sql/sql_select.cc:5802
#9  0x000055b6de6206b6 in make_join_statistics (join=0x7f9da8165340, tables_list=..., keyuse_array=0x7f9da8165630) at /data/src/10.2/sql/sql_select.cc:4094
#10 0x000055b6de617d5f in JOIN::optimize_inner (this=0x7f9da8165340) at /data/src/10.2/sql/sql_select.cc:1580
#11 0x000055b6de616243 in JOIN::optimize (this=0x7f9da8165340) at /data/src/10.2/sql/sql_select.cc:1115
#12 0x000055b6de5a5bdf in mysql_derived_optimize (thd=0x7f9da8000b00, lex=0x7f9da8004618, derived=0x7f9da81647f8) at /data/src/10.2/sql/sql_derived.cc:926
#13 0x000055b6de5a427d in mysql_handle_single_derived (lex=0x7f9da8004618, derived=0x7f9da81647f8, phases=4) at /data/src/10.2/sql/sql_derived.cc:197
#14 0x000055b6de6172d3 in JOIN::optimize_inner (this=0x7f9da8166240) at /data/src/10.2/sql/sql_select.cc:1399
#15 0x000055b6de616243 in JOIN::optimize (this=0x7f9da8166240) at /data/src/10.2/sql/sql_select.cc:1115
#16 0x000055b6de5a5bdf in mysql_derived_optimize (thd=0x7f9da8000b00, lex=0x7f9da8004618, derived=0x7f9da8014ce8) at /data/src/10.2/sql/sql_derived.cc:926
#17 0x000055b6de5a427d in mysql_handle_single_derived (lex=0x7f9da8004618, derived=0x7f9da8014ce8, phases=4) at /data/src/10.2/sql/sql_derived.cc:197
#18 0x000055b6de6172d3 in JOIN::optimize_inner (this=0x7f9da8166a10) at /data/src/10.2/sql/sql_select.cc:1399
#19 0x000055b6de616243 in JOIN::optimize (this=0x7f9da8166a10) at /data/src/10.2/sql/sql_select.cc:1115
#20 0x000055b6de61f6ac in mysql_select (thd=0x7f9da8000b00, tables=0x7f9da8014ce8, wild_num=1, fields=..., conds=0x7f9da8015408, og_num=0, order=0x0, group=0x0, having=0x0, proc_param=0x0, select_options=3489925888, result=0x7f9da8166968, unit=0x7f9da80046e0, select_lex=0x7f9da8004e18) at /data/src/10.2/sql/sql_select.cc:3790
#21 0x000055b6de6139f7 in handle_select (thd=0x7f9da8000b00, lex=0x7f9da8004618, result=0x7f9da8166968, setup_tables_done_option=1073741824) at /data/src/10.2/sql/sql_select.cc:376
#22 0x000055b6de5d8132 in mysql_execute_command (thd=0x7f9da8000b00) at /data/src/10.2/sql/sql_parse.cc:4542
#23 0x000055b6de5e2f39 in mysql_parse (thd=0x7f9da8000b00, rawbuf=0x7f9da8012488 "INSERT INTO t1 SELECT * FROM ( SELECT t1.f FROM v1 JOIN t1 ) AS sq WHERE f IS NOT NULL", length=86, parser_state=0x7f9dc46e0200, is_com_multi=false, is_next_command=false) at /data/src/10.2/sql/sql_parse.cc:8011
#24 0x000055b6de5d0894 in dispatch_command (command=COM_QUERY, thd=0x7f9da8000b00, packet=0x7f9da808c3f1 "INSERT INTO t1 SELECT * FROM ( SELECT t1.f FROM v1 JOIN t1 ) AS sq WHERE f IS NOT NULL", packet_length=86, is_com_multi=false, is_next_command=false) at /data/src/10.2/sql/sql_parse.cc:1824
#25 0x000055b6de5cf1f7 in do_command (thd=0x7f9da8000b00) at /data/src/10.2/sql/sql_parse.cc:1378
#26 0x000055b6de721278 in do_handle_one_connection (connect=0x55b6e1e5a960) at /data/src/10.2/sql/sql_connect.cc:1335
#27 0x000055b6de721005 in handle_one_connection (arg=0x55b6e1e5a960) at /data/src/10.2/sql/sql_connect.cc:1241
#28 0x000055b6deb442b4 in pfs_spawn_thread (arg=0x55b6e1dbe0c0) at /data/src/10.2/storage/perfschema/pfs.cc:1862
#29 0x00007f9dcb8da494 in start_thread (arg=0x7f9dc46e1700) at pthread_create.c:333
#30 0x00007f9dc9cc093f in clone () from /lib/x86_64-linux-gnu/libc.so.6
{noformat}

Reproducible on 10.2, 10.3, 10.4, debug- and non-debug builds, with MyISAM, Aria, InnoDB.
```

## Fix commit message(s)

`6d29c8527b42`

```
MDEV-17354 Server crashes in add_key_field / .. / Item_func_null_predicate::add_key_fields            upon INSERT .. SELECT

The function Item *Item_direct_view_ref::derived_field_transformer_for_where()
erroneously did not strip off ref wrappers from references to materialized
derived tables / views. As a result the expressions that contained some
references of the type Item_direct_view_ref to columns of a materialized
derived table / view V were pushed into V incorrectly. This could cause
crashes for some INSERT ... SELECT statements.
```

## Files the fix changed

Snapshot holds 3,682 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/item.cc`

## The fix diff

### `sql/item.cc`

```diff
diff --git a/sql/item.cc b/sql/item.cc
index 35de01b1186..2adec33491b 100644
--- a/sql/item.cc
+++ b/sql/item.cc
@@ -7212,11 +7212,11 @@ Item *Item_direct_view_ref::derived_field_transformer_for_where(THD *thd,
     st_select_lex *sel= (st_select_lex *)arg;
     Item *producing_item= find_producing_item(this, sel);
     DBUG_ASSERT (producing_item != NULL);
     return producing_item->build_clone(thd, thd->mem_root);
   }
-  return this;
+  return (*ref);
 }
 
 static
 Grouping_tmp_field *find_matching_grouping_field(Item *item,
                                                  st_select_lex *sel)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
