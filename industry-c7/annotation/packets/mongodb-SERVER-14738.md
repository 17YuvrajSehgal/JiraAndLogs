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
(empty)
```

`d7133440dc8f`

```
(empty)
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
(no diff retrieved)
```

### `src/mongo/db/catalog/collection_info_cache.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/ops/update.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/ops/update_driver.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/ops/update_driver.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/ops/update_lifecycle.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/ops/update_lifecycle_impl.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/ops/update_lifecycle_impl.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
