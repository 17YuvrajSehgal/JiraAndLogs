# Annotation packet: KAFKA-6624  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
log segment deletion could cause a disk to be marked offline incorrectly

Saw the following log.

[2018-03-06 23:12:20,721] ERROR Error while flushing log for topic1-0 in dir /data01/kafka-logs with offset 80993 (kafka.server.LogDirFailureChannel)

java.nio.channels.ClosedChannelException

        at sun.nio.ch.FileChannelImpl.ensureOpen(FileChannelImpl.java:110)

        at sun.nio.ch.FileChannelImpl.force(FileChannelImpl.java:379)

        at org.apache.kafka.common.record.FileRecords.flush(FileRecords.java:163)

        at kafka.log.LogSegment$$anonfun$flush$1.apply$mcV$sp(LogSegment.scala:375)

        at kafka.log.LogSegment$$anonfun$flush$1.apply(LogSegment.scala:374)

        at kafka.log.LogSegment$$anonfun$flush$1.apply(LogSegment.scala:374)

        at kafka.metrics.KafkaTimer.time(KafkaTimer.scala:31)

        at kafka.log.LogSegment.flush(LogSegment.scala:374)

        at kafka.log.Log$$anonfun$flush$1$$anonfun$apply$mcV$sp$4.apply(Log.scala:1374)

        at kafka.log.Log$$anonfun$flush$1$$anonfun$apply$mcV$sp$4.apply(Log.scala:1373)

        at scala.collection.Iterator$class.foreach(Iterator.scala:891)

        at scala.collection.AbstractIterator.foreach(Iterator.scala:1334)

        at scala.collection.IterableLike$class.foreach(IterableLike.scala:72)

        at scala.collection.AbstractIterable.foreach(Iterable.scala:54)

        at kafka.log.Log$$anonfun$flush$1.apply$mcV$sp(Log.scala:1373)

        at kafka.log.Log$$anonfun$flush$1.apply(Log.scala:1368)

        at kafka.log.Log$$anonfun$flush$1.apply(Log.scala:1368)

        at kafka.log.Log.maybeHandleIOException(Log.scala:1669)

        at kafka.log.Log.flush(Log.scala:1368)

        at kafka.log.Log$$anonfun$roll$2$$anonfun$apply$1.apply$mcV$sp(Log.scala:1343)

        at kafka.utils.KafkaScheduler$$anonfun$1.apply$mcV$sp(KafkaScheduler.scala:110)

        at kafka.utils.CoreUtils$$anon$1.run(CoreUtils.scala:61)

        at java.util.concurrent.Executors$RunnableAdapter.call(Executors.java:511)

        at java.util.concurrent.FutureTask.run(FutureTask.java:266)

        at java.util.concurrent.ScheduledThreadPoolExecutor$ScheduledFutureTask.access$201(ScheduledThreadPoolExecutor.java:180)

        at java.util.concurrent.ScheduledThreadPoolExecutor$ScheduledFutureTask.run(ScheduledThreadPoolExecutor.java:293)

        at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1149)

        at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:624)

        at java.lang.Thread.run(Thread.java:748)

[2018-03-06 23:12:20,722] INFO [ReplicaManager broker=0] Stopping serving replicas in dir /data01/kafka-logs (kafka.server.ReplicaManager)

It seems that topic1 was being deleted around the time when flushing was called. Then flushing hit an IOException, which caused the disk to be marked offline incorrectly.
```

## Fix commit message(s)

`1ea07b993d75`

```
KAFKA-6624; Prevent concurrent log flush and log deletion (#4663)

KAFKA-6624; Prevent concurrent log flush and log deletion

Reviewers: Ted Yu <yuzhihong@gmail.com>, Jun Rao <junrao@gmail.com>
```

## Files the fix changed

Snapshot holds 1,494 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/log/LogManager.scala`

## The fix diff

### `core/src/main/scala/kafka/log/LogManager.scala`

```diff
diff --git a/core/src/main/scala/kafka/log/LogManager.scala b/core/src/main/scala/kafka/log/LogManager.scala
index 9ae93aadf0..7aa5bcd88d 100755
--- a/core/src/main/scala/kafka/log/LogManager.scala
+++ b/core/src/main/scala/kafka/log/LogManager.scala
@@ -73,11 +73,12 @@ class LogManager(logDirs: Seq[File],
   private val currentLogs = new Pool[TopicPartition, Log]()
   // Future logs are put in the directory with "-future" suffix. Future log is created when user wants to move replica
   // from one log directory to another log directory on the same broker. The directory of the future log will be renamed
   // to replace the current log of the partition after the future log catches up with the current log
   private val futureLogs = new Pool[TopicPartition, Log]()
-  private val logsToBeDeleted = new LinkedBlockingQueue[Log]()
+  // Each element in the queue contains the log object to be deleted and the time it is scheduled for deletion.
+  private val logsToBeDeleted = new LinkedBlockingQueue[(Log, Long)]()
 
   private val _liveLogDirs: ConcurrentLinkedQueue[File] = createAndValidateLogDirs(logDirs, initialOfflineDirs)
   @volatile var currentDefaultConfig = initialDefaultConfig
   @volatile private var numRecoveryThreadsPerDataDir = recoveryThreadsPerDataDir
 
@@ -238,10 +239,14 @@ class LogManager(logDirs: Seq[File],
           None
       }
     }
   }
 
+  private def addLogToBeDeleted(log: Log): Unit = {
+    this.logsToBeDeleted.add((log, time.milliseconds()))
+  }
+
   private def loadLog(logDir: File, recoveryPoints: Map[TopicPartition, Long], logStartOffsets: Map[TopicPartition, Long]): Unit = {
     debug("Loading log '" + logDir.getName + "'")
     val topicPartition = Log.parseTopicPartitionName(logDir)
     val config = topicConfigs.getOrElse(topicPartition.topic, currentDefaultConfig)
     val logRecoveryPoint = recoveryPoints.getOrElse(topicPartition, 0L)
@@ -258,11 +263,11 @@ class LogManager(logDirs: Seq[File],
       time = time,
       brokerTopicStats = brokerTopicStats,
       logDirFailureChannel = logDirFailureChannel)
 
     if (logDir.getName.endsWith(Log.DeleteDirSuffix)) {
-      this.logsToBeDeleted.add(log)
+      addLogToBeDeleted(log)
     } else {
       val previous = {
         if (log.isFuture)
           this.futureLogs.put(topicPartition, log)
         else
@@ -702,13 +707,16 @@ class LogManager(logDirs: Seq[File],
    *  Delete logs marked for deletion.
    */
   private def deleteLogs(): Unit = {
     try {
       while (!logsToBeDeleted.isEmpty) {
-        val removedLog = logsToBeDeleted.take()
+        val (removedLog, scheduleTimeMs) = logsToBeDeleted.take()
         if (removedLog != null) {
           try {
+            val waitingTimeMs = scheduleTimeMs + currentDefaultConfig.fileDeleteDelayMs - time.milliseconds()
+            if (waitingTimeMs > 0)
+              Thread.sleep(waitingTimeMs)
             removedLog.delete()
             info(s"Deleted log for partition ${removedLog.topicPartition} in ${removedLog.dir.getAbsolutePath}.")
           } catch {
             case e: KafkaStorageException =>
               error(s"Exception while deleting $removedLog in dir ${removedLog.dir.getParent}.", e)
@@ -765,11 +773,11 @@ class LogManager(logDirs: Seq[File],
         // Now that replica in source log directory has been successfully renamed for deletion.
         // Close the log, update checkpoint files, and enqueue this log to be deleted.
         sourceLog.close()
         checkpointLogRecoveryOffsetsInDir(sourceLog.dir.getParentFile)
         checkpointLogStartOffsetsInDir(sourceLog.dir.getParentFile)
-        logsToBeDeleted.add(sourceLog)
+        addLogToBeDeleted(sourceLog)
       } catch {
         case e: KafkaStorageException =>
           // If sourceLog's log directory is offline, we need close its handlers here.
           // handleLogDirFailure() will not close handlers of sourceLog because it has been removed from currentLogs map
           sourceLog.closeHandlers()
@@ -803,11 +811,11 @@ class LogManager(logDirs: Seq[File],
         cleaner.updateCheckpoints(removedLog.dir.getParentFile)
       }
       removedLog.renameDir(Log.logDeleteDirName(topicPartition))
       checkpointLogRecoveryOffsetsInDir(removedLog.dir.getParentFile)
       checkpointLogStartOffsetsInDir(removedLog.dir.getParentFile)
-      logsToBeDeleted.add(removedLog)
+      addLogToBeDeleted(removedLog)
       info(s"Log for partition ${removedLog.topicPartition} is renamed to ${removedLog.dir.getAbsolutePath} and is scheduled for deletion")
     } else if (offlineLogDirs.nonEmpty) {
       throw new KafkaStorageException("Failed to delete log for " + topicPartition + " because it may be in one of the offline directories " + offlineLogDirs.mkString(","))
     }
     removedLog
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
