# Annotation packet: KAFKA-8803  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Stream will not start due to TimeoutException: Timeout expired after 60000milliseconds while awaiting InitProducerId

One streams app is consistently failing at startup with the following exception:

{code}
2019-08-14 17:02:29,568 ERROR --- [2ce1b-StreamThread-2] org.apa.kaf.str.pro.int.StreamTask                : task [0_36] Timeout exception caught when initializing transactions for task 0_36. This might happen if the broker is slow to respond, if the network connection to the broker was interrupted, or if similar circumstances arise. You can increase producer parameter `max.block.ms` to increase this timeout.
org.apache.kafka.common.errors.TimeoutException: Timeout expired after 60000milliseconds while awaiting InitProducerId
{code}

These same brokers are used by many other streams without any issue, including some in the very same processes for the stream which consistently throws this exception.

*UPDATE 08/16:*

The very first instance of this error is August 13th 2019, 17:03:36.754 and it happened for 4 different streams. For 3 of these streams, the error only happened once, and then the stream recovered. For the 4th stream, the error has continued to happen, and continues to happen now.

I looked up the broker logs for this time, and see that at August 13th 2019, 16:47:43, two of four brokers started reporting messages like this, for multiple partitions:

[2019-08-13 20:47:43,658] INFO [ReplicaFetcher replicaId=3, leaderId=1, fetcherId=0] Retrying leaderEpoch request for partition xxx-1 as the leader reported an error: UNKNOWN_LEADER_EPOCH (kafka.server.ReplicaFetcherThread)

The UNKNOWN_LEADER_EPOCH messages continued for some time, and then stopped, here is a view of the count of these messages over time:

 !screenshot-1.png! 

However, as noted, the stream task timeout error continues to happen.

I use the static consumer group protocol with Kafka 2.3.0 clients and 2.3.0 broker. The broker has a patch for KAFKA-8773.
```

## Fix commit message(s)

`6a88d32b9fe3`

```
KAFKA-8803: Remove timestamp check in completeTransitionTo (#8278)

In prepareAddPartitions the txnStartTimestamp could be updated as updateTimestamp, which is assumed to be always larger then the original startTimestamp. However, due to ntp time shift the timer may go backwards and hence the newStartTimestamp be smaller than the original one. Then later in completeTransitionTo the time check would fail with an IllegalStateException, and the txn would not transit to Ongoing.

An indirect result of this, is that this txn would NEVER be expired anymore because only Ongoing ones would be checked for expiration.

We should do the same as in #3286 to remove this check.

Also added test coverage for both KAFKA-5415 and KAFKA-8803.

Reviewers: Jason Gustafson<jason@confluent.io>
```

## Files the fix changed

Snapshot holds 1,863 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/coordinator/transaction/TransactionMetadata.scala`

## The fix diff

### `core/src/main/scala/kafka/coordinator/transaction/TransactionMetadata.scala`

```diff
diff --git a/core/src/main/scala/kafka/coordinator/transaction/TransactionMetadata.scala b/core/src/main/scala/kafka/coordinator/transaction/TransactionMetadata.scala
index 4b57abf54b..24b418ac3c 100644
--- a/core/src/main/scala/kafka/coordinator/transaction/TransactionMetadata.scala
+++ b/core/src/main/scala/kafka/coordinator/transaction/TransactionMetadata.scala
@@ -376,12 +376,11 @@ private[transaction] class TransactionMetadata(val transactionalId: String,
           }
 
         case Ongoing => // from addPartitions
           if (!validProducerEpoch(transitMetadata) ||
             !topicPartitions.subsetOf(transitMetadata.topicPartitions) ||
-            txnTimeoutMs != transitMetadata.txnTimeoutMs ||
-            txnStartTimestamp > transitMetadata.txnStartTimestamp) {
+            txnTimeoutMs != transitMetadata.txnTimeoutMs) {
 
             throwStateTransitionFailure(transitMetadata)
           } else {
             txnStartTimestamp = transitMetadata.txnStartTimestamp
             addPartitions(transitMetadata.topicPartitions)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
