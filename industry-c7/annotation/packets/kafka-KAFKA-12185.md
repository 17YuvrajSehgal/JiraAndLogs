# Annotation packet: KAFKA-12185  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Flaky Test StoreQueryIntegrationTest#shouldQueryAllStalePartitionStores

{{{{java.lang.AssertionError: Application did not reach a RUNNING state for all streams instances. Non-running instances: \{org.apache.kafka.streams.KafkaStreams@651720d3=NOT_RUNNING}
	at org.junit.Assert.fail(Assert.java:89)
	at org.apache.kafka.streams.integration.utils.IntegrationTestUtils.startApplicationAndWaitUntilRunning(IntegrationTestUtils.java:892)
	at org.apache.kafka.streams.integration.StoreQueryIntegrationTest.shouldQueryAllStalePartitionStores(StoreQueryIntegrationTest.java:270)}}}}

 

{{https://github.com/apache/kafka/pull/9835/checks?check_run_id=1666639314}}
```

## Fix commit message(s)

`92e72f7bf968`

```
KAFKA-12185: fix ConcurrentModificationException in newly added Tasks container class (#9940)

Reviewers: Guozhang Wang <guozhand@confluent.io>, A. Sophie Blee-Goldman <sophie@confluent.io>
```

## Files the fix changed

Snapshot holds 2,096 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `streams/src/main/java/org/apache/kafka/streams/processor/internals/Tasks.java`

## The fix diff

### `streams/src/main/java/org/apache/kafka/streams/processor/internals/Tasks.java`

```diff
diff --git a/streams/src/main/java/org/apache/kafka/streams/processor/internals/Tasks.java b/streams/src/main/java/org/apache/kafka/streams/processor/internals/Tasks.java
index 843db801ee..e12290f395 100644
--- a/streams/src/main/java/org/apache/kafka/streams/processor/internals/Tasks.java
+++ b/streams/src/main/java/org/apache/kafka/streams/processor/internals/Tasks.java
@@ -126,13 +126,15 @@ class Tasks {
                                 final Set<TopicPartition> partitions,
                                 final Map<TaskId, RuntimeException> taskCloseExceptions) {
         if (activeTasksPerId.remove(activeTask.id()) == null) {
             throw new IllegalStateException("Attempted to convert unknown active task to standby task: " + activeTask.id());
         }
-        activeTasksPerPartition.entrySet().stream()
+        final Set<TopicPartition> toBeRemoved = activeTasksPerPartition.entrySet().stream()
             .filter(e -> e.getValue().id().equals(activeTask.id()))
-            .forEach(e -> activeTasksPerPartition.remove(e.getKey()));
+            .map(Map.Entry::getKey)
+            .collect(Collectors.toSet());
+        toBeRemoved.forEach(activeTasksPerPartition::remove);
 
         cleanUpTaskProducerAndRemoveTask(activeTask.id(), taskCloseExceptions);
 
         final StandbyTask standbyTask = standbyTaskCreator.createStandbyTaskFromActive(activeTask, partitions);
         standbyTasksPerId.put(standbyTask.id(), standbyTask);
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
