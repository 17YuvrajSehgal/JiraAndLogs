# Annotation packet: KAFKA-5140  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Flaky ResetIntegrationTest

{noformat}
org.apache.kafka.streams.integration.ResetIntegrationTest > testReprocessingFromScratchAfterResetWithIntermediateUserTopic FAILED
    java.lang.AssertionError: 
    Expected: <[KeyValue(2986681642095, 1), KeyValue(2986681642055, 1), KeyValue(2986681642075, 1), KeyValue(2986681642035, 1), KeyValue(2986681642095, 1), KeyValue(2986681642055, 1), KeyValue(2986681642115, 1), KeyValue(2986681642075, 1), KeyValue(2986681642075, 2), KeyValue(2986681642095, 2), KeyValue(2986681642115, 1), KeyValue(2986681642135, 1), KeyValue(2986681642095, 2), KeyValue(2986681642115, 2), KeyValue(2986681642155, 1), KeyValue(2986681642135, 1), KeyValue(2986681642115, 2), KeyValue(2986681642135, 2), KeyValue(2986681642155, 1), KeyValue(2986681642175, 1), KeyValue(2986681642135, 2), KeyValue(2986681642155, 2), KeyValue(2986681642175, 1), KeyValue(2986681642195, 1), KeyValue(2986681642135, 3), KeyValue(2986681642155, 2), KeyValue(2986681642175, 2), KeyValue(2986681642195, 1), KeyValue(2986681642155, 3), KeyValue(2986681642175, 2), KeyValue(2986681642195, 2), KeyValue(2986681642155, 3), KeyValue(2986681642175, 3), KeyValue(2986681642195, 2), KeyValue(2986681642155, 4), KeyValue(2986681642175, 3), KeyValue(2986681642195, 3)]>
         but: was <[KeyValue(2986681642095, 1), KeyValue(2986681642055, 1), KeyValue(2986681642075, 1), KeyValue(2986681642035, 1), KeyValue(2986681642095, 1), KeyValue(2986681642055, 1), KeyValue(2986681642115, 1), KeyValue(2986681642075, 1), KeyValue(2986681642075, 2), KeyValue(2986681642095, 2), KeyValue(2986681642115, 1), KeyValue(2986681642135, 1), KeyValue(2986681642095, 2), KeyValue(2986681642115, 2), KeyValue(2986681642155, 1), KeyValue(2986681642135, 1), KeyValue(2986681642115, 2), KeyValue(2986681642135, 2), KeyValue(2986681642155, 1), KeyValue(2986681642175, 1), KeyValue(2986681642135, 2), KeyValue(2986681642155, 2), KeyValue(2986681642175, 1), KeyValue(2986681642195, 1), KeyValue(2986681642135, 3), KeyValue(2986681642155, 2), KeyValue(2986681642175, 2), KeyValue(2986681642195, 1), KeyValue(2986681642155, 3), KeyValue(2986681642175, 2), KeyValue(2986681642195, 2), KeyValue(2986681642155, 3)]>
        at org.hamcrest.MatcherAssert.assertThat(MatcherAssert.java:20)
        at org.hamcrest.MatcherAssert.assertThat(MatcherAssert.java:8)
        at org.apache.kafka.streams.integration.ResetIntegrationTest.testReprocessingFromScratchAfterResetWithIntermediateUserTopic(ResetIntegrationTest.java:190)
{noformat}
```

## Fix commit message(s)

`d3f24798f92a`

```
KAFKA-5140: Fix reset integration test

A couple of root causes of this flaky test is fixed:

1. The MockTime was incorrectly used across multiple test methods within the class, as a class rule. Instead we set it on each test case; also remove the scala MockTime dependency.

2. List topics may not contain the deleted topics while their ZK paths are yet to be deleted; so the delete-check-recreate pattern may fail to successfully recreate the topic at all. Change the checking to read from zk path directly instead.

Another minor fix is to remove the misleading wait condition error message as the accumData is always empty.

Author: Guozhang Wang <wangguoz@gmail.com>

Reviewers: Bill Bejeck <bill@confluent.io>, Damian Guy <damian.guy@gmail.com>, Matthias J. Sax <matthias@confluent.io>

Closes #4095 from guozhangwang/KMinor-reset-integration-test
```

## Files the fix changed

Snapshot holds 1,394 non-test source files. The fix changed 8 file(s); 2 of them are non-test source files (listed below as gold).

- `streams/src/main/java/org/apache/kafka/streams/processor/internals/InternalTopicManager.java`
- `streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamPartitionAssignor.java`

## The fix diff

### `streams/src/main/java/org/apache/kafka/streams/processor/internals/InternalTopicManager.java`

```diff
diff --git a/streams/src/main/java/org/apache/kafka/streams/processor/internals/InternalTopicManager.java b/streams/src/main/java/org/apache/kafka/streams/processor/internals/InternalTopicManager.java
index cd57867c4b..a038d09021 100644
--- a/streams/src/main/java/org/apache/kafka/streams/processor/internals/InternalTopicManager.java
+++ b/streams/src/main/java/org/apache/kafka/streams/processor/internals/InternalTopicManager.java
@@ -15,41 +15,48 @@
  * limitations under the License.
  */
 package org.apache.kafka.streams.processor.internals;
 
 import org.apache.kafka.common.requests.MetadataResponse;
+import org.apache.kafka.common.utils.LogContext;
 import org.apache.kafka.common.utils.Time;
 import org.apache.kafka.streams.errors.StreamsException;
 import org.slf4j.Logger;
-import org.slf4j.LoggerFactory;
 
 import java.io.IOException;
 import java.util.Collection;
 import java.util.HashMap;
 import java.util.Map;
 import java.util.Set;
 import java.util.concurrent.TimeUnit;
 
 public class InternalTopicManager {
 
-    private static final Logger log = LoggerFactory.getLogger(InternalTopicManager.class);
+    static final Long WINDOW_CHANGE_LOG_ADDITIONAL_RETENTION_DEFAULT = TimeUnit.MILLISECONDS.convert(1, TimeUnit.DAYS);
+
     public static final String CLEANUP_POLICY_PROP = "cleanup.policy";
     public static final String RETENTION_MS = "retention.ms";
-    public static final Long WINDOW_CHANGE_LOG_ADDITIONAL_RETENTION_DEFAULT = TimeUnit.MILLISECONDS.convert(1, TimeUnit.DAYS);
     private static final int MAX_TOPIC_READY_TRY = 5;
+
+    private final Logger log;
     private final Time time;
     private final long windowChangeLogAdditionalRetention;
 
     private final int replicationFactor;
     private final StreamsKafkaClient streamsKafkaClient;
 
-    public InternalTopicManager(final StreamsKafkaClient streamsKafkaClient, final int replicationFactor,
-                                final long windowChangeLogAdditionalRetention, final Time time) {
+    public InternalTopicManager(final StreamsKafkaClient streamsKafkaClient,
+                                final int replicationFactor,
+                                final long windowChangeLogAdditionalRetention,
+                                final Time time) {
         this.streamsKafkaClient = streamsKafkaClient;
         this.replicationFactor = replicationFactor;
         this.windowChangeLogAdditionalRetention = windowChangeLogAdditionalRetention;
         this.time = time;
+
+        LogContext logContext = new LogContext(String.format("stream-thread [%s] ", Thread.currentThread().getName()));
+        this.log = logContext.logger(getClass());
     }
 
     /**
      * Prepares a set of given internal topics.
      *
```

### `streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamPartitionAssignor.java`

```diff
diff --git a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamPartitionAssignor.java b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamPartitionAssignor.java
index 621eb15635..9e505a1bf3 100644
--- a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamPartitionAssignor.java
+++ b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StreamPartitionAssignor.java
@@ -14,10 +14,11 @@
  * See the License for the specific language governing permissions and
  * limitations under the License.
  */
 package org.apache.kafka.streams.processor.internals;
 
+import org.apache.kafka.clients.CommonClientConfigs;
 import org.apache.kafka.clients.consumer.internals.PartitionAssignor;
 import org.apache.kafka.common.Cluster;
 import org.apache.kafka.common.Configurable;
 import org.apache.kafka.common.KafkaException;
 import org.apache.kafka.common.Node;
@@ -198,13 +199,13 @@ public class StreamPartitionAssignor implements PartitionAssignor, Configurable,
      */
     @Override
     public void configure(Map<String, ?> configs) {
         numStandbyReplicas = (Integer) configs.get(StreamsConfig.NUM_STANDBY_REPLICAS_CONFIG);
 
-        //Initializing the logger without threadDataProvider name because provider name is not known/verified at this point
-        logPrefix = String.format("stream-thread ");
-        LogContext logContext = new LogContext(logPrefix);
+        // Setting the logger with the passed in client thread name
+        logPrefix = String.format("stream-thread [%s] ", configs.get(CommonClientConfigs.CLIENT_ID_CONFIG));
+        final LogContext logContext = new LogContext(logPrefix);
         this.log = logContext.logger(getClass());
 
         Object o = configs.get(StreamsConfig.InternalConfig.STREAM_THREAD_INSTANCE);
         if (o == null) {
             KafkaException ex = new KafkaException("StreamThread is not specified");
@@ -219,15 +220,10 @@ public class StreamPartitionAssignor implements PartitionAssignor, Configurable,
         }
 
         threadDataProvider = (ThreadDataProvider) o;
         threadDataProvider.setThreadMetadataProvider(this);
 
-        //Reassigning the logger with threadDataProvider name
-        logPrefix = String.format("stream-thread [%s] ", threadDataProvider.name());
-        logContext = new LogContext(logPrefix);
-        this.log = logContext.logger(getClass());
-
         String userEndPoint = (String) configs.get(StreamsConfig.APPLICATION_SERVER_CONFIG);
         if (userEndPoint != null && !userEndPoint.isEmpty()) {
             try {
                 String host = getHost(userEndPoint);
                 Integer port = getPort(userEndPoint);
@@ -500,12 +496,12 @@ public class StreamPartitionAssignor implements PartitionAssignor, Configurable,
         Map<UUID, ClientState> states = new HashMap<>();
         for (Map.Entry<UUID, ClientMetadata> entry : clientsMetadata.entrySet()) {
             states.put(entry.getKey(), entry.getValue().state);
         }
 
-        log.debug("{} Assigning tasks {} to clients {} with number of replicas {}",
-                logPrefix, partitionsForTask.keySet(), states, numStandbyReplicas);
+        log.debug("Assigning tasks {} to clients {} with number of replicas {}",
+                partitionsForTask.keySet(), states, numStandbyReplicas);
 
         final StickyTaskAssignor<UUID> taskAssignor = new StickyTaskAssignor<>(states, partitionsForTask.keySet());
         taskAssignor.assign(numStandbyReplicas);
 
         log.info("Assigned tasks to clients as {}.", states);
@@ -686,11 +682,11 @@ public class StreamPartitionAssignor implements PartitionAssignor, Configurable,
                     // ignore
                 }
             }
         }
 
-        log.debug("Completed validating internal topics in partition assignor");
+        log.debug("Completed validating internal topics in partition assignor.");
     }
 
     private boolean allTopicsCreated(final Set<String> topicNamesToMakeReady, final Map<InternalTopicConfig, Integer> topicsToMakeReady) {
         final Map<String, Integer> partitions = internalTopicManager.getNumPartitions(topicNamesToMakeReady);
         for (Map.Entry<InternalTopicConfig, Integer> entry : topicsToMakeReady.entrySet()) {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
