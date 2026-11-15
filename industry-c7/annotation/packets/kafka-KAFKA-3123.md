# Annotation packet: KAFKA-3123  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Follower Broker cannot start if offsets are already out of range

I was trying to upgrade our test Windows cluster from 0.8.1.1 to 0.9.0 one machine at a time. Our logs have just 2 hours of retention. I had re-imaged the test machine under consideration, and got the following error in loop after starting afresh with 0.9.0 broker:

[2016-01-19 13:57:28,809] WARN [ReplicaFetcherThread-1-169595708], Replica 177775588 for partition [EventLogs4,1] reset its fetch offset from 0 to current leader 169595708's start offset 334086 (kafka.server.ReplicaFetcherThread)
[2016-01-19 13:57:28,809] ERROR [ReplicaFetcherThread-1-169595708], Error getting offset for partition [EventLogs4,1] to broker 169595708 (kafka.server.ReplicaFetcherThread)
java.lang.IllegalStateException: Compaction for partition [EXO_EventLogs4,1] cannot be aborted and paused since it is in LogCleaningPaused state.
	at kafka.log.LogCleanerManager$$anonfun$abortAndPauseCleaning$1.apply$mcV$sp(LogCleanerManager.scala:149)
	at kafka.log.LogCleanerManager$$anonfun$abortAndPauseCleaning$1.apply(LogCleanerManager.scala:140)
	at kafka.log.LogCleanerManager$$anonfun$abortAndPauseCleaning$1.apply(LogCleanerManager.scala:140)
	at kafka.utils.CoreUtils$.inLock(CoreUtils.scala:262)
	at kafka.log.LogCleanerManager.abortAndPauseCleaning(LogCleanerManager.scala:140)
	at kafka.log.LogCleaner.abortAndPauseCleaning(LogCleaner.scala:141)
	at kafka.log.LogManager.truncateFullyAndStartAt(LogManager.scala:304)
	at kafka.server.ReplicaFetcherThread.handleOffsetOutOfRange(ReplicaFetcherThread.scala:185)
	at kafka.server.AbstractFetcherThread$$anonfun$processFetchRequest$2$$anonfun$apply$mcV$sp$1$$anonfun$apply$2.apply(AbstractFetcherThread.scala:152)
	at kafka.server.AbstractFetcherThread$$anonfun$processFetchRequest$2$$anonfun$apply$mcV$sp$1$$anonfun$apply$2.apply(AbstractFetcherThread.scala:122)
	at scala.Option.foreach(Option.scala:236)
	at kafka.server.AbstractFetcherThread$$anonfun$processFetchRequest$2$$anonfun$apply$mcV$sp$1.apply(AbstractFetcherThread.scala:122)
	at kafka.server.AbstractFetcherThread$$anonfun$processFetchRequest$2$$anonfun$apply$mcV$sp$1.apply(AbstractFetcherThread.scala:120)
	at scala.collection.mutable.HashMap$$anonfun$foreach$1.apply(HashMap.scala:98)
	at scala.collection.mutable.HashMap$$anonfun$foreach$1.apply(HashMap.scala:98)
	at scala.collection.mutable.HashTable$class.foreachEntry(HashTable.scala:226)
	at scala.collection.mutable.HashMap.foreachEntry(HashMap.scala:39)
	at scala.collection.mutable.HashMap.foreach(HashMap.scala:98)
	at kafka.server.AbstractFetcherThread$$anonfun$processFetchRequest$2.apply$mcV$sp(AbstractFetcherThread.scala:120)
	at kafka.server.AbstractFetcherThread$$anonfun$processFetchRequest$2.apply(AbstractFetcherThread.scala:120)
	at kafka.server.AbstractFetcherThread$$anonfun$processFetchRequest$2.apply(AbstractFetcherThread.scala:120)
	at kafka.utils.CoreUtils$.inLock(CoreUtils.scala:262)
	at kafka.server.AbstractFetcherThread.processFetchRequest(AbstractFetcherThread.scala:118)
	at kafka.server.AbstractFetcherThread.doWork(AbstractFetcherThread.scala:93)
	at kafka.utils.ShutdownableThread.run(ShutdownableThread.scala:63)

I could unblock myself with a code change. I deleted the action for "case s =>" in the LogCleanerManager.scala's abortAndPauseCleaning(). I think we should not throw exception if the state is already LogCleaningAborted or LogCleaningPaused in this function, but instead just let it roll.
```

## Fix commit message(s)

`2d154420c54f`

```
KAFKA-3123; Ensure cleaning is resumed if truncateTo throws

Author: Mickael Maison <mickael.maison@gmail.com>

Reviewers: Ismael Juma <ismael@juma.me.uk>

Closes #3296 from mimaison/KAFKA-3123
```

## Files the fix changed

Snapshot holds 1,220 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/log/LogManager.scala`

## The fix diff

### `core/src/main/scala/kafka/log/LogManager.scala`

```diff
diff --git a/core/src/main/scala/kafka/log/LogManager.scala b/core/src/main/scala/kafka/log/LogManager.scala
index d8cdf90cb5..61879beb72 100755
--- a/core/src/main/scala/kafka/log/LogManager.scala
+++ b/core/src/main/scala/kafka/log/LogManager.scala
@@ -322,17 +322,20 @@ class LogManager(val logDirs: Array[File],
     for ((topicPartition, truncateOffset) <- partitionOffsets) {
       val log = logs.get(topicPartition)
       // If the log does not exist, skip it
       if (log != null) {
         //May need to abort and pause the cleaning of the log, and resume after truncation is done.
-        val needToStopCleaner: Boolean = truncateOffset < log.activeSegment.baseOffset
-        if (needToStopCleaner && cleaner != null)
+        val needToStopCleaner = cleaner != null && truncateOffset < log.activeSegment.baseOffset
+        if (needToStopCleaner)
           cleaner.abortAndPauseCleaning(topicPartition)
-        log.truncateTo(truncateOffset)
-        if (needToStopCleaner && cleaner != null) {
-          cleaner.maybeTruncateCheckpoint(log.dir.getParentFile, topicPartition, log.activeSegment.baseOffset)
-          cleaner.resumeCleaning(topicPartition)
+        try {
+          log.truncateTo(truncateOffset)
+          if (needToStopCleaner)
+            cleaner.maybeTruncateCheckpoint(log.dir.getParentFile, topicPartition, log.activeSegment.baseOffset)
+        } finally {
+          if (needToStopCleaner)
+            cleaner.resumeCleaning(topicPartition)
         }
       }
     }
     checkpointRecoveryPointOffsets()
   }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
