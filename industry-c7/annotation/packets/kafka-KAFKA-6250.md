# Annotation packet: KAFKA-6250  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Kafka Connect requires permission to create internal topics even if they exist

When using Kafka Connect with a cluster that doesn't allow the user to create topics (due to ACL configuration), Connect fails when trying to create its internal topics, even if these topics already exist.

This happens specifically when using hosted [Aiven Kafka|https://aiven.io/kafka], which does not permit creation of topics via the Kafka Admin Client API.

The problem is that Connect tries to create the topics, and ignores some specific errors such as topics that already exist, but not authorization errors.

This is what happens:
{noformat}
2017-11-21 15:57:24,176 [DistributedHerder] ERROR DistributedHerder:206 - Uncaught exception in herder work thread, exiting:
org.apache.kafka.connect.errors.ConnectException: Error while attempting to create/find topic(s) 'connect-offsets'
	at org.apache.kafka.connect.util.TopicAdmin.createTopics(TopicAdmin.java:245)
	at org.apache.kafka.connect.storage.KafkaOffsetBackingStore$1.run(KafkaOffsetBackingStore.java:99)
	at org.apache.kafka.connect.util.KafkaBasedLog.start(KafkaBasedLog.java:126)
	at org.apache.kafka.connect.storage.KafkaOffsetBackingStore.start(KafkaOffsetBackingStore.java:109)
	at org.apache.kafka.connect.runtime.Worker.start(Worker.java:146)
	at org.apache.kafka.connect.runtime.AbstractHerder.startServices(AbstractHerder.java:99)
	at org.apache.kafka.connect.runtime.distributed.DistributedHerder.run(DistributedHerder.java:194)
	at java.util.concurrent.Executors$RunnableAdapter.call(Executors.java:511)
	at java.util.concurrent.FutureTask.run(FutureTask.java:266)
	at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1142)
	at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:617)
	at java.lang.Thread.run(Thread.java:745)
Caused by: java.util.concurrent.ExecutionException: org.apache.kafka.common.errors.ClusterAuthorizationException: Cluster authorization failed.
	at org.apache.kafka.common.internals.KafkaFutureImpl.wrapAndThrow(KafkaFutureImpl.java:45)
	at org.apache.kafka.common.internals.KafkaFutureImpl.access$000(KafkaFutureImpl.java:32)
	at org.apache.kafka.common.internals.KafkaFutureImpl$SingleWaiter.await(KafkaFutureImpl.java:89)
	at org.apache.kafka.common.internals.KafkaFutureImpl.get(KafkaFutureImpl.java:213)
	at org.apache.kafka.connect.util.TopicAdmin.createTopics(TopicAdmin.java:226)
	... 11 more
Caused by: org.apache.kafka.common.errors.ClusterAuthorizationException: Cluster authorization failed.
{noformat}
```

## Fix commit message(s)

`936e81afcb04`

```
KAFKA-6250: Use existing Kafka Connect internal topics without requiring ACL (#4247)

When using Kafka Connect with a cluster that doesn't allow the user to
create topics (due to ACL configuration), Connect fails when trying to
create its internal topics even if these topics already exist. This is
incorrect behavior according to the documentation, which mentions that
R/W access should be enough.

This happens specifically when using Aiven Kafka, which does not permit
creation of topics via the Kafka Admin Client API.

The patch ignores the returned error, similar to the behavior for older
brokers that don't support the API.
```

## Files the fix changed

Snapshot holds 1,435 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `connect/runtime/src/main/java/org/apache/kafka/connect/util/TopicAdmin.java`

## The fix diff

### `connect/runtime/src/main/java/org/apache/kafka/connect/util/TopicAdmin.java`

```diff
diff --git a/connect/runtime/src/main/java/org/apache/kafka/connect/util/TopicAdmin.java b/connect/runtime/src/main/java/org/apache/kafka/connect/util/TopicAdmin.java
index 5da4f2d00d..ad21561baf 100644
--- a/connect/runtime/src/main/java/org/apache/kafka/connect/util/TopicAdmin.java
+++ b/connect/runtime/src/main/java/org/apache/kafka/connect/util/TopicAdmin.java
@@ -19,10 +19,11 @@ package org.apache.kafka.connect.util;
 import org.apache.kafka.clients.admin.AdminClient;
 import org.apache.kafka.clients.admin.AdminClientConfig;
 import org.apache.kafka.clients.admin.CreateTopicsOptions;
 import org.apache.kafka.clients.admin.NewTopic;
 import org.apache.kafka.common.KafkaFuture;
+import org.apache.kafka.common.errors.ClusterAuthorizationException;
 import org.apache.kafka.common.errors.TimeoutException;
 import org.apache.kafka.common.errors.TopicExistsException;
 import org.apache.kafka.common.errors.UnsupportedVersionException;
 import org.apache.kafka.common.utils.Utils;
 import org.apache.kafka.connect.errors.ConnectException;
@@ -227,17 +228,24 @@ public class TopicAdmin implements AutoCloseable {
                 entry.getValue().get();
                 log.info("Created topic {} on brokers at {}", topicsByName.get(topic), bootstrapServers);
                 newlyCreatedTopicNames.add(topic);
             } catch (ExecutionException e) {
                 Throwable cause = e.getCause();
-                if (e.getCause() instanceof TopicExistsException) {
+                if (cause instanceof TopicExistsException) {
                     log.debug("Found existing topic '{}' on the brokers at {}", topic, bootstrapServers);
                     continue;
                 }
                 if (cause instanceof UnsupportedVersionException) {
-                    log.debug("Unable to use Kafka admin client to create topic descriptions for '{}' using the brokers at {}," +
-                                      "falling back to assume topic(s) exist or will be auto-created by the broker", topicNameList, bootstrapServers);
+                    log.debug("Unable to create topic(s) '{}' since the brokers at {} do not support the CreateTopics API.",
+                            " Falling back to assume topic(s) exist or will be auto-created by the broker.",
+                            topicNameList, bootstrapServers);
+                    return Collections.emptySet();
+                }
+                if (cause instanceof ClusterAuthorizationException) {
+                    log.debug("Not authorized to create topic(s) '{}'." +
+                            " Falling back to assume topic(s) exist or will be auto-created by the broker.",
+                            topicNameList, bootstrapServers);
                     return Collections.emptySet();
                 }
                 if (cause instanceof TimeoutException) {
                     // Timed out waiting for the operation to complete
                     throw new ConnectException("Timed out while checking for or creating topic(s) '" + topicNameList + "'." +
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
