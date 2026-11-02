# Annotation packet: KAFKA-7112  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
StreamThread does not check for state again after pollRequests()

In StreamThread's main loop, we have:

{code}
        if (state == State.PARTITIONS_ASSIGNED) {
            // try to fetch some records with zero poll millis
            // to unblock the restoration as soon as possible
            records = pollRequests(Duration.ZERO);

            if (taskManager.updateNewAndRestoringTasks()) {
                setState(State.RUNNING);
            }
        }
{code}

in which we first check for state, and if it is {{PARTITIONS_ASSIGNED}} then call `consumer.poll()` and then call `askManager.updateNewAndRestoringTasks()`. There is a race condition though, that if another rebalance gets triggered, then `onPartitionRevoked` will be called in which we will {{restoreConsumer.unsubscribe();}}, and then if we call {{taskManager.updateNewAndRestoringTasks()}} right away we will see this:

{code}
Encountered the following error during processing: (org.apache.kafka.streams.processor.internals.StreamThread)
java.lang.IllegalStateException: Consumer is not subscribed to any topics or assigned any partitions
        at org.apache.kafka.clients.consumer.KafkaConsumer.poll(KafkaConsumer.java:1159)
        at org.apache.kafka.clients.consumer.KafkaConsumer.poll(KafkaConsumer.java:1150)
        at org.apache.kafka.streams.processor.internals.StoreChangelogReader.restore(StoreChangelogReader.java:83)
        at org.apache.kafka.streams.processor.internals.TaskManager.updateNewAndRestoringTasks(TaskManager.java:317)
        at org.apache.kafka.streams.processor.internals.StreamThread.runOnce(StreamThread.java:808)
        at org.apache.kafka.streams.processor.internals.StreamThread.runLoop(StreamThread.java:767)
        at org.apache.kafka.streams.processor.internals.StreamThread.run(StreamThread.java:736)
{code}
```

## Fix commit message(s)

`be0f10e19029`

```
MINOR: KAFKA-7112: Only resume restoration if state is still PARTITIONS_ASSIGNED after poll (#5306)

Before KIP-266, consumer.poll(0) would call updateAssignmentMetadataIfNeeded(Long.MAX_VALUE), which makes sure that the rebalance is definitely completed, i.e. both onPartitionRevoked and onPartitionAssigned called within this poll(0). After KIP-266, however, it is possible that only onPartitionRevoked will be called if timeout is elapsed. And hence we need to double check that state is still PARTITIONS_ASSIGNED after the consumer.poll(duration) call.

Reviewers: Ted Yu <yuzhihong@gmail.com>, Matthias J. Sax <matthias@confluent.io>
```

## Files the fix changed

Snapshot holds 1,497 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java`

## The fix diff

### `streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java`

```diff
diff --git a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java
index a159e7b6c7..77538ae9c7 100644
--- a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java
+++ b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamThread.java
@@ -802,25 +802,30 @@ public class StreamThread extends Thread {
 
         if (state == State.PARTITIONS_ASSIGNED) {
             // try to fetch some records with zero poll millis
             // to unblock the restoration as soon as possible
             records = pollRequests(Duration.ZERO);
+        } else if (state == State.PARTITIONS_REVOKED) {
+            // try to fetch some records with normal poll time
+            // in order to wait long enough to get the join response
+            records = pollRequests(pollTime);
+        } else if (state == State.RUNNING) {
+            // try to fetch some records with normal poll time
+            // in order to get long polling
+            records = pollRequests(pollTime);
+        } else {
+            // any other state should not happen
+            log.error("Unexpected state {} during normal iteration", state);
+            throw new StreamsException(logPrefix + "Unexpected state " + state + " during normal iteration");
+        }
 
+        // only try to initialize the assigned tasks
+        // if the state is still in PARTITION_ASSIGNED after the poll call
+        if (state == State.PARTITIONS_ASSIGNED) {
             if (taskManager.updateNewAndRestoringTasks()) {
                 setState(State.RUNNING);
             }
-        } else {
-            // try to fetch some records if necessary
-            records = pollRequests(pollTime);
-
-            // if state changed after the poll call,
-            // try to initialize the assigned tasks again
-            if (state == State.PARTITIONS_ASSIGNED) {
-                if (taskManager.updateNewAndRestoringTasks()) {
-                    setState(State.RUNNING);
-                }
-            }
         }
 
         if (records != null && !records.isEmpty() && taskManager.hasActiveRunningTasks()) {
             streamsMetrics.pollTimeSensor.record(computeLatency(), timerStartedMs);
             addRecordsToTasks(records);
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
