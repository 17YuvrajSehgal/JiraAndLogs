# Annotation packet: SERVER-14738  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Updates to documents with text-indexed fields may lead to incorrect entries

{panel:title=Issue Status as of Aug 04, 2014|borderColor=#ccc|titleBGColor=#6CB33F|bgColor=#EEEEEE}

*ISSUE SUMMARY*
An update to a text-indexed field may fail to update the text index. As a result a text search may not match the field contents, yielding incorrect search results.

For example, given a collection with a text index on field “title”:

{code}
> db.col.ensureIndex({title:"text"})
{code}

Inserting a document and searching for it produces the expected results:
{code}
> db.col.insert({title:"test"})
WriteResult({ "nInserted" : 1 })
> db.col.find({$text:{$search:"test"}})
{ "_id" : ObjectId("53df95d559c54fcf80f8e418"), "title" : "test" }
{code}

But when the text-indexed field is modified under the conditions outlined above, queries may return incorrect results:
{code}
> db.col.update({title:"test"}, {$set:{title:"fail"}})
WriteResult({ "nMatched" : 1, "nUpserted" : 0, "nModified" : 1 })
> db.col.find({$text:{$search:"test"}})
{ "_id" : ObjectId("53df95d559c54fcf80f8e418"), "title" : "fail" }
{code}

At this stage, if the document grows sufficiently and needs to be moved, the data in the index entry no longer points to a valid document, and queries that hit the index return an error:
{code}
> db.col.update({}, {$set : { padding : new Array(512).join('x') }})
WriteResult({ "nMatched" : 1, "nUpserted" : 0, "nModified" : 1 })
> db.col.find({$text:{$search:"test"}})
error: {
        "$err" : "BSONObj size: -286331154 (0xEEEEEEEE) is invalid. Size must be between 0 and 16793600(16MB) First element: _id: ObjectId('53dfae9755c5ce157d6a8560')",
        "code" : 10334
}
{code}

*USER IMPACT*
Users who update documents in a collection that contains a text index may see incorrect/incomplete search results.

Specifically, an update may cause corrupt index entries if *all* of the following conditions are met:
* the update modifies a text-indexed field, and
* the update does not change the size of any text-indexed values, and
* the update is in-place (does not result in a document move), and
* the update does not modify another index

None of the following operations trigger this bug:
* an update that changes the size of a text-indexed value
* an update that results in a document move
* an update that modifies another index 
* an update that replaces the entire document
* an insert, query, or delete operation

*WORKAROUNDS*
No workarounds exist for this issue. To fix this issue, users must upgrade to 2.4.11 or 2.6.4 and then rebuild text indexes, either by dropping and creating each index, or by resyncing a new replica set member.

There is no simple way to identify whether or not a text index is affected by this issue. If any updates have been issued to documents in a collection with a text index, the index may have been impacted.

*AFFECTED VERSIONS*
MongoDB versions 2.4.0 through 2.4.10, and 2.6.0 through 2.6.3 are affected by this issue. 

*FIX VERSION*
The fix is included in the 2.4.11 and 2.6.4 production releases.

*RESOLUTION DETAILS*
Correctly determine if update with text index is in-place.

{panel}

h6. Original description
```

## Fix commit message(s)

`1f00ffcd22e6`

```
SERVER-14738 Correctly determine if update w/ text index is in-place
```

`d7133440dc8f`

```
SERVER-14738 UpdateIndexData::clear() reset all member variables
```

## Files the fix changed

Snapshot holds 7,707 non-test source files. The fix changed 18 file(s); 8 of them are non-test source files (listed below as gold).

- `src/mongo/db/catalog/collection_info_cache.cpp`
- `src/mongo/db/catalog/collection_info_cache.h`
- `src/mongo/db/ops/update.cpp`
- `src/mongo/db/ops/update_driver.cpp`
- `src/mongo/db/ops/update_driver.h`
- `src/mongo/db/ops/update_lifecycle.h`
- `src/mongo/db/ops/update_lifecycle_impl.cpp`
- `src/mongo/db/ops/update_lifecycle_impl.h`

## The fix diff

### `src/mongo/db/catalog/collection_info_cache.cpp`

```diff
--- from commit 1f00ffcd22e6 ---
diff --git a/src/mongo/db/catalog/collection_info_cache.cpp b/src/mongo/db/catalog/collection_info_cache.cpp
index 85122d0d926..aea1af88c42 100644
--- a/src/mongo/db/catalog/collection_info_cache.cpp
+++ b/src/mongo/db/catalog/collection_info_cache.cpp
@@ -30,14 +30,16 @@
 
 #include "mongo/platform/basic.h"
 
 #include "mongo/db/catalog/collection_info_cache.h"
 
-#include "mongo/db/d_concurrency.h"
-#include "mongo/db/query/plan_cache.h"
 #include "mongo/db/catalog/collection.h"
+#include "mongo/db/d_concurrency.h"
+#include "mongo/db/fts/fts_spec.h"
 #include "mongo/db/index/index_descriptor.h"
+#include "mongo/db/index_legacy.h"
+#include "mongo/db/query/plan_cache.h"
 #include "mongo/util/debug_util.h"
 #include "mongo/util/log.h"
 
 
 namespace mongo {
@@ -59,17 +61,44 @@ namespace mongo {
     }
 
     void CollectionInfoCache::computeIndexKeys() {
         _indexedPaths.clear();
 
-        IndexCatalog::IndexIterator i = _collection->getIndexCatalog()->getIndexIterator( true );
-        while( i.more() ) {
-            BSONObj key = i.next()->keyPattern();
-            BSONObjIterator j( key );
-            while ( j.more() ) {
-                BSONElement e = j.next();
-                _indexedPaths.addPath( e.fieldName() );
+        IndexCatalog::IndexIterator i = _collection->getIndexCatalog()->getIndexIterator(true);
+        while (i.more()) {
+            IndexDescriptor* descriptor = i.next();
+
+            if (descriptor->getAccessMethodName() != IndexNames::TEXT) {
+                BSONObj key = descriptor->keyPattern();
+                BSONObjIterator j(key);
+                while (j.more()) {
+                    BSONElement e = j.next();
+                    _indexedPaths.addPath(e.fieldName());
+                }
+            }
+            else {
+                fts::FTSSpec ftsSpec(descriptor->infoObj());
+
+                if (ftsSpec.wildcard()) {
+                    _indexedPaths.allPathsIndexed();
+                }
+                else {
+                    for (size_t i = 0; i < ftsSpec.numExtraBefore(); ++i) {
+                        _indexedPaths.addPath(ftsSpec.extraBefore(i));
+                    }
+                    for (fts::Weights::const_iterator it = ftsSpec.weights().begin();
+                         it != ftsSpec.weights().end();
+                         ++it) {
+                        _indexedPaths.addPath(it->first);
+                    }
+                    for (size_t i = 0; i < ftsSpec.numExtraAfter(); ++i) {
+                        _indexedPaths.addPath(ftsSpec.extraAfter(i));
+                    }
+                    // Any update to a path containing "language" as a component could change the
+                    // language of a subdocument.  Add the override field as a path component.
+                    _indexedPaths.addPathComponent(ftsSpec.languageOverrideField());
+                }
             }
         }
 
         _keysComputed = true;
```

### `src/mongo/db/catalog/collection_info_cache.h`

```diff
--- from commit 1f00ffcd22e6 ---
diff --git a/src/mongo/db/catalog/collection_info_cache.h b/src/mongo/db/catalog/collection_info_cache.h
index 874018fdc89..3948c55e5c0 100644
--- a/src/mongo/db/catalog/collection_info_cache.h
+++ b/src/mongo/db/catalog/collection_info_cache.h
@@ -30,13 +30,13 @@
 
 #pragma once
 
 #include <boost/scoped_ptr.hpp>
 
-#include "mongo/db/index_set.h"
-#include "mongo/db/query/query_settings.h"
 #include "mongo/db/query/plan_cache.h"
+#include "mongo/db/query/query_settings.h"
+#include "mongo/db/update_index_data.h"
 
 namespace mongo {
 
     class Collection;
 
@@ -71,11 +71,11 @@ namespace mongo {
         // -------------------
 
         /* get set of index keys for this namespace.  handy to quickly check if a given
            field is indexed (Note it might be a secondary component of a compound index.)
         */
-        const IndexPathSet& indexKeys() {
+        const UpdateIndexData& indexKeys() {
             if ( !_keysComputed )
                 computeIndexKeys();
             return _indexedPaths;
         }
 
@@ -95,11 +95,11 @@ namespace mongo {
 
         Collection* _collection; // not owned
 
         // ---  index keys cache
         bool _keysComputed;
-        IndexPathSet _indexedPaths;
+        UpdateIndexData _indexedPaths;
 
         // A cache for query plans.
         boost::scoped_ptr<PlanCache> _planCache;
 
         // Query settings.
```

### `src/mongo/db/ops/update.cpp`

```diff
--- from commit 1f00ffcd22e6 ---
diff --git a/src/mongo/db/ops/update.cpp b/src/mongo/db/ops/update.cpp
index 4a95d8c92c9..921f7fd02e6 100644
--- a/src/mongo/db/ops/update.cpp
+++ b/src/mongo/db/ops/update.cpp
@@ -35,24 +35,24 @@
 #include <cstring>  // for memcpy
 
 #include "mongo/bson/mutable/algorithm.h"
 #include "mongo/bson/mutable/document.h"
 #include "mongo/client/dbclientinterface.h"
+#include "mongo/db/catalog/collection.h"
 #include "mongo/db/catalog/database_holder.h"
 #include "mongo/db/clientcursor.h"
-#include "mongo/db/index_set.h"
+#include "mongo/db/operation_context_impl.h"
 #include "mongo/db/ops/update_driver.h"
 #include "mongo/db/ops/update_executor.h"
 #include "mongo/db/ops/update_lifecycle.h"
 #include "mongo/db/query/explain.h"
 #include "mongo/db/query/get_executor.h"
 #include "mongo/db/query/lite_parsed_query.h"
 #include "mongo/db/query/query_planner_common.h"
-#include "mongo/db/repl/repl_coordinator_global.h"
 #include "mongo/db/repl/oplog.h"
-#include "mongo/db/operation_context_impl.h"
-#include "mongo/db/catalog/collection.h"
+#include "mongo/db/repl/repl_coordinator_global.h"
+#include "mongo/db/update_index_data.h"
 #include "mongo/platform/unordered_set.h"
 #include "mongo/util/log.h"
 
 namespace mongo {
```

### `src/mongo/db/ops/update_driver.cpp`

```diff
--- from commit 1f00ffcd22e6 ---
diff --git a/src/mongo/db/ops/update_driver.cpp b/src/mongo/db/ops/update_driver.cpp
index 9492cb13851..672aad85d73 100644
--- a/src/mongo/db/ops/update_driver.cpp
+++ b/src/mongo/db/ops/update_driver.cpp
@@ -388,11 +388,11 @@ namespace mongo {
 
     bool UpdateDriver::modsAffectIndices() const {
         return _affectIndices;
     }
 
-    void UpdateDriver::refreshIndexKeys(const IndexPathSet* indexedFields) {
+    void UpdateDriver::refreshIndexKeys(const UpdateIndexData* indexedFields) {
         _indexedFields = indexedFields;
     }
 
     bool UpdateDriver::logOp() const {
         return _logOp;
```

### `src/mongo/db/ops/update_driver.h`

```diff
--- from commit 1f00ffcd22e6 ---
diff --git a/src/mongo/db/ops/update_driver.h b/src/mongo/db/ops/update_driver.h
index 29a702a1917..0b9fd951cb8 100644
--- a/src/mongo/db/ops/update_driver.h
+++ b/src/mongo/db/ops/update_driver.h
@@ -33,15 +33,15 @@
 
 #include "mongo/base/owned_pointer_vector.h"
 #include "mongo/base/status.h"
 #include "mongo/bson/mutable/document.h"
 #include "mongo/db/field_ref_set.h"
-#include "mongo/db/index_set.h"
 #include "mongo/db/jsobj.h"
 #include "mongo/db/ops/modifier_interface.h"
 #include "mongo/db/ops/modifier_table.h"
 #include "mongo/db/query/canonical_query.h"
+#include "mongo/db/update_index_data.h"
 
 namespace mongo {
 
     class UpdateDriver {
     public:
@@ -105,11 +105,11 @@ namespace mongo {
         size_t numMods() const;
 
         bool isDocReplacement() const;
 
         bool modsAffectIndices() const;
-        void refreshIndexKeys(const IndexPathSet* indexedFields);
+        void refreshIndexKeys(const UpdateIndexData* indexedFields);
 
         bool logOp() const;
         void setLogOp(bool logOp);
 
         ModifierInterface::Options modOptions() const;
@@ -151,11 +151,11 @@ namespace mongo {
 
         // What are the list of fields in the collection over which the update is going to be
         // applied that participate in indices?
         //
         // NOTE: Owned by the collection's info cache!.
-        const IndexPathSet* _indexedFields;
+        const UpdateIndexData* _indexedFields;
 
         //
         // mutable properties after parsing
         //
```

### `src/mongo/db/ops/update_lifecycle.h`

```diff
--- from commit 1f00ffcd22e6 ---
diff --git a/src/mongo/db/ops/update_lifecycle.h b/src/mongo/db/ops/update_lifecycle.h
index 4cb5076aa88..ed5b55d3e5d 100644
--- a/src/mongo/db/ops/update_lifecycle.h
+++ b/src/mongo/db/ops/update_lifecycle.h
@@ -54,11 +54,11 @@ namespace mongo {
         virtual bool canContinue() const = 0;
 
         /**
          * Return a pointer to any indexes if there is a collection.
          */
-        virtual const IndexPathSet* getIndexKeys() const = 0;
+        virtual const UpdateIndexData* getIndexKeys() const = 0;
 
         /**
          * Returns the shard keys as immutable fields
          * Immutable fields in this case mean that they are required to exist, cannot change values
          * and must not be multi-valued (in an array, or an array)
```

### `src/mongo/db/ops/update_lifecycle_impl.cpp`

```diff
--- from commit 1f00ffcd22e6 ---
diff --git a/src/mongo/db/ops/update_lifecycle_impl.cpp b/src/mongo/db/ops/update_lifecycle_impl.cpp
index 5ae625923e5..87648c37403 100644
--- a/src/mongo/db/ops/update_lifecycle_impl.cpp
+++ b/src/mongo/db/ops/update_lifecycle_impl.cpp
@@ -59,11 +59,11 @@ namespace mongo {
     bool UpdateLifecycleImpl::canContinue() const {
         // Collection needs to exist to continue
         return _collection;
     }
 
-    const IndexPathSet* UpdateLifecycleImpl::getIndexKeys() const {
+    const UpdateIndexData* UpdateLifecycleImpl::getIndexKeys() const {
         if (_collection)
             return &_collection->infoCache()->indexKeys();
         return NULL;
     }
```

### `src/mongo/db/ops/update_lifecycle_impl.h`

```diff
--- from commit 1f00ffcd22e6 ---
diff --git a/src/mongo/db/ops/update_lifecycle_impl.h b/src/mongo/db/ops/update_lifecycle_impl.h
index c5a5b15ac67..fa612463757 100644
--- a/src/mongo/db/ops/update_lifecycle_impl.h
+++ b/src/mongo/db/ops/update_lifecycle_impl.h
@@ -50,11 +50,11 @@ namespace mongo {
 
         virtual void setCollection(Collection* collection);
 
         virtual bool canContinue() const;
 
-        virtual const IndexPathSet* getIndexKeys() const;
+        virtual const UpdateIndexData* getIndexKeys() const;
 
         virtual const std::vector<FieldRef*>* getImmutableFields() const;
 
     private:
         Collection* _collection;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
