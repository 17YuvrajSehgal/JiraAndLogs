# Annotation packet: KAFKA-10432  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
LeaderEpochCache is incorrectly recovered on segment recovery for epoch 0

I added some functionality to the system tests to compare epoch cache lineages ([https://github.com/apache/kafka/pull/9213]), and I found a bug in leader epoch cache recovery.

The test hard kills a broker and the cache hasn't been flushed yet, and then it starts up and goes through log recovery. After recovery there is divergence in the epoch caches for epoch 0:
{noformat}
AssertionError: leader epochs for output-topic-1 didn't match
 [{0: 9393L, 2: 9441L, 4: 42656L},
 {0: 0L, 2: 9441L, 4: 42656L}, 
 {0: 0L, 2: 9441L, 4: 42656L}]                                                                                                                                                                
{noformat}
The cache is supposed to include the offset for epoch 0 but in recovery it skips it [https://github.com/apache/kafka/blob/487b3682ebe0eefde3445b37ee72956451a9d15e/core/src/main/scala/kafka/log/LogSegment.scala#L364] due to [https://github.com/apache/kafka/commit/d152989f26f51b9004b881397db818ad6eaf0392]. Then it stamps the epoch with a later offset when fetching from the leader.

I'm not sure why the recovery code includes the condition `batch.partitionLeaderEpoch > 0`. I discussed this with Jason Gustafson and he believes it may have been intended to avoid assigning negative epochs but is not sure why it was added. None of the tests fail with this check removed.
{noformat}
          leaderEpochCache.foreach { cache =>
            if (batch.partitionLeaderEpoch > 0 && cache.latestEpoch.forall(batch.partitionLeaderEpoch > _))
              cache.assign(batch.partitionLeaderEpoch, batch.baseOffset)
          }
{noformat}
```

## Fix commit message(s)

`d2521855b8eb`

```
KAFKA-10432; LeaderEpochCache is incorrectly recovered for leader epoch 0 (#9219)

The leader epoch cache is incorrectly recovered for epoch 0 as the
assignment is skipped when epoch == 0. This check was likely intended to
prevent negative epochs from being applied or there was an assumption
that epochs started at 1.

A test has been added to LogSegmentTest to show the LogSegment
recovery path works for the epoch cache. This was a test gap as none of the 
recover calls supply a leader epoch cache to recover.

Reviewers: Jason Gustafson <jason@confluent.io>
```

## Files the fix changed

Snapshot holds 1,959 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/log/LogSegment.scala`

## The fix diff

### `core/src/main/scala/kafka/log/LogSegment.scala`

```diff
diff --git a/core/src/main/scala/kafka/log/LogSegment.scala b/core/src/main/scala/kafka/log/LogSegment.scala
index 6c0f8f9ece..b43833d4a7 100755
--- a/core/src/main/scala/kafka/log/LogSegment.scala
+++ b/core/src/main/scala/kafka/log/LogSegment.scala
@@ -359,11 +359,11 @@ class LogSegment private[log] (val log: FileRecords,
         }
         validBytes += batch.sizeInBytes()
 
         if (batch.magic >= RecordBatch.MAGIC_VALUE_V2) {
           leaderEpochCache.foreach { cache =>
-            if (batch.partitionLeaderEpoch > 0 && cache.latestEpoch.forall(batch.partitionLeaderEpoch > _))
+            if (batch.partitionLeaderEpoch >= 0 && cache.latestEpoch.forall(batch.partitionLeaderEpoch > _))
               cache.assign(batch.partitionLeaderEpoch, batch.baseOffset)
           }
           updateProducerState(producerStateManager, batch)
         }
       }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
