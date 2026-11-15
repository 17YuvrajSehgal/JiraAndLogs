# Annotation packet: MDEV-12602  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
InnoDB: Failing assertion: space->n_pending_ops == 0

When a tablespace is being removed from the InnoDB tablespace cache, we occasionally have an assertion failing in 10.2:
{noformat}
2017-04-27 10:38:42 0x4538  InnoDB: Assertion failure in file D:\win32-debug\build\src\storage\innobase\fil\fil0fil.cc line 2875
InnoDB: Failing assertion: space->n_pending_ops == 0
{noformat}
This has failed at least twice in 10.2:
[non-debug x86, Debian Stretch|http://buildbot.askmonty.org/buildbot/builders/kvm-deb-stretch-x86/builds/599/steps/mtr/logs/stdio]
[debug x86, Microsoft Windows|http://buildbot.askmonty.org/buildbot/builders/win32-debug/builds/3594/steps/test/logs/stdio]

The likely cause is the MDEV-12428 fix, which allows I/O threads to increment the fil_space_t::n_pending_ops count even after the tablespace has been marked for dropping.

We must review the code also in 10.1 before the 10.1.23 release.
```

## Fix commit message(s)

`4b24467ff37d`

```
MDEV-12602 InnoDB: Failing assertion: space->n_pending_ops == 0

This fixes a regression caused by MDEV-12428.
When we introduced a variant of fil_space_acquire() that could
increment space->n_pending_ops after space->stop_new_ops was set,
the logic of fil_check_pending_operations() was broken.

fil_space_t::n_pending_ios: A new field to track read or write
access from the buffer pool routines immediately before a block
write or after a block read in the file system.

fil_space_acquire_for_io(), fil_space_release_for_io(): Similar
to fil_space_acquire_silent() and fil_space_release(), but
modify fil_space_t::n_pending_ios instead of fil_space_t::n_pending_ops.

fil_space_free_low(): Wait for space->n_pending_ios to reach 0,
to avoid accessing freed data in a concurrent thread. Future
calls to fil_space_acquire_for_io() will not find this tablespace,
because it will already have been detached from fil_system.

Adjust a number of places accordingly, and remove some redundant
tablespace lookups.

FIXME: buf_page_check_corrupt() should take a tablespace from
fil_space_acquire_for_io() as a parameter. This will be done
in the 10.1 version of this patch and merged from there.
That depends on MDEV-12253, which has not been merged from 10.1 yet.
```

`b82c602db588`

```
MDEV-12602 InnoDB: Failing assertion: space->n_pending_ops == 0

This fixes a regression caused by MDEV-12428.
When we introduced a variant of fil_space_acquire() that could
increment space->n_pending_ops after space->stop_new_ops was set,
the logic of fil_check_pending_operations() was broken.

fil_space_t::n_pending_ios: A new field to track read or write
access from the buffer pool routines immediately before a block
write or after a block read in the file system.

fil_space_acquire_for_io(), fil_space_release_for_io(): Similar
to fil_space_acquire_silent() and fil_space_release(), but
modify fil_space_t::n_pending_ios instead of fil_space_t::n_pending_ops.

Adjust a number of places accordingly, and remove some redundant
tablespace lookups.

The following parts of this fix differ from the 10.2 version of this fix:

buf_page_get_corrupt(): Add a tablespace parameter.

In 10.2, we already had a two-phase process of freeing fil_space objects
(first, fil_space_detach(), then release fil_system->mutex, and finally
free the fil_space and fil_node objects).

fil_space_free_and_mutex_exit(): Renamed from fil_space_free().
Detach the tablespace from the fil_system cache, release the
fil_system->mutex, and then wait for space->n_pending_ios to reach 0,
to avoid accessing freed data in a concurrent thread.
During the wait, future calls to fil_space_acquire_for_io() will
not find this tablespace, and the count can only be decremented to 0,
at which point it is safe to free the objects.

fil_node_free_part1(), fil_node_free_part2(): Refactored from
fil_node_free().
```

## Files the fix changed

Snapshot holds 3,450 non-test source files. The fix changed 13 file(s); 13 of them are non-test source files (listed below as gold).

- `storage/innobase/buf/buf0buf.cc`
- `storage/innobase/buf/buf0flu.cc`
- `storage/innobase/fil/fil0crypt.cc`
- `storage/innobase/fil/fil0fil.cc`
- `storage/innobase/fil/fil0pagecompress.cc`
- `storage/innobase/include/buf0buf.h`
- `storage/innobase/include/fil0fil.h`
- `storage/xtradb/buf/buf0buf.cc`
- `storage/xtradb/buf/buf0flu.cc`
- `storage/xtradb/fil/fil0crypt.cc`
- `storage/xtradb/fil/fil0fil.cc`
- `storage/xtradb/include/buf0buf.h`
- `storage/xtradb/include/fil0fil.h`

## The fix diff

### `storage/innobase/buf/buf0buf.cc`

```diff
--- from commit 4b24467ff37d ---
diff --git a/storage/innobase/buf/buf0buf.cc b/storage/innobase/buf/buf0buf.cc
index 56f39a78acb..502df6c6160 100644
--- a/storage/innobase/buf/buf0buf.cc
+++ b/storage/innobase/buf/buf0buf.cc
@@ -403,14 +403,26 @@ buf_pool_register_chunk(
 		chunk->blocks->frame, chunk));
 }
 
 /** Decrypt a page.
 @param[in,out]	bpage	Page control block
+@param[in,out]	space	tablespace
 @return whether the operation was successful */
 static
 bool
-buf_page_decrypt_after_read(buf_page_t* bpage);
+buf_page_decrypt_after_read(buf_page_t* bpage, fil_space_t* space)
+	MY_ATTRIBUTE((nonnull));
+
+/** Check if page is maybe compressed, encrypted or both when we encounter
+corrupted page. Note that we can't be 100% sure if page is corrupted
+or decrypt/decompress just failed.
+@param[in,out]	bpage		Page
+@return true if page corrupted, false if not */
+static
+bool
+buf_page_check_corrupt(buf_page_t* bpage)
+	MY_ATTRIBUTE((nonnull, warn_unused_result));
 
 /* prototypes for new functions added to ha_innodb.cc */
 trx_t* innobase_get_trx();
 
 /********************************************************************//**
@@ -5842,20 +5854,18 @@ buf_mark_space_corrupt(
 	}
 
 	return(ret);
 }
 
-/********************************************************************//**
-Check if page is maybe compressed, encrypted or both when we encounter
+/** Check if page is maybe compressed, encrypted or both when we encounter
 corrupted page. Note that we can't be 100% sure if page is corrupted
 or decrypt/decompress just failed.
 @param[in,out]	bpage		Page
 @return true if page corrupted, false if not */
-UNIV_INTERN
+static
 bool
-buf_page_check_corrupt(
-	buf_page_t*	bpage)
+buf_page_check_corrupt(buf_page_t* bpage)
 {
 	byte* dst_frame = (bpage->zip.data) ? bpage->zip.data :
 		((buf_block_t*) bpage)->frame;
 	fil_space_t* space = fil_space_acquire_silent(bpage->id.space());
 	bool still_encrypted = false;
@@ -5954,12 +5964,17 @@ buf_page_io_complete(
 	if (io_type == BUF_IO_READ) {
 		ulint	read_page_no;
 		ulint	read_space_id;
 
 		ut_ad(bpage->zip.data != NULL || ((buf_block_t*)bpage)->frame != NULL);
+		fil_space_t* space = fil_space_acquire_for_io(
+			bpage->id.space());
+		if (!space) {
+			return false;
+		}
 
-		buf_page_decrypt_after_read(bpage);
+		buf_page_decrypt_after_read(bpage, space);
 
 		if (bpage->size.is_compressed()) {
 			frame = bpage->zip.data;
 		} else {
 			frame = ((buf_block_t*) bpage)->frame;
@@ -6029,25 +6044,21 @@ database_corrupted:
 				    > srv_undo_tablespaces_open
 				    && bpage->id.space() != SRV_TMP_SPACE_ID
 				    && buf_mark_space_corrupt(bpage)) {
 					ib::info() << "Simulated IMPORT "
 						"corruption";
+					fil_space_release_for_io(space);
 					return(true);
 				}
 				goto page_not_corrupt;
 			);
 
 			if (!bpage->encrypted) {
-				fil_system_enter();
-				fil_space_t* space = fil_space_get_by_id(bpage->id.space());
-				fil_system_exit();
-
 				ib::error()
 					<< "Database page corruption on disk"
 					" or a failed file read of tablespace "
-					<< (space->name ? space->name : "NULL")
-					<< " page " << bpage->id
+					<< space->name << " page " << bpage->id
 					<< ". You may have to recover from "
 					<< "a backup.";
 
 				buf_page_print(frame, bpage->size,
 					BUF_PAGE_PRINT_NO_CRASH);
@@ -6072,10 +6083,11 @@ database_corrupted:
 				(0), we will attempt to mark the corresponding
 				table as corrupted instead of crashing server */
 
 				if (bpage->id.space() > TRX_SYS_SPACE
 				    && buf_mark_space_corrupt(bpage)) {
+					fil_space_release_for_io(space);
 					return(false);
 				} else {
 					if (!bpage->encrypted) {
 						ib::fatal()
 							<< "Aborting because of a"
@@ -6097,10 +6109,11 @@ database_corrupted:
 						buf_mark_space_corrupt(bpage);
 					} else {
 						ut_error;
 					}
 
+					fil_space_release_for_io(space);
 					return(false);
 				}
 			}
 		}
 
@@ -6140,10 +6153,12 @@ database_corrupted:
 					(buf_block_t*) bpage, bpage->id,
 					&bpage->size, TRUE);
 			}
 
 		}
+
+		fil_space_release_for_io(space);
 	} else {
 		/* io_type == BUF_IO_WRITE */
 		if (bpage->slot) {
 			/* Mark slot free */
 			bpage->slot->reserved = false;
@@ -7500,15 +7515,19 @@ buf_page_encrypt_before_write(
 	return dst_frame;
 }
 
 /** Decrypt a page.
 @param[in,out]	bpage	Page control block
+@param[in,out]	space	tablespace
 @return whether the operation was successful */
 static
 bool
-buf_page_decrypt_after_read(buf_page_t* bpage)
+buf_page_decrypt_after_read(buf_page_t* bpage, fil_space_t* space)
 {
+	ut_ad(space->n_pending_ios > 0);
+	ut_ad(space->id == bpage->id.space());
+
 	bool compressed = bpage->size.is_compressed();
 	const page_size_t& size = bpage->size;
 	byte* dst_frame = compressed ? bpage->zip.data :
 		((buf_block_t*) bpage)->frame;
 	unsigned key_version =
@@ -7523,16 +7542,14 @@ buf_page_decrypt_after_read(buf_page_t* bpage)
 	if (bpage->id.page_no() == 0) {
 		/* File header pages are not encrypted/compressed */
 		return (true);
 	}
 
-	FilSpace space(bpage->id.space(), true);
-
 	/* Page is encrypted if encryption information is found from
 	tablespace and page contains used key_version. This is true
 	also for pages first compressed and then encrypted. */
-	if (!space() || !space()->crypt_data) {
+	if (!space->crypt_data) {
 		key_version = 0;
 	}
 
 	if (page_compressed) {
 		/* the page we read is unencrypted */
@@ -7600,10 +7617,11 @@ buf_page_decrypt_after_read(buf_page_t* bpage)
 		if (slot) {
 			slot->reserved = false;
 		}
 	}
 
+	ut_ad(space->n_pending_ios > 0);
 	return (success);
 }
 
 /**
 Should we punch hole to deallocate unused portion of the page.
--- from commit b82c602db588 ---
diff --git a/storage/innobase/buf/buf0buf.cc b/storage/innobase/buf/buf0buf.cc
index 8f8069a0884..30893798d6f 100644
--- a/storage/innobase/buf/buf0buf.cc
+++ b/storage/innobase/buf/buf0buf.cc
@@ -315,10 +315,19 @@ on the io_type */
 #define MONITOR_RW_COUNTER(io_type, counter)		\
 	((io_type == BUF_IO_READ)			\
 	 ? (counter##_READ)				\
 	 : (counter##_WRITTEN))
 
+/** Decrypt a page.
+@param[in,out]	bpage	Page control block
+@param[in,out]	space	tablespace
+@return whether the operation was successful */
+static
+bool
+buf_page_decrypt_after_read(buf_page_t* bpage, fil_space_t* space)
+	MY_ATTRIBUTE((nonnull));
+
 /* prototypes for new functions added to ha_innodb.cc */
 trx_t* innobase_get_trx();
 
 /********************************************************************//**
 Gets the smallest oldest_modification lsn for any page in the pool. Returns
@@ -481,20 +490,17 @@ buf_block_alloc(
 
 	return(block);
 }
 #endif /* !UNIV_HOTBACKUP */
 
-/********************************************************************//**
-Checks if a page is all zeroes.
-@return	TRUE if the page is all zeroes */
+/** Check if a page is all zeroes.
+@param[in]	read_buf	database page
+@param[in]	zip_size	ROW_FORMAT=COMPRESSED page size, or 0
+@return	whether the page is all zeroes */
 UNIV_INTERN
 bool
-buf_page_is_zeroes(
-/*===============*/
-	const byte*	read_buf,	/*!< in: a database page */
-	const ulint	zip_size)	/*!< in: size of compressed page;
-					0 for uncompressed pages */
+buf_page_is_zeroes(const byte* read_buf, ulint zip_size)
 {
 	const ulint page_size = zip_size ? zip_size : UNIV_PAGE_SIZE;
 
 	for (ulint i = 0; i < page_size; i++) {
 		if (read_buf[i] != 0) {
@@ -605,12 +611,11 @@ buf_page_is_checksum_valid_none(
 
 	return(checksum_field1 == checksum_field2
 	       && checksum_field1 == BUF_NO_CHECKSUM_MAGIC);
 }
 
-/********************************************************************//**
-Checks if a page is corrupt.
+/** Check if a page is corrupt.
 @param[in]	check_lsn		true if LSN should be checked
 @param[in]	read_buf		Page to be checked
 @param[in]	zip_size		compressed size or 0
 @param[in]	space			Pointer to tablespace
 @return	true if corrupted, false if not */
@@ -4437,38 +4442,34 @@ buf_mark_space_corrupt(
 	buf_pool->n_pend_reads--;
 
 	buf_pool_mutex_exit(buf_pool);
 }
 
-/********************************************************************//**
-Check if page is maybe compressed, encrypted or both when we encounter
+/** Check if page is maybe compressed, encrypted or both when we encounter
 corrupted page. Note that we can't be 100% sure if page is corrupted
 or decrypt/decompress just failed.
-@param[in,out]	bpage		Page
-@return DB_SUCCESS if page has been read and is not corrupted,
-@retval DB_PAGE_CORRUPTED if page based on checksum check is corrupted,
-@retval DB_DECRYPTION_FAILED if page post encryption checksum matches but
+@param[in,out]	bpage		page
+@param[in,out]	space		tablespace from fil_space_acquire_for_io()
+@return	whether the operation succeeded
+@retval	DB_SUCCESS		if page has been read and is not corrupted
+@retval	DB_PAGE_CORRUPTED	if page based on checksum check is corrupted
+@retval	DB_DECRYPTION_FAILED	if page post encryption checksum matches but
 after decryption normal page checksum does not match.
-@retval DB_TABLESPACE_DELETED if accessed tablespace is not found */
+@retval	DB_TABLESPACE_DELETED	if accessed tablespace is not found */
 static
 dberr_t
-buf_page_check_corrupt(buf_page_t*	bpage)
+buf_page_check_corrupt(buf_page_t* bpage, fil_space_t* space)
 {
+	ut_ad(space->n_pending_ios > 0);
+
 	ulint zip_size = buf_page_get_zip_size(bpage);
 	byte* dst_frame = (zip_size) ? bpage->zip.data :
 		((buf_block_t*) bpage)->frame;
-	FilSpace space(bpage->space, true);
 	bool still_encrypted = false;
 	dberr_t err = DB_SUCCESS;
 	bool corrupted = false;
-	fil_space_crypt_t* crypt_data = NULL;
-
-	if (!space()) {
-		return(DB_TABLESPACE_DELETED);
-	}
-
-	crypt_data = space()->crypt_data;
+	fil_space_crypt_t* crypt_data = space->crypt_data;
 
 	/* In buf_decrypt_after_read we have either decrypted the page if
 	page post encryption checksum matches and used key_id is found
 	from the encryption plugin. If checksum did not match page was
 	not decrypted and it could be either encrypted and corrupted
@@ -4476,15 +4477,16 @@ buf_page_check_corrupt(buf_page_t*	bpage)
 	still be corrupted if used key does not match. */
 	still_encrypted = (crypt_data &&
 		crypt_data->type != CRYPT_SCHEME_UNENCRYPTED &&
 		!bpage->encrypted &&
 		fil_space_verify_crypt_checksum(dst_frame, zip_size,
-			space(), bpage->offset));
+			space, bpage->offset));
 	if (!still_encrypted) {
 		/* If traditional checksums match, we assume that page is
 		not anymore encrypted. */
-		corrupted = buf_page_is_corrupted(true, dst_frame, zip_size, space());
+		corrupted = buf_page_is_corrupted(true, dst_frame, zip_size,
+						  space);
 
 		if (!corrupted) {
 			bpage->encrypted = false;
 		} else {
 			err = DB_PAGE_CORRUPTED;
@@ -4503,11 +4505,11 @@ buf_page_check_corrupt(buf_page_t*	bpage)
 		ib_logf(IB_LOG_LEVEL_ERROR,
 			"The page [page id: space=%u"
 			", page number=%u]"
 			" in file %s cannot be decrypted.",
 			bpage->space, bpage->offset,
-			space()->name);
+			space->name);
 
 		ib_logf(IB_LOG_LEVEL_INFO,
 			"However key management plugin or used key_version " ULINTPF
 			" is not found or"
 			" used encryption algorithm or method does not match.",
@@ -4521,32 +4523,28 @@ buf_page_check_corrupt(buf_page_t*	bpage)
 	}
 
 	return (err);
 }
 
-/********************************************************************//**
-Completes an asynchronous read or write request of a file page to or from
-the buffer pool.
+/** Complete a read or write request of a file page to or from the buffer pool.
 @param[in,out]		bpage		Page to complete
 @param[in]		evict		whether or not to evict the page
 					from LRU list.
-@return DB_SUCCESS if page has been read and is not corrupted,
-DB_PAGE_CORRUPTED if page based on checksum check is corrupted,
-DB_DECRYPTION_FAILED if page post encryption checksum matches but
-after decryption normal page checksum does not match.
-in write only DB_SUCCESS is possible. */
+@return whether the operation succeeded
+@retval	DB_SUCCESS		always when writing, or if a read page was OK
+@retval	DB_PAGE_CORRUPTED	if the checksum fails on a page read
+@retval	DB_DECRYPTION_FAILED	if page post encryption checksum matches but
+				after decryption normal page checksum does
+				not match */
 UNIV_INTERN
 dberr_t
-buf_page_io_complete(
-	buf_page_t*	bpage,
-	bool		evict)
+buf_page_io_complete(buf_page_t* bpage, bool evict)
 {
 	enum buf_io_fix	io_type;
 	buf_pool_t*	buf_pool = buf_pool_from_bpage(bpage);
 	const ibool	uncompressed = (buf_page_get_state(bpage)
 					== BUF_BLOCK_FILE_PAGE);
-	fil_space_t*	space = NULL;
 	byte*		frame = NULL;
 	dberr_t 	err = DB_SUCCESS;
 
 	ut_a(buf_page_in_file(bpage));
 
@@ -4562,11 +4560,17 @@ buf_page_io_complete(
 	if (io_type == BUF_IO_READ) {
 		ulint	read_page_no = 0;
 		ulint	read_space_id = 0;
 		uint	key_version = 0;
 
-		buf_page_decrypt_after_read(bpage);
+		ut_ad(bpage->zip.data || ((buf_block_t*)bpage)->frame);
+		fil_space_t* space = fil_space_acquire_for_io(bpage->space);
+		if (!space) {
+			return(DB_TABLESPACE_DELETED);
+		}
+
+		buf_page_decrypt_after_read(bpage, space);
 
 		if (buf_page_get_zip_size(bpage)) {
 			frame = bpage->zip.data;
 		} else {
 			frame = ((buf_block_t*) bpage)->frame;
@@ -4633,11 +4637,11 @@ buf_page_io_complete(
 				read_page_no,
 				bpage->space,
 				bpage->offset);
 		}
 
-		err = buf_page_check_corrupt(bpage);
+		err = buf_page_check_corrupt(bpage, space);
 
 database_corrupted:
 
 		if (err != DB_SUCCESS) {
 			/* Not a real corruption if it was triggered by
@@ -4645,32 +4649,28 @@ database_corrupted:
 			DBUG_EXECUTE_IF("buf_page_is_corrupt_failure",
 				if (bpage->space > TRX_SYS_SPACE) {
 					buf_mark_space_corrupt(bpage);
 					ib_logf(IB_LOG_LEVEL_INFO,
 						"Simulated page corruption");
+					fil_space_release_for_io(space);
 					return(err);
 				}
 				err = DB_SUCCESS;
 				goto page_not_corrupt;
 			);
 
 			if (err == DB_PAGE_CORRUPTED) {
-				fil_system_enter();
-				space = fil_space_get_by_id(bpage->space);
-
 				ib_logf(IB_LOG_LEVEL_ERROR,
 					"Database page corruption on disk"
 					" or a failed file read of tablespace %s"
 					" page  [page id: space=%u"
 					", page number=%u]"
 					". You may have to recover from "
 					"a backup.",
 					space->name,
 					bpage->space, bpage->offset);
 
-				fil_system_exit();
-
 				buf_page_print(frame, buf_page_get_zip_size(bpage),
 					BUF_PAGE_PRINT_NO_CRASH);
 
 				ib_logf(IB_LOG_LEVEL_INFO,
 					"It is also possible that your"
@@ -4691,10 +4691,11 @@ database_corrupted:
 				/* If page space id is larger than TRX_SYS_SPACE
 				(0), we will attempt to mark the corresponding
 				table as corrupted instead of crashing server */
 				if (bpage->space > TRX_SYS_SPACE) {
 					buf_mark_space_corrupt(bpage);
+					fil_space_release_for_io(space);
 					return(err);
 				} else {
 					ib_logf(IB_LOG_LEVEL_FATAL,
 						"Ending processing because of a corrupt database page.");
 				}
@@ -4728,10 +4729,12 @@ database_corrupted:
 					bpage->offset, buf_page_get_zip_size(bpage),
 					TRUE);
 			}
 
 		}
+
+		fil_space_release_for_io(space);
 	} else {
 		/* io_type == BUF_IO_WRITE */
 		if (bpage->slot) {
 			/* Mark slot free */
 			bpage->slot->reserved = false;
@@ -6154,20 +6157,21 @@ buf_page_encrypt_before_write(
 
 	// return dst_frame which will be written
 	return dst_frame;
 }
 
-/********************************************************************//**
-Decrypt page after it has been read from disk
-@param[in,out]	bpage		Page control block
-@return true if successfull, false if something went wrong
-*/
-UNIV_INTERN
+/** Decrypt a page.
+@param[in,out]	bpage	Page control block
+@param[in,out]	space	tablespace
+@return whether the operation was successful */
+static
 bool
-buf_page_decrypt_after_read(
-	buf_page_t*	bpage)
+buf_page_decrypt_after_read(buf_page_t* bpage, fil_space_t* space)
 {
+	ut_ad(space->n_pending_ios > 0);
+	ut_ad(space->id == bpage->space);
+
 	ulint zip_size = buf_page_get_zip_size(bpage);
 	ulint size = (zip_size) ? zip_size : UNIV_PAGE_SIZE;
 
 	byte* dst_frame = (zip_size) ? bpage->zip.data :
 		((buf_block_t*) bpage)->frame;
@@ -6181,16 +6185,14 @@ buf_page_decrypt_after_read(
 	if (bpage->offset == 0) {
 		/* File header pages are not encrypted/compressed */
 		return (true);
 	}
 
-	FilSpace space(bpage->space, false, true);
-
 	/* Page is encrypted if encryption information is found from
 	tablespace and page contains used key_version. This is true
 	also for pages first compressed and then encrypted. */
-	if (!space() || !space()->crypt_data) {
+	if (!space->crypt_data) {
 		key_version = 0;
 	}
 
 	if (page_compressed) {
 		/* the page we read is unencrypted */
@@ -6223,13 +6225,13 @@ buf_page_decrypt_after_read(
 			if (!fil_space_verify_crypt_checksum(dst_frame,
 					zip_size, NULL, bpage->offset)) {
 
 				/* Mark page encrypted in case it should
 				be. */
-				if (key_version && space()->crypt_data &&
-				    space()->crypt_data->type != CRYPT_SCHEME_UNENCRYPTED) {
-					bpage->encrypted=true;
+				if (space->crypt_data->type
+				    != CRYPT_SCHEME_UNENCRYPTED) {
+					bpage->encrypted = true;
 				}
 
 				return (false);
 			}
 
@@ -6239,16 +6241,12 @@ buf_page_decrypt_after_read(
 #ifdef UNIV_DEBUG
 			fil_page_type_validate(dst_frame);
 #endif
 
 			/* decrypt using crypt_buf to dst_frame */
-			byte* res = fil_space_decrypt(space(),
-						slot->crypt_buf,
-						dst_frame,
-						&bpage->encrypted);
-
-			if (!res) {
+			if (!fil_space_decrypt(space, slot->crypt_buf,
+					       dst_frame, &bpage->encrypted)) {
 				success = false;
 			}
 
 #ifdef UNIV_DEBUG
 			fil_page_type_validate(dst_frame);
@@ -6275,7 +6273,8 @@ buf_page_decrypt_after_read(
 		if (slot) {
 			slot->reserved = false;
 		}
 	}
 
+	ut_ad(space->n_pending_ios > 0);
 	return (success);
 }
```

### `storage/innobase/buf/buf0flu.cc`

```diff
--- from commit 4b24467ff37d ---
diff --git a/storage/innobase/buf/buf0flu.cc b/storage/innobase/buf/buf0flu.cc
index 366e92a7112..d0c0316bf13 100644
--- a/storage/innobase/buf/buf0flu.cc
+++ b/storage/innobase/buf/buf0flu.cc
@@ -1004,11 +1004,11 @@ buf_flush_write_block_low(
 /*======================*/
 	buf_page_t*	bpage,		/*!< in: buffer block to write */
 	buf_flush_t	flush_type,	/*!< in: type of flush */
 	bool		sync)		/*!< in: true if sync IO request */
 {
-	fil_space_t*	space = fil_space_acquire(bpage->id.space(), true);
+	fil_space_t* space = fil_space_acquire_for_io(bpage->id.space());
 	if (!space) {
 		return;
 	}
 	ut_ad(space->purpose == FIL_TYPE_TEMPORARY
 	      || space->purpose == FIL_TYPE_IMPORT
@@ -1119,14 +1119,20 @@ buf_flush_write_block_low(
 			fil_flush(space);
 		}
 
 		/* true means we want to evict this page from the
 		LRU list as well. */
+		/* The tablespace could already have been dropped,
+		because fil_io(request, sync) would already have
+		decremented the node->n_pending. However,
+		buf_page_io_complete() only needs to look up the
+		tablespace during read requests, not during writes. */
+		ut_ad(buf_page_get_io_fix(bpage) == BUF_IO_WRITE);
 		buf_page_io_complete(bpage, true);
 	}
 
-	fil_space_release(space);
+	fil_space_release_for_io(space);
 
 	/* Increment the counter of I/O operations used
 	for selecting LRU policy. */
 	buf_LRU_stat_inc_io();
 }
--- from commit b82c602db588 ---
diff --git a/storage/innobase/buf/buf0flu.cc b/storage/innobase/buf/buf0flu.cc
index c20dd03c8a9..b41ea4c8f02 100644
--- a/storage/innobase/buf/buf0flu.cc
+++ b/storage/innobase/buf/buf0flu.cc
@@ -829,11 +829,11 @@ buf_flush_write_block_low(
 /*======================*/
 	buf_page_t*	bpage,		/*!< in: buffer block to write */
 	buf_flush_t	flush_type,	/*!< in: type of flush */
 	bool		sync)		/*!< in: true if sync IO request */
 {
-	fil_space_t*	space = fil_space_acquire(bpage->space, true);
+	fil_space_t*	space = fil_space_acquire_for_io(bpage->space);
 	if (!space) {
 		return;
 	}
 	ulint	zip_size	= buf_page_get_zip_size(bpage);
 	page_t*	frame		= NULL;
@@ -954,21 +954,28 @@ buf_flush_write_block_low(
 	are working on. */
 	if (sync) {
 		ut_ad(flush_type == BUF_FLUSH_SINGLE_PAGE);
 		fil_flush(space);
 
+		/* The tablespace could already have been dropped,
+		because fil_io(request, sync) would already have
+		decremented the node->n_pending. However,
+		buf_page_io_complete() only needs to look up the
+		tablespace during read requests, not during writes. */
+		ut_ad(buf_page_get_io_fix(bpage) == BUF_IO_WRITE);
+
 		/* true means we want to evict this page from the
 		LRU list as well. */
 #ifdef UNIV_DEBUG
 		dberr_t err =
 #endif
 		buf_page_io_complete(bpage, true);
 
 		ut_ad(err == DB_SUCCESS);
 	}
 
-	fil_space_release(space);
+	fil_space_release_for_io(space);
 
 	/* Increment the counter of I/O operations used
 	for selecting LRU policy. */
 	buf_LRU_stat_inc_io();
 }
```

### `storage/innobase/fil/fil0crypt.cc`

```diff
--- from commit 4b24467ff37d ---
diff --git a/storage/innobase/fil/fil0crypt.cc b/storage/innobase/fil/fil0crypt.cc
index 016b7c3d24e..033ddd39f90 100644
--- a/storage/innobase/fil/fil0crypt.cc
+++ b/storage/innobase/fil/fil0crypt.cc
@@ -627,11 +627,11 @@ fil_space_encrypt(
 		return (src_frame);
 	}
 
 	fil_space_crypt_t* crypt_data = space->crypt_data;
 	const page_size_t	page_size(space->flags);
-	ut_ad(space->n_pending_ops);
+	ut_ad(space->n_pending_ios > 0);
 	byte* tmp = fil_encrypt_buf(crypt_data, space->id, offset, lsn,
 				    src_frame, page_size, dst_frame);
 
 #ifdef UNIV_DEBUG
 	if (tmp) {
@@ -819,11 +819,11 @@ fil_space_decrypt(
 	byte* res = NULL;
 	const page_size_t page_size(space->flags);
 	*decrypted = false;
 
 	ut_ad(space->crypt_data != NULL && space->crypt_data->is_encrypted());
-	ut_ad(space->n_pending_ops > 0);
+	ut_ad(space->n_pending_ios > 0);
 
 	bool encrypted = fil_space_decrypt(space->crypt_data, tmp_frame,
 					   page_size, src_frame, &err);
 
 	if (err == DB_SUCCESS) {
--- from commit b82c602db588 ---
diff --git a/storage/innobase/fil/fil0crypt.cc b/storage/innobase/fil/fil0crypt.cc
index b51c6ac9cdc..c25d3e78f0e 100644
--- a/storage/innobase/fil/fil0crypt.cc
+++ b/storage/innobase/fil/fil0crypt.cc
@@ -681,11 +681,11 @@ fil_space_encrypt(
 	if (!space->crypt_data || !space->crypt_data->is_encrypted()) {
 		return (src_frame);
 	}
 
 	fil_space_crypt_t* crypt_data = space->crypt_data;
-	ut_ad(space->n_pending_ops);
+	ut_ad(space->n_pending_ios > 0);
 	ulint zip_size = fsp_flags_get_zip_size(space->flags);
 	byte* tmp = fil_encrypt_buf(crypt_data, space->id, offset, lsn, src_frame, zip_size, dst_frame);
 
 #ifdef UNIV_DEBUG
 	if (tmp) {
@@ -858,11 +858,11 @@ fil_space_decrypt(
 	ulint zip_size = fsp_flags_get_zip_size(space->flags);
 	ulint size = zip_size ? zip_size : UNIV_PAGE_SIZE;
 	*decrypted = false;
 
 	ut_ad(space->crypt_data != NULL && space->crypt_data->is_encrypted());
-	ut_ad(space->n_pending_ops > 0);
+	ut_ad(space->n_pending_ios > 0);
 
 	bool encrypted = fil_space_decrypt(
 				space->crypt_data,
 				tmp_frame,
 				size,
```

### `storage/innobase/fil/fil0fil.cc`

```diff
--- from commit 4b24467ff37d ---
diff --git a/storage/innobase/fil/fil0fil.cc b/storage/innobase/fil/fil0fil.cc
index 84c2f07b361..7a169c0bf2c 100644
--- a/storage/innobase/fil/fil0fil.cc
+++ b/storage/innobase/fil/fil0fil.cc
@@ -1504,10 +1504,17 @@ fil_space_free_low(
 {
 	/* The tablespace must not be in fil_system->named_spaces. */
 	ut_ad(srv_fast_shutdown == 2 || !srv_was_started
 	      || space->max_lsn == 0);
 
+	/* Wait for fil_space_release_for_io(); after
+	fil_space_detach(), the tablespace cannot be found, so
+	fil_space_acquire_for_io() would return NULL */
+	while (space->n_pending_ios) {
+		os_thread_sleep(100);
+	}
+
 	for (fil_node_t* node = UT_LIST_GET_FIRST(space->chain);
 	     node != NULL; ) {
 		ut_d(space->size -= node->size);
 		os_event_destroy(node->sync_event);
 		ut_free(node->name);
@@ -2265,17 +2272,15 @@ fil_write_flushed_lsn(
 /** Acquire a tablespace when it could be dropped concurrently.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
 @param[in]	id	tablespace ID
 @param[in]	silent	whether to silently ignore missing tablespaces
-@param[in]	for_io	whether to look up the tablespace while performing I/O
-			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted or truncated */
 inline
 fil_space_t*
-fil_space_acquire_low(ulint id, bool silent, bool for_io = false)
+fil_space_acquire_low(ulint id, bool silent)
 {
 	fil_space_t*	space;
 
 	mutex_enter(&fil_system->mutex);
 
@@ -2284,11 +2289,11 @@ fil_space_acquire_low(ulint id, bool silent, bool for_io = false)
 	if (space == NULL) {
 		if (!silent) {
 			ib::warn() << "Trying to access missing"
 				" tablespace " << id;
 		}
-	} else if (!for_io && space->is_stopping()) {
+	} else if (space->is_stopping()) {
 		space = NULL;
 	} else {
 		space->n_pending_ops++;
 	}
 
@@ -2299,18 +2304,16 @@ fil_space_acquire_low(ulint id, bool silent, bool for_io = false)
 
 /** Acquire a tablespace when it could be dropped concurrently.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
 @param[in]	id	tablespace ID
-@param[in]	for_io	whether to look up the tablespace while performing I/O
-			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL	if missing or being deleted or truncated */
 fil_space_t*
-fil_space_acquire(ulint id, bool for_io)
+fil_space_acquire(ulint id)
 {
-	return(fil_space_acquire_low(id, false, for_io));
+	return(fil_space_acquire_low(id, false));
 }
 
 /** Acquire a tablespace that may not exist.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
@@ -2333,10 +2336,43 @@ fil_space_release(fil_space_t* space)
 	ut_ad(space->n_pending_ops > 0);
 	space->n_pending_ops--;
 	mutex_exit(&fil_system->mutex);
 }
 
+/** Acquire a tablespace for reading or writing a block,
+when it could be dropped concurrently.
+@param[in]	id	tablespace ID
+@return	the tablespace
+@retval	NULL if missing */
+fil_space_t*
+fil_space_acquire_for_io(ulint id)
+{
+	mutex_enter(&fil_system->mutex);
+
+	fil_space_t* space = fil_space_get_by_id(id);
+
+	if (space) {
+		space->n_pending_ios++;
+	}
+
+	mutex_exit(&fil_system->mutex);
+
+	return(space);
+}
+
+/** Release a tablespace acquired with fil_space_acquire_for_io().
+@param[in,out]	space	tablespace to release  */
+void
+fil_space_release_for_io(fil_space_t* space)
+{
+	mutex_enter(&fil_system->mutex);
+	ut_ad(space->magic_n == FIL_SPACE_MAGIC_N);
+	ut_ad(space->n_pending_ios > 0);
+	space->n_pending_ios--;
+	mutex_exit(&fil_system->mutex);
+}
+
 /********************************************************//**
 Creates the database directory for a table if it does not exist yet. */
 void
 fil_create_directory_for_tablename(
 /*===============================*/
@@ -2834,19 +2870,19 @@ enum fil_operation_t {
 @param[in]	space	tablespace
 @param[in]	count	number of attempts so far
 @return 0 if no operations else count + 1. */
 static
 ulint
-fil_check_pending_ops(
-	fil_space_t*	space,
-	ulint		count)
+fil_check_pending_ops(const fil_space_t* space, ulint count)
 {
 	ut_ad(mutex_own(&fil_system->mutex));
 
-	const ulint	n_pending_ops = space ? space->n_pending_ops : 0;
+	if (space == NULL) {
+		return 0;
+	}
 
-	if (n_pending_ops) {
+	if (ulint n_pending_ops = space->n_pending_ops) {
 
 		if (count > 5000) {
 			ib::warn() << "Trying to close/delete/truncate"
 				" tablespace '" << space->name
 				<< "' but there are " << n_pending_ops
@@ -5529,11 +5565,11 @@ fil_flush(
 /** Flush a tablespace.
 @param[in,out]	space	tablespace to flush */
 void
 fil_flush(fil_space_t* space)
 {
-	ut_ad(space->n_pending_ops > 0);
+	ut_ad(space->n_pending_ios > 0);
 	ut_ad(space->purpose == FIL_TYPE_TABLESPACE
 	      || space->purpose == FIL_TYPE_IMPORT);
 
 	if (!space->is_stopping()) {
 		mutex_enter(&fil_system->mutex);
--- from commit b82c602db588 ---
diff --git a/storage/innobase/fil/fil0fil.cc b/storage/innobase/fil/fil0fil.cc
index 66eb425c58b..7bc784121e5 100644
--- a/storage/innobase/fil/fil0fil.cc
+++ b/storage/innobase/fil/fil0fil.cc
@@ -1,9 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1995, 2016, Oracle and/or its affiliates. All Rights Reserved.
-Copyright (c) 2014, 2017, MariaDB Corporation. All Rights Reserved.
+Copyright (c) 2014, 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -242,22 +242,20 @@ fil_node_complete_io(
 	fil_node_t*	node,	/*!< in: file node */
 	fil_system_t*	system,	/*!< in: tablespace memory cache */
 	ulint		type);	/*!< in: OS_FILE_WRITE or OS_FILE_READ; marks
 				the node as modified if
 				type == OS_FILE_WRITE */
-/*******************************************************************//**
-Frees a space object from the tablespace memory cache. Closes the files in
-the chain but does not delete them. There must not be any pending i/o's or
+/** Free a space object from the tablespace memory cache. Close the files in
+the chain but do not delete them. There must not be any pending i/o's or
 flushes on the files.
-@return TRUE on success */
+The fil_system->mutex will be released.
+@param[in]	id		tablespace ID
+@param[in]	x_latched	whether the caller holds exclusive space->latch
+@return whether the tablespace existed */
 static
-ibool
-fil_space_free(
-/*===========*/
-	ulint		id,		/* in: space id */
-	ibool		x_latched);	/* in: TRUE if caller has space->latch
-					in X mode */
+bool
+fil_space_free_and_mutex_exit(ulint id, bool x_latched);
 /********************************************************************//**
 Reads data from a space to a buffer. Remember that the possible incomplete
 blocks at the end of file are ignored: they are not taken into account when
 calculating the byte offset within a space.
 @return DB_SUCCESS, or DB_TABLESPACE_DELETED if we are trying to do
@@ -1358,22 +1356,18 @@ retry:
 			space->recv_size = 0;
 		}
 	}
 }
 
-/*******************************************************************//**
-Frees a file node object from a tablespace memory cache. */
+/** Prepare a data file object for freeing.
+@param[in,out]	space	tablespace
+@param[in,out]	node	data file */
 static
 void
-fil_node_free(
-/*==========*/
-	fil_node_t*	node,	/*!< in, own: file node */
-	fil_system_t*	system,	/*!< in: tablespace memory cache */
-	fil_space_t*	space)	/*!< in: space where the file node is chained */
+fil_node_free_part1(fil_space_t* space, fil_node_t* node)
 {
-	ut_ad(node && system && space);
-	ut_ad(mutex_own(&(system->mutex)));
+	ut_ad(mutex_own(&fil_system->mutex));
 	ut_a(node->magic_n == FIL_NODE_MAGIC_N);
 	ut_a(node->n_pending == 0);
 	ut_a(!node->being_extended);
 
 	if (node->open) {
@@ -1392,16 +1386,26 @@ fil_node_free(
 			   && fil_space_is_flushed(space)) {
 
 			space->is_in_unflushed_spaces = false;
 
 			UT_LIST_REMOVE(unflushed_spaces,
-				       system->unflushed_spaces,
+				       fil_system->unflushed_spaces,
 				       space);
 		}
 
-		fil_node_close_file(node, system);
+		fil_node_close_file(node, fil_system);
 	}
+}
+
+/** Free a data file object.
+@param[in,out]	space	tablespace
+@param[in]	node	data file */
+static
+void
+fil_node_free_part2(fil_space_t* space, fil_node_t* node)
+{
+	ut_ad(!node->open);
 
 	space->size -= node->size;
 
 	UT_LIST_REMOVE(chain, space->chain, node);
 
@@ -1437,11 +1441,12 @@ fil_space_truncate_start(
 
 		ut_a(node->size * UNIV_PAGE_SIZE <= trunc_len);
 
 		trunc_len -= node->size * UNIV_PAGE_SIZE;
 
-		fil_node_free(node, fil_system, space);
+		fil_node_free_part1(space, node);
+		fil_node_free_part2(space, node);
 	}
 
 	mutex_exit(&fil_system->mutex);
 }
 #endif /* UNIV_LOG_ARCHIVE */
@@ -1496,14 +1501,13 @@ fil_space_create(
 			ib_logf(IB_LOG_LEVEL_WARN,
 				"Freeing existing tablespace '%s' entry "
 				"from the cache with id %lu",
 				name, (ulong) id);
 
-			ibool	success = fil_space_free(space->id, FALSE);
+			bool	success = fil_space_free_and_mutex_exit(
+				space->id, false);
 			ut_a(success);
-
-			mutex_exit(&fil_system->mutex);
 		}
 
 	} while (space != 0);
 
 	space = fil_space_get_by_id(id);
@@ -1654,39 +1658,34 @@ fil_assign_new_space_id(
 	mutex_exit(&fil_system->mutex);
 
 	return(success);
 }
 
-/*******************************************************************//**
-Frees a space object from the tablespace memory cache. Closes the files in
-the chain but does not delete them. There must not be any pending i/o's or
+/** Free a space object from the tablespace memory cache. Close the files in
+the chain but do not delete them. There must not be any pending i/o's or
 flushes on the files.
-@return	TRUE if success */
+The fil_system->mutex will be released.
+@param[in]	id		tablespace ID
+@param[in]	x_latched	whether the caller holds exclusive space->latch
+@return whether the tablespace existed */
 static
-ibool
-fil_space_free(
-/*===========*/
-					/* out: TRUE if success */
-	ulint		id,		/* in: space id */
-	ibool		x_latched)	/* in: TRUE if caller has space->latch
-					in X mode */
+bool
+fil_space_free_and_mutex_exit(ulint id, bool x_latched)
 {
 	fil_space_t*	space;
 	fil_space_t*	fnamespace;
 
 	ut_ad(mutex_own(&fil_system->mutex));
 
 	space = fil_space_get_by_id(id);
 
 	if (!space) {
-		ut_print_timestamp(stderr);
-		fprintf(stderr,
-			"  InnoDB: Error: trying to remove tablespace %lu"
-			" from the cache but\n"
-			"InnoDB: it is not there.\n", (ulong) id);
-
-		return(FALSE);
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"trying to remove non-existing tablespace " ULINTPF,
+			id);
+		mutex_exit(&fil_system->mutex);
+		return(false);
 	}
 
 	HASH_DELETE(fil_space_t, hash, fil_system->spaces, id, space);
 
 	fnamespace = fil_space_get_by_name(space->name);
@@ -1714,15 +1713,29 @@ fil_space_free(
 	UT_LIST_REMOVE(space_list, fil_system->space_list, space);
 
 	ut_a(space->magic_n == FIL_SPACE_MAGIC_N);
 	ut_a(0 == space->n_pending_flushes);
 
+	for (fil_node_t* node = UT_LIST_GET_FIRST(space->chain);
+	     node != NULL;
+	     node = UT_LIST_GET_NEXT(chain, node)) {
+		fil_node_free_part1(space, node);
+	}
+
+	mutex_exit(&fil_system->mutex);
+
+	/* Wait for fil_space_release_for_io(); after
+	fil_space_detach(), the tablespace cannot be found, so
+	fil_space_acquire_for_io() would return NULL */
+	while (space->n_pending_ios) {
+		os_thread_sleep(100);
+	}
+
 	for (fil_node_t* fil_node = UT_LIST_GET_FIRST(space->chain);
 	     fil_node != NULL;
 	     fil_node = UT_LIST_GET_FIRST(space->chain)) {
-
-		fil_node_free(fil_node, fil_system, space);
+		fil_node_free_part2(space, fil_node);
 	}
 
 	ut_a(0 == UT_LIST_GET_LEN(space->chain));
 
 	if (x_latched) {
@@ -2112,11 +2125,15 @@ fil_close_all_files(void)
 			}
 		}
 
 		space = UT_LIST_GET_NEXT(space_list, space);
 
-		fil_space_free(prev_space->id, FALSE);
+		/* This is executed during shutdown. No other thread
+		can create or remove tablespaces while we are not
+		holding fil_system->mutex. */
+		fil_space_free_and_mutex_exit(prev_space->id, false);
+		mutex_enter(&fil_system->mutex);
 	}
 
 	mutex_exit(&fil_system->mutex);
 }
 
@@ -2154,11 +2171,15 @@ fil_close_log_files(
 		}
 
 		space = UT_LIST_GET_NEXT(space_list, space);
 
 		if (free) {
-			fil_space_free(prev_space->id, FALSE);
+			/* This is executed during startup. No other thread
+			can create or remove tablespaces while we are not
+			holding fil_system->mutex. */
+			fil_space_free_and_mutex_exit(prev_space->id, false);
+			mutex_enter(&fil_system->mutex);
 		}
 	}
 
 	mutex_exit(&fil_system->mutex);
 }
@@ -2960,19 +2981,17 @@ fil_close_tablespace(
 	mutex_enter(&fil_system->mutex);
 
 	/* If the free is successful, the X lock will be released before
 	the space memory data structure is freed. */
 
-	if (!fil_space_free(id, TRUE)) {
+	if (!fil_space_free_and_mutex_exit(id, TRUE)) {
 		rw_lock_x_unlock(&space->latch);
 		err = DB_TABLESPACE_NOT_FOUND;
 	} else {
 		err = DB_SUCCESS;
 	}
 
-	mutex_exit(&fil_system->mutex);
-
 	/* If it is a delete then also delete any generated files, otherwise
 	when we drop the database the remove directory will fail. */
 
 	char*	cfg_name = fil_make_cfg_name(path);
 
@@ -3077,16 +3096,14 @@ fil_delete_tablespace(
 		ut_a(UT_LIST_GET_LEN(space->chain) == 1);
 		fil_node_t* node = UT_LIST_GET_FIRST(space->chain);
 		ut_a(node->n_pending == 0);
 	}
 
-	if (!fil_space_free(id, TRUE)) {
+	if (!fil_space_free_and_mutex_exit(id, true)) {
 		err = DB_TABLESPACE_NOT_FOUND;
 	}
 
-	mutex_exit(&fil_system->mutex);
-
 	if (err != DB_SUCCESS) {
 		rw_lock_x_unlock(&space->latch);
 	} else if (!os_file_delete(innodb_file_data_key, path)
 		   && !os_file_delete_if_exists(innodb_file_data_key, path)) {
 
@@ -5877,11 +5894,11 @@ fil_space_get_node(
 @return	block size */
 UNIV_INTERN
 ulint
 fil_space_get_block_size(const fil_space_t* space, unsigned offset)
 {
-	ut_ad(space->n_pending_ops > 0);
+	ut_ad(space->n_pending_ios > 0);
 
 	ulint block_size = 512;
 
 	for (fil_node_t* node = UT_LIST_GET_FIRST(space->chain);
 	     node != NULL;
@@ -6278,11 +6295,11 @@ fil_flush(
 @param[in,out]	space	tablespace to flush */
 UNIV_INTERN
 void
 fil_flush(fil_space_t* space)
 {
-	ut_ad(space->n_pending_ops > 0);
+	ut_ad(space->n_pending_ios > 0);
 
 	if (!space->is_stopping()) {
 		mutex_enter(&fil_system->mutex);
 		if (!space->is_stopping()) {
 			fil_flush_low(space);
@@ -7159,17 +7176,15 @@ fil_mtr_rename_log(
 /** Acquire a tablespace when it could be dropped concurrently.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
 @param[in]	id	tablespace ID
 @param[in]	silent	whether to silently ignore missing tablespaces
-@param[in]	for_io	whether to look up the tablespace while performing I/O
-			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted or truncated */
 UNIV_INTERN
 fil_space_t*
-fil_space_acquire_low(ulint id, bool silent, bool for_io)
+fil_space_acquire_low(ulint id, bool silent)
 {
 	fil_space_t*	space;
 
 	mutex_enter(&fil_system->mutex);
 
@@ -7178,11 +7193,11 @@ fil_space_acquire_low(ulint id, bool silent, bool for_io)
 	if (space == NULL) {
 		if (!silent) {
 			ib_logf(IB_LOG_LEVEL_WARN, "Trying to access missing"
 				" tablespace " ULINTPF ".", id);
 		}
-	} else if (!for_io && space->is_stopping()) {
+	} else if (space->is_stopping()) {
 		space = NULL;
 	} else {
 		space->n_pending_ops++;
 	}
 
@@ -7191,28 +7206,65 @@ fil_space_acquire_low(ulint id, bool silent, bool for_io)
 	return(space);
 }
 
 /** Release a tablespace acquired with fil_space_acquire().
 @param[in,out]	space	tablespace to release  */
+UNIV_INTERN
 void
 fil_space_release(fil_space_t* space)
 {
 	mutex_enter(&fil_system->mutex);
 	ut_ad(space->magic_n == FIL_SPACE_MAGIC_N);
 	ut_ad(space->n_pending_ops > 0);
 	space->n_pending_ops--;
 	mutex_exit(&fil_system->mutex);
 }
 
+/** Acquire a tablespace for reading or writing a block,
+when it could be dropped concurrently.
+@param[in]	id	tablespace ID
+@return	the tablespace
+@retval	NULL if missing */
+UNIV_INTERN
+fil_space_t*
+fil_space_acquire_for_io(ulint id)
+{
+	mutex_enter(&fil_system->mutex);
+
+	fil_space_t* space = fil_space_get_by_id(id);
+
+	if (space) {
+		space->n_pending_ios++;
+	}
+
+	mutex_exit(&fil_system->mutex);
+
+	return(space);
+}
+
+/** Release a tablespace acquired with fil_space_acquire_for_io().
+@param[in,out]	space	tablespace to release  */
+UNIV_INTERN
+void
+fil_space_release_for_io(fil_space_t* space)
+{
+	mutex_enter(&fil_system->mutex);
+	ut_ad(space->magic_n == FIL_SPACE_MAGIC_N);
+	ut_ad(space->n_pending_ios > 0);
+	space->n_pending_ios--;
+	mutex_exit(&fil_system->mutex);
+}
+
 /** Return the next fil_space_t.
 Once started, the caller must keep calling this until it returns NULL.
 fil_space_acquire() and fil_space_release() are invoked here which
 blocks a concurrent operation from dropping the tablespace.
 @param[in]	prev_space	Pointer to the previous fil_space_t.
 If NULL, use the first fil_space_t on fil_system->space_list.
 @return pointer to the next fil_space_t.
 @retval NULL if this was the last*/
+UNIV_INTERN
 fil_space_t*
 fil_space_next(fil_space_t* prev_space)
 {
 	fil_space_t*		space=prev_space;
 
@@ -7276,10 +7328,11 @@ fil_space_acquire() and fil_space_release() are invoked here which
 blocks a concurrent operation from dropping the tablespace.
 @param[in]	prev_space	Pointer to the previous fil_space_t.
 If NULL, use the first fil_space_t on fil_system->space_list.
 @return pointer to the next fil_space_t.
 @retval NULL if this was the last*/
+UNIV_INTERN
 fil_space_t*
 fil_space_keyrotate_next(
 	fil_space_t*	prev_space)
 {
 	fil_space_t* space = prev_space;
```

### `storage/innobase/fil/fil0pagecompress.cc`

```diff
--- from commit 4b24467ff37d ---
diff --git a/storage/innobase/fil/fil0pagecompress.cc b/storage/innobase/fil/fil0pagecompress.cc
index 41966cf005a..cb3e50745a7 100644
--- a/storage/innobase/fil/fil0pagecompress.cc
+++ b/storage/innobase/fil/fil0pagecompress.cc
@@ -629,18 +629,19 @@ error_return:
 
 err_exit:
 	/* Note that as we have found the page is corrupted, so
 	all this could be incorrect. */
 	ulint space_id = mach_read_from_4(buf+FIL_PAGE_SPACE_ID);
-	const FilSpace space(space_id, true);
+	fil_space_t* space = fil_space_acquire_for_io(space_id);
 
 	ib::error() << "Corruption: Page is marked as compressed"
 		    << " space: " <<  space_id << " name: "
-		    << (space() ? space()->name : "NULL")
+		    << (space ? space->name : "NULL")
 		    << " but uncompress failed with error: " << err
 		    << " size: " << actual_size
 		    << " len: " << len
 		    << " compression method: "
 		    << fil_get_compression_alg_name(compression_alg) << ".";
 
 	buf_page_print(buf, univ_page_size, 0);
+	fil_space_release_for_io(space);
 }
```

### `storage/innobase/include/buf0buf.h`

```diff
--- from commit 4b24467ff37d ---
diff --git a/storage/innobase/include/buf0buf.h b/storage/innobase/include/buf0buf.h
index 6832c133d58..746ac6a25bd 100644
--- a/storage/innobase/include/buf0buf.h
+++ b/storage/innobase/include/buf0buf.h
@@ -833,21 +833,10 @@ buf_page_is_checksum_valid_none(
 	const srv_checksum_algorithm_t	curr_algo
 #endif	/* UNIV_INNOCHECKSUM */
 	)
 	MY_ATTRIBUTE((nonnull(1), warn_unused_result));
 
-/********************************************************************//**
-Check if page is maybe compressed, encrypted or both when we encounter
-corrupted page. Note that we can't be 100% sure if page is corrupted
-or decrypt/decompress just failed.
-@param[in]	bpage		Page
-@return true if page corrupted, false if not */
-bool
-buf_page_check_corrupt(
-	buf_page_t*	bpage)	/*!< in/out: buffer page read from disk */
-	MY_ATTRIBUTE((nonnull, warn_unused_result));
-
 /** Checks if a page contains only zeroes.
 @param[in]	read_buf	database page
 @param[in]	page_size	page size
 @return true if page is filled with zeroes */
 bool
--- from commit b82c602db588 ---
diff --git a/storage/innobase/include/buf0buf.h b/storage/innobase/include/buf0buf.h
index 3dc2bfc7e5d..1301e112078 100644
--- a/storage/innobase/include/buf0buf.h
+++ b/storage/innobase/include/buf0buf.h
@@ -1,9 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1995, 2016, Oracle and/or its affiliates. All Rights Reserved.
-Copyright (c) 2013, 2017, MariaDB Corporation. All Rights Reserved.
+Copyright (c) 2013, 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -677,33 +677,31 @@ buf_page_is_checksum_valid_none(
 	const byte*	read_buf,
 	ulint		checksum_field1,
 	ulint		checksum_field2)
 	MY_ATTRIBUTE((warn_unused_result));
 
-/********************************************************************//**
-Checks if a page is corrupt.
+/** Check if a page is corrupt.
 @param[in]	check_lsn		true if LSN should be checked
 @param[in]	read_buf		Page to be checked
 @param[in]	zip_size		compressed size or 0
 @param[in]	space			Pointer to tablespace
 @return	true if corrupted, false if not */
+UNIV_INTERN
 bool
 buf_page_is_corrupted(
 	bool			check_lsn,
 	const byte*		read_buf,
 	ulint			zip_size,
 	const fil_space_t* 	space)
 	MY_ATTRIBUTE((warn_unused_result));
-/********************************************************************//**
-Checks if a page is all zeroes.
-@return	TRUE if the page is all zeroes */
+/** Check if a page is all zeroes.
+@param[in]	read_buf	database page
+@param[in]	zip_size	ROW_FORMAT=COMPRESSED page size, or 0
+@return	whether the page is all zeroes */
+UNIV_INTERN
 bool
-buf_page_is_zeroes(
-/*===============*/
-	const byte*	read_buf,	/*!< in: a database page */
-	const ulint	zip_size);	/*!< in: size of compressed page;
-					0 for uncompressed pages */
+buf_page_is_zeroes(const byte* read_buf, ulint zip_size);
 #ifndef UNIV_HOTBACKUP
 /**********************************************************************//**
 Gets the space id, page offset, and byte offset within page of a
 pointer pointing to a buffer frame containing a file page. */
 UNIV_INLINE
@@ -1238,24 +1236,24 @@ buf_page_init_for_read(
 	ibool		unzip,	/*!< in: TRUE=request uncompressed page */
 	ib_int64_t	tablespace_version,/*!< in: prevents reading from a wrong
 				version of the tablespace in case we have done
 				DISCARD + IMPORT */
 	ulint		offset);/*!< in: page number */
-/********************************************************************//**
-Completes an asynchronous read or write request of a file page to or from
-the buffer pool.
-@param[in,out]	bpage		pointer to the block in question
-@param[in]	evict		true if page should be evicted from LRU
-@return DB_SUCCESS if page has been read and is not corrupted,
-DB_PAGE_CORRUPTED if page based on checksum check is corrupted,
-DB_DECRYPTION_FAILED if page post encryption checksum matches but
-after decryption normal page checksum does not match.*/
+/** Complete a read or write request of a file page to or from the buffer pool.
+@param[in,out]		bpage		Page to complete
+@param[in]		evict		whether or not to evict the page
+					from LRU list.
+@return whether the operation succeeded
+@retval	DB_SUCCESS		always when writing, or if a read page was OK
+@retval	DB_PAGE_CORRUPTED	if the checksum fails on a page read
+@retval	DB_DECRYPTION_FAILED	if page post encryption checksum matches but
+				after decryption normal page checksum does
+				not match */
 UNIV_INTERN
 dberr_t
-buf_page_io_complete(
-	buf_page_t*	bpage,
-	bool		evict = false);
+buf_page_io_complete(buf_page_t* bpage, bool evict = false)
+	MY_ATTRIBUTE((nonnull));
 
 /********************************************************************//**
 Calculates a folded value of a file page address to use in the page hash
 table.
 @return	the folded value */
```

### `storage/innobase/include/fil0fil.h`

```diff
--- from commit 4b24467ff37d ---
diff --git a/storage/innobase/include/fil0fil.h b/storage/innobase/include/fil0fil.h
index 188e0b0bd3b..cef5b578a4a 100644
--- a/storage/innobase/include/fil0fil.h
+++ b/storage/innobase/include/fil0fil.h
@@ -140,18 +140,25 @@ struct fil_space_t {
 				/*!< number of reserved free extents for
 				ongoing operations like B-tree page split */
 	ulint		n_pending_flushes; /*!< this is positive when flushing
 				the tablespace to disk; dropping of the
 				tablespace is forbidden if this is positive */
-	ulint		n_pending_ops;/*!< this is positive when we
-				have pending operations against this
-				tablespace. The pending operations can
-				be ibuf merges or lock validation code
-				trying to read a block.
-				Dropping of the tablespace is forbidden
-				if this is positive.
-				Protected by fil_system->mutex. */
+	/** Number of pending buffer pool operations accessing the tablespace
+	without holding a table lock or dict_operation_lock S-latch
+	that would prevent the table (and tablespace) from being
+	dropped. An example is change buffer merge.
+	The tablespace cannot be dropped while this is nonzero,
+	or while fil_node_t::n_pending is nonzero.
+	Protected by fil_system->mutex. */
+	ulint		n_pending_ops;
+	/** Number of pending block read or write operations
+	(when a write is imminent or a read has recently completed).
+	The tablespace object cannot be freed while this is nonzero,
+	but it can be detached from fil_system.
+	Note that fil_node_t::n_pending tracks actual pending I/O requests.
+	Protected by fil_system->mutex. */
+	ulint		n_pending_ios;
 	hash_node_t	hash;	/*!< hash chain node */
 	hash_node_t	name_hash;/*!< hash chain the name_hash table */
 	rw_lock_t	latch;	/*!< latch protecting the file space storage
 				allocation */
 	UT_LIST_NODE_T(fil_space_t) unflushed_spaces;
@@ -724,16 +731,14 @@ MY_ATTRIBUTE((warn_unused_result));
 
 /** Acquire a tablespace when it could be dropped concurrently.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
 @param[in]	id	tablespace ID
-@param[in]	for_io	whether to look up the tablespace while performing I/O
-			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted or truncated */
 fil_space_t*
-fil_space_acquire(ulint id, bool for_io = false)
+fil_space_acquire(ulint id)
 	MY_ATTRIBUTE((warn_unused_result));
 
 /** Acquire a tablespace that may not exist.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
@@ -747,10 +752,23 @@ fil_space_acquire_silent(ulint id)
 /** Release a tablespace acquired with fil_space_acquire().
 @param[in,out]	space	tablespace to release  */
 void
 fil_space_release(fil_space_t* space);
 
+/** Acquire a tablespace for reading or writing a block,
+when it could be dropped concurrently.
+@param[in]	id	tablespace ID
+@return	the tablespace
+@retval	NULL if missing */
+fil_space_t*
+fil_space_acquire_for_io(ulint id);
+
+/** Release a tablespace acquired with fil_space_acquire_for_io().
+@param[in,out]	space	tablespace to release  */
+void
+fil_space_release_for_io(fil_space_t* space);
+
 /** Return the next fil_space_t.
 Once started, the caller must keep calling this until it returns NULL.
 fil_space_acquire() and fil_space_release() are invoked here which
 blocks a concurrent operation from dropping the tablespace.
 @param[in,out]	prev_space	Pointer to the previous fil_space_t.
@@ -783,16 +801,13 @@ public:
 	is done outside this wrapper. */
 	FilSpace() : m_space(NULL) {}
 
 	/** Constructor: Look up the tablespace and increment the
 	reference count if found.
-	@param[in]	space_id	tablespace ID
-	@param[in]	for_io		whether to look up the tablespace
-					while performing I/O
-					(possibly executing TRUNCATE) */
-	explicit FilSpace(ulint space_id, bool for_io = false)
-		: m_space(fil_space_acquire(space_id, for_io)) {}
+	@param[in]	space_id	tablespace ID */
+	explicit FilSpace(ulint space_id)
+		: m_space(fil_space_acquire(space_id)) {}
 
 	/** Assignment operator: This assumes that fil_space_acquire()
 	has already been done for the fil_space_t. The caller must
 	assign NULL if it calls fil_space_release().
 	@param[in]	space	tablespace to assign */
--- from commit b82c602db588 ---
diff --git a/storage/innobase/include/fil0fil.h b/storage/innobase/include/fil0fil.h
index 0bf0364afba..599abc88fa3 100644
--- a/storage/innobase/include/fil0fil.h
+++ b/storage/innobase/include/fil0fil.h
@@ -318,17 +318,25 @@ struct fil_space_t {
 				/*!< number of reserved free extents for
 				ongoing operations like B-tree page split */
 	ulint		n_pending_flushes; /*!< this is positive when flushing
 				the tablespace to disk; dropping of the
 				tablespace is forbidden if this is positive */
-	ulint		n_pending_ops;/*!< this is positive when we
-				have pending operations against this
-				tablespace. The pending operations can
-				be ibuf merges or lock validation code
-				trying to read a block.
-				Dropping of the tablespace is forbidden
-				if this is positive */
+	/** Number of pending buffer pool operations accessing the tablespace
+	without holding a table lock or dict_operation_lock S-latch
+	that would prevent the table (and tablespace) from being
+	dropped. An example is change buffer merge.
+	The tablespace cannot be dropped while this is nonzero,
+	or while fil_node_t::n_pending is nonzero.
+	Protected by fil_system->mutex. */
+	ulint		n_pending_ops;
+	/** Number of pending block read or write operations
+	(when a write is imminent or a read has recently completed).
+	The tablespace object cannot be freed while this is nonzero,
+	but it can be detached from fil_system.
+	Note that fil_node_t::n_pending tracks actual pending I/O requests.
+	Protected by fil_system->mutex. */
+	ulint		n_pending_ios;
 	hash_node_t	hash;	/*!< hash chain node */
 	hash_node_t	name_hash;/*!< hash chain the name_hash table */
 #ifndef UNIV_HOTBACKUP
 	rw_lock_t	latch;	/*!< latch protecting the file space storage
 				allocation */
@@ -644,17 +652,15 @@ fil_write_flushed_lsn_to_data_files(
 /** Acquire a tablespace when it could be dropped concurrently.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
 @param[in]	id	tablespace ID
 @param[in]	silent	whether to silently ignore missing tablespaces
-@param[in]	for_io	whether to look up the tablespace while performing I/O
-			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted or truncated */
 UNIV_INTERN
 fil_space_t*
-fil_space_acquire_low(ulint id, bool silent, bool for_io = false)
+fil_space_acquire_low(ulint id, bool silent)
 	MY_ATTRIBUTE((warn_unused_result));
 
 /** Acquire a tablespace when it could be dropped concurrently.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
@@ -663,43 +669,58 @@ for concurrency control.
 			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted or truncated */
 inline
 fil_space_t*
-fil_space_acquire(ulint id, bool for_io = false)
+fil_space_acquire(ulint id)
 {
-	return (fil_space_acquire_low(id, false, for_io));
+	return(fil_space_acquire_low(id, false));
 }
 
 /** Acquire a tablespace that may not exist.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
 @param[in]	id	tablespace ID
-@param[in]	for_io	whether to look up the tablespace while performing I/O
-			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted */
 inline
 fil_space_t*
-fil_space_acquire_silent(ulint id, bool for_io = false)
+fil_space_acquire_silent(ulint id)
 {
-	return (fil_space_acquire_low(id, true, for_io));
+	return(fil_space_acquire_low(id, true));
 }
 
 /** Release a tablespace acquired with fil_space_acquire().
 @param[in,out]	space	tablespace to release  */
+UNIV_INTERN
 void
 fil_space_release(fil_space_t* space);
 
+/** Acquire a tablespace for reading or writing a block,
+when it could be dropped concurrently.
+@param[in]	id	tablespace ID
+@return	the tablespace
+@retval	NULL if missing */
+UNIV_INTERN
+fil_space_t*
+fil_space_acquire_for_io(ulint id);
+
+/** Release a tablespace acquired with fil_space_acquire_for_io().
+@param[in,out]	space	tablespace to release  */
+UNIV_INTERN
+void
+fil_space_release_for_io(fil_space_t* space);
+
 /** Return the next fil_space_t.
 Once started, the caller must keep calling this until it returns NULL.
 fil_space_acquire() and fil_space_release() are invoked here which
 blocks a concurrent operation from dropping the tablespace.
 @param[in,out]	prev_space	Pointer to the previous fil_space_t.
 If NULL, use the first fil_space_t on fil_system->space_list.
 @return pointer to the next fil_space_t.
 @retval NULL if this was the last  */
+UNIV_INTERN
 fil_space_t*
 fil_space_next(
 	fil_space_t*	prev_space)
 	MY_ATTRIBUTE((warn_unused_result));
 
@@ -709,10 +730,11 @@ fil_space_acquire() and fil_space_release() are invoked here which
 blocks a concurrent operation from dropping the tablespace.
 @param[in,out]	prev_space	Pointer to the previous fil_space_t.
 If NULL, use the first fil_space_t on fil_system->space_list.
 @return pointer to the next fil_space_t.
 @retval NULL if this was the last*/
+UNIV_INTERN
 fil_space_t*
 fil_space_keyrotate_next(
 	fil_space_t*	prev_space)
 	MY_ATTRIBUTE((warn_unused_result));
 
@@ -725,16 +747,13 @@ public:
 	FilSpace() : m_space(NULL) {}
 
 	/** Constructor: Look up the tablespace and increment the
 	reference count if found.
 	@param[in]	space_id	tablespace ID
-	@param[in]	silent		whether not print any errors
-	@param[in]	for_io		whether to look up the tablespace
-					while performing I/O
-					(possibly executing TRUNCATE) */
-	explicit FilSpace(ulint space_id, bool silent = false, bool for_io = false)
-		: m_space(fil_space_acquire_low(space_id, silent, for_io)) {}
+	@param[in]	silent		whether not to print any errors */
+	explicit FilSpace(ulint space_id, bool silent = false)
+		: m_space(fil_space_acquire_low(space_id, silent)) {}
 
 	/** Assignment operator: This assumes that fil_space_acquire()
 	has already been done for the fil_space_t. The caller must
 	assign NULL if it calls fil_space_release().
 	@param[in]	space	tablespace to assign */
```

### `storage/xtradb/buf/buf0buf.cc`

```diff
--- from commit b82c602db588 ---
diff --git a/storage/xtradb/buf/buf0buf.cc b/storage/xtradb/buf/buf0buf.cc
index 4593f84b43b..8873e2bcb42 100644
--- a/storage/xtradb/buf/buf0buf.cc
+++ b/storage/xtradb/buf/buf0buf.cc
@@ -63,10 +63,19 @@ Created 11/5/1995 Heikki Tuuri
 #include "srv0start.h"
 #include "ut0byte.h"
 #include "fil0pagecompress.h"
 #include "ha_prototypes.h"
 
+/** Decrypt a page.
+@param[in,out]	bpage	Page control block
+@param[in,out]	space	tablespace
+@return whether the operation was successful */
+static
+bool
+buf_page_decrypt_after_read(buf_page_t* bpage, fil_space_t* space)
+	MY_ATTRIBUTE((nonnull));
+
 /* prototypes for new functions added to ha_innodb.cc */
 trx_t* innobase_get_trx();
 
 static inline
 void
@@ -546,20 +555,17 @@ buf_block_alloc(
 
 	return(block);
 }
 #endif /* !UNIV_HOTBACKUP */
 
-/********************************************************************//**
-Checks if a page is all zeroes.
-@return	TRUE if the page is all zeroes */
+/** Check if a page is all zeroes.
+@param[in]	read_buf	database page
+@param[in]	zip_size	ROW_FORMAT=COMPRESSED page size, or 0
+@return	whether the page is all zeroes */
 UNIV_INTERN
 bool
-buf_page_is_zeroes(
-/*===============*/
-	const byte*	read_buf,	/*!< in: a database page */
-	const ulint	zip_size)	/*!< in: size of compressed page;
-					0 for uncompressed pages */
+buf_page_is_zeroes(const byte* read_buf, ulint zip_size)
 {
 	const ulint page_size = zip_size ? zip_size : UNIV_PAGE_SIZE;
 
 	for (ulint i = 0; i < page_size; i++) {
 		if (read_buf[i] != 0) {
@@ -671,12 +677,11 @@ buf_page_is_checksum_valid_none(
 
 	return(checksum_field1 == checksum_field2
 	       && checksum_field1 == BUF_NO_CHECKSUM_MAGIC);
 }
 
-/********************************************************************//**
-Checks if a page is corrupt.
+/** Check if a page is corrupt.
 @param[in]	check_lsn		true if LSN should be checked
 @param[in]	read_buf		Page to be checked
 @param[in]	zip_size		compressed size or 0
 @param[in]	space			Pointer to tablespace
 @return	true if corrupted, false if not */
@@ -4524,38 +4529,34 @@ buf_mark_space_corrupt(
 	ut_ad(buf_pool->n_pend_reads > 0);
 	os_atomic_decrement_ulint(&buf_pool->n_pend_reads, 1);
 	mutex_exit(&buf_pool->LRU_list_mutex);
 }
 
-/********************************************************************//**
-Check if page is maybe compressed, encrypted or both when we encounter
+/** Check if page is maybe compressed, encrypted or both when we encounter
 corrupted page. Note that we can't be 100% sure if page is corrupted
 or decrypt/decompress just failed.
-@param[in,out]	bpage		Page
-@return DB_SUCCESS if page has been read and is not corrupted,
-@retval DB_PAGE_CORRUPTED if page based on checksum check is corrupted,
-@retval DB_DECRYPTION_FAILED if page post encryption checksum matches but
+@param[in,out]	bpage		page
+@param[in,out]	space		tablespace from fil_space_acquire_for_io()
+@return	whether the operation succeeded
+@retval	DB_SUCCESS		if page has been read and is not corrupted
+@retval	DB_PAGE_CORRUPTED	if page based on checksum check is corrupted
+@retval	DB_DECRYPTION_FAILED	if page post encryption checksum matches but
 after decryption normal page checksum does not match.
-@retval DB_TABLESPACE_DELETED if accessed tablespace is not found */
+@retval	DB_TABLESPACE_DELETED	if accessed tablespace is not found */
 static
 dberr_t
-buf_page_check_corrupt(buf_page_t*	bpage)
+buf_page_check_corrupt(buf_page_t* bpage, fil_space_t* space)
 {
+	ut_ad(space->n_pending_ios > 0);
+
 	ulint zip_size = buf_page_get_zip_size(bpage);
 	byte* dst_frame = (zip_size) ? bpage->zip.data :
 		((buf_block_t*) bpage)->frame;
-	FilSpace space(bpage->space, true);
 	bool still_encrypted = false;
 	dberr_t err = DB_SUCCESS;
 	bool corrupted = false;
-	fil_space_crypt_t* crypt_data = NULL;
-
-	if (!space()) {
-		return(DB_TABLESPACE_DELETED);
-	}
-
-	crypt_data = space()->crypt_data;
+	fil_space_crypt_t* crypt_data = space->crypt_data;
 
 	/* In buf_decrypt_after_read we have either decrypted the page if
 	page post encryption checksum matches and used key_id is found
 	from the encryption plugin. If checksum did not match page was
 	not decrypted and it could be either encrypted and corrupted
@@ -4563,16 +4564,16 @@ buf_page_check_corrupt(buf_page_t*	bpage)
 	still be corrupted if used key does not match. */
 	still_encrypted = (crypt_data &&
 		crypt_data->type != CRYPT_SCHEME_UNENCRYPTED &&
 		!bpage->encrypted &&
 		fil_space_verify_crypt_checksum(dst_frame, zip_size,
-			space(), bpage->offset));
-
+			space, bpage->offset));
 	if (!still_encrypted) {
 		/* If traditional checksums match, we assume that page is
 		not anymore encrypted. */
-		corrupted = buf_page_is_corrupted(true, dst_frame, zip_size, space());
+		corrupted = buf_page_is_corrupted(true, dst_frame, zip_size,
+						  space);
 
 		if (!corrupted) {
 			bpage->encrypted = false;
 		} else {
 			err = DB_PAGE_CORRUPTED;
@@ -4591,11 +4592,11 @@ buf_page_check_corrupt(buf_page_t*	bpage)
 		ib_logf(IB_LOG_LEVEL_ERROR,
 			"The page [page id: space=%u"
 			", page number=%u]"
 			" in file %s cannot be decrypted.",
 			bpage->space, bpage->offset,
-			space()->name);
+			space->name);
 
 		ib_logf(IB_LOG_LEVEL_INFO,
 			"However key management plugin or used key_version " ULINTPF
 			" is not found or"
 			" used encryption algorithm or method does not match.",
@@ -4609,30 +4610,27 @@ buf_page_check_corrupt(buf_page_t*	bpage)
 	}
 
 	return (err);
 }
 
-/********************************************************************//**
-Completes an asynchronous read or write request of a file page to or from
-the buffer pool.
+/** Complete a read or write request of a file page to or from the buffer pool.
 @param[in,out]		bpage		Page to complete
-@return DB_SUCCESS if page has been read and is not corrupted,
-DB_PAGE_CORRUPTED if page based on checksum check is corrupted,
-DB_DECRYPTION_FAILED if page post encryption checksum matches but
-after decryption normal page checksum does not match.
-in write only DB_SUCCESS is possible. */
+@return whether the operation succeeded
+@retval	DB_SUCCESS		always when writing, or if a read page was OK
+@retval	DB_PAGE_CORRUPTED	if the checksum fails on a page read
+@retval	DB_DECRYPTION_FAILED	if page post encryption checksum matches but
+				after decryption normal page checksum does
+				not match */
 UNIV_INTERN
 dberr_t
-buf_page_io_complete(
-	buf_page_t*	bpage)
+buf_page_io_complete(buf_page_t* bpage)
 {
 	enum buf_io_fix	io_type;
 	buf_pool_t*	buf_pool = buf_pool_from_bpage(bpage);
 	const ibool	uncompressed = (buf_page_get_state(bpage)
 					== BUF_BLOCK_FILE_PAGE);
 	bool		have_LRU_mutex = false;
-	fil_space_t*	space = NULL;
 	byte*		frame = NULL;
 	dberr_t 	err = DB_SUCCESS;
 
 	ut_a(buf_page_in_file(bpage));
 
@@ -4648,11 +4646,17 @@ buf_page_io_complete(
 	if (io_type == BUF_IO_READ) {
 		ulint	read_page_no = 0;
 		ulint	read_space_id = 0;
 		uint	key_version = 0;
 
-		buf_page_decrypt_after_read(bpage);
+		ut_ad(bpage->zip.data || ((buf_block_t*)bpage)->frame);
+		fil_space_t* space = fil_space_acquire_for_io(bpage->space);
+		if (!space) {
+			return(DB_TABLESPACE_DELETED);
+		}
+
+		buf_page_decrypt_after_read(bpage, space);
 
 		if (buf_page_get_zip_size(bpage)) {
 			frame = bpage->zip.data;
 		} else {
 			frame = ((buf_block_t*) bpage)->frame;
@@ -4722,11 +4726,11 @@ buf_page_io_complete(
 				bpage->offset);
 		}
 
 		if (UNIV_LIKELY(!bpage->is_corrupt ||
 				!srv_pass_corrupt_table)) {
-			err = buf_page_check_corrupt(bpage);
+			err = buf_page_check_corrupt(bpage, space);
 		}
 
 database_corrupted:
 
 		if (err != DB_SUCCESS) {
@@ -4735,32 +4739,28 @@ database_corrupted:
 			DBUG_EXECUTE_IF("buf_page_is_corrupt_failure",
 				if (bpage->space > TRX_SYS_SPACE) {
 					buf_mark_space_corrupt(bpage);
 					ib_logf(IB_LOG_LEVEL_INFO,
 						"Simulated page corruption");
+					fil_space_release_for_io(space);
 					return(err);
 				}
 				err = DB_SUCCESS;
 				goto page_not_corrupt;
 			);
 
 			if (err == DB_PAGE_CORRUPTED) {
-				fil_system_enter();
-				space = fil_space_get_by_id(bpage->space);
-
 				ib_logf(IB_LOG_LEVEL_ERROR,
 					"Database page corruption on disk"
 					" or a failed file read of tablespace %s"
 					" page  [page id: space=%u"
 					", page number=%u]"
 					". You may have to recover from "
 					"a backup.",
 					space->name,
 					bpage->space, bpage->offset);
 
-				fil_system_exit();
-
 				buf_page_print(frame, buf_page_get_zip_size(bpage),
 					BUF_PAGE_PRINT_NO_CRASH);
 
 				ib_logf(IB_LOG_LEVEL_INFO,
 					"It is also possible that your"
@@ -4793,10 +4793,11 @@ database_corrupted:
 				/* If page space id is larger than TRX_SYS_SPACE
 				(0), we will attempt to mark the corresponding
 				table as corrupted instead of crashing server */
 				if (bpage->space > TRX_SYS_SPACE) {
 					buf_mark_space_corrupt(bpage);
+					fil_space_release_for_io(space);
 					return(err);
 				} else {
 					ib_logf(IB_LOG_LEVEL_FATAL,
 						"Ending processing because of a corrupt database page.");
 				}
@@ -4831,10 +4832,12 @@ database_corrupted:
 					bpage->offset, buf_page_get_zip_size(bpage),
 					TRUE);
 			}
 
 		}
+
+		fil_space_release_for_io(space);
 	} else {
 		/* io_type == BUF_IO_WRITE */
 		if (bpage->slot) {
 			/* Mark slot free */
 			bpage->slot->reserved = false;
@@ -6301,20 +6304,21 @@ buf_page_encrypt_before_write(
 
 	// return dst_frame which will be written
 	return dst_frame;
 }
 
-/********************************************************************//**
-Decrypt page after it has been read from disk
-@param[in,out]	bpage		Page control block
-@return true if successfull, false if something went wrong
-*/
-UNIV_INTERN
+/** Decrypt a page.
+@param[in,out]	bpage	Page control block
+@param[in,out]	space	tablespace
+@return whether the operation was successful */
+static
 bool
-buf_page_decrypt_after_read(
-	buf_page_t*	bpage)
+buf_page_decrypt_after_read(buf_page_t* bpage, fil_space_t* space)
 {
+	ut_ad(space->n_pending_ios > 0);
+	ut_ad(space->id == bpage->space);
+
 	ulint zip_size = buf_page_get_zip_size(bpage);
 	ulint size = (zip_size) ? zip_size : UNIV_PAGE_SIZE;
 
 	byte* dst_frame = (zip_size) ? bpage->zip.data :
 		((buf_block_t*) bpage)->frame;
@@ -6328,16 +6332,14 @@ buf_page_decrypt_after_read(
 	if (bpage->offset == 0) {
 		/* File header pages are not encrypted/compressed */
 		return (true);
 	}
 
-	FilSpace space(bpage->space, false, true);
-
 	/* Page is encrypted if encryption information is found from
 	tablespace and page contains used key_version. This is true
 	also for pages first compressed and then encrypted. */
-	if (!space() || !space()->crypt_data) {
+	if (!space->crypt_data) {
 		key_version = 0;
 	}
 
 	if (page_compressed) {
 		/* the page we read is unencrypted */
@@ -6370,12 +6372,12 @@ buf_page_decrypt_after_read(
 			if (!fil_space_verify_crypt_checksum(dst_frame,
 					zip_size, NULL, bpage->offset)) {
 
 				/* Mark page encrypted in case it should
 				be. */
-				if (key_version && space()->crypt_data &&
-				    space()->crypt_data->type != CRYPT_SCHEME_UNENCRYPTED) {
+				if (space->crypt_data->type
+				    != CRYPT_SCHEME_UNENCRYPTED) {
 					bpage->encrypted = true;
 				}
 
 				return (false);
 			}
@@ -6386,16 +6388,12 @@ buf_page_decrypt_after_read(
 #ifdef UNIV_DEBUG
 			fil_page_type_validate(dst_frame);
 #endif
 
 			/* decrypt using crypt_buf to dst_frame */
-			byte* res = fil_space_decrypt(space(),
-						slot->crypt_buf,
-						dst_frame,
-						&bpage->encrypted);
-
-			if (!res) {
+			if (!fil_space_decrypt(space, slot->crypt_buf,
+					       dst_frame, &bpage->encrypted)) {
 				success = false;
 			}
 
 #ifdef UNIV_DEBUG
 			fil_page_type_validate(dst_frame);
@@ -6422,7 +6420,8 @@ buf_page_decrypt_after_read(
 		if (slot) {
 			slot->reserved = false;
 		}
 	}
 
+	ut_ad(space->n_pending_ios > 0);
 	return (success);
 }
```

### `storage/xtradb/buf/buf0flu.cc`

```diff
--- from commit b82c602db588 ---
diff --git a/storage/xtradb/buf/buf0flu.cc b/storage/xtradb/buf/buf0flu.cc
index 9c9823bbc28..6f8bbd75d99 100644
--- a/storage/xtradb/buf/buf0flu.cc
+++ b/storage/xtradb/buf/buf0flu.cc
@@ -871,11 +871,11 @@ buf_flush_write_block_low(
 /*======================*/
 	buf_page_t*	bpage,		/*!< in: buffer block to write */
 	buf_flush_t	flush_type,	/*!< in: type of flush */
 	bool		sync)		/*!< in: true if sync IO request */
 {
-	fil_space_t*	space = fil_space_acquire(bpage->space, true);
+	fil_space_t*	space = fil_space_acquire_for_io(bpage->space);
 	if (!space) {
 		return;
 	}
 	ulint	zip_size	= buf_page_get_zip_size(bpage);
 	page_t*	frame		= NULL;
@@ -993,19 +993,26 @@ buf_flush_write_block_low(
 	are working on. */
 	if (sync) {
 		ut_ad(flush_type == BUF_FLUSH_SINGLE_PAGE);
 		fil_flush(space);
 
+		/* The tablespace could already have been dropped,
+		because fil_io(request, sync) would already have
+		decremented the node->n_pending. However,
+		buf_page_io_complete() only needs to look up the
+		tablespace during read requests, not during writes. */
+		ut_ad(buf_page_get_io_fix_unlocked(bpage) == BUF_IO_WRITE);
+
 #ifdef UNIV_DEBUG
 		dberr_t err =
 #endif
 		buf_page_io_complete(bpage);
 
 		ut_ad(err == DB_SUCCESS);
 	}
 
-	fil_space_release(space);
+	fil_space_release_for_io(space);
 
 	/* Increment the counter of I/O operations used
 	for selecting LRU policy. */
 	buf_LRU_stat_inc_io();
 }
```

### `storage/xtradb/fil/fil0crypt.cc`

```diff
--- from commit b82c602db588 ---
diff --git a/storage/xtradb/fil/fil0crypt.cc b/storage/xtradb/fil/fil0crypt.cc
index 72a4e713e60..3537ad2c66a 100644
--- a/storage/xtradb/fil/fil0crypt.cc
+++ b/storage/xtradb/fil/fil0crypt.cc
@@ -681,11 +681,11 @@ fil_space_encrypt(
 	if (!space->crypt_data || !space->crypt_data->is_encrypted()) {
 		return (src_frame);
 	}
 
 	fil_space_crypt_t* crypt_data = space->crypt_data;
-	ut_ad(space->n_pending_ops);
+	ut_ad(space->n_pending_ios > 0);
 	ulint zip_size = fsp_flags_get_zip_size(space->flags);
 	byte* tmp = fil_encrypt_buf(crypt_data, space->id, offset, lsn, src_frame, zip_size, dst_frame);
 
 #ifdef UNIV_DEBUG
 	if (tmp) {
@@ -858,11 +858,11 @@ fil_space_decrypt(
 	ulint zip_size = fsp_flags_get_zip_size(space->flags);
 	ulint size = zip_size ? zip_size : UNIV_PAGE_SIZE;
 	*decrypted = false;
 
 	ut_ad(space->crypt_data != NULL && space->crypt_data->is_encrypted());
-	ut_ad(space->n_pending_ops > 0);
+	ut_ad(space->n_pending_ios > 0);
 
 	bool encrypted = fil_space_decrypt(
 				space->crypt_data,
 				tmp_frame,
 				size,
```

### `storage/xtradb/fil/fil0fil.cc`

```diff
--- from commit b82c602db588 ---
diff --git a/storage/xtradb/fil/fil0fil.cc b/storage/xtradb/fil/fil0fil.cc
index c95fd872c67..e39be46840c 100644
--- a/storage/xtradb/fil/fil0fil.cc
+++ b/storage/xtradb/fil/fil0fil.cc
@@ -1,9 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1995, 2016, Oracle and/or its affiliates. All Rights Reserved.
-Copyright (c) 2014, 2017, MariaDB Corporation. All Rights Reserved.
+Copyright (c) 2014, 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -247,22 +247,20 @@ fil_node_complete_io(
 	fil_node_t*	node,	/*!< in: file node */
 	fil_system_t*	system,	/*!< in: tablespace memory cache */
 	ulint		type);	/*!< in: OS_FILE_WRITE or OS_FILE_READ; marks
 				the node as modified if
 				type == OS_FILE_WRITE */
-/*******************************************************************//**
-Frees a space object from the tablespace memory cache. Closes the files in
-the chain but does not delete them. There must not be any pending i/o's or
+/** Free a space object from the tablespace memory cache. Close the files in
+the chain but do not delete them. There must not be any pending i/o's or
 flushes on the files.
-@return TRUE on success */
+The fil_system->mutex will be released.
+@param[in]	id		tablespace ID
+@param[in]	x_latched	whether the caller holds exclusive space->latch
+@return whether the tablespace existed */
 static
-ibool
-fil_space_free(
-/*===========*/
-	ulint		id,		/* in: space id */
-	ibool		x_latched);	/* in: TRUE if caller has space->latch
-					in X mode */
+bool
+fil_space_free_and_mutex_exit(ulint id, bool x_latched);
 /********************************************************************//**
 Reads data from a space to a buffer. Remember that the possible incomplete
 blocks at the end of file are ignored: they are not taken into account when
 calculating the byte offset within a space.
 @return DB_SUCCESS, or DB_TABLESPACE_DELETED if we are trying to do
@@ -1367,22 +1365,18 @@ retry:
 			space->recv_size = 0;
 		}
 	}
 }
 
-/*******************************************************************//**
-Frees a file node object from a tablespace memory cache. */
+/** Prepare a data file object for freeing.
+@param[in,out]	space	tablespace
+@param[in,out]	node	data file */
 static
 void
-fil_node_free(
-/*==========*/
-	fil_node_t*	node,	/*!< in, own: file node */
-	fil_system_t*	system,	/*!< in: tablespace memory cache */
-	fil_space_t*	space)	/*!< in: space where the file node is chained */
+fil_node_free_part1(fil_space_t* space, fil_node_t* node)
 {
-	ut_ad(node && system && space);
-	ut_ad(mutex_own(&(system->mutex)));
+	ut_ad(mutex_own(&fil_system->mutex));
 	ut_a(node->magic_n == FIL_NODE_MAGIC_N);
 	ut_a(node->n_pending == 0);
 	ut_a(!node->being_extended);
 
 	if (node->open) {
@@ -1401,16 +1395,26 @@ fil_node_free(
 			   && fil_space_is_flushed(space)) {
 
 			space->is_in_unflushed_spaces = false;
 
 			UT_LIST_REMOVE(unflushed_spaces,
-				       system->unflushed_spaces,
+				       fil_system->unflushed_spaces,
 				       space);
 		}
 
-		fil_node_close_file(node, system);
+		fil_node_close_file(node, fil_system);
 	}
+}
+
+/** Free a data file object.
+@param[in,out]	space	tablespace
+@param[in]	node	data file */
+static
+void
+fil_node_free_part2(fil_space_t* space, fil_node_t* node)
+{
+	ut_ad(!node->open);
 
 	space->size -= node->size;
 
 	UT_LIST_REMOVE(chain, space->chain, node);
 
@@ -1446,11 +1450,12 @@ fil_space_truncate_start(
 
 		ut_a(node->size * UNIV_PAGE_SIZE <= trunc_len);
 
 		trunc_len -= node->size * UNIV_PAGE_SIZE;
 
-		fil_node_free(node, fil_system, space);
+		fil_node_free_part1(space, node);
+		fil_node_free_part2(space, node);
 	}
 
 	mutex_exit(&fil_system->mutex);
 }
 
@@ -1538,14 +1543,13 @@ fil_space_create(
 			ib_logf(IB_LOG_LEVEL_WARN,
 				"Freeing existing tablespace '%s' entry "
 				"from the cache with id %lu",
 				name, (ulong) id);
 
-			ibool	success = fil_space_free(space->id, FALSE);
+			bool	success = fil_space_free_and_mutex_exit(
+				space->id, false);
 			ut_a(success);
-
-			mutex_exit(&fil_system->mutex);
 		}
 
 	} while (space != 0);
 
 	space = fil_space_get_by_id(id);
@@ -1696,39 +1700,34 @@ fil_assign_new_space_id(
 	mutex_exit(&fil_system->mutex);
 
 	return(success);
 }
 
-/*******************************************************************//**
-Frees a space object from the tablespace memory cache. Closes the files in
-the chain but does not delete them. There must not be any pending i/o's or
+/** Free a space object from the tablespace memory cache. Close the files in
+the chain but do not delete them. There must not be any pending i/o's or
 flushes on the files.
-@return	TRUE if success */
+The fil_system->mutex will be released.
+@param[in]	id		tablespace ID
+@param[in]	x_latched	whether the caller holds exclusive space->latch
+@return whether the tablespace existed */
 static
-ibool
-fil_space_free(
-/*===========*/
-					/* out: TRUE if success */
-	ulint		id,		/* in: space id */
-	ibool		x_latched)	/* in: TRUE if caller has space->latch
-					in X mode */
+bool
+fil_space_free_and_mutex_exit(ulint id, bool x_latched)
 {
 	fil_space_t*	space;
 	fil_space_t*	fnamespace;
 
 	ut_ad(mutex_own(&fil_system->mutex));
 
 	space = fil_space_get_by_id(id);
 
 	if (!space) {
-		ut_print_timestamp(stderr);
-		fprintf(stderr,
-			"  InnoDB: Error: trying to remove tablespace %lu"
-			" from the cache but\n"
-			"InnoDB: it is not there.\n", (ulong) id);
-
-		return(FALSE);
+		ib_logf(IB_LOG_LEVEL_ERROR,
+			"trying to remove non-existing tablespace " ULINTPF,
+			id);
+		mutex_exit(&fil_system->mutex);
+		return(false);
 	}
 
 	HASH_DELETE(fil_space_t, hash, fil_system->spaces, id, space);
 
 	fnamespace = fil_space_get_by_name(space->name);
@@ -1756,15 +1755,29 @@ fil_space_free(
 	UT_LIST_REMOVE(space_list, fil_system->space_list, space);
 
 	ut_a(space->magic_n == FIL_SPACE_MAGIC_N);
 	ut_a(0 == space->n_pending_flushes);
 
+	for (fil_node_t* node = UT_LIST_GET_FIRST(space->chain);
+	     node != NULL;
+	     node = UT_LIST_GET_NEXT(chain, node)) {
+		fil_node_free_part1(space, node);
+	}
+
+	mutex_exit(&fil_system->mutex);
+
+	/* Wait for fil_space_release_for_io(); after
+	fil_space_detach(), the tablespace cannot be found, so
+	fil_space_acquire_for_io() would return NULL */
+	while (space->n_pending_ios) {
+		os_thread_sleep(100);
+	}
+
 	for (fil_node_t* fil_node = UT_LIST_GET_FIRST(space->chain);
 	     fil_node != NULL;
 	     fil_node = UT_LIST_GET_FIRST(space->chain)) {
-
-		fil_node_free(fil_node, fil_system, space);
+		fil_node_free_part2(space, fil_node);
 	}
 
 	ut_a(0 == UT_LIST_GET_LEN(space->chain));
 
 	if (x_latched) {
@@ -2160,11 +2173,15 @@ fil_close_all_files(void)
 			}
 		}
 
 		space = UT_LIST_GET_NEXT(space_list, space);
 
-		fil_space_free(prev_space->id, FALSE);
+		/* This is executed during shutdown. No other thread
+		can create or remove tablespaces while we are not
+		holding fil_system->mutex. */
+		fil_space_free_and_mutex_exit(prev_space->id, false);
+		mutex_enter(&fil_system->mutex);
 	}
 
 	mutex_exit(&fil_system->mutex);
 }
 
@@ -2208,11 +2225,15 @@ fil_close_log_files(
 		}
 
 		space = UT_LIST_GET_NEXT(space_list, space);
 
 		if (free) {
-			fil_space_free(prev_space->id, FALSE);
+			/* This is executed during startup. No other thread
+			can create or remove tablespaces while we are not
+			holding fil_system->mutex. */
+			fil_space_free_and_mutex_exit(prev_space->id, false);
+			mutex_enter(&fil_system->mutex);
 		}
 	}
 
 	mutex_exit(&fil_system->mutex);
 }
@@ -3018,19 +3039,17 @@ fil_close_tablespace(
 	mutex_enter(&fil_system->mutex);
 
 	/* If the free is successful, the X lock will be released before
 	the space memory data structure is freed. */
 
-	if (!fil_space_free(id, TRUE)) {
+	if (!fil_space_free_and_mutex_exit(id, TRUE)) {
 		rw_lock_x_unlock(&space->latch);
 		err = DB_TABLESPACE_NOT_FOUND;
 	} else {
 		err = DB_SUCCESS;
 	}
 
-	mutex_exit(&fil_system->mutex);
-
 	/* If it is a delete then also delete any generated files, otherwise
 	when we drop the database the remove directory will fail. */
 
 	char*	cfg_name = fil_make_cfg_name(path);
 
@@ -3135,16 +3154,14 @@ fil_delete_tablespace(
 		ut_a(UT_LIST_GET_LEN(space->chain) == 1);
 		fil_node_t* node = UT_LIST_GET_FIRST(space->chain);
 		ut_a(node->n_pending == 0);
 	}
 
-	if (!fil_space_free(id, TRUE)) {
+	if (!fil_space_free_and_mutex_exit(id, true)) {
 		err = DB_TABLESPACE_NOT_FOUND;
 	}
 
-	mutex_exit(&fil_system->mutex);
-
 	if (err != DB_SUCCESS) {
 		rw_lock_x_unlock(&space->latch);
 	} else if (!os_file_delete(innodb_file_data_key, path)
 		   && !os_file_delete_if_exists(innodb_file_data_key, path)) {
 
@@ -6187,11 +6204,11 @@ fil_space_get_node(
 @return	block size */
 UNIV_INTERN
 ulint
 fil_space_get_block_size(const fil_space_t* space, unsigned offset)
 {
-	ut_ad(space->n_pending_ops > 0);
+	ut_ad(space->n_pending_ios > 0);
 
 	ulint block_size = 512;
 
 	for (fil_node_t* node = UT_LIST_GET_FIRST(space->chain);
 	     node != NULL;
@@ -6624,11 +6641,11 @@ fil_flush(
 @param[in,out]	space	tablespace to flush */
 UNIV_INTERN
 void
 fil_flush(fil_space_t* space)
 {
-	ut_ad(space->n_pending_ops > 0);
+	ut_ad(space->n_pending_ios > 0);
 
 	if (!space->is_stopping()) {
 		mutex_enter(&fil_system->mutex);
 		if (!space->is_stopping()) {
 			fil_flush_low(space);
@@ -7553,17 +7570,15 @@ fil_space_set_corrupt(
 /** Acquire a tablespace when it could be dropped concurrently.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
 @param[in]	id	tablespace ID
 @param[in]	silent	whether to silently ignore missing tablespaces
-@param[in]	for_io	whether to look up the tablespace while performing I/O
-			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted or truncated */
 UNIV_INTERN
 fil_space_t*
-fil_space_acquire_low(ulint id, bool silent, bool for_io)
+fil_space_acquire_low(ulint id, bool silent)
 {
 	fil_space_t*	space;
 
 	mutex_enter(&fil_system->mutex);
 
@@ -7572,23 +7587,59 @@ fil_space_acquire_low(ulint id, bool silent, bool for_io)
 	if (space == NULL) {
 		if (!silent) {
 			ib_logf(IB_LOG_LEVEL_WARN, "Trying to access missing"
 				" tablespace " ULINTPF ".", id);
 		}
-	} else if (!for_io && space->is_stopping()) {
+	} else if (space->is_stopping()) {
 		space = NULL;
 	} else {
 		space->n_pending_ops++;
 	}
 
 	mutex_exit(&fil_system->mutex);
 
 	return(space);
 }
 
+/** Acquire a tablespace for reading or writing a block,
+when it could be dropped concurrently.
+@param[in]	id	tablespace ID
+@return	the tablespace
+@retval	NULL if missing */
+UNIV_INTERN
+fil_space_t*
+fil_space_acquire_for_io(ulint id)
+{
+	mutex_enter(&fil_system->mutex);
+
+	fil_space_t* space = fil_space_get_by_id(id);
+
+	if (space) {
+		space->n_pending_ios++;
+	}
+
+	mutex_exit(&fil_system->mutex);
+
+	return(space);
+}
+
+/** Release a tablespace acquired with fil_space_acquire_for_io().
+@param[in,out]	space	tablespace to release  */
+UNIV_INTERN
+void
+fil_space_release_for_io(fil_space_t* space)
+{
+	mutex_enter(&fil_system->mutex);
+	ut_ad(space->magic_n == FIL_SPACE_MAGIC_N);
+	ut_ad(space->n_pending_ios > 0);
+	space->n_pending_ios--;
+	mutex_exit(&fil_system->mutex);
+}
+
 /** Release a tablespace acquired with fil_space_acquire().
 @param[in,out]	space	tablespace to release  */
+UNIV_INTERN
 void
 fil_space_release(fil_space_t* space)
 {
 	mutex_enter(&fil_system->mutex);
 	ut_ad(space->magic_n == FIL_SPACE_MAGIC_N);
@@ -7603,10 +7654,11 @@ fil_space_acquire() and fil_space_release() are invoked here which
 blocks a concurrent operation from dropping the tablespace.
 @param[in]	prev_space	Pointer to the previous fil_space_t.
 If NULL, use the first fil_space_t on fil_system->space_list.
 @return pointer to the next fil_space_t.
 @retval NULL if this was the last*/
+UNIV_INTERN
 fil_space_t*
 fil_space_next(fil_space_t* prev_space)
 {
 	fil_space_t*		space=prev_space;
 
@@ -7670,10 +7722,11 @@ fil_space_acquire() and fil_space_release() are invoked here which
 blocks a concurrent operation from dropping the tablespace.
 @param[in]	prev_space	Pointer to the previous fil_space_t.
 If NULL, use the first fil_space_t on fil_system->space_list.
 @return pointer to the next fil_space_t.
 @retval NULL if this was the last*/
+UNIV_INTERN
 fil_space_t*
 fil_space_keyrotate_next(
 	fil_space_t*	prev_space)
 {
 	fil_space_t* space = prev_space;
```

### `storage/xtradb/include/buf0buf.h`

```diff
--- from commit b82c602db588 ---
diff --git a/storage/xtradb/include/buf0buf.h b/storage/xtradb/include/buf0buf.h
index 08c3a765a8b..9b4276efaa8 100644
--- a/storage/xtradb/include/buf0buf.h
+++ b/storage/xtradb/include/buf0buf.h
@@ -1,9 +1,9 @@
 /*****************************************************************************
 
 Copyright (c) 1995, 2016, Oracle and/or its affiliates. All Rights Reserved.
-Copyright (c) 2013, 2017, MariaDB Corporation. All Rights Reserved.
+Copyright (c) 2013, 2017, MariaDB Corporation.
 
 This program is free software; you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation; version 2 of the License.
 
@@ -673,33 +673,31 @@ buf_page_is_checksum_valid_none(
 	const byte*	read_buf,
 	ulint		checksum_field1,
 	ulint		checksum_field2)
 	MY_ATTRIBUTE((warn_unused_result));
 
-/********************************************************************//**
-Checks if a page is corrupt.
+/** Check if a page is corrupt.
 @param[in]	check_lsn		true if LSN should be checked
 @param[in]	read_buf		Page to be checked
 @param[in]	zip_size		compressed size or 0
 @param[in]	space			Pointer to tablespace
 @return	true if corrupted, false if not */
+UNIV_INTERN
 bool
 buf_page_is_corrupted(
 	bool			check_lsn,
 	const byte*		read_buf,
 	ulint			zip_size,
 	const fil_space_t* 	space)
 	MY_ATTRIBUTE((warn_unused_result));
-/********************************************************************//**
-Checks if a page is all zeroes.
-@return	TRUE if the page is all zeroes */
+/** Check if a page is all zeroes.
+@param[in]	read_buf	database page
+@param[in]	zip_size	ROW_FORMAT=COMPRESSED page size, or 0
+@return	whether the page is all zeroes */
+UNIV_INTERN
 bool
-buf_page_is_zeroes(
-/*===============*/
-	const byte*	read_buf,	/*!< in: a database page */
-	const ulint	zip_size);	/*!< in: size of compressed page;
-					0 for uncompressed pages */
+buf_page_is_zeroes(const byte* read_buf, ulint zip_size);
 #ifndef UNIV_HOTBACKUP
 /**********************************************************************//**
 Gets the space id, page offset, and byte offset within page of a
 pointer pointing to a buffer frame containing a file page. */
 UNIV_INLINE
@@ -1257,22 +1255,22 @@ buf_page_init_for_read(
 	ibool		unzip,	/*!< in: TRUE=request uncompressed page */
 	ib_int64_t	tablespace_version,/*!< in: prevents reading from a wrong
 				version of the tablespace in case we have done
 				DISCARD + IMPORT */
 	ulint		offset);/*!< in: page number */
-/********************************************************************//**
-Completes an asynchronous read or write request of a file page to or from
-the buffer pool.
-@param[in,out]	bpage		pointer to the block in question
-@return DB_SUCCESS if page has been read and is not corrupted,
-DB_PAGE_CORRUPTED if page based on checksum check is corrupted,
-DB_DECRYPTION_FAILED if page post encryption checksum matches but
-after decryption normal page checksum does not match.*/
+/** Complete a read or write request of a file page to or from the buffer pool.
+@param[in,out]		bpage		Page to complete
+@return whether the operation succeeded
+@retval	DB_SUCCESS		always when writing, or if a read page was OK
+@retval	DB_PAGE_CORRUPTED	if the checksum fails on a page read
+@retval	DB_DECRYPTION_FAILED	if page post encryption checksum matches but
+				after decryption normal page checksum does
+				not match */
 UNIV_INTERN
 dberr_t
-buf_page_io_complete(
-	buf_page_t*	bpage);
+buf_page_io_complete(buf_page_t* bpage)
+	MY_ATTRIBUTE((nonnull));
 /********************************************************************//**
 Calculates a folded value of a file page address to use in the page hash
 table.
 @return	the folded value */
 UNIV_INLINE
```

### `storage/xtradb/include/fil0fil.h`

```diff
--- from commit b82c602db588 ---
diff --git a/storage/xtradb/include/fil0fil.h b/storage/xtradb/include/fil0fil.h
index 37269db1960..2f03d2aa0f5 100644
--- a/storage/xtradb/include/fil0fil.h
+++ b/storage/xtradb/include/fil0fil.h
@@ -312,17 +312,25 @@ struct fil_space_t {
 				/*!< number of reserved free extents for
 				ongoing operations like B-tree page split */
 	ulint		n_pending_flushes; /*!< this is positive when flushing
 				the tablespace to disk; dropping of the
 				tablespace is forbidden if this is positive */
-	ulint		n_pending_ops;/*!< this is positive when we
-				have pending operations against this
-				tablespace. The pending operations can
-				be ibuf merges or lock validation code
-				trying to read a block.
-				Dropping of the tablespace is forbidden
-				if this is positive */
+	/** Number of pending buffer pool operations accessing the tablespace
+	without holding a table lock or dict_operation_lock S-latch
+	that would prevent the table (and tablespace) from being
+	dropped. An example is change buffer merge.
+	The tablespace cannot be dropped while this is nonzero,
+	or while fil_node_t::n_pending is nonzero.
+	Protected by fil_system->mutex. */
+	ulint		n_pending_ops;
+	/** Number of pending block read or write operations
+	(when a write is imminent or a read has recently completed).
+	The tablespace object cannot be freed while this is nonzero,
+	but it can be detached from fil_system.
+	Note that fil_node_t::n_pending tracks actual pending I/O requests.
+	Protected by fil_system->mutex. */
+	ulint		n_pending_ios;
 	hash_node_t	hash;	/*!< hash chain node */
 	hash_node_t	name_hash;/*!< hash chain the name_hash table */
 #ifndef UNIV_HOTBACKUP
 	prio_rw_lock_t	latch;	/*!< latch protecting the file space storage
 				allocation */
@@ -650,17 +658,15 @@ fil_write_flushed_lsn_to_data_files(
 /** Acquire a tablespace when it could be dropped concurrently.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
 @param[in]	id	tablespace ID
 @param[in]	silent	whether to silently ignore missing tablespaces
-@param[in]	for_io	whether to look up the tablespace while performing I/O
-			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted or truncated */
 UNIV_INTERN
 fil_space_t*
-fil_space_acquire_low(ulint id, bool silent, bool for_io = false)
+fil_space_acquire_low(ulint id, bool silent)
 	MY_ATTRIBUTE((warn_unused_result));
 
 /** Acquire a tablespace when it could be dropped concurrently.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
@@ -669,43 +675,58 @@ for concurrency control.
 			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted or truncated */
 inline
 fil_space_t*
-fil_space_acquire(ulint id, bool for_io = false)
+fil_space_acquire(ulint id)
 {
-	return (fil_space_acquire_low(id, false, for_io));
+	return(fil_space_acquire_low(id, false));
 }
 
 /** Acquire a tablespace that may not exist.
 Used by background threads that do not necessarily hold proper locks
 for concurrency control.
 @param[in]	id	tablespace ID
-@param[in]	for_io	whether to look up the tablespace while performing I/O
-			(possibly executing TRUNCATE)
 @return	the tablespace
 @retval	NULL if missing or being deleted */
 inline
 fil_space_t*
-fil_space_acquire_silent(ulint id, bool for_io = false)
+fil_space_acquire_silent(ulint id)
 {
-	return (fil_space_acquire_low(id, true, for_io));
+	return(fil_space_acquire_low(id, true));
 }
 
 /** Release a tablespace acquired with fil_space_acquire().
 @param[in,out]	space	tablespace to release  */
+UNIV_INTERN
 void
 fil_space_release(fil_space_t* space);
 
+/** Acquire a tablespace for reading or writing a block,
+when it could be dropped concurrently.
+@param[in]	id	tablespace ID
+@return	the tablespace
+@retval	NULL if missing */
+UNIV_INTERN
+fil_space_t*
+fil_space_acquire_for_io(ulint id);
+
+/** Release a tablespace acquired with fil_space_acquire_for_io().
+@param[in,out]	space	tablespace to release  */
+UNIV_INTERN
+void
+fil_space_release_for_io(fil_space_t* space);
+
 /** Return the next fil_space_t.
 Once started, the caller must keep calling this until it returns NULL.
 fil_space_acquire() and fil_space_release() are invoked here which
 blocks a concurrent operation from dropping the tablespace.
 @param[in,out]	prev_space	Pointer to the previous fil_space_t.
 If NULL, use the first fil_space_t on fil_system->space_list.
 @return pointer to the next fil_space_t.
 @retval NULL if this was the last  */
+UNIV_INTERN
 fil_space_t*
 fil_space_next(
 	fil_space_t*	prev_space)
 	MY_ATTRIBUTE((warn_unused_result));
 
@@ -715,10 +736,11 @@ fil_space_acquire() and fil_space_release() are invoked here which
 blocks a concurrent operation from dropping the tablespace.
 @param[in,out]	prev_space	Pointer to the previous fil_space_t.
 If NULL, use the first fil_space_t on fil_system->space_list.
 @return pointer to the next fil_space_t.
 @retval NULL if this was the last*/
+UNIV_INTERN
 fil_space_t*
 fil_space_keyrotate_next(
 	fil_space_t*	prev_space)
 	MY_ATTRIBUTE((warn_unused_result));
 
@@ -731,16 +753,13 @@ public:
 	FilSpace() : m_space(NULL) {}
 
 	/** Constructor: Look up the tablespace and increment the
 	reference count if found.
 	@param[in]	space_id	tablespace ID
-	@param[in]	silent		whether not print any errors
-	@param[in]	for_io		whether to look up the tablespace
-					while performing I/O
-					(possibly executing TRUNCATE) */
-	explicit FilSpace(ulint space_id, bool silent = false, bool for_io = false)
-		: m_space(fil_space_acquire_low(space_id, silent, for_io)) {}
+	@param[in]	silent		whether not to print any errors */
+	explicit FilSpace(ulint space_id, bool silent = false)
+		: m_space(fil_space_acquire_low(space_id, silent)) {}
 
 	/** Assignment operator: This assumes that fil_space_acquire()
 	has already been done for the fil_space_t. The caller must
 	assign NULL if it calls fil_space_release().
 	@param[in]	space	tablespace to assign */
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
