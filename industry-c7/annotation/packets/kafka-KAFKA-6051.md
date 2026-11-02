# Annotation packet: KAFKA-6051  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
ReplicaFetcherThread should close the ReplicaFetcherBlockingSend earlier on shutdown

The ReplicaFetcherBlockingSend works as designed and will blocks until it is able to get data. This becomes a problem when we are gracefully shutting down a broker. The controller will attempt to shutdown the fetchers and elect new leaders. When the last fetch of partition is removed, as part of the {{replicaManager.becomeLeaderOrFollower}} call will proceed to shut down any idle ReplicaFetcherThread. The shutdown process here can block up to until the last fetch request completes. This blocking delay is a big problem because the {{replicaStateChangeLock}}, and {{mapLock}} in {{AbstractFetcherManager}} is still locked causing latency spikes on multiple brokers.

At this point in time, we do not need the last response as the fetcher is shutting down. We should close the leaderEndpoint early during {{initiateShutdown()}} instead of after {{super.shutdown()}}.


For example we see here the shutdown blocked the broker from processing more replica changes for ~500 ms 

{code}
[2017-09-01 18:11:42,879] INFO [ReplicaFetcherThread-0-2], Shutting down (kafka.server.ReplicaFetcherThread) 
[2017-09-01 18:11:43,314] INFO [ReplicaFetcherThread-0-2], Stopped (kafka.server.ReplicaFetcherThread) 
[2017-09-01 18:11:43,314] INFO [ReplicaFetcherThread-0-2], Shutdown completed (kafka.server.ReplicaFetcherThread)
{code}
```

## Fix commit message(s)

`5c1a85caa074`

```
KAFKA-6051; Close the ReplicaFetcherBlockingSend earlier on shutdown

Rearranged the testAddPartitionDuringDeleteTopic() test to keep the
likelyhood of the race condition.

Author: Maytee Chinavanichkit <maytee.chinavanichkit@linecorp.com>

Reviewers: Jun Rao <junrao@gmail.com>

Closes #4056 from mayt/KAFKA-6051
```

## Files the fix changed

Snapshot holds 1,393 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/server/ReplicaFetcherThread.scala`

## The fix diff

### `core/src/main/scala/kafka/server/ReplicaFetcherThread.scala`

```diff
diff --git a/core/src/main/scala/kafka/server/ReplicaFetcherThread.scala b/core/src/main/scala/kafka/server/ReplicaFetcherThread.scala
index a8acde4101..3bc68da54d 100644
--- a/core/src/main/scala/kafka/server/ReplicaFetcherThread.scala
+++ b/core/src/main/scala/kafka/server/ReplicaFetcherThread.scala
@@ -77,13 +77,16 @@ class ReplicaFetcherThread(name: String,
   private val fetchSize = brokerConfig.replicaFetchMaxBytes
   private val shouldSendLeaderEpochRequest: Boolean = brokerConfig.interBrokerProtocolVersion >= KAFKA_0_11_0_IV2
 
   private def epochCacheOpt(tp: TopicPartition): Option[LeaderEpochCache] =  replicaMgr.getReplica(tp).map(_.epochs.get)
 
-  override def shutdown(): Unit = {
-    super.shutdown()
-    leaderEndpoint.close()
+  override def initiateShutdown(): Boolean = {
+    val justShutdown = super.initiateShutdown()
+    if (justShutdown) {
+      leaderEndpoint.close()
+    }
+    justShutdown
   }
 
   // process fetched data
   def processPartitionData(topicPartition: TopicPartition, fetchOffset: Long, partitionData: PartitionData) {
     val replica = replicaMgr.getReplicaOrException(topicPartition)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
