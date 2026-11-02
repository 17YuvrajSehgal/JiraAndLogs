# Annotation packet: KAFKA-9645  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Records could not find corresponding partition/task

We could be hitting the illegal state when stream kicks off a rebalance with all tasks closed:

```

[2020-03-03T18:36:09-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,105] WARN [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] stream-thread [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] Detected that the thread is being fenced. This implies that this thread missed a rebalance and dropped out of the consumer group. Will close out all assigned tasks and rejoin the consumer group. (org.apache.kafka.streams.processor.internals.StreamThread)

[2020-03-03T18:36:09-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,105] INFO [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] [Consumer clientId=stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1-restore-consumer, groupId=null] Subscribed to partition(s): stream-soak-test-KSTREAM-AGGREGATE-STATE-STORE-0000000049-changelog-2 (org.apache.kafka.clients.consumer.KafkaConsumer)

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,286] INFO [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] [Producer clientId=stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1-1_1-producer, transactionalId=stream-soak-test-1_1] Closing the Kafka producer with timeoutMillis = 9223372036854775807 ms. (org.apache.kafka.clients.producer.KafkaProducer)

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,287] INFO [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] stream-thread [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] task [1_1] Closed dirty (org.apache.kafka.streams.processor.internals.StreamTask)

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,287] INFO [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] [Consumer clientId=stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1-restore-consumer, groupId=null] Unsubscribed all topics or patterns and assigned partitions (org.apache.kafka.clients.consumer.KafkaConsumer)

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,290] INFO [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] [Producer clientId=stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1-3_2-producer, transactionalId=stream-soak-test-3_2] Closing the Kafka producer with timeoutMillis = 9223372036854775807 ms. (org.apache.kafka.clients.producer.KafkaProducer)

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,292] INFO [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] stream-thread [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] task [3_2] Closed dirty (org.apache.kafka.streams.processor.internals.StreamTask)

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,293] ERROR [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] stream-thread [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] Unable to locate active task for received-record partition node-name-repartition-1. Current tasks: TaskManager

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) >      MetadataState:

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) >      Tasks:

 (org.apache.kafka.streams.processor.internals.StreamThread)

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,293] ERROR [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] stream-thread [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] Encountered the following exception during processing and the thread is going to shut down:  (org.apache.kafka.streams.processor.internals.StreamThread)

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) java.lang.NullPointerException: Task was unexpectedly missing for partition node-name-repartition-1

        at org.apache.kafka.streams.processor.internals.StreamThread.addRecordsToTasks(StreamThread.java:984)

        at org.apache.kafka.streams.processor.internals.StreamThread.runOnce(StreamThread.java:820)

```

We should be more careful in this case by avoiding processing data when no corresponding task is found.

        at org.apache.kafka.streams.processor.internals.StreamThread.runLoop(StreamThread.java:751)

        at org.apache.kafka.streams.processor.internals.StreamThread.run(StreamThread.java:725)

[2020-03-03T18:36:10-08:00] (streams-soak-trunk-eos_soak_i-050294ea2392cf355_streamslog) [2020-03-04 02:36:09,294] INFO [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] stream-thread [stream-soak-test-e639a3a1-bd9d-49e0-896e-df9fe0cd63db-StreamThread-1] State transition from RUNNING to PENDING_SHUTDOWN (org.apache.kafka.streams.processor.internals.StreamThread)
```

## Fix commit message(s)

`fe0b704285eb`

```
KAFKA-9645: Fallback to unsubscribe during Task Migrated (#8220)

After #7312, we could still return data during the rebalance phase, which means it could be possible to find records without corresponding tasks. We have to fallback to the unsubscribe mode during task migrated as the assignment should be cleared out to keep sync with task manager state.

Reviewers: A. Sophie Blee-Goldman <sophie@confluent.io>, Guozhang Wang <wangguoz@gmail.com>
```

## Files the fix changed

Snapshot holds 1,850 non-test source files. The fix changed 3 file(s); 2 of them are non-test source files (listed below as gold).

- `clients/src/main/java/org/apache/kafka/clients/consumer/MockConsumer.java`
- `streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java`

## The fix diff

### `clients/src/main/java/org/apache/kafka/clients/consumer/MockConsumer.java`

```diff
diff --git a/clients/src/main/java/org/apache/kafka/clients/consumer/MockConsumer.java b/clients/src/main/java/org/apache/kafka/clients/consumer/MockConsumer.java
index b8579c45df..33702c3144 100644
--- a/clients/src/main/java/org/apache/kafka/clients/consumer/MockConsumer.java
+++ b/clients/src/main/java/org/apache/kafka/clients/consumer/MockConsumer.java
@@ -64,10 +64,11 @@ public class MockConsumer<K, V> implements Consumer<K, V> {
     private Map<TopicPartition, List<ConsumerRecord<K, V>>> records;
     private KafkaException pollException;
     private KafkaException offsetsException;
     private AtomicBoolean wakeup;
     private boolean closed;
+    private boolean shouldRebalance;
 
     public MockConsumer(OffsetResetStrategy offsetResetStrategy) {
         this.subscriptions = new SubscriptionState(new LogContext(), offsetResetStrategy);
         this.partitions = new HashMap<>();
         this.records = new HashMap<>();
@@ -77,10 +78,11 @@ public class MockConsumer<K, V> implements Consumer<K, V> {
         this.endOffsets = new HashMap<>();
         this.pollTasks = new LinkedList<>();
         this.pollException = null;
         this.wakeup = new AtomicBoolean(false);
         this.committed = new HashMap<>();
+        this.shouldRebalance = false;
     }
 
     @Override
     public synchronized Set<TopicPartition> assignment() {
         return this.subscriptions.assignedPartitions();
@@ -354,25 +356,14 @@ public class MockConsumer<K, V> implements Consumer<K, V> {
     public synchronized void seekToEnd(Collection<TopicPartition> partitions) {
         ensureNotClosed();
         subscriptions.requestOffsetReset(partitions, OffsetResetStrategy.LATEST);
     }
 
-    // needed for cases where you make a second call to endOffsets
-    public synchronized void addEndOffsets(final Map<TopicPartition, Long> newOffsets) {
-        innerUpdateEndOffsets(newOffsets, false);
-    }
-
     public synchronized void updateEndOffsets(final Map<TopicPartition, Long> newOffsets) {
-        innerUpdateEndOffsets(newOffsets, true);
-    }
-
-    private void innerUpdateEndOffsets(final Map<TopicPartition, Long> newOffsets,
-                                       final boolean replace) {
-
         for (final Map.Entry<TopicPartition, Long> entry : newOffsets.entrySet()) {
             List<Long> offsets = endOffsets.get(entry.getKey());
-            if (replace || offsets == null) {
+            if (offsets == null) {
                 offsets = new ArrayList<>();
             }
             offsets.add(entry.getValue());
             endOffsets.put(entry.getKey(), offsets);
         }
@@ -566,10 +557,19 @@ public class MockConsumer<K, V> implements Consumer<K, V> {
         return null;
     }
 
     @Override
     public void enforceRebalance() {
+        shouldRebalance = true;
+    }
+
+    public boolean shouldRebalance() {
+        return shouldRebalance;
+    }
+
+    public void resetShouldRebalance() {
+        shouldRebalance = false;
     }
 
     @Override
     public void close(Duration timeout) {
         close();
```

### `streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java`

```diff
diff --git a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java
index d67fff8577..7b6ac833f6 100644
--- a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java
+++ b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java
@@ -506,15 +506,16 @@ public class StreamThread extends Thread {
                 log.warn("Detected that the thread is being fenced. " +
                     "This implies that this thread missed a rebalance and dropped out of the consumer group. " +
                     "Will close out all assigned tasks and rejoin the consumer group.");
 
                 taskManager.handleLostAll();
-                mainConsumer.enforceRebalance();
+                mainConsumer.unsubscribe();
+                subscribeConsumer();
             }
         }
     }
-    
+
     private void subscribeConsumer() {
         if (builder.usesPatternSubscription()) {
             mainConsumer.subscribe(builder.sourceTopicPattern(), rebalanceListener);
         } else {
             mainConsumer.subscribe(builder.sourceTopicCollection(), rebalanceListener);
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
