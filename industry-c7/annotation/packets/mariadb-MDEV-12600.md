# Annotation packet: MDEV-12600  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
crash during install_db with innodb_page_size=32K and ibdata1=3M;

May be related to MDEV-12113 , just this is without encryption.
When trying to install_db in 10.1 with :
innodb_page_size=32k
innodb_data_file_path=ibdata1:3M;ibdata2:10M:autoextend

I am not getting stack resolved - let me know if this is required to troubleshoot:


{noformat}
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld(my_print_stacktrace+0x2e)[0xc0b60e]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld(handle_fatal_signal+0x4bf)[0x76902f]
/lib/x86_64-linux-gnu/libpthread.so.0(+0x11630)[0x7fd86e014630]
/lib/x86_64-linux-gnu/libc.so.6(gsignal+0x9f)[0x7fd86cd9a7ef]
/lib/x86_64-linux-gnu/libc.so.6(abort+0x16a)[0x7fd86cd9c3ea]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0xa9b877]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0xa49a8f]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0xa4f75e]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0x94e3a3]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0x951768]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0x9e2232]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0x908304]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld(_Z24ha_initialize_handlertonP13st_plugin_int+0x5e)[0x76eede]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0x5c6008]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld(_Z11plugin_initPiPPci+0xbc0)[0x5c6fd0]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0x5204ad]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld(_Z11mysqld_mainiPPc+0x8c3)[0x5216f3]
/lib/x86_64-linux-gnu/libc.so.6(__libc_start_main+0xf1)[0x7fd86cd853f1]
/home/a/mariadb-environs/m9-10.1.22/../_depot/m-tar/10.1.22/bin/mysqld[0x516a49]
The manual page at http://dev.mysql.com/doc/mysql/en/crashing.html contains
{noformat}




https://travis-ci.org/AndriiNikitin/mariadb-environs-MDEV-12113/builds/226281024

Only these configurations do show crash:

{noformat}
VERSION=10.1.22 PAGE_SIZE=32k DATA_FILE_PATH='ibdata1:3M;ibdata2:10M:autoextend'
{noformat}

the rest pass:
{noformat}
VERSION=10.1.22 PAGE_SIZE=16k DATA_FILE_PATH='ibdata1:3M;ibdata2:10M:autoextend'
VERSION=10.1.22 PAGE_SIZE=16k DATA_FILE_PATH='ibdata1:3M;ibdata2:10M:autoextend' REST=configure_rest_encryption.sh=1
VERSION=10.1.22 PAGE_SIZE=8k DATA_FILE_PATH='ibdata1:3M;ibdata2:10M:autoextend'
VERSION=10.1.22 PAGE_SIZE=64k DATA_FILE_PATH='ibdata1:3M;ibdata2:10M:autoextend'
VERSION=10.1.22 PAGE_SIZE=32k DATA_FILE_PATH='ibdata1:1M;ibdata2:10M:autoextend'
VERSION=10.1.22 PAGE_SIZE=32k DATA_FILE_PATH='ibdata1:11M;ibdata2:10M:autoextend'
VERSION=10.1.22 PAGE_SIZE=32k DATA_FILE_PATH='ibdata1:31M;ibdata2:10M:autoextend'
VERSION=10.1.22 PAGE_SIZE=32k DATA_FILE_PATH='ibdata1:3M:autoextend'
VERSION=10.1.22 PAGE_SIZE=32k DATA_FILE_PATH='ibdata1:1M;ibdata2:3M:autoextend'
VERSION=10.0.30 PAGE_SIZE=8k DATA_FILE_PATH='ibdata1:3M;ibdata2:10M:autoextend'
VERSION=5.5.55 PAGE_SIZE=8k DATA_FILE_PATH='ibdata1:3M;ibdata2:10M:autoextend'
{noformat}

10.2 reports an (expected) error that 3Mb is too small :
InnoDB: The innodb_system data file 'ibdata1' must be at least 6 MB

{noformat}
VERSION=10.2.5 PAGE_SIZE=32k DATA_FILE_PATH='ibdata1:3M;ibdata2:10M:autoextend'
{noformat}
```

## Fix commit message(s)

`112b21da37da`

```
MDEV-12600: crash during install_db with innodb_page_size=32K and ibdata1=3M;

Problem was that all doublewrite buffer pages must fit to first
system datafile.

Ported commit 27a34df7882b1f8ed283f22bf83e8bfc523cbfde
Author: Shaohua Wang <shaohua.wang@oracle.com>
Date:   Wed Aug 12 15:55:19 2015 +0800

    BUG#21551464 - SEGFAULT WHILE INITIALIZING DATABASE WHEN
    INNODB_DATA_FILE SIZE IS SMALL

To 10.1 (with extended error printout).

btr_create(): If ibuf header page allocation fails report error and
return FIL_NULL. Similarly if root page allocation fails return a error.

dict_build_table_def_step: If fsp_header_init fails return
error code.

fsp_header_init: returns true if header initialization succeeds
and false if not.

fseg_create_general: report error if segment or page allocation fails.

innobase_init: If first datafile is smaller than 3M and could not
contain all doublewrite buffer pages report error and fail to
initialize InnoDB plugin.

row_truncate_table_for_mysql: report error if fsp header init
fails.

srv_init_abort: New function to report database initialization errors.

srv_undo_tablespaces_init, innobase_start_or_create_for_mysql: If
database initialization fails report error and abort.

trx_rseg_create: If segment header creation fails return.
```

`fbeb9489cd7d`

```
Cleanup of MDEV-12600: crash during install_db with innodb_page_size=32K and ibdata1=3M

The doublewrite buffer pages must fit in the first InnoDB system
tablespace data file. The checks that were added in the initial patch
(commit 112b21da37dad0fbb28bc65f9ab5a3ba6c0c2186)
were at too high level and did not cover all cases.

innodb.log_data_file_size: Test all innodb_page_size combinations.

fsp_header_init(): Never return an error. Move the change buffer creation
to the only caller that needs to do it.

btr_create(): Clean up the logic. Remove the error log messages.

buf_dblwr_create(): Try to return an error on non-fatal failure.
Check that the first data file is big enough for creating the
doublewrite buffers.

buf_dblwr_process(): Check if the doublewrite buffer is available.
Display the message only if it is available.

recv_recovery_from_checkpoint_start_func(): Remove a redundant message
about FIL_PAGE_FILE_FLUSH_LSN mismatch when crash recovery has already
been initiated.

fil_report_invalid_page_access(): Simplify the message.

fseg_create_general(): Do not emit messages to the error log.

innobase_init(): Revert the changes.

trx_rseg_create(): Refactor (no functional change).
```

## Files the fix changed

Snapshot holds 3,458 non-test source files. The fix changed 30 file(s); 26 of them are non-test source files (listed below as gold).

- `storage/innobase/btr/btr0btr.cc`
- `storage/innobase/buf/buf0dblwr.cc`
- `storage/innobase/dict/dict0crea.cc`
- `storage/innobase/fil/fil0fil.cc`
- `storage/innobase/fsp/fsp0fsp.cc`
- `storage/innobase/handler/ha_innodb.cc`
- `storage/innobase/include/buf0dblwr.h`
- `storage/innobase/include/fsp0fsp.h`
- `storage/innobase/include/trx0rseg.h`
- `storage/innobase/log/log0recv.cc`
- `storage/innobase/row/row0mysql.cc`
- `storage/innobase/srv/srv0start.cc`
- `storage/innobase/trx/trx0rseg.cc`
- `storage/xtradb/btr/btr0btr.cc`
- `storage/xtradb/buf/buf0dblwr.cc`
- `storage/xtradb/dict/dict0crea.cc`
- `storage/xtradb/fil/fil0fil.cc`
- `storage/xtradb/fsp/fsp0fsp.cc`
- `storage/xtradb/handler/ha_innodb.cc`
- `storage/xtradb/include/buf0dblwr.h`
- `storage/xtradb/include/fsp0fsp.h`
- `storage/xtradb/include/trx0rseg.h`
- `storage/xtradb/log/log0recv.cc`
- `storage/xtradb/row/row0mysql.cc`
- `storage/xtradb/srv/srv0start.cc`
- `storage/xtradb/trx/trx0rseg.cc`

## The fix diff

### `storage/innobase/btr/btr0btr.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/innobase/btr/btr0btr.cc b/storage/innobase/btr/btr0btr.cc
index cccae031b88..e200a2b9677 100644
--- a/storage/innobase/btr/btr0btr.cc
+++ b/storage/innobase/btr/btr0btr.cc
@@ -1699,10 +1699,16 @@ btr_create(
 		/* Allocate first the ibuf header page */
 		buf_block_t*	ibuf_hdr_block = fseg_create(
 			space, 0,
 			IBUF_HEADER + IBUF_TREE_SEG_HEADER, mtr);
 
+		if (ibuf_hdr_block == NULL) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of the first ibuf header page failed.");
+			return (FIL_NULL);
+		}
+
 		buf_block_dbg_add_level(
 			ibuf_hdr_block, SYNC_IBUF_TREE_NODE_NEW);
 
 		ut_ad(buf_block_get_page_no(ibuf_hdr_block)
 		      == IBUF_HEADER_PAGE_NO);
@@ -1712,10 +1718,15 @@ btr_create(
 		block = fseg_alloc_free_page(
 			buf_block_get_frame(ibuf_hdr_block)
 			+ IBUF_HEADER + IBUF_TREE_SEG_HEADER,
 			IBUF_TREE_ROOT_PAGE_NO,
 			FSP_UP, mtr);
+
+		if (!block) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of the tree root page segment failed.");
+		}
 		ut_ad(buf_block_get_page_no(block) == IBUF_TREE_ROOT_PAGE_NO);
 	} else {
 #ifdef UNIV_BLOB_DEBUG
 		if ((type & DICT_CLUSTERED) && !index->blobs) {
 			mutex_create(PFS_NOT_INSTRUMENTED,
@@ -1724,10 +1735,16 @@ btr_create(
 						  btr_blob_dbg_cmp);
 		}
 #endif /* UNIV_BLOB_DEBUG */
 		block = fseg_create(space, 0,
 				    PAGE_HEADER + PAGE_BTR_SEG_TOP, mtr);
+
+		if (!block) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of the btree segment failed.");
+		}
+
 	}
 
 	if (block == NULL) {
 
 		return(FIL_NULL);
@@ -1752,10 +1769,12 @@ btr_create(
 				 PAGE_HEADER + PAGE_BTR_SEG_LEAF, mtr)) {
 			/* Not enough space for new segment, free root
 			segment before return. */
 			btr_free_root(space, zip_size, page_no, mtr);
 
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of the non-ibuf tree segment for leaf pages failed.");
 			return(FIL_NULL);
 		}
 
 		/* The fseg create acquires a second latch on the page,
 		therefore we must declare it: */
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/btr/btr0btr.cc b/storage/innobase/btr/btr0btr.cc
index e200a2b9677..b7afcf12b39 100644
--- a/storage/innobase/btr/btr0btr.cc
+++ b/storage/innobase/btr/btr0btr.cc
@@ -1,10 +1,10 @@
 /*****************************************************************************
 
 Copyright (c) 1994, 2016, Oracle and/or its affiliates. All Rights Reserved.
 Copyright (c) 2012, Facebook Inc.
-Copyright (c) 2014, 2017, MariaDB Corporation
+Copyright (c) 2014, 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -1682,13 +1682,11 @@ btr_create(
 				or 0 for uncompressed pages */
 	index_id_t	index_id,/*!< in: index id */
 	dict_index_t*	index,	/*!< in: index */
 	mtr_t*		mtr)	/*!< in: mini-transaction handle */
 {
-	ulint		page_no;
 	buf_block_t*	block;
-	buf_frame_t*	frame;
 	page_t*		page;
 	page_zip_des_t*	page_zip;
 
 	/* Create the two new segments (one, in the case of an ibuf tree) for
 	the index tree; the segment headers are put on the allocated root page
@@ -1700,13 +1698,11 @@ btr_create(
 		buf_block_t*	ibuf_hdr_block = fseg_create(
 			space, 0,
 			IBUF_HEADER + IBUF_TREE_SEG_HEADER, mtr);
 
 		if (ibuf_hdr_block == NULL) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of the first ibuf header page failed.");
-			return (FIL_NULL);
+			return(FIL_NULL);
 		}
 
 		buf_block_dbg_add_level(
 			ibuf_hdr_block, SYNC_IBUF_TREE_NODE_NEW);
 
@@ -1719,15 +1715,20 @@ btr_create(
 			buf_block_get_frame(ibuf_hdr_block)
 			+ IBUF_HEADER + IBUF_TREE_SEG_HEADER,
 			IBUF_TREE_ROOT_PAGE_NO,
 			FSP_UP, mtr);
 
-		if (!block) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of the tree root page segment failed.");
+		if (block == NULL) {
+			return(FIL_NULL);
 		}
+
 		ut_ad(buf_block_get_page_no(block) == IBUF_TREE_ROOT_PAGE_NO);
+
+		buf_block_dbg_add_level(block, SYNC_IBUF_TREE_NODE_NEW);
+
+		flst_init(block->frame + PAGE_HEADER + PAGE_BTR_IBUF_FREE_LIST,
+			  mtr);
 	} else {
 #ifdef UNIV_BLOB_DEBUG
 		if ((type & DICT_CLUSTERED) && !index->blobs) {
 			mutex_create(PFS_NOT_INSTRUMENTED,
 				     &index->blobs_mutex, SYNC_ANY_LATCH);
@@ -1736,45 +1737,22 @@ btr_create(
 		}
 #endif /* UNIV_BLOB_DEBUG */
 		block = fseg_create(space, 0,
 				    PAGE_HEADER + PAGE_BTR_SEG_TOP, mtr);
 
-		if (!block) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of the btree segment failed.");
+		if (block == NULL) {
+			return(FIL_NULL);
 		}
 
-	}
-
-	if (block == NULL) {
-
-		return(FIL_NULL);
-	}
-
-	page_no = buf_block_get_page_no(block);
-	frame = buf_block_get_frame(block);
-
-	if (type & DICT_IBUF) {
-		/* It is an insert buffer tree: initialize the free list */
-		buf_block_dbg_add_level(block, SYNC_IBUF_TREE_NODE_NEW);
-
-		ut_ad(page_no == IBUF_TREE_ROOT_PAGE_NO);
-
-		flst_init(frame + PAGE_HEADER + PAGE_BTR_IBUF_FREE_LIST, mtr);
-	} else {
-		/* It is a non-ibuf tree: create a file segment for leaf
-		pages */
 		buf_block_dbg_add_level(block, SYNC_TREE_NODE_NEW);
 
-		if (!fseg_create(space, page_no,
+		if (!fseg_create(space, buf_block_get_page_no(block),
 				 PAGE_HEADER + PAGE_BTR_SEG_LEAF, mtr)) {
 			/* Not enough space for new segment, free root
 			segment before return. */
-			btr_free_root(space, zip_size, page_no, mtr);
-
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of the non-ibuf tree segment for leaf pages failed.");
+			btr_free_root(space, zip_size,
+				      buf_block_get_page_no(block), mtr);
 			return(FIL_NULL);
 		}
 
 		/* The fseg create acquires a second latch on the page,
 		therefore we must declare it: */
@@ -1814,11 +1792,11 @@ btr_create(
 	allowed size fit on the root page: this fact is needed to ensure
 	correctness of split algorithms */
 
 	ut_ad(page_get_max_insert_size(page, 2) > 2 * BTR_PAGE_MAX_REC_SIZE);
 
-	return(page_no);
+	return(buf_block_get_page_no(block));
 }
 
 /************************************************************//**
 Frees a B-tree except the root page, which MUST be freed after this
 by calling btr_free_root. */
```

### `storage/innobase/buf/buf0dblwr.cc`

```diff
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/buf/buf0dblwr.cc b/storage/innobase/buf/buf0dblwr.cc
index e2c7ae9bae1..8ff5428d3a5 100644
--- a/storage/innobase/buf/buf0dblwr.cc
+++ b/storage/innobase/buf/buf0dblwr.cc
@@ -173,17 +173,18 @@ buf_dblwr_init(
 
 	buf_dblwr->buf_block_arr = static_cast<buf_page_t**>(
 		mem_zalloc(buf_size * sizeof(void*)));
 }
 
-/****************************************************************//**
-Creates the doublewrite buffer to a new InnoDB installation. The header of the
-doublewrite buffer is placed on the trx system header page. */
+/** Create the doublewrite buffer if the doublewrite buffer header
+is not present in the TRX_SYS page.
+@return	whether the operation succeeded
+@retval	true	if the doublewrite buffer exists or was created
+@retval	false	if the creation failed (too small first data file) */
 UNIV_INTERN
-void
-buf_dblwr_create(void)
-/*==================*/
+bool
+buf_dblwr_create()
 {
 	buf_block_t*	block2;
 	buf_block_t*	new_block;
 	byte*	doublewrite;
 	byte*	fseg_header;
@@ -192,12 +193,11 @@ buf_dblwr_create(void)
 	ulint	i;
 	mtr_t	mtr;
 
 	if (buf_dblwr) {
 		/* Already inited */
-
-		return;
+		return(true);
 	}
 
 start_again:
 	mtr_start(&mtr);
 	buf_dblwr_being_created = TRUE;
@@ -211,43 +211,63 @@ start_again:
 
 		buf_dblwr_init(doublewrite);
 
 		mtr_commit(&mtr);
 		buf_dblwr_being_created = FALSE;
-		return;
+		return(true);
 	}
 
-	ib_logf(IB_LOG_LEVEL_INFO,
-		"Doublewrite buffer not found: creating new");
-
 	if (buf_pool_get_curr_size()
 	    < ((TRX_SYS_DOUBLEWRITE_BLOCKS * TRX_SYS_DOUBLEWRITE_BLOCK_SIZE
 		+ FSP_EXTENT_SIZE / 2 + 100)
 	       * UNIV_PAGE_SIZE)) {
 
-		ib_logf(IB_LOG_LEVEL_FATAL,
-			"Cannot create doublewrite buffer: you must "
-			"increase your buffer pool size. Cannot continue "
-			"operation.");
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Cannot create doublewrite buffer: "
+			"innodb_buffer_pool_size is too small.");
+		mtr_commit(&mtr);
+		return(false);
+	} else {
+		fil_space_t* space = fil_space_acquire(TRX_SYS_SPACE);
+		const bool fail = UT_LIST_GET_FIRST(space->chain)->size
+			< 3 * FSP_EXTENT_SIZE;
+		fil_space_release(space);
+
+		if (fail) {
+			goto too_small;
+		}
 	}
 
 	block2 = fseg_create(TRX_SYS_SPACE, TRX_SYS_PAGE_NO,
 			     TRX_SYS_DOUBLEWRITE
 			     + TRX_SYS_DOUBLEWRITE_FSEG, &mtr);
 
+	if (block2 == NULL) {
+too_small:
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Cannot create doublewrite buffer: "
+			"the first file in innodb_data_file_path"
+			" must be at least %luM.",
+			3 * (FSP_EXTENT_SIZE * UNIV_PAGE_SIZE) >> 20);
+		mtr_commit(&mtr);
+		return(false);
+	}
+
+	ib_logf(IB_LOG_LEVEL_INFO,
+		"Doublewrite buffer not found: creating new");
+
+	/* FIXME: After this point, the doublewrite buffer creation
+	is not atomic. The doublewrite buffer should not exist in
+	the InnoDB system tablespace file in the first place.
+	It could be located in separate optional file(s) in a
+	user-specified location. */
+
 	/* fseg_create acquires a second latch on the page,
 	therefore we must declare it: */
 
 	buf_block_dbg_add_level(block2, SYNC_NO_ORDER_CHECK);
 
-	if (block2 == NULL) {
-		ib_logf(IB_LOG_LEVEL_FATAL,
-			"Cannot create doublewrite buffer: you must "
-			"increase your tablespace size. "
-			"Cannot continue operation.");
-	}
-
 	fseg_header = doublewrite + TRX_SYS_DOUBLEWRITE_FSEG;
 	prev_page_no = 0;
 
 	for (i = 0; i < TRX_SYS_DOUBLEWRITE_BLOCKS * TRX_SYS_DOUBLEWRITE_BLOCK_SIZE
 		     + FSP_EXTENT_SIZE / 2; i++) {
@@ -480,10 +500,18 @@ buf_dblwr_process()
 	byte*	page;
 	byte*	read_buf;
 	byte*	unaligned_read_buf;
 	recv_dblwr_t& recv_dblwr = recv_sys->dblwr;
 
+	if (!buf_dblwr) {
+		return;
+	}
+
+	ib_logf(IB_LOG_LEVEL_INFO,
+		"Restoring possible half-written data pages "
+		"from the doublewrite buffer...");
+
 	unaligned_read_buf = static_cast<byte*>(ut_malloc(2 * UNIV_PAGE_SIZE));
 
 	read_buf = static_cast<byte*>(
 		ut_align(unaligned_read_buf, UNIV_PAGE_SIZE));
```

### `storage/innobase/dict/dict0crea.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/innobase/dict/dict0crea.cc b/storage/innobase/dict/dict0crea.cc
index f6cd294884b..1ec7123bbc2 100644
--- a/storage/innobase/dict/dict0crea.cc
+++ b/storage/innobase/dict/dict0crea.cc
@@ -319,13 +319,17 @@ dict_build_table_def_step(
 			return(error);
 		}
 
 		mtr_start(&mtr);
 
-		fsp_header_init(table->space, FIL_IBD_FILE_INITIAL_SIZE, &mtr);
+		bool res = fsp_header_init(table->space, FIL_IBD_FILE_INITIAL_SIZE, &mtr);
 
 		mtr_commit(&mtr);
+
+		if (!res) {
+			return (DB_ERROR);
+		}
 	} else {
 		/* Create in the system tablespace: disallow Barracuda
 		features by keeping only the first bit which says whether
 		the row format is redundant or compact */
 		table->flags &= DICT_TF_COMPACT;
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/dict/dict0crea.cc b/storage/innobase/dict/dict0crea.cc
index 1ec7123bbc2..f6cd294884b 100644
--- a/storage/innobase/dict/dict0crea.cc
+++ b/storage/innobase/dict/dict0crea.cc
@@ -319,17 +319,13 @@ dict_build_table_def_step(
 			return(error);
 		}
 
 		mtr_start(&mtr);
 
-		bool res = fsp_header_init(table->space, FIL_IBD_FILE_INITIAL_SIZE, &mtr);
+		fsp_header_init(table->space, FIL_IBD_FILE_INITIAL_SIZE, &mtr);
 
 		mtr_commit(&mtr);
-
-		if (!res) {
-			return (DB_ERROR);
-		}
 	} else {
 		/* Create in the system tablespace: disallow Barracuda
 		features by keeping only the first bit which says whether
 		the row format is redundant or compact */
 		table->flags &= DICT_TF_COMPACT;
```

### `storage/innobase/fil/fil0fil.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/innobase/fil/fil0fil.cc b/storage/innobase/fil/fil0fil.cc
index 9d4a464460f..e19ef110b4f 100644
--- a/storage/innobase/fil/fil0fil.cc
+++ b/storage/innobase/fil/fil0fil.cc
@@ -5810,23 +5810,25 @@ fil_report_invalid_page_access(
 	const char*	space_name,	/*!< in: space name */
 	ulint		byte_offset,	/*!< in: byte offset */
 	ulint		len,		/*!< in: I/O length */
 	ulint		type)		/*!< in: I/O type */
 {
-	fprintf(stderr,
-		"InnoDB: Error: trying to access page number %lu"
-		" in space %lu,\n"
-		"InnoDB: space name %s,\n"
-		"InnoDB: which is outside the tablespace bounds.\n"
-		"InnoDB: Byte offset %lu, len %lu, i/o type %lu.\n"
-		"InnoDB: If you get this error at mysqld startup,"
-		" please check that\n"
-		"InnoDB: your my.cnf matches the ibdata files"
-		" that you have in the\n"
-		"InnoDB: MySQL server.\n",
-		(ulong) block_offset, (ulong) space_id, space_name,
-		(ulong) byte_offset, (ulong) len, (ulong) type);
+	ib_logf(IB_LOG_LEVEL_ERROR,
+		"Trying to access page number " ULINTPF
+		" in space " ULINTPF
+		" space name %s,"
+		" which is outside the tablespace bounds."
+		" Byte offset " ULINTPF ", len " ULINTPF " i/o type " ULINTPF ".",
+		block_offset, space_id, space_name,
+		byte_offset, len, type);
+
+	ib_logf(IB_LOG_LEVEL_FATAL,
+		"If you get this error at mysqld startup,"
+		" please check that"
+		" your my.cnf matches the ibdata files"
+		" that you have in the"
+		" MySQL server.");
 }
 
 /********************************************************************//**
 Find correct node from file space
 @return node */
@@ -6041,15 +6043,14 @@ fil_io(
 	if (!node) {
 		if (ignore_nonexistent_pages) {
 			mutex_exit(&fil_system->mutex);
 			return(DB_ERROR);
 		}
+
 		fil_report_invalid_page_access(
 				block_offset, space_id, space->name,
 				byte_offset, len, type);
-
-		ut_error;
 	}
 
 	/* Open file if closed */
 	if (!fil_node_prepare_for_io(node, fil_system, space)) {
 		if (space->purpose == FIL_TABLESPACE
@@ -6057,14 +6058,15 @@ fil_io(
 			mutex_exit(&fil_system->mutex);
 
 			ib_logf(IB_LOG_LEVEL_ERROR,
 				"Trying to do i/o to a tablespace which "
 				"exists without .ibd data file. "
-				"i/o type %lu, space id %lu, page no %lu, "
-				"i/o length %lu bytes",
-				(ulong) type, (ulong) space_id,
-				(ulong) block_offset, (ulong) len);
+				"i/o type " ULINTPF ", space id "
+				ULINTPF ", page no " ULINTPF ", "
+				"i/o length " ULINTPF " bytes",
+				type, space_id,
+				block_offset, len);
 
 			return(DB_TABLESPACE_DELETED);
 		}
 
 		/* The tablespace is for log. Currently, we just assert here
@@ -6080,12 +6082,10 @@ fil_io(
 	    && space->id != 0 && space->purpose == FIL_TABLESPACE) {
 
 		fil_report_invalid_page_access(
 			block_offset, space_id, space->name, byte_offset,
 			len, type);
-
-		ut_error;
 	}
 
 	/* Now we have made the changes in the data structures of fil_system */
 	mutex_exit(&fil_system->mutex);
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/fil/fil0fil.cc b/storage/innobase/fil/fil0fil.cc
index e19ef110b4f..f88bb2add59 100644
--- a/storage/innobase/fil/fil0fil.cc
+++ b/storage/innobase/fil/fil0fil.cc
@@ -1,9 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1995, 2017, Oracle and/or its affiliates. All Rights Reserved.
-Copyright (c) 2014, 2017, MariaDB Corporation. All Rights Reserved.
+Copyright (c) 2014, 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -5810,25 +5810,23 @@ fil_report_invalid_page_access(
 	const char*	space_name,	/*!< in: space name */
 	ulint		byte_offset,	/*!< in: byte offset */
 	ulint		len,		/*!< in: I/O length */
 	ulint		type)		/*!< in: I/O type */
 {
-	ib_logf(IB_LOG_LEVEL_ERROR,
+	ib_logf(IB_LOG_LEVEL_FATAL,
 		"Trying to access page number " ULINTPF
 		" in space " ULINTPF
 		" space name %s,"
 		" which is outside the tablespace bounds."
-		" Byte offset " ULINTPF ", len " ULINTPF " i/o type " ULINTPF ".",
+		" Byte offset " ULINTPF ", len " ULINTPF
+		" i/o type " ULINTPF ".%s",
 		block_offset, space_id, space_name,
-		byte_offset, len, type);
-
-	ib_logf(IB_LOG_LEVEL_FATAL,
-		"If you get this error at mysqld startup,"
-		" please check that"
-		" your my.cnf matches the ibdata files"
-		" that you have in the"
-		" MySQL server.");
+		byte_offset, len, type,
+		space_id == 0 && !srv_was_started
+		? "Please check that the configuration matches"
+		" the InnoDB system tablespace location (ibdata files)"
+		: "");
 }
 
 /********************************************************************//**
 Find correct node from file space
 @return node */
```

### `storage/innobase/fsp/fsp0fsp.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/innobase/fsp/fsp0fsp.cc b/storage/innobase/fsp/fsp0fsp.cc
index a40283412e2..98cd11f3369 100644
--- a/storage/innobase/fsp/fsp0fsp.cc
+++ b/storage/innobase/fsp/fsp0fsp.cc
@@ -668,20 +668,22 @@ fsp_header_init_fields(
 	mach_write_to_4(FSP_HEADER_OFFSET + FSP_SPACE_FLAGS + page,
 			flags);
 }
 
 #ifndef UNIV_HOTBACKUP
-/**********************************************************************//**
-Initializes the space header of a new created space and creates also the
-insert buffer tree root if space == 0. */
+/** Initializes the space header of a new created space and creates also the
+insert buffer tree root if space == 0.
+@param[in]	space_id	space id
+@param[in]	size		current size in blocks
+@param[in,out]	mtr		min-transaction
+@return	true on success, otherwise false. */
 UNIV_INTERN
-void
+bool
 fsp_header_init(
-/*============*/
-	ulint	space_id,	/*!< in: space id */
-	ulint	size,		/*!< in: current size in blocks */
-	mtr_t*	mtr)		/*!< in/out: mini-transaction */
+	ulint	space_id,
+	ulint	size,
+	mtr_t*	mtr)
 {
 	fsp_header_t*	header;
 	buf_block_t*	block;
 	page_t*		page;
 	ulint		flags;
@@ -720,15 +722,19 @@ fsp_header_init(
 	flst_init(header + FSP_FULL_FRAG, mtr);
 	flst_init(header + FSP_SEG_INODES_FULL, mtr);
 	flst_init(header + FSP_SEG_INODES_FREE, mtr);
 
 	mlog_write_ull(header + FSP_SEG_ID, 1, mtr);
+
 	if (space_id == 0) {
 		fsp_fill_free_list(FALSE, space_id, header, mtr);
-		btr_create(DICT_CLUSTERED | DICT_UNIVERSAL | DICT_IBUF,
+
+		if (btr_create(DICT_CLUSTERED | DICT_UNIVERSAL | DICT_IBUF,
 			   0, 0, DICT_IBUF_ID_MIN + space_id,
-			   dict_ind_redundant, mtr);
+				dict_ind_redundant, mtr) == FIL_NULL) {
+			return (false);
+		}
 	} else {
 		fsp_fill_free_list(TRUE, space_id, header, mtr);
 	}
 
 	fil_space_t* space = fil_space_acquire(space_id);
@@ -737,10 +743,12 @@ fsp_header_init(
 	if (space->crypt_data) {
 		space->crypt_data->write_page0(page, mtr);
 	}
 
 	fil_space_release(space);
+
+	return (true);
 }
 
 #endif /* !UNIV_HOTBACKUP */
 
 /**********************************************************************//**
@@ -2055,19 +2063,25 @@ fseg_create_general(
 
 	if (!has_done_reservation) {
 		success = fsp_reserve_free_extents(&n_reserved, space, 2,
 						   FSP_NORMAL, mtr);
 		if (!success) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Reserving %d free extents failed"
+				" could reserve only " ULINTPF " extents.",
+				2, n_reserved);
 			return(NULL);
 		}
 	}
 
 	space_header = fsp_get_space_header(space, zip_size, mtr);
 
 	inode = fsp_alloc_seg_inode(space_header, mtr);
 
 	if (inode == NULL) {
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Allocation of a new file segment inode page failed.");
 
 		goto funct_exit;
 	}
 
 	/* Read the next segment id from space header and increment the
@@ -2093,10 +2107,13 @@ fseg_create_general(
 	if (page == 0) {
 		block = fseg_alloc_free_page_low(space, zip_size,
 						 inode, 0, FSP_UP, mtr, mtr);
 
 		if (block == NULL) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of a free page from space " ULINTPF " failed.",
+				space);
 
 			fsp_free_seg_inode(space, zip_size, inode, mtr);
 
 			goto funct_exit;
 		}
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/fsp/fsp0fsp.cc b/storage/innobase/fsp/fsp0fsp.cc
index 98cd11f3369..4f05549bc1c 100644
--- a/storage/innobase/fsp/fsp0fsp.cc
+++ b/storage/innobase/fsp/fsp0fsp.cc
@@ -668,22 +668,17 @@ fsp_header_init_fields(
 	mach_write_to_4(FSP_HEADER_OFFSET + FSP_SPACE_FLAGS + page,
 			flags);
 }
 
 #ifndef UNIV_HOTBACKUP
-/** Initializes the space header of a new created space and creates also the
-insert buffer tree root if space == 0.
+/** Initialize a tablespace header.
 @param[in]	space_id	space id
 @param[in]	size		current size in blocks
-@param[in,out]	mtr		min-transaction
-@return	true on success, otherwise false. */
+@param[in,out]	mtr		mini-transaction */
 UNIV_INTERN
-bool
-fsp_header_init(
-	ulint	space_id,
-	ulint	size,
-	mtr_t*	mtr)
+void
+fsp_header_init(ulint space_id, ulint size, mtr_t* mtr)
 {
 	fsp_header_t*	header;
 	buf_block_t*	block;
 	page_t*		page;
 	ulint		flags;
@@ -723,32 +718,20 @@ fsp_header_init(
 	flst_init(header + FSP_SEG_INODES_FULL, mtr);
 	flst_init(header + FSP_SEG_INODES_FREE, mtr);
 
 	mlog_write_ull(header + FSP_SEG_ID, 1, mtr);
 
-	if (space_id == 0) {
-		fsp_fill_free_list(FALSE, space_id, header, mtr);
-
-		if (btr_create(DICT_CLUSTERED | DICT_UNIVERSAL | DICT_IBUF,
-			   0, 0, DICT_IBUF_ID_MIN + space_id,
-				dict_ind_redundant, mtr) == FIL_NULL) {
-			return (false);
-		}
-	} else {
-		fsp_fill_free_list(TRUE, space_id, header, mtr);
-	}
+	fsp_fill_free_list(space_id != TRX_SYS_SPACE, space_id, header, mtr);
 
 	fil_space_t* space = fil_space_acquire(space_id);
 	ut_ad(space);
 
 	if (space->crypt_data) {
 		space->crypt_data->write_page0(page, mtr);
 	}
 
 	fil_space_release(space);
-
-	return (true);
 }
 
 #endif /* !UNIV_HOTBACKUP */
 
 /**********************************************************************//**
@@ -2063,26 +2046,19 @@ fseg_create_general(
 
 	if (!has_done_reservation) {
 		success = fsp_reserve_free_extents(&n_reserved, space, 2,
 						   FSP_NORMAL, mtr);
 		if (!success) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Reserving %d free extents failed"
-				" could reserve only " ULINTPF " extents.",
-				2, n_reserved);
 			return(NULL);
 		}
 	}
 
 	space_header = fsp_get_space_header(space, zip_size, mtr);
 
 	inode = fsp_alloc_seg_inode(space_header, mtr);
 
 	if (inode == NULL) {
-		ib_logf(IB_LOG_LEVEL_ERROR,
-			"Allocation of a new file segment inode page failed.");
-
 		goto funct_exit;
 	}
 
 	/* Read the next segment id from space header and increment the
 	value in space header */
@@ -2107,13 +2083,10 @@ fseg_create_general(
 	if (page == 0) {
 		block = fseg_alloc_free_page_low(space, zip_size,
 						 inode, 0, FSP_UP, mtr, mtr);
 
 		if (block == NULL) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of a free page from space " ULINTPF " failed.",
-				space);
 
 			fsp_free_seg_inode(space, zip_size, inode, mtr);
 
 			goto funct_exit;
 		}
```

### `storage/innobase/handler/ha_innodb.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/innobase/handler/ha_innodb.cc b/storage/innobase/handler/ha_innodb.cc
index 012539d1ace..b68a96c8846 100644
--- a/storage/innobase/handler/ha_innodb.cc
+++ b/storage/innobase/handler/ha_innodb.cc
@@ -3351,10 +3351,11 @@ innobase_init(
 	int		err;
 	bool		ret;
 	char		*default_path;
 	uint		format_id;
 	ulong		num_pll_degree;
+	ulint		min_size = 0;
 
 	DBUG_ENTER("innobase_init");
 	handlerton *innobase_hton= (handlerton*) p;
 	innodb_hton_ptr = innobase_hton;
 
@@ -3561,10 +3562,23 @@ mem_free_and_error:
 		srv_free_paths_and_sizes();
 		my_free(internal_innobase_data_file_path);
 		goto error;
 	}
 
+	/* All doublewrite buffer pages must fit to first system
+	datafile and first datafile must be at least 3M. */
+	min_size = ut_max((3*1024*1024U), (192U*UNIV_PAGE_SIZE));
+
+	if ((srv_data_file_sizes[0]*1024*1024) < min_size) {
+		sql_print_error(
+			"InnoDB: first datafile is too small current=" ULINTPF
+			"M it should be at least " ULINTPF "M.",
+			srv_data_file_sizes[0],
+			min_size / (1024 * 1024));
+		goto mem_free_and_error;
+	}
+
 	/* -------------- All log files ---------------------------*/
 
 	/* The default dir for log files is the datadir of MySQL */
 
 	if (!srv_log_group_home_dir) {
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/handler/ha_innodb.cc b/storage/innobase/handler/ha_innodb.cc
index b68a96c8846..012539d1ace 100644
--- a/storage/innobase/handler/ha_innodb.cc
+++ b/storage/innobase/handler/ha_innodb.cc
@@ -3351,11 +3351,10 @@ innobase_init(
 	int		err;
 	bool		ret;
 	char		*default_path;
 	uint		format_id;
 	ulong		num_pll_degree;
-	ulint		min_size = 0;
 
 	DBUG_ENTER("innobase_init");
 	handlerton *innobase_hton= (handlerton*) p;
 	innodb_hton_ptr = innobase_hton;
 
@@ -3562,23 +3561,10 @@ mem_free_and_error:
 		srv_free_paths_and_sizes();
 		my_free(internal_innobase_data_file_path);
 		goto error;
 	}
 
-	/* All doublewrite buffer pages must fit to first system
-	datafile and first datafile must be at least 3M. */
-	min_size = ut_max((3*1024*1024U), (192U*UNIV_PAGE_SIZE));
-
-	if ((srv_data_file_sizes[0]*1024*1024) < min_size) {
-		sql_print_error(
-			"InnoDB: first datafile is too small current=" ULINTPF
-			"M it should be at least " ULINTPF "M.",
-			srv_data_file_sizes[0],
-			min_size / (1024 * 1024));
-		goto mem_free_and_error;
-	}
-
 	/* -------------- All log files ---------------------------*/
 
 	/* The default dir for log files is the datadir of MySQL */
 
 	if (!srv_log_group_home_dir) {
```

### `storage/innobase/include/buf0dblwr.h`

```diff
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/include/buf0dblwr.h b/storage/innobase/include/buf0dblwr.h
index 8e1b00db83c..7b7464761cc 100644
--- a/storage/innobase/include/buf0dblwr.h
+++ b/storage/innobase/include/buf0dblwr.h
@@ -1,9 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1995, 2017, Oracle and/or its affiliates. All Rights Reserved.
-Copyright (c) 2017, MariaDB Corporation. All Rights Reserved.
+Copyright (c) 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -37,17 +37,19 @@ Created 2011/12/19 Inaam Rana
 /** Doublewrite system */
 extern buf_dblwr_t*	buf_dblwr;
 /** Set to TRUE when the doublewrite buffer is being created */
 extern ibool		buf_dblwr_being_created;
 
-/****************************************************************//**
-Creates the doublewrite buffer to a new InnoDB installation. The header of the
-doublewrite buffer is placed on the trx system header page. */
+/** Create the doublewrite buffer if the doublewrite buffer header
+is not present in the TRX_SYS page.
+@return	whether the operation succeeded
+@retval	true	if the doublewrite buffer exists or was created
+@retval	false	if the creation failed (too small first data file) */
 UNIV_INTERN
-void
-buf_dblwr_create(void);
-/*==================*/
+bool
+buf_dblwr_create()
+	MY_ATTRIBUTE((warn_unused_result));
 
 /****************************************************************//**
 At a database startup initializes the doublewrite buffer memory structure if
 we already have a doublewrite buffer created in the data files. If we are
 upgrading to an InnoDB version which supports multiple tablespaces, then this
```

### `storage/innobase/include/fsp0fsp.h`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/innobase/include/fsp0fsp.h b/storage/innobase/include/fsp0fsp.h
index 2a162100dc1..905e98cc1e6 100644
--- a/storage/innobase/include/fsp0fsp.h
+++ b/storage/innobase/include/fsp0fsp.h
@@ -518,20 +518,24 @@ fsp_header_init_fields(
 /*===================*/
 	page_t*	page,		/*!< in/out: first page in the space */
 	ulint	space_id,	/*!< in: space id */
 	ulint	flags);		/*!< in: tablespace flags (FSP_SPACE_FLAGS):
 				0, or table->flags if newer than COMPACT */
-/**********************************************************************//**
-Initializes the space header of a new created space and creates also the
-insert buffer tree root if space == 0. */
+/** Initializes the space header of a new created space and creates also the
+insert buffer tree root if space == 0.
+@param[in]	space_id	space id
+@param[in]	size		current size in blocks
+@param[in,out]	mtr		min-transaction
+@return	true on success, otherwise false. */
 UNIV_INTERN
-void
+bool
 fsp_header_init(
-/*============*/
-	ulint	space,		/*!< in: space id */
-	ulint	size,		/*!< in: current size in blocks */
-	mtr_t*	mtr);		/*!< in/out: mini-transaction */
+	ulint	space_id,
+	ulint	size,
+	mtr_t*	mtr)
+	MY_ATTRIBUTE((warn_unused_result));
+
 /**********************************************************************//**
 Increases the space size field of a space. */
 UNIV_INTERN
 void
 fsp_header_inc_size(
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/include/fsp0fsp.h b/storage/innobase/include/fsp0fsp.h
index 905e98cc1e6..d8d044ba2ec 100644
--- a/storage/innobase/include/fsp0fsp.h
+++ b/storage/innobase/include/fsp0fsp.h
@@ -518,23 +518,17 @@ fsp_header_init_fields(
 /*===================*/
 	page_t*	page,		/*!< in/out: first page in the space */
 	ulint	space_id,	/*!< in: space id */
 	ulint	flags);		/*!< in: tablespace flags (FSP_SPACE_FLAGS):
 				0, or table->flags if newer than COMPACT */
-/** Initializes the space header of a new created space and creates also the
-insert buffer tree root if space == 0.
+/** Initialize a tablespace header.
 @param[in]	space_id	space id
 @param[in]	size		current size in blocks
-@param[in,out]	mtr		min-transaction
-@return	true on success, otherwise false. */
+@param[in,out]	mtr		mini-transaction */
 UNIV_INTERN
-bool
-fsp_header_init(
-	ulint	space_id,
-	ulint	size,
-	mtr_t*	mtr)
-	MY_ATTRIBUTE((warn_unused_result));
+void
+fsp_header_init(ulint space_id, ulint size, mtr_t* mtr);
 
 /**********************************************************************//**
 Increases the space size field of a space. */
 UNIV_INTERN
 void
```

### `storage/innobase/include/trx0rseg.h`

```diff
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/include/trx0rseg.h b/storage/innobase/include/trx0rseg.h
index 185b05876b4..2fe5df14cee 100644
--- a/storage/innobase/include/trx0rseg.h
+++ b/storage/innobase/include/trx0rseg.h
@@ -1,8 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1996, 2011, Oracle and/or its affiliates. All Rights Reserved.
+Copyright (c) 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -122,17 +123,17 @@ UNIV_INTERN
 void
 trx_rseg_mem_free(
 /*==============*/
 	trx_rseg_t*	rseg);		/*!< in, own: instance to free */
 
-/*********************************************************************
-Creates a rollback segment. */
+/** Create a rollback segment.
+@param[in]	space	undo tablespace ID
+@return pointer to new rollback segment
+@retval	NULL	on failure */
 UNIV_INTERN
 trx_rseg_t*
-trx_rseg_create(
-/*============*/
-	ulint	space);			/*!< in: id of UNDO tablespace */
+trx_rseg_create(ulint space);
 
 /********************************************************************
 Get the number of unique rollback tablespaces in use except space id 0.
 The last space id will be the sentinel value ULINT_UNDEFINED. The array
 will be sorted on space id. Note: space_ids should have have space for
```

### `storage/innobase/log/log0recv.cc`

```diff
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/log/log0recv.cc b/storage/innobase/log/log0recv.cc
index bf00cd8e8d9..4e6e66e808e 100644
--- a/storage/innobase/log/log0recv.cc
+++ b/storage/innobase/log/log0recv.cc
@@ -2912,15 +2912,10 @@ recv_init_crash_recovery(void)
 	check if there are half-written pages in data files,
 	and restore them from the doublewrite buffer if
 	possible */
 
 	if (srv_force_recovery < SRV_FORCE_NO_LOG_REDO) {
-
-		ib_logf(IB_LOG_LEVEL_INFO,
-			"Restoring possible half-written data pages "
-			"from the doublewrite buffer...");
-
 		buf_dblwr_process();
 
 		/* Spawn the background thread to flush dirty pages
 		from the buffer pools. */
 		recv_writer_thread_active = true;
@@ -3177,28 +3172,10 @@ recv_recovery_from_checkpoint_start_func(
 		/* NOTE: we always do a 'recovery' at startup, but only if
 		there is something wrong we will print a message to the
 		user about recovery: */
 
 		if (checkpoint_lsn != flushed_lsn) {
-
-			if (checkpoint_lsn < flushed_lsn) {
-
-				ib_logf(IB_LOG_LEVEL_WARN,
-					"The log sequence number "
-					"in the ibdata files is higher "
-					"than the log sequence number "
-					"in the ib_logfiles! Are you sure "
-					"you are using the right "
-					"ib_logfiles to start up the database. "
-					"Log sequence number in the "
-					"ib_logfiles is " LSN_PF ", log"
-					"sequence number stamped "
-					"to ibdata file header is " LSN_PF ".",
-					checkpoint_lsn,
-					flushed_lsn);
-			}
-
 			if (!recv_needed_recovery) {
 				ib_logf(IB_LOG_LEVEL_INFO,
 					"The log sequence number "
 					LSN_PF
 					" in ibdata file do not match"
```

### `storage/innobase/row/row0mysql.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/innobase/row/row0mysql.cc b/storage/innobase/row/row0mysql.cc
index 82938995e93..6ca9443dc7d 100644
--- a/storage/innobase/row/row0mysql.cc
+++ b/storage/innobase/row/row0mysql.cc
@@ -3588,13 +3588,19 @@ row_truncate_table_for_mysql(
 				index->space = space_id;
 				index = dict_table_get_next_index(index);
 			} while (index);
 
 			mtr_start_trx(&mtr, trx);
-			fsp_header_init(space_id,
+			bool ret = fsp_header_init(space_id,
 					FIL_IBD_FILE_INITIAL_SIZE, &mtr);
 			mtr_commit(&mtr);
+
+			if (!ret) {
+				table->file_unreadable = true;
+				err = DB_ERROR;
+				goto funct_exit;
+			}
 		}
 	} else {
 		/* Lock all index trees for this table, as we will
 		truncate the table/index and possibly change their metadata.
 		All DML/DDL are blocked by table level lock, with
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/row/row0mysql.cc b/storage/innobase/row/row0mysql.cc
index 6ca9443dc7d..82938995e93 100644
--- a/storage/innobase/row/row0mysql.cc
+++ b/storage/innobase/row/row0mysql.cc
@@ -3588,19 +3588,13 @@ row_truncate_table_for_mysql(
 				index->space = space_id;
 				index = dict_table_get_next_index(index);
 			} while (index);
 
 			mtr_start_trx(&mtr, trx);
-			bool ret = fsp_header_init(space_id,
+			fsp_header_init(space_id,
 					FIL_IBD_FILE_INITIAL_SIZE, &mtr);
 			mtr_commit(&mtr);
-
-			if (!ret) {
-				table->file_unreadable = true;
-				err = DB_ERROR;
-				goto funct_exit;
-			}
 		}
 	} else {
 		/* Lock all index trees for this table, as we will
 		truncate the table/index and possibly change their metadata.
 		All DML/DDL are blocked by table level lock, with
```

### `storage/innobase/srv/srv0start.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/innobase/srv/srv0start.cc b/storage/innobase/srv/srv0start.cc
index f601ff17ebc..032b902c633 100644
--- a/storage/innobase/srv/srv0start.cc
+++ b/storage/innobase/srv/srv0start.cc
@@ -186,10 +186,43 @@ UNIV_INTERN mysql_pfs_key_t	srv_error_monitor_thread_key;
 UNIV_INTERN mysql_pfs_key_t	srv_monitor_thread_key;
 UNIV_INTERN mysql_pfs_key_t	srv_master_thread_key;
 UNIV_INTERN mysql_pfs_key_t	srv_purge_thread_key;
 #endif /* UNIV_PFS_THREAD */
 
+/** Innobase start-up aborted. Perform cleanup actions.
+@param[in]	create_new_db	TRUE if new db is  being created
+@param[in]	file		File name
+@param[in]	line		Line number
+@param[in]	err		Reason for aborting InnoDB startup
+@return DB_SUCCESS or error code. */
+static
+dberr_t
+srv_init_abort(
+	bool		create_new_db,
+	const char*	file,
+	ulint		line,
+	dberr_t		err)
+{
+	if (create_new_db) {
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Database creation was aborted"
+			" at %s [" ULINTPF "]"
+			" with error %s. You may need"
+			" to delete the ibdata1 file before trying to start"
+			" up again.",
+			file, line, ut_strerr(err));
+	} else {
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Plugin initialization aborted"
+			" at %s [" ULINTPF "]"
+			" with error %s.",
+			file, line, ut_strerr(err));
+	}
+
+	return(err);
+}
+
 /*********************************************************************//**
 Convert a numeric string that optionally ends in G or M or K, to a number
 containing megabytes.
 @return	next character in string */
 static
@@ -1526,22 +1559,30 @@ srv_undo_tablespaces_init(
 		}
 	}
 
 	if (create_new_db) {
 		mtr_t	mtr;
+		bool ret=true;
 
 		mtr_start(&mtr);
 
 		/* The undo log tablespace */
 		for (i = 0; i < n_undo_tablespaces; ++i) {
 
-			fsp_header_init(
+			ret = fsp_header_init(
 				undo_tablespace_ids[i],
 				SRV_UNDO_TABLESPACE_SIZE_IN_PAGES, &mtr);
+			if (!ret) {
+				break;
+			}
 		}
 
 		mtr_commit(&mtr);
+
+		if (!ret) {
+			return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
+		}
 	}
 
 	return(DB_SUCCESS);
 }
 
@@ -2376,14 +2417,18 @@ files_checked:
 	if (create_new_db) {
 		ut_a(!srv_read_only_mode);
 
 		mtr_start(&mtr);
 
-		fsp_header_init(0, sum_of_new_sizes, &mtr);
+		bool ret = fsp_header_init(0, sum_of_new_sizes, &mtr);
 
 		mtr_commit(&mtr);
 
+		if (!ret) {
+			return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
+		}
+
 		/* To maintain backward compatibility we create only
 		the first rollback segment before the double write buffer.
 		All the remaining rollback segments will be created later,
 		after the double write buffer has been created. */
 		trx_sys_create_sys_pages();
@@ -2807,10 +2852,13 @@ files_checked:
 
 	if (srv_available_undo_logs == ULINT_UNDEFINED) {
 		/* Can only happen if server is read only. */
 		ut_a(srv_read_only_mode);
 		srv_undo_logs = ULONG_UNDEFINED;
+	} else if (srv_available_undo_logs < srv_undo_logs) {
+		/* Should due to out of file space. */
+		return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
 	}
 
 	if (!srv_read_only_mode) {
 		/* Create the thread which watches the timeouts
 		for lock waits */
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/srv/srv0start.cc b/storage/innobase/srv/srv0start.cc
index 4e59ddd1f87..c7026b4f04a 100644
--- a/storage/innobase/srv/srv0start.cc
+++ b/storage/innobase/srv/srv0start.cc
@@ -1559,30 +1559,22 @@ srv_undo_tablespaces_init(
 		}
 	}
 
 	if (create_new_db) {
 		mtr_t	mtr;
-		bool ret=true;
 
 		mtr_start(&mtr);
 
 		/* The undo log tablespace */
 		for (i = 0; i < n_undo_tablespaces; ++i) {
 
-			ret = fsp_header_init(
+			fsp_header_init(
 				undo_tablespace_ids[i],
 				SRV_UNDO_TABLESPACE_SIZE_IN_PAGES, &mtr);
-			if (!ret) {
-				break;
-			}
 		}
 
 		mtr_commit(&mtr);
-
-		if (!ret) {
-			return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
-		}
 	}
 
 	return(DB_SUCCESS);
 }
 
@@ -2417,18 +2409,28 @@ files_checked:
 	if (create_new_db) {
 		ut_a(!srv_read_only_mode);
 
 		mtr_start(&mtr);
 
-		bool ret = fsp_header_init(0, sum_of_new_sizes, &mtr);
+		fsp_header_init(0, sum_of_new_sizes, &mtr);
+		compile_time_assert(TRX_SYS_SPACE == 0);
+		compile_time_assert(IBUF_SPACE_ID == 0);
+
+		ulint ibuf_root = btr_create(
+			DICT_CLUSTERED | DICT_UNIVERSAL | DICT_IBUF,
+			0, 0, DICT_IBUF_ID_MIN,
+			dict_ind_redundant, &mtr);
 
 		mtr_commit(&mtr);
 
-		if (!ret) {
-			return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
+		if (ibuf_root == FIL_NULL) {
+			return(srv_init_abort(true, __FILE__, __LINE__,
+					      DB_ERROR));
 		}
 
+		ut_ad(ibuf_root == IBUF_TREE_ROOT_PAGE_NO);
+
 		/* To maintain backward compatibility we create only
 		the first rollback segment before the double write buffer.
 		All the remaining rollback segments will be created later,
 		after the double write buffer has been created. */
 		trx_sys_create_sys_pages();
@@ -2810,14 +2812,13 @@ files_checked:
 #endif /* UNIV_LOG_ARCHIVE */
 
 	/* fprintf(stderr, "Max allowed record size %lu\n",
 	page_get_free_space_of_empty() / 2); */
 
-	if (buf_dblwr == NULL) {
-		/* Create the doublewrite buffer to a new tablespace */
-
-		buf_dblwr_create();
+	if (!buf_dblwr_create()) {
+		return(srv_init_abort(create_new_db, __FILE__, __LINE__,
+				      DB_ERROR));
 	}
 
 	/* Here the double write buffer has already been created and so
 	any new rollback segments will be allocated after the double
 	write buffer. The default segment should already exist.
```

### `storage/innobase/trx/trx0rseg.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/innobase/trx/trx0rseg.cc b/storage/innobase/trx/trx0rseg.cc
index 003d1036a8c..21dbab98e48 100644
--- a/storage/innobase/trx/trx0rseg.cc
+++ b/storage/innobase/trx/trx0rseg.cc
@@ -321,11 +321,14 @@ trx_rseg_create(
 		trx_sysf_t*	sys_header;
 
 		page_no = trx_rseg_header_create(
 			space, 0, ULINT_MAX, slot_no, &mtr);
 
-		ut_a(page_no != FIL_NULL);
+		if (page_no == FIL_NULL) {
+			mtr_commit(&mtr);
+			return (rseg);
+		}
 
 		sys_header = trx_sysf_get(&mtr);
 
 		id = trx_sysf_rseg_get_space(sys_header, slot_no, &mtr);
 		ut_a(id == space);
--- from commit fbeb9489cd7d ---
diff --git a/storage/innobase/trx/trx0rseg.cc b/storage/innobase/trx/trx0rseg.cc
index 21dbab98e48..16fa334872b 100644
--- a/storage/innobase/trx/trx0rseg.cc
+++ b/storage/innobase/trx/trx0rseg.cc
@@ -1,8 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1996, 2011, Oracle and/or its affiliates. All Rights Reserved.
+Copyright (c) 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -291,18 +292,17 @@ trx_rseg_create_instance(
 			ut_a(trx_sys->rseg_array[i] == NULL);
 		}
 	}
 }
 
-/*********************************************************************
-Creates a rollback segment.
-@return pointer to new rollback segment if create successful */
+/** Create a rollback segment.
+@param[in]	space	undo tablespace ID
+@return pointer to new rollback segment
+@retval	NULL	on failure */
 UNIV_INTERN
 trx_rseg_t*
-trx_rseg_create(
-/*============*/
-	ulint		space)		/*!< in: id of UNDO tablespace */
+trx_rseg_create(ulint space)
 {
 	mtr_t		mtr;
 	ulint		slot_no;
 	trx_rseg_t*	rseg = NULL;
 
@@ -321,29 +321,25 @@ trx_rseg_create(
 		trx_sysf_t*	sys_header;
 
 		page_no = trx_rseg_header_create(
 			space, 0, ULINT_MAX, slot_no, &mtr);
 
-		if (page_no == FIL_NULL) {
-			mtr_commit(&mtr);
-			return (rseg);
-		}
-
-		sys_header = trx_sysf_get(&mtr);
+		if (page_no != FIL_NULL) {
+			sys_header = trx_sysf_get(&mtr);
 
-		id = trx_sysf_rseg_get_space(sys_header, slot_no, &mtr);
-		ut_a(id == space);
+			id = trx_sysf_rseg_get_space(sys_header, slot_no, &mtr);
+			ut_a(id == space);
 
-		zip_size = space ? fil_space_get_zip_size(space) : 0;
+			zip_size = space ? fil_space_get_zip_size(space) : 0;
 
-		rseg = trx_rseg_mem_create(
-			slot_no, space, zip_size, page_no,
-			purge_sys->ib_bh, &mtr);
+			rseg = trx_rseg_mem_create(
+				slot_no, space, zip_size, page_no,
+				purge_sys->ib_bh, &mtr);
+		}
 	}
 
 	mtr_commit(&mtr);
-
 	return(rseg);
 }
 
 /*********************************************************************//**
 Creates the memory copies for rollback segments and initializes the
```

### `storage/xtradb/btr/btr0btr.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/xtradb/btr/btr0btr.cc b/storage/xtradb/btr/btr0btr.cc
index d84c93f8b3e..7b5b3bb6cba 100644
--- a/storage/xtradb/btr/btr0btr.cc
+++ b/storage/xtradb/btr/btr0btr.cc
@@ -1718,10 +1718,16 @@ btr_create(
 		/* Allocate first the ibuf header page */
 		buf_block_t*	ibuf_hdr_block = fseg_create(
 			space, 0,
 			IBUF_HEADER + IBUF_TREE_SEG_HEADER, mtr);
 
+		if (ibuf_hdr_block == NULL) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of the first ibuf header page failed.");
+			return (FIL_NULL);
+		}
+
 		buf_block_dbg_add_level(
 			ibuf_hdr_block, SYNC_IBUF_TREE_NODE_NEW);
 
 		ut_ad(buf_block_get_page_no(ibuf_hdr_block)
 		      == IBUF_HEADER_PAGE_NO);
@@ -1731,10 +1737,15 @@ btr_create(
 		block = fseg_alloc_free_page(
 			buf_block_get_frame(ibuf_hdr_block)
 			+ IBUF_HEADER + IBUF_TREE_SEG_HEADER,
 			IBUF_TREE_ROOT_PAGE_NO,
 			FSP_UP, mtr);
+
+		if (!block) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of the tree root page segment failed.");
+		}
 		ut_ad(buf_block_get_page_no(block) == IBUF_TREE_ROOT_PAGE_NO);
 	} else {
 #ifdef UNIV_BLOB_DEBUG
 		if ((type & DICT_CLUSTERED) && !index->blobs) {
 			mutex_create(PFS_NOT_INSTRUMENTED,
@@ -1743,10 +1754,16 @@ btr_create(
 						  btr_blob_dbg_cmp);
 		}
 #endif /* UNIV_BLOB_DEBUG */
 		block = fseg_create(space, 0,
 				    PAGE_HEADER + PAGE_BTR_SEG_TOP, mtr);
+
+		if (!block) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of the btree segment failed.");
+		}
+
 	}
 
 	if (block == NULL) {
 
 		return(FIL_NULL);
@@ -1771,10 +1788,12 @@ btr_create(
 				 PAGE_HEADER + PAGE_BTR_SEG_LEAF, mtr)) {
 			/* Not enough space for new segment, free root
 			segment before return. */
 			btr_free_root(space, zip_size, page_no, mtr);
 
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of the non-ibuf tree segment for leaf pages failed.");
 			return(FIL_NULL);
 		}
 
 		/* The fseg create acquires a second latch on the page,
 		therefore we must declare it: */
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/btr/btr0btr.cc b/storage/xtradb/btr/btr0btr.cc
index 7b5b3bb6cba..e66599e206d 100644
--- a/storage/xtradb/btr/btr0btr.cc
+++ b/storage/xtradb/btr/btr0btr.cc
@@ -1,10 +1,10 @@
 /*****************************************************************************
 
 Copyright (c) 1994, 2016, Oracle and/or its affiliates. All Rights Reserved.
 Copyright (c) 2012, Facebook Inc.
-Copyright (c) 2014, 2017, MariaDB Corporation
+Copyright (c) 2014, 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -1701,13 +1701,11 @@ btr_create(
 				or 0 for uncompressed pages */
 	index_id_t	index_id,/*!< in: index id */
 	dict_index_t*	index,	/*!< in: index */
 	mtr_t*		mtr)	/*!< in: mini-transaction handle */
 {
-	ulint		page_no;
 	buf_block_t*	block;
-	buf_frame_t*	frame;
 	page_t*		page;
 	page_zip_des_t*	page_zip;
 
 	/* Create the two new segments (one, in the case of an ibuf tree) for
 	the index tree; the segment headers are put on the allocated root page
@@ -1719,13 +1717,11 @@ btr_create(
 		buf_block_t*	ibuf_hdr_block = fseg_create(
 			space, 0,
 			IBUF_HEADER + IBUF_TREE_SEG_HEADER, mtr);
 
 		if (ibuf_hdr_block == NULL) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of the first ibuf header page failed.");
-			return (FIL_NULL);
+			return(FIL_NULL);
 		}
 
 		buf_block_dbg_add_level(
 			ibuf_hdr_block, SYNC_IBUF_TREE_NODE_NEW);
 
@@ -1738,15 +1734,20 @@ btr_create(
 			buf_block_get_frame(ibuf_hdr_block)
 			+ IBUF_HEADER + IBUF_TREE_SEG_HEADER,
 			IBUF_TREE_ROOT_PAGE_NO,
 			FSP_UP, mtr);
 
-		if (!block) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of the tree root page segment failed.");
+		if (block == NULL) {
+			return(FIL_NULL);
 		}
+
 		ut_ad(buf_block_get_page_no(block) == IBUF_TREE_ROOT_PAGE_NO);
+
+		buf_block_dbg_add_level(block, SYNC_IBUF_TREE_NODE_NEW);
+
+		flst_init(block->frame + PAGE_HEADER + PAGE_BTR_IBUF_FREE_LIST,
+			  mtr);
 	} else {
 #ifdef UNIV_BLOB_DEBUG
 		if ((type & DICT_CLUSTERED) && !index->blobs) {
 			mutex_create(PFS_NOT_INSTRUMENTED,
 				     &index->blobs_mutex, SYNC_ANY_LATCH);
@@ -1755,45 +1756,22 @@ btr_create(
 		}
 #endif /* UNIV_BLOB_DEBUG */
 		block = fseg_create(space, 0,
 				    PAGE_HEADER + PAGE_BTR_SEG_TOP, mtr);
 
-		if (!block) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of the btree segment failed.");
+		if (block == NULL) {
+			return(FIL_NULL);
 		}
 
-	}
-
-	if (block == NULL) {
-
-		return(FIL_NULL);
-	}
-
-	page_no = buf_block_get_page_no(block);
-	frame = buf_block_get_frame(block);
-
-	if (type & DICT_IBUF) {
-		/* It is an insert buffer tree: initialize the free list */
-		buf_block_dbg_add_level(block, SYNC_IBUF_TREE_NODE_NEW);
-
-		ut_ad(page_no == IBUF_TREE_ROOT_PAGE_NO);
-
-		flst_init(frame + PAGE_HEADER + PAGE_BTR_IBUF_FREE_LIST, mtr);
-	} else {
-		/* It is a non-ibuf tree: create a file segment for leaf
-		pages */
 		buf_block_dbg_add_level(block, SYNC_TREE_NODE_NEW);
 
-		if (!fseg_create(space, page_no,
+		if (!fseg_create(space, buf_block_get_page_no(block),
 				 PAGE_HEADER + PAGE_BTR_SEG_LEAF, mtr)) {
 			/* Not enough space for new segment, free root
 			segment before return. */
-			btr_free_root(space, zip_size, page_no, mtr);
-
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of the non-ibuf tree segment for leaf pages failed.");
+			btr_free_root(space, zip_size,
+				      buf_block_get_page_no(block), mtr);
 			return(FIL_NULL);
 		}
 
 		/* The fseg create acquires a second latch on the page,
 		therefore we must declare it: */
@@ -1833,11 +1811,11 @@ btr_create(
 	allowed size fit on the root page: this fact is needed to ensure
 	correctness of split algorithms */
 
 	ut_ad(page_get_max_insert_size(page, 2) > 2 * BTR_PAGE_MAX_REC_SIZE);
 
-	return(page_no);
+	return(buf_block_get_page_no(block));
 }
 
 /************************************************************//**
 Frees a B-tree except the root page, which MUST be freed after this
 by calling btr_free_root. */
```

### `storage/xtradb/buf/buf0dblwr.cc`

```diff
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/buf/buf0dblwr.cc b/storage/xtradb/buf/buf0dblwr.cc
index c0c52deb57f..49371f9a6f1 100644
--- a/storage/xtradb/buf/buf0dblwr.cc
+++ b/storage/xtradb/buf/buf0dblwr.cc
@@ -173,17 +173,18 @@ buf_dblwr_init(
 
 	buf_dblwr->buf_block_arr = static_cast<buf_page_t**>(
 		mem_zalloc(buf_size * sizeof(void*)));
 }
 
-/****************************************************************//**
-Creates the doublewrite buffer to a new InnoDB installation. The header of the
-doublewrite buffer is placed on the trx system header page. */
+/** Create the doublewrite buffer if the doublewrite buffer header
+is not present in the TRX_SYS page.
+@return	whether the operation succeeded
+@retval	true	if the doublewrite buffer exists or was created
+@retval	false	if the creation failed (too small first data file) */
 UNIV_INTERN
-void
-buf_dblwr_create(void)
-/*==================*/
+bool
+buf_dblwr_create()
 {
 	buf_block_t*	block2;
 	buf_block_t*	new_block;
 	byte*	doublewrite;
 	byte*	fseg_header;
@@ -192,12 +193,11 @@ buf_dblwr_create(void)
 	ulint	i;
 	mtr_t	mtr;
 
 	if (buf_dblwr) {
 		/* Already inited */
-
-		return;
+		return(true);
 	}
 
 start_again:
 	mtr_start(&mtr);
 	buf_dblwr_being_created = TRUE;
@@ -211,43 +211,63 @@ start_again:
 
 		buf_dblwr_init(doublewrite);
 
 		mtr_commit(&mtr);
 		buf_dblwr_being_created = FALSE;
-		return;
+		return(true);
 	}
 
-	ib_logf(IB_LOG_LEVEL_INFO,
-		"Doublewrite buffer not found: creating new");
-
 	if (buf_pool_get_curr_size()
 	    < ((TRX_SYS_DOUBLEWRITE_BLOCKS * TRX_SYS_DOUBLEWRITE_BLOCK_SIZE
 		+ FSP_EXTENT_SIZE / 2 + 100)
 	       * UNIV_PAGE_SIZE)) {
 
-		ib_logf(IB_LOG_LEVEL_FATAL,
-			"Cannot create doublewrite buffer: you must "
-			"increase your buffer pool size. Cannot continue "
-			"operation.");
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Cannot create doublewrite buffer: "
+			"innodb_buffer_pool_size is too small.");
+		mtr_commit(&mtr);
+		return(false);
+	} else {
+		fil_space_t* space = fil_space_acquire(TRX_SYS_SPACE);
+		const bool fail = UT_LIST_GET_FIRST(space->chain)->size
+			< 3 * FSP_EXTENT_SIZE;
+		fil_space_release(space);
+
+		if (fail) {
+			goto too_small;
+		}
 	}
 
 	block2 = fseg_create(TRX_SYS_SPACE, TRX_SYS_PAGE_NO,
 			     TRX_SYS_DOUBLEWRITE
 			     + TRX_SYS_DOUBLEWRITE_FSEG, &mtr);
 
+	if (block2 == NULL) {
+too_small:
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Cannot create doublewrite buffer: "
+			"the first file in innodb_data_file_path"
+			" must be at least %luM.",
+			3 * (FSP_EXTENT_SIZE * UNIV_PAGE_SIZE) >> 20);
+		mtr_commit(&mtr);
+		return(false);
+	}
+
+	ib_logf(IB_LOG_LEVEL_INFO,
+		"Doublewrite buffer not found: creating new");
+
+	/* FIXME: After this point, the doublewrite buffer creation
+	is not atomic. The doublewrite buffer should not exist in
+	the InnoDB system tablespace file in the first place.
+	It could be located in separate optional file(s) in a
+	user-specified location. */
+
 	/* fseg_create acquires a second latch on the page,
 	therefore we must declare it: */
 
 	buf_block_dbg_add_level(block2, SYNC_NO_ORDER_CHECK);
 
-	if (block2 == NULL) {
-		ib_logf(IB_LOG_LEVEL_FATAL,
-			"Cannot create doublewrite buffer: you must "
-			"increase your tablespace size. "
-			"Cannot continue operation.");
-	}
-
 	fseg_header = doublewrite + TRX_SYS_DOUBLEWRITE_FSEG;
 	prev_page_no = 0;
 
 	for (i = 0; i < TRX_SYS_DOUBLEWRITE_BLOCKS * TRX_SYS_DOUBLEWRITE_BLOCK_SIZE
 		     + FSP_EXTENT_SIZE / 2; i++) {
@@ -480,10 +500,18 @@ buf_dblwr_process()
 	byte*	page;
 	byte*	read_buf;
 	byte*	unaligned_read_buf;
 	recv_dblwr_t& recv_dblwr = recv_sys->dblwr;
 
+	if (!buf_dblwr) {
+		return;
+	}
+
+	ib_logf(IB_LOG_LEVEL_INFO,
+		"Restoring possible half-written data pages "
+		"from the doublewrite buffer...");
+
 	unaligned_read_buf = static_cast<byte*>(ut_malloc(2 * UNIV_PAGE_SIZE));
 
 	read_buf = static_cast<byte*>(
 		ut_align(unaligned_read_buf, UNIV_PAGE_SIZE));
```

### `storage/xtradb/dict/dict0crea.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/xtradb/dict/dict0crea.cc b/storage/xtradb/dict/dict0crea.cc
index 6d5b12474eb..faaa6d1bdc7 100644
--- a/storage/xtradb/dict/dict0crea.cc
+++ b/storage/xtradb/dict/dict0crea.cc
@@ -321,13 +321,17 @@ dict_build_table_def_step(
 			return(error);
 		}
 
 		mtr_start(&mtr);
 
-		fsp_header_init(table->space, FIL_IBD_FILE_INITIAL_SIZE, &mtr);
+		bool res = fsp_header_init(table->space, FIL_IBD_FILE_INITIAL_SIZE, &mtr);
 
 		mtr_commit(&mtr);
+
+		if(!res) {
+			return (DB_ERROR);
+		}
 	} else {
 		/* Create in the system tablespace: disallow Barracuda
 		features by keeping only the first bit which says whether
 		the row format is redundant or compact */
 		table->flags &= DICT_TF_COMPACT;
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/dict/dict0crea.cc b/storage/xtradb/dict/dict0crea.cc
index faaa6d1bdc7..6d5b12474eb 100644
--- a/storage/xtradb/dict/dict0crea.cc
+++ b/storage/xtradb/dict/dict0crea.cc
@@ -321,17 +321,13 @@ dict_build_table_def_step(
 			return(error);
 		}
 
 		mtr_start(&mtr);
 
-		bool res = fsp_header_init(table->space, FIL_IBD_FILE_INITIAL_SIZE, &mtr);
+		fsp_header_init(table->space, FIL_IBD_FILE_INITIAL_SIZE, &mtr);
 
 		mtr_commit(&mtr);
-
-		if(!res) {
-			return (DB_ERROR);
-		}
 	} else {
 		/* Create in the system tablespace: disallow Barracuda
 		features by keeping only the first bit which says whether
 		the row format is redundant or compact */
 		table->flags &= DICT_TF_COMPACT;
```

### `storage/xtradb/fil/fil0fil.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/xtradb/fil/fil0fil.cc b/storage/xtradb/fil/fil0fil.cc
index 17e9a1be973..b669d35ff15 100644
--- a/storage/xtradb/fil/fil0fil.cc
+++ b/storage/xtradb/fil/fil0fil.cc
@@ -6113,23 +6113,25 @@ fil_report_invalid_page_access(
 	const char*	space_name,	/*!< in: space name */
 	ulint		byte_offset,	/*!< in: byte offset */
 	ulint		len,		/*!< in: I/O length */
 	ulint		type)		/*!< in: I/O type */
 {
-	fprintf(stderr,
-		"InnoDB: Error: trying to access page number %lu"
-		" in space %lu,\n"
-		"InnoDB: space name %s,\n"
-		"InnoDB: which is outside the tablespace bounds.\n"
-		"InnoDB: Byte offset %lu, len %lu, i/o type %lu.\n"
-		"InnoDB: If you get this error at mysqld startup,"
-		" please check that\n"
-		"InnoDB: your my.cnf matches the ibdata files"
-		" that you have in the\n"
-		"InnoDB: MySQL server.\n",
-		(ulong) block_offset, (ulong) space_id, space_name,
-		(ulong) byte_offset, (ulong) len, (ulong) type);
+	ib_logf(IB_LOG_LEVEL_ERROR,
+		"Trying to access page number " ULINTPF
+		" in space " ULINTPF
+		" space name %s,"
+		" which is outside the tablespace bounds."
+		" Byte offset " ULINTPF ", len " ULINTPF " i/o type " ULINTPF ".",
+		block_offset, space_id, space_name,
+		byte_offset, len, type);
+
+	ib_logf(IB_LOG_LEVEL_FATAL,
+		"If you get this error at mysqld startup,"
+		" please check that"
+		" your my.cnf matches the ibdata files"
+		" that you have in the"
+		" MySQL server.");
 }
 
 /********************************************************************//**
 Find correct node from file space
 @return node */
@@ -6345,15 +6347,14 @@ _fil_io(
 	if (!node) {
 		if (ignore_nonexistent_pages) {
 			mutex_exit(&fil_system->mutex);
 			return(DB_ERROR);
 		}
+
 		fil_report_invalid_page_access(
 				block_offset, space_id, space->name,
 				byte_offset, len, type);
-
-		ut_error;
 	}
 
 	/* Open file if closed */
 	if (!fil_node_prepare_for_io(node, fil_system, space)) {
 		if (space->purpose == FIL_TABLESPACE
@@ -6361,14 +6362,15 @@ _fil_io(
 			mutex_exit(&fil_system->mutex);
 
 			ib_logf(IB_LOG_LEVEL_ERROR,
 				"Trying to do i/o to a tablespace which "
 				"exists without .ibd data file. "
-				"i/o type %lu, space id %lu, page no %lu, "
-				"i/o length %lu bytes",
-				(ulong) type, (ulong) space_id,
-				(ulong) block_offset, (ulong) len);
+				"i/o type " ULINTPF ", space id "
+				ULINTPF ", page no " ULINTPF ", "
+				"i/o length " ULINTPF " bytes",
+				type, space_id,
+				block_offset, len);
 
 			return(DB_TABLESPACE_DELETED);
 		}
 
 		/* The tablespace is for log. Currently, we just assert here
@@ -6384,12 +6386,10 @@ _fil_io(
 		&& space->id != 0 && space->purpose == FIL_TABLESPACE) {
 
 		fil_report_invalid_page_access(
 			block_offset, space_id, space->name, byte_offset,
 			len, type);
-
-		ut_error;
 	}
 
 	/* Now we have made the changes in the data structures of fil_system */
 	mutex_exit(&fil_system->mutex);
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/fil/fil0fil.cc b/storage/xtradb/fil/fil0fil.cc
index b669d35ff15..d979c05c9a6 100644
--- a/storage/xtradb/fil/fil0fil.cc
+++ b/storage/xtradb/fil/fil0fil.cc
@@ -1,9 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1995, 2017, Oracle and/or its affiliates. All Rights Reserved.
-Copyright (c) 2014, 2017, MariaDB Corporation. All Rights Reserved.
+Copyright (c) 2014, 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -6113,25 +6113,23 @@ fil_report_invalid_page_access(
 	const char*	space_name,	/*!< in: space name */
 	ulint		byte_offset,	/*!< in: byte offset */
 	ulint		len,		/*!< in: I/O length */
 	ulint		type)		/*!< in: I/O type */
 {
-	ib_logf(IB_LOG_LEVEL_ERROR,
+	ib_logf(IB_LOG_LEVEL_FATAL,
 		"Trying to access page number " ULINTPF
 		" in space " ULINTPF
 		" space name %s,"
 		" which is outside the tablespace bounds."
-		" Byte offset " ULINTPF ", len " ULINTPF " i/o type " ULINTPF ".",
+		" Byte offset " ULINTPF ", len " ULINTPF
+		" i/o type " ULINTPF ".%s",
 		block_offset, space_id, space_name,
-		byte_offset, len, type);
-
-	ib_logf(IB_LOG_LEVEL_FATAL,
-		"If you get this error at mysqld startup,"
-		" please check that"
-		" your my.cnf matches the ibdata files"
-		" that you have in the"
-		" MySQL server.");
+		byte_offset, len, type,
+		space_id == 0 && !srv_was_started
+		? "Please check that the configuration matches"
+		" the InnoDB system tablespace location (ibdata files)"
+		: "");
 }
 
 /********************************************************************//**
 Find correct node from file space
 @return node */
```

### `storage/xtradb/fsp/fsp0fsp.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/xtradb/fsp/fsp0fsp.cc b/storage/xtradb/fsp/fsp0fsp.cc
index 934824c6462..7929372ae6c 100644
--- a/storage/xtradb/fsp/fsp0fsp.cc
+++ b/storage/xtradb/fsp/fsp0fsp.cc
@@ -671,20 +671,22 @@ fsp_header_init_fields(
 	mach_write_to_4(FSP_HEADER_OFFSET + FSP_SPACE_FLAGS + page,
 			flags);
 }
 
 #ifndef UNIV_HOTBACKUP
-/**********************************************************************//**
-Initializes the space header of a new created space and creates also the
-insert buffer tree root if space == 0. */
+/** Initializes the space header of a new created space and creates also the
+insert buffer tree root if space == 0.
+@param[in]	space_id	space id
+@param[in]	size		current size in blocks
+@param[in,out]	mtr		min-transaction
+@return	true on success, otherwise false. */
 UNIV_INTERN
-void
+bool
 fsp_header_init(
-/*============*/
-	ulint	space_id,	/*!< in: space id */
-	ulint	size,		/*!< in: current size in blocks */
-	mtr_t*	mtr)		/*!< in/out: mini-transaction */
+	ulint	space_id,
+	ulint	size,
+	mtr_t*	mtr)
 {
 	fsp_header_t*	header;
 	buf_block_t*	block;
 	page_t*		page;
 	ulint		flags;
@@ -723,15 +725,19 @@ fsp_header_init(
 	flst_init(header + FSP_FULL_FRAG, mtr);
 	flst_init(header + FSP_SEG_INODES_FULL, mtr);
 	flst_init(header + FSP_SEG_INODES_FREE, mtr);
 
 	mlog_write_ull(header + FSP_SEG_ID, 1, mtr);
+
 	if (space_id == 0) {
 		fsp_fill_free_list(FALSE, space_id, header, mtr);
-		btr_create(DICT_CLUSTERED | DICT_UNIVERSAL | DICT_IBUF,
+
+		if (btr_create(DICT_CLUSTERED | DICT_UNIVERSAL | DICT_IBUF,
 			   0, 0, DICT_IBUF_ID_MIN + space_id,
-			   dict_ind_redundant, mtr);
+				dict_ind_redundant, mtr) == FIL_NULL) {
+			return (false);
+		}
 	} else {
 		fsp_fill_free_list(TRUE, space_id, header, mtr);
 	}
 
 	fil_space_t* space = fil_space_acquire(space_id);
@@ -740,10 +746,12 @@ fsp_header_init(
 	if (space->crypt_data) {
 		space->crypt_data->write_page0(page, mtr);
 	}
 
 	fil_space_release(space);
+
+	return (true);
 }
 
 #endif /* !UNIV_HOTBACKUP */
 
 /**********************************************************************//**
@@ -2064,19 +2072,25 @@ fseg_create_general(
 
 	if (!has_done_reservation) {
 		success = fsp_reserve_free_extents(&n_reserved, space, 2,
 						   FSP_NORMAL, mtr);
 		if (!success) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Reserving %d free extents failed"
+				" could reserve only " ULINTPF " extents.",
+				2, n_reserved);
 			return(NULL);
 		}
 	}
 
 	space_header = fsp_get_space_header(space, zip_size, mtr);
 
 	inode = fsp_alloc_seg_inode(space_header, mtr);
 
 	if (inode == NULL) {
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Allocation of a new file segment inode page failed.");
 
 		goto funct_exit;
 	}
 
 	/* Read the next segment id from space header and increment the
@@ -2102,10 +2116,13 @@ fseg_create_general(
 	if (page == 0) {
 		block = fseg_alloc_free_page_low(space, zip_size,
 						 inode, 0, FSP_UP, mtr, mtr);
 
 		if (block == NULL) {
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"Allocation of a free page from space " ULINTPF " failed.",
+				space);
 
 			fsp_free_seg_inode(space, zip_size, inode, mtr);
 
 			goto funct_exit;
 		}
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/fsp/fsp0fsp.cc b/storage/xtradb/fsp/fsp0fsp.cc
index 7929372ae6c..bd87b88f58d 100644
--- a/storage/xtradb/fsp/fsp0fsp.cc
+++ b/storage/xtradb/fsp/fsp0fsp.cc
@@ -671,22 +671,17 @@ fsp_header_init_fields(
 	mach_write_to_4(FSP_HEADER_OFFSET + FSP_SPACE_FLAGS + page,
 			flags);
 }
 
 #ifndef UNIV_HOTBACKUP
-/** Initializes the space header of a new created space and creates also the
-insert buffer tree root if space == 0.
+/** Initialize a tablespace header.
 @param[in]	space_id	space id
 @param[in]	size		current size in blocks
-@param[in,out]	mtr		min-transaction
-@return	true on success, otherwise false. */
+@param[in,out]	mtr		mini-transaction */
 UNIV_INTERN
-bool
-fsp_header_init(
-	ulint	space_id,
-	ulint	size,
-	mtr_t*	mtr)
+void
+fsp_header_init(ulint space_id, ulint size, mtr_t* mtr)
 {
 	fsp_header_t*	header;
 	buf_block_t*	block;
 	page_t*		page;
 	ulint		flags;
@@ -726,32 +721,20 @@ fsp_header_init(
 	flst_init(header + FSP_SEG_INODES_FULL, mtr);
 	flst_init(header + FSP_SEG_INODES_FREE, mtr);
 
 	mlog_write_ull(header + FSP_SEG_ID, 1, mtr);
 
-	if (space_id == 0) {
-		fsp_fill_free_list(FALSE, space_id, header, mtr);
-
-		if (btr_create(DICT_CLUSTERED | DICT_UNIVERSAL | DICT_IBUF,
-			   0, 0, DICT_IBUF_ID_MIN + space_id,
-				dict_ind_redundant, mtr) == FIL_NULL) {
-			return (false);
-		}
-	} else {
-		fsp_fill_free_list(TRUE, space_id, header, mtr);
-	}
+	fsp_fill_free_list(space_id != TRX_SYS_SPACE, space_id, header, mtr);
 
 	fil_space_t* space = fil_space_acquire(space_id);
 	ut_ad(space);
 
 	if (space->crypt_data) {
 		space->crypt_data->write_page0(page, mtr);
 	}
 
 	fil_space_release(space);
-
-	return (true);
 }
 
 #endif /* !UNIV_HOTBACKUP */
 
 /**********************************************************************//**
@@ -2072,26 +2055,19 @@ fseg_create_general(
 
 	if (!has_done_reservation) {
 		success = fsp_reserve_free_extents(&n_reserved, space, 2,
 						   FSP_NORMAL, mtr);
 		if (!success) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Reserving %d free extents failed"
-				" could reserve only " ULINTPF " extents.",
-				2, n_reserved);
 			return(NULL);
 		}
 	}
 
 	space_header = fsp_get_space_header(space, zip_size, mtr);
 
 	inode = fsp_alloc_seg_inode(space_header, mtr);
 
 	if (inode == NULL) {
-		ib_logf(IB_LOG_LEVEL_ERROR,
-			"Allocation of a new file segment inode page failed.");
-
 		goto funct_exit;
 	}
 
 	/* Read the next segment id from space header and increment the
 	value in space header */
@@ -2116,13 +2092,10 @@ fseg_create_general(
 	if (page == 0) {
 		block = fseg_alloc_free_page_low(space, zip_size,
 						 inode, 0, FSP_UP, mtr, mtr);
 
 		if (block == NULL) {
-			ib_logf(IB_LOG_LEVEL_ERROR,
-				"Allocation of a free page from space " ULINTPF " failed.",
-				space);
 
 			fsp_free_seg_inode(space, zip_size, inode, mtr);
 
 			goto funct_exit;
 		}
```

### `storage/xtradb/handler/ha_innodb.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/xtradb/handler/ha_innodb.cc b/storage/xtradb/handler/ha_innodb.cc
index dd5d041aed9..7be6c64407b 100644
--- a/storage/xtradb/handler/ha_innodb.cc
+++ b/storage/xtradb/handler/ha_innodb.cc
@@ -3768,10 +3768,11 @@ innobase_init(
 	int		err;
 	bool		ret;
 	char		*default_path;
 	uint		format_id;
 	ulong		num_pll_degree;
+	ulint		min_size = 0;
 
 	DBUG_ENTER("innobase_init");
 	handlerton *innobase_hton= (handlerton*) p;
 	innodb_hton_ptr = innobase_hton;
 
@@ -4018,10 +4019,23 @@ mem_free_and_error:
 		srv_free_paths_and_sizes();
 		my_free(internal_innobase_data_file_path);
 		goto error;
 	}
 
+	/* All doublewrite buffer pages must fit to first system
+	datafile and first datafile must be at least 3M. */
+	min_size = ut_max((3*1024*1024U), (192U*UNIV_PAGE_SIZE));
+
+	if ((srv_data_file_sizes[0]*1024*1024) < min_size) {
+		sql_print_error(
+			"InnoDB: first datafile is too small current=" ULINTPF
+			"M it should be at least " ULINTPF "M.",
+			srv_data_file_sizes[0],
+			min_size / (1024 * 1024));
+		goto mem_free_and_error;
+	}
+
 	/* -------------- All log files ---------------------------*/
 
 	/* The default dir for log files is the datadir of MySQL */
 
 	if (!srv_log_group_home_dir) {
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/handler/ha_innodb.cc b/storage/xtradb/handler/ha_innodb.cc
index 7be6c64407b..dd5d041aed9 100644
--- a/storage/xtradb/handler/ha_innodb.cc
+++ b/storage/xtradb/handler/ha_innodb.cc
@@ -3768,11 +3768,10 @@ innobase_init(
 	int		err;
 	bool		ret;
 	char		*default_path;
 	uint		format_id;
 	ulong		num_pll_degree;
-	ulint		min_size = 0;
 
 	DBUG_ENTER("innobase_init");
 	handlerton *innobase_hton= (handlerton*) p;
 	innodb_hton_ptr = innobase_hton;
 
@@ -4019,23 +4018,10 @@ mem_free_and_error:
 		srv_free_paths_and_sizes();
 		my_free(internal_innobase_data_file_path);
 		goto error;
 	}
 
-	/* All doublewrite buffer pages must fit to first system
-	datafile and first datafile must be at least 3M. */
-	min_size = ut_max((3*1024*1024U), (192U*UNIV_PAGE_SIZE));
-
-	if ((srv_data_file_sizes[0]*1024*1024) < min_size) {
-		sql_print_error(
-			"InnoDB: first datafile is too small current=" ULINTPF
-			"M it should be at least " ULINTPF "M.",
-			srv_data_file_sizes[0],
-			min_size / (1024 * 1024));
-		goto mem_free_and_error;
-	}
-
 	/* -------------- All log files ---------------------------*/
 
 	/* The default dir for log files is the datadir of MySQL */
 
 	if (!srv_log_group_home_dir) {
```

### `storage/xtradb/include/buf0dblwr.h`

```diff
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/include/buf0dblwr.h b/storage/xtradb/include/buf0dblwr.h
index 8e1b00db83c..7b7464761cc 100644
--- a/storage/xtradb/include/buf0dblwr.h
+++ b/storage/xtradb/include/buf0dblwr.h
@@ -1,9 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1995, 2017, Oracle and/or its affiliates. All Rights Reserved.
-Copyright (c) 2017, MariaDB Corporation. All Rights Reserved.
+Copyright (c) 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -37,17 +37,19 @@ Created 2011/12/19 Inaam Rana
 /** Doublewrite system */
 extern buf_dblwr_t*	buf_dblwr;
 /** Set to TRUE when the doublewrite buffer is being created */
 extern ibool		buf_dblwr_being_created;
 
-/****************************************************************//**
-Creates the doublewrite buffer to a new InnoDB installation. The header of the
-doublewrite buffer is placed on the trx system header page. */
+/** Create the doublewrite buffer if the doublewrite buffer header
+is not present in the TRX_SYS page.
+@return	whether the operation succeeded
+@retval	true	if the doublewrite buffer exists or was created
+@retval	false	if the creation failed (too small first data file) */
 UNIV_INTERN
-void
-buf_dblwr_create(void);
-/*==================*/
+bool
+buf_dblwr_create()
+	MY_ATTRIBUTE((warn_unused_result));
 
 /****************************************************************//**
 At a database startup initializes the doublewrite buffer memory structure if
 we already have a doublewrite buffer created in the data files. If we are
 upgrading to an InnoDB version which supports multiple tablespaces, then this
```

### `storage/xtradb/include/fsp0fsp.h`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/xtradb/include/fsp0fsp.h b/storage/xtradb/include/fsp0fsp.h
index 6ed78eba6f9..d8f851a0846 100644
--- a/storage/xtradb/include/fsp0fsp.h
+++ b/storage/xtradb/include/fsp0fsp.h
@@ -517,20 +517,24 @@ fsp_header_init_fields(
 /*===================*/
 	page_t*	page,		/*!< in/out: first page in the space */
 	ulint	space_id,	/*!< in: space id */
 	ulint	flags);		/*!< in: tablespace flags (FSP_SPACE_FLAGS):
 				0, or table->flags if newer than COMPACT */
-/**********************************************************************//**
-Initializes the space header of a new created space and creates also the
-insert buffer tree root if space == 0. */
+/** Initializes the space header of a new created space and creates also the
+insert buffer tree root if space == 0.
+@param[in]	space_id	space id
+@param[in]	size		current size in blocks
+@param[in,out]	mtr		min-transaction
+@return	true on success, otherwise false. */
 UNIV_INTERN
-void
+bool
 fsp_header_init(
-/*============*/
-	ulint	space,		/*!< in: space id */
-	ulint	size,		/*!< in: current size in blocks */
-	mtr_t*	mtr);		/*!< in/out: mini-transaction */
+	ulint	space_id,
+	ulint	size,
+	mtr_t*	mtr)
+	MY_ATTRIBUTE((warn_unused_result));
+
 /**********************************************************************//**
 Increases the space size field of a space. */
 UNIV_INTERN
 void
 fsp_header_inc_size(
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/include/fsp0fsp.h b/storage/xtradb/include/fsp0fsp.h
index d8f851a0846..715572199ab 100644
--- a/storage/xtradb/include/fsp0fsp.h
+++ b/storage/xtradb/include/fsp0fsp.h
@@ -517,23 +517,17 @@ fsp_header_init_fields(
 /*===================*/
 	page_t*	page,		/*!< in/out: first page in the space */
 	ulint	space_id,	/*!< in: space id */
 	ulint	flags);		/*!< in: tablespace flags (FSP_SPACE_FLAGS):
 				0, or table->flags if newer than COMPACT */
-/** Initializes the space header of a new created space and creates also the
-insert buffer tree root if space == 0.
+/** Initialize a tablespace header.
 @param[in]	space_id	space id
 @param[in]	size		current size in blocks
-@param[in,out]	mtr		min-transaction
-@return	true on success, otherwise false. */
+@param[in,out]	mtr		mini-transaction */
 UNIV_INTERN
-bool
-fsp_header_init(
-	ulint	space_id,
-	ulint	size,
-	mtr_t*	mtr)
-	MY_ATTRIBUTE((warn_unused_result));
+void
+fsp_header_init(ulint space_id, ulint size, mtr_t* mtr);
 
 /**********************************************************************//**
 Increases the space size field of a space. */
 UNIV_INTERN
 void
```

### `storage/xtradb/include/trx0rseg.h`

```diff
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/include/trx0rseg.h b/storage/xtradb/include/trx0rseg.h
index b9c84ef2b06..e2853df7045 100644
--- a/storage/xtradb/include/trx0rseg.h
+++ b/storage/xtradb/include/trx0rseg.h
@@ -1,8 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1996, 2011, Oracle and/or its affiliates. All Rights Reserved.
+Copyright (c) 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -122,17 +123,17 @@ UNIV_INTERN
 void
 trx_rseg_mem_free(
 /*==============*/
 	trx_rseg_t*	rseg);		/*!< in, own: instance to free */
 
-/*********************************************************************
-Creates a rollback segment. */
+/** Create a rollback segment.
+@param[in]	space	undo tablespace ID
+@return pointer to new rollback segment
+@retval	NULL	on failure */
 UNIV_INTERN
 trx_rseg_t*
-trx_rseg_create(
-/*============*/
-	ulint	space);			/*!< in: id of UNDO tablespace */
+trx_rseg_create(ulint space);
 
 /********************************************************************
 Get the number of unique rollback tablespaces in use except space id 0.
 The last space id will be the sentinel value ULINT_UNDEFINED. The array
 will be sorted on space id. Note: space_ids should have have space for
```

### `storage/xtradb/log/log0recv.cc`

```diff
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/log/log0recv.cc b/storage/xtradb/log/log0recv.cc
index 037bc9d35d3..fb64309cee4 100644
--- a/storage/xtradb/log/log0recv.cc
+++ b/storage/xtradb/log/log0recv.cc
@@ -3002,15 +3002,10 @@ recv_init_crash_recovery(void)
 	check if there are half-written pages in data files,
 	and restore them from the doublewrite buffer if
 	possible */
 
 	if (srv_force_recovery < SRV_FORCE_NO_LOG_REDO) {
-
-		ib_logf(IB_LOG_LEVEL_INFO,
-			"Restoring possible half-written data pages "
-			"from the doublewrite buffer...");
-
 		buf_dblwr_process();
 
 		/* Spawn the background thread to flush dirty pages
 		from the buffer pools. */
 		recv_writer_thread_active = true;
@@ -3274,28 +3269,10 @@ recv_recovery_from_checkpoint_start_func(
 		/* NOTE: we always do a 'recovery' at startup, but only if
 		there is something wrong we will print a message to the
 		user about recovery: */
 
 		if (checkpoint_lsn != flushed_lsn) {
-
-			if (checkpoint_lsn <flushed_lsn) {
-
-				ib_logf(IB_LOG_LEVEL_WARN,
-					"The log sequence number "
-					"in the ibdata files is higher "
-					"than the log sequence number "
-					"in the ib_logfiles! Are you sure "
-					"you are using the right "
-					"ib_logfiles to start up the database. "
-					"Log sequence number in the "
-					"ib_logfiles is " LSN_PF ", log"
-					"sequence number stamped "
-					"to ibdata file header is " LSN_PF ".",
-					checkpoint_lsn,
-					flushed_lsn);
-			}
-
 			if (!recv_needed_recovery) {
 				ib_logf(IB_LOG_LEVEL_INFO,
 					"The log sequence number "
 					LSN_PF
 					" in ibdata file do not match"
```

### `storage/xtradb/row/row0mysql.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/xtradb/row/row0mysql.cc b/storage/xtradb/row/row0mysql.cc
index 59568f5c91b..9f1f216bccb 100644
--- a/storage/xtradb/row/row0mysql.cc
+++ b/storage/xtradb/row/row0mysql.cc
@@ -3612,13 +3612,19 @@ row_truncate_table_for_mysql(
 				index->space = space_id;
 				index = dict_table_get_next_index(index);
 			} while (index);
 
 			mtr_start_trx(&mtr, trx);
-			fsp_header_init(space_id,
+			bool ret = fsp_header_init(space_id,
 					FIL_IBD_FILE_INITIAL_SIZE, &mtr);
 			mtr_commit(&mtr);
+
+			if (!ret) {
+				table->file_unreadable = true;
+				err = DB_ERROR;
+				goto funct_exit;
+			}
 		}
 	} else {
 		/* Lock all index trees for this table, as we will
 		truncate the table/index and possibly change their metadata.
 		All DML/DDL are blocked by table level lock, with
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/row/row0mysql.cc b/storage/xtradb/row/row0mysql.cc
index 9f1f216bccb..59568f5c91b 100644
--- a/storage/xtradb/row/row0mysql.cc
+++ b/storage/xtradb/row/row0mysql.cc
@@ -3612,19 +3612,13 @@ row_truncate_table_for_mysql(
 				index->space = space_id;
 				index = dict_table_get_next_index(index);
 			} while (index);
 
 			mtr_start_trx(&mtr, trx);
-			bool ret = fsp_header_init(space_id,
+			fsp_header_init(space_id,
 					FIL_IBD_FILE_INITIAL_SIZE, &mtr);
 			mtr_commit(&mtr);
-
-			if (!ret) {
-				table->file_unreadable = true;
-				err = DB_ERROR;
-				goto funct_exit;
-			}
 		}
 	} else {
 		/* Lock all index trees for this table, as we will
 		truncate the table/index and possibly change their metadata.
 		All DML/DDL are blocked by table level lock, with
```

### `storage/xtradb/srv/srv0start.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/xtradb/srv/srv0start.cc b/storage/xtradb/srv/srv0start.cc
index 9e2bd483511..9491d5328e7 100644
--- a/storage/xtradb/srv/srv0start.cc
+++ b/storage/xtradb/srv/srv0start.cc
@@ -204,10 +204,43 @@ UNIV_INTERN mysql_pfs_key_t	srv_monitor_thread_key;
 UNIV_INTERN mysql_pfs_key_t	srv_master_thread_key;
 UNIV_INTERN mysql_pfs_key_t	srv_purge_thread_key;
 UNIV_INTERN mysql_pfs_key_t	srv_log_tracking_thread_key;
 #endif /* UNIV_PFS_THREAD */
 
+/** Innobase start-up aborted. Perform cleanup actions.
+@param[in]	create_new_db	TRUE if new db is  being created
+@param[in]	file		File name
+@param[in]	line		Line number
+@param[in]	err		Reason for aborting InnoDB startup
+@return DB_SUCCESS or error code. */
+static
+dberr_t
+srv_init_abort(
+	bool		create_new_db,
+	const char*	file,
+	ulint		line,
+	dberr_t		err)
+{
+	if (create_new_db) {
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Database creation was aborted"
+			" at %s [" ULINTPF "]"
+			" with error %s. You may need"
+			" to delete the ibdata1 file before trying to start"
+			" up again.",
+			file, line, ut_strerr(err));
+	} else {
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"Plugin initialization aborted"
+			" at %s [" ULINTPF "]"
+			" with error %s.",
+			file, line, ut_strerr(err));
+	}
+
+	return(err);
+}
+
 /*********************************************************************//**
 Convert a numeric string that optionally ends in G or M or K, to a number
 containing megabytes.
 @return	next character in string */
 static
@@ -1566,22 +1599,30 @@ srv_undo_tablespaces_init(
 		}
 	}
 
 	if (create_new_db) {
 		mtr_t	mtr;
+		bool ret=true;
 
 		mtr_start(&mtr);
 
 		/* The undo log tablespace */
 		for (i = 0; i < n_undo_tablespaces; ++i) {
 
-			fsp_header_init(
+			ret = fsp_header_init(
 				undo_tablespace_ids[i],
 				SRV_UNDO_TABLESPACE_SIZE_IN_PAGES, &mtr);
+			if (!ret) {
+				break;
+			}
 		}
 
 		mtr_commit(&mtr);
+
+		if (!ret) {
+			return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
+		}
 	}
 
 	return(DB_SUCCESS);
 }
 
@@ -2464,14 +2505,18 @@ files_checked:
 		ut_a(!srv_read_only_mode);
 		init_log_online();
 
 		mtr_start(&mtr);
 
-		fsp_header_init(0, sum_of_new_sizes, &mtr);
+		bool ret = fsp_header_init(0, sum_of_new_sizes, &mtr);
 
 		mtr_commit(&mtr);
 
+		if (!ret) {
+			return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
+		}
+
 		/* To maintain backward compatibility we create only
 		the first rollback segment before the double write buffer.
 		All the remaining rollback segments will be created later,
 		after the double write buffer has been created. */
 		trx_sys_create_sys_pages();
@@ -2897,10 +2942,13 @@ files_checked:
 
 	if (srv_available_undo_logs == ULINT_UNDEFINED) {
 		/* Can only happen if server is read only. */
 		ut_a(srv_read_only_mode);
 		srv_undo_logs = ULONG_UNDEFINED;
+	} else if (srv_available_undo_logs < srv_undo_logs) {
+		/* Should due to out of file space. */
+		return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
 	}
 
 	if (!srv_read_only_mode) {
 		/* Create the thread which watches the timeouts
 		for lock waits */
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/srv/srv0start.cc b/storage/xtradb/srv/srv0start.cc
index cbab9b2f8c4..6fd8e8944f5 100644
--- a/storage/xtradb/srv/srv0start.cc
+++ b/storage/xtradb/srv/srv0start.cc
@@ -1599,30 +1599,22 @@ srv_undo_tablespaces_init(
 		}
 	}
 
 	if (create_new_db) {
 		mtr_t	mtr;
-		bool ret=true;
 
 		mtr_start(&mtr);
 
 		/* The undo log tablespace */
 		for (i = 0; i < n_undo_tablespaces; ++i) {
 
-			ret = fsp_header_init(
+			fsp_header_init(
 				undo_tablespace_ids[i],
 				SRV_UNDO_TABLESPACE_SIZE_IN_PAGES, &mtr);
-			if (!ret) {
-				break;
-			}
 		}
 
 		mtr_commit(&mtr);
-
-		if (!ret) {
-			return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
-		}
 	}
 
 	return(DB_SUCCESS);
 }
 
@@ -2505,18 +2497,28 @@ files_checked:
 		ut_a(!srv_read_only_mode);
 		init_log_online();
 
 		mtr_start(&mtr);
 
-		bool ret = fsp_header_init(0, sum_of_new_sizes, &mtr);
+		fsp_header_init(0, sum_of_new_sizes, &mtr);
+		compile_time_assert(TRX_SYS_SPACE == 0);
+		compile_time_assert(IBUF_SPACE_ID == 0);
+
+		ulint ibuf_root = btr_create(
+			DICT_CLUSTERED | DICT_UNIVERSAL | DICT_IBUF,
+			0, 0, DICT_IBUF_ID_MIN,
+			dict_ind_redundant, &mtr);
 
 		mtr_commit(&mtr);
 
-		if (!ret) {
-			return (srv_init_abort(create_new_db, __FILE__, __LINE__, DB_ERROR));
+		if (ibuf_root == FIL_NULL) {
+			return(srv_init_abort(true, __FILE__, __LINE__,
+					      DB_ERROR));
 		}
 
+		ut_ad(ibuf_root == IBUF_TREE_ROOT_PAGE_NO);
+
 		/* To maintain backward compatibility we create only
 		the first rollback segment before the double write buffer.
 		All the remaining rollback segments will be created later,
 		after the double write buffer has been created. */
 		trx_sys_create_sys_pages();
@@ -2899,14 +2901,13 @@ files_checked:
 #endif /* UNIV_LOG_ARCHIVE */
 
 	/* fprintf(stderr, "Max allowed record size %lu\n",
 	page_get_free_space_of_empty() / 2); */
 
-	if (buf_dblwr == NULL) {
-		/* Create the doublewrite buffer to a new tablespace */
-
-		buf_dblwr_create();
+	if (!buf_dblwr_create()) {
+		return(srv_init_abort(create_new_db, __FILE__, __LINE__,
+				      DB_ERROR));
 	}
 
 	/* Here the double write buffer has already been created and so
 	any new rollback segments will be allocated after the double
 	write buffer. The default segment should already exist.
```

### `storage/xtradb/trx/trx0rseg.cc`

```diff
--- from commit 112b21da37da ---
diff --git a/storage/xtradb/trx/trx0rseg.cc b/storage/xtradb/trx/trx0rseg.cc
index 003d1036a8c..21dbab98e48 100644
--- a/storage/xtradb/trx/trx0rseg.cc
+++ b/storage/xtradb/trx/trx0rseg.cc
@@ -321,11 +321,14 @@ trx_rseg_create(
 		trx_sysf_t*	sys_header;
 
 		page_no = trx_rseg_header_create(
 			space, 0, ULINT_MAX, slot_no, &mtr);
 
-		ut_a(page_no != FIL_NULL);
+		if (page_no == FIL_NULL) {
+			mtr_commit(&mtr);
+			return (rseg);
+		}
 
 		sys_header = trx_sysf_get(&mtr);
 
 		id = trx_sysf_rseg_get_space(sys_header, slot_no, &mtr);
 		ut_a(id == space);
--- from commit fbeb9489cd7d ---
diff --git a/storage/xtradb/trx/trx0rseg.cc b/storage/xtradb/trx/trx0rseg.cc
index 21dbab98e48..16fa334872b 100644
--- a/storage/xtradb/trx/trx0rseg.cc
+++ b/storage/xtradb/trx/trx0rseg.cc
@@ -1,8 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1996, 2011, Oracle and/or its affiliates. All Rights Reserved.
+Copyright (c) 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -291,18 +292,17 @@ trx_rseg_create_instance(
 			ut_a(trx_sys->rseg_array[i] == NULL);
 		}
 	}
 }
 
-/*********************************************************************
-Creates a rollback segment.
-@return pointer to new rollback segment if create successful */
+/** Create a rollback segment.
+@param[in]	space	undo tablespace ID
+@return pointer to new rollback segment
+@retval	NULL	on failure */
 UNIV_INTERN
 trx_rseg_t*
-trx_rseg_create(
-/*============*/
-	ulint		space)		/*!< in: id of UNDO tablespace */
+trx_rseg_create(ulint space)
 {
 	mtr_t		mtr;
 	ulint		slot_no;
 	trx_rseg_t*	rseg = NULL;
 
@@ -321,29 +321,25 @@ trx_rseg_create(
 		trx_sysf_t*	sys_header;
 
 		page_no = trx_rseg_header_create(
 			space, 0, ULINT_MAX, slot_no, &mtr);
 
-		if (page_no == FIL_NULL) {
-			mtr_commit(&mtr);
-			return (rseg);
-		}
-
-		sys_header = trx_sysf_get(&mtr);
+		if (page_no != FIL_NULL) {
+			sys_header = trx_sysf_get(&mtr);
 
-		id = trx_sysf_rseg_get_space(sys_header, slot_no, &mtr);
-		ut_a(id == space);
+			id = trx_sysf_rseg_get_space(sys_header, slot_no, &mtr);
+			ut_a(id == space);
 
-		zip_size = space ? fil_space_get_zip_size(space) : 0;
+			zip_size = space ? fil_space_get_zip_size(space) : 0;
 
-		rseg = trx_rseg_mem_create(
-			slot_no, space, zip_size, page_no,
-			purge_sys->ib_bh, &mtr);
+			rseg = trx_rseg_mem_create(
+				slot_no, space, zip_size, page_no,
+				purge_sys->ib_bh, &mtr);
+		}
 	}
 
 	mtr_commit(&mtr);
-
 	return(rseg);
 }
 
 /*********************************************************************//**
 Creates the memory copies for rollback segments and initializes the
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
