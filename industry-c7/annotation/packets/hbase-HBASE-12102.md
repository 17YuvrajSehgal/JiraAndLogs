# Annotation packet: HBASE-12102  (hbase)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Duplicate keys in HBase.RegionServer metrics JSON

The JSON returned by /jmx on the RegionServer contains duplicate 'tag.Context' keys for various HBase.RegionServer metrics. 

Regions:
{noformat}
{
    "name" : "Hadoop:service=HBase,name=RegionServer,sub=Regions",
    "modelerType" : "RegionServer,sub=Regions",
    "tag.Context" : "regionserver",
    "tag.Context" : "regionserver",
    "tag.Hostname" : "some.host.name",
    ...
}
{noformat}

Server:
{noformat}
"name" : "Hadoop:service=HBase,name=RegionServer,sub=Server",
    "modelerType" : "RegionServer,sub=Server",
    "tag.Context" : "regionserver",
    "tag.zookeeperQuorum" : "some.zookeeper.quorum.peers",
    "tag.serverName" : "some.server.name",
    "tag.clusterId" : "88c186ea-2308-4713-8b5f-5a3e829cbb10",
    "tag.Context" : "regionserver",
    ...
}
{noformat}

IPC:
{noformat}
{
    "name" : "Hadoop:service=HBase,name=IPC,sub=IPC",
    "modelerType" : "IPC,sub=IPC",
    "tag.Context" : "ipc",
    "tag.Context" : "ipc",
    "tag.Hostname" : "some.host.name",
    ...
}
{noformat}

This can cause issues with some JSON parsers. We should avoid emitting duplicate keys if it is under our control.
```

## Fix commit message(s)

`cecc475d2f19`

```
HBASE-12102 Duplicate keys in HBase.RegionServer metrics JSON (Ravi Kishore Valeti)
```

## Files the fix changed

Snapshot holds 1,483 non-test source files. The fix changed 4 file(s); 4 of them are non-test source files (listed below as gold).

- `hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/ipc/MetricsHBaseServerSourceImpl.java`
- `hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/master/MetricsMasterSourceImpl.java`
- `hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionAggregateSourceImpl.java`
- `hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionServerSourceImpl.java`

## The fix diff

### `hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/ipc/MetricsHBaseServerSourceImpl.java`

```diff
diff --git a/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/ipc/MetricsHBaseServerSourceImpl.java b/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/ipc/MetricsHBaseServerSourceImpl.java
index 2f5e5cf289..04cf953642 100644
--- a/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/ipc/MetricsHBaseServerSourceImpl.java
+++ b/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/ipc/MetricsHBaseServerSourceImpl.java
@@ -108,12 +108,11 @@ public class MetricsHBaseServerSourceImpl extends BaseSourceImpl
     processCallTime.add(processingTime);
   }
 
   @Override
   public void getMetrics(MetricsCollector metricsCollector, boolean all) {
-    MetricsRecordBuilder mrb = metricsCollector.addRecord(metricsName)
-        .setContext(metricsContext);
+    MetricsRecordBuilder mrb = metricsCollector.addRecord(metricsName);
 
     if (wrapper != null) {
       mrb.addGauge(Interns.info(QUEUE_SIZE_NAME, QUEUE_SIZE_DESC), wrapper.getTotalQueueSize())
           .addGauge(Interns.info(GENERAL_QUEUE_NAME, GENERAL_QUEUE_DESC),
               wrapper.getGeneralQueueLength())
```

### `hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/master/MetricsMasterSourceImpl.java`

```diff
diff --git a/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/master/MetricsMasterSourceImpl.java b/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/master/MetricsMasterSourceImpl.java
index d4c90dcb88..02463f618c 100644
--- a/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/master/MetricsMasterSourceImpl.java
+++ b/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/master/MetricsMasterSourceImpl.java
@@ -66,12 +66,11 @@ public class MetricsMasterSourceImpl
   }
 
   @Override
   public void getMetrics(MetricsCollector metricsCollector, boolean all) {
 
-    MetricsRecordBuilder metricsRecordBuilder = metricsCollector.addRecord(metricsName)
-        .setContext(metricsContext);
+    MetricsRecordBuilder metricsRecordBuilder = metricsCollector.addRecord(metricsName);
 
     // masterWrapper can be null because this function is called inside of init.
     if (masterWrapper != null) {
       metricsRecordBuilder
           .addGauge(Interns.info(MASTER_ACTIVE_TIME_NAME,
```

### `hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionAggregateSourceImpl.java`

```diff
diff --git a/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionAggregateSourceImpl.java b/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionAggregateSourceImpl.java
index 5cb2cec414..ab7255e8f0 100644
--- a/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionAggregateSourceImpl.java
+++ b/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionAggregateSourceImpl.java
@@ -78,12 +78,11 @@ public class MetricsRegionAggregateSourceImpl extends BaseSourceImpl
    */
   @Override
   public void getMetrics(MetricsCollector collector, boolean all) {
 
 
-    MetricsRecordBuilder mrb = collector.addRecord(metricsName)
-        .setContext(metricsContext);
+    MetricsRecordBuilder mrb = collector.addRecord(metricsName);
 
     if (regionSources != null) {
       lock.readLock().lock();
       try {
         for (MetricsRegionSourceImpl regionMetricSource : regionSources) {
```

### `hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionServerSourceImpl.java`

```diff
diff --git a/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionServerSourceImpl.java b/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionServerSourceImpl.java
index 2c1dcd325f..4cd73a9ec2 100644
--- a/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionServerSourceImpl.java
+++ b/hbase-hadoop2-compat/src/main/java/org/apache/hadoop/hbase/regionserver/MetricsRegionServerSourceImpl.java
@@ -174,12 +174,11 @@ public class MetricsRegionServerSourceImpl
    * @param all              push all or only changed?
    */
   @Override
   public void getMetrics(MetricsCollector metricsCollector, boolean all) {
 
-    MetricsRecordBuilder mrb = metricsCollector.addRecord(metricsName)
-        .setContext(metricsContext);
+    MetricsRecordBuilder mrb = metricsCollector.addRecord(metricsName);
 
     // rsWrap can be null because this function is called inside of init.
     if (rsWrap != null) {
       mrb.addGauge(Interns.info(REGION_COUNT, REGION_COUNT_DESC), rsWrap.getNumOnlineRegions())
           .addGauge(Interns.info(STORE_COUNT, STORE_COUNT_DESC), rsWrap.getNumStores())
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
