# Annotation packet: KAFKA-5173  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
SASL tests failing with Could not find a 'KafkaServer' or 'sasl_plaintext.KafkaServer' entry in the JAAS configuration

I've seen this a few times. One example:

{code}
java.lang.IllegalArgumentException: Could not find a 'KafkaServer' or 'sasl_plaintext.KafkaServer' entry in the JAAS configuration. System property 'java.security.auth.login.config' is /tmp/kafka8162725028002772063.tmp
	at org.apache.kafka.common.security.JaasContext.defaultContext(JaasContext.java:131)
	at org.apache.kafka.common.security.JaasContext.load(JaasContext.java:96)
	at org.apache.kafka.common.security.JaasContext.load(JaasContext.java:78)
	at org.apache.kafka.common.network.ChannelBuilders.create(ChannelBuilders.java:100)
	at org.apache.kafka.common.network.ChannelBuilders.serverChannelBuilder(ChannelBuilders.java:73)
	at kafka.network.Processor.<init>(SocketServer.scala:423)
	at kafka.network.SocketServer.newProcessor(SocketServer.scala:145)
	at kafka.network.SocketServer$$anonfun$startup$1$$anonfun$apply$1.apply$mcVI$sp(SocketServer.scala:96)
	at scala.collection.immutable.Range.foreach$mVc$sp(Range.scala:160)
	at kafka.network.SocketServer$$anonfun$startup$1.apply(SocketServer.scala:95)
	at kafka.network.SocketServer$$anonfun$startup$1.apply(SocketServer.scala:90)
	at scala.collection.mutable.ResizableArray$class.foreach(ResizableArray.scala:59)
	at scala.collection.mutable.ArrayBuffer.foreach(ArrayBuffer.scala:48)
	at kafka.network.SocketServer.startup(SocketServer.scala:90)
	at kafka.server.KafkaServer.startup(KafkaServer.scala:218)
	at kafka.utils.TestUtils$.createServer(TestUtils.scala:126)
	at kafka.integration.BaseTopicMetadataTest.setUp(BaseTopicMetadataTest.scala:51)
	at kafka.integration.SaslPlaintextTopicMetadataTest.kafka$api$SaslTestHarness$$super$setUp(SaslPlaintextTopicMetadataTest.scala:23)
	at kafka.api.SaslTestHarness$class.setUp(SaslTestHarness.scala:31)
	at kafka.integration.SaslPlaintextTopicMetadataTest.setUp(SaslPlaintextTopicMetadataTest.scala:23)
{code}

https://builds.apache.org/job/kafka-trunk-jdk8/1479/testReport/junit/kafka.integration/SaslPlaintextTopicMetadataTest/testIsrAfterBrokerShutDownAndJoinsBack/

[~rsivaram], any ideas?
```

## Fix commit message(s)

`0bede30ada6d`

```
KAFKA-5184 KAFKA-5173; Various improvements to SASL tests

1. Call `closeSasl` in `MultipleListenersWithSameSecurityProtocolBaseTest`
2. Refactor the code to make it easier to reason about
3. Add an assert that may possibly help us narrow down how KAFKA-5184
can happen (it seems impossible).
4. Remove SaslTestHarness to make it easier to reason about setUp
and tearDown methods.
5. Fix *AdminClientIntegrationTest to have a single `tearDown`
6. Remove a *ReplicaFetcherTest and *TopicMetadataTest secure variants.
They are redundant from a security perspective given the consumer and
producer tests.

Author: Ismael Juma <ismael@juma.me.uk>

Reviewers: Rajini Sivaram <rajinisivaram@googlemail.com>

Closes #3010 from ijuma/kafka-5184-kafka-5173-sasl-issues
```

## Files the fix changed

Snapshot holds 1,149 non-test source files. The fix changed 36 file(s); 1 of them are non-test source files (listed below as gold).

- `core/src/main/scala/kafka/cluster/Broker.scala`

## The fix diff

### `core/src/main/scala/kafka/cluster/Broker.scala`

```diff
diff --git a/core/src/main/scala/kafka/cluster/Broker.scala b/core/src/main/scala/kafka/cluster/Broker.scala
index 00b4078993..184a750d85 100755
--- a/core/src/main/scala/kafka/cluster/Broker.scala
+++ b/core/src/main/scala/kafka/cluster/Broker.scala
@@ -167,16 +167,16 @@ case class Broker(id: Int, endPoints: Seq[EndPoint], rack: Option[String]) {
     this(bep.id, bep.host, bep.port, listenerName, protocol)
   }
 
   def getNode(listenerName: ListenerName): Node = {
     val endpoint = endPointsMap.getOrElse(listenerName,
-      throw new BrokerEndPointNotAvailableException(s"End point with protocol label $listenerName not found for broker $id"))
+      throw new BrokerEndPointNotAvailableException(s"End point with listener name ${listenerName.value} not found for broker $id"))
     new Node(id, endpoint.host, endpoint.port, rack.orNull)
   }
 
   def getBrokerEndPoint(listenerName: ListenerName): BrokerEndPoint = {
     val endpoint = endPointsMap.getOrElse(listenerName,
-      throw new BrokerEndPointNotAvailableException(s"End point with security protocol $listenerName not found for broker $id"))
+      throw new BrokerEndPointNotAvailableException(s"End point with listener name ${listenerName.value} not found for broker $id"))
     new BrokerEndPoint(id, endpoint.host, endpoint.port)
   }
 
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
