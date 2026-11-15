# Annotation packet: KAFKA-10063  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
UnsupportedOperation when querying cleaner metrics after shutdown

We have a few log cleaner metrics which iterate the set of cleaners. For example:

{code}
  newGauge("max-clean-time-secs", () => cleaners.iterator.map(_.lastStats.elapsedSecs).max.toInt)
{code}

It seems possible currently for LogCleaner metrics to get queried after shutdown of the log cleaner, which clears the `cleaners` collection. This can lead to the following error:
{code}
java.lang.UnsupportedOperationException: empty.max
	at scala.collection.IterableOnceOps.max(IterableOnce.scala:952)
	at scala.collection.IterableOnceOps.max$(IterableOnce.scala:950)
	at scala.collection.AbstractIterator.max(Iterator.scala:1279)
	at kafka.log.LogCleaner.kafka$log$LogCleaner$$$anonfun$new$9(LogCleaner.scala:132)
	at kafka.log.LogCleaner$$anonfun$4.value(LogCleaner.scala:132)
	at kafka.log.LogCleaner$$anonfun$4.value(LogCleaner.scala:132)
{code}
```

## Fix commit message(s)

`8d3d2742b399`

```
KAFKA-10063; UnsupportedOperation when querying cleaner metrics after shutdown (#8783)

Some `LogCleaner` metrics have an unsafe call to `max` over the collection of cleaner threads, which could be empty after shutdown. This leads to an `UnsupportedOperationException`. This patch fixes the problem by changing the computation to use `foldLeft`.

Reviewers: Jason Gustafson <jason@confluent.io>
```

## Files the fix changed

Snapshot holds 1,889 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/log/LogCleaner.scala`

## The fix diff

### `core/src/main/scala/kafka/log/LogCleaner.scala`

```diff
diff --git a/core/src/main/scala/kafka/log/LogCleaner.scala b/core/src/main/scala/kafka/log/LogCleaner.scala
index 2ce1a85460..c83cc6f693 100644
--- a/core/src/main/scala/kafka/log/LogCleaner.scala
+++ b/core/src/main/scala/kafka/log/LogCleaner.scala
@@ -110,28 +110,39 @@ class LogCleaner(initialConfig: CleanerConfig,
                                         "bytes",
                                         time = time)
 
   private[log] val cleaners = mutable.ArrayBuffer[CleanerThread]()
 
+  /**
+   * scala 2.12 does not support maxOption so we handle the empty manually.
+   * @param f to compute the result
+   * @return the max value (int value) or 0 if there is no cleaner
+   */
+  private def maxOverCleanerThreads(f: CleanerThread => Double): Int =
+    cleaners.foldLeft(0.0d)((max: Double, thread: CleanerThread) => math.max(max, f(thread))).toInt
+
+
   /* a metric to track the maximum utilization of any thread's buffer in the last cleaning */
   newGauge("max-buffer-utilization-percent",
-    () => cleaners.iterator.map(100 * _.lastStats.bufferUtilization).max.toInt)
+    () => maxOverCleanerThreads(_.lastStats.bufferUtilization) * 100)
 
   /* a metric to track the recopy rate of each thread's last cleaning */
   newGauge("cleaner-recopy-percent", () => {
     val stats = cleaners.map(_.lastStats)
     val recopyRate = stats.iterator.map(_.bytesWritten).sum.toDouble / math.max(stats.iterator.map(_.bytesRead).sum, 1)
     (100 * recopyRate).toInt
   })
 
   /* a metric to track the maximum cleaning time for the last cleaning from each thread */
-  newGauge("max-clean-time-secs", () => cleaners.iterator.map(_.lastStats.elapsedSecs).max.toInt)
+  newGauge("max-clean-time-secs",
+    () => maxOverCleanerThreads(_.lastStats.elapsedSecs))
+
 
   // a metric to track delay between the time when a log is required to be compacted
   // as determined by max compaction lag and the time of last cleaner run.
   newGauge("max-compaction-delay-secs",
-    () => Math.max(0, (cleaners.iterator.map(_.lastPreCleanStats.maxCompactionDelayMs).max / 1000).toInt))
+    () => maxOverCleanerThreads(_.lastPreCleanStats.maxCompactionDelayMs.toDouble) / 1000)
 
   newGauge("DeadThreadCount", () => deadThreadCount)
 
   private[log] def deadThreadCount: Int = cleaners.count(_.isThreadFailed)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
