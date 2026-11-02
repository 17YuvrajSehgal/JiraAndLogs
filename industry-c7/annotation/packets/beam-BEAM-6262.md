# Annotation packet: BEAM-6262  (beam)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
KinesisIO - ShardReadersPool - Unexpected exception occurred

While reading a stream with limited number of records or time it throws an exception in the end. Though, it seems that there is no data loss, so it's a minor issue.

{noformat}
INFO: Creating new reader using [Checkpoint AT_TIMESTAMP for stream apache-beam, shard shardId-000000000002: null, Checkpoint AT_TIMESTAMP for stream apache-beam, shard shardId-000000000001: null]
Dec 18, 2018 6:41:44 PM org.apache.beam.sdk.io.kinesis.KinesisReader start
INFO: Starting reader using [Checkpoint AT_TIMESTAMP for stream apache-beam, shard shardId-000000000002: null, Checkpoint AT_TIMESTAMP for stream apache-beam, shard shardId-000000000001: null]
Dec 18, 2018 6:41:46 PM org.apache.beam.sdk.io.kinesis.ShardReadersPool stop
INFO: Closing shard iterators pool
Dec 18, 2018 6:41:46 PM org.apache.beam.sdk.io.kinesis.ShardReadersPool readLoop
SEVERE: Unexpected exception occurred
java.lang.RuntimeException: Not retryable client failure
	at org.apache.beam.sdk.io.kinesis.SimplifiedKinesisClient.wrapExceptions(SimplifiedKinesisClient.java:225)
	at org.apache.beam.sdk.io.kinesis.SimplifiedKinesisClient.getRecords(SimplifiedKinesisClient.java:134)
	at org.apache.beam.sdk.io.kinesis.SimplifiedKinesisClient.getRecords(SimplifiedKinesisClient.java:119)
	at org.apache.beam.sdk.io.kinesis.ShardRecordsIterator.fetchRecords(ShardRecordsIterator.java:86)
	at org.apache.beam.sdk.io.kinesis.ShardRecordsIterator.readNextBatch(ShardRecordsIterator.java:76)
	at org.apache.beam.sdk.io.kinesis.ShardReadersPool.readLoop(ShardReadersPool.java:123)
	at org.apache.beam.sdk.io.kinesis.ShardReadersPool.lambda$startReadingShards$0(ShardReadersPool.java:114)
	at java.util.concurrent.Executors$RunnableAdapter.call(Executors.java:511)
	at java.util.concurrent.FutureTask.run(FutureTask.java:266)
	at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1149)
	at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:624)
	at java.lang.Thread.run(Thread.java:748)
Caused by: com.amazonaws.AbortedException: 
	at com.amazonaws.internal.SdkFilterInputStream.abortIfNeeded(SdkFilterInputStream.java:53)
	at com.amazonaws.internal.SdkFilterInputStream.read(SdkFilterInputStream.java:81)
	at com.amazonaws.event.ProgressInputStream.read(ProgressInputStream.java:180)
	at com.fasterxml.jackson.dataformat.cbor.CBORParserBootstrapper.ensureLoaded(CBORParserBootstrapper.java:196)
	at com.fasterxml.jackson.dataformat.cbor.CBORParserBootstrapper.constructParser(CBORParserBootstrapper.java:90)
	at com.fasterxml.jackson.dataformat.cbor.CBORFactory._createParser(CBORFactory.java:350)
	at com.fasterxml.jackson.dataformat.cbor.CBORFactory.createParser(CBORFactory.java:287)
	at com.fasterxml.jackson.dataformat.cbor.CBORFactory.createParser(CBORFactory.java:26)
	at com.amazonaws.http.JsonResponseHandler.handle(JsonResponseHandler.java:109)
	at com.amazonaws.http.JsonResponseHandler.handle(JsonResponseHandler.java:43)
	at com.amazonaws.http.response.AwsResponseHandlerAdapter.handle(AwsResponseHandlerAdapter.java:70)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.handleResponse(AmazonHttpClient.java:1554)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.executeOneRequest(AmazonHttpClient.java:1272)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.executeHelper(AmazonHttpClient.java:1056)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.doExecute(AmazonHttpClient.java:743)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.executeWithTimer(AmazonHttpClient.java:717)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.execute(AmazonHttpClient.java:699)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.access$500(AmazonHttpClient.java:667)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutionBuilderImpl.execute(AmazonHttpClient.java:649)
	at com.amazonaws.http.AmazonHttpClient.execute(AmazonHttpClient.java:513)
	at com.amazonaws.services.kinesis.AmazonKinesisClient.doInvoke(AmazonKinesisClient.java:2276)
	at com.amazonaws.services.kinesis.AmazonKinesisClient.invoke(AmazonKinesisClient.java:2252)
	at com.amazonaws.services.kinesis.AmazonKinesisClient.executeGetRecords(AmazonKinesisClient.java:1062)
	at com.amazonaws.services.kinesis.AmazonKinesisClient.getRecords(AmazonKinesisClient.java:1038)
	at org.apache.beam.sdk.io.kinesis.SimplifiedKinesisClient.lambda$getRecords$2(SimplifiedKinesisClient.java:137)
	at org.apache.beam.sdk.io.kinesis.SimplifiedKinesisClient.wrapExceptions(SimplifiedKinesisClient.java:210)
	... 11 more
{noformat}
```

## Fix commit message(s)

`72486020e519`

```
[BEAM-6262] KinesisIO - gracefully shutdown executor service
```

## Files the fix changed

Snapshot holds 2,652 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `sdks/java/io/kinesis/src/main/java/org/apache/beam/sdk/io/kinesis/ShardReadersPool.java`

## The fix diff

### `sdks/java/io/kinesis/src/main/java/org/apache/beam/sdk/io/kinesis/ShardReadersPool.java`

```diff
diff --git a/sdks/java/io/kinesis/src/main/java/org/apache/beam/sdk/io/kinesis/ShardReadersPool.java b/sdks/java/io/kinesis/src/main/java/org/apache/beam/sdk/io/kinesis/ShardReadersPool.java
index a02caf07252..86fda0a4810 100644
--- a/sdks/java/io/kinesis/src/main/java/org/apache/beam/sdk/io/kinesis/ShardReadersPool.java
+++ b/sdks/java/io/kinesis/src/main/java/org/apache/beam/sdk/io/kinesis/ShardReadersPool.java
@@ -42,10 +42,11 @@ import org.slf4j.LoggerFactory;
  */
 class ShardReadersPool {
 
   private static final Logger LOG = LoggerFactory.getLogger(ShardReadersPool.class);
   private static final int DEFAULT_CAPACITY_PER_SHARD = 10_000;
+  private static final int ATTEMPTS_TO_SHUTDOWN = 3;
 
   /**
    * Executor service for running the threads that read records from shards handled by this pool.
    * Each thread runs the {@link ShardReadersPool#readLoop(ShardRecordsIterator)} method and handles
    * exactly one shard.
@@ -170,21 +171,33 @@ class ShardReadersPool {
   }
 
   void stop() {
     LOG.info("Closing shard iterators pool");
     poolOpened.set(false);
-    executorService.shutdownNow();
-    boolean isShutdown = false;
-    int attemptsLeft = 3;
-    while (!isShutdown && attemptsLeft-- > 0) {
+    executorService.shutdown();
+    awaitTermination();
+    if (!executorService.isTerminated()) {
+      LOG.warn(
+          "Executor service was not completely terminated after {} attempts, trying to forcibly stop it.",
+          ATTEMPTS_TO_SHUTDOWN);
+      executorService.shutdownNow();
+      awaitTermination();
+    }
+  }
+
+  private void awaitTermination() {
+    int attemptsLeft = ATTEMPTS_TO_SHUTDOWN;
+    boolean isTerminated = executorService.isTerminated();
+
+    while (!isTerminated && attemptsLeft-- > 0) {
       try {
-        isShutdown = executorService.awaitTermination(10, TimeUnit.SECONDS);
+        isTerminated = executorService.awaitTermination(10, TimeUnit.SECONDS);
       } catch (InterruptedException e) {
         LOG.error("Interrupted while waiting for the executor service to shutdown");
         throw new RuntimeException(e);
       }
-      if (!isShutdown && attemptsLeft > 0) {
+      if (!isTerminated && attemptsLeft > 0) {
         LOG.warn(
             "Executor service is taking long time to shutdown, will retry. {} attempts left",
             attemptsLeft);
       }
     }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
