# Annotation packet: GEODE-8079  (geode)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
AttributesMutator Should Validate AsyncEventQueue/GatewaySender Type

By design, a parallel {{gateway-sender}} can't be attached to a {{REPLICATE}} region.
 While working on on GEODE-8029 I've found that the above fact is correctly validated when creating or initialising the region, but totally ignored when updating the region through the {{AttributesMutator}} class.
 Altering a {{REPLICATE}} region to dispatch events through a parallel {{gateway-sender}} results in cryptic errors while putting entries into the region afterwards:
{noformat}
[vm1] [warn 2020/05/06 10:34:09.638 IST <RMI TCP Connection(1)-127.0.0.1> tid=0x13] GatewaySender: Not queuing the event GatewaySenderEventImpl[id=EventID[id=18 bytes;threadID=0x10062|2;sequenceID=91;bucketId=98];action=0;operation=CREATE;region=/TestRegion;key=Key90;value=Value90;valueIsObject=1;numberOfParts=9;callbackArgument=GatewaySenderEventCallbackArgument [originalCallbackArg=null;originatingSenderId=1;recipientGatewayReceivers={2}];possibleDuplicate=false;creationTime=1588757649638;shadowKey=-1;timeStamp=1588757649638;acked=false;dispatched=false;bucketId=98;isConcurrencyConflict=false], as the region for which this event originated is not yet configured in the GatewaySender

[vm1] [warn 2020/05/06 10:34:09.638 IST <RMI TCP Connection(1)-127.0.0.1> tid=0x13] GatewaySender: Not queuing the event GatewaySenderEventImpl[id=EventID[id=18 bytes;threadID=0x10063|2;sequenceID=92;bucketId=99];action=0;operation=CREATE;region=/TestRegion;key=Key91;value=Value91;valueIsObject=1;numberOfParts=9;callbackArgument=GatewaySenderEventCallbackArgument [originalCallbackArg=null;originatingSenderId=1;recipientGatewayReceivers={2}];possibleDuplicate=false;creationTime=1588757649638;shadowKey=-1;timeStamp=1588757649638;acked=false;dispatched=false;bucketId=99;isConcurrencyConflict=false], as the region for which this event originated is not yet configured in the GatewaySender

[vm1] [warn 2020/05/06 10:34:09.639 IST <RMI TCP Connection(1)-127.0.0.1> tid=0x13] GatewaySender: Not queuing the event GatewaySenderEventImpl[id=EventID[id=18 bytes;threadID=0x10064|2;sequenceID=93;bucketId=100];action=0;operation=CREATE;region=/TestRegion;key=Key92;value=Value92;valueIsObject=1;numberOfParts=9;callbackArgument=GatewaySenderEventCallbackArgument [originalCallbackArg=null;originatingSenderId=1;recipientGatewayReceivers={2}];possibleDuplicate=false;creationTime=1588757649638;shadowKey=-1;timeStamp=1588757649638;acked=false;dispatched=false;bucketId=100;isConcurrencyConflict=false], as the region for which this event originated is not yet configured in the GatewaySender

[vm1] [warn 2020/05/06 10:34:09.639 IST <RMI TCP Connection(1)-127.0.0.1> tid=0x13] GatewaySender: Not queuing the event GatewaySenderEventImpl[id=EventID[id=18 bytes;threadID=0x10065|2;sequenceID=94;bucketId=101];action=0;operation=CREATE;region=/TestRegion;key=Key93;value=Value93;valueIsObject=1;numberOfParts=9;callbackArgument=GatewaySenderEventCallbackArgument [originalCallbackArg=null;originatingSenderId=1;recipientGatewayReceivers={2}];possibleDuplicate=false;creationTime=1588757649639;shadowKey=-1;timeStamp=1588757649639;acked=false;dispatched=false;bucketId=101;isConcurrencyConflict=false], as the region for which this event originated is not yet configured in the GatewaySender
{noformat}
When done from {{GFSH}}, on the other hand, the server doesn't even start up after altering the region as the {{cluster-configuration}} is invalid:
{noformat}
gfsh -e "connect" -e "create region --name=TestRegion --type=REPLICATE"

    Member      | Status | Message
--------------- | ------ | -------------------------------------------------
cluster1-server | OK     | Region "/TestRegion" created on "cluster1-server"
Cluster configuration for group 'cluster' is updated.


gfsh -e "connect" -e "create gateway-sender --id=MyGateway --remote-distributed-system-id=2 --parallel=true"

    Member      | Status | Message
--------------- | ------ | ------------------------------------------------------
cluster1-server | OK     | GatewaySender "MyGateway" created on "cluster1-server"
Cluster configuration for group 'cluster' is updated.


gfsh -e "connect" -e "alter region --name=/TestRegion -–gateway-sender-id=MyGateway"

    Member      | Status | Message
--------------- | ------ | -------------------------
cluster1-server | OK     | Region TestRegion altered
Cluster configuration for group 'cluster' is updated.


////// Restart Cluster
[warn 2020/05/06 10:09:07.385 IST <main> tid=0x1] Initialization failed for Region /TestRegion
org.apache.geode.internal.cache.wan.GatewaySenderConfigurationException: Parallel gateway sender MyGateway can not be used with replicated region /TestRegion
	at org.apache.geode.internal.cache.DistributedRegion.preInitialize(DistributedRegion.java:1035)
	at org.apache.geode.internal.cache.GemFireCacheImpl.createVMRegion(GemFireCacheImpl.java:2996)
	at org.apache.geode.internal.cache.GemFireCacheImpl.basicCreateRegion(GemFireCacheImpl.java:2891)
	at org.apache.geode.internal.cache.xmlcache.RegionCreation.createRoot(RegionCreation.java:237)
	at org.apache.geode.internal.cache.xmlcache.CacheCreation.initializeRegions(CacheCreation.java:658)
	at org.apache.geode.internal.cache.xmlcache.CacheCreation.create(CacheCreation.java:592)
	at org.apache.geode.internal.cache.xmlcache.CacheXmlParser.create(CacheXmlParser.java:339)
	at org.apache.geode.internal.cache.GemFireCacheImpl.loadCacheXml(GemFireCacheImpl.java:4096)
	at org.apache.geode.internal.cache.ClusterConfigurationLoader.applyClusterXmlConfiguration(ClusterConfigurationLoader.java:208)
	at org.apache.geode.internal.cache.GemFireCacheImpl.applyJarAndXmlFromClusterConfig(GemFireCacheImpl.java:1409)
	at org.apache.geode.internal.cache.GemFireCacheImpl.initialize(GemFireCacheImpl.java:1374)
	at org.apache.geode.internal.cache.InternalCacheBuilder.create(InternalCacheBuilder.java:191)
	at org.apache.geode.internal.cache.InternalCacheBuilder.create(InternalCacheBuilder.java:158)
	at org.apache.geode.cache.CacheFactory.create(CacheFactory.java:142)
	at org.apache.geode.distributed.internal.DefaultServerLauncherCacheProvider.createCache(DefaultServerLauncherCacheProvider.java:52)
	at org.apache.geode.distributed.ServerLauncher.createCache(ServerLauncher.java:892)
	at org.apache.geode.distributed.ServerLauncher.start(ServerLauncher.java:807)
	at org.apache.geode.distributed.ServerLauncher.run(ServerLauncher.java:737)
	at org.apache.geode.distributed.ServerLauncher.main(ServerLauncher.java:256)
{noformat}
```

## Fix commit message(s)

`78a4fb9bf164`

```
GEODE-8079: Fix DistributedRegion Validations (#5070)

Attaching a parallel gateway-sender or async-event-queue to a
Replicate Region through the AttributesMutator class now throws an
exception instead of wrongly assigning the dispatcher to the region.

- Fixed several warnings.
- Added unit and distributed tests.
- Refactored WanValidationsDUnitTest.
- Replaced usages of 'junit.Assert' by 'assertj'.
- Changed test methods to use more meaningful names.
- Removed references to old ids used by another ticketing system.
```

## Files the fix changed

Snapshot holds 4,745 non-test source files. The fix changed 8 file(s); 2 of them are non-test source files (listed below as gold).

- `geode-core/src/main/java/org/apache/geode/internal/cache/DistributedRegion.java`
- `geode-core/src/main/java/org/apache/geode/internal/cache/wan/parallel/ParallelGatewaySenderQueue.java`

## The fix diff

### `geode-core/src/main/java/org/apache/geode/internal/cache/DistributedRegion.java`

```diff
diff --git a/geode-core/src/main/java/org/apache/geode/internal/cache/DistributedRegion.java b/geode-core/src/main/java/org/apache/geode/internal/cache/DistributedRegion.java
index dd73b20776..63c0d76c60 100755
--- a/geode-core/src/main/java/org/apache/geode/internal/cache/DistributedRegion.java
+++ b/geode-core/src/main/java/org/apache/geode/internal/cache/DistributedRegion.java
@@ -13,10 +13,13 @@
  * the License.
  */
 
 package org.apache.geode.internal.cache;
 
+import static org.apache.geode.cache.asyncqueue.internal.AsyncEventQueueImpl.getAsyncEventQueueIdFromSenderId;
+import static org.apache.geode.cache.asyncqueue.internal.AsyncEventQueueImpl.getSenderIdFromAsyncEventQueueId;
+
 import java.io.IOException;
 import java.io.InputStream;
 import java.util.ArrayList;
 import java.util.Collection;
 import java.util.Collections;
@@ -1011,38 +1014,42 @@ public class DistributedRegion extends LocalRegion implements InternalDistribute
           "This thread has suspended all locking for this region");
     }
     return new DistributedLock(key);
   }
 
-  @Override
-  public void preInitialize() {
-    Set<String> allGatewaySenderIds = getAllGatewaySenderIds();
-
-    if (!allGatewaySenderIds.isEmpty()) {
-      for (GatewaySender sender : cache.getAllGatewaySenders()) {
-        if (sender.isParallel() && allGatewaySenderIds.contains(sender.getId())) {
-          // Once decided to support REPLICATED regions with parallel
-          // gateway-sender/asynchronous-event-queue, ShadowPartitionedRegionForUserRR should be
-          // called and this validation should be removed.
-          if (sender.getId().contains(AsyncEventQueueImpl.ASYNC_EVENT_QUEUE_PREFIX)) {
-            throw new AsyncEventQueueConfigurationException(
-                String.format(
-                    "Parallel Async Event Queue %s can not be used with replicated region %s",
-
-                    AsyncEventQueueImpl.getAsyncEventQueueIdFromSenderId(sender.getId()),
-                    getFullPath()));
-          } else {
-            throw new GatewaySenderConfigurationException(
-                String.format(
-                    "Parallel gateway sender %s can not be used with replicated region %s",
-                    sender.getId(), getFullPath()));
-          }
+  /**
+   * Validates that the GatewaySender/AsyncEventQueue referenced by the {@param asyncDispatcherId}
+   * can be attached to this region; that is, verifies that the dispatcher is not configured as
+   * parallel.
+   *
+   * @param asyncDispatcherId Id of the AsynchronousEventDispatcher to validate.
+   */
+  void validateAsynchronousEventDispatcher(String asyncDispatcherId) {
+    for (GatewaySender sender : getCache().getAllGatewaySenders()) {
+      if (sender.isParallel() && sender.getId().equals(asyncDispatcherId)) {
+        // Once decided to support REPLICATED regions with parallel
+        // gateway-sender/asynchronous-event-queue, ShadowPartitionedRegionForUserRR should be
+        // called and this validation should be removed.
+        if (sender.getId().contains(AsyncEventQueueImpl.ASYNC_EVENT_QUEUE_PREFIX)) {
+          throw new AsyncEventQueueConfigurationException(String.format(
+              "Parallel Async Event Queue %s can not be used with replicated region %s",
+              getAsyncEventQueueIdFromSenderId(sender.getId()), getFullPath()));
+        } else {
+          throw new GatewaySenderConfigurationException(
+              String.format("Parallel Gateway Sender %s can not be used with replicated region %s",
+                  sender.getId(), getFullPath()));
         }
       }
     }
   }
 
+  @Override
+  public void preInitialize() {
+    Set<String> allGatewaySenderIds = getAllGatewaySenderIds();
+    allGatewaySenderIds.forEach(this::validateAsynchronousEventDispatcher);
+  }
+
   /**
    * Called while NOT holding lock on parent's subregions
    *
    * @throws IllegalStateException if region is not compatible with a region in another VM.
    */
@@ -2743,10 +2750,11 @@ public class DistributedRegion extends LocalRegion implements InternalDistribute
     }
   }
 
   @Override
   public void addGatewaySenderId(String gatewaySenderId) {
+    validateAsynchronousEventDispatcher(gatewaySenderId);
     super.addGatewaySenderId(gatewaySenderId);
     new UpdateAttributesProcessor(this).distribute();
     updateSenderIdMonitor();
   }
 
@@ -2757,10 +2765,11 @@ public class DistributedRegion extends LocalRegion implements InternalDistribute
     updateSenderIdMonitor();
   }
 
   @Override
   public void addAsyncEventQueueId(String asyncEventQueueId) {
+    validateAsynchronousEventDispatcher(getSenderIdFromAsyncEventQueueId(asyncEventQueueId));
     super.addAsyncEventQueueId(asyncEventQueueId);
     new UpdateAttributesProcessor(this).distribute();
     updateSenderIdMonitor();
   }
```

### `geode-core/src/main/java/org/apache/geode/internal/cache/wan/parallel/ParallelGatewaySenderQueue.java`

```diff
diff --git a/geode-core/src/main/java/org/apache/geode/internal/cache/wan/parallel/ParallelGatewaySenderQueue.java b/geode-core/src/main/java/org/apache/geode/internal/cache/wan/parallel/ParallelGatewaySenderQueue.java
index 97d64a7e01..aaa84fef39 100644
--- a/geode-core/src/main/java/org/apache/geode/internal/cache/wan/parallel/ParallelGatewaySenderQueue.java
+++ b/geode-core/src/main/java/org/apache/geode/internal/cache/wan/parallel/ParallelGatewaySenderQueue.java
@@ -258,20 +258,18 @@ public class ParallelGatewaySenderQueue implements RegionQueue {
         addShadowPartitionedRegionForUserPR((PartitionedRegion) userRegion);
       } else {
         // Fix for Bug#51491. Once decided to support this configuration we have call
         // addShadowPartitionedRegionForUserRR
         if (this.sender.getId().contains(AsyncEventQueueImpl.ASYNC_EVENT_QUEUE_PREFIX)) {
-          throw new AsyncEventQueueConfigurationException(
-              String.format(
-                  "Parallel Async Event Queue %s can not be used with replicated region %s",
-                  new Object[] {
-                      AsyncEventQueueImpl.getAsyncEventQueueIdFromSenderId(this.sender.getId()),
-                      userRegion.getFullPath()}));
+          throw new AsyncEventQueueConfigurationException(String.format(
+              "Parallel Async Event Queue %s can not be used with replicated region %s",
+              AsyncEventQueueImpl.getAsyncEventQueueIdFromSenderId(this.sender.getId()),
+              userRegion.getFullPath()));
         }
         throw new GatewaySenderConfigurationException(
-            String.format("Parallel gateway sender %s can not be used with replicated region %s",
-                new Object[] {this.sender.getId(), userRegion.getFullPath()}));
+            String.format("Parallel Gateway Sender %s can not be used with replicated region %s",
+                this.sender.getId(), userRegion.getFullPath()));
       }
     }
 
     buckToDispatchLock = new StoppableReentrantLock(sender.getCancelCriterion());
     regionToDispatchedKeysMapEmpty = buckToDispatchLock.newCondition();
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
