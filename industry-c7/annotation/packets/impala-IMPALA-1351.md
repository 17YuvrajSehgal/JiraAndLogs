# Annotation packet: IMPALA-1351  (impala)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Failed DCHECK(!status_.ok()) in complicated query

The query below reliably crashes. This is almost certainly not the simplest case but the two NOT IN predicates seem to be required.

{noformat}
Socket error 104: Connection reset by peer
Could not execute command: 
select COUNT(t2.month) AS int_col_1
FROM alltypesagg t1 CROSS
JOIN alltypesagg t2 FULL
OUTER JOIN alltypestiny t3 ON t3.year = t2.int_col
AND t3.int_col = t2.year
WHERE t1.day NOT IN
    (SELECT tt1.year AS int_col_1
     FROM alltypes tt1
     RIGHT JOIN alltypes tt2 ON tt2.month = tt1.year
     WHERE t3.tinyint_col = tt2.tinyint_col
       AND t3.bigint_col = tt2.bigint_col
       AND t3.int_col = tt1.id)
  AND t1.day NOT IN
    (SELECT ttt1.tinyint_col AS tinyint_col_1
     FROM alltypestiny ttt1
     WHERE t1.tinyint_col = ttt1.month
       AND ttt1.month IS NULL
       AND ttt1.tinyint_col NOT IN
         (SELECT tttt2.int_col AS int_col_1
          FROM alltypesagg tttt1
          RIGHT JOIN alltypes tttt2 ON tttt2.id = tttt1.year)
       AND ttt1.month NOT IN
         (SELECT MIN(tttt2.year + tttt1.smallint_col * tttt1.int_col - tttt2.bigint_col) + MAX(tttt2.tinyint_col) AS bigint_col_1
          FROM alltypestiny tttt1
          INNER JOIN alltypestiny tttt2 ON tttt2.month = tttt1.smallint_col)
       AND ttt1.month IS NOT NULL
       AND t2.smallint_col = ttt1.bigint_col)
{noformat}

stack trace 

{noformat}
(gdb) bt
#0  0x0000003a0ca32635 in raise () from /lib64/libc.so.6
#1  0x0000003a0ca33e15 in abort () from /lib64/libc.so.6
#2  0x0000000001e862a9 in google::DumpStackTraceAndExit () at src/utilities.cc:147
#3  0x0000000001e7d9ad in google::LogMessage::Fail () at src/logging.cc:1296
#4  0x0000000001e81437 in google::LogMessage::SendToLog (this=0x7f9abb2b5870)
    at src/logging.cc:1250
#5  0x0000000001e80996 in google::LogMessage::Flush (this=0x7f9abb2b5870)
    at src/logging.cc:1119
#6  0x0000000001e818cd in google::LogMessageFatal::~LogMessageFatal (this=0x7f9abb2b5870, 
    __in_chrg=<value optimized out>) at src/logging.cc:1817
#7  0x00000000014c38a0 in impala::PartitionedHashJoinNode::GetNext (this=0x4aa5680, 
    state=0x5b33c00, out_batch=0x728fba0, eos=0x4aa60c8)
    at /data/9/query-gen/Impala/be/src/exec/partitioned-hash-join-node.cc:761
#8  0x00000000014fcdef in impala::BlockingJoinNode::Open (this=0x4aa5f80, state=0x5b33c00)
    at /data/9/query-gen/Impala/be/src/exec/blocking-join-node.cc:177
#9  0x00000000014aabaa in impala::PartitionedAggregationNode::Open (this=0x59cbb80, 
    state=0x5b33c00)
    at /data/9/query-gen/Impala/be/src/exec/partitioned-aggregation-node.cc:227
#10 0x00000000013c20b0 in impala::PlanFragmentExecutor::OpenInternal (this=0x533e1d0)
    at /data/9/query-gen/Impala/be/src/runtime/plan-fragment-executor.cc:332
#11 0x00000000013c1f2c in impala::PlanFragmentExecutor::Open (this=0x533e1d0)
    at /data/9/query-gen/Impala/be/src/runtime/plan-fragment-executor.cc:318
#12 0x000000000106c1d4 in impala::ImpalaServer::FragmentExecState::Exec (this=0x533e000)
    at /data/9/query-gen/Impala/be/src/service/fragment-exec-state.cc:49
{noformat}

code

{code}
 // Finish up the current batch.
    {
      // Putting SCOPED_TIMER in ProcessProbeBatch() causes weird exception handling IR in
      // the xcompiled function, so call it here instead.
      int rows_added = 0;
      SCOPED_TIMER(probe_timer_);
      if (process_probe_batch_fn_ == NULL || ht_ctx_->level() != 0) {
        rows_added = ProcessProbeBatch(join_op_, out_batch, ht_ctx_.get());
      } else {
        DCHECK_NOTNULL(process_probe_batch_fn_level0_);
        if (ht_ctx_->level() == 0) {
          rows_added = process_probe_batch_fn_level0_(this, out_batch, ht_ctx_.get());
        } else {
          rows_added = process_probe_batch_fn_(this, out_batch, ht_ctx_.get());
        }
      }
      if (UNLIKELY(rows_added < 0)) {
        DCHECK(!status_.ok());
{code}
```

## Fix commit message(s)

`5845a02b6e28`

```
IMPALA-1351: Update NAAJ stream to use io sized buffers and better error handling.

Since we only make one NULL-aware stream per NAAJ (as opposed to one per partition),
we do not care about the memory footprint on this tuple stream. For simplicity,
this will always use io-sized buffers.
Also, improving error handling in PHJ::ProcessProbeBatch(), as status_ was not being
set properly.

Disabling the regression test for this bug, as it takes too long to run. Need to find
a simpler query.

Change-Id: I7572f607199f38b1bc30ae208ece2832522342a1
Reviewed-on: http://gerrit.sjc.cloudera.com:8080/4770
Reviewed-by: Ippokratis Pandis <ipandis@cloudera.com>
Tested-by: jenkins

Conflicts:

	be/src/exec/partitioned-hash-join-node.cc
```

## Files the fix changed

Snapshot holds 798 non-test source files. The fix changed 4 file(s); 3 of them are non-test source files (listed below as gold).

- `be/src/exec/partitioned-hash-join-node-ir.cc`
- `be/src/exec/partitioned-hash-join-node.cc`
- `be/src/exec/partitioned-hash-join-node.h`

## The fix diff

### `be/src/exec/partitioned-hash-join-node-ir.cc`

```diff
diff --git a/be/src/exec/partitioned-hash-join-node-ir.cc b/be/src/exec/partitioned-hash-join-node-ir.cc
index b1a58a3b1..8519020c4 100644
--- a/be/src/exec/partitioned-hash-join-node-ir.cc
+++ b/be/src/exec/partitioned-hash-join-node-ir.cc
@@ -127,11 +127,14 @@ int PartitionedHashJoinNode::ProcessProbeBatch(
         // should interpret the hash table probe as "unknown" if there are nulls on the
         // build size. For those rows, we need to process the remaining join
         // predicates later.
         if (null_aware_partition_->build_rows()->num_rows() != 0) {
           if (num_join_conjuncts == 0) goto next_row;
-          if (!null_aware_partition_->probe_rows()->AddRow(current_probe_row_)) return -1;
+          if (!null_aware_partition_->probe_rows()->AddRow(current_probe_row_)) {
+            status_ = null_aware_partition_->probe_rows()->status();
+            return -1;
+          }
           goto next_row;
         }
       }
 
       if ((JoinOp == TJoinOp::LEFT_OUTER_JOIN || JoinOp == TJoinOp::FULL_OUTER_JOIN) &&
@@ -182,11 +185,14 @@ next_row:
         // build rows. First evaluate it against this partition, and if there is not
         // a match, save it to evaluate against other partitions later. If there
         // is a match, the row is skipped.
         if (!non_empty_build_) continue;
         if (num_join_conjuncts == 0) goto next_row;
-        if (UNLIKELY(!null_probe_rows_->AddRow(current_probe_row_))) return -1;
+        if (UNLIKELY(!null_probe_rows_->AddRow(current_probe_row_))) {
+          status_ = null_probe_rows_->status();
+          return -1;
+        }
         matched_null_probe_.push_back(false);
         goto next_row;
       }
       continue;
     }
@@ -200,11 +206,14 @@ next_row:
         DCHECK_EQ(state_, PROCESSING_PROBE);
       } else {
         DCHECK(partition->is_spilled());
         DCHECK(partition->probe_rows() != NULL);
         // This partition is not in memory, spill the probe row.
-        if (UNLIKELY(!AppendRow(partition->probe_rows(), current_probe_row_))) return -1;
+        if (UNLIKELY(!AppendRow(partition->probe_rows(), current_probe_row_))) {
+          status_ = partition->probe_rows()->status();
+          return -1;
+        }
         continue;
       }
     }
   }
```

### `be/src/exec/partitioned-hash-join-node.cc`

```diff
diff --git a/be/src/exec/partitioned-hash-join-node.cc b/be/src/exec/partitioned-hash-join-node.cc
index 78ab1b955..4a6f4dbc7 100644
--- a/be/src/exec/partitioned-hash-join-node.cc
+++ b/be/src/exec/partitioned-hash-join-node.cc
@@ -75,17 +75,18 @@ Status PartitionedHashJoinNode::Init(const TPlanNode& tnode) {
   }
   RETURN_IF_ERROR(
       Expr::CreateExprTrees(pool_, tnode.hash_join_node.other_join_conjuncts,
                             &other_join_conjunct_ctxs_));
 
-  if (join_op_ == TJoinOp::NULL_AWARE_LEFT_ANTI_JOIN) {
-    DCHECK_EQ(eq_join_conjuncts.size(), 1);
-  }
   if (join_op_ == TJoinOp::LEFT_SEMI_JOIN || join_op_ == TJoinOp::LEFT_ANTI_JOIN ||
       join_op_ == TJoinOp::RIGHT_SEMI_JOIN || join_op_ == TJoinOp::RIGHT_ANTI_JOIN ||
       join_op_ == TJoinOp::NULL_AWARE_LEFT_ANTI_JOIN) {
     DCHECK_EQ(conjunct_ctxs_.size(), 0);
+
+    if (join_op_ == TJoinOp::NULL_AWARE_LEFT_ANTI_JOIN) {
+      DCHECK_EQ(eq_join_conjuncts.size(), 1);
+    }
   }
   return Status::OK;
 }
 
 Status PartitionedHashJoinNode::Prepare(RuntimeState* state) {
@@ -127,17 +128,19 @@ Status PartitionedHashJoinNode::Prepare(RuntimeState* state) {
   ht_ctx_.reset(new HashTableCtx(build_expr_ctxs_, probe_expr_ctxs_,
       should_store_nulls, false, state->fragment_hash_seed(), MAX_PARTITION_DEPTH,
       child(1)->row_desc().tuple_descriptors().size()));
 
   if (join_op_ == TJoinOp::NULL_AWARE_LEFT_ANTI_JOIN) {
-    null_aware_partition_ = pool_->Add(new Partition(state, this, 0));
+    // Since there is only one such NAAJ stream, we don't worry about the memory consumed
+    // and always use IO-sized buffers.
+    null_aware_partition_ = pool_->Add(new Partition(state, this, 0, false));
     RETURN_IF_ERROR(null_aware_partition_->build_rows()->Init(runtime_profile(), false));
     RETURN_IF_ERROR(null_aware_partition_->probe_rows()->Init(runtime_profile(), false));
 
     null_probe_rows_ = state->obj_pool()->Add(new BufferedTupleStream(
         state, child(0)->row_desc(), state->block_mgr(), block_mgr_client_,
-        false, true));
+        false /* use small buffers */, false /* delete on read */ ));
     RETURN_IF_ERROR(null_probe_rows_->Init(runtime_profile(), false));
     null_aware_eval_timer_ = ADD_TIMER(runtime_profile(), "NullAwareAntiJoinEvalTime");
   }
 
   partition_build_timer_ = ADD_TIMER(runtime_profile(), "BuildPartitionTime");
@@ -205,24 +208,21 @@ void PartitionedHashJoinNode::Close(RuntimeState* state) {
   Expr::Close(other_join_conjunct_ctxs_, state);
   BlockingJoinNode::Close(state);
 }
 
 PartitionedHashJoinNode::Partition::Partition(RuntimeState* state,
-        PartitionedHashJoinNode* parent, int level)
+        PartitionedHashJoinNode* parent, int level, bool use_small_buffers)
   : parent_(parent),
     is_closed_(false),
     is_spilled_(false),
     level_(level),
     build_rows_(state->obj_pool()->Add(new BufferedTupleStream(
         state, parent_->child(1)->row_desc(), state->block_mgr(),
-        parent_->block_mgr_client_,
-        parent_->using_small_buffers_ /* use small buffers */))),
+        parent_->block_mgr_client_, use_small_buffers))),
     probe_rows_(state->obj_pool()->Add(new BufferedTupleStream(
         state, parent_->child(0)->row_desc(),
-        state->block_mgr(), parent_->block_mgr_client_,
-        parent_->using_small_buffers_, /* use small buffers */
-        true /* delete on read */))) {
+        state->block_mgr(), parent_->block_mgr_client_, use_small_buffers))) {
 }
 
 PartitionedHashJoinNode::Partition::~Partition() {
   DCHECK(is_closed());
 }
@@ -492,11 +492,12 @@ Status PartitionedHashJoinNode::ProcessBuildInput(RuntimeState* state, int level
     DCHECK_EQ(input_partition_->build_rows()->blocks_pinned(), 0) << NodeDebugString();
     RETURN_IF_ERROR(input_partition_->build_rows()->PrepareForRead());
   }
 
   for (int i = 0; i < PARTITION_FANOUT; ++i) {
-    hash_partitions_.push_back(pool_->Add(new Partition(state, this, level)));
+    hash_partitions_.push_back(pool_->Add(
+        new Partition(state, this, level, using_small_buffers_)));
     RETURN_IF_ERROR(hash_partitions_[i]->build_rows()->Init(runtime_profile()));
 
     // Initialize a buffer for the probe here to make sure why have it if we
     // need it. While this is not strictly necessary (there are some cases where we
     // won't need this buffer), the benefit is low. Not grabbing this buffer means
@@ -796,12 +797,16 @@ Status PartitionedHashJoinNode::GetNext(RuntimeState* state, RowBatch* out_batch
 
     if (input_partition_ == NULL) {
       if (join_op_ == TJoinOp::NULL_AWARE_LEFT_ANTI_JOIN) {
         RETURN_IF_ERROR(PrepareNullAwarePartition());
       }
-      *eos = null_aware_partition_ == NULL;
-      if (*eos) break;
+      if (null_aware_partition_ == NULL) {
+        *eos = true;
+        break;
+      } else {
+        *eos = false;
+      }
     }
   }
 
   if (ReachedLimit()) *eos = true;
   return Status::OK;
```

### `be/src/exec/partitioned-hash-join-node.h`

```diff
diff --git a/be/src/exec/partitioned-hash-join-node.h b/be/src/exec/partitioned-hash-join-node.h
index 88efd4736..9f80c8b21 100644
--- a/be/src/exec/partitioned-hash-join-node.h
+++ b/be/src/exec/partitioned-hash-join-node.h
@@ -336,11 +336,12 @@ class PartitionedHashJoinNode : public BlockingJoinNode {
   // Time spent evaluating other_join_conjuncts for NAAJ.
   RuntimeProfile::Counter* null_aware_eval_timer_;
 
   class Partition {
    public:
-    Partition(RuntimeState* state, PartitionedHashJoinNode* parent, int level);
+    Partition(RuntimeState* state, PartitionedHashJoinNode* parent, int level,
+        bool use_small_buffers);
     ~Partition();
 
     BufferedTupleStream* build_rows() { return build_rows_; }
     BufferedTupleStream* probe_rows() { return probe_rows_; }
     HashTable* hash_tbl() const { return hash_tbl_.get(); }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
