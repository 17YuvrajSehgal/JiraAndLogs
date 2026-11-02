# Annotation packet: SERVER-62000  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Do not generate "unique" field in oplog if collMod "unique" parameter is a no-op

If we use the collMod "unique" parameter, which currently has to be set to {{true}}, on a index that is already unique, the primary still generates the following oplog entry that will cause oplog application on a secondary to fail:
{noformat}
{collMod: 'mycoll', index: {name: 'myidx', unique: false}}
{noformat}

For a no-op "unique" collMod request, we should apply a strategy similar to that implemented in SERVER-48047.

This is follow-up work to SERVER-61980 where we addressed a gap in the no-op "hidden" parameter when "unique" is also provided.

This applies to a flag-guarded feature that is still under development.
```

## Fix commit message(s)

`5e5230ee102f`

```
SERVER-62000 minimize BSONElement references in collMod index options parsing
```

`a4387740aa41`

```
SERVER-62000 Do not generate "unique" field in oplog if collMod "unique" parameter is a no-op
```

`88390273fec7`

```
SERVER-62000 rename hidden_index_noop.js to reflect new test cases that do not include hidden indexes
```

## Files the fix changed

Snapshot holds 16,633 non-test source files. The fix changed 4 file(s); 2 of them are non-test source files (listed below as gold).

- `src/mongo/db/catalog/coll_mod.cpp`
- `src/mongo/db/catalog/coll_mod_index.cpp`

## The fix diff

### `src/mongo/db/catalog/coll_mod.cpp`

```diff
--- from commit 5e5230ee102f ---
diff --git a/src/mongo/db/catalog/coll_mod.cpp b/src/mongo/db/catalog/coll_mod.cpp
index 16d996b972f..ff3c4c61d14 100644
--- a/src/mongo/db/catalog/coll_mod.cpp
+++ b/src/mongo/db/catalog/coll_mod.cpp
@@ -132,69 +132,50 @@ StatusWith<ParsedCollModRequest> parseCollModRequest(OperationContext* opCtx,
         if (isGenericArgument(fieldName)) {
             continue;  // Don't add to oplog builder.
         } else if (fieldName == "collMod") {
             // no-op
         } else if (fieldName == "index" && !isView) {
-            auto cmrIndex = &cmr.indexRequest;
-            cmrIndex->indexObj = e.Obj().getOwned();
-            const auto& indexObj = cmrIndex->indexObj;
+            const auto& cmdIndex = *cmd.getIndex();
             StringData indexName;
             BSONObj keyPattern;
 
-            for (auto&& elem : indexObj) {
-                const auto field = elem.fieldNameStringData();
-                if (field != "name" && field != "keyPattern" && field != "expireAfterSeconds" &&
-                    field != "hidden" && field != "unique") {
-                    return {ErrorCodes::InvalidOptions,
-                            str::stream()
-                                << "Unrecognized field '" << field << "' in 'index' option"};
-                }
-            }
-
-            BSONElement nameElem = indexObj["name"];
-            BSONElement keyPatternElem = indexObj["keyPattern"];
-            if (nameElem && keyPatternElem) {
+            if (cmdIndex.getName() && cmdIndex.getKeyPattern()) {
                 return Status(ErrorCodes::InvalidOptions,
                               "Cannot specify both key pattern and name.");
             }
 
-            if (!nameElem && !keyPatternElem) {
+            if (!cmdIndex.getName() && !cmdIndex.getKeyPattern()) {
                 return Status(ErrorCodes::InvalidOptions,
                               "Must specify either index name or key pattern.");
             }
 
-            if (nameElem) {
-                if (nameElem.type() != BSONType::String) {
-                    return Status(ErrorCodes::InvalidOptions, "Index name must be a string.");
-                }
-                indexName = nameElem.valueStringData();
+            if (cmdIndex.getName()) {
+                indexName = *cmdIndex.getName();
             }
 
-            if (keyPatternElem) {
-                if (keyPatternElem.type() != BSONType::Object) {
-                    return Status(ErrorCodes::InvalidOptions, "Key pattern must be an object.");
-                }
-                keyPattern = keyPatternElem.embeddedObject();
+            if (cmdIndex.getKeyPattern()) {
+                keyPattern = *cmdIndex.getKeyPattern();
+            }
+
+            if (!cmdIndex.getExpireAfterSeconds() && !cmdIndex.getHidden() &&
+                !cmdIndex.getUnique()) {
+                return Status(ErrorCodes::InvalidOptions,
+                              "no expireAfterSeconds, hidden, or unique field");
             }
 
-            cmrIndex->indexExpireAfterSeconds = indexObj["expireAfterSeconds"];
-            cmrIndex->indexHidden = indexObj["hidden"];
-            cmrIndex->indexUnique = indexObj["unique"];
+            auto cmrIndex = &cmr.indexRequest;
+            cmrIndex->indexObj = e.Obj().getOwned();
+            const auto& indexObj = cmrIndex->indexObj;
 
-            if (cmrIndex->indexUnique) {
+            if (cmdIndex.getUnique()) {
                 uassert(ErrorCodes::InvalidOptions,
                         "collMod does not support converting an index to unique",
                         feature_flags::gCollModIndexUnique.isEnabled(
                             serverGlobalParams.featureCompatibility));
             }
 
-            if (cmrIndex->indexExpireAfterSeconds.eoo() && cmrIndex->indexHidden.eoo() &&
-                cmrIndex->indexUnique.eoo()) {
-                return Status(ErrorCodes::InvalidOptions,
-                              "no expireAfterSeconds, hidden, or unique field");
-            }
-            if (!cmrIndex->indexExpireAfterSeconds.eoo()) {
+            if (cmdIndex.getExpireAfterSeconds()) {
                 if (isTimeseries) {
                     return Status(ErrorCodes::InvalidOptions,
                                   "TTL indexes are not supported for time-series collections. "
                                   "Please refer to the documentation and use the top-level "
                                   "'expireAfterSeconds' option instead");
@@ -202,22 +183,17 @@ StatusWith<ParsedCollModRequest> parseCollModRequest(OperationContext* opCtx,
                 if (coll->isCapped()) {
                     return Status(ErrorCodes::InvalidOptions,
                                   "TTL indexes are not supported for capped collections.");
                 }
                 if (auto status = index_key_validate::validateExpireAfterSeconds(
-                        cmrIndex->indexExpireAfterSeconds.safeNumberLong());
+                        *cmdIndex.getExpireAfterSeconds());
                     !status.isOK()) {
                     return {ErrorCodes::InvalidOptions, status.reason()};
                 }
             }
-            if (!cmrIndex->indexHidden.eoo() && !cmrIndex->indexHidden.isBoolean()) {
-                return Status(ErrorCodes::InvalidOptions, "hidden field must be a boolean");
-            }
-            if (!cmrIndex->indexUnique.eoo() && !cmrIndex->indexUnique.isBoolean()) {
-                return Status(ErrorCodes::InvalidOptions, "unique field must be a boolean");
-            }
-            if (!cmrIndex->indexHidden.eoo() && coll->isClustered() &&
+
+            if (cmdIndex.getHidden() && coll->isClustered() &&
                 !nss.isTimeseriesBucketsCollection()) {
                 auto clusteredInfo = coll->getClusteredInfo();
                 tassert(6011801,
                         "Collection isClustered() and getClusteredInfo() should be synced",
                         clusteredInfo);
@@ -262,11 +238,11 @@ StatusWith<ParsedCollModRequest> parseCollModRequest(OperationContext* opCtx,
                 }
 
                 cmrIndex->idx = indexes[0];
             }
 
-            if (!cmrIndex->indexExpireAfterSeconds.eoo()) {
+            if (cmdIndex.getExpireAfterSeconds()) {
                 cmr.numModifications++;
                 BSONElement oldExpireSecs = cmrIndex->idx->infoObj().getField("expireAfterSeconds");
                 if (oldExpireSecs.eoo()) {
                     if (cmrIndex->idx->isIdIndex()) {
                         return Status(ErrorCodes::InvalidOptions,
@@ -279,32 +255,36 @@ StatusWith<ParsedCollModRequest> parseCollModRequest(OperationContext* opCtx,
                     }
                 } else if (!oldExpireSecs.isNumber()) {
                     return Status(ErrorCodes::InvalidOptions,
                                   "existing expireAfterSeconds field is not a number");
                 }
+
+                cmrIndex->indexExpireAfterSeconds =
+                    indexObj[CollModIndex::kExpireAfterSecondsFieldName];
             }
 
-            if (cmrIndex->indexUnique) {
+            if (cmdIndex.getUnique()) {
                 cmr.numModifications++;
-                if (!cmrIndex->indexUnique.trueValue()) {
+                if (bool unique = *cmdIndex.getUnique(); !unique) {
                     return Status(ErrorCodes::BadValue, "Cannot make index non-unique");
                 }
+
+                cmrIndex->indexUnique = indexObj[CollModIndex::kUniqueFieldName];
             }
 
-            if (cmrIndex->indexHidden) {
+            if (cmdIndex.getHidden()) {
                 cmr.numModifications++;
                 // Hiding a hidden index or unhiding a visible index should be treated as a no-op.
-                if (cmrIndex->idx->hidden() == cmrIndex->indexHidden.booleanSafe()) {
+                if (cmrIndex->idx->hidden() == *cmdIndex.getHidden()) {
                     // If the collMod includes "expireAfterSeconds" or "unique", remove the no-op
                     // "hidden" parameter and write the remaining "index" object to the oplog entry
                     // builder.
-                    if (!cmrIndex->indexExpireAfterSeconds.eoo() || !cmrIndex->indexUnique.eoo()) {
+                    if (cmdIndex.getExpireAfterSeconds() || cmdIndex.getUnique()) {
                         oplogEntryBuilder->append(fieldName, indexObj.removeField("hidden"));
                     }
-                    // Un-set "indexHidden" in ParsedCollModRequest, and skip the automatic write to
-                    // the oplogEntryBuilder that occurs at the end of the parsing loop.
-                    cmrIndex->indexHidden = {};
+                    // Skip setting "indexHidden" in ParsedCollModRequest, and skip the automatic
+                    // write to the oplogEntryBuilder that occurs at the end of the parsing loop.
                     continue;
                 }
 
                 // Disallow index hiding/unhiding on system collections.
                 // Bucket collections, which hold data for user-created time-series collections, do
@@ -316,10 +296,12 @@ StatusWith<ParsedCollModRequest> parseCollModRequest(OperationContext* opCtx,
                 // Disallow index hiding/unhiding on _id indexes - these are created by default and
                 // are critical to most collection operations.
                 if (cmrIndex->idx->isIdIndex()) {
                     return Status(ErrorCodes::BadValue, "can't hide _id index");
                 }
+
+                cmrIndex->indexHidden = indexObj[CollModIndex::kHiddenFieldName];
             }
         } else if (fieldName == "validator" && !isView && !isTimeseries) {
             cmr.numModifications++;
             // If the feature compatibility version is not kLatest, and we are validating features
             // as primary, ban the use of new agg features introduced in kLatest to prevent them
--- from commit a4387740aa41 ---
diff --git a/src/mongo/db/catalog/coll_mod.cpp b/src/mongo/db/catalog/coll_mod.cpp
index ff3c4c61d14..f40de5555de 100644
--- a/src/mongo/db/catalog/coll_mod.cpp
+++ b/src/mongo/db/catalog/coll_mod.cpp
@@ -260,34 +260,31 @@ StatusWith<ParsedCollModRequest> parseCollModRequest(OperationContext* opCtx,
 
                 cmrIndex->indexExpireAfterSeconds =
                     indexObj[CollModIndex::kExpireAfterSecondsFieldName];
             }
 
+            // Make a copy of the index options doc for writing to the oplog.
+            // This index options doc should exclude the options that do not need
+            // to be modified.
+            auto indexObjForOplog = indexObj;
+
             if (cmdIndex.getUnique()) {
                 cmr.numModifications++;
                 if (bool unique = *cmdIndex.getUnique(); !unique) {
                     return Status(ErrorCodes::BadValue, "Cannot make index non-unique");
                 }
 
-                cmrIndex->indexUnique = indexObj[CollModIndex::kUniqueFieldName];
+                // Attempting to converting a unique index should be treated as a no-op.
+                if (cmrIndex->idx->unique()) {
+                    indexObjForOplog = indexObjForOplog.removeField(CollModIndex::kUniqueFieldName);
+                } else {
+                    cmrIndex->indexUnique = indexObj[CollModIndex::kUniqueFieldName];
+                }
             }
 
             if (cmdIndex.getHidden()) {
                 cmr.numModifications++;
-                // Hiding a hidden index or unhiding a visible index should be treated as a no-op.
-                if (cmrIndex->idx->hidden() == *cmdIndex.getHidden()) {
-                    // If the collMod includes "expireAfterSeconds" or "unique", remove the no-op
-                    // "hidden" parameter and write the remaining "index" object to the oplog entry
-                    // builder.
-                    if (cmdIndex.getExpireAfterSeconds() || cmdIndex.getUnique()) {
-                        oplogEntryBuilder->append(fieldName, indexObj.removeField("hidden"));
-                    }
-                    // Skip setting "indexHidden" in ParsedCollModRequest, and skip the automatic
-                    // write to the oplogEntryBuilder that occurs at the end of the parsing loop.
-                    continue;
-                }
-
                 // Disallow index hiding/unhiding on system collections.
                 // Bucket collections, which hold data for user-created time-series collections, do
                 // not have this restriction.
                 if (nss.isSystem() && !nss.isTimeseriesBucketsCollection()) {
                     return Status(ErrorCodes::BadValue, "Can't hide index on system collection");
@@ -297,12 +294,29 @@ StatusWith<ParsedCollModRequest> parseCollModRequest(OperationContext* opCtx,
                 // are critical to most collection operations.
                 if (cmrIndex->idx->isIdIndex()) {
                     return Status(ErrorCodes::BadValue, "can't hide _id index");
                 }
 
-                cmrIndex->indexHidden = indexObj[CollModIndex::kHiddenFieldName];
+                // Hiding a hidden index or unhiding a visible index should be treated as a no-op.
+                if (cmrIndex->idx->hidden() == *cmdIndex.getHidden()) {
+                    indexObjForOplog = indexObjForOplog.removeField(CollModIndex::kHiddenFieldName);
+                } else {
+                    cmrIndex->indexHidden = indexObj[CollModIndex::kHiddenFieldName];
+                }
             }
+
+            // The index options doc must contain either the name or key pattern, but not both.
+            // If we have just one field, the index modifications requested matches the current
+            // state in catalog and there is nothing further to do.
+            if (indexObjForOplog.nFields() > 1) {
+                oplogEntryBuilder->append(CollMod::kIndexFieldName, indexObjForOplog);
+            }
+
+            // Skip the automatic write to the oplogEntryBuilder that occurs at the end of the
+            // parsing loop because we have already written the normalized index options in
+            // 'indexObjForOplog'.
+            continue;
         } else if (fieldName == "validator" && !isView && !isTimeseries) {
             cmr.numModifications++;
             // If the feature compatibility version is not kLatest, and we are validating features
             // as primary, ban the use of new agg features introduced in kLatest to prevent them
             // from being persisted in the catalog.
```

### `src/mongo/db/catalog/coll_mod_index.cpp`

```diff
--- from commit a4387740aa41 ---
diff --git a/src/mongo/db/catalog/coll_mod_index.cpp b/src/mongo/db/catalog/coll_mod_index.cpp
index 64a4a4a2d4a..5f126d56084 100644
--- a/src/mongo/db/catalog/coll_mod_index.cpp
+++ b/src/mongo/db/catalog/coll_mod_index.cpp
@@ -130,14 +130,12 @@ void _processCollModIndexRequestUnique(OperationContext* opCtx,
                                        const IndexDescriptor* idx,
                                        boost::optional<repl::OplogApplication::Mode> mode,
                                        const CollModWriteOpsTracker::Docs* docsForUniqueIndex,
                                        BSONElement indexUnique,
                                        BSONElement* newUnique) {
-    // Do not update catalog if index is already unique.
-    if (idx->infoObj().getField("unique").trueValue()) {
-        return;
-    }
+    invariant(!idx->unique(), str::stream() << "Index is already unique: " << idx->infoObj());
+
     const auto& collection = autoColl->getCollection();
 
     // Checks for duplicates on the primary or for the 'applyOps' command.
     // TODO(SERVER-61356): revisit this condition for tenant migration, which uses kInitialSync.
     std::list<std::set<RecordId>> duplicateRecordsList;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
