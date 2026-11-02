# Annotation packet: KAFKA-6052  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Windows: Consumers not polling when isolation.level=read_committed 

*The same code is running fine in Linux.* I am trying to send a transactional record with exactly once schematics. These are my producer, consumer and broker setups. 
public void sendWithTTemp(String topic, EHEvent event) {
    Properties props = new Properties();
    props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG,
              "localhost:9092,localhost:9093,localhost:9094");
//    props.put("bootstrap.servers", "34.240.248.190:9092,52.50.95.30:9092,52.50.95.30:9092");
    props.put(ProducerConfig.ACKS_CONFIG, "all");
    props.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, true);
    props.put(ProducerConfig.MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION, "1");
    props.put(ProducerConfig.BATCH_SIZE_CONFIG, 16384);
    props.put(ProducerConfig.LINGER_MS_CONFIG, 1);
    props.put("transactional.id", "TID" + transactionId.incrementAndGet());
    props.put(ProducerConfig.TRANSACTION_TIMEOUT_CONFIG, "5000");

    Producer<String, String> producer =
        new KafkaProducer<>(props,
                            new StringSerializer(),
                            new StringSerializer());

    Logger.log(this, "Initializing transaction...");

    producer.initTransactions();

    Logger.log(this, "Initializing done.");

    try {
      Logger.log(this, "Begin transaction...");
      producer.beginTransaction();
      Logger.log(this, "Begin transaction done.");
      Logger.log(this, "Sending events...");
      producer.send(new ProducerRecord<>(topic,
                                         event.getKey().toString(),
                                         event.getValue().toString()));
      Logger.log(this, "Sending events done.");
      Logger.log(this, "Committing...");
      producer.commitTransaction();
      Logger.log(this, "Committing done.");
    } catch (ProducerFencedException | OutOfOrderSequenceException
        | AuthorizationException e) {
      producer.close();
      e.printStackTrace();
    } catch (KafkaException e) {
      producer.abortTransaction();
      e.printStackTrace();
    }

    producer.close();
  }

*In Consumer*
I have set isolation.level=read_committed
*In 3 Brokers*
I'm running with the following properties
      Properties props = new Properties();
      props.setProperty("broker.id", "" + i);
      props.setProperty("listeners", "PLAINTEXT://:909" + (2 + i));
      props.setProperty("log.dirs", Configuration.KAFKA_DATA_PATH + "\\B" + i);
      props.setProperty("num.partitions", "1");
      props.setProperty("zookeeper.connect", "localhost:2181");
      props.setProperty("zookeeper.connection.timeout.ms", "6000");
      props.setProperty("min.insync.replicas", "2");
      props.setProperty("offsets.topic.replication.factor", "2");
      props.setProperty("offsets.topic.num.partitions", "1");
      props.setProperty("transaction.state.log.num.partitions", "2");
      props.setProperty("transaction.state.log.replication.factor", "2");
      props.setProperty("transaction.state.log.min.isr", "2");

I am not getting any records in the consumer. When I set isolation.level=read_uncommitted, I get the records. I assume that the records are not getting commited. What could be the problem? log attached
```

## Fix commit message(s)

`3f611044cc55`

```
KAFKA-6052; Fix WriteTxnMarkers request retry issue in InterBrokerSendThread (#4705)

This resolves the issue found when running the brokers on Windows which prevents the coordinator from sending WriteTxnMarkers requests to complete a transaction.
```

## Files the fix changed

Snapshot holds 1,497 non-test source files. The fix changed 3 file(s); 2 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/common/InterBrokerSendThread.scala`
- `core/src/main/scala/kafka/coordinator/transaction/TransactionMarkerChannelManager.scala`

## The fix diff

### `core/src/main/scala/kafka/common/InterBrokerSendThread.scala`

```diff
diff --git a/core/src/main/scala/kafka/common/InterBrokerSendThread.scala b/core/src/main/scala/kafka/common/InterBrokerSendThread.scala
index 70dae354aa..c65e557297 100644
--- a/core/src/main/scala/kafka/common/InterBrokerSendThread.scala
+++ b/core/src/main/scala/kafka/common/InterBrokerSendThread.scala
@@ -14,17 +14,21 @@
  * See the License for the specific language governing permissions and
  * limitations under the License.
  */
 package kafka.common
 
+import java.util.{ArrayDeque, ArrayList, Collection, Collections, HashMap, Iterator}
+import java.util.Map.Entry
+
 import kafka.utils.ShutdownableThread
-import org.apache.kafka.clients.{ClientResponse, NetworkClient, RequestCompletionHandler}
+import org.apache.kafka.clients.{ClientRequest, ClientResponse, NetworkClient, RequestCompletionHandler}
 import org.apache.kafka.common.Node
 import org.apache.kafka.common.internals.FatalExitError
 import org.apache.kafka.common.requests.AbstractRequest
 import org.apache.kafka.common.utils.Time
 
+import scala.collection.JavaConverters._
 
 /**
  *  Class for inter-broker send thread that utilize a non-blocking network client.
  */
 abstract class InterBrokerSendThread(name: String,
@@ -32,48 +36,38 @@ abstract class InterBrokerSendThread(name: String,
                                      time: Time,
                                      isInterruptible: Boolean = true)
   extends ShutdownableThread(name, isInterruptible) {
 
   def generateRequests(): Iterable[RequestAndCompletionHandler]
+  def unsentExpiryMs: Int
+  private val unsentRequests = new UnsentRequests
+
+  def hasUnsentRequests = unsentRequests.iterator().hasNext
 
   override def shutdown(): Unit = {
     initiateShutdown()
     // wake up the thread in case it is blocked inside poll
     networkClient.wakeup()
     awaitShutdown()
   }
 
   override def doWork() {
-    val now = time.milliseconds()
-    var pollTimeout = Long.MaxValue
+    var now = time.milliseconds()
+
+    generateRequests().foreach { request =>
+      val completionHandler = request.handler
+      unsentRequests.put(request.destination,
+        networkClient.newClientRequest(request.destination.idString, request.request, now, true, completionHandler))
+    }
 
     try {
-      for (request: RequestAndCompletionHandler <- generateRequests()) {
-        val destination = Integer.toString(request.destination.id())
-        val completionHandler = request.handler
-        val clientRequest = networkClient.newClientRequest(destination,
-          request.request,
-          now,
-          true,
-          completionHandler)
-
-        if (networkClient.ready(request.destination, now)) {
-          networkClient.send(clientRequest, now)
-        } else {
-          val header = clientRequest.makeHeader(request.request.latestAllowedVersion)
-          val disconnectResponse: ClientResponse = new ClientResponse(header, completionHandler, destination,
-            now /* createdTimeMs */ , now /* receivedTimeMs */ , true /* disconnected */ , null /* versionMismatch */ ,
-            null /* responseBody */)
-
-          // poll timeout would be the minimum of connection delay if there are any dest yet to be reached;
-          // otherwise it is infinity
-          pollTimeout = Math.min(pollTimeout, networkClient.connectionDelay(request.destination, now))
-
-          completionHandler.onComplete(disconnectResponse)
-        }
-      }
-      networkClient.poll(pollTimeout, now)
+      val timeout = sendRequests(now)
+      networkClient.poll(timeout, now)
+      now = time.milliseconds()
+      checkDisconnects(now)
+      failExpiredRequests(now)
+      unsentRequests.clean()
     } catch {
       case e: FatalExitError => throw e
       case t: Throwable =>
         error(s"unhandled exception caught in InterBrokerSendThread", t)
         // rethrow any unhandled exceptions as FatalExitError so the JVM will be terminated
@@ -82,11 +76,115 @@ abstract class InterBrokerSendThread(name: String,
         // dealt with already.
         throw new FatalExitError()
     }
   }
 
-  def wakeup(): Unit = networkClient.wakeup()
+  private def sendRequests(now: Long): Long = {
+    var pollTimeout = Long.MaxValue
+    for (node <- unsentRequests.nodes.asScala) {
+      val requestIterator = unsentRequests.requestIterator(node)
+      while (requestIterator.hasNext) {
+        val request = requestIterator.next
+        if (networkClient.ready(node, now)) {
+          networkClient.send(request, now)
+          requestIterator.remove()
+        } else
+          pollTimeout = Math.min(pollTimeout, networkClient.connectionDelay(node, now))
+      }
+    }
+    pollTimeout
+  }
+
+  private def checkDisconnects(now: Long): Unit = {
+    // any disconnects affecting requests that have already been transmitted will be handled
+    // by NetworkClient, so we just need to check whether connections for any of the unsent
+    // requests have been disconnected; if they have, then we complete the corresponding future
+    // and set the disconnect flag in the ClientResponse
+    val iterator = unsentRequests.iterator()
+    while (iterator.hasNext) {
+      val entry = iterator.next
+      val (node, requests) = (entry.getKey, entry.getValue)
+      if (!requests.isEmpty && networkClient.connectionFailed(node)) {
+        iterator.remove()
+        for (request <- requests.asScala) {
+          if (networkClient.authenticationException(node) != null)
+            error(s"Failed to send the following request due to authentication error: $request")
+          completeWithDisconnect(request, now)
+        }
+      }
+    }
+  }
 
+  private def failExpiredRequests(now: Long): Unit = {
+    // clear all expired unsent requests
+    val expiredRequests = unsentRequests.removeExpiredRequests(now, unsentExpiryMs)
+    for (request <- expiredRequests.asScala) {
+      debug(s"Failed to send the following request after $unsentExpiryMs ms: $request")
+      completeWithDisconnect(request, now)
+    }
+  }
+
+  def completeWithDisconnect(request: ClientRequest, now: Long): Unit = {
+    val handler = request.callback
+    handler.onComplete(new ClientResponse(request.makeHeader(request.requestBuilder().latestAllowedVersion()),
+      handler, request.destination, now /* createdTimeMs */ , now /* receivedTimeMs */ , true /* disconnected */ ,
+      null /* versionMismatch */ , null /* responseBody */))
+  }
+
+  def wakeup(): Unit = networkClient.wakeup()
 }
 
 case class RequestAndCompletionHandler(destination: Node, request: AbstractRequest.Builder[_ <: AbstractRequest],
-                                       handler: RequestCompletionHandler)
\ No newline at end of file
+                                       handler: RequestCompletionHandler)
+
+private class UnsentRequests {
+  private val unsent = new HashMap[Node, ArrayDeque[ClientRequest]]
+
+  def put(node: Node, request: ClientRequest): Unit = {
+    var requests = unsent.get(node)
+    if (requests == null) {
+      requests = new ArrayDeque[ClientRequest]
+      unsent.put(node, requests)
+    }
+    requests.add(request)
+  }
+
+  def removeExpiredRequests(now: Long, unsentExpiryMs: Long): Collection[ClientRequest] = {
+    val expiredRequests = new ArrayList[ClientRequest]
+    for (requests <- unsent.values.asScala) {
+      val requestIterator = requests.iterator
+      var foundExpiredRequest = false
+      while (requestIterator.hasNext && !foundExpiredRequest) {
+        val request = requestIterator.next
+        if (request.createdTimeMs < now - unsentExpiryMs) {
+          expiredRequests.add(request)
+          requestIterator.remove()
+          foundExpiredRequest = true
+        }
+      }
+    }
+    expiredRequests
+  }
+
+  def clean(): Unit = {
+    val iterator = unsent.values.iterator
+    while (iterator.hasNext) {
+      val requests = iterator.next
+      if (requests.isEmpty)
+        iterator.remove()
+    }
+  }
+
+  def iterator(): Iterator[Entry[Node, ArrayDeque[ClientRequest]]] = {
+    unsent.entrySet().iterator()
+  }
+
+  def requestIterator(node: Node): Iterator[ClientRequest] = {
+    val requests = unsent.get(node)
+    if (requests == null)
+      Collections.emptyIterator[ClientRequest]
+    else
+      requests.iterator
+  }
+
+  def nodes = unsent.keySet
+}
```

### `core/src/main/scala/kafka/coordinator/transaction/TransactionMarkerChannelManager.scala`

```diff
diff --git a/core/src/main/scala/kafka/coordinator/transaction/TransactionMarkerChannelManager.scala b/core/src/main/scala/kafka/coordinator/transaction/TransactionMarkerChannelManager.scala
index fa9d2c3fed..7059ced5b3 100644
--- a/core/src/main/scala/kafka/coordinator/transaction/TransactionMarkerChannelManager.scala
+++ b/core/src/main/scala/kafka/coordinator/transaction/TransactionMarkerChannelManager.scala
@@ -133,10 +133,12 @@ class TransactionMarkerChannelManager(config: KafkaConfig,
 
   private val markersQueueForUnknownBroker = new TxnMarkerQueue(Node.noNode)
 
   private val txnLogAppendRetryQueue = new LinkedBlockingQueue[TxnLogAppend]()
 
+  override val unsentExpiryMs: Int = config.requestTimeoutMs
+
   newGauge(
     "UnknownDestinationQueueSize",
     new Gauge[Int] {
       def value: Int = markersQueueForUnknownBroker.totalNumMarkers
     }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
