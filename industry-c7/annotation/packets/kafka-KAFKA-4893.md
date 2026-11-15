# Annotation packet: KAFKA-4893  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
async topic deletion conflicts with max topic length

As per the [documentation|http://kafka.apache.org/documentation/#basic_ops_add_topic], topics can be only 249 characters long to line up with typical filesystem limitations:
{quote}
Each sharded partition log is placed into its own folder under the Kafka log directory. The name of such folders consists of the topic name, appended by a dash (\-) and the partition id. Since a typical folder name can not be over 255 characters long, there will be a limitation on the length of topic names. We assume the number of partitions will not ever be above 100,000. Therefore, topic names cannot be longer than 249 characters. This leaves just enough room in the folder name for a dash and a potentially 5 digit long partition id.
{quote}

{{kafka.common.Topic.maxNameLength}} is set to 249 and is used during validation.

This limit ends up not being quite right since topic deletion ends up renaming the directory to the form {{topic-partition.uniqueId-delete}} as can be seen in {{LogManager.asyncDelete}}:
{code}
val dirName = new StringBuilder(removedLog.name)
                  .append(".")
                  .append(java.util.UUID.randomUUID.toString.replaceAll("-",""))
                  .append(Log.DeleteDirSuffix)
                  .toString()
{code}

So the unique id and "-delete" suffix end up hogging some of the characters. Deleting a long-named topic results in a log message such as the following:
{code}
kafka.common.KafkaStorageException: Failed to rename log directory from /tmp/kafka-logs0/000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000-0 to /tmp/kafka-logs0/000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000-0.797bba3fb2464729840f87769243edbb-delete
  at kafka.log.LogManager.asyncDelete(LogManager.scala:439)
  at kafka.cluster.Partition$$anonfun$delete$1.apply$mcV$sp(Partition.scala:142)
  at kafka.cluster.Partition$$anonfun$delete$1.apply(Partition.scala:137)
  at kafka.cluster.Partition$$anonfun$delete$1.apply(Partition.scala:137)
  at kafka.utils.CoreUtils$.inLock(CoreUtils.scala:213)
  at kafka.utils.CoreUtils$.inWriteLock(CoreUtils.scala:221)
  at kafka.cluster.Partition.delete(Partition.scala:137)
  at kafka.server.ReplicaManager.stopReplica(ReplicaManager.scala:230)
  at kafka.server.ReplicaManager$$anonfun$stopReplicas$2.apply(ReplicaManager.scala:260)
  at kafka.server.ReplicaManager$$anonfun$stopReplicas$2.apply(ReplicaManager.scala:259)
  at scala.collection.Iterator$class.foreach(Iterator.scala:727)
  at scala.collection.AbstractIterator.foreach(Iterator.scala:1157)
  at scala.collection.IterableLike$class.foreach(IterableLike.scala:72)
  at scala.collection.AbstractIterable.foreach(Iterable.scala:54)
  at kafka.server.ReplicaManager.stopReplicas(ReplicaManager.scala:259)
  at kafka.server.KafkaApis.handleStopReplicaRequest(KafkaApis.scala:174)
  at kafka.server.KafkaApis.handle(KafkaApis.scala:86)
  at kafka.server.KafkaRequestHandler.run(KafkaRequestHandler.scala:64)
  at java.lang.Thread.run(Thread.java:745)
{code}

The topic after this point still exists but has Leader set to -1 and the controller recognizes the topic completion as incomplete (the topic znode is still in /admin/delete_topics).

I don't believe linkedin has any topic name this long but I'm making the ticket in case anyone runs into this problem.
```

## Fix commit message(s)

`e6563aab722b`

```
KAFKA-4893; Fix deletion and moving of topics with long names

Author: Colin P. Mccabe <cmccabe@confluent.io>

Reviewers: Gwen Shapira, David Arthur, James Cheng, Vahid Hashemian

Closes #6869 from cmccabe/KAFKA-4893
```

## Files the fix changed

Snapshot holds 1,671 non-test source files. The fix changed 5 file(s); 2 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/log/Log.scala`
- `core/src/main/scala/kafka/server/ReplicaManager.scala`

## The fix diff

### `core/src/main/scala/kafka/log/Log.scala`

```diff
diff --git a/core/src/main/scala/kafka/log/Log.scala b/core/src/main/scala/kafka/log/Log.scala
index 56b2969e2b..9ab6fda309 100644
--- a/core/src/main/scala/kafka/log/Log.scala
+++ b/core/src/main/scala/kafka/log/Log.scala
@@ -2178,12 +2178,12 @@ object Log {
   val DeleteDirSuffix = "-delete"
 
   /** a directory that is used for future partition */
   val FutureDirSuffix = "-future"
 
-  private val DeleteDirPattern = Pattern.compile(s"^(\\S+)-(\\S+)\\.(\\S+)$DeleteDirSuffix")
-  private val FutureDirPattern = Pattern.compile(s"^(\\S+)-(\\S+)\\.(\\S+)$FutureDirSuffix")
+  private[log] val DeleteDirPattern = Pattern.compile(s"^(\\S+)-(\\S+)\\.(\\S+)$DeleteDirSuffix")
+  private[log] val FutureDirPattern = Pattern.compile(s"^(\\S+)-(\\S+)\\.(\\S+)$FutureDirSuffix")
 
   val UnknownLogStartOffset = -1L
 
   def apply(dir: File,
             config: LogConfig,
@@ -2225,15 +2225,20 @@ object Log {
    */
   def logFile(dir: File, offset: Long, suffix: String = ""): File =
     new File(dir, filenamePrefixFromOffset(offset) + LogFileSuffix + suffix)
 
   /**
-   * Return a directory name to rename the log directory to for async deletion. The name will be in the following
-   * format: topic-partition.uniqueId-delete where topic, partition and uniqueId are variables.
+   * Return a directory name to rename the log directory to for async deletion.
+   * The name will be in the following format: "topic-partitionId.uniqueId-delete".
+   * If the topic name is too long, it will be truncated to prevent the total name
+   * from exceeding 255 characters.
    */
   def logDeleteDirName(topicPartition: TopicPartition): String = {
-    logDirNameWithSuffix(topicPartition, DeleteDirSuffix)
+    val uniqueId = java.util.UUID.randomUUID.toString.replaceAll("-", "")
+    val suffix = s"-${topicPartition.partition()}.${uniqueId}${DeleteDirSuffix}"
+    val prefixLength = Math.min(topicPartition.topic().size, 255 - suffix.size)
+    s"${topicPartition.topic().substring(0, prefixLength)}${suffix}"
   }
 
   /**
    * Return a future directory name for the given topic partition. The name will be in the following
    * format: topic-partition.uniqueId-future where topic, partition and uniqueId are variables.
```

### `core/src/main/scala/kafka/server/ReplicaManager.scala`

```diff
diff --git a/core/src/main/scala/kafka/server/ReplicaManager.scala b/core/src/main/scala/kafka/server/ReplicaManager.scala
index 8cfa247f39..e9ab738610 100644
--- a/core/src/main/scala/kafka/server/ReplicaManager.scala
+++ b/core/src/main/scala/kafka/server/ReplicaManager.scala
@@ -576,10 +576,15 @@ class ReplicaManager(val config: KafkaConfig,
    */
   def alterReplicaLogDirs(partitionDirs: Map[TopicPartition, String]): Map[TopicPartition, Errors] = {
     replicaStateChangeLock synchronized {
       partitionDirs.map { case (topicPartition, destinationDir) =>
         try {
+          /* If the topic name is exceptionally long, we can't support altering the log directory.
+           * See KAFKA-4893 for details.
+           * TODO: fix this by implementing topic IDs. */
+          if (Log.logFutureDirName(topicPartition).size > 255)
+            throw new InvalidTopicException("The topic name is too long.")
           if (!logManager.isLogDirOnline(destinationDir))
             throw new KafkaStorageException(s"Log directory $destinationDir is offline")
 
           getPartition(topicPartition) match {
             case partition: Partition =>
@@ -619,11 +624,12 @@ class ReplicaManager(val config: KafkaConfig,
             replicaAlterLogDirsManager.addFetcherForPartitions(Map(topicPartition -> initialFetchState))
           }
 
           (topicPartition, Errors.NONE)
         } catch {
-          case e@(_: LogDirNotFoundException |
+          case e@(_: InvalidTopicException |
+                  _: LogDirNotFoundException |
                   _: ReplicaNotAvailableException |
                   _: KafkaStorageException) =>
             (topicPartition, Errors.forException(e))
           case t: Throwable =>
             error("Error while changing replica dir for partition %s".format(topicPartition), t)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
