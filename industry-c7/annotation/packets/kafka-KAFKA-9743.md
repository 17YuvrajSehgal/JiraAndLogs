# Annotation packet: KAFKA-9743  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
StreamTask could fail to close during HandleNewAssignment

We found this particular bug from happening in soak:

[2020-03-20T16:12:02-07:00] (streams-soak-trunk-eos_soak_i-026133a325ea91147_streamslog) [2020-03-20 23:12:01,534] ERROR [stream-soak-test-7ece4c7d-f528-4c92-93e2-9b32f1f722b1-StreamThread-2] stream-thread [stream-soak-test-7ece4c7d-f528-4c92-93e2-9b32f1f722b1-StreamThread-2] Encountered the following exception during processing and the thread is going to shut down:  (org.apache.kafka.streams.processor.internals.StreamThread)

[2020-03-20T16:12:02-07:00] (streams-soak-trunk-eos_soak_i-026133a325ea91147_streamslog) java.lang.IllegalStateException: RocksDB metrics recorder for store "KSTREAM-AGGREGATE-STATE-STORE-0000000040" of task 2_2 has already been added. This is a bug in Kafka Streams.

        at org.apache.kafka.streams.state.internals.metrics.RocksDBMetricsRecordingTrigger.addMetricsRecorder(RocksDBMetricsRecordingTrigger.java:30)

        at org.apache.kafka.streams.state.internals.metrics.RocksDBMetricsRecorder.addStatistics(RocksDBMetricsRecorder.java:98)

        at org.apache.kafka.streams.state.internals.RocksDBStore.maybeSetUpMetricsRecorder(RocksDBStore.java:207)

        at org.apache.kafka.streams.state.internals.RocksDBStore.openDB(RocksDBStore.java:193)

        at org.apache.kafka.streams.state.internals.RocksDBStore.init(RocksDBStore.java:231)

        at org.apache.kafka.streams.state.internals.WrappedStateStore.init(WrappedStateStore.java:48)

        at org.apache.kafka.streams.state.internals.ChangeLoggingKeyValueBytesStore.init(ChangeLoggingKeyValueBytesStore.java:44)

        at org.apache.kafka.streams.state.internals.WrappedStateStore.init(WrappedStateStore.java:48)

        at org.apache.kafka.streams.state.internals.CachingKeyValueStore.init(CachingKeyValueStore.java:58)

        at org.apache.kafka.streams.state.internals.WrappedStateStore.init(WrappedStateStore.java:48)

        at org.apache.kafka.streams.state.internals.MeteredKeyValueStore.lambda$init$0(MeteredKeyValueStore.java:101)

        at org.apache.kafka.streams.processor.internals.metrics.StreamsMetricsImpl.maybeMeasureLatency(StreamsMetricsImpl.java:801)

        at org.apache.kafka.streams.state.internals.MeteredKeyValueStore.init(MeteredKeyValueStore.java:101)

        at org.apache.kafka.streams.processor.internals.StateManagerUtil.registerStateStores(StateManagerUtil.java:81)

        at org.apache.kafka.streams.processor.internals.StreamTask.initializeIfNeeded(StreamTask.java:191)

        at org.apache.kafka.streams.processor.internals.TaskManager.tryToCompleteRestoration(TaskManager.java:329)

        at org.apache.kafka.streams.processor.internals.StreamThread.runOnce(StreamThread.java:587)

        at org.apache.kafka.streams.processor.internals.StreamThread.runLoop(StreamThread.java:501)

        at org.apache.kafka.streams.processor.internals.StreamThread.run(StreamThread.java:475)

 

Which could bring the entire instance down. The bug was that if we fail to do the commit during task close section, the actual `closeClean` call could not be triggered.
```

## Fix commit message(s)

`cc7061410567`

```
KAFKA-9743: Catch commit offset exception to eventually close dirty tasks (#8327)

Reviewers: Guozhang Wang <guozhang@confluent.io>, Matthias J. Sax <matthias@confluent.io>
```

## Files the fix changed

Snapshot holds 1,865 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `streams/src/main/java/org/apache/kafka/streams/processor/internals/TaskManager.java`

## The fix diff

### `streams/src/main/java/org/apache/kafka/streams/processor/internals/TaskManager.java`

```diff
diff --git a/streams/src/main/java/org/apache/kafka/streams/processor/internals/TaskManager.java b/streams/src/main/java/org/apache/kafka/streams/processor/internals/TaskManager.java
index d45c4e9af5..192962347e 100644
--- a/streams/src/main/java/org/apache/kafka/streams/processor/internals/TaskManager.java
+++ b/streams/src/main/java/org/apache/kafka/streams/processor/internals/TaskManager.java
@@ -235,14 +235,23 @@ public class TaskManager {
                 if (!committableOffsets.isEmpty()) {
                     consumedOffsetsAndMetadataPerTask.put(task.id(), committableOffsets);
                 }
             }
 
-            commitOffsetsOrTransaction(consumedOffsetsAndMetadataPerTask);
+            try {
+                commitOffsetsOrTransaction(consumedOffsetsAndMetadataPerTask);
 
-            for (final Task task : additionalTasksForCommitting) {
-                task.postCommit();
+                for (final Task task : additionalTasksForCommitting) {
+                    task.postCommit();
+                }
+            } catch (final RuntimeException e) {
+                log.error("Failed to commit tasks that are " +
+                    "prepared to close clean, will close them as dirty instead", e);
+                dirtyTasks.addAll(checkpointPerTask.keySet());
+                checkpointPerTask.clear();
+                // Just add first taskId to re-throw by the end.
+                taskCloseExceptions.put(consumedOffsetsAndMetadataPerTask.keySet().iterator().next(), e);
             }
         }
 
         for (final Map.Entry<Task, Map<TopicPartition, Long>> taskAndCheckpoint : checkpointPerTask.entrySet()) {
             final Task task = taskAndCheckpoint.getKey();
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
