# Annotation packet: GEODE-440  (geode)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
CI failure: RangeIndexAPIJUnitTest.testQueryMethod_2

{noformat}
java.lang.NullPointerException
	at com.gemstone.gemfire.cache.query.internal.index.CompactRangeIndex.evaluateEntry(CompactRangeIndex.java:953)
	at com.gemstone.gemfire.cache.query.internal.index.CompactRangeIndex.addToResultsFromEntries(CompactRangeIndex.java:889)
	at com.gemstone.gemfire.cache.query.internal.index.CompactRangeIndex.addToResultsFromEntries(CompactRangeIndex.java:722)
	at com.gemstone.gemfire.cache.query.internal.index.CompactRangeIndex.evaluate(CompactRangeIndex.java:611)
	at com.gemstone.gemfire.cache.query.internal.index.CompactRangeIndex.lockedQueryPrivate(CompactRangeIndex.java:483)
	at com.gemstone.gemfire.cache.query.internal.index.CompactRangeIndex.lockedQuery(CompactRangeIndex.java:1721)
	at com.gemstone.gemfire.cache.query.internal.index.AbstractIndex.query(AbstractIndex.java:336)
	at com.gemstone.gemfire.cache.query.internal.index.RangeIndexAPIJUnitTest.testQueryMethod_2(RangeIndexAPIJUnitTest.java:162)
	at sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
	at sun.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:62)
	at sun.reflect.DelegatingMethodAccessorImpl.invoke(DelegatingMethodAccessorImpl.java:43)
	at java.lang.reflect.Method.invoke(Method.java:497)
	at org.junit.runners.model.FrameworkMethod$1.runReflectiveCall(FrameworkMethod.java:50)
	at org.junit.internal.runners.model.ReflectiveCallable.run(ReflectiveCallable.java:12)
	at org.junit.runners.model.FrameworkMethod.invokeExplosively(FrameworkMethod.java:47)
	at org.junit.internal.runners.statements.InvokeMethod.evaluate(InvokeMethod.java:17)
	at org.junit.internal.runners.statements.RunBefores.evaluate(RunBefores.java:26)
	at org.junit.internal.runners.statements.RunAfters.evaluate(RunAfters.java:27)
	at org.junit.runners.ParentRunner.runLeaf(ParentRunner.java:325)
	at org.junit.runners.BlockJUnit4ClassRunner.runChild(BlockJUnit4ClassRunner.java:78)
	at org.junit.runners.BlockJUnit4ClassRunner.runChild(BlockJUnit4ClassRunner.java:57)
	at org.junit.runners.ParentRunner$3.run(ParentRunner.java:290)
	at org.junit.runners.ParentRunner$1.schedule(ParentRunner.java:71)
	at org.junit.runners.ParentRunner.runChildren(ParentRunner.java:288)
	at org.junit.runners.ParentRunner.access$000(ParentRunner.java:58)
	at org.junit.runners.ParentRunner$2.evaluate(ParentRunner.java:268)
	at org.junit.runners.ParentRunner.run(ParentRunner.java:363)
	at org.gradle.api.internal.tasks.testing.junit.JUnitTestClassExecuter.runTestClass(JUnitTestClassExecuter.java:86)
	at org.gradle.api.internal.tasks.testing.junit.JUnitTestClassExecuter.execute(JUnitTestClassExecuter.java:49)
	at org.gradle.api.internal.tasks.testing.junit.JUnitTestClassProcessor.processTestClass(JUnitTestClassProcessor.java:64)
	at org.gradle.api.internal.tasks.testing.SuiteTestClassProcessor.processTestClass(SuiteTestClassProcessor.java:50)
	at sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
	at sun.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:62)
	at sun.reflect.DelegatingMethodAccessorImpl.invoke(DelegatingMethodAccessorImpl.java:43)
	at java.lang.reflect.Method.invoke(Method.java:497)
	at org.gradle.messaging.dispatch.ReflectionDispatch.dispatch(ReflectionDispatch.java:35)
	at org.gradle.messaging.dispatch.ReflectionDispatch.dispatch(ReflectionDispatch.java:24)
	at org.gradle.messaging.dispatch.ContextClassLoaderDispatch.dispatch(ContextClassLoaderDispatch.java:32)
	at org.gradle.messaging.dispatch.ProxyDispatchAdapter$DispatchingInvocationHandler.invoke(ProxyDispatchAdapter.java:93)
	at com.sun.proxy.$Proxy2.processTestClass(Unknown Source)
	at org.gradle.api.internal.tasks.testing.worker.TestWorker.processTestClass(TestWorker.java:106)
	at sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
	at sun.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:62)
	at sun.reflect.DelegatingMethodAccessorImpl.invoke(DelegatingMethodAccessorImpl.java:43)
	at java.lang.reflect.Method.invoke(Method.java:497)
	at org.gradle.messaging.dispatch.ReflectionDispatch.dispatch(ReflectionDispatch.java:35)
	at org.gradle.messaging.dispatch.ReflectionDispatch.dispatch(ReflectionDispatch.java:24)
	at org.gradle.messaging.remote.internal.hub.MessageHub$Handler.run(MessageHub.java:360)
	at org.gradle.internal.concurrent.DefaultExecutorFactory$StoppableExecutorImpl$1.run(DefaultExecutorFactory.java:64)
	at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1142)
	at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:617)
	at java.lang.Thread.run(Thread.java:745)
{noformat}
```

## Fix commit message(s)

`f8935b3b81e3`

```
[GEODE-440] RangeIndexAPIJUnitTest.testQueryMethod_2 Added a flag to ignore the update in progress calculation for querying
```

## Files the fix changed

Snapshot holds 3,819 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `gemfire-core/src/main/java/com/gemstone/gemfire/cache/query/internal/index/IndexManager.java`

## The fix diff

### `gemfire-core/src/main/java/com/gemstone/gemfire/cache/query/internal/index/IndexManager.java`

```diff
diff --git a/gemfire-core/src/main/java/com/gemstone/gemfire/cache/query/internal/index/IndexManager.java b/gemfire-core/src/main/java/com/gemstone/gemfire/cache/query/internal/index/IndexManager.java
index 0a9b16607c..2c597a8e43 100644
--- a/gemfire-core/src/main/java/com/gemstone/gemfire/cache/query/internal/index/IndexManager.java
+++ b/gemfire-core/src/main/java/com/gemstone/gemfire/cache/query/internal/index/IndexManager.java
@@ -132,10 +132,11 @@ public class IndexManager  {
   public static final String INDEX_ELEMARRAY_THRESHOLD_PROP = "index_elemarray_threshold";
   public static final String INDEX_ELEMARRAY_SIZE_PROP = "index_elemarray_size";
   public static final int INDEX_ELEMARRAY_THRESHOLD = Integer.parseInt(System.getProperty(INDEX_ELEMARRAY_THRESHOLD_PROP,"100"));
   public static final int INDEX_ELEMARRAY_SIZE = Integer.parseInt(System.getProperty(INDEX_ELEMARRAY_SIZE_PROP,"5"));
   public final static AtomicLong SAFE_QUERY_TIME = new AtomicLong(0);
+  public static boolean ENABLE_UPDATE_IN_PROGRESS_INDEX_CALCULATION = true;
   /** The NULL constant */
   public static final Object NULL = new NullToken();
 
   public static TestHook testHook;
 
@@ -203,11 +204,11 @@ public class IndexManager  {
    * Small amounts of false positives are ok as it will have a slight impact on performance
    * @param queryStartTime
    * @param lastModifiedTime
    */
   public static boolean needsRecalculation(long queryStartTime, long lastModifiedTime) {
-    return queryStartTime <= SAFE_QUERY_TIME.get() - queryStartTime + lastModifiedTime;
+    return ENABLE_UPDATE_IN_PROGRESS_INDEX_CALCULATION && queryStartTime <= SAFE_QUERY_TIME.get() - queryStartTime + lastModifiedTime;
   }
   
   /**
    * 
    * @param value
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
