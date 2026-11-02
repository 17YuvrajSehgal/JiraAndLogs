# Annotation packet: SERVER-60958  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Avoid server hang in chunk migration when step-down event occurs
```

## Fix commit message(s)

`dc5de6843f2e`

```
SERVER-60958 Access info on SessionCatalogMigrationSource outside of the Cloner protected section
```

## Files the fix changed

Snapshot holds 16,556 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/s/migration_chunk_cloner_source_legacy.cpp`

## The fix diff

### `src/mongo/db/s/migration_chunk_cloner_source_legacy.cpp`

```diff
diff --git a/src/mongo/db/s/migration_chunk_cloner_source_legacy.cpp b/src/mongo/db/s/migration_chunk_cloner_source_legacy.cpp
index 888ecb0e8fe..6df9f3e4b87 100644
--- a/src/mongo/db/s/migration_chunk_cloner_source_legacy.cpp
+++ b/src/mongo/db/s/migration_chunk_cloner_source_legacy.cpp
@@ -1016,10 +1016,15 @@ Status MigrationChunkClonerSourceLegacy::_checkRecipientCloningStatus(OperationC
         if (!res["waited"].boolean()) {
             sleepmillis(1LL << std::min(iteration, 10));
         }
         iteration++;
 
+        const auto sessionCatalogSourceInCatchupPhase = _sessionCatalogSource->inCatchupPhase();
+        const auto estimateUntransferredSessionsSize = sessionCatalogSourceInCatchupPhase
+            ? _sessionCatalogSource->untransferredCatchUpDataSize()
+            : std::numeric_limits<int64_t>::max();
+
         stdx::lock_guard<Latch> sl(_mutex);
 
         const std::size_t cloneLocsRemaining = _cloneLocs.size();
 
         if (_forceJumbo && _jumboChunkCloneState) {
@@ -1038,12 +1043,12 @@ Status MigrationChunkClonerSourceLegacy::_checkRecipientCloningStatus(OperationC
                   "response"_attr = redact(res),
                   "memoryUsedBytes"_attr = _memoryUsed,
                   "docsRemainingToClone"_attr = cloneLocsRemaining);
         }
 
-        if (res["state"].String() == "steady" && _sessionCatalogSource->inCatchupPhase() &&
-            _sessionCatalogSource->untransferredCatchUpDataSize() == 0) {
+        if (res["state"].String() == "steady" && sessionCatalogSourceInCatchupPhase &&
+            estimateUntransferredSessionsSize == 0) {
             if (cloneLocsRemaining != 0 ||
                 (_jumboChunkCloneState && _forceJumbo &&
                  PlanExecutor::IS_EOF != _jumboChunkCloneState->clonerState)) {
                 return {ErrorCodes::OperationIncomplete,
                         str::stream() << "Unable to enter critical section because the recipient "
@@ -1065,19 +1070,17 @@ Status MigrationChunkClonerSourceLegacy::_checkRecipientCloningStatus(OperationC
             }
             supportsCriticalSectionDuringCatchUp = true;
         }
 
         if ((res["state"].String() == "steady" || res["state"].String() == "catchup") &&
-            _sessionCatalogSource->inCatchupPhase() && supportsCriticalSectionDuringCatchUp) {
+            sessionCatalogSourceInCatchupPhase && supportsCriticalSectionDuringCatchUp) {
             int64_t estimatedUntransferredModsSize =
                 _untransferredDeletesCounter * _averageObjectIdSize +
                 _untransferredUpsertsCounter * _averageObjectSizeForCloneLocs;
             auto estimatedUntransferredChunkPercentage =
                 (std::min(_args.getMaxChunkSizeBytes(), estimatedUntransferredModsSize) * 100) /
                 _args.getMaxChunkSizeBytes();
-            int64_t estimateUntransferredSessionsSize =
-                _sessionCatalogSource->untransferredCatchUpDataSize();
             int64_t maxUntransferredSessionsSize = BSONObjMaxUserSize *
                 _args.getMaxChunkSizeBytes() / ChunkSizeSettingsType::kDefaultMaxChunkSizeBytes;
             if (estimatedUntransferredChunkPercentage < maxCatchUpPercentageBeforeBlockingWrites &&
                 estimateUntransferredSessionsSize < maxUntransferredSessionsSize) {
                 // The recipient is sufficiently caught-up with the writes on the donor.
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
