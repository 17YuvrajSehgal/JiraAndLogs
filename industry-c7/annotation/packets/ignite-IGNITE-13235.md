# Annotation packet: IGNITE-13235  (ignite)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Deadlock in IgniteServiceProcessor

{code:java}
"main" #1 prio=5 os_prio=0 tid=0x00007ff9ac00f000 nid=0x86d in Object.wait() [0x00007ff9b418b000]
   java.lang.Thread.State: WAITING (on object monitor)
	at java.lang.Object.wait(Native Method)
	at java.lang.Object.wait(Object.java:502)
	at org.apache.ignite.internal.util.worker.GridWorker.join(GridWorker.java:242)
	- locked <0x0000000776ee2028> (a java.lang.Object)
	at org.apache.ignite.internal.util.IgniteUtils.join(IgniteUtils.java:5009)
	at org.apache.ignite.internal.processors.service.ServiceDeploymentManager.stopProcessing(ServiceDeploymentManager.java:145)
	at org.apache.ignite.internal.processors.service.IgniteServiceProcessor.stopProcessor(IgniteServiceProcessor.java:261)
	at org.apache.ignite.internal.processors.service.IgniteServiceProcessor.onKernalStop(IgniteServiceProcessor.java:248)
	at org.apache.ignite.internal.IgniteKernal.stop0(IgniteKernal.java:2466)
	at org.apache.ignite.internal.IgniteKernal.stop(IgniteKernal.java:2414)
	at org.apache.ignite.internal.IgnitionEx$IgniteNamedInstance.stop0(IgnitionEx.java:2577)
	- locked <0x0000000776424138> (a org.apache.ignite.internal.IgnitionEx$IgniteNamedInstance)
	at org.apache.ignite.internal.IgnitionEx$IgniteNamedInstance.stop(IgnitionEx.java:2540)
	at org.apache.ignite.internal.IgnitionEx.stop(IgnitionEx.java:333)
	at org.apache.ignite.Ignition.stop(Ignition.java:221)
	at org.apache.ignite.testframework.junits.GridAbstractTest.stopGrid(GridAbstractTest.java:1225)
	at org.apache.ignite.testframework.junits.GridAbstractTest.stopAllGrids(GridAbstractTest.java:1268)
	at org.apache.ignite.testframework.junits.GridAbstractTest.stopAllGrids(GridAbstractTest.java:1246)
	at org.apache.ignite.events.ClusterActivationStartedEventTest.afterTest(ClusterActivationStartedEventTest.java:41)
	at org.apache.ignite.testframework.junits.GridAbstractTest.cleanUpTestEnviroment(GridAbstractTest.java:701)
	at org.apache.ignite.testframework.junits.GridAbstractTest.runTest(GridAbstractTest.java:2165)
	at org.apache.ignite.testframework.junits.GridAbstractTest.access$600(GridAbstractTest.java:172)
	at org.apache.ignite.testframework.junits.GridAbstractTest$2.evaluate(GridAbstractTest.java:207)
	at org.junit.rules.TestWatcher$1.evaluate(TestWatcher.java:55)
	at org.apache.ignite.testframework.junits.SystemPropertiesRule.lambda$methodStatement$1(SystemPropertiesRule.java:109)
	at org.apache.ignite.testframework.junits.SystemPropertiesRule$$Lambda$6/167185492.evaluate(Unknown Source)
	at org.apache.ignite.testframework.junits.DelegatingJUnitStatement.evaluate(DelegatingJUnitStatement.java:48)
	at org.junit.rules.RunRules.evaluate(RunRules.java:20)
	at org.junit.runners.ParentRunner.runLeaf(ParentRunner.java:325)
	at org.junit.runners.BlockJUnit4ClassRunner.runChild(BlockJUnit4ClassRunner.java:78)
	at org.junit.runners.BlockJUnit4ClassRunner.runChild(BlockJUnit4ClassRunner.java:57)
	at org.junit.runners.ParentRunner$3.run(ParentRunner.java:290)
	at org.junit.runners.ParentRunner$1.schedule(ParentRunner.java:71)
	at org.junit.runners.ParentRunner.runChildren(ParentRunner.java:288)
	at org.junit.runners.ParentRunner.access$000(ParentRunner.java:58)
	at org.junit.runners.ParentRunner$2.evaluate(ParentRunner.java:268)
	at org.apache.ignite.testframework.junits.GridAbstractTest.evaluateInsideFixture(GridAbstractTest.java:2669)
	at org.apache.ignite.testframework.junits.GridAbstractTest.access$500(GridAbstractTest.java:172)
	at org.apache.ignite.testframework.junits.GridAbstractTest$BeforeFirstAndAfterLastTestRule$1.evaluate(GridAbstractTest.java:2649)
	at org.apache.ignite.testframework.junits.SystemPropertiesRule.lambda$classStatement$0(SystemPropertiesRule.java:93)
	at org.apache.ignite.testframework.junits.SystemPropertiesRule$$Lambda$2/1879492184.evaluate(Unknown Source)
	at org.apache.ignite.testframework.junits.DelegatingJUnitStatement.evaluate(DelegatingJUnitStatement.java:48)
	at org.junit.rules.RunRules.evaluate(RunRules.java:20)
	at org.junit.runners.ParentRunner.run(ParentRunner.java:363)
	at org.junit.runner.JUnitCore.run(JUnitCore.java:137)
	at com.intellij.junit4.JUnit4IdeaTestRunner.startRunnerWithArgs(JUnit4IdeaTestRunner.java:68)
	at com.intellij.rt.junit.IdeaTestRunner$Repeater.startRunnerWithArgs(IdeaTestRunner.java:40)
	at com.intellij.rt.junit.JUnitStarter.prepareStreamsAndStart(JUnitStarter.java:230)
	at com.intellij.rt.junit.JUnitStarter.main(JUnitStarter.java:58)
{code}
{code:java}
 
"services-deployment-worker-#3503%events.ClusterActivationStartedEventTest0%" #4171 prio=5 os_prio=0 tid=0x00007ff89810e800 nid=0x1b7c waiting on condition [0x00007ff97f0f5000] java.lang.Thread.State: WAITING (parking) at sun.misc.Unsafe.park(Native Method) - parking to wait for <0x0000000776ee2230> (a java.util.concurrent.locks.ReentrantReadWriteLock$NonfairSync) at java.util.concurrent.locks.LockSupport.park(LockSupport.java:175) at java.util.concurrent.locks.AbstractQueuedSynchronizer.parkAndCheckInterrupt(AbstractQueuedSynchronizer.java:836) at java.util.concurrent.locks.AbstractQueuedSynchronizer.acquireQueued(AbstractQueuedSynchronizer.java:870) at java.util.concurrent.locks.AbstractQueuedSynchronizer.acquire(AbstractQueuedSynchronizer.java:1199) at java.util.concurrent.locks.ReentrantReadWriteLock$WriteLock.lock(ReentrantReadWriteLock.java:943) at org.apache.ignite.internal.processors.service.IgniteServiceProcessor.onDeActivate(IgniteServiceProcessor.java:405) at org.apache.ignite.internal.processors.service.ServiceDeploymentTask.init(ServiceDeploymentTask.java:176) at org.apache.ignite.internal.processors.service.ServiceDeploymentManager$ServicesDeploymentWorker.body(ServiceDeploymentManager.java:474) at org.apache.ignite.internal.util.worker.GridWorker.run(GridWorker.java:119) at java.lang.Thread.run(Thread.java:748)
{code}
```

## Fix commit message(s)

`aa4e8f7e097a`

```
IGNITE-13235 Fix of deadlock in IgniteServiceProcessor. - Fixes #8009.

Signed-off-by: Sergey Chugunov <sergey.chugunov@gmail.com>
```

## Files the fix changed

Snapshot holds 6,273 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `modules/core/src/main/java/org/apache/ignite/internal/processors/service/IgniteServiceProcessor.java`

## The fix diff

### `modules/core/src/main/java/org/apache/ignite/internal/processors/service/IgniteServiceProcessor.java`

```diff
diff --git a/modules/core/src/main/java/org/apache/ignite/internal/processors/service/IgniteServiceProcessor.java b/modules/core/src/main/java/org/apache/ignite/internal/processors/service/IgniteServiceProcessor.java
index 79aa57901b..2e4dcec8ec 100644
--- a/modules/core/src/main/java/org/apache/ignite/internal/processors/service/IgniteServiceProcessor.java
+++ b/modules/core/src/main/java/org/apache/ignite/internal/processors/service/IgniteServiceProcessor.java
@@ -40,10 +40,11 @@ import java.util.concurrent.TimeUnit;
 import java.util.concurrent.locks.ReentrantReadWriteLock;
 import java.util.stream.Collectors;
 import java.util.stream.Stream;
 import org.apache.ignite.IgniteCheckedException;
 import org.apache.ignite.IgniteException;
+import org.apache.ignite.IgniteInterruptedException;
 import org.apache.ignite.cluster.ClusterGroup;
 import org.apache.ignite.cluster.ClusterNode;
 import org.apache.ignite.configuration.DeploymentMode;
 import org.apache.ignite.configuration.IgniteConfiguration;
 import org.apache.ignite.events.DiscoveryEvent;
@@ -415,11 +416,18 @@ public class IgniteServiceProcessor extends ServiceProcessorAdapter implements I
      * Invokes from services deployment worker.
      * <p/>
      * {@inheritDoc}
      */
     @Override public void onDeActivate(GridKernalContext kctx) {
-        opsLock.writeLock().lock();
+        try {
+            opsLock.writeLock().lockInterruptibly();
+        }
+        catch (InterruptedException e) {
+            Thread.currentThread().interrupt();
+
+            throw new IgniteInterruptedException(e);
+        }
 
         try {
             if (log.isDebugEnabled()) {
                 log.debug("DeActivate service processor [nodeId=" + ctx.localNodeId() +
                     " topVer=" + ctx.discovery().topologyVersionEx() + " ]");
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
