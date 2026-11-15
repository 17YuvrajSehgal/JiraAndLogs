# Annotation packet: MDEV-15611  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Due to the failure of foreign key detection, Galera slave node killed himself.

*err.log*
{code:java}
[ERROR] Slave SQL: Could not execute Delete_rows_v1 event on table aaa.p; Cannot delete or update a parent row: a foreign key constraint fails (`aaa`.`f`, CONSTRAINT `f_ibfk_1` FOREIGN KEY (`f_id`) REFERENCES `p` (`id`)), Error_code: 1451; handler error HA_ERR_ROW_IS_REFERENCED; the event's master log FIRST, end_log_pos 108, Internal MariaDB error code: 1451
2018-03-16 14:33:39 140457990018816 [Warning] WSREP: RBR event 3 Delete_rows_v1 apply warning: 152, 128
2018-03-16 14:33:39 140457990018816 [Warning] WSREP: Failed to apply app buffer: seqno: 128, status: 1
         at galera/src/trx_handle.cpp:apply():351
{code}

*Reproduce*
*wsrep_slave_threads>1*
{code:java}
CREATE TABLE `p` (
  `id` int(11) NOT NULL,
  `a` varchar(33) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ;

CREATE TABLE `f` (
  `id` int(11) NOT NULL,
  `f_id` int(11) DEFAULT NULL,
  KEY `f_id` (`f_id`),
  CONSTRAINT `f_ibfk_1` FOREIGN KEY (`f_id`) REFERENCES `p` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ;

insert into p select 1,'aaa';

insert into f select 1,1;

#Repeatedly execute the following SQL until you generate thousands of data
insert into f select a.id + b.a,a.f_id from f a join (select max(id) as a from f b) b on 1=1;

select count(*) from f;
+----------+
| count(*) |
+----------+
|   131072 |
+----------+

#Slave node, no matter wsrep_slave_fk_checks is on or off.
show variables like 'wsrep_slave_fk_checks';
+-----------------------+-------+
| Variable_name         | Value |
+-----------------------+-------+
| wsrep_slave_fk_checks | ON    |
+-----------------------+-------+

#Master (Write) node
delete from f;delete from p;

#Slave node down and got errors
2018-03-16 14:33:39 140457990018816 [ERROR] Slave SQL: Could not execute Delete_rows_v1 event on table aaa.p; Cannot delete or update a parent row: a foreign key constraint fails (`aaa`.`f`, CONSTRAINT `f_ibfk_1` FOREIGN KEY (`f_id`) REFERENCES `p` (`id`)), Error_code: 1451; handler error HA_ERR_ROW_IS_REFERENCED; the event's master log FIRST, end_log_pos 108, Internal MariaDB error code: 1451
2018-03-16 14:33:39 140457990018816 [Warning] WSREP: RBR event 3 Delete_rows_v1 apply warning: 152, 128
2018-03-16 14:33:39 140457990018816 [Warning] WSREP: Failed to apply app buffer: seqno: 128, status: 1
         at galera/src/trx_handle.cpp:apply():351
Retrying 2th time
2018-03-16 14:33:39 140457990018816 [ERROR] Slave SQL: Could not execute Delete_rows_v1 event on table aaa.p; Cannot delete or update a parent row: a foreign key constraint fails (`aaa`.`f`, CONSTRAINT `f_ibfk_1` FOREIGN KEY (`f_id`) REFERENCES `p` (`id`)), Error_code: 1451; handler error HA_ERR_ROW_IS_REFERENCED; the event's master log FIRST, end_log_pos 108, Internal MariaDB error code: 1451
2018-03-16 14:33:39 140457990018816 [Warning] WSREP: RBR event 3 Delete_rows_v1 apply warning: 152, 128
2018-03-16 14:33:39 140457990018816 [Warning] WSREP: Failed to apply app buffer: seqno: 128, status: 1
         at galera/src/trx_handle.cpp:apply():351
Retrying 3th time
2018-03-16 14:33:39 140457990018816 [ERROR] Slave SQL: Could not execute Delete_rows_v1 event on table aaa.p; Cannot delete or update a parent row: a foreign key constraint fails (`aaa`.`f`, CONSTRAINT `f_ibfk_1` FOREIGN KEY (`f_id`) REFERENCES `p` (`id`)), Error_code: 1451; handler error HA_ERR_ROW_IS_REFERENCED; the event's master log FIRST, end_log_pos 108, Internal MariaDB error code: 1451
2018-03-16 14:33:39 140457990018816 [Warning] WSREP: RBR event 3 Delete_rows_v1 apply warning: 152, 128
2018-03-16 14:33:39 140457990018816 [Warning] WSREP: Failed to apply app buffer: seqno: 128, status: 1
         at galera/src/trx_handle.cpp:apply():351
Retrying 4th time
2018-03-16 14:33:39 140457990018816 [ERROR] Slave SQL: Could not execute Delete_rows_v1 event on table aaa.p; Cannot delete or update a parent row: a foreign key constraint fails (`aaa`.`f`, CONSTRAINT `f_ibfk_1` FOREIGN KEY (`f_id`) REFERENCES `p` (`id`)), Error_code: 1451; handler error HA_ERR_ROW_IS_REFERENCED; the event's master log FIRST, end_log_pos 108, Internal MariaDB error code: 1451
2018-03-16 14:33:39 140457990018816 [Warning] WSREP: RBR event 3 Delete_rows_v1 apply warning: 152, 128
2018-03-16 14:33:39 140457990018816 [ERROR] WSREP: Failed to apply trx: source: 849e805c-1dd2-11e8-aa79-eb31f2b81368 version: 3 local: 0 state: APPLYING flags: 1 conn_id: 87 trx_id: 12277 seqnos (l: 33, g: 128, s: 127, d: 126, ts: 1358419270394303)
2018-03-16 14:33:39 140457990018816 [ERROR] WSREP: Failed to apply trx 128 4 times
2018-03-16 14:33:39 140457990018816 [ERROR] WSREP: Node consistency compromised, aborting...

#Slave processlist
#Write set 127 is "delete from f;"
#Write set 128 is "delete from p;"
#Slave concurrently apply the two sql
 !image-2018-03-21-10-45-36-084.png|thumbnail! 
{code}

*This error didn't reproduce on MariaDB 10.2.7 with wsrep_slave_threads>1*
```

## Fix commit message(s)

`efae12680e7a`

```
MDEV-15611 Due to the failure of foreign key detection, Galera... slave node killed himself.

Problem:- If we try to delete table with foreign key and table whom it is
referring with wsrep_slave_threads>1 then galera tries to execute both
Delete_rows_log-event in parallel, which should not happen.

Solution:- This is happening because we do not have foreign key info in
write set. Upto version 10.2.7 it used to work fine. Actually it happening
because of issue in commit 2f342c4. wsrep_must_process_fk has changed to
make it similar to original condition.
```

`c69357d8d459`

```
MDEV-15611 Due to the failure of foreign key detection, Galera slave node killed himself.

Merge following change from 10.2

revision-id: d52cff9f10aeea208a1058f7b5527e602125584c (mariadb-10.2.14-25-gd52cff9)
parent(s): bc2501453c3ab9a2cf3516bc3557de8665bc2776
author: Sachin Setiya
committer: Sachin Setiya
timestamp: 2018-04-04 12:26:06 +0530
message:

MDEV-15611 Due to the failure of foreign key detection, Galera...
slave node killed himself.

Problem:- If we try to delete table with foreign key and table whom it is
referring with wsrep_slave_threads>1 then galera tries to execute both
Delete_rows_log-event in parallel, which should not happen.

Solution:- This is happening because we do not have foreign key info in
write set. Upto version 10.2.7 it used to work fine. Actually it happening
because of issue in commit 2f342c4. wsrep_must_process_fk should be used
with negation.
```

## Files the fix changed

Snapshot holds 3,681 non-test source files. The fix changed 5 file(s); 2 of them are non-test source files (listed below as gold).

- `storage/innobase/row/row0upd.cc`
- `storage/xtradb/row/row0upd.cc`

## The fix diff

### `storage/innobase/row/row0upd.cc`

```diff
--- from commit efae12680e7a ---
diff --git a/storage/innobase/row/row0upd.cc b/storage/innobase/row/row0upd.cc
index 5009ac02408..946bbae9534 100644
--- a/storage/innobase/row/row0upd.cc
+++ b/storage/innobase/row/row0upd.cc
@@ -464,21 +464,19 @@ func_exit:
 
 /** Determine if a FOREIGN KEY constraint needs to be processed.
 @param[in]	node	query node
 @param[in]	trx	transaction
 @return	whether the node cannot be ignored */
-inline
-bool
-wsrep_must_process_fk(const upd_node_t* node, const trx_t* trx)
+
+inline bool wsrep_must_process_fk(const upd_node_t* node, const trx_t* trx)
 {
-	if (que_node_get_type(node->common.parent) != QUE_NODE_UPDATE
-	    || !wsrep_on_trx(trx)) {
+	if (!wsrep_on_trx(trx)) {
 		return false;
 	}
-
-	return static_cast<upd_node_t*>(node->common.parent)->cascade_node
-		== node;
+	return que_node_get_type(node->common.parent) != QUE_NODE_UPDATE
+		|| static_cast<upd_node_t*>(node->common.parent)->cascade_node
+		!= node;
 }
 #endif /* WITH_WSREP */
 
 /*********************************************************************//**
 Creates an update node for a query graph.
--- from commit c69357d8d459 ---
diff --git a/storage/innobase/row/row0upd.cc b/storage/innobase/row/row0upd.cc
index e2de47bf86a..33f46882651 100644
--- a/storage/innobase/row/row0upd.cc
+++ b/storage/innobase/row/row0upd.cc
@@ -1801,10 +1801,27 @@ row_upd_store_row(
 	if (UNIV_LIKELY_NULL(heap)) {
 		mem_heap_free(heap);
 	}
 }
 
+#ifdef WITH_WSREP
+/** Determine if a FOREIGN KEY constraint needs to be processed.
+@param[in]	node	query node
+@param[in]	trx	transaction
+@return	whether the node cannot be ignored */
+
+inline bool wsrep_must_process_fk(const upd_node_t* node, const trx_t* trx)
+{
+	if (!wsrep_on_trx(trx)) {
+		return false;
+	}
+	return que_node_get_type(node->common.parent) != QUE_NODE_UPDATE
+		|| static_cast<upd_node_t*>(node->common.parent)->cascade_node
+		!= node;
+}
+#endif /* WITH_WSREP */
+
 /***********************************************************//**
 Updates a secondary index entry of a row.
 @return DB_SUCCESS if operation successfully completed, else error
 code or DB_LOCK_WAIT */
 static MY_ATTRIBUTE((nonnull, warn_unused_result))
@@ -1831,11 +1848,11 @@ row_upd_sec_index_entry(
 
 	index = node->index;
 
 	referenced = row_upd_index_is_referenced(index, trx);
 #ifdef WITH_WSREP
-	ibool foreign = wsrep_row_upd_index_is_foreign(index, trx);
+	bool foreign = wsrep_row_upd_index_is_foreign(index, trx);
 #endif /* WITH_WSREP */
 
 	heap = mem_heap_create(1024);
 
 	/* Build old index entry */
@@ -1960,65 +1977,65 @@ row_upd_sec_index_entry(
 		/* Delete mark the old index record; it can already be
 		delete marked if we return after a lock wait in
 		row_ins_sec_index_entry() below */
 		if (!rec_get_deleted_flag(
 			    rec, dict_table_is_comp(index->table))) {
-#ifdef WITH_WSREP
-			que_node_t *parent = que_node_get_parent(node);
-#endif /* WITH_WSREP */
 			err = btr_cur_del_mark_set_sec_rec(
 				0, btr_cur, TRUE, thr, &mtr);
 
-			if (err == DB_SUCCESS && referenced) {
-
-				ulint*	offsets;
-
-				offsets = rec_get_offsets(
-					rec, index, NULL, ULINT_UNDEFINED,
-					&heap);
-
-				/* NOTE that the following call loses
-				the position of pcur ! */
-				err = row_upd_check_references_constraints(
-					node, &pcur, index->table,
-					index, offsets, thr, &mtr);
+			if (err != DB_SUCCESS) {
+				break;
 			}
+
 #ifdef WITH_WSREP
-			if (err == DB_SUCCESS && !referenced                  &&
-			    wsrep_on_trx(trx)                                 &&
-			    !wsrep_thd_is_BF(trx->mysql_thd, FALSE)           &&
-			    !(parent && que_node_get_type(parent) ==
-				QUE_NODE_UPDATE                               &&
-			      ((upd_node_t*)parent)->cascade_node == node)    &&
-			    foreign
-			) {
-				ulint*	offsets =
-					rec_get_offsets(
+			if (!referenced && foreign
+			    && wsrep_must_process_fk(node, trx)
+			    && !wsrep_thd_is_BF(trx->mysql_thd, FALSE)) {
+				ulint*	offsets = rec_get_offsets(
 						rec, index, NULL, ULINT_UNDEFINED,
 						&heap);
+
 				err = wsrep_row_upd_check_foreign_constraints(
 					node, &pcur, index->table,
 					index, offsets, thr, &mtr);
+
 				switch (err) {
 				case DB_SUCCESS:
 				case DB_NO_REFERENCED_ROW:
 					err = DB_SUCCESS;
 					break;
 				case DB_DEADLOCK:
-					if (wsrep_debug) fprintf (stderr, 
-						"WSREP: sec index FK check fail for deadlock");
+					if (wsrep_debug) {
+						ib_logf(IB_LOG_LEVEL_WARN,
+							"WSREP: sec index FK check fail for deadlock: "
+							" index %s table %s", index->name, index->table->name);
+					}
 					break;
 				default:
-					fprintf (stderr, 
-						 "WSREP: referenced FK check fail: %d", 
-						 (int)err);
+					ib_logf(IB_LOG_LEVEL_ERROR,
+						"WSREP: referenced FK check fail: %s index %s table %s",
+						ut_strerr(err), index->name, index->table->name);
 					break;
 				}
 			}
 #endif /* WITH_WSREP */
 		}
-		break;
+
+		if (referenced) {
+
+			ulint*	offsets;
+
+			offsets = rec_get_offsets(
+				rec, index, NULL, ULINT_UNDEFINED,
+				&heap);
+
+			/* NOTE that the following call loses
+			the position of pcur ! */
+			err = row_upd_check_references_constraints(
+				node, &pcur, index->table,
+				index, offsets, thr, &mtr);
+		}
 	}
 
 	btr_pcur_close(&pcur);
 	mtr_commit(&mtr);
 
@@ -2183,13 +2200,10 @@ row_upd_clust_rec_by_insert(
 	dberr_t		err;
 	ibool		change_ownership	= FALSE;
 	rec_t*		rec;
 	ulint*		offsets			= NULL;
 
-#ifdef WITH_WSREP
-	que_node_t *parent = que_node_get_parent(node);
-#endif /* WITH_WSREP */
 	ut_ad(node);
 	ut_ad(dict_index_is_clust(index));
 
 	trx = thr_get_trx(thr);
 	table = node->table;
@@ -2267,39 +2281,35 @@ err_exit:
 				node, pcur, table, index, offsets, thr, mtr);
 
 			if (err != DB_SUCCESS) {
 				goto err_exit;
 			}
-		}
 #ifdef WITH_WSREP
-		if (!referenced && wsrep_on_trx(trx) &&
-		    !(parent && que_node_get_type(parent) == QUE_NODE_UPDATE &&
-		      ((upd_node_t*)parent)->cascade_node == node)           &&
-		    foreign
-		) {
+		} else if ((foreign && wsrep_must_process_fk(node, trx))) {
 			err = wsrep_row_upd_check_foreign_constraints(
 				node, pcur, table, index, offsets, thr, mtr);
+
 			switch (err) {
 			case DB_SUCCESS:
 			case DB_NO_REFERENCED_ROW:
 				err = DB_SUCCESS;
 				break;
 			case DB_DEADLOCK:
-				if (wsrep_debug) fprintf (stderr, 
-					"WSREP: insert FK check fail for deadlock");
+				if (wsrep_debug) {
+					ib_logf(IB_LOG_LEVEL_WARN,
+						"WSREP: sec index FK check fail for deadlock: "
+						" index %s table %s", index->name, index->table->name);
+				}
 				break;
 			default:
-				fprintf (stderr, 
-					"WSREP: referenced FK check fail: %d", 
-					 (int)err);
+				ib_logf(IB_LOG_LEVEL_ERROR,
+					"WSREP: referenced FK check fail: %s index %s table %s",
+					ut_strerr(err), index->name, index->table->name);
 				break;
 			}
-			if (err != DB_SUCCESS) {
-				goto err_exit;
-			}
-		}
 #endif /* WITH_WSREP */
+		}
 	}
 
 	mtr_commit(mtr);
 
 	err = row_ins_clust_index_entry(
@@ -2498,11 +2508,11 @@ row_upd_del_mark_clust_rec(
 	btr_pcur_t*	pcur;
 	btr_cur_t*	btr_cur;
 	dberr_t		err;
 #ifdef WITH_WSREP
 	rec_t*		rec;
-	que_node_t *parent = que_node_get_parent(node);
+	trx_t* trx = thr_get_trx(thr) ;
 #endif /* WITH_WSREP */
 
 	ut_ad(node);
 	ut_ad(dict_index_is_clust(index));
 	ut_ad(node->is_delete);
@@ -2527,42 +2537,41 @@ row_upd_del_mark_clust_rec(
 		btr_cur_get_block(btr_cur), rec,
 #else
 		btr_cur_get_block(btr_cur), btr_cur_get_rec(btr_cur),
 #endif /* WITH_WSREP */
 		index, offsets, thr, mtr);
-	if (err == DB_SUCCESS && referenced) {
+	if (err != DB_SUCCESS) {
+	} else if (referenced) {
 		/* NOTE that the following call loses the position of pcur ! */
 
 		err = row_upd_check_references_constraints(
 			node, pcur, index->table, index, offsets, thr, mtr);
-	}
 #ifdef WITH_WSREP
-	trx_t* trx = thr_get_trx(thr) ;
-	if (err == DB_SUCCESS && !referenced && wsrep_on_trx(trx) &&
-	    !(parent && que_node_get_type(parent) == QUE_NODE_UPDATE &&
-	      ((upd_node_t*)parent)->cascade_node == node)           &&
-	    foreign
-	) {
+	} else if (foreign && wsrep_must_process_fk(node, trx)) {
 		err = wsrep_row_upd_check_foreign_constraints(
 			node, pcur, index->table, index, offsets, thr, mtr);
+
 		switch (err) {
 		case DB_SUCCESS:
 		case DB_NO_REFERENCED_ROW:
 			err = DB_SUCCESS;
 			break;
 		case DB_DEADLOCK:
-			if (wsrep_debug) fprintf (stderr, 
-				"WSREP: clust rec FK check fail for deadlock");
+			if (wsrep_debug) {
+				ib_logf(IB_LOG_LEVEL_WARN,
+					"WSREP: sec index FK check fail for deadlock: "
+					" index %s table %s", index->name, index->table->name);
+			}
 			break;
 		default:
-			fprintf (stderr, 
-				"WSREP: clust rec referenced FK check fail: %d", 
-				 (int)err);
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"WSREP: referenced FK check fail: %s index %s table %s",
+				ut_strerr(err), index->name, index->table->name);
 			break;
 		}
-	}
 #endif /* WITH_WSREP */
+	}
 
 	mtr_commit(mtr);
 
 	return(err);
 }
```

### `storage/xtradb/row/row0upd.cc`

```diff
--- from commit c69357d8d459 ---
diff --git a/storage/xtradb/row/row0upd.cc b/storage/xtradb/row/row0upd.cc
index 9ac72f8d068..93ccc07c9af 100644
--- a/storage/xtradb/row/row0upd.cc
+++ b/storage/xtradb/row/row0upd.cc
@@ -1804,10 +1804,27 @@ row_upd_store_row(
 	if (UNIV_LIKELY_NULL(heap)) {
 		mem_heap_free(heap);
 	}
 }
 
+#ifdef WITH_WSREP
+/** Determine if a FOREIGN KEY constraint needs to be processed.
+@param[in]	node	query node
+@param[in]	trx	transaction
+@return	whether the node cannot be ignored */
+
+inline bool wsrep_must_process_fk(const upd_node_t* node, const trx_t* trx)
+{
+	if (!wsrep_on_trx(trx)) {
+		return false;
+	}
+	return que_node_get_type(node->common.parent) != QUE_NODE_UPDATE
+		|| static_cast<upd_node_t*>(node->common.parent)->cascade_node
+		!= node;
+}
+#endif /* WITH_WSREP */
+
 /***********************************************************//**
 Updates a secondary index entry of a row.
 @return DB_SUCCESS if operation successfully completed, else error
 code or DB_LOCK_WAIT */
 static MY_ATTRIBUTE((nonnull, warn_unused_result))
@@ -1834,11 +1851,11 @@ row_upd_sec_index_entry(
 
 	index = node->index;
 
 	referenced = row_upd_index_is_referenced(index, trx);
 #ifdef WITH_WSREP
-	ibool foreign = wsrep_row_upd_index_is_foreign(index, trx);
+	bool foreign = wsrep_row_upd_index_is_foreign(index, trx);
 #endif /* WITH_WSREP */
 
 	heap = mem_heap_create(1024);
 
 	/* Build old index entry */
@@ -1966,65 +1983,65 @@ row_upd_sec_index_entry(
 		/* Delete mark the old index record; it can already be
 		delete marked if we return after a lock wait in
 		row_ins_sec_index_entry() below */
 		if (!rec_get_deleted_flag(
 			    rec, dict_table_is_comp(index->table))) {
-#ifdef WITH_WSREP
-			que_node_t *parent = que_node_get_parent(node);
-#endif /* WITH_WSREP */
 			err = btr_cur_del_mark_set_sec_rec(
 				0, btr_cur, TRUE, thr, &mtr);
 
-			if (err == DB_SUCCESS && referenced) {
-
-				ulint*	offsets;
-
-				offsets = rec_get_offsets(
-					rec, index, NULL, ULINT_UNDEFINED,
-					&heap);
-
-				/* NOTE that the following call loses
-				the position of pcur ! */
-				err = row_upd_check_references_constraints(
-					node, &pcur, index->table,
-					index, offsets, thr, &mtr);
+			if (err != DB_SUCCESS) {
+				break;
 			}
+
 #ifdef WITH_WSREP
-			if (err == DB_SUCCESS && !referenced                  &&
-			    wsrep_on_trx(trx)                                 &&
-			    !wsrep_thd_is_BF(trx->mysql_thd, FALSE)           &&
-			    !(parent && que_node_get_type(parent) ==
-				QUE_NODE_UPDATE                               &&
-			      ((upd_node_t*)parent)->cascade_node == node)    &&
-			    foreign
-			) {
-				ulint*	offsets =
-					rec_get_offsets(
+			if (!referenced && foreign
+			    && wsrep_must_process_fk(node, trx)
+			    && !wsrep_thd_is_BF(trx->mysql_thd, FALSE)) {
+				ulint*	offsets = rec_get_offsets(
 						rec, index, NULL, ULINT_UNDEFINED,
 						&heap);
+
 				err = wsrep_row_upd_check_foreign_constraints(
 					node, &pcur, index->table,
 					index, offsets, thr, &mtr);
+
 				switch (err) {
 				case DB_SUCCESS:
 				case DB_NO_REFERENCED_ROW:
 					err = DB_SUCCESS;
 					break;
 				case DB_DEADLOCK:
-					if (wsrep_debug) fprintf (stderr, 
-						"WSREP: sec index FK check fail for deadlock");
+					if (wsrep_debug) {
+						ib_logf(IB_LOG_LEVEL_WARN,
+							"WSREP: sec index FK check fail for deadlock: "
+							" index %s table %s", index->name, index->table->name);
+					}
 					break;
 				default:
-					fprintf (stderr, 
-						 "WSREP: referenced FK check fail: %d", 
-						 (int)err);
+					ib_logf(IB_LOG_LEVEL_ERROR,
+						"WSREP: referenced FK check fail: %s index %s table %s",
+						ut_strerr(err), index->name, index->table->name);
 					break;
 				}
 			}
 #endif /* WITH_WSREP */
 		}
-		break;
+
+		if (referenced) {
+
+			ulint*	offsets;
+
+			offsets = rec_get_offsets(
+				rec, index, NULL, ULINT_UNDEFINED,
+				&heap);
+
+			/* NOTE that the following call loses
+			the position of pcur ! */
+			err = row_upd_check_references_constraints(
+				node, &pcur, index->table,
+				index, offsets, thr, &mtr);
+		}
 	}
 
 	btr_pcur_close(&pcur);
 	mtr_commit(&mtr);
 
@@ -2189,13 +2206,10 @@ row_upd_clust_rec_by_insert(
 	dberr_t		err;
 	ibool		change_ownership	= FALSE;
 	rec_t*		rec;
 	ulint*		offsets			= NULL;
 
-#ifdef WITH_WSREP
-	que_node_t *parent = que_node_get_parent(node);
-#endif /* WITH_WSREP */
 	ut_ad(node);
 	ut_ad(dict_index_is_clust(index));
 
 	trx = thr_get_trx(thr);
 	table = node->table;
@@ -2276,39 +2290,35 @@ err_exit:
 				node, pcur, table, index, offsets, thr, mtr);
 
 			if (err != DB_SUCCESS) {
 				goto err_exit;
 			}
-		}
 #ifdef WITH_WSREP
-		if (!referenced && wsrep_on_trx(trx) &&
-		    !(parent && que_node_get_type(parent) == QUE_NODE_UPDATE &&
-		      ((upd_node_t*)parent)->cascade_node == node)           &&
-		    foreign
-		) {
+		} else if ((foreign && wsrep_must_process_fk(node, trx))) {
 			err = wsrep_row_upd_check_foreign_constraints(
 				node, pcur, table, index, offsets, thr, mtr);
+
 			switch (err) {
 			case DB_SUCCESS:
 			case DB_NO_REFERENCED_ROW:
 				err = DB_SUCCESS;
 				break;
 			case DB_DEADLOCK:
-				if (wsrep_debug) fprintf (stderr, 
-					"WSREP: insert FK check fail for deadlock");
+				if (wsrep_debug) {
+					ib_logf(IB_LOG_LEVEL_WARN,
+						"WSREP: sec index FK check fail for deadlock: "
+						" index %s table %s", index->name, index->table->name);
+				}
 				break;
 			default:
-				fprintf (stderr, 
-					"WSREP: referenced FK check fail: %d", 
-					 (int)err);
+				ib_logf(IB_LOG_LEVEL_ERROR,
+					"WSREP: referenced FK check fail: %s index %s table %s",
+					ut_strerr(err), index->name, index->table->name);
 				break;
 			}
-			if (err != DB_SUCCESS) {
-				goto err_exit;
-			}
-		}
 #endif /* WITH_WSREP */
+		}
 	}
 
 	mtr_commit(mtr);
 
 	err = row_ins_clust_index_entry(
@@ -2510,11 +2520,11 @@ row_upd_del_mark_clust_rec(
 	btr_pcur_t*	pcur;
 	btr_cur_t*	btr_cur;
 	dberr_t		err;
 #ifdef WITH_WSREP
 	rec_t*		rec;
-	que_node_t *parent = que_node_get_parent(node);
+	trx_t* trx = thr_get_trx(thr) ;
 #endif /* WITH_WSREP */
 
 	ut_ad(node);
 	ut_ad(dict_index_is_clust(index));
 	ut_ad(node->is_delete);
@@ -2539,42 +2549,41 @@ row_upd_del_mark_clust_rec(
 		btr_cur_get_block(btr_cur), rec,
 #else
 		btr_cur_get_block(btr_cur), btr_cur_get_rec(btr_cur),
 #endif /* WITH_WSREP */
 		index, offsets, thr, mtr);
-	if (err == DB_SUCCESS && referenced) {
+	if (err != DB_SUCCESS) {
+	} else if (referenced) {
 		/* NOTE that the following call loses the position of pcur ! */
 
 		err = row_upd_check_references_constraints(
 			node, pcur, index->table, index, offsets, thr, mtr);
-	}
 #ifdef WITH_WSREP
-	trx_t* trx = thr_get_trx(thr) ;
-	if (err == DB_SUCCESS && !referenced && wsrep_on_trx(trx) &&
-	    !(parent && que_node_get_type(parent) == QUE_NODE_UPDATE &&
-	      ((upd_node_t*)parent)->cascade_node == node)           &&
-	    foreign
-	) {
+	} else if (foreign && wsrep_must_process_fk(node, trx)) {
 		err = wsrep_row_upd_check_foreign_constraints(
 			node, pcur, index->table, index, offsets, thr, mtr);
+
 		switch (err) {
 		case DB_SUCCESS:
 		case DB_NO_REFERENCED_ROW:
 			err = DB_SUCCESS;
 			break;
 		case DB_DEADLOCK:
-			if (wsrep_debug) fprintf (stderr, 
-				"WSREP: clust rec FK check fail for deadlock");
+			if (wsrep_debug) {
+				ib_logf(IB_LOG_LEVEL_WARN,
+					"WSREP: sec index FK check fail for deadlock: "
+					" index %s table %s", index->name, index->table->name);
+			}
 			break;
 		default:
-			fprintf (stderr, 
-				"WSREP: clust rec referenced FK check fail: %d", 
-				 (int)err);
+			ib_logf(IB_LOG_LEVEL_ERROR,
+				"WSREP: referenced FK check fail: %s index %s table %s",
+				ut_strerr(err), index->name, index->table->name);
 			break;
 		}
-	}
 #endif /* WITH_WSREP */
+	}
 
 	mtr_commit(mtr);
 
 	return(err);
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
