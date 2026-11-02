# Annotation packet: KAFKA-4558  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
throttling_test fails if the producer starts too fast.

As described in https://issues.apache.org/jira/browse/KAFKA-4526, the throttling test will fail if the producer in the produce-consume-validate loop starts up before the consumer is fully initialized.

We need to block the start of the producer until the consumer is ready to go. 

The current plan is to poll the consumer for a particular metric (like, for instance, partition assignment) which will act as a good proxy for successful initialization. Currently, we just check for the existence of a process with the PID, which is not a strong enough check, causing the test to fail intermittently.
```

## Fix commit message(s)

`d0932b0286d8`

```
KAFKA-4558; throttling_test fails if the producer starts too fast

With this change, the consumer will be considered initialized in the
ProduceConsumeValidate tests once its partitions have been assigned.

Author: Apurva Mehta <apurva.1618@gmail.com>

Reviewers: Ismael Juma <ismael@juma.me.uk>

Closes #2347 from apurvam/KAFKA-4588-fix-race-between-producer-consumer-start
```

## Files the fix changed

Snapshot holds 1,048 non-test source files. The fix changed 5 file(s); 1 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/tools/JmxTool.scala`

## The fix diff

### `core/src/main/scala/kafka/tools/JmxTool.scala`

```diff
diff --git a/core/src/main/scala/kafka/tools/JmxTool.scala b/core/src/main/scala/kafka/tools/JmxTool.scala
index a1ceb03a86..e980084b5b 100644
--- a/core/src/main/scala/kafka/tools/JmxTool.scala
+++ b/core/src/main/scala/kafka/tools/JmxTool.scala
@@ -28,10 +28,17 @@ import joptsimple.OptionParser
 import scala.collection.JavaConverters._
 import scala.collection.mutable
 import scala.math._
 import kafka.utils.{CommandLineUtils, Exit, Logging}
 
+
+/**
+  * A program for reading JMX metrics from a given endpoint.
+  *
+  * This tool only works reliably if the JmxServer is fully initialized prior to invoking the tool. See KAFKA-4620 for
+  * details.
+  */
 object JmxTool extends Logging {
 
   def main(args: Array[String]) {
     // Parse command line
     val parser = new OptionParser
@@ -80,12 +87,36 @@ object JmxTool extends Logging {
     val interval = options.valueOf(reportingIntervalOpt).intValue
     val attributesWhitelistExists = options.has(attributesOpt)
     val attributesWhitelist = if(attributesWhitelistExists) Some(options.valueOf(attributesOpt).split(",")) else None
     val dateFormatExists = options.has(dateFormatOpt)
     val dateFormat = if(dateFormatExists) Some(new SimpleDateFormat(options.valueOf(dateFormatOpt))) else None
-    val jmxc = JMXConnectorFactory.connect(url, null)
-    val mbsc = jmxc.getMBeanServerConnection()
+
+    var jmxc: JMXConnector = null
+    var mbsc: MBeanServerConnection = null
+    var retries = 0
+    val maxNumRetries = 10
+    var connected = false
+    while (retries < maxNumRetries && !connected) {
+      try {
+        System.err.println(s"Trying to connect to JMX url: $url.")
+        jmxc = JMXConnectorFactory.connect(url, null)
+        mbsc = jmxc.getMBeanServerConnection
+        connected = true
+      } catch {
+        case e : Exception =>
+          System.err.println(s"Could not connect to JMX url: $url. Exception ${e.getMessage}.")
+          e.printStackTrace()
+          retries += 1
+          Thread.sleep(500)
+      }
+    }
+
+    if (!connected) {
+      System.err.println(s"Could not connect to JMX url $url after $maxNumRetries retries.")
+      System.err.println("Exiting.")
+      sys.exit(1)
+    }
 
     val queries: Iterable[ObjectName] =
       if(options.has(objectNameOpt))
         options.valuesOf(objectNameOpt).asScala.map(new ObjectName(_))
       else
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
