# Annotation packet: SERVER-15763  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Ensure readable state while draining and becoming primary

Check to make sure that isMaster returns something readable, {{ismaster:true, secondary:false }}, when transitioning to primary, during draining stage esp.
```

## Fix commit message(s)

`ede05b3fc832`

```
SERVER-15763 Report issecondary:true while newly elected primary drains unapplied oplog entries.

Such nodes already report ismaster:false, so need to report issecondary:true to
indicate that they are ready to accept reads.
```

## Files the fix changed

Snapshot holds 8,767 non-test source files. The fix changed 3 file(s); 2 of them are non-test source files (listed below as gold).

- `src/mongo/db/repl/repl_coordinator_impl.cpp`
- `src/mongo/db/repl/repl_coordinator_test_fixture.cpp`

## The fix diff

### `src/mongo/db/repl/repl_coordinator_impl.cpp`

```diff
diff --git a/src/mongo/db/repl/repl_coordinator_impl.cpp b/src/mongo/db/repl/repl_coordinator_impl.cpp
index ebf97645121..0a7fef26e76 100644
--- a/src/mongo/db/repl/repl_coordinator_impl.cpp
+++ b/src/mongo/db/repl/repl_coordinator_impl.cpp
@@ -1214,12 +1214,13 @@ namespace {
                        this,
                        stdx::placeholders::_1,
                        response));
         _replExecutor.wait(cbh.getValue());
         if (isWaitingForApplierToDrain()) {
-            // Report NotMaster when draining the applier.
+            // Report that we are secondary to ismaster callers until drain completes.
             response->setIsMaster(false);
+            response->setIsSecondary(true);
         }
     }
 
     void ReplicationCoordinatorImpl::_fillIsMasterForReplSet_finish(
             const ReplicationExecutor::CallbackData& cbData, IsMasterResponse* response) {
```

### `src/mongo/db/repl/repl_coordinator_test_fixture.cpp`

```diff
diff --git a/src/mongo/db/repl/repl_coordinator_test_fixture.cpp b/src/mongo/db/repl/repl_coordinator_test_fixture.cpp
index bd614f15b34..5d6195ef7d0 100644
--- a/src/mongo/db/repl/repl_coordinator_test_fixture.cpp
+++ b/src/mongo/db/repl/repl_coordinator_test_fixture.cpp
@@ -31,10 +31,11 @@
 #include "mongo/platform/basic.h"
 
 #include "mongo/db/repl/repl_coordinator_test_fixture.h"
 
 #include "mongo/db/operation_context_noop.h"
+#include "mongo/db/repl/is_master_response.h"
 #include "mongo/db/repl/network_interface_mock.h"
 #include "mongo/db/repl/repl_coordinator_external_state_mock.h"
 #include "mongo/db/repl/repl_coordinator_impl.h"
 #include "mongo/db/repl/repl_settings.h"
 #include "mongo/db/repl/repl_set_heartbeat_args.h"
@@ -205,11 +206,23 @@ namespace {
                 net->blackHole(noi);
             }
             net->runReadyNetworkOperations();
             getNet()->exitNetwork();
         }
+        ASSERT(replCoord->isWaitingForApplierToDrain());
+        ASSERT(replCoord->getCurrentMemberState().primary()) <<
+            replCoord->getCurrentMemberState().toString();
+
+        IsMasterResponse imResponse;
+        replCoord->fillIsMasterForReplSet(&imResponse);
+        ASSERT_FALSE(imResponse.isMaster()) << imResponse.toBSON().toString();
+        ASSERT_TRUE(imResponse.isSecondary()) << imResponse.toBSON().toString();
         replCoord->signalDrainComplete();
+        replCoord->fillIsMasterForReplSet(&imResponse);
+        ASSERT_TRUE(imResponse.isMaster()) << imResponse.toBSON().toString();
+        ASSERT_FALSE(imResponse.isSecondary()) << imResponse.toBSON().toString();
+
         ASSERT(replCoord->getCurrentMemberState().primary()) <<
             replCoord->getCurrentMemberState().toString();
     }
 
     void ReplCoordTest::simulateStepDownOnIsolation() {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
