# Annotation packet: MDEV-22867  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Assertion `instant.n_core_fields == n_core_fields' failed in dict_index_t::instant_add_field

_Note: The test case has an obvious race condition, run with --repeat=N. It currently fails nearly every time for me, both in memory and on disk, but it can vary on different machines and builds._

{code:sql}
--source include/have_innodb.inc

CREATE TABLE t1 (a BINARY, UNIQUE(a)) ENGINE=InnoDB;
INSERT INTO t1 VALUES (NULL);
ALTER TABLE t1 ADD COLUMN b INT;

--connect (con1,localhost,root,,test)
--send
  ALTER TABLE t1 DROP a;

--connection default
DELETE FROM t1;

--connection con1
--reap

# Cleanup
--disconnect con1
--connection default
DROP TABLE t1;
{code}

{noformat:title=10.5 17a7bafe}
mariadbd: /data/src/10.5/storage/innobase/handler/handler0alter.cc:422: void dict_index_t::instant_add_field(const dict_index_t&): Assertion `instant.n_core_fields == n_core_fields' failed.
200610 21:59:38 [ERROR] mysqld got signal 6 ;

#7  0x00007fc6095eaf12 in __GI___assert_fail (assertion=0x55f9bb456db8 "instant.n_core_fields == n_core_fields", file=0x55f9bb456618 "/data/src/10.5/storage/innobase/handler/handler0alter.cc", line=422, function=0x55f9bb45f700 <dict_index_t::instant_add_field(dict_index_t const&)::__PRETTY_FUNCTION__> "void dict_index_t::instant_add_field(const dict_index_t&)") at assert.c:101
#8  0x000055f9babac041 in dict_index_t::instant_add_field (this=0x7fc5d421efc8, instant=...) at /data/src/10.5/storage/innobase/handler/handler0alter.cc:422
#9  0x000055f9babae111 in dict_table_t::instant_column (this=0x7fc5d40faf58, table=..., col_map=0x7fc5c80230f8) at /data/src/10.5/storage/innobase/handler/handler0alter.cc:604
#10 0x000055f9babb0509 in ha_innobase_inplace_ctx::instant_column (this=0x7fc5c8013950) at /data/src/10.5/storage/innobase/handler/handler0alter.cc:1050
#11 0x000055f9bab8f737 in innobase_instant_try (ha_alter_info=0x7fc5feb17e80, ctx=0x7fc5c8013950, altered_table=0x7fc5feb17f20, table=0x7fc5c801a8f8, trx=0x7fc5ffc02558) at /data/src/10.5/storage/innobase/handler/handler0alter.cc:5629
#12 0x000055f9babb3d9a in commit_try_norebuild (ha_alter_info=0x7fc5feb17e80, ctx=0x7fc5c8013950, altered_table=0x7fc5feb17f20, old_table=0x7fc5c801a8f8, trx=0x7fc5ffc02558, table_name=0x7fc5d40fc245 "t1") at /data/src/10.5/storage/innobase/handler/handler0alter.cc:10179
#13 0x000055f9baba27c3 in ha_innobase::commit_inplace_alter_table (this=0x7fc5c801bbe0, altered_table=0x7fc5feb17f20, ha_alter_info=0x7fc5feb17e80, commit=true) at /data/src/10.5/storage/innobase/handler/handler0alter.cc:10901
#14 0x000055f9ba6fa051 in handler::ha_commit_inplace_alter_table (this=0x7fc5c801bbe0, altered_table=0x7fc5feb17f20, ha_alter_info=0x7fc5feb17e80, commit=true) at /data/src/10.5/sql/handler.cc:4745
#15 0x000055f9ba492313 in mysql_inplace_alter_table (thd=0x7fc5c8000b18, table_list=0x7fc5c80125c8, table=0x7fc5c801a8f8, altered_table=0x7fc5feb17f20, ha_alter_info=0x7fc5feb17e80, inplace_supported=HA_ALTER_INPLACE_NOCOPY_NO_LOCK, target_mdl_request=0x7fc5feb18ce0, alter_ctx=0x7fc5feb19830) at /data/src/10.5/sql/sql_table.cc:7947
#16 0x000055f9ba499b0c in mysql_alter_table (thd=0x7fc5c8000b18, new_db=0x7fc5c80053d8, new_name=0x7fc5c80057e0, create_info=0x7fc5feb1a430, table_list=0x7fc5c80125c8, alter_info=0x7fc5feb1a360, order_num=0, order=0x0, ignore=false, if_exists=false) at /data/src/10.5/sql/sql_table.cc:10468
#17 0x000055f9ba53effa in Sql_cmd_alter_table::execute (this=0x7fc5c8012cc8, thd=0x7fc5c8000b18) at /data/src/10.5/sql/sql_alter.cc:538
#18 0x000055f9ba39eef3 in mysql_execute_command (thd=0x7fc5c8000b18) at /data/src/10.5/sql/sql_parse.cc:5950
#19 0x000055f9ba3a5227 in mysql_parse (thd=0x7fc5c8000b18, rawbuf=0x7fc5c80124f0 "ALTER TABLE t1 DROP a", length=21, parser_state=0x7fc5feb1b520, is_com_multi=false, is_next_command=false) at /data/src/10.5/sql/sql_parse.cc:7992
#20 0x000055f9ba3915ad in dispatch_command (command=COM_QUERY, thd=0x7fc5c8000b18, packet=0x7fc5c8008939 "ALTER TABLE t1 DROP a", packet_length=21, is_com_multi=false, is_next_command=false) at /data/src/10.5/sql/sql_parse.cc:1875
#21 0x000055f9ba38fce5 in do_command (thd=0x7fc5c8000b18) at /data/src/10.5/sql/sql_parse.cc:1356
#22 0x000055f9ba5346cf in do_handle_one_connection (connect=0x55f9bd3abb58, put_in_cache=true) at /data/src/10.5/sql/sql_connect.cc:1411
#23 0x000055f9ba534437 in handle_one_connection (arg=0x55f9bd3abb58) at /data/src/10.5/sql/sql_connect.cc:1313
#24 0x000055f9baa6d60e in pfs_spawn_thread (arg=0x55f9bd7121f8) at /data/src/10.5/storage/perfschema/pfs.cc:2201
#25 0x00007fc60b5734a4 in start_thread (arg=0x7fc5feb1c700) at pthread_create.c:456
#26 0x00007fc6096a7d0f in clone () at ../sysdeps/unix/sysv/linux/x86_64/clone.S:97
{noformat}

No obvious immediate problem on a non-debug build.
Couldn't reproduce on 10.4, however the failure seems to have appeared after the merge 7bcaa541aa, which featured this commit:
{noformat}
commit 474290540a829edcc6a74be8c354053f330bf5de
Author: Marko Mäkelä
Date:   Tue May 5 14:20:47 2020 +0300

    MDEV-22465: DROP indexed COLUMN is wrongly claimed to be ALGORITHM=INSTANT
{noformat}
```

## Fix commit message(s)

`431200090e40`

```
MDEV-22867 Assertion instant.n_core_fields == n_core_fields failed

This is a race condition where a table on which a 10.3-style
instant ADD COLUMN is emptied during the execution of
ALTER TABLE ... DROP COLUMN ..., DROP INDEX ..., ALGORITHM=NOCOPY.

In commit 2c4844c9e76427525e8c39a2d72686085efe89c3 the
function instant_metadata_lock() would prevent this race condition.
But, it would also hold a page latch on the leftmost leaf page of
clustered index for the duration of a possible DROP INDEX operation.

The race could be fixed by restoring the function
instant_metadata_lock() that was removed in
commit ea37b144094a0c2ebfc6774047fd473c1b2a8658
but it would be more future-proof to prevent the
dict_index_t::clear_instant_add() call from being issued at all.

We at some point support DROP COLUMN ..., ADD INDEX ..., ALGORITHM=NOCOPY
and that would spend a non-trivial amount of
execution time in ha_innobase::inplace_alter(),
making a server hang possible. Currently this is not supported
and our added test case will notice when the support is introduced.

dict_index_t::must_avoid_clear_instant_add(): Determine if
a call to clear_instant_add() must be avoided.

btr_discard_only_page_on_level(): Preserve the metadata record
if must_avoid_clear_instant_add() holds.

btr_cur_optimistic_delete_func(), btr_cur_pessimistic_delete():
Do not remove the metadata record even if the table becomes empty
but must_avoid_clear_instant_add() holds.

btr_pcur_store_position(): Relax a debug assertion.

This is joint work with Thirunarayanan Balathandayuthapani.
```

## Files the fix changed

Snapshot holds 3,311 non-test source files. The fix changed 6 file(s); 4 of them are non-test source files (listed below as gold).

- `storage/innobase/btr/btr0btr.cc`
- `storage/innobase/btr/btr0cur.cc`
- `storage/innobase/btr/btr0pcur.cc`
- `storage/innobase/include/dict0mem.h`

## The fix diff

### `storage/innobase/btr/btr0btr.cc`

```diff
diff --git a/storage/innobase/btr/btr0btr.cc b/storage/innobase/btr/btr0btr.cc
index 03eb1e076e4..d9c99f59132 100644
--- a/storage/innobase/btr/btr0btr.cc
+++ b/storage/innobase/btr/btr0btr.cc
@@ -3942,15 +3942,18 @@ btr_discard_only_page_on_level(
 #endif /* UNIV_BTR_DEBUG */
 
 	mem_heap_t* heap = NULL;
 	const rec_t* rec = NULL;
 	rec_offs* offsets = NULL;
-	if (index->table->instant) {
+
+	if (index->table->instant || index->must_avoid_clear_instant_add()) {
 		const rec_t* r = page_rec_get_next(page_get_infimum_rec(
 							   block->frame));
 		ut_ad(rec_is_metadata(r, *index) == index->is_instant());
-		if (rec_is_alter_metadata(r, *index)) {
+		if (!rec_is_metadata(r, *index)) {
+		} else if (!index->table->instant
+			   || rec_is_alter_metadata(r, *index)) {
 			heap = mem_heap_create(srv_page_size);
 			offsets = rec_get_offsets(r, index, NULL, true,
 						  ULINT_UNDEFINED, &heap);
 			rec = rec_copy(mem_heap_alloc(heap,
 						      rec_offs_size(offsets)),
```

### `storage/innobase/btr/btr0cur.cc`

```diff
diff --git a/storage/innobase/btr/btr0cur.cc b/storage/innobase/btr/btr0cur.cc
index f036f677712..4fbd1d653ac 100644
--- a/storage/innobase/btr/btr0cur.cc
+++ b/storage/innobase/btr/btr0cur.cc
@@ -5448,11 +5448,12 @@ btr_cur_optimistic_delete_func(
 	rec = btr_cur_get_rec(cursor);
 
 	if (UNIV_UNLIKELY(block->page.id().page_no() == cursor->index->page
 			  && page_get_n_recs(block->frame) == 1
 			  + (cursor->index->is_instant()
-			     && !rec_is_metadata(rec, *cursor->index)))) {
+			     && !rec_is_metadata(rec, *cursor->index))
+			  && !cursor->index->must_avoid_clear_instant_add())) {
 		/* The whole index (and table) becomes logically empty.
 		Empty the whole page. That is, if we are deleting the
 		only user record, also delete the metadata record
 		if one exists for instant ADD COLUMN (not generic ALTER TABLE).
 		If we are deleting the metadata record and the
@@ -5685,11 +5686,12 @@ btr_cur_pessimistic_delete(
 		if (block->page.id().page_no() != index->page) {
 			if (page_get_n_recs(page) < 2) {
 				goto discard_page;
 			}
 		} else if (page_get_n_recs(page) == 1
-			   + (index->is_instant() && !is_metadata)) {
+			   + (index->is_instant() && !is_metadata)
+			   && !index->must_avoid_clear_instant_add()) {
 			/* The whole index (and table) becomes logically empty.
 			Empty the whole page. That is, if we are deleting the
 			only user record, also delete the metadata record
 			if one exists for instant ADD COLUMN
 			(not generic ALTER TABLE).
```

### `storage/innobase/btr/btr0pcur.cc`

```diff
diff --git a/storage/innobase/btr/btr0pcur.cc b/storage/innobase/btr/btr0pcur.cc
index 9ecddf4904c..aac080d1a6e 100644
--- a/storage/innobase/btr/btr0pcur.cc
+++ b/storage/innobase/btr/btr0pcur.cc
@@ -147,11 +147,17 @@ before_first:
 	if (page_rec_is_supremum_low(offs)) {
 		rec = page_rec_get_prev(rec);
 
 		ut_ad(!page_rec_is_infimum(rec));
 		if (UNIV_UNLIKELY(rec_is_metadata(rec, *index))) {
+#if 0 /* MDEV-22867 had to relax this */
+			/* If the table is emptied during an ALGORITHM=NOCOPY
+			DROP COLUMN ... that is not ALGORITHM=INSTANT,
+			then we must preserve any instant ADD metadata. */
 			ut_ad(index->table->instant);
+#endif
+			ut_ad(index->is_instant());
 			ut_ad(page_get_n_recs(block->frame) == 1);
 			ut_ad(page_is_leaf(block->frame));
 			ut_ad(!page_has_siblings(block->frame));
 			cursor->rel_pos = BTR_PCUR_AFTER_LAST_IN_TREE;
 			return;
```

### `storage/innobase/include/dict0mem.h`

```diff
diff --git a/storage/innobase/include/dict0mem.h b/storage/innobase/include/dict0mem.h
index 731ff545685..694c7081574 100644
--- a/storage/innobase/include/dict0mem.h
+++ b/storage/innobase/include/dict0mem.h
@@ -1304,10 +1304,20 @@ public:
   bool freed() const { return UNIV_UNLIKELY(page == 1); }
   /** Note that the index is waiting for btr_search_lazy_free() */
   void set_freed() { ut_ad(!freed()); page= 1; }
 #endif /* BTR_CUR_HASH_ADAPT */
 
+  /** @return whether it is forbidden to invoke clear_instant_add() */
+  bool must_avoid_clear_instant_add() const
+  {
+    if (is_instant())
+      for (auto i= this; (i= UT_LIST_GET_NEXT(indexes, i)) != nullptr; )
+        if (i->to_be_dropped /* || i->online_log*/)
+          return true;
+    return false;
+  }
+
 	/** This ad-hoc class is used by record_size_info only.	*/
 	class record_size_info_t {
 	public:
 		record_size_info_t()
 		    : max_leaf_size(0), shortest_size(0), too_big(false),
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
