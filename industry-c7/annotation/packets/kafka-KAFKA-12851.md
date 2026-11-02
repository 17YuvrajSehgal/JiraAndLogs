# Annotation packet: KAFKA-12851  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Flaky Test RaftEventSimulationTest.canMakeProgressIfMajorityIsReachable

Failed twice on a [PR build|https://ci-builds.apache.org/job/Kafka/job/kafka-pr/job/PR-10755/6/testReport/]
h3. Stacktrace

org.opentest4j.AssertionFailedError: expected: <true> but was: <false> at org.junit.jupiter.api.AssertionUtils.fail(AssertionUtils.java:55) at org.junit.jupiter.api.AssertTrue.assertTrue(AssertTrue.java:40) at org.junit.jupiter.api.AssertTrue.assertTrue(AssertTrue.java:35) at org.junit.jupiter.api.Assertions.assertTrue(Assertions.java:162) at org.apache.kafka.raft.RaftEventSimulationTest.canMakeProgressIfMajorityIsReachable(RaftEventSimulationTest.java:263)
```

## Fix commit message(s)

`fd36e5a8b657`

```
KAFKA-12851: Fix Raft partition simulation (#11134)

Instead of waiting for a high-watermark of 20 after the partition, the
test should wait for the high-watermark to reach an offset greater than
the largest log end offset at the time of the partition. Only that offset
is guarantee to be reached as the high-watermark by the new majority.

Reviewers: Jason Gustafson <jason@confluent.io>
```

## Files the fix changed

Snapshot holds 2,340 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `raft/src/main/java/org/apache/kafka/raft/LeaderState.java`

## The fix diff

### `raft/src/main/java/org/apache/kafka/raft/LeaderState.java`

```diff
diff --git a/raft/src/main/java/org/apache/kafka/raft/LeaderState.java b/raft/src/main/java/org/apache/kafka/raft/LeaderState.java
index 2bcc931b50..de08b7b1cc 100644
--- a/raft/src/main/java/org/apache/kafka/raft/LeaderState.java
+++ b/raft/src/main/java/org/apache/kafka/raft/LeaderState.java
@@ -169,10 +169,16 @@ public class LeaderState<T> implements EpochState {
                     LogOffsetMetadata currentHighWatermarkMetadata = highWatermark.get();
                     if (highWatermarkUpdateOffset > currentHighWatermarkMetadata.offset
                         || (highWatermarkUpdateOffset == currentHighWatermarkMetadata.offset &&
                             !highWatermarkUpdateMetadata.metadata.equals(currentHighWatermarkMetadata.metadata))) {
                         highWatermark = highWatermarkUpdateOpt;
+                        log.trace(
+                            "High watermark updated to {} based on indexOfHw {} and voters {}",
+                            highWatermark,
+                            indexOfHw,
+                            followersByDescendingFetchOffset
+                        );
                         return true;
                     } else if (highWatermarkUpdateOffset < currentHighWatermarkMetadata.offset) {
                         log.error("The latest computed high watermark {} is smaller than the current " +
                                 "value {}, which suggests that one of the voters has lost committed data. " +
                                 "Full voter replication state: {}", highWatermarkUpdateOffset,
@@ -181,10 +187,16 @@ public class LeaderState<T> implements EpochState {
                     } else {
                         return false;
                     }
                 } else {
                     highWatermark = highWatermarkUpdateOpt;
+                    log.trace(
+                        "High watermark set to {} based on indexOfHw {} and voters {}",
+                        highWatermark,
+                        indexOfHw,
+                        followersByDescendingFetchOffset
+                    );
                     return true;
                 }
             }
         }
         return false;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
