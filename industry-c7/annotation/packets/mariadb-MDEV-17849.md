# Annotation packet: MDEV-17849  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Undo tablespace truncation recovery fails to shrink file

A test occasionally fails like this:
{noformat:title=10.4 2dd6cd5f15f9996f38b4fcba890a237d69041d5a}
innodb.undo_truncate_recover '2,4k,innodb' w28 [ fail ]
        Test ended at 2018-11-27 09:27:05

CURRENT_TEST: innodb.undo_truncate_recover
…
2018-11-27  9:27:03 0 [Note] InnoDB: Opened 2 undo tablespaces
2018-11-27  9:27:03 0 [Note] InnoDB: Starting crash recovery from checkpoint LSN=22827480
2018-11-27  9:27:04 0 [Note] InnoDB: Starting a batch to recover 3004 pages from redo log.
mysqld: /mariadb/10.4/storage/innobase/log/log0recv.cc:258: void recv_addr_trim(ulint, unsigned int, lsn_t): Assertion `file->is_open()' failed.
{noformat}
In a release build, the impact of this would be calling {{ftruncate()}} or {{SetFilePointerEx()}} on {{OS_FILE_CLOSED}}, and thus failing to shrink the file:
{code:c++}
		fil_node_t* file = UT_LIST_GET_FIRST(space->chain);
		ut_ad(file->is_open());
		os_file_truncate(file->name, file->handle,
				 os_offset_t(pages) << srv_page_size_shift,
				 true);
{code}
There is no guarantee that the undo tablespace file would be open at this point. {{srv_undo_tablespace_open()}} is opening and immediately closing the file, without assigning {{fil_node_t::handle}}.
```

## Fix commit message(s)

`e82e216e3747`

```
MDEV-17849 Undo tablespace truncation recovery fails to shrink file

fil_space_t::add(): Replaces fil_node_create(), fil_node_create_low().
Let the caller pass fil_node_t::handle, to avoid having to close and
re-open files.

fil_node_t::read_page0(): Refactored from fil_node_open_file().
Read the first page of a data file.

fil_node_open_file(): Open the file only once.

srv_undo_tablespace_open(): Set the file handle for the opened
undo tablespace. This should ensure that ut_ad(file->is_open())
no longer fails in recv_add_trim().

xtrabackup_backup_func(): Remove some dead code.

xb_fil_cur_open(): Open files only if needed. Undo tablespaces
should already have been opened.
```

## Files the fix changed

Snapshot holds 3,685 non-test source files. The fix changed 7 file(s); 7 of them are non-test source files (listed below as gold).

- `extra/mariabackup/fil_cur.cc`
- `extra/mariabackup/xtrabackup.cc`
- `storage/innobase/fil/fil0fil.cc`
- `storage/innobase/fsp/fsp0space.cc`
- `storage/innobase/fsp/fsp0sysspace.cc`
- `storage/innobase/include/fil0fil.h`
- `storage/innobase/srv/srv0start.cc`

## The fix diff

### `extra/mariabackup/fil_cur.cc`

```diff
diff --git a/extra/mariabackup/fil_cur.cc b/extra/mariabackup/fil_cur.cc
index 7b7cfb3c948..219ec8845d4 100644
--- a/extra/mariabackup/fil_cur.cc
+++ b/extra/mariabackup/fil_cur.cc
@@ -157,12 +157,15 @@ xb_fil_cur_open(
 		sizeof(cursor->rel_path));
 
 	/* In the backup mode we should already have a tablespace handle created
 	by fil_ibd_load() unless it is a system
 	tablespace. Otherwise we open the file here. */
-	if (cursor->is_system() || srv_operation == SRV_OPERATION_RESTORE_DELTA
-	    || xb_close_files) {
+	if (!node->is_open()) {
+		ut_ad(cursor->is_system()
+		      || srv_operation == SRV_OPERATION_RESTORE_DELTA
+		      || xb_close_files);
+
 		node->handle = os_file_create_simple_no_error_handling(
 			0, node->name,
 			OS_FILE_OPEN,
 			OS_FILE_READ_ALLOW_DELETE, true, &success);
 		if (!success) {
```

### `extra/mariabackup/xtrabackup.cc`

```diff
diff --git a/extra/mariabackup/xtrabackup.cc b/extra/mariabackup/xtrabackup.cc
index e627826b8c4..0f29da9e78e 100644
--- a/extra/mariabackup/xtrabackup.cc
+++ b/extra/mariabackup/xtrabackup.cc
@@ -3099,15 +3099,12 @@ xb_load_single_table_tablespace(
 			name, file->space_id(), file->flags(),
 			FIL_TYPE_TABLESPACE, NULL/* TODO: crypt_data */);
 
 		ut_a(space != NULL);
 
-		if (!fil_node_create(file->filepath(), ulint(n_pages), space,
-				     false, false)) {
-			ut_error;
-		}
-
+		space->add(file->filepath(), OS_FILE_CLOSED, ulint(n_pages),
+			   false, false);
 		/* by opening the tablespace we forcing node and space objects
 		in the cache to be populated with fields from space header */
 		fil_space_open(space->name);
 
 		if (srv_operation == SRV_OPERATION_RESTORE_DELTA
@@ -3779,26 +3776,21 @@ xb_filters_free()
 		xb_filter_hash_free(databases_exclude_hash);
 	}
 }
 
 /*********************************************************************//**
-Creates or opens the log files and closes them.
-@return	DB_SUCCESS or error code */
+Create log file metadata. */
 static
-ulint
+void
 open_or_create_log_file(
 /*====================*/
 	fil_space_t* space,
-	ibool*	log_file_created,	/*!< out: TRUE if new log file
-					created */
 	ulint	i)			/*!< in: log file number in group */
 {
 	char	name[10000];
 	ulint	dirnamelen;
 
-	*log_file_created = FALSE;
-
 	os_normalize_path(srv_log_group_home_dir);
 
 	dirnamelen = strlen(srv_log_group_home_dir);
 	ut_a(dirnamelen < (sizeof name) - 10 - sizeof "ib_logfile");
 	memcpy(name, srv_log_group_home_dir, dirnamelen);
@@ -3806,18 +3798,17 @@ open_or_create_log_file(
 	/* Add a path separator if needed. */
 	if (dirnamelen && name[dirnamelen - 1] != OS_PATH_SEPARATOR) {
 		name[dirnamelen++] = OS_PATH_SEPARATOR;
 	}
 
-	sprintf(name + dirnamelen, "%s%lu", "ib_logfile", (ulong) i);
+	sprintf(name + dirnamelen, "%s%zu", "ib_logfile", i);
 
 	ut_a(fil_validate());
 
-	ut_a(fil_node_create(name, ulint(srv_log_file_size >> srv_page_size_shift),
-			     space, false, false));
-
-	return(DB_SUCCESS);
+	space->add(name, OS_FILE_CLOSED,
+		   ulint(srv_log_file_size >> srv_page_size_shift),
+		   false, false);
 }
 
 /*********************************************************************//**
 Normalizes init parameter values to use units we use inside InnoDB.
 @return	DB_SUCCESS or error code */
@@ -4122,17 +4113,10 @@ fail:
 	os_event_set(srv_allow_writes_event);
 #endif
 
 	xb_filters_init();
 
-	{
-	ibool	log_file_created;
-	ibool	log_created	= FALSE;
-	ibool	log_opened	= FALSE;
-	ulint	err;
-	ulint	i;
-
 	xb_fil_io_init();
 	srv_n_file_io_threads = srv_n_read_io_threads;
 
 	os_aio_init(srv_n_read_io_threads, srv_n_write_io_threads,
 		    SRV_MAX_N_PENDING_SYNC_IOS);
@@ -4143,40 +4127,12 @@ fail:
 		"innodb_redo_log", SRV_LOG_SPACE_FIRST_ID, 0,
 		FIL_TYPE_LOG, NULL);
 
 	lock_sys_create(srv_lock_table_size);
 
-	for (i = 0; i < srv_n_log_files; i++) {
-		err = open_or_create_log_file(space, &log_file_created, i);
-		if (err != DB_SUCCESS) {
-			goto fail;
-		}
-
-		if (log_file_created) {
-			log_created = TRUE;
-		} else {
-			log_opened = TRUE;
-		}
-		if ((log_opened && log_created)) {
-			msg(
-	"mariabackup: Error: all log files must be created at the same time.\n"
-	"mariabackup: All log files must be created also in database creation.\n"
-	"mariabackup: If you want bigger or smaller log files, shut down the\n"
-	"mariabackup: database and make sure there were no errors in shutdown.\n"
-	"mariabackup: Then delete the existing log files. Edit the .cnf file\n"
-	"mariabackup: and start the database again.\n");
-
-			goto fail;
-		}
-	}
-
-	/* log_file_created must not be TRUE, if online */
-	if (log_file_created) {
-		msg("mariabackup: Something wrong with source files...\n");
-		goto fail;
-	}
-
+	for (ulint i = 0; i < srv_n_log_files; i++) {
+		open_or_create_log_file(space, i);
 	}
 
 	/* create extra LSN dir if it does not exist. */
 	if (xtrabackup_extra_lsndir
 		&&!my_stat(xtrabackup_extra_lsndir,&stat_info,MYF(0))
```

### `storage/innobase/fil/fil0fil.cc`

```diff
diff --git a/storage/innobase/fil/fil0fil.cc b/storage/innobase/fil/fil0fil.cc
index 6368d4b4751..7744c9079f2 100644
--- a/storage/innobase/fil/fil0fil.cc
+++ b/storage/innobase/fil/fil0fil.cc
@@ -463,40 +463,29 @@ fil_space_is_flushed(
 }
 
 
 /** Append a file to the chain of files of a space.
 @param[in]	name		file name of a file that is not open
-@param[in]	size		file size in entire database blocks
-@param[in,out]	space		tablespace from fil_space_create()
-@param[in]	is_raw		whether this is a raw device or partition
-@param[in]	atomic_write	true if the file could use atomic write
+@param[in]	handle		file handle, or OS_FILE_CLOSED
+@param[in]	size		file size in entire database pages
+@param[in]	is_raw		whether this is a raw device
+@param[in]	atomic_write	true if atomic write could be enabled
 @param[in]	max_pages	maximum number of pages in file,
-ULINT_MAX means the file size is unlimited.
-@return pointer to the file name
-@retval NULL if error */
-static
-fil_node_t*
-fil_node_create_low(
-	const char*	name,
-	ulint		size,
-	fil_space_t*	space,
-	bool		is_raw,
-	bool		atomic_write,
-	ulint		max_pages = ULINT_MAX)
+or ULINT_MAX for unlimited
+@return file object */
+fil_node_t* fil_space_t::add(const char* name, pfs_os_file_t handle,
+			     ulint size, bool is_raw, bool atomic_write,
+			     ulint max_pages)
 {
 	fil_node_t*	node;
 
 	ut_ad(name != NULL);
 	ut_ad(fil_system != NULL);
 
-	if (space == NULL) {
-		return(NULL);
-	}
-
 	node = reinterpret_cast<fil_node_t*>(ut_zalloc_nokey(sizeof(*node)));
 
-	node->handle = OS_FILE_CLOSED;
+	node->handle = handle;
 
 	node->name = mem_strdup(name);
 
 	ut_a(!is_raw || srv_start_raw_disk_in_use);
 
@@ -509,60 +498,120 @@ fil_node_create_low(
 	node->magic_n = FIL_NODE_MAGIC_N;
 
 	node->init_size = size;
 	node->max_size = max_pages;
 
-	mutex_enter(&fil_system->mutex);
-
-	space->size += size;
-
-	node->space = space;
+	node->space = this;
 
 	node->atomic_write = atomic_write;
 
-	UT_LIST_ADD_LAST(space->chain, node);
+	mutex_enter(&fil_system->mutex);
+	this->size += size;
+	UT_LIST_ADD_LAST(chain, node);
+	if (node->is_open()) {
+		fil_system->n_open++;
+	}
 	mutex_exit(&fil_system->mutex);
 
-	return(node);
+	return node;
 }
 
-/** Appends a new file to the chain of files of a space. File must be closed.
-@param[in]	name		file name (file must be closed)
-@param[in]	size		file size in database blocks, rounded downwards to
-				an integer
-@param[in,out]	space		space where to append
-@param[in]	is_raw		true if a raw device or a raw disk partition
-@param[in]	atomic_write	true if the file could use atomic write
-@param[in]	max_pages	maximum number of pages in file,
-ULINT_MAX means the file size is unlimited.
-@return pointer to the file name
-@retval NULL if error */
-char*
-fil_node_create(
-	const char*	name,
-	ulint		size,
-	fil_space_t*	space,
-	bool		is_raw,
-	bool		atomic_write,
-	ulint		max_pages)
+/** Read the first page of a data file.
+@param[in]	first	whether this is the very first read
+@return	whether the page was found valid */
+bool fil_node_t::read_page0(bool first)
 {
-	fil_node_t*	node;
+	ut_ad(mutex_own(&fil_system->mutex));
+	ut_a(space->purpose != FIL_TYPE_LOG);
+	const page_size_t page_size(space->flags);
+	const ulint psize = page_size.physical();
+
+	os_offset_t size_bytes = os_file_get_size(handle);
+	ut_a(size_bytes != (os_offset_t) -1);
+	const ulint min_size = FIL_IBD_FILE_INITIAL_SIZE * psize;
+
+	if (size_bytes < min_size) {
+		ib::error() << "The size of the file " << name
+			    << " is only " << size_bytes
+			    << " bytes, should be at least " << min_size;
+		return false;
+	}
 
-	node = fil_node_create_low(
-		name, size, space, is_raw, atomic_write, max_pages);
+	byte* buf2 = static_cast<byte*>(ut_malloc_nokey(2 * psize));
 
-	return(node == NULL ? NULL : node->name);
+	/* Align the memory for file i/o if we might have O_DIRECT set */
+	byte* page = static_cast<byte*>(ut_align(buf2, psize));
+	IORequest request(IORequest::READ);
+	if (!os_file_read(request, handle, page, 0, psize)) {
+		ib::error() << "Unable to read first page of file " << name;
+		ut_free(buf2);
+		return false;
+	}
+	srv_stats.page0_read.add(1);
+	const ulint space_id = fsp_header_get_space_id(page);
+	ulint flags = fsp_header_get_flags(page);
+	const ulint size = fsp_header_get_field(page, FSP_SIZE);
+	const ulint free_limit = fsp_header_get_field(page, FSP_FREE_LIMIT);
+	const ulint free_len = flst_get_len(FSP_HEADER_OFFSET + FSP_FREE
+					    + page);
+	/* Try to read crypt_data from page 0 if it is not yet read. */
+	if (!space->crypt_data) {
+		space->crypt_data = fil_space_read_crypt_data(page_size, page);
+	}
+	ut_free(buf2);
+
+	if (!fsp_flags_is_valid(flags, space->id)) {
+		ulint cflags = fsp_flags_convert_from_101(flags);
+		if (cflags == ULINT_UNDEFINED
+		    || (cflags ^ space->flags) & ~FSP_FLAGS_MEM_MASK) {
+			ib::error()
+				<< "Expected tablespace flags "
+				<< ib::hex(space->flags)
+				<< " but found " << ib::hex(flags)
+				<< " in the file " << name;
+			return false;
+		}
+
+		flags = cflags;
+	}
+
+	if (UNIV_UNLIKELY(space_id != space->id)) {
+		ib::error() << "Expected tablespace id " << space->id
+			<< " but found " << space_id
+			<< " in the file " << name;
+		return false;
+	}
+
+	ut_ad(space->free_limit == 0 || space->free_limit == free_limit);
+	ut_ad(space->free_len == 0 || space->free_len == free_len);
+	space->size_in_header = size;
+	space->free_limit = free_limit;
+	space->free_len = free_len;
+
+	if (first) {
+		/* Truncate the size to a multiple of extent size. */
+		ulint	mask = psize * FSP_EXTENT_SIZE - 1;
+
+		if (size_bytes <= mask) {
+			/* .ibd files start smaller than an
+			extent size. Do not truncate valid data. */
+		} else {
+			size_bytes &= ~os_offset_t(mask);
+		}
+
+		this->size = ulint(size_bytes / psize);
+		space->size += this->size;
+	}
+
+	return true;
 }
 
 /** Open a file node of a tablespace.
 The caller must own the fil_system mutex.
 @param[in,out]	node	File node
 @return false if the file can't be opened, otherwise true */
-static
-bool
-fil_node_open_file(
-	fil_node_t*	node)
+static bool fil_node_open_file(fil_node_t* node)
 {
 	bool		success;
 	bool		read_only_mode;
 	fil_space_t*	space = node->space;
 
@@ -586,13 +635,16 @@ fil_node_open_file(
 		file again.  NOTE that we could not use the simple
 		file read function os_file_read() in Windows to read
 		from a file opened for async I/O! */
 
 retry:
-		node->handle = os_file_create_simple_no_error_handling(
-			innodb_data_file_key, node->name, OS_FILE_OPEN,
-			OS_FILE_READ_ONLY, read_only_mode, &success);
+		node->handle = os_file_create(
+			innodb_data_file_key, node->name,
+			node->is_raw_disk
+			? OS_FILE_OPEN_RAW | OS_FILE_ON_ERROR_NO_EXIT
+			: OS_FILE_OPEN | OS_FILE_ON_ERROR_NO_EXIT,
+			OS_FILE_AIO, OS_DATA_FILE, read_only_mode, &success);
 
 		if (!success) {
 			/* The following call prints an error message */
 			ulint err = os_file_get_last_error(true);
 			if (err == EMFILE + 100) {
@@ -604,154 +656,51 @@ retry:
 				" Have you deleted .ibd files under a"
 				" running mysqld server?";
 			return(false);
 		}
 
-		os_offset_t size_bytes = os_file_get_size(node->handle);
-		ut_a(size_bytes != (os_offset_t) -1);
-
-		ut_a(space->purpose != FIL_TYPE_LOG);
-		const page_size_t	page_size(space->flags);
-		const ulint		psize = page_size.physical();
-		const ulint		min_size = FIL_IBD_FILE_INITIAL_SIZE
-			* psize;
-
-		if (size_bytes < min_size) {
-			ib::error() << "The size of the file " << node->name
-				<< " is only " << size_bytes
-				<< " bytes, should be at least " << min_size;
+		if (!node->read_page0(first_time_open)) {
 			os_file_close(node->handle);
 			node->handle = OS_FILE_CLOSED;
-			return(false);
-		}
-
-		/* Read the first page of the tablespace */
-
-		byte* buf2 = static_cast<byte*>(ut_malloc_nokey(2 * psize));
-
-		/* Align the memory for file i/o if we might have O_DIRECT
-		set */
-		byte* page = static_cast<byte*>(ut_align(buf2, psize));
-
-		IORequest	request(IORequest::READ);
-
-		success = os_file_read(
-			request,
-			node->handle, page, 0, psize);
-		srv_stats.page0_read.add(1);
-
-		const ulint	space_id
-			= fsp_header_get_space_id(page);
-		ulint		flags		= fsp_header_get_flags(page);
-		const ulint	size		= fsp_header_get_field(
-			page, FSP_SIZE);
-		const ulint	free_limit	= fsp_header_get_field(
-			page, FSP_FREE_LIMIT);
-		const ulint	free_len	= flst_get_len(
-			FSP_HEADER_OFFSET + FSP_FREE + page);
-
-		/* Try to read crypt_data from page 0 if it is not yet
-		read. */
-		if (!space->crypt_data) {
-			space->crypt_data = fil_space_read_crypt_data(
-				page_size_t(space->flags), page);
-		}
-
-		ut_free(buf2);
-		os_file_close(node->handle);
-		node->handle = OS_FILE_CLOSED;
-
-		if (!fsp_flags_is_valid(flags, space->id)) {
-			ulint cflags = fsp_flags_convert_from_101(flags);
-			if (cflags == ULINT_UNDEFINED
-			    || (cflags ^ space->flags) & ~FSP_FLAGS_MEM_MASK) {
-				ib::error()
-					<< "Expected tablespace flags "
-					<< ib::hex(space->flags)
-					<< " but found " << ib::hex(flags)
-					<< " in the file " << node->name;
-				return(false);
-			}
-
-			flags = cflags;
-		}
-
-		if (UNIV_UNLIKELY(space_id != space->id)) {
-			ib::error()
-				<< "Expected tablespace id " << space->id
-				<< " but found " << space_id
-				<< " in the file" << node->name;
-			return(false);
+			return false;
 		}
-
-		ut_ad(space->free_limit == 0
-		      || space->free_limit == free_limit);
-		ut_ad(space->free_len == 0
-		      || space->free_len == free_len);
-		space->size_in_header = size;
-		space->free_limit = free_limit;
-		space->free_len = free_len;
-
-		if (first_time_open) {
-			/* Truncate the size to a multiple of extent size. */
-			ulint	mask = psize * FSP_EXTENT_SIZE - 1;
-
-			if (size_bytes <= mask) {
-				/* .ibd files start smaller than an
-				extent size. Do not truncate valid data. */
-			} else {
-				size_bytes &= ~os_offset_t(mask);
-			}
-
-			node->size = ulint(size_bytes / psize);
-			space->size += node->size;
-		}
-	}
-
-	/* printf("Opening file %s\n", node->name); */
-
-	/* Open the file for reading and writing, in Windows normally in the
-	unbuffered async I/O mode, though global variables may make
-	os_file_create() to fall back to the normal file I/O mode. */
-
-	if (space->purpose == FIL_TYPE_LOG) {
+	} else if (space->purpose == FIL_TYPE_LOG) {
 		node->handle = os_file_create(
 			innodb_log_file_key, node->name, OS_FILE_OPEN,
 			OS_FILE_AIO, OS_LOG_FILE, read_only_mode, &success);
-	} else if (node->is_raw_disk) {
-		node->handle = os_file_create(
-			innodb_data_file_key, node->name, OS_FILE_OPEN_RAW,
-			OS_FILE_AIO, OS_DATA_FILE, read_only_mode, &success);
 	} else {
 		node->handle = os_file_create(
-			innodb_data_file_key, node->name, OS_FILE_OPEN,
+			innodb_data_file_key, node->name,
+			node->is_raw_disk
+			? OS_FILE_OPEN_RAW | OS_FILE_ON_ERROR_NO_EXIT
+			: OS_FILE_OPEN | OS_FILE_ON_ERROR_NO_EXIT,
 			OS_FILE_AIO, OS_DATA_FILE, read_only_mode, &success);
+	}
 
-                if (first_time_open) {
-			/*
-			For the temporary tablespace and during the
-			non-redo-logged adjustments in
-			IMPORT TABLESPACE, we do not care about
-			the atomicity of writes.
-
-			Atomic writes is supported if the file can be used
-			with atomic_writes (not log file), O_DIRECT is
-			used (tested in ha_innodb.cc) and the file is
-			device and file system that supports atomic writes
-			for the given block size
-			*/
-			space->atomic_write_supported
-				= space->purpose == FIL_TYPE_TEMPORARY
-				|| space->purpose == FIL_TYPE_IMPORT
-				|| (node->atomic_write
-				    && srv_use_atomic_writes
-				    && my_test_if_atomic_write(
-					    node->handle,
-					    int(page_size_t(space->flags)
-						.physical())));
-                }
-        }
+	if (space->purpose != FIL_TYPE_LOG) {
+		/*
+		For the temporary tablespace and during the
+		non-redo-logged adjustments in
+		IMPORT TABLESPACE, we do not care about
+		the atomicity of writes.
+
+		Atomic writes is supported if the file can be used
+		with atomic_writes (not log file), O_DIRECT is
+		used (tested in ha_innodb.cc) and the file is
+		device and file system that supports atomic writes
+		for the given block size
+		*/
+		space->atomic_write_supported
+			= space->purpose == FIL_TYPE_TEMPORARY
+			|| space->purpose == FIL_TYPE_IMPORT
+			|| (node->atomic_write
+			    && srv_use_atomic_writes
+			    && my_test_if_atomic_write(
+				    node->handle,
+				    int(page_size_t(space->flags)
+					.physical())));
+	}
 
 	ut_a(success);
 	ut_a(node->is_open());
 
 	fil_system->n_open++;
@@ -1428,11 +1377,11 @@ Error messages are issued to the server log.
 @param[in]	id		tablespace identifier
 @param[in]	flags		tablespace flags
 @param[in]	purpose		tablespace purpose
 @param[in,out]	crypt_data	encryption information
 @param[in]	mode		encryption mode
-@return pointer to created tablespace, to be filled in with fil_node_create()
+@return pointer to created tablespace, to be filled in with fil_space_t::add()
 @retval NULL on failure (such as when the same tablespace exists) */
 fil_space_t*
 fil_space_create(
 	const char*		name,
 	ulint			id,
@@ -1517,11 +1466,11 @@ fil_space_create(
 	rw_lock_create(fil_space_latch_key, &space->latch, SYNC_FSP);
 
 	if (space->purpose == FIL_TYPE_TEMPORARY) {
 		ut_d(space->latch.set_temp_fsp());
 		/* SysTablespace::open_or_create() would pass
-		size!=0 to fil_node_create(), so first_time_open
+		size!=0 to fil_space_t::add(), so first_time_open
 		would not hold in fil_node_open_file(), and we
 		must assign this manually. We do not care about
 		the durability or atomicity of writes to the
 		temporary tablespace files. */
 		space->atomic_write_supported = true;
@@ -3817,35 +3766,29 @@ fil_ibd_create(
 		crypt_data = fil_space_create_crypt_data(mode, key_id);
 	}
 
 	space = fil_space_create(name, space_id, flags, FIL_TYPE_TABLESPACE,
 				 crypt_data, mode);
-
-	fil_node_t* node = NULL;
-
-	if (space) {
-		node = fil_node_create_low(path, size, space, false, true);
-	}
-
-	if (!space || !node) {
+	if (!space) {
 		if (crypt_data) {
 			free(crypt_data);
 		}
 
 		err = DB_ERROR;
 	} else {
-		mtr_t			mtr;
-		const fil_node_t*	file = UT_LIST_GET_FIRST(space->chain);
+		mtr_t mtr;
+		fil_node_t* file = space->add(path, OS_FILE_CLOSED, size,
+					      false, true);
 
 		mtr.start();
 		fil_op_write_log(
 			MLOG_FILE_CREATE2, space_id, 0, file->name,
 			NULL, space->flags & ~FSP_FLAGS_MEM_MASK, &mtr);
 		fil_name_write(space, 0, file, &mtr);
 		mtr.commit();
 
-		node->block_size = block_size;
+		file->block_size = block_size;
 		space->punch_hole = punch_hole;
 
 		err = DB_SUCCESS;
 	}
 
@@ -4070,10 +4013,11 @@ fil_ibd_open(
 			if (df_default.is_open() != df_default.is_valid()
 			    || df_dict.is_open() != df_dict.is_valid()
 			    || df_remote.is_open() != df_remote.is_valid()) {
 				return(DB_CORRUPTION);
 			}
+error:
 			return(DB_ERROR);
 		}
 
 		/* There is only one valid tablespace found and we did
 		not use srv_force_recovery during REDO.  Use this one
@@ -4178,21 +4122,21 @@ skip_validate:
 						    first_page)
 			: NULL;
 
 		fil_space_t* space = fil_space_create(
 			space_name, id, flags, purpose, crypt_data);
+		if (!space) {
+			goto error;
+		}
 
 		/* We do not measure the size of the file, that is why
 		we pass the 0 below */
 
-		if (fil_node_create_low(
-			    df_remote.is_open() ? df_remote.filepath() :
-			    df_dict.is_open() ? df_dict.filepath() :
-			    df_default.filepath(), 0, space, false,
-			    true) == NULL) {
-			err = DB_ERROR;
-		}
+		space->add(
+			df_remote.is_open() ? df_remote.filepath() :
+			df_dict.is_open() ? df_dict.filepath() :
+			df_default.filepath(), OS_FILE_CLOSED, 0, false, true);
 
 		if (err == DB_SUCCESS && validate
 		    && purpose != FIL_TYPE_IMPORT && !srv_read_only_mode) {
 			df_remote.close();
 			df_dict.close();
@@ -4537,13 +4481,11 @@ fil_ibd_load(
 
 	/* We do not use the size information we have about the file, because
 	the rounding formula for extents and pages is somewhat complex; we
 	let fil_node_open() do that task. */
 
-	if (!fil_node_create_low(file.filepath(), 0, space, false, false)) {
-		ut_error;
-	}
+	space->add(file.filepath(), OS_FILE_CLOSED, 0, false, false);
 
 	return(FIL_LOAD_OK);
 }
 
 /***********************************************************************//**
```

### `storage/innobase/fsp/fsp0space.cc`

```diff
diff --git a/storage/innobase/fsp/fsp0space.cc b/storage/innobase/fsp/fsp0space.cc
index df234f7274e..88b34be4952 100644
--- a/storage/innobase/fsp/fsp0space.cc
+++ b/storage/innobase/fsp/fsp0space.cc
@@ -121,22 +121,19 @@ Tablespace::open_or_create(bool is_temp)
 			space = fil_space_create(
 				m_name, m_space_id, FSP_FLAGS_PAGE_SSIZE(),
 				is_temp
 				? FIL_TYPE_TEMPORARY : FIL_TYPE_TABLESPACE,
 				NULL);
+			if (!space) {
+				return DB_ERROR;
+			}
 		}
 
 		ut_a(fil_validate());
 
-		/* Create the tablespace node entry for this data file. */
-		if (!fil_node_create(
-			    it->m_filepath, it->m_size, space, false,
-			    TRUE)) {
-
-		       err = DB_ERROR;
-		       break;
-		}
+		space->add(it->m_filepath, OS_FILE_CLOSED, it->m_size,
+			   false, true);
 	}
 
 	return(err);
 }
```

### `storage/innobase/fsp/fsp0sysspace.cc`

```diff
diff --git a/storage/innobase/fsp/fsp0sysspace.cc b/storage/innobase/fsp/fsp0sysspace.cc
index baf864bc1c3..b856bf3da74 100644
--- a/storage/innobase/fsp/fsp0sysspace.cc
+++ b/storage/innobase/fsp/fsp0sysspace.cc
@@ -916,29 +916,25 @@ SysTablespace::open_or_create(
 			tablespace in the tablespace manager. */
 			space = fil_space_create(
 				name(), space_id(), flags(), is_temp
 				? FIL_TYPE_TEMPORARY : FIL_TYPE_TABLESPACE,
 				NULL);
+			if (!space) {
+				return DB_ERROR;
+			}
 		}
 
 		ut_a(fil_validate());
 
 		ulint	max_size = (++node_counter == m_files.size()
 				    ? (m_last_file_size_max == 0
 				       ? ULINT_MAX
 				       : m_last_file_size_max)
 				    : it->m_size);
 
-		/* Add the datafile to the fil_system cache. */
-		if (!fil_node_create(
-			    it->m_filepath, it->m_size,
-			    space, it->m_type != SRV_NOT_RAW,
-			    TRUE, max_size)) {
-
-			err = DB_ERROR;
-			break;
-		}
+		space->add(it->m_filepath, OS_FILE_CLOSED, it->m_size,
+			   it->m_type != SRV_NOT_RAW, true, max_size);
 	}
 
 	return(err);
 }
```

### `storage/innobase/include/fil0fil.h`

```diff
diff --git a/storage/innobase/include/fil0fil.h b/storage/innobase/include/fil0fil.h
index d1bd2dc14d4..6406ff8448c 100644
--- a/storage/innobase/include/fil0fil.h
+++ b/storage/innobase/include/fil0fil.h
@@ -193,10 +193,23 @@ struct fil_space_t {
 	bool use_doublewrite() const
 	{
 		return !atomic_write_supported
 			&& srv_use_doublewrite_buf && buf_dblwr;
 	}
+
+	/** Append a file to the chain of files of a space.
+	@param[in]	name		file name of a file that is not open
+	@param[in]	handle		file handle, or OS_FILE_CLOSED
+	@param[in]	size		file size in entire database pages
+	@param[in]	is_raw		whether this is a raw device
+	@param[in]	atomic_write	true if atomic write could be enabled
+	@param[in]	max_pages	maximum number of pages in file,
+	or ULINT_MAX for unlimited
+	@return file object */
+	fil_node_t* add(const char* name, pfs_os_file_t handle,
+			ulint size, bool is_raw, bool atomic_write,
+			ulint max_pages = ULINT_MAX);
 };
 
 /** Value of fil_space_t::magic_n */
 #define	FIL_SPACE_MAGIC_N	89472
 
@@ -250,10 +263,15 @@ struct fil_node_t {
 	/** @return whether this file is open */
 	bool is_open() const
 	{
 		return(handle != OS_FILE_CLOSED);
 	}
+
+	/** Read the first page of a data file.
+	@param[in]	first	whether this is the very first read
+	@return	whether the page was found valid */
+	bool read_page0(bool first);
 };
 
 /** Value of fil_node_t::magic_n */
 #define	FIL_NODE_MAGIC_N	89389
 
@@ -545,39 +563,19 @@ NOTE: temporary tablespaces are never imported.
 @param[in]	id	tablespace identifier */
 void
 fil_space_set_imported(
 	ulint	id);
 
-/** Append a file to the chain of files of a space.
-@param[in]	name		file name of a file that is not open
-@param[in]	size		file size in entire database blocks
-@param[in,out]	space		tablespace from fil_space_create()
-@param[in]	is_raw		whether this is a raw device or partition
-@param[in]	atomic_write	true if atomic write could be enabled
-@param[in]	max_pages	maximum number of pages in file,
-ULINT_MAX means the file size is unlimited.
-@return pointer to the file name
-@retval NULL if error */
-char*
-fil_node_create(
-	const char*	name,
-	ulint		size,
-	fil_space_t*	space,
-	bool		is_raw,
-	bool		atomic_write,
-	ulint		max_pages = ULINT_MAX)
-	MY_ATTRIBUTE((warn_unused_result));
-
 /** Create a space memory object and put it to the fil_system hash table.
 Error messages are issued to the server log.
 @param[in]	name		tablespace name
 @param[in]	id		tablespace identifier
 @param[in]	flags		tablespace flags
 @param[in]	purpose		tablespace purpose
 @param[in,out]	crypt_data	encryption information
 @param[in]	mode		encryption mode
-@return pointer to created tablespace, to be filled in with fil_node_create()
+@return pointer to created tablespace, to be filled in with fil_space_t::add()
 @retval NULL on failure (such as when the same tablespace exists) */
 fil_space_t*
 fil_space_create(
 	const char*		name,
 	ulint			id,
```

### `storage/innobase/srv/srv0start.cc`

```diff
diff --git a/storage/innobase/srv/srv0start.cc b/storage/innobase/srv/srv0start.cc
index 8719d26d5f3..ae890750841 100644
--- a/storage/innobase/srv/srv0start.cc
+++ b/storage/innobase/srv/srv0start.cc
@@ -468,27 +468,20 @@ create_log_files(
 	ut_a(fil_validate());
 	ut_a(log_space != NULL);
 
 	const ulint size = ulint(srv_log_file_size >> srv_page_size_shift);
 
-	logfile0 = fil_node_create(
-		logfilename, size, log_space, false, false);
+	logfile0 = log_space->add(logfilename, OS_FILE_CLOSED, size,
+				  false, false)->name;
 	ut_a(logfile0);
 
 	for (unsigned i = 1; i < srv_n_log_files; i++) {
 
 		sprintf(logfilename + dirnamelen, "ib_logfile%u", i);
 
-		if (!fil_node_create(logfilename, size,
-				     log_space, false, false)) {
-
-			ib::error()
-				<< "Cannot create file node for log file "
-				<< logfilename;
-
-			return(DB_ERROR);
-		}
+		log_space->add(logfilename, OS_FILE_CLOSED, size,
+			       false, false);
 	}
 
 	log_init(srv_n_log_files);
 	if (!log_set_capacity(srv_log_file_size_requested)) {
 		return(DB_ERROR);
@@ -632,87 +625,72 @@ srv_undo_tablespace_create(
 		os_file_close(fh);
 	}
 
 	return(err);
 }
-/*********************************************************************//**
-Open an undo tablespace.
-@return DB_SUCCESS or error code */
-static
-dberr_t
-srv_undo_tablespace_open(
-/*=====================*/
-	const char*	name,		/*!< in: tablespace file name */
-	ulint		space_id)	/*!< in: tablespace id */
+
+/** Open an undo tablespace.
+@param[in]	name		tablespace file name
+@param[in]	space_id	tablespace ID
+@param[in]	create_new_db	whether undo tablespaces are being created
+@return whether the tablespace was opened */
+static bool srv_undo_tablespace_open(const char* name, ulint space_id,
+				     bool create_new_db)
 {
 	pfs_os_file_t	fh;
-	bool		ret;
-	dberr_t		err	= DB_ERROR;
+	bool		success;
 	char		undo_name[sizeof "innodb_undo000"];
 
 	snprintf(undo_name, sizeof(undo_name),
 		 "innodb_undo%03u", static_cast<unsigned>(space_id));
 
-	if (!srv_file_check_mode(name)) {
-		ib::error() << "UNDO tablespaces must be " <<
-			(srv_read_only_mode ? "writable" : "readable") << "!";
-
-		return(DB_ERROR);
-	}
-
 	fh = os_file_create(
-		innodb_data_file_key, name,
-		OS_FILE_OPEN_RETRY
-		| OS_FILE_ON_ERROR_NO_EXIT
-		| OS_FILE_ON_ERROR_SILENT,
-		OS_FILE_NORMAL,
-		OS_DATA_FILE,
-		srv_read_only_mode,
-		&ret);
-
-	/* If the file open was successful then load the tablespace. */
-
-	if (ret) {
-		os_offset_t	size;
-		fil_space_t*	space;
-
-		size = os_file_get_size(fh);
-		ut_a(size != (os_offset_t) -1);
+		innodb_data_file_key, name, OS_FILE_OPEN
+		| OS_FILE_ON_ERROR_NO_EXIT | OS_FILE_ON_ERROR_SILENT,
+		OS_FILE_AIO, OS_DATA_FILE, srv_read_only_mode, &success);
+	if (!success) {
+		return false;
+	}
 
-		ret = os_file_close(fh);
-		ut_a(ret);
+	os_offset_t size = os_file_get_size(fh);
+	ut_a(size != os_offset_t(-1));
 
-		/* Load the tablespace into InnoDB's internal
-		data structures. */
+	/* Load the tablespace into InnoDB's internal data structures. */
 
-		/* We set the biggest space id to the undo tablespace
-		because InnoDB hasn't opened any other tablespace apart
-		from the system tablespace. */
+	/* We set the biggest space id to the undo tablespace
+	because InnoDB hasn't opened any other tablespace apart
+	from the system tablespace. */
 
-		fil_set_max_space_id_if_bigger(space_id);
+	fil_set_max_space_id_if_bigger(space_id);
 
-		space = fil_space_create(
-			undo_name, space_id, FSP_FLAGS_PAGE_SSIZE(),
-			FIL_TYPE_TABLESPACE, NULL);
+	fil_space_t* space = fil_space_create(
+		undo_name, space_id, FSP_FLAGS_PAGE_SSIZE(),
+		FIL_TYPE_TABLESPACE, NULL);
 
-		ut_a(fil_validate());
-		ut_a(space);
+	ut_a(fil_validate());
+	ut_a(space);
 
-		os_offset_t	n_pages = size / UNIV_PAGE_SIZE;
+	fil_node_t* file = space->add(name, fh, 0, false, true);
 
-		/* On 32-bit platforms, ulint is 32 bits and os_offset_t
-		is 64 bits. It is OK to cast the n_pages to ulint because
-		the unit has been scaled to pages and page number is always
-		32 bits. */
-		if (fil_node_create(
-			name, (ulint) n_pages, space, false, TRUE)) {
+	mutex_enter(&fil_system->mutex);
 
-			err = DB_SUCCESS;
+	if (create_new_db) {
+		space->size = file->size = ulint(size >> srv_page_size_shift);
+		space->size_in_header = SRV_UNDO_TABLESPACE_SIZE_IN_PAGES;
+	} else {
+		success = file->read_page0(true);
+		if (!success) {
+			os_file_close(file->handle);
+			file->handle = OS_FILE_CLOSED;
+			ut_a(fil_system->n_open > 0);
+			fil_system->n_open--;
 		}
 	}
 
-	return(err);
+	mutex_exit(&fil_system->mutex);
+
+	return success;
 }
 
 /** Check if undo tablespaces and redo log files exist before creating a
 new system tablespace
 @retval DB_SUCCESS  if all undo and redo logs are not found
@@ -934,16 +912,15 @@ srv_undo_tablespaces_init(bool create_new_db)
 
 		/* The system space id should not be in this array. */
 		ut_a(undo_tablespace_ids[i] != 0);
 		ut_a(undo_tablespace_ids[i] != ULINT_UNDEFINED);
 
-		err = srv_undo_tablespace_open(name, undo_tablespace_ids[i]);
-
-		if (err != DB_SUCCESS) {
+		if (!srv_undo_tablespace_open(name, undo_tablespace_ids[i],
+					      create_new_db)) {
 			ib::error() << "Unable to open undo tablespace '"
 				<< name << "'.";
-			return(err);
+			return DB_ERROR;
 		}
 
 		prev_space_id = undo_tablespace_ids[i];
 
 		/* Note the first undo tablespace id in case of
@@ -964,13 +941,12 @@ srv_undo_tablespaces_init(bool create_new_db)
 
 		snprintf(
 			name, sizeof(name),
 			"%s%cundo%03zu", srv_undo_dir, OS_PATH_SEPARATOR, i);
 
-		err = srv_undo_tablespace_open(name, i);
-
-		if (err != DB_SUCCESS) {
+		if (!srv_undo_tablespace_open(name, i, create_new_db)) {
+			err = DB_ERROR;
 			break;
 		}
 
 		++n_undo_tablespaces;
 
@@ -2076,14 +2052,12 @@ innobase_start_or_create_for_mysql()
 					     >> srv_page_size_shift);
 
 		for (unsigned j = 0; j < srv_n_log_files_found; j++) {
 			sprintf(logfilename + dirnamelen, "ib_logfile%u", j);
 
-			if (!fil_node_create(logfilename, size,
-					     log_space, false, false)) {
-				return(srv_init_abort(DB_ERROR));
-			}
+			log_space->add(logfilename, OS_FILE_CLOSED, size,
+				       false, false);
 		}
 
 		log_init(srv_n_log_files_found);
 
 		if (!log_set_capacity(srv_log_file_size_requested)) {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
