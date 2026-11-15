# Annotation packet: SPARK-32975  (spark)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Add config for driver readiness timeout before executors start

We are using v1beta2-1.1.2-2.4.5 version of operator with spark-2.4.4

spark executors keeps getting killed with exit code 1 and we are seeing following exception in the executor which goes to error state. Once this error happens, driver doesn't restart executor. 

 

Exception in thread "main" java.lang.reflect.UndeclaredThrowableException
at org.apache.hadoop.security.UserGroupInformation.doAs(UserGroupInformation.java:1713)
at org.apache.spark.deploy.SparkHadoopUtil.runAsSparkUser(SparkHadoopUtil.scala:64)
at org.apache.spark.executor.CoarseGrainedExecutorBackend$.run(CoarseGrainedExecutorBackend.scala:188)
at org.apache.spark.executor.CoarseGrainedExecutorBackend$.main(CoarseGrainedExecutorBackend.scala:281)
at org.apache.spark.executor.CoarseGrainedExecutorBackend.main(CoarseGrainedExecutorBackend.scala)
Caused by: org.apache.spark.SparkException: Exception thrown in awaitResult:
at org.apache.spark.util.ThreadUtils$.awaitResult(ThreadUtils.scala:226)
at org.apache.spark.rpc.RpcTimeout.awaitResult(RpcTimeout.scala:75)
at org.apache.spark.rpc.RpcEnv.setupEndpointRefByURI(RpcEnv.scala:101)
at org.apache.spark.executor.CoarseGrainedExecutorBackend$$anonfun$run$1.apply$mcV$sp(CoarseGrainedExecutorBackend.scala:201)
at org.apache.spark.deploy.SparkHadoopUtil$$anon$2.run(SparkHadoopUtil.scala:65)
at org.apache.spark.deploy.SparkHadoopUtil$$anon$2.run(SparkHadoopUtil.scala:64)
at java.security.AccessController.doPrivileged(Native Method)
at javax.security.auth.Subject.doAs(Subject.java:422)
at org.apache.hadoop.security.UserGroupInformation.doAs(UserGroupInformation.java:1698)
... 4 more
Caused by: java.io.IOException: Failed to connect to act-pipeline-app-1600187491917-driver-svc.default.svc:7078
at org.apache.spark.network.client.TransportClientFactory.createClient(TransportClientFactory.java:245)
at org.apache.spark.network.client.TransportClientFactory.createClient(TransportClientFactory.java:187)
at org.apache.spark.rpc.netty.NettyRpcEnv.createClient(NettyRpcEnv.scala:198)
at org.apache.spark.rpc.netty.Outbox$$anon$1.call(Outbox.scala:194)
at org.apache.spark.rpc.netty.Outbox$$anon$1.call(Outbox.scala:190)
at java.util.concurrent.FutureTask.run(FutureTask.java:266)
at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1149)
at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:624)
at java.lang.Thread.run(Thread.java:748)
Caused by: java.net.UnknownHostException: act-pipeline-app-1600187491917-driver-svc.default.svc
at java.net.InetAddress.getAllByName0(InetAddress.java:1281)
at java.net.InetAddress.getAllByName(InetAddress.java:1193)
at java.net.InetAddress.getAllByName(InetAddress.java:1127)
at java.net.InetAddress.getByName(InetAddress.java:1077)
at io.netty.util.internal.SocketUtils$8.run(SocketUtils.java:146)
at io.netty.util.internal.SocketUtils$8.run(SocketUtils.java:143)
at java.security.AccessController.doPrivileged(Native Method)
at io.netty.util.internal.SocketUtils.addressByName(SocketUtils.java:143)
at io.netty.resolver.DefaultNameResolver.doResolve(DefaultNameResolver.java:43)
at io.netty.resolver.SimpleNameResolver.resolve(SimpleNameResolver.java:63)
at io.netty.resolver.SimpleNameResolver.resolve(SimpleNameResolver.java:55)
at io.netty.resolver.InetSocketAddressResolver.doResolve(InetSocketAddressResolver.java:57)
at io.netty.resolver.InetSocketAddressResolver.doResolve(InetSocketAddressResolver.java:32)
at io.netty.resolver.AbstractAddressResolver.resolve(AbstractAddressResolver.java:108)
at io.netty.bootstrap.Bootstrap.doResolveAndConnect0(Bootstrap.java:208)
at io.netty.bootstrap.Bootstrap.access$000(Bootstrap.java:49)
at io.netty.bootstrap.Bootstrap$1.operationComplete(Bootstrap.java:188)
at io.netty.bootstrap.Bootstrap$1.operationComplete(Bootstrap.java:174)
at io.netty.util.concurrent.DefaultPromise.notifyListener0(DefaultPromise.java:507)
at io.netty.util.concurrent.DefaultPromise.notifyListenersNow(DefaultPromise.java:481)
at io.netty.util.concurrent.DefaultPromise.notifyListeners(DefaultPromise.java:420)
at io.netty.util.concurrent.DefaultPromise.trySuccess(DefaultPromise.java:104)
at io.netty.channel.DefaultChannelPromise.trySuccess(DefaultChannelPromise.java:82)
at io.netty.channel.AbstractChannel$AbstractUnsafe.safeSetSuccess(AbstractChannel.java:978)
at io.netty.channel.AbstractChannel$AbstractUnsafe.register0(AbstractChannel.java:512)
at io.netty.channel.AbstractChannel$AbstractUnsafe.access$200(AbstractChannel.java:423)
at io.netty.channel.AbstractChannel$AbstractUnsafe$1.run(AbstractChannel.java:482)
at io.netty.util.concurrent.AbstractEventExecutor.safeExecute(AbstractEventExecutor.java:163)
at io.netty.util.concurrent.SingleThreadEventExecutor.runAllTasks(SingleThreadEventExecutor.java:403)
at io.netty.channel.nio.NioEventLoop.run(NioEventLoop.java:463)
at io.netty.util.concurrent.SingleThreadEventExecutor$5.run(SingleThreadEventExecutor.java:858)
at io.netty.util.concurrent.DefaultThreadFactory$DefaultRunnableDecorator.run(DefaultThreadFactory.java:138)
... 1 more
CodeCache: size=245760Kb used=4762Kb max_used=4763Kb free=240997Kb
bounds [0x00007f49f5000000, 0x00007f49f54b0000, 0x00007f4a04000000]
total_blobs=1764 nmethods=1356 adapters=324
compilation: enabled

 

 

 

*Additional information:*

*The status of spark application shows it is RUNNING:*

kubectl describe sparkapplications.sparkoperator.k8s.io act-pipeline-app

...

...

Status:

  Application State:

    State:  RUNNING

  Driver Info:

    Pod Name:             act-pipeline-app-driver

    Web UI Address:       10.233.57.201:40550

    Web UI Port:          40550

    Web UI Service Name:  act-pipeline-app-ui-svc

  Execution Attempts:     1

  Executor State:

    act-pipeline-app-1600097064694-exec-1:  RUNNING

  Last Submission Attempt Time:             2020-09-14T15:24:26Z

  Spark Application Id:                     spark-942bb2e500c54f92ac357b818c712558

  Submission Attempts:                      1

  Submission ID:                            4ecdb6ca-d237-4524-b05e-c42cfcc73dc7

  Termination Time:                         <nil>

Events:                                     <none>

 

*The executor pod is reporting that it is Terminated:*

kubectl describe pod -l sparkoperator.k8s.io/app-name=act-pipeline-app,spark-role=executor

...

...

Containers:

  executor:

    Container ID:  docker://9aa5b585e8fb7390b87a4771f3ed1402cae41f0fe55905d0172ed6e90dde34e6

...

    Ports:         7079/TCP, 8090/TCP

    Host Ports:    0/TCP, 0/TCP

    Args:

      executor

    State:          Terminated

      Reason:       Error

      Exit Code:    1

      Started:      Mon, 14 Sep 2020 11:25:35 -0400

      Finished:     Mon, 14 Sep 2020 11:25:39 -0400

    Ready:          False

    Restart Count:  0

...

Conditions:

  Type              Status

  Initialized       True

  Ready             False

  ContainersReady   False

  PodScheduled      True

...

QoS Class:       Burstable

Node-Selectors:  <none>

Tolerations:     node.kubernetes.io/not-ready:NoExecute for 300s

                 node.kubernetes.io/unreachable:NoExecute for 300s

Events:          <none>

In early stage of the driver’s life the failed executor is not detected (it is assumed to be running) and therefore it will not be restarted.
```

## Fix commit message(s)

`497c80a1ad7f`

```
[SPARK-32975][K8S] Add config for driver readiness timeout before executors start

### What changes were proposed in this pull request?
Add a new config that controls the timeout of waiting for driver pod's readiness before allocating executor pods. This wait only happens once on application start.

### Why are the changes needed?
The driver's headless service can be resolved by DNS only after the driver pod is ready. If the executor tries to connect to the headless service before driver pod is ready, it will hit UnkownHostException and get into error state but will not be restarted. **This case usually happens when the driver pod has sidecar containers but hasn't finished their creation when executors start.** So basically there is a race condition. This issue can be mitigated by tweaking this config.

### Does this PR introduce _any_ user-facing change?
A new config `spark.kubernetes.allocation.driver.readinessTimeout` added.

### How was this patch tested?
Exisiting tests.

Closes #32752 from cchriswu/SPARK-32975-fix.

Lead-authored-by: Chris Wu <wucaowei19@gmail.com>
Co-authored-by: Chris Wu <wcaowei@vmware.com>
Signed-off-by: Dongjoon Hyun <dhyun@apple.com>
```

`b4b78ce26567`

```
[SPARK-32975][K8S][FOLLOWUP] Avoid None.get exception

### What changes were proposed in this pull request?

A follow-up for SPARK-32975 to avoid unexpected the `None.get` exception

Run SparkPi with docker desktop, as podName is an option, we will got
```logtalk
21/06/09 01:09:12 ERROR Utils: Uncaught exception in thread main
java.util.NoSuchElementException: None.get
	at scala.None$.get(Option.scala:529)
	at scala.None$.get(Option.scala:527)
	at org.apache.spark.scheduler.cluster.k8s.ExecutorPodsAllocator.$anonfun$start$1(ExecutorPodsAllocator.scala:110)
	at org.apache.spark.util.Utils$.tryLogNonFatalError(Utils.scala:1417)
	at org.apache.spark.scheduler.cluster.k8s.ExecutorPodsAllocator.start(ExecutorPodsAllocator.scala:111)
	at org.apache.spark.scheduler.cluster.k8s.KubernetesClusterSchedulerBackend.start(KubernetesClusterSchedulerBackend.scala:99)
	at org.apache.spark.scheduler.TaskSchedulerImpl.start(TaskSchedulerImpl.scala:220)
	at org.apache.spark.SparkContext.<init>(SparkContext.scala:581)
	at org.apache.spark.SparkContext$.getOrCreate(SparkContext.scala:2686)
	at org.apache.spark.sql.SparkSession$Builder.$anonfun$getOrCreate$2(SparkSession.scala:948)
	at scala.Option.getOrElse(Option.scala:189)
	at org.apache.spark.sql.SparkSession$Builder.getOrCreate(SparkSession.scala:942)
	at org.apache.spark.examples.SparkPi$.main(SparkPi.scala:30)
	at org.apache.spark.examples.SparkPi.main(SparkPi.scala)
	at sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
	at sun.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:62)
	at sun.reflect.DelegatingMethodAccessorImpl.invoke(DelegatingMethodAccessorImpl.java:43)
	at java.lang.reflect.Method.invoke(Method.java:498)
	at org.apache.spark.deploy.JavaMainApplication.start(SparkApplication.scala:52)
	at org.apache.spark.deploy.SparkSubmit.org$apache$spark$deploy$SparkSubmit$$runMain(SparkSubmit.scala:955)
	at org.apache.spark.deploy.SparkSubmit.doRunMain$1(SparkSubmit.scala:180)
	at org.apache.spark.deploy.SparkSubmit.submit(SparkSubmit.scala:203)
	at org.apache.spark.deploy.SparkSubmit.doSubmit(SparkSubmit.scala:90)
	at org.apache.spark.deploy.SparkSubmit$$anon$2.doSubmit(SparkSubmit.scala:1043)
	at org.apache.spark.deploy.SparkSubmit$.main(SparkSubmit.scala:1052)
	at org.apache.spark.deploy.SparkSubmit.main(SparkSubmit.scala)
```

### Why are the changes needed?

fix a regression

### Does this PR introduce _any_ user-facing change?

no
### How was this patch tested?

Manual.

Closes #32830 from yaooqinn/SPARK-32975.

Authored-by: Kent Yao <yao@apache.org>
Signed-off-by: Dongjoon Hyun <dhyun@apple.com>
```

## Files the fix changed

Snapshot holds 3,030 non-test source files. The fix changed 3 file(s); 2 of them are non-test source files (listed below as gold).

- `resource-managers/kubernetes/core/src/main/scala/org/apache/spark/deploy/k8s/Config.scala`
- `resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala`

## The fix diff

### `resource-managers/kubernetes/core/src/main/scala/org/apache/spark/deploy/k8s/Config.scala`

```diff
--- from commit 497c80a1ad7f ---
diff --git a/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/deploy/k8s/Config.scala b/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/deploy/k8s/Config.scala
index 8df8e669127..9fceca783ae 100644
--- a/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/deploy/k8s/Config.scala
+++ b/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/deploy/k8s/Config.scala
@@ -298,10 +298,21 @@ private[spark] object Config extends Logging {
       .version("2.3.0")
       .timeConf(TimeUnit.MILLISECONDS)
       .checkValue(value => value > 0, "Allocation batch delay must be a positive time value.")
       .createWithDefaultString("1s")
 
+  val KUBERNETES_ALLOCATION_DRIVER_READINESS_TIMEOUT =
+    ConfigBuilder("spark.kubernetes.allocation.driver.readinessTimeout")
+      .doc("Time to wait for driver pod to get ready before creating executor pods. This wait " +
+        "only happens on application start. If timeout happens, executor pods will still be " +
+        "created.")
+      .version("3.1.3")
+      .timeConf(TimeUnit.SECONDS)
+      .checkValue(value => value > 0, "Allocation driver readiness timeout must be a positive "
+        + "time value.")
+      .createWithDefaultString("1s")
+
   val KUBERNETES_ALLOCATION_EXECUTOR_TIMEOUT =
     ConfigBuilder("spark.kubernetes.allocation.executor.timeout")
       .doc("Time to wait before a newly created executor POD request, which does not reached " +
         "the POD pending state yet, considered timedout and will be deleted.")
       .version("3.1.0")
```

### `resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala`

```diff
--- from commit 497c80a1ad7f ---
diff --git a/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala b/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala
index 606339aec95..7b17f44291c 100644
--- a/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala
+++ b/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala
@@ -16,10 +16,11 @@
  */
 package org.apache.spark.scheduler.cluster.k8s
 
 import java.time.Instant
 import java.util.concurrent.ConcurrentHashMap
+import java.util.concurrent.TimeUnit
 import java.util.concurrent.atomic.{AtomicInteger, AtomicLong}
 
 import scala.collection.JavaConverters._
 import scala.collection.mutable
 import scala.util.control.NonFatal
@@ -59,10 +60,12 @@ private[spark] class ExecutorPodsAllocator(
 
   private val podCreationTimeout = math.max(
     podAllocationDelay * 5,
     conf.get(KUBERNETES_ALLOCATION_EXECUTOR_TIMEOUT))
 
+  private val driverPodReadinessTimeout = conf.get(KUBERNETES_ALLOCATION_DRIVER_READINESS_TIMEOUT)
+
   private val executorIdleTimeout = conf.get(DYN_ALLOCATION_EXECUTOR_IDLE_TIMEOUT) * 1000
 
   private val namespace = conf.get(KUBERNETES_NAMESPACE)
 
   private val kubernetesDriverPodName = conf
@@ -97,10 +100,18 @@ private[spark] class ExecutorPodsAllocator(
   // a snapshot from the API server. This is used to deny registration from these executors
   // if they happen to come up before the deletion takes effect.
   @volatile private var deletedExecutorIds = Set.empty[Long]
 
   def start(applicationId: String, schedulerBackend: KubernetesClusterSchedulerBackend): Unit = {
+    // Wait until the driver pod is ready before starting executors, as the headless service won't
+    // be resolvable by DNS until the driver pod is ready.
+    Utils.tryLogNonFatalError {
+      kubernetesClient
+        .pods()
+        .withName(kubernetesDriverPodName.get)
+        .waitUntilReady(driverPodReadinessTimeout, TimeUnit.SECONDS)
+    }
     snapshotsStore.addSubscriber(podAllocationDelay) {
       onNewSnapshots(applicationId, schedulerBackend, _)
     }
   }
--- from commit b4b78ce26567 ---
diff --git a/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala b/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala
index 7b17f44291c..c101567a1d2 100644
--- a/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala
+++ b/resource-managers/kubernetes/core/src/main/scala/org/apache/spark/scheduler/cluster/k8s/ExecutorPodsAllocator.scala
@@ -100,17 +100,19 @@ private[spark] class ExecutorPodsAllocator(
   // a snapshot from the API server. This is used to deny registration from these executors
   // if they happen to come up before the deletion takes effect.
   @volatile private var deletedExecutorIds = Set.empty[Long]
 
   def start(applicationId: String, schedulerBackend: KubernetesClusterSchedulerBackend): Unit = {
-    // Wait until the driver pod is ready before starting executors, as the headless service won't
-    // be resolvable by DNS until the driver pod is ready.
-    Utils.tryLogNonFatalError {
-      kubernetesClient
-        .pods()
-        .withName(kubernetesDriverPodName.get)
-        .waitUntilReady(driverPodReadinessTimeout, TimeUnit.SECONDS)
+    driverPod.foreach { pod =>
+      // Wait until the driver pod is ready before starting executors, as the headless service won't
+      // be resolvable by DNS until the driver pod is ready.
+      Utils.tryLogNonFatalError {
+        kubernetesClient
+          .pods()
+          .withName(pod.getMetadata.getName)
+          .waitUntilReady(driverPodReadinessTimeout, TimeUnit.SECONDS)
+      }
     }
     snapshotsStore.addSubscriber(podAllocationDelay) {
       onNewSnapshots(applicationId, schedulerBackend, _)
     }
   }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
