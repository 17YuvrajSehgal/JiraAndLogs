# Annotation packet: KAFKA-5449  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Flaky test TransactionsTest.testReadCommittedConsumerShouldNotSeeUndecidedData

{noformat}
java.lang.AssertionError: Consumed 6 records until timeout instead of the expected 8 records
	at kafka.utils.TestUtils$.fail(TestUtils.scala:333)
	at kafka.utils.TestUtils$.waitUntilTrue(TestUtils.scala:847)
	at kafka.utils.TestUtils$.consumeRecords(TestUtils.scala:1357)
	at kafka.api.TransactionsTest.testReadCommittedConsumerShouldNotSeeUndecidedData(TransactionsTest.scala:143)
{noformat}
```

## Fix commit message(s)

`54a3718a900a`

```
KAFKA-5449; Fix race condition on producer dequeuing of EndTxn request

Author: Jason Gustafson <jason@confluent.io>

Reviewers: Apurva Mehta <apurva@confluent.io>, Ismael Juma <ismael@juma.me.uk>

Closes #3348 from hachikuji/fix-has-unflushed-synchronization
```

## Files the fix changed

Snapshot holds 1,218 non-test source files. The fix changed 8 file(s); 5 of them are non-test source files (listed below as gold).

- `clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java`
- `clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java`
- `clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java`
- `clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java`
- `clients/src/main/java/org/apache/kafka/clients/producer/internals/TransactionManager.java`

## The fix diff

### `clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java`

```diff
diff --git a/clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java b/clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java
index 1be30f1a4d..5be20e25d4 100644
--- a/clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java
+++ b/clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java
@@ -494,11 +494,11 @@ public class KafkaProducer<K, V> implements Producer<K, V> {
      *         transactional.id is active.
      */
     public void commitTransaction() throws ProducerFencedException {
         if (transactionManager == null)
             throw new IllegalStateException("Cannot commit transaction since transactions are not enabled");
-        TransactionalRequestResult result = transactionManager.beginCommittingTransaction();
+        TransactionalRequestResult result = transactionManager.beginCommit();
         sender.wakeup();
         result.await();
     }
 
     /**
@@ -508,11 +508,11 @@ public class KafkaProducer<K, V> implements Producer<K, V> {
      *         transactional.id is active.
      */
     public void abortTransaction() throws ProducerFencedException {
         if (transactionManager == null)
             throw new IllegalStateException("Cannot abort transaction since transactions are not enabled.");
-        TransactionalRequestResult result = transactionManager.beginAbortingTransaction();
+        TransactionalRequestResult result = transactionManager.beginAbort();
         sender.wakeup();
         result.await();
     }
 
     /**
```

### `clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java`

```diff
diff --git a/clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java b/clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java
index 9d8b82d04e..5679c26ebe 100644
--- a/clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java
+++ b/clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java
@@ -54,11 +54,11 @@ import static org.apache.kafka.common.record.RecordBatch.NO_TIMESTAMP;
  */
 public final class ProducerBatch {
 
     private static final Logger log = LoggerFactory.getLogger(ProducerBatch.class);
 
-    private enum FinalState { ABORTED, FAILED, SUCCEEDED };
+    private enum FinalState { ABORTED, FAILED, SUCCEEDED }
 
     final long createdMs;
     final TopicPartition topicPartition;
     final ProduceRequestResult produceFuture;
```

### `clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java`

```diff
diff --git a/clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java b/clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java
index 505417c1f4..10c68d832b 100644
--- a/clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java
+++ b/clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java
@@ -98,12 +98,12 @@ public final class RecordAccumulator {
      * @param retryBackoffMs An artificial delay time to retry the produce request upon receiving an error. This avoids
      *        exhausting all retries in a short period of time.
      * @param metrics The metrics
      * @param time The time instance to use
      * @param apiVersions Request API versions for current connected brokers
-     * @param transactionManager The shared transaction state object which tracks Pids, epochs, and sequence numbers per
-     *                         partition.
+     * @param transactionManager The shared transaction state object which tracks producer IDs, epochs, and sequence
+     *                           numbers per partition.
      */
     public RecordAccumulator(int batchSize,
                              long totalSize,
                              CompressionType compression,
                              long lingerMs,
@@ -397,13 +397,13 @@ public final class RecordAccumulator {
 
         return new ReadyCheckResult(readyNodes, nextReadyCheckDelayMs, unknownLeaderTopics);
     }
 
     /**
-     * @return Whether there is any unsent record in the accumulator.
+     * Check whether there are any batches which haven't been drained
      */
-    public boolean hasUnsent() {
+    public boolean hasUndrained() {
         for (Map.Entry<TopicPartition, Deque<ProducerBatch>> entry : this.batches.entrySet()) {
             Deque<ProducerBatch> deque = entry.getValue();
             synchronized (deque) {
                 if (!deque.isEmpty())
                     return true;
@@ -567,23 +567,22 @@ public final class RecordAccumulator {
     /**
      * Mark all partitions as ready to send and block until the send is complete
      */
     public void awaitFlushCompletion() throws InterruptedException {
         try {
-            for (ProducerBatch batch : this.incomplete.all())
+            for (ProducerBatch batch : this.incomplete.copyAll())
                 batch.produceFuture.await();
         } finally {
             this.flushesInProgress.decrementAndGet();
         }
     }
 
-    public boolean hasUnflushedBatches() {
-        for (Map.Entry<TopicPartition, Deque<ProducerBatch>> entry : this.batches().entrySet()) {
-            if (!entry.getValue().isEmpty())
-                return true;
-        }
-        return !this.incomplete.incomplete.isEmpty();
+    /**
+     * Check whether there are any pending batches (whether sent or unsent).
+     */
+    public boolean hasIncomplete() {
+        return !this.incomplete.isEmpty();
     }
 
     /**
      * This function is only called when sender is closed forcefully. It will fail all the
      * incomplete batches and return.
@@ -608,24 +607,30 @@ public final class RecordAccumulator {
      */
     private void abortBatches() {
         abortBatches(new IllegalStateException("Producer is closed forcefully."));
     }
 
+    /**
+     * Abort all incomplete batches (whether they have been sent or not)
+     */
     void abortBatches(final RuntimeException reason) {
-        for (ProducerBatch batch : incomplete.all()) {
+        for (ProducerBatch batch : incomplete.copyAll()) {
             Deque<ProducerBatch> dq = getDeque(batch.topicPartition);
             synchronized (dq) {
                 batch.abortRecordAppends();
                 dq.remove(batch);
             }
             batch.abort(reason);
             deallocate(batch);
         }
     }
 
-    void abortOpenBatches(RuntimeException reason) {
-        for (ProducerBatch batch : incomplete.all()) {
+    /**
+     * Abort any batches which have not been drained
+     */
+    void abortUndrainedBatches(RuntimeException reason) {
+        for (ProducerBatch batch : incomplete.copyAll()) {
             Deque<ProducerBatch> dq = getDeque(batch.topicPartition);
             boolean aborted = false;
             synchronized (dq) {
                 if (!batch.isClosed()) {
                     aborted = true;
@@ -683,37 +688,6 @@ public final class RecordAccumulator {
             this.nextReadyCheckDelayMs = nextReadyCheckDelayMs;
             this.unknownLeaderTopics = unknownLeaderTopics;
         }
     }
 
-    /*
-     * A threadsafe helper class to hold batches that haven't been ack'd yet
-     */
-    private final static class IncompleteBatches {
-        private final Set<ProducerBatch> incomplete;
-
-        public IncompleteBatches() {
-            this.incomplete = new HashSet<>();
-        }
-
-        public void add(ProducerBatch batch) {
-            synchronized (incomplete) {
-                this.incomplete.add(batch);
-            }
-        }
-
-        public void remove(ProducerBatch batch) {
-            synchronized (incomplete) {
-                boolean removed = this.incomplete.remove(batch);
-                if (!removed)
-                    throw new IllegalStateException("Remove from the incomplete set failed. This should be impossible.");
-            }
-        }
-
-        public Iterable<ProducerBatch> all() {
-            synchronized (incomplete) {
-                return new ArrayList<>(this.incomplete);
-            }
-        }
-    }
-
 }
```

### `clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java`

```diff
diff --git a/clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java b/clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java
index e2bff27154..27eb2447d9 100644
--- a/clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java
+++ b/clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java
@@ -168,11 +168,11 @@ public class Sender implements Runnable {
         log.debug("Beginning shutdown of Kafka producer I/O thread, sending remaining records.");
 
         // okay we stopped accepting requests but there may still be
         // requests in the accumulator or waiting for acknowledgment,
         // wait until these are completed.
-        while (!forceClose && (this.accumulator.hasUnsent() || this.client.inFlightRequestCount() > 0)) {
+        while (!forceClose && (this.accumulator.hasUndrained() || this.client.inFlightRequestCount() > 0)) {
             try {
                 run(time.milliseconds());
             } catch (Exception e) {
                 log.error("Uncaught error in kafka producer I/O thread: ", e);
             }
@@ -199,11 +199,11 @@ public class Sender implements Runnable {
     void run(long now) {
         if (transactionManager != null) {
             if (!transactionManager.isTransactional()) {
                 // this is an idempotent producer, so make sure we have a producer id
                 maybeWaitForProducerId();
-            } else if (transactionManager.hasInflightRequest() || maybeSendTransactionalRequest(now)) {
+            } else if (transactionManager.hasInFlightRequest() || maybeSendTransactionalRequest(now)) {
                 // as long as there are outstanding transactional requests, we simply wait for them to return
                 client.poll(retryBackoffMs, now);
                 return;
             }
 
@@ -214,11 +214,11 @@ public class Sender implements Runnable {
                 if (lastError != null)
                     maybeAbortBatches(lastError);
                 client.poll(retryBackoffMs, now);
                 return;
             } else if (transactionManager.hasAbortableError()) {
-                accumulator.abortOpenBatches(transactionManager.lastError());
+                accumulator.abortUndrainedBatches(transactionManager.lastError());
             }
         }
 
         long pollTimeout = sendProducerData(now);
         client.poll(pollTimeout, now);
@@ -300,31 +300,23 @@ public class Sender implements Runnable {
 
         return pollTimeout;
     }
 
     private boolean maybeSendTransactionalRequest(long now) {
-        if (transactionManager.isCompletingTransaction() &&
-                !transactionManager.hasPartitionsToAdd() &&
-                accumulator.hasUnflushedBatches()) {
-
-            // If the transaction is being aborted, then we can clear any unsent produce requests
+        if (transactionManager.isCompleting() && accumulator.hasIncomplete()) {
             if (transactionManager.isAborting())
-                accumulator.abortOpenBatches(new KafkaException("Failing batch since transaction was aborted"));
+                accumulator.abortUndrainedBatches(new KafkaException("Failing batch since transaction was aborted"));
 
             // There may still be requests left which are being retried. Since we do not know whether they had
             // been successfully appended to the broker log, we must resend them until their final status is clear.
             // If they had been appended and we did not receive the error, then our sequence number would no longer
             // be correct which would lead to an OutOfSequenceException.
             if (!accumulator.flushInProgress())
                 accumulator.beginFlush();
-
-            // Do not send the EndTxn until all pending batches have been completed
-            if (accumulator.hasUnflushedBatches())
-                return false;
         }
 
-        TransactionManager.TxnRequestHandler nextRequestHandler = transactionManager.nextRequestHandler();
+        TransactionManager.TxnRequestHandler nextRequestHandler = transactionManager.nextRequestHandler(accumulator.hasIncomplete());
         if (nextRequestHandler == null)
             return false;
 
         AbstractRequest.Builder<?> requestBuilder = nextRequestHandler.requestBuilder();
         while (true) {
@@ -375,11 +367,11 @@ public class Sender implements Runnable {
         transactionManager.retry(nextRequestHandler);
         return true;
     }
 
     private void maybeAbortBatches(RuntimeException exception) {
-        if (accumulator.hasUnflushedBatches()) {
+        if (accumulator.hasIncomplete()) {
             String logPrefix = "";
             if (transactionManager != null)
                 logPrefix = transactionManager.logPrefix;
             log.error("{}Aborting producer batches due to fatal error", logPrefix, exception);
             accumulator.abortBatches(exception);
```

### `clients/src/main/java/org/apache/kafka/clients/producer/internals/TransactionManager.java`

```diff
diff --git a/clients/src/main/java/org/apache/kafka/clients/producer/internals/TransactionManager.java b/clients/src/main/java/org/apache/kafka/clients/producer/internals/TransactionManager.java
index 5c498db4ae..f2deca3897 100644
--- a/clients/src/main/java/org/apache/kafka/clients/producer/internals/TransactionManager.java
+++ b/clients/src/main/java/org/apache/kafka/clients/producer/internals/TransactionManager.java
@@ -171,18 +171,18 @@ public class TransactionManager {
         ensureTransactional();
         maybeFailWithError();
         transitionTo(State.IN_TRANSACTION);
     }
 
-    public synchronized TransactionalRequestResult beginCommittingTransaction() {
+    public synchronized TransactionalRequestResult beginCommit() {
         ensureTransactional();
         maybeFailWithError();
         transitionTo(State.COMMITTING_TRANSACTION);
         return beginCompletingTransaction(TransactionResult.COMMIT);
     }
 
-    public synchronized TransactionalRequestResult beginAbortingTransaction() {
+    public synchronized TransactionalRequestResult beginAbort() {
         ensureTransactional();
         if (currentState != State.ABORTABLE_ERROR)
             maybeFailWithError();
         transitionTo(State.ABORTING_TRANSACTION);
 
@@ -266,11 +266,11 @@ public class TransactionManager {
 
     synchronized boolean hasPartitionsToAdd() {
         return !newPartitionsInTransaction.isEmpty() || !pendingPartitionsInTransaction.isEmpty();
     }
 
-    synchronized boolean isCompletingTransaction() {
+    synchronized boolean isCompleting() {
         return currentState == State.COMMITTING_TRANSACTION || currentState == State.ABORTING_TRANSACTION;
     }
 
     synchronized boolean hasError() {
         return currentState == State.ABORTABLE_ERROR || currentState == State.FATAL_ERROR;
@@ -375,22 +375,30 @@ public class TransactionManager {
 
         currentSequenceNumber += increment;
         sequenceNumbers.put(topicPartition, currentSequenceNumber);
     }
 
-    synchronized TxnRequestHandler nextRequestHandler() {
+    synchronized TxnRequestHandler nextRequestHandler(boolean hasIncompleteBatches) {
         if (!newPartitionsInTransaction.isEmpty())
             enqueueRequest(addPartitionsToTransactionHandler());
 
-        TxnRequestHandler nextRequestHandler = pendingRequests.poll();
-        if (nextRequestHandler != null && maybeTerminateRequestWithError(nextRequestHandler)) {
+        TxnRequestHandler nextRequestHandler = pendingRequests.peek();
+        if (nextRequestHandler == null)
+            return null;
+
+        // Do not send the EndTxn until all batches have been flushed
+        if (nextRequestHandler.isEndTxn() && hasIncompleteBatches)
+            return null;
+
+        pendingRequests.poll();
+        if (maybeTerminateRequestWithError(nextRequestHandler)) {
             log.trace("{}Not sending transactional request {} because we are in an error state",
                     logPrefix, nextRequestHandler.requestBuilder());
             return null;
         }
 
-        if (nextRequestHandler != null && nextRequestHandler.isEndTxn() && !transactionStarted) {
+        if (nextRequestHandler.isEndTxn() && !transactionStarted) {
             nextRequestHandler.result.done();
             if (currentState != State.FATAL_ERROR) {
                 log.debug("{}Not sending EndTxn for completed transaction since no partitions " +
                         "or offsets were successfully added", logPrefix);
                 completeTransaction();
@@ -430,11 +438,11 @@ public class TransactionManager {
 
     void clearInFlightRequestCorrelationId() {
         inFlightRequestCorrelationId = NO_INFLIGHT_REQUEST_CORRELATION_ID;
     }
 
-    boolean hasInflightRequest() {
+    boolean hasInFlightRequest() {
         return inFlightRequestCorrelationId != NO_INFLIGHT_REQUEST_CORRELATION_ID;
     }
 
     // visible for testing.
     boolean hasFatalError() {
@@ -457,11 +465,11 @@ public class TransactionManager {
     }
 
     // visible for testing
     synchronized boolean hasOngoingTransaction() {
         // transactions are considered ongoing once started until completion or a fatal error
-        return currentState == State.IN_TRANSACTION || isCompletingTransaction() || hasAbortableError();
+        return currentState == State.IN_TRANSACTION || isCompleting() || hasAbortableError();
     }
 
     // visible for testing
     synchronized boolean isReady() {
         return isTransactional() && currentState == State.READY;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
