# Annotation packet: SERVER-21636  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
read_majority.js broken in noPassthrough_WT

The [read_majority.js|https://evergreen.mongodb.com/task/mongodb_mongo_master_enterprise_linux_64_amazon_ami_noPassthrough_WT_6f2a7e6cfb69e186ee2d5ca8653dda5bf0633ef7_15_11_20_23_29_04] test is broken in noPassthrough_WT with the following error:

{noformat}
[js_test:read_majority] 2015-11-21T17:01:06.493-0500 2015-11-21T17:01:06.488-0500 E QUERY    [thread1] Error: assert.soon failed, msg:could not kill an op that was waiting for a snapshot :
[js_test:read_majority] 2015-11-21T17:01:06.493-0500 doassert@src/mongo/shell/assert.js:15:14
[js_test:read_majority] 2015-11-21T17:01:06.493-0500 assert.soon@src/mongo/shell/assert.js:200:13
[js_test:read_majority] 2015-11-21T17:01:06.493-0500 @jstests/noPassthrough/read_majority.js:50:1
[js_test:read_majority] 2015-11-21T17:01:06.493-0500 @jstests/noPassthrough/read_majority.js:3:2
{noformat}

Happened after [Matt's commit|https://evergreen.mongodb.com/version/mongodb_mongo_master_463993d94b20b130c8dd1523da5688a561c07862].

Not sure why we should not be able to kill operations, which are blocked on snapshot creation other than that they sleep on condition variables and we might have killed the snapshot thread, so cc [~redbeard0531].
```

## Fix commit message(s)

`160de93cc00a`

```
SERVER-21636 fix testing snapshots in isolation
```

## Files the fix changed

Snapshot holds 8,529 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/dbcommands.cpp`

## The fix diff

### `src/mongo/db/dbcommands.cpp`

```diff
diff --git a/src/mongo/db/dbcommands.cpp b/src/mongo/db/dbcommands.cpp
index 9bd3abddc95..f328296e347 100644
--- a/src/mongo/db/dbcommands.cpp
+++ b/src/mongo/db/dbcommands.cpp
@@ -1388,11 +1388,11 @@ bool Command::run(OperationContext* txn,
             if ((replCoord->getReplicationMode() ==
                      repl::ReplicationCoordinator::Mode::modeReplSet ||
                  testingSnapshotBehaviorInIsolation) &&
                 readConcernArgs.getLevel() == repl::ReadConcernLevel::kMajorityReadConcern) {
                 // ReadConcern Majority is not supported in ProtocolVersion 0.
-                if (!replCoord->isV1ElectionProtocol()) {
+                if (!testingSnapshotBehaviorInIsolation && !replCoord->isV1ElectionProtocol()) {
                     auto result = appendCommandStatus(
                         inPlaceReplyBob,
                         {ErrorCodes::ReadConcernMajorityNotEnabled,
                          str::stream() << "Replica sets running protocol version 0 do not support "
                                           "readConcern: majority"});
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
