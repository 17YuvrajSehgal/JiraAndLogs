# Annotation packet: SERVER-34125  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Only RTT WT storage engines may call `getLastStableCheckpoint`.

In particular, {{inMemory}} does not take checkpoints.
```

## Fix commit message(s)

`57909b80fd32`

```
SERVER-34125: inMemory should not restrict truncating the oplog.
```

## Files the fix changed

Snapshot holds 11,319 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `src/mongo/db/storage/wiredtiger/wiredtiger_record_store.cpp`
- `src/mongo/db/storage/wiredtiger/wiredtiger_record_store.h`

## The fix diff

### `src/mongo/db/storage/wiredtiger/wiredtiger_record_store.cpp`

```diff
diff --git a/src/mongo/db/storage/wiredtiger/wiredtiger_record_store.cpp b/src/mongo/db/storage/wiredtiger/wiredtiger_record_store.cpp
index 1533b66287b..16b68a17481 100644
--- a/src/mongo/db/storage/wiredtiger/wiredtiger_record_store.cpp
+++ b/src/mongo/db/storage/wiredtiger/wiredtiger_record_store.cpp
@@ -1051,20 +1051,23 @@ bool WiredTigerRecordStore::yieldAndAwaitOplogDeletionRequest(OperationContext*
 
     return !oplogStones->isDead();
 }
 
 void WiredTigerRecordStore::reclaimOplog(OperationContext* opCtx) {
+    if (!_kvEngine->supportsRecoverToStableTimestamp()) {
+        // For non-RTT storage engines, the oplog can always be truncated.
+        reclaimOplog(opCtx, Timestamp::max());
+        return;
+    }
     reclaimOplog(opCtx, _kvEngine->getLastStableCheckpointTimestamp());
 }
 
 void WiredTigerRecordStore::reclaimOplog(OperationContext* opCtx, Timestamp persistedTimestamp) {
-
     while (auto stone = _oplogStones->peekOldestStoneIfNeeded()) {
         invariant(stone->lastRecord.isNormal());
 
-        const auto persistedAsNumber = static_cast<std::int64_t>(persistedTimestamp.asULL());
-        if (stone->lastRecord.repr() >= persistedAsNumber) {
+        if (static_cast<std::uint64_t>(stone->lastRecord.repr()) >= persistedTimestamp.asULL()) {
             // Do not truncate oplogs needed for replication recovery.
             return;
         }
 
         LOG(1) << "Truncating the oplog between " << _oplogStones->firstRecord << " and "
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_record_store.h`

```diff
diff --git a/src/mongo/db/storage/wiredtiger/wiredtiger_record_store.h b/src/mongo/db/storage/wiredtiger/wiredtiger_record_store.h
index f60d161a620..6ff78eae68a 100644
--- a/src/mongo/db/storage/wiredtiger/wiredtiger_record_store.h
+++ b/src/mongo/db/storage/wiredtiger/wiredtiger_record_store.h
@@ -249,10 +249,14 @@ public:
 
     bool inShutdown() const;
 
     void reclaimOplog(OperationContext* opCtx);
 
+    /**
+     * The `persistedTimestamp` is when replication recovery would need to replay from on a
+     * restart. `reclaimOplog` will not truncate oplog entries in front of this time.
+     */
     void reclaimOplog(OperationContext* opCtx, Timestamp persistedTimestamp);
 
     int64_t cappedDeleteAsNeeded(OperationContext* opCtx, const RecordId& justInserted);
 
     int64_t cappedDeleteAsNeeded_inlock(OperationContext* opCtx, const RecordId& justInserted);
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
