# Annotation packet: KAFKA-4848  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Stream thread getting into deadlock state while trying to get rocksdb lock in retryWithBackoff

We see a deadlock state when streams thread to process a task takes longer than MAX_POLL_INTERVAL_MS_CONFIG time. In this case this threads partitions are assigned to some other thread including rocksdb lock. When it tries to process the next task it cannot get rocks db lock and simply keeps waiting for that lock forever.

in retryWithBackoff for AbstractTaskCreator we have a backoffTimeMs = 50L.
If it does not get lock the we simply increase the time by 10x and keep trying inside the while true loop.

We need to have a upper bound for this backoffTimeM. If the time is greater than  MAX_POLL_INTERVAL_MS_CONFIG and it still hasn't got the lock means this thread's partitions are moved somewhere else and it may not get the lock again.
```

## Fix commit message(s)

`197a5d5a6d16`

```
KAFKA-4848: Fix retryWithBackoff deadlock issue

Fixes related to handling of MAX_POLL_INTERVAL_MS_CONFIG during deadlock and CommitFailedException on partition revoked.

Author: Sachin Mittal <sjmittal@gmail.com>

Reviewers: Matthias J. Sax, Damian Guy, Guozhang Wang

Closes #2642 from sjmittal/trunk
```

## Files the fix changed

Snapshot holds 1,057 non-test source files. The fix changed 7 file(s); 2 of them are non-test source files (listed below as gold).

- `streams/src/main/java/org/apache/kafka/streams/StreamsConfig.java`
- `streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java`

## The fix diff

### `streams/src/main/java/org/apache/kafka/streams/StreamsConfig.java`

```diff
diff --git a/streams/src/main/java/org/apache/kafka/streams/StreamsConfig.java b/streams/src/main/java/org/apache/kafka/streams/StreamsConfig.java
index 0eb3f7b248..d2ba063d94 100644
--- a/streams/src/main/java/org/apache/kafka/streams/StreamsConfig.java
+++ b/streams/src/main/java/org/apache/kafka/streams/StreamsConfig.java
@@ -399,10 +399,11 @@ public class StreamsConfig extends AbstractConfig {
     static {
         final Map<String, Object> tempConsumerDefaultOverrides = new HashMap<>();
         tempConsumerDefaultOverrides.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, "1000");
         tempConsumerDefaultOverrides.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
         tempConsumerDefaultOverrides.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
+        tempConsumerDefaultOverrides.put(ConsumerConfig.MAX_POLL_INTERVAL_MS_CONFIG, "300000");
 
         CONSUMER_DEFAULT_OVERRIDES = Collections.unmodifiableMap(tempConsumerDefaultOverrides);
     }
 
     public static class InternalConfig {
```

### `streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java`

```diff
diff --git a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java
index 6a6b508166..7cd4b93036 100644
--- a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java
+++ b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java
@@ -24,10 +24,12 @@ import org.apache.kafka.clients.consumer.ConsumerRecord;
 import org.apache.kafka.clients.consumer.ConsumerRecords;
 import org.apache.kafka.clients.consumer.NoOffsetForPartitionException;
 import org.apache.kafka.clients.producer.Producer;
 import org.apache.kafka.common.KafkaException;
 import org.apache.kafka.common.TopicPartition;
+import org.apache.kafka.common.config.ConfigDef;
+import org.apache.kafka.common.config.ConfigDef.Type;
 import org.apache.kafka.common.metrics.Metrics;
 import org.apache.kafka.common.metrics.Sensor;
 import org.apache.kafka.common.metrics.stats.Avg;
 import org.apache.kafka.common.metrics.stats.Count;
 import org.apache.kafka.common.metrics.stats.Max;
@@ -195,10 +197,11 @@ public class StreamThread extends Thread {
     private final Map<TopicPartition, StandbyTask> standbyTasksByPartition;
     private final Set<TaskId> prevActiveTasks;
     private final Map<TaskId, StreamTask> suspendedTasks;
     private final Map<TaskId, StandbyTask> suspendedStandbyTasks;
     private final Time time;
+    private final int rebalanceTimeoutMs;
     private final long pollTimeMs;
     private final long cleanTimeMs;
     private final long commitTimeMs;
     private final StreamsMetricsThreadImpl streamsMetrics;
     // TODO: this is not private only for tests, should be better refactored
@@ -288,10 +291,12 @@ public class StreamThread extends Thread {
 
         // standby ktables
         this.standbyRecords = new HashMap<>();
 
         this.stateDirectory = new StateDirectory(applicationId, config.getString(StreamsConfig.STATE_DIR_CONFIG), time);
+        final Object maxPollInterval = consumerConfigs.get(ConsumerConfig.MAX_POLL_INTERVAL_MS_CONFIG);
+        this.rebalanceTimeoutMs =  (Integer) ConfigDef.parseType(ConsumerConfig.MAX_POLL_INTERVAL_MS_CONFIG, maxPollInterval, Type.INT);
         this.pollTimeMs = config.getLong(StreamsConfig.POLL_MS_CONFIG);
         this.commitTimeMs = config.getLong(StreamsConfig.COMMIT_INTERVAL_MS_CONFIG);
         this.cleanTimeMs = config.getLong(StreamsConfig.STATE_CLEANUP_DELAY_MS_CONFIG);
 
         this.time = time;
@@ -853,11 +858,11 @@ public class StreamThread extends Thread {
                 }
             }
         }
     }
 
-    private void addStreamTasks(Collection<TopicPartition> assignment) {
+    private void addStreamTasks(Collection<TopicPartition> assignment, final long start) {
         if (partitionAssignor == null)
             throw new IllegalStateException(logPrefix + " Partition assignor has not been initialized while adding stream tasks: this should not happen.");
 
         final Map<TaskId, Set<TopicPartition>> newTasks = new HashMap<>();
 
@@ -891,11 +896,11 @@ public class StreamThread extends Thread {
             }
         }
 
         // create all newly assigned tasks (guard against race condition with other thread via backoff and retry)
         // -> other thread will call removeSuspendedTasks(); eventually
-        taskCreator.retryWithBackoff(newTasks);
+        taskCreator.retryWithBackoff(newTasks, start);
     }
 
     StandbyTask createStandbyTask(TaskId id, Collection<TopicPartition> partitions) {
         log.info("{} Creating new standby task {} with assigned partitions {}", logPrefix, id, partitions);
 
@@ -908,11 +913,11 @@ public class StreamThread extends Thread {
         } else {
             return null;
         }
     }
 
-    private void addStandbyTasks() {
+    private void addStandbyTasks(final long start) {
         if (partitionAssignor == null)
             throw new IllegalStateException(logPrefix + " Partition assignor has not been initialized while adding standby tasks: this should not happen.");
 
         Map<TopicPartition, Long> checkpointedOffsets = new HashMap<>();
 
@@ -935,11 +940,11 @@ public class StreamThread extends Thread {
             updateStandByTaskMaps(checkpointedOffsets, taskId, partitions, task);
         }
 
         // create all newly assigned standby tasks (guard against race condition with other thread via backoff and retry)
         // -> other thread will call removeSuspendedStandbyTasks(); eventually
-        new StandbyTaskCreator(checkpointedOffsets).retryWithBackoff(newStandbyTasks);
+        new StandbyTaskCreator(checkpointedOffsets).retryWithBackoff(newStandbyTasks, start);
 
         restoreConsumer.assign(new ArrayList<>(checkpointedOffsets.keySet()));
 
         for (Map.Entry<TopicPartition, Long> entry : checkpointedOffsets.entrySet()) {
             TopicPartition partition = entry.getKey();
@@ -1124,11 +1129,11 @@ public class StreamThread extends Thread {
 
         }
     }
 
     abstract class AbstractTaskCreator {
-        void retryWithBackoff(final Map<TaskId, Set<TopicPartition>> tasksToBeCreated) {
+        void retryWithBackoff(final Map<TaskId, Set<TopicPartition>> tasksToBeCreated, final long start) {
             long backoffTimeMs = 50L;
             while (true) {
                 final Iterator<Map.Entry<TaskId, Set<TopicPartition>>> it = tasksToBeCreated.entrySet().iterator();
                 while (it.hasNext()) {
                     final Map.Entry<TaskId, Set<TopicPartition>> newTaskAndPartitions = it.next();
@@ -1136,17 +1141,18 @@ public class StreamThread extends Thread {
                     final Set<TopicPartition> partitions = newTaskAndPartitions.getValue();
 
                     try {
                         createTask(taskId, partitions);
                         it.remove();
+                        backoffTimeMs = 50L;
                     } catch (final LockException e) {
                         // ignore and retry
                         log.warn("Could not create task {}. Will retry.", taskId, e);
                     }
                 }
 
-                if (tasksToBeCreated.isEmpty()) {
+                if (tasksToBeCreated.isEmpty() || time.milliseconds() - start > rebalanceTimeoutMs) {
                     break;
                 }
 
                 try {
                     Thread.sleep(backoffTimeMs);
@@ -1205,13 +1211,13 @@ public class StreamThread extends Thread {
                 setStateWhenNotInPendingShutdown(State.ASSIGNING_PARTITIONS);
                 // do this first as we may have suspended standby tasks that
                 // will become active or vice versa
                 closeNonAssignedSuspendedStandbyTasks();
                 closeNonAssignedSuspendedTasks();
-                addStreamTasks(assignment);
+                addStreamTasks(assignment, start);
                 storeChangelogReader.restore();
-                addStandbyTasks();
+                addStandbyTasks(start);
                 streamsMetadataState.onChange(partitionAssignor.getPartitionsByHostState(), partitionAssignor.clusterMetadata());
                 lastCleanMs = time.milliseconds(); // start the cleaning cycle
                 setStateWhenNotInPendingShutdown(State.RUNNING);
             } catch (Throwable t) {
                 rebalanceException = t;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
