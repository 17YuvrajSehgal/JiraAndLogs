# Annotation packet: SERVER-15512  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
resync.js

http://buildlogs.mongodb.org/MCI_windows-64-debug/builds/108438/test/replicasets_0/resync.js

{code}
 m31001| 2014-10-02T03:15:02.123+0000 I REPLSETS [rsSync] initial sync pending
 m31001| 2014-10-02T03:15:02.124+0000 I REPLSETS [rsSync] no valid sync sources found in current replset to do an initial sync
ReplSetTest awaitReplication: waiting for secondary #1, WIN-LPG54MQP00S:31001, to have an oplog built
ReplSetTest awaitReplication: checking secondaries against timestamp Timestamp(1412219668, 998)
ReplSetTest awaitReplication: checking secondary #1: WIN-LPG54MQP00S:31001
ReplSetTest awaitReplication: waiting for secondary #1, WIN-LPG54MQP00S:31001, to have an oplog built
ReplSetTest awaitReplication: checking secondaries against timestamp Timestamp(1412219668, 998)
ReplSetTest awaitReplication: checking secondary #1: WIN-LPG54MQP00S:31001
ReplSetTest awaitReplication: waiting for secondary #1, WIN-LPG54MQP00S:31001, to have an oplog built
ReplSetTest awaitReplication: checking secondaries against timestamp Timestamp(1412219668, 998)
ReplSetTest awaitReplication: checking secondary #1: WIN-LPG54MQP00S:31001
ReplSetTest awaitReplication: waiting for secondary #1, WIN-LPG54MQP00S:31001, to have an oplog built
assert.soon failed, msg:awaiting replication
Error: assert.soon failed, msg:awaiting replication
    at Error (<anonymous>)
    at doassert (src/mongo/shell/assert.js:11:14)
    at Function.assert.soon (src/mongo/shell/assert.js:181:51)
    at ReplSetTest.awaitReplication (src/mongo/shell/replsettest.js:507:12)
    at C:\data\mci\shell\src\jstests\replsets\resync.js:55:10
2014-10-02T03:15:04.335+0000 I QUERY    Error: assert.soon failed, msg:awaiting replication
{code}

Nothing else obviously useful from the logs yet.
```

## Fix commit message(s)

`8f349cc6f6c3`

```
(empty)
```

## Files the fix changed

Snapshot holds 8,739 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/repl/rs_sync.cpp`

## The fix diff

### `src/mongo/db/repl/rs_sync.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
