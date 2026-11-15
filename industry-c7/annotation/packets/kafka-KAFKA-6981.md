# Annotation packet: KAFKA-6981  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Missing Connector Config (errors.deadletterqueue.topic.name) kills Connect Clusters

The trunk version of AK currently tries to incorrectly read the property (errors.deadletterqueue.topic.name) when starting a sink connector. This fails no matter what the contents of the connector config are. The ConnectorConfig does not define this property, and any calls to getString will throw a ConfigException (since only known properties are retained by AbstractConfig). 

{noformat}
org.apache.kafka.common.config.ConfigException: Unknown configuration 'errors.deadletterqueue.topic.name'
    at org.apache.kafka.common.config.AbstractConfig.get(AbstractConfig.java:91)
    at org.apache.kafka.connect.runtime.ConnectorConfig$EnrichedConnectorConfig.get(ConnectorConfig.java:117)
    at org.apache.kafka.connect.runtime.ConnectorConfig.get(ConnectorConfig.java:162)
    at org.apache.kafka.common.config.AbstractConfig.getString(AbstractConfig.java:126)
    at org.apache.kafka.connect.runtime.Worker.sinkTaskReporters(Worker.java:531)
    at org.apache.kafka.connect.runtime.Worker.buildWorkerTask(Worker.java:508)
    at org.apache.kafka.connect.runtime.Worker.startTask(Worker.java:451)
    at org.apache.kafka.connect.runtime.distributed.DistributedHerder.startTask(DistributedHerder.java:873)
    at org.apache.kafka.connect.runtime.distributed.DistributedHerder.access$1600(DistributedHerder.java:111)
    at org.apache.kafka.connect.runtime.distributed.DistributedHerder$13.call(DistributedHerder.java:888)
    at org.apache.kafka.connect.runtime.distributed.DistributedHerder$13.call(DistributedHerder.java:884)
    at java.util.concurrent.FutureTask.run(FutureTask.java:266)
    at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1142)
    at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:617)
    at java.lang.Thread.run(Thread.java:745)
{noformat}

This is related to the changes introduced in the [KIP-298 Error Handling|https://cwiki.apache.org/confluence/display/KAFKA/KIP-298%3A+Error+Handling+in+Connect] feature.
```

## Fix commit message(s)

`faa15b8b758e`

```
KAFKA-6981: Move the error handling configuration properties into the ConnectorConfig and SinkConnectorConfig classes (KIP-298)

Move the error handling configuration properties into the ConnectorConfig and SinkConnectorConfig classes, and refactor the tests and classes to use these new properties.

Testing: Unit tests and running the connect-standalone script with a file sink connector.

Author: Arjun Satish <arjun@confluent.io>
Author: Randall Hauch <rhauch@gmail.com>

Reviewers: Konstantine Karantasis <konstantine@confluent.io>, Magesh Nandakumar <magesh.n.kumar@gmail.com>, Robert Yokota <rayokota@gmail.com>, Randall Hauch <rhauch@gmail.com>, Ewen Cheslack-Postava <ewen@confluent.io>

Closes #5125 from wicknicks/KAFKA-6981
```

## Files the fix changed

Snapshot holds 1,589 non-test source files. The fix changed 17 file(s); 8 of them are non-test source files (listed below as gold).

- `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/ConnectorConfig.java`
- `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/SinkConnectorConfig.java`
- `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/Worker.java`
- `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/DeadLetterQueueReporter.java`
- `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ErrorReporter.java`
- `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/LogReporter.java`
- `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/RetryWithToleranceOperator.java`
- `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ToleranceType.java`

## The fix diff

### `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/ConnectorConfig.java`

```diff
diff --git a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/ConnectorConfig.java b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/ConnectorConfig.java
index c54c160d5a..f98469e5b5 100644
--- a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/ConnectorConfig.java
+++ b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/ConnectorConfig.java
@@ -22,10 +22,11 @@ import org.apache.kafka.common.config.ConfigDef.Importance;
 import org.apache.kafka.common.config.ConfigDef.Type;
 import org.apache.kafka.common.config.ConfigDef.Width;
 import org.apache.kafka.common.config.ConfigException;
 import org.apache.kafka.connect.connector.ConnectRecord;
 import org.apache.kafka.connect.errors.ConnectException;
+import org.apache.kafka.connect.runtime.errors.ToleranceType;
 import org.apache.kafka.connect.runtime.isolation.PluginDesc;
 import org.apache.kafka.connect.runtime.isolation.Plugins;
 import org.apache.kafka.connect.transforms.Transformation;
 
 import java.util.ArrayList;
@@ -34,12 +35,12 @@ import java.util.HashMap;
 import java.util.HashSet;
 import java.util.LinkedHashSet;
 import java.util.List;
 import java.util.Map;
 
-import static org.apache.kafka.common.config.ConfigDef.Range.atLeast;
 import static org.apache.kafka.common.config.ConfigDef.NonEmptyStringWithoutControlChars.nonEmptyStringWithoutControlChars;
+import static org.apache.kafka.common.config.ConfigDef.Range.atLeast;
 import static org.apache.kafka.common.config.ConfigDef.ValidString.in;
 
 /**
  * <p>
  * Configuration options for Connectors. These only include Kafka Connect system-level configuration
@@ -52,10 +53,11 @@ import static org.apache.kafka.common.config.ConfigDef.ValidString.in;
  * </p>
  */
 public class ConnectorConfig extends AbstractConfig {
     protected static final String COMMON_GROUP = "Common";
     protected static final String TRANSFORMS_GROUP = "Transforms";
+    protected static final String ERROR_GROUP = "Error Handling";
 
     public static final String NAME_CONFIG = "name";
     private static final String NAME_DOC = "Globally unique name to use for this connector.";
     private static final String NAME_DISPLAY = "Connector name";
 
@@ -104,10 +106,41 @@ public class ConnectorConfig extends AbstractConfig {
 
     private static final String CONFIG_RELOAD_ACTION_DISPLAY = "Reload Action";
     public static final String CONFIG_RELOAD_ACTION_NONE = Herder.ConfigReloadAction.NONE.toString();
     public static final String CONFIG_RELOAD_ACTION_RESTART = Herder.ConfigReloadAction.RESTART.toString();
 
+    public static final String ERRORS_RETRY_TIMEOUT_CONFIG = "errors.retry.timeout";
+    public static final String ERRORS_RETRY_TIMEOUT_DISPLAY = "Retry Timeout for Errors";
+    public static final int ERRORS_RETRY_TIMEOUT_DEFAULT = 0;
+    public static final String ERRORS_RETRY_TIMEOUT_DOC = "The maximum duration in milliseconds that a failed operation " +
+            "will be reattempted. The default is 0, which means no retries will be attempted. Use -1 for infinite retries.";
+
+    public static final String ERRORS_RETRY_MAX_DELAY_CONFIG = "errors.retry.delay.max.ms";
+    public static final String ERRORS_RETRY_MAX_DELAY_DISPLAY = "Maximum Delay Between Retries for Errors";
+    public static final int ERRORS_RETRY_MAX_DELAY_DEFAULT = 60000;
+    public static final String ERRORS_RETRY_MAX_DELAY_DOC = "The maximum duration in milliseconds between consecutive retry attempts. " +
+            "Jitter will be added to the delay once this limit is reached to prevent thundering herd issues.";
+
+    public static final String ERRORS_TOLERANCE_CONFIG = "errors.allowed.max";
+    public static final String ERRORS_TOLERANCE_DISPLAY = "Error Tolerance";
+    public static final ToleranceType ERRORS_TOLERANCE_DEFAULT = ToleranceType.NONE;
+    public static final String ERRORS_TOLERANCE_DOC = "Behavior for tolerating errors during connector operation. 'none' is the default value " +
+            "and signals that any error will result in an immediate connector task failure; 'all' changes the behavior to skip over problematic records.";
+
+    public static final String ERRORS_LOG_ENABLE_CONFIG = "errors.log.enable";
+    public static final String ERRORS_LOG_ENABLE_DISPLAY = "Log Errors";
+    public static final boolean ERRORS_LOG_ENABLE_DEFAULT = false;
+    public static final String ERRORS_LOG_ENABLE_DOC = "If true, write each error and the details of the failed operation and problematic record " +
+            "to the Connect application log. This is 'false' by default, so that only errors that are not tolerated are reported.";
+
+    public static final String ERRORS_LOG_INCLUDE_MESSAGES_CONFIG = "errors.log.include.messages";
+    public static final String ERRORS_LOG_INCLUDE_MESSAGES_DISPLAY = "Log Error Details";
+    public static final boolean ERRORS_LOG_INCLUDE_MESSAGES_DEFAULT = false;
+    public static final String ERRORS_LOG_INCLUDE_MESSAGES_DOC = "Whether to the include in the log the Connect record that resulted in " +
+            "a failure. This is 'false' by default, which will prevent record keys, values, and headers from being written to log files, " +
+            "although some information such as topic and partition number will still be logged.";
+
     private final EnrichedConnectorConfig enrichedConfig;
     private static class EnrichedConnectorConfig extends AbstractConfig {
         EnrichedConnectorConfig(ConfigDef configDef, Map<String, String> props) {
             super(configDef, props);
         }
@@ -118,10 +151,11 @@ public class ConnectorConfig extends AbstractConfig {
         }
     }
 
     public static ConfigDef configDef() {
         int orderInGroup = 0;
+        int orderInErrorGroup = 0;
         return new ConfigDef()
                 .define(NAME_CONFIG, Type.STRING, ConfigDef.NO_DEFAULT_VALUE, nonEmptyStringWithoutControlChars(), Importance.HIGH, NAME_DOC, COMMON_GROUP, ++orderInGroup, Width.MEDIUM, NAME_DISPLAY)
                 .define(CONNECTOR_CLASS_CONFIG, Type.STRING, Importance.HIGH, CONNECTOR_CLASS_DOC, COMMON_GROUP, ++orderInGroup, Width.LONG, CONNECTOR_CLASS_DISPLAY)
                 .define(TASKS_MAX_CONFIG, Type.INT, TASKS_MAX_DEFAULT, atLeast(TASKS_MIN_CONFIG), Importance.HIGH, TASKS_MAX_DOC, COMMON_GROUP, ++orderInGroup, Width.SHORT, TASK_MAX_DISPLAY)
                 .define(KEY_CONVERTER_CLASS_CONFIG, Type.CLASS, null, Importance.LOW, KEY_CONVERTER_CLASS_DOC, COMMON_GROUP, ++orderInGroup, Width.SHORT, KEY_CONVERTER_CLASS_DISPLAY)
@@ -136,11 +170,22 @@ public class ConnectorConfig extends AbstractConfig {
                         }
                     }
                 }), Importance.LOW, TRANSFORMS_DOC, TRANSFORMS_GROUP, ++orderInGroup, Width.LONG, TRANSFORMS_DISPLAY)
                 .define(CONFIG_RELOAD_ACTION_CONFIG, Type.STRING, CONFIG_RELOAD_ACTION_RESTART,
                         in(CONFIG_RELOAD_ACTION_NONE, CONFIG_RELOAD_ACTION_RESTART), Importance.LOW,
-                        CONFIG_RELOAD_ACTION_DOC, COMMON_GROUP, ++orderInGroup, Width.MEDIUM, CONFIG_RELOAD_ACTION_DISPLAY);
+                        CONFIG_RELOAD_ACTION_DOC, COMMON_GROUP, ++orderInGroup, Width.MEDIUM, CONFIG_RELOAD_ACTION_DISPLAY)
+                .define(ERRORS_RETRY_TIMEOUT_CONFIG, Type.LONG, ERRORS_RETRY_TIMEOUT_DEFAULT, Importance.MEDIUM,
+                        ERRORS_RETRY_TIMEOUT_DOC, ERROR_GROUP, ++orderInErrorGroup, Width.MEDIUM, ERRORS_RETRY_TIMEOUT_DISPLAY)
+                .define(ERRORS_RETRY_MAX_DELAY_CONFIG, Type.LONG, ERRORS_RETRY_MAX_DELAY_DEFAULT, Importance.MEDIUM,
+                        ERRORS_RETRY_MAX_DELAY_DOC, ERROR_GROUP, ++orderInErrorGroup, Width.MEDIUM, ERRORS_RETRY_MAX_DELAY_DISPLAY)
+                .define(ERRORS_TOLERANCE_CONFIG, Type.STRING, ERRORS_TOLERANCE_DEFAULT.value(),
+                        in(ToleranceType.NONE.value(), ToleranceType.ALL.value()), Importance.MEDIUM,
+                        ERRORS_TOLERANCE_DOC, ERROR_GROUP, ++orderInErrorGroup, Width.SHORT, ERRORS_TOLERANCE_DISPLAY)
+                .define(ERRORS_LOG_ENABLE_CONFIG, Type.BOOLEAN, ERRORS_LOG_ENABLE_DEFAULT, Importance.MEDIUM,
+                        ERRORS_LOG_ENABLE_DOC, ERROR_GROUP, ++orderInErrorGroup, Width.SHORT, ERRORS_LOG_ENABLE_DISPLAY)
+                .define(ERRORS_LOG_INCLUDE_MESSAGES_CONFIG, Type.BOOLEAN, ERRORS_LOG_INCLUDE_MESSAGES_DEFAULT, Importance.MEDIUM,
+                        ERRORS_LOG_INCLUDE_MESSAGES_DOC, ERROR_GROUP, ++orderInErrorGroup, Width.SHORT, ERRORS_LOG_INCLUDE_MESSAGES_DISPLAY);
     }
 
     public ConnectorConfig(Plugins plugins) {
         this(plugins, new HashMap<String, String>());
     }
@@ -160,10 +205,36 @@ public class ConnectorConfig extends AbstractConfig {
     @Override
     public Object get(String key) {
         return enrichedConfig.get(key);
     }
 
+    public long errorRetryTimeout() {
+        return getLong(ERRORS_RETRY_TIMEOUT_CONFIG);
+    }
+
+    public long errorMaxDelayInMillis() {
+        return getLong(ERRORS_RETRY_MAX_DELAY_CONFIG);
+    }
+
+    public ToleranceType errorToleranceType() {
+        String tolerance = getString(ERRORS_TOLERANCE_CONFIG);
+        for (ToleranceType type: ToleranceType.values()) {
+            if (type.name().equalsIgnoreCase(tolerance)) {
+                return type;
+            }
+        }
+        return ERRORS_TOLERANCE_DEFAULT;
+    }
+
+    public boolean enableErrorLog() {
+        return getBoolean(ERRORS_LOG_ENABLE_CONFIG);
+    }
+
+    public boolean includeRecordDetailsInErrorLog() {
+        return getBoolean(ERRORS_LOG_INCLUDE_MESSAGES_CONFIG);
+    }
+
     /**
      * Returns the initialized list of {@link Transformation} which are specified in {@link #TRANSFORMS_CONFIG}.
      */
     public <R extends ConnectRecord<R>> List<Transformation<R>> transformations() {
         final List<String> transformAliases = getList(TRANSFORMS_CONFIG);
```

### `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/SinkConnectorConfig.java`

```diff
diff --git a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/SinkConnectorConfig.java b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/SinkConnectorConfig.java
index 887a4da2de..9629f8f0e4 100644
--- a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/SinkConnectorConfig.java
+++ b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/SinkConnectorConfig.java
@@ -15,10 +15,11 @@
  * limitations under the License.
  */
 package org.apache.kafka.connect.runtime;
 
 import org.apache.kafka.common.config.ConfigDef;
+import org.apache.kafka.common.config.ConfigDef.Importance;
 import org.apache.kafka.common.config.ConfigException;
 import org.apache.kafka.connect.runtime.isolation.Plugins;
 import org.apache.kafka.connect.sink.SinkTask;
 import org.apache.kafka.connect.transforms.util.RegexValidator;
 
@@ -40,13 +41,23 @@ public class SinkConnectorConfig extends ConnectorConfig {
         "Under the hood, the regex is compiled to a <code>java.util.regex.Pattern</code>. " +
         "Only one of " + TOPICS_CONFIG + " or " + TOPICS_REGEX_CONFIG + " should be specified.";
     public static final String TOPICS_REGEX_DEFAULT = "";
     private static final String TOPICS_REGEX_DISPLAY = "Topics regex";
 
+    public static final String DLQ_PREFIX = "errors.deadletterqueue.";
+
+    public static final String DLQ_TOPIC_NAME_CONFIG = DLQ_PREFIX + "topic.name";
+    public static final String DLQ_TOPIC_NAME_DOC = "The name of the topic to be used as the dead letter queue (DLQ) for messages that " +
+        "result in an error when processed by this sink connector, or its transformations or converters. The topic name is blank by default, " +
+        "which means that no messages are to be recorded in the DLQ.";
+    public static final String DLQ_TOPIC_DEFAULT = "";
+    private static final String DLQ_TOPIC_DISPLAY = "Dead Letter Queue Topic Name";
+
     static ConfigDef config = ConnectorConfig.configDef()
         .define(TOPICS_CONFIG, ConfigDef.Type.LIST, TOPICS_DEFAULT, ConfigDef.Importance.HIGH, TOPICS_DOC, COMMON_GROUP, 4, ConfigDef.Width.LONG, TOPICS_DISPLAY)
-        .define(TOPICS_REGEX_CONFIG, ConfigDef.Type.STRING, TOPICS_REGEX_DEFAULT, new RegexValidator(), ConfigDef.Importance.HIGH, TOPICS_REGEX_DOC, COMMON_GROUP, 4, ConfigDef.Width.LONG, TOPICS_REGEX_DISPLAY);
+        .define(TOPICS_REGEX_CONFIG, ConfigDef.Type.STRING, TOPICS_REGEX_DEFAULT, new RegexValidator(), ConfigDef.Importance.HIGH, TOPICS_REGEX_DOC, COMMON_GROUP, 4, ConfigDef.Width.LONG, TOPICS_REGEX_DISPLAY)
+        .define(DLQ_TOPIC_NAME_CONFIG, ConfigDef.Type.STRING, DLQ_TOPIC_DEFAULT, Importance.MEDIUM, DLQ_TOPIC_NAME_DOC, ERROR_GROUP, 6, ConfigDef.Width.MEDIUM, DLQ_TOPIC_DISPLAY);
 
     public static ConfigDef configDef() {
         return config;
     }
 
@@ -81,6 +92,9 @@ public class SinkConnectorConfig extends ConnectorConfig {
     public static boolean hasTopicsRegexConfig(Map<String, String> props) {
         String topicsRegexStr = props.get(TOPICS_REGEX_CONFIG);
         return topicsRegexStr != null && !topicsRegexStr.trim().isEmpty();
     }
 
+    public String dlqTopicName() {
+        return getString(DLQ_TOPIC_NAME_CONFIG);
+    }
 }
```

### `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/Worker.java`

```diff
diff --git a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/Worker.java b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/Worker.java
index 7a72a0e7b2..97e68faa4c 100644
--- a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/Worker.java
+++ b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/Worker.java
@@ -483,12 +483,12 @@ public class Worker {
                                        Converter valueConverter,
                                        HeaderConverter headerConverter,
                                        ClassLoader loader) {
         ErrorHandlingMetrics errorHandlingMetrics = errorHandlingMetrics(id);
 
-        RetryWithToleranceOperator retryWithToleranceOperator = new RetryWithToleranceOperator();
-        retryWithToleranceOperator.configure(connConfig.originalsWithPrefix("errors."));
+        RetryWithToleranceOperator retryWithToleranceOperator = new RetryWithToleranceOperator(connConfig.errorRetryTimeout(),
+                connConfig.errorMaxDelayInMillis(), connConfig.errorToleranceType(), Time.SYSTEM);
         retryWithToleranceOperator.metrics(errorHandlingMetrics);
 
         // Decide which type of worker task we need based on the type of task.
         if (task instanceof SourceTask) {
             retryWithToleranceOperator.reporters(sourceTaskReporters(id, connConfig, errorHandlingMetrics));
@@ -503,11 +503,12 @@ public class Worker {
             return new WorkerSourceTask(id, (SourceTask) task, statusListener, initialState, keyConverter, valueConverter,
                     headerConverter, transformationChain, producer, offsetReader, offsetWriter, config, configState, metrics, loader,
                     time, retryWithToleranceOperator);
         } else if (task instanceof SinkTask) {
             TransformationChain<SinkRecord> transformationChain = new TransformationChain<>(connConfig.<SinkRecord>transformations(), retryWithToleranceOperator);
-            retryWithToleranceOperator.reporters(sinkTaskReporters(id, connConfig, errorHandlingMetrics));
+            SinkConnectorConfig sinkConfig = new SinkConnectorConfig(plugins, connConfig.originalsStrings());
+            retryWithToleranceOperator.reporters(sinkTaskReporters(id, sinkConfig, errorHandlingMetrics));
             return new WorkerSinkTask(id, (SinkTask) task, statusListener, initialState, config, configState, metrics, keyConverter,
                     valueConverter, headerConverter, transformationChain, loader, time,
                     retryWithToleranceOperator);
         } else {
             log.error("Tasks must be a subclass of either SourceTask or SinkTask", task);
@@ -517,34 +518,31 @@ public class Worker {
 
     ErrorHandlingMetrics errorHandlingMetrics(ConnectorTaskId id) {
         return new ErrorHandlingMetrics(id, metrics);
     }
 
-    private List<ErrorReporter> sinkTaskReporters(ConnectorTaskId id, ConnectorConfig connConfig,
-                                                    ErrorHandlingMetrics errorHandlingMetrics) {
+    private List<ErrorReporter> sinkTaskReporters(ConnectorTaskId id, SinkConnectorConfig connConfig,
+                                                  ErrorHandlingMetrics errorHandlingMetrics) {
         ArrayList<ErrorReporter> reporters = new ArrayList<>();
-        LogReporter logReporter = new LogReporter(id);
-        logReporter.configure(connConfig.originalsWithPrefix(LogReporter.PREFIX + "."));
+        LogReporter logReporter = new LogReporter(id, connConfig);
         logReporter.metrics(errorHandlingMetrics);
         reporters.add(logReporter);
 
         // check if topic for dead letter queue exists
-        String topic = connConfig.getString(DeadLetterQueueReporter.PREFIX + "." + DeadLetterQueueReporter.DLQ_TOPIC_NAME);
+        String topic = connConfig.dlqTopicName();
         if (topic != null && !topic.isEmpty()) {
             DeadLetterQueueReporter reporter = DeadLetterQueueReporter.createAndSetup(config, connConfig, producerProps);
-            reporter.configure(connConfig.originalsWithPrefix(DeadLetterQueueReporter.PREFIX + "."));
             reporters.add(reporter);
         }
 
         return reporters;
     }
 
     private List<ErrorReporter> sourceTaskReporters(ConnectorTaskId id, ConnectorConfig connConfig,
                                                       ErrorHandlingMetrics errorHandlingMetrics) {
         List<ErrorReporter> reporters = new ArrayList<>();
-        LogReporter logReporter = new LogReporter(id);
-        logReporter.configure(connConfig.originalsWithPrefix(LogReporter.PREFIX + "."));
+        LogReporter logReporter = new LogReporter(id, connConfig);
         logReporter.metrics(errorHandlingMetrics);
         reporters.add(logReporter);
 
         return reporters;
     }
```

### `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/DeadLetterQueueReporter.java`

```diff
diff --git a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/DeadLetterQueueReporter.java b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/DeadLetterQueueReporter.java
index 454a619ec7..9a8a9afb29 100644
--- a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/DeadLetterQueueReporter.java
+++ b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/DeadLetterQueueReporter.java
@@ -19,16 +19,14 @@ package org.apache.kafka.connect.runtime.errors;
 import org.apache.kafka.clients.admin.AdminClient;
 import org.apache.kafka.clients.admin.NewTopic;
 import org.apache.kafka.clients.consumer.ConsumerRecord;
 import org.apache.kafka.clients.producer.KafkaProducer;
 import org.apache.kafka.clients.producer.ProducerRecord;
-import org.apache.kafka.common.config.AbstractConfig;
-import org.apache.kafka.common.config.ConfigDef;
 import org.apache.kafka.common.errors.TopicExistsException;
 import org.apache.kafka.common.record.RecordBatch;
 import org.apache.kafka.connect.errors.ConnectException;
-import org.apache.kafka.connect.runtime.ConnectorConfig;
+import org.apache.kafka.connect.runtime.SinkConnectorConfig;
 import org.apache.kafka.connect.runtime.WorkerConfig;
 import org.slf4j.Logger;
 import org.slf4j.LoggerFactory;
 
 import java.util.Map;
@@ -47,26 +45,18 @@ public class DeadLetterQueueReporter implements ErrorReporter {
     private static final Logger log = LoggerFactory.getLogger(DeadLetterQueueReporter.class);
 
     private static final short DLQ_MAX_DESIRED_REPLICATION_FACTOR = 3;
     private static final int DLQ_NUM_DESIRED_PARTITIONS = 1;
 
-    public static final String PREFIX = "errors.deadletterqueue";
+    private final SinkConnectorConfig connConfig;
 
-    public static final String DLQ_TOPIC_NAME = "topic.name";
-    public static final String DLQ_TOPIC_NAME_DOC = "The name of the topic where these messages are written to.";
-    public static final String DLQ_TOPIC_DEFAULT = "";
-
-    private DeadLetterQueueReporterConfig config;
     private KafkaProducer<byte[], byte[]> kafkaProducer;
     private ErrorHandlingMetrics errorHandlingMetrics;
 
-    private static final ConfigDef CONFIG_DEF = new ConfigDef()
-            .define(DLQ_TOPIC_NAME, ConfigDef.Type.STRING, DLQ_TOPIC_DEFAULT, ConfigDef.Importance.HIGH, DLQ_TOPIC_NAME_DOC);
-
     public static DeadLetterQueueReporter createAndSetup(WorkerConfig workerConfig,
-                                                         ConnectorConfig connConfig, Map<String, Object> producerProps) {
-        String topic = connConfig.getString(PREFIX + "." + DLQ_TOPIC_NAME);
+                                                         SinkConnectorConfig connConfig, Map<String, Object> producerProps) {
+        String topic = connConfig.dlqTopicName();
 
         try (AdminClient admin = AdminClient.create(workerConfig.originals())) {
             if (!admin.listTopics().names().get().contains(topic)) {
                 log.error("Topic {} doesn't exist. Will attempt to create topic.", topic);
                 NewTopic schemaTopicRequest = new NewTopic(topic, DLQ_NUM_DESIRED_PARTITIONS, DLQ_MAX_DESIRED_REPLICATION_FACTOR);
@@ -79,26 +69,22 @@ public class DeadLetterQueueReporter implements ErrorReporter {
                 throw new ConnectException("Could not initialize dead letter queue with topic=" + topic, e);
             }
         }
 
         KafkaProducer<byte[], byte[]> dlqProducer = new KafkaProducer<>(producerProps);
-        return new DeadLetterQueueReporter(dlqProducer);
+        return new DeadLetterQueueReporter(dlqProducer, connConfig);
     }
 
     /**
      * Initialize the dead letter queue reporter with a {@link KafkaProducer}.
      *
      * @param kafkaProducer a Kafka Producer to produce the original consumed records.
      */
     // Visible for testing
-    DeadLetterQueueReporter(KafkaProducer<byte[], byte[]> kafkaProducer) {
+    DeadLetterQueueReporter(KafkaProducer<byte[], byte[]> kafkaProducer, SinkConnectorConfig connConfig) {
         this.kafkaProducer = kafkaProducer;
-    }
-
-    @Override
-    public void configure(Map<String, ?> configs) {
-        config = new DeadLetterQueueReporterConfig(configs);
+        this.connConfig = connConfig;
     }
 
     @Override
     public void metrics(ErrorHandlingMetrics errorHandlingMetrics) {
         this.errorHandlingMetrics = errorHandlingMetrics;
@@ -108,11 +94,12 @@ public class DeadLetterQueueReporter implements ErrorReporter {
      * Write the raw records into a Kafka topic.
      *
      * @param context processing context containing the raw record at {@link ProcessingContext#consumerRecord()}.
      */
     public void report(ProcessingContext context) {
-        if (config.topic().isEmpty()) {
+        final String dlqTopicName = connConfig.dlqTopicName();
+        if (dlqTopicName.isEmpty()) {
             return;
         }
 
         errorHandlingMetrics.recordDeadLetterQueueProduceRequest();
 
@@ -122,33 +109,20 @@ public class DeadLetterQueueReporter implements ErrorReporter {
             return;
         }
 
         ProducerRecord<byte[], byte[]> producerRecord;
         if (originalMessage.timestamp() == RecordBatch.NO_TIMESTAMP) {
-            producerRecord = new ProducerRecord<>(config.topic(), null,
+            producerRecord = new ProducerRecord<>(dlqTopicName, null,
                     originalMessage.key(), originalMessage.value(), originalMessage.headers());
         } else {
-            producerRecord = new ProducerRecord<>(config.topic(), null, originalMessage.timestamp(),
+            producerRecord = new ProducerRecord<>(dlqTopicName, null, originalMessage.timestamp(),
                     originalMessage.key(), originalMessage.value(), originalMessage.headers());
         }
 
         this.kafkaProducer.send(producerRecord, (metadata, exception) -> {
             if (exception != null) {
-                log.error("Could not produce message to dead letter queue. topic=" + config.topic(), exception);
+                log.error("Could not produce message to dead letter queue. topic=" + dlqTopicName, exception);
                 errorHandlingMetrics.recordDeadLetterQueueProduceFailed();
             }
         });
     }
-
-    static class DeadLetterQueueReporterConfig extends AbstractConfig {
-        public DeadLetterQueueReporterConfig(Map<?, ?> originals) {
-            super(CONFIG_DEF, originals, true);
-        }
-
-        /**
-         * @return name of the dead letter queue topic.
-         */
-        public String topic() {
-            return getString(DLQ_TOPIC_NAME);
-        }
-    }
 }
```

### `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ErrorReporter.java`

```diff
diff --git a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ErrorReporter.java b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ErrorReporter.java
index e71b6bc8ba..f7df1b2d1a 100644
--- a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ErrorReporter.java
+++ b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ErrorReporter.java
@@ -14,16 +14,14 @@
  * See the License for the specific language governing permissions and
  * limitations under the License.
  */
 package org.apache.kafka.connect.runtime.errors;
 
-import org.apache.kafka.common.Configurable;
-
 /**
  * Report an error using the information contained in the {@link ProcessingContext}.
  */
-public interface ErrorReporter extends Configurable {
+public interface ErrorReporter {
 
     /**
      * Report an error.
      *
      * @param context the processing context (cannot be null).
```

### `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/LogReporter.java`

```diff
diff --git a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/LogReporter.java b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/LogReporter.java
index 1d2c08fd18..e81bd54756 100644
--- a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/LogReporter.java
+++ b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/LogReporter.java
@@ -14,56 +14,40 @@
  * See the License for the specific language governing permissions and
  * limitations under the License.
  */
 package org.apache.kafka.connect.runtime.errors;
 
-import org.apache.kafka.common.config.AbstractConfig;
-import org.apache.kafka.common.config.ConfigDef;
+import org.apache.kafka.connect.runtime.ConnectorConfig;
 import org.apache.kafka.connect.util.ConnectorTaskId;
 import org.slf4j.Logger;
 import org.slf4j.LoggerFactory;
 
-import java.util.Map;
-
 /**
  * Writes errors and their context to application logs.
  */
 public class LogReporter implements ErrorReporter {
 
     private static final Logger log = LoggerFactory.getLogger(LogReporter.class);
 
-    public static final String PREFIX = "errors.log";
-
-    public static final String LOG_ENABLE = "enable";
-    public static final String LOG_ENABLE_DOC = "If true, log to application logs the errors and the information describing where they occurred.";
-    public static final boolean LOG_ENABLE_DEFAULT = false;
-
-    public static final String LOG_INCLUDE_MESSAGES = "include.messages";
-    public static final String LOG_INCLUDE_MESSAGES_DOC = "If true, include in the application log the Connect key, value, and other details of records that resulted in errors and failures.";
-    public static final boolean LOG_INCLUDE_MESSAGES_DEFAULT = false;
-
     private final ConnectorTaskId id;
+    private final ConnectorConfig connConfig;
 
-    private LogReporterConfig config;
     private ErrorHandlingMetrics errorHandlingMetrics;
 
-    public LogReporter(ConnectorTaskId id) {
+    public LogReporter(ConnectorTaskId id, ConnectorConfig connConfig) {
         this.id = id;
+        this.connConfig = connConfig;
     }
 
-    private static final ConfigDef CONFIG_DEF = new ConfigDef()
-                .define(LOG_ENABLE, ConfigDef.Type.BOOLEAN, LOG_ENABLE_DEFAULT, ConfigDef.Importance.MEDIUM, LOG_ENABLE_DOC)
-                .define(LOG_INCLUDE_MESSAGES, ConfigDef.Type.BOOLEAN, LOG_INCLUDE_MESSAGES_DEFAULT, ConfigDef.Importance.MEDIUM, LOG_INCLUDE_MESSAGES_DOC);
-
     /**
      * Log error context.
      *
      * @param context the processing context.
      */
     @Override
     public void report(ProcessingContext context) {
-        if (!config.isEnabled()) {
+        if (!connConfig.enableErrorLog()) {
             return;
         }
 
         if (!context.failed()) {
             return;
@@ -78,34 +62,10 @@ public class LogReporter implements ErrorReporter {
         this.errorHandlingMetrics = errorHandlingMetrics;
     }
 
     // Visible for testing
     String message(ProcessingContext context) {
-        return String.format("Error encountered in task %s. %s", String.valueOf(id), context.toString(config.canLogMessages()));
-    }
-
-    @Override
-    public void configure(Map<String, ?> configs) {
-        config = new LogReporterConfig(configs);
-    }
-
-    private static class LogReporterConfig extends AbstractConfig {
-        public LogReporterConfig(Map<?, ?> originals) {
-            super(CONFIG_DEF, originals, true);
-        }
-
-        /**
-         * @return true, if logging of error context is desired; false otherwise.
-         */
-        public boolean isEnabled() {
-            return getBoolean(LOG_ENABLE);
-        }
-
-        /**
-         * @return if false, the connect record which caused the exception is not logged.
-         */
-        public boolean canLogMessages() {
-            return getBoolean(LOG_INCLUDE_MESSAGES);
-        }
+        return String.format("Error encountered in task %s. %s", String.valueOf(id),
+                context.toString(connConfig.includeRecordDetailsInErrorLog()));
     }
 
 }
```

### `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/RetryWithToleranceOperator.java`

```diff
diff --git a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/RetryWithToleranceOperator.java b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/RetryWithToleranceOperator.java
index 941abf3d3d..eadf276adb 100644
--- a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/RetryWithToleranceOperator.java
+++ b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/RetryWithToleranceOperator.java
@@ -15,41 +15,35 @@
  * limitations under the License.
  */
 package org.apache.kafka.connect.runtime.errors;
 
 import org.apache.kafka.clients.consumer.ConsumerRecord;
-import org.apache.kafka.common.config.AbstractConfig;
-import org.apache.kafka.common.config.ConfigDef;
 import org.apache.kafka.common.config.ConfigException;
-import org.apache.kafka.common.utils.SystemTime;
 import org.apache.kafka.common.utils.Time;
 import org.apache.kafka.connect.errors.ConnectException;
 import org.apache.kafka.connect.errors.RetriableException;
+import org.apache.kafka.connect.runtime.ConnectorConfig;
 import org.apache.kafka.connect.source.SourceRecord;
 import org.slf4j.Logger;
 import org.slf4j.LoggerFactory;
 
-import java.util.Collections;
 import java.util.HashMap;
 import java.util.List;
 import java.util.Map;
 import java.util.concurrent.ThreadLocalRandom;
 
-import static org.apache.kafka.common.config.ConfigDef.Range.atLeast;
-import static org.apache.kafka.common.config.ConfigDef.ValidString.in;
-
 /**
  * Attempt to recover a failed operation with retries and tolerance limits.
  * <p>
  *
  * A retry is attempted if the operation throws a {@link RetriableException}. Retries are accompanied by exponential backoffs, starting with
- * {@link #RETRIES_DELAY_MIN_MS}, up to what is specified with {@link RetryWithToleranceOperatorConfig#retryDelayMax()}.
+ * {@link #RETRIES_DELAY_MIN_MS}, up to what is specified with {@link ConnectorConfig#errorMaxDelayInMillis()}.
  * Including the first attempt and future retries, the total time taken to evaluate the operation should be within
- * {@link RetryWithToleranceOperatorConfig#retryDelayMax()} millis.
+ * {@link ConnectorConfig#errorMaxDelayInMillis()} millis.
  * <p>
  *
- * This executor will tolerate failures, as specified by {@link RetryWithToleranceOperatorConfig#toleranceLimit()}.
+ * This executor will tolerate failures, as specified by {@link ConnectorConfig#errorToleranceType()}.
  * For transformations and converters, all exceptions are tolerated. For others operations, only {@link RetriableException} are tolerated.
  * <p>
  *
  * There are three outcomes to executing an operation. It might succeed, in which case the result is returned to the caller.
  * If it fails, this class does one of these two things: (1) if the failure occurred due to a tolerable exception, then
@@ -59,62 +53,38 @@ import static org.apache.kafka.common.config.ConfigDef.ValidString.in;
  */
 public class RetryWithToleranceOperator {
 
     private static final Logger log = LoggerFactory.getLogger(RetryWithToleranceOperator.class);
 
-    public static final String RETRY_TIMEOUT = "retry.timeout";
-    public static final String RETRY_TIMEOUT_DOC = "The total duration in milliseconds a failed operation will be retried for.";
-    public static final long RETRY_TIMEOUT_DEFAULT = 0;
-
-    public static final String RETRY_DELAY_MAX_MS = "retry.delay.max.ms";
-    public static final String RETRY_DELAY_MAX_MS_DOC = "The maximum duration between two consecutive retries (in milliseconds).";
-    public static final long RETRY_DELAY_MAX_MS_DEFAULT = 60000;
-
     public static final long RETRIES_DELAY_MIN_MS = 300;
 
-    public static final String TOLERANCE_LIMIT = "allowed.max";
-    public static final String TOLERANCE_LIMIT_DOC = "Fail the task if we exceed specified number of errors overall.";
-    public static final String TOLERANCE_LIMIT_DEFAULT = "none";
-
-    // for testing only
-    public static final RetryWithToleranceOperator NOOP_OPERATOR = new RetryWithToleranceOperator();
-    static {
-        NOOP_OPERATOR.configure(Collections.emptyMap());
-        NOOP_OPERATOR.metrics(new ErrorHandlingMetrics());
-    }
-
     private static final Map<Stage, Class<? extends Exception>> TOLERABLE_EXCEPTIONS = new HashMap<>();
     static {
         TOLERABLE_EXCEPTIONS.put(Stage.TRANSFORMATION, Exception.class);
         TOLERABLE_EXCEPTIONS.put(Stage.HEADER_CONVERTER, Exception.class);
         TOLERABLE_EXCEPTIONS.put(Stage.KEY_CONVERTER, Exception.class);
         TOLERABLE_EXCEPTIONS.put(Stage.VALUE_CONVERTER, Exception.class);
     }
 
+    private final long errorRetryTimeout;
+    private final long errorMaxDelayInMillis;
+    private final ToleranceType errorToleranceType;
+
     private long totalFailures = 0;
     private final Time time;
-    private RetryWithToleranceOperatorConfig config;
     private ErrorHandlingMetrics errorHandlingMetrics;
 
     protected ProcessingContext context = new ProcessingContext();
 
-    public RetryWithToleranceOperator() {
-        this(new SystemTime());
-    }
-
-    // Visible for testing
-    public RetryWithToleranceOperator(Time time) {
+    public RetryWithToleranceOperator(long errorRetryTimeout, long errorMaxDelayInMillis,
+                                      ToleranceType toleranceType, Time time) {
+        this.errorRetryTimeout = errorRetryTimeout;
+        this.errorMaxDelayInMillis = errorMaxDelayInMillis;
+        this.errorToleranceType = toleranceType;
         this.time = time;
     }
 
-    static ConfigDef getConfigDef() {
-        return new ConfigDef()
-                .define(RETRY_TIMEOUT, ConfigDef.Type.LONG, RETRY_TIMEOUT_DEFAULT, ConfigDef.Importance.HIGH, RETRY_TIMEOUT_DOC)
-                .define(RETRY_DELAY_MAX_MS, ConfigDef.Type.LONG, RETRY_DELAY_MAX_MS_DEFAULT, atLeast(1), ConfigDef.Importance.MEDIUM, RETRY_DELAY_MAX_MS_DOC)
-                .define(TOLERANCE_LIMIT, ConfigDef.Type.STRING, TOLERANCE_LIMIT_DEFAULT, in("none", "all"), ConfigDef.Importance.HIGH, TOLERANCE_LIMIT_DOC);
-    }
-
     /**
      * Execute the recoverable operation. If the operation is already in a failed state, then simply return
      * with the existing failure.
      *
      * @param operation the recoverable operation
@@ -149,11 +119,11 @@ public class RetryWithToleranceOperator {
      * @throws Exception rethrow if a non-retriable Exception is thrown by the operation
      */
     protected <V> V execAndRetry(Operation<V> operation) throws Exception {
         int attempt = 0;
         long startTime = time.milliseconds();
-        long deadline = startTime + config.retryTimeout();
+        long deadline = startTime + errorRetryTimeout;
         do {
             try {
                 attempt++;
                 return operation.call();
             } catch (RetriableException e) {
@@ -219,78 +189,52 @@ public class RetryWithToleranceOperator {
         totalFailures++;
     }
 
     // Visible for testing
     boolean withinToleranceLimits() {
-        switch (config.toleranceLimit()) {
+        switch (errorToleranceType) {
             case NONE:
                 if (totalFailures > 0) return false;
             case ALL:
                 return true;
             default:
-                throw new ConfigException("Unknown tolerance type: {}", config.toleranceLimit());
+                throw new ConfigException("Unknown tolerance type: {}", errorToleranceType);
         }
     }
 
     // Visible for testing
     boolean checkRetry(long startTime) {
-        return (time.milliseconds() - startTime) < config.retryTimeout();
+        return (time.milliseconds() - startTime) < errorRetryTimeout;
     }
 
     // Visible for testing
     void backoff(int attempt, long deadline) {
         int numRetry = attempt - 1;
         long delay = RETRIES_DELAY_MIN_MS << numRetry;
-        if (delay > config.retryDelayMax()) {
-            delay = ThreadLocalRandom.current().nextLong(config.retryDelayMax());
+        if (delay > errorMaxDelayInMillis) {
+            delay = ThreadLocalRandom.current().nextLong(errorMaxDelayInMillis);
         }
         if (delay + time.milliseconds() > deadline) {
             delay = deadline - time.milliseconds();
         }
         log.debug("Sleeping for {} millis", delay);
         time.sleep(delay);
     }
 
-    public void configure(Map<String, ?> configs) {
-        config = new RetryWithToleranceOperatorConfig(configs);
-    }
-
     public void metrics(ErrorHandlingMetrics errorHandlingMetrics) {
         this.errorHandlingMetrics = errorHandlingMetrics;
     }
 
-    static class RetryWithToleranceOperatorConfig extends AbstractConfig {
-        public RetryWithToleranceOperatorConfig(Map<?, ?> originals) {
-            super(getConfigDef(), originals, true);
-        }
-
-        /**
-         * @return the total time an operation can take to succeed (including the first attempt and retries).
-         */
-        public long retryTimeout() {
-            return getLong(RETRY_TIMEOUT);
-        }
-
-        /**
-         * @return the maximum delay between two subsequent retries in milliseconds.
-         */
-        public long retryDelayMax() {
-            return getLong(RETRY_DELAY_MAX_MS);
-        }
-
-        /**
-         * @return determine how many errors to tolerate.
-         */
-        public ToleranceType toleranceLimit() {
-            return ToleranceType.fromString(getString(TOLERANCE_LIMIT));
-        }
-    }
-
     @Override
     public String toString() {
         return "RetryWithToleranceOperator{" +
-                "config=" + config +
+                "errorRetryTimeout=" + errorRetryTimeout +
+                ", errorMaxDelayInMillis=" + errorMaxDelayInMillis +
+                ", errorToleranceType=" + errorToleranceType +
+                ", totalFailures=" + totalFailures +
+                ", time=" + time +
+                ", context=" + context +
                 '}';
     }
 
     /**
      * Set the error reporters for this connector.
```

### `connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ToleranceType.java`

```diff
diff --git a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ToleranceType.java b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ToleranceType.java
index 79956ac796..dd40a60648 100644
--- a/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ToleranceType.java
+++ b/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/errors/ToleranceType.java
@@ -31,9 +31,10 @@ public enum ToleranceType {
     /**
      * Tolerate all errors.
      */
     ALL;
 
-    public static ToleranceType fromString(String typeStr) {
-        return "ALL".equals(typeStr.toUpperCase(Locale.ROOT)) ? ToleranceType.ALL : ToleranceType.NONE;
+    public String value() {
+        return name().toLowerCase(Locale.ROOT);
     }
+
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
