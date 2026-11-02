# Annotation packet: MDEV-18163  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Assertion `table_share->tmp_table != NO_TMP_TABLE || m_lock_type != 2' failed in handler::ha_rnd_next(); / Assertion `table_list->table' failed in find_field_in_table_ref / ERROR 1901 (on optimized builds)

{code:sql}
CREATE TABLE t1 (k1 varchar(10) DEFAULT 5);
CREATE TABLE t2 (i1 int);

ALTER TABLE t1 ALTER COLUMN k1 SET DEFAULT (SELECT 1 FROM t2 limit 1);
{code}

{noformat:title=10.2 0c20b247de0c1cc7f993e1eba6}
#3  <signal handler called>
#4  0x00007f3aea115428 in __GI_raise (sig=sig@entry=6) at ../sysdeps/unix/sysv/linux/raise.c:54
#5  0x00007f3aea11702a in __GI_abort () at abort.c:89
#6  0x00007f3aea10dbd7 in __assert_fail_base (fmt=<optimized out>, assertion=assertion@entry=0x558024fcdfe0 "table_share->tmp_table != NO_TMP_TABLE || m_lock_type != 2", file=file@entry=0x558024fcd078 "/git/10.2/sql/handler.cc", line=line@entry=2576, function=function@entry=0x558024fcf620 <handler::ha_rnd_next(unsigned char*)::__PRETTY_FUNCTION__> "int handler::ha_rnd_next(uchar*)") at assert.c:92
#7  0x00007f3aea10dc82 in __GI___assert_fail (assertion=0x558024fcdfe0 "table_share->tmp_table != NO_TMP_TABLE || m_lock_type != 2", file=0x558024fcd078 "/git/10.2/sql/handler.cc", line=2576, function=0x558024fcf620 <handler::ha_rnd_next(unsigned char*)::__PRETTY_FUNCTION__> "int handler::ha_rnd_next(uchar*)") at assert.c:101
#8  0x00005580246ebec5 in handler::ha_rnd_next (this=0x7f3a9408cd38, buf=0x7f3a9408c8e0 "\377") at /git/10.2/sql/handler.cc:2575
#9  0x00005580246ed734 in handler::read_first_row (this=0x7f3a9408cd38, buf=0x7f3a9408c8e0 "\377", primary_key=64) at /git/10.2/sql/handler.cc:2815
#10 0x00005580244f62fd in handler::ha_read_first_row (this=0x7f3a9408cd38, buf=0x7f3a9408c8e0 "\377", primary_key=64) at /git/10.2/sql/sql_class.h:5829
#11 0x00005580244de453 in join_read_system (tab=0x7f3a94015320) at /git/10.2/sql/sql_select.cc:19296
#12 0x00005580244de010 in join_read_const_table (thd=0x7f3a94000b00, tab=0x7f3a94015320, pos=0x7f3a940158d8) at /git/10.2/sql/sql_select.cc:19192
#13 0x00005580244b8a8e in make_join_statistics (join=0x7f3a94014b10, tables_list=..., keyuse_array=0x7f3a94014e00) at /git/10.2/sql/sql_select.cc:4144
#14 0x00005580244afeb6 in JOIN::optimize_inner (this=0x7f3a94014b10) at /git/10.2/sql/sql_select.cc:1582
#15 0x00005580244ae3a9 in JOIN::optimize (this=0x7f3a94014b10) at /git/10.2/sql/sql_select.cc:1115
#16 0x00005580247b5792 in subselect_single_select_engine::exec (this=0x7f3a94013fe8) at /git/10.2/sql/item_subselect.cc:3811
#17 0x00005580247aab8f in Item_subselect::exec (this=0x7f3a94013e68) at /git/10.2/sql/item_subselect.cc:722
#18 0x00005580247ac8a3 in Item_singlerow_subselect::val_int (this=0x7f3a94013e68) at /git/10.2/sql/item_subselect.cc:1329
#19 0x000055802470b6ce in Item::save_in_field (this=0x7f3a94013e68, field=0x7f3a94014a30, no_conversions=true) at /git/10.2/sql/item.cc:6394
#20 0x000055802458c9f0 in make_empty_rec (thd=0x7f3a94000b00, buff=0x7f3a94090626 "\001", table_options=9, create_fields=..., reclength=12, data_offset=1) at /git/10.2/sql/unireg.cc:998
#21 0x000055802458a125 in build_frm_image (thd=0x7f3a94000b00, table=0x7f3a94012548 "t1", create_info=0x7f3adc112cd0, create_fields=..., keys=0, key_info=0x7f3a94014a18, db_file=0x7f3a94014338) at /git/10.2/sql/unireg.cc:308
#22 0x0000558024536eb7 in mysql_create_frm_image (thd=0x7f3a94000b00, db=0x7f3a94012b90 "test", table_name=0x7f3a94012548 "t1", create_info=0x7f3adc112cd0, alter_info=0x7f3adc112c20, create_table_mode=-2, key_info=0x7f3adc1113d8, key_count=0x7f3adc1113a8, frm=0x7f3adc111440) at /git/10.2/sql/sql_table.cc:4658
#23 0x00005580245378be in create_table_impl (thd=0x7f3a94000b00, orig_db=0x7f3a94012b90 "test", orig_table_name=0x7f3a94012548 "t1", db=0x7f3a94012b90 "test", table_name=0x7f3adc112100 "#sql-2ad7_9", path=0x7f3adc11296c "./test/#sql-2ad7_9", options=..., create_info=0x7f3adc112cd0, alter_info=0x7f3adc112c20, create_table_mode=-2, is_trans=0x0, key_info=0x7f3adc1113d8, key_count=0x7f3adc1113a8, frm=0x7f3adc111440) at /git/10.2/sql/sql_table.cc:4898
#24 0x0000558024542fc7 in mysql_alter_table (thd=0x7f3a94000b00, new_db=0x7f3a94012b90 "test", new_name=0x0, create_info=0x7f3adc112cd0, table_list=0x7f3a94012580, alter_info=0x7f3adc112c20, order_num=0, order=0x0, ignore=false) at /git/10.2/sql/sql_table.cc:9238
#25 0x00005580245be7a4 in Sql_cmd_alter_table::execute (this=0x7f3a94014078, thd=0x7f3a94000b00) at /git/10.2/sql/sql_alter.cc:329
#26 0x0000558024475d98 in mysql_execute_command (thd=0x7f3a94000b00) at /git/10.2/sql/sql_parse.cc:6228
#27 0x000055802447ae9f in mysql_parse (thd=0x7f3a94000b00, rawbuf=0x7f3a94012448 "ALTER TABLE t1 ALTER COLUMN k1 SET DEFAULT (SELECT 1 FROM t2 limit 1)", length=69, parser_state=0x7f3adc114080, is_com_multi=false, is_next_command=false) at /git/10.2/sql/sql_parse.cc:8015
#28 0x00005580244684f0 in dispatch_command (command=COM_QUERY, thd=0x7f3a94000b00, packet=0x7f3a94095e21 "ALTER TABLE t1 ALTER COLUMN k1 SET DEFAULT (SELECT 1 FROM t2 limit 1)", packet_length=69, is_com_multi=false, is_next_command=false) at /git/10.2/sql/sql_parse.cc:1826
#29 0x0000558024466e40 in do_command (thd=0x7f3a94000b00) at /git/10.2/sql/sql_parse.cc:1379
#30 0x00005580245b947c in do_handle_one_connection (connect=0x558026b7af40) at /git/10.2/sql/sql_connect.cc:1335
#31 0x00005580245b91fc in handle_one_connection (arg=0x558026b7af40) at /git/10.2/sql/sql_connect.cc:1241
#32 0x0000558024de7066 in pfs_spawn_thread (arg=0x558026ac1630) at /git/10.2/storage/perfschema/pfs.cc:1862
#33 0x00007f3aead526ba in start_thread (arg=0x7f3adc115700) at pthread_create.c:333
#34 0x00007f3aea1e741d in clone () at ../sysdeps/unix/sysv/linux/x86_64/clone.S:109
{noformat}
```

## Fix commit message(s)

`5933081d8b05`

```
MDEV-18163 Assertion `table_share->tmp_table != NO_TMP_TABLE || m_lock_type != 2' failed in handler::ha_rnd_next(); / Assertion `table_list->table' failed in find_field_in_table_ref / ERROR 1901 (on optimized builds)

Add the same check for altering DEFAULT used as for CREATE TABLE.
```

## Files the fix changed

Snapshot holds 3,694 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/sql_yacc.yy`

## The fix diff

### `sql/sql_yacc.yy`

```diff
diff --git a/sql/sql_yacc.yy b/sql/sql_yacc.yy
index 386c86cb3e2..138d5e13701 100644
--- a/sql/sql_yacc.yy
+++ b/sql/sql_yacc.yy
@@ -7690,10 +7690,12 @@ alter_list_item:
             lex->alter_info.flags|= Alter_info::ALTER_KEYS_ONOFF;
           }
         | ALTER opt_column field_ident SET DEFAULT column_default_expr
           {
             LEX *lex=Lex;
+            if (check_expression($6, $3.str, VCOL_DEFAULT))
+              MYSQL_YYABORT;
             Alter_column *ac= new (thd->mem_root) Alter_column($3.str,$6);
             if (ac == NULL)
               MYSQL_YYABORT;
             lex->alter_info.alter_list.push_back(ac, thd->mem_root);
             lex->alter_info.flags|= Alter_info::ALTER_CHANGE_COLUMN_DEFAULT;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
