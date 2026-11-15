# Annotation packet: CASSANDRA-16095  (cassandra)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
When a table attempts to clean up metrics, it was cleaning up all global table metrics

when i use
{code:java}
bin/nodetool tablestats xxxx{code}
i get this error
{code:java}
error: org.apache.cassandra.metrics:type=Table,keyspace=xxxx,scope=feed,name=WriteLatency
-- StackTrace --
javax.management.InstanceNotFoundException: org.apache.cassandra.metrics:type=Table,keyspace=xxxx,scope=feed,name=WriteLatency
{code}
if i restart the node and check it works but if i write something then i get the error again
 * Cassandra 4.0-beta1
 * Ubuntu 20
```

## Fix commit message(s)

`876ac8c61116`

```
When a table attempts to clean up metrics, it was cleaning up all global table metrics

patch by David Capwell; reviewed by Jon Meredith, Jordan West, Yifan Cai for CASSANDRA-16095
```

## Files the fix changed

Snapshot holds 1,998 non-test source files. The fix changed 8 file(s); 4 of them are non-test source files (listed below as gold).

- `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java`
- `src/java/org/apache/cassandra/db/ColumnFamilyStore.java`
- `src/java/org/apache/cassandra/metrics/TableMetrics.java`
- `src/java/org/apache/cassandra/utils/MBeanWrapper.java`

## The fix diff

### `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java`

```diff
diff --git a/src/java/org/apache/cassandra/config/CassandraRelevantProperties.java b/src/java/org/apache/cassandra/config/CassandraRelevantProperties.java
index 7402aa1523..5d918a842d 100644
--- a/src/java/org/apache/cassandra/config/CassandraRelevantProperties.java
+++ b/src/java/org/apache/cassandra/config/CassandraRelevantProperties.java
@@ -161,11 +161,14 @@ public enum CassandraRelevantProperties
     //only for testing
     ORG_APACHE_CASSANDRA_CONF_CASSANDRA_RELEVANT_PROPERTIES_TEST("org.apache.cassandra.conf.CassandraRelevantPropertiesTest"),
     ORG_APACHE_CASSANDRA_DB_VIRTUAL_SYSTEM_PROPERTIES_TABLE_TEST("org.apache.cassandra.db.virtual.SystemPropertiesTableTest"),
 
     /** This property indicates whether disable_mbean_registration is true */
-    IS_DISABLED_MBEAN_REGISTRATION("org.apache.cassandra.disable_mbean_registration");
+    IS_DISABLED_MBEAN_REGISTRATION("org.apache.cassandra.disable_mbean_registration"),
+
+    /** what class to use for mbean registeration */
+    MBEAN_REGISTRATION_CLASS("org.apache.cassandra.mbean_registration_class");
 
     CassandraRelevantProperties(String key, String defaultVal)
     {
         this.key = key;
         this.defaultVal = defaultVal;
@@ -194,10 +197,32 @@ public enum CassandraRelevantProperties
         String value = System.getProperty(key);
 
         return value == null ? defaultVal : STRING_CONVERTER.convert(value);
     }
 
+    /**
+     * Gets the value of a system property as a String.
+     * @return system property String value if it exists, overrideDefaultValue otherwise.
+     */
+    public String getString(String overrideDefaultValue)
+    {
+        String value = System.getProperty(key);
+        if (value == null)
+            return overrideDefaultValue;
+
+        return STRING_CONVERTER.convert(value);
+    }
+
+    /**
+     * Sets the value into system properties.
+     * @param value to set
+     */
+    public void setString(String value)
+    {
+        System.setProperty(key, value);
+    }
+
     /**
      * Gets the value of a system property as a boolean.
      * @return system property boolean value if it exists, false otherwise().
      */
     public boolean getBoolean()
@@ -205,10 +230,32 @@ public enum CassandraRelevantProperties
         String value = System.getProperty(key);
 
         return BOOLEAN_CONVERTER.convert(value == null ? defaultVal : value);
     }
 
+    /**
+     * Gets the value of a system property as a boolean.
+     * @return system property boolean value if it exists, overrideDefaultValue otherwise.
+     */
+    public boolean getBoolean(boolean overrideDefaultValue)
+    {
+        String value = System.getProperty(key);
+        if (value == null)
+            return overrideDefaultValue;
+
+        return BOOLEAN_CONVERTER.convert(value);
+    }
+
+    /**
+     * Sets the value into system properties.
+     * @param value to set
+     */
+    public void setBoolean(boolean value)
+    {
+        System.setProperty(key, Boolean.toString(value));
+    }
+
     /**
      * Gets the value of a system property as a int.
      * @return system property int value if it exists, defaultValue otherwise.
      */
     public int getInt()
@@ -216,10 +263,32 @@ public enum CassandraRelevantProperties
         String value = System.getProperty(key);
 
         return INTEGER_CONVERTER.convert(value == null ? defaultVal : value);
     }
 
+    /**
+     * Gets the value of a system property as a int.
+     * @return system property int value if it exists, overrideDefaultValue otherwise.
+     */
+    public int getInt(int overrideDefaultValue)
+    {
+        String value = System.getProperty(key);
+        if (value == null)
+            return overrideDefaultValue;
+
+        return INTEGER_CONVERTER.convert(value);
+    }
+
+    /**
+     * Sets the value into system properties.
+     * @param value to set
+     */
+    public void setInt(int value)
+    {
+        System.setProperty(key, Integer.toString(value));
+    }
+
     private interface PropertyConverter<T>
     {
         T convert(String value);
     }
```

### `src/java/org/apache/cassandra/db/ColumnFamilyStore.java`

```diff
diff --git a/src/java/org/apache/cassandra/db/ColumnFamilyStore.java b/src/java/org/apache/cassandra/db/ColumnFamilyStore.java
index f712d1b8cb..ceacd0d2b0 100644
--- a/src/java/org/apache/cassandra/db/ColumnFamilyStore.java
+++ b/src/java/org/apache/cassandra/db/ColumnFamilyStore.java
@@ -437,16 +437,12 @@ public class ColumnFamilyStore implements ColumnFamilyStoreMBean
         }
 
         if (registerBookeeping)
         {
             // register the mbean
-            mbeanName = String.format("org.apache.cassandra.db:type=%s,keyspace=%s,table=%s",
-                                         isIndex() ? "IndexTables" : "Tables",
-                                         keyspace.getName(), name);
-            oldMBeanName = String.format("org.apache.cassandra.db:type=%s,keyspace=%s,columnfamily=%s",
-                                         isIndex() ? "IndexColumnFamilies" : "ColumnFamilies",
-                                         keyspace.getName(), name);
+            mbeanName = getTableMBeanName(keyspace.getName(), name, isIndex());
+            oldMBeanName = getColumnFamilieMBeanName(keyspace.getName(), name, isIndex());
 
             String[] objectNames = {mbeanName, oldMBeanName};
             for (String objectName : objectNames)
                 MBeanWrapper.instance.registerMBean(this, objectName);
         }
@@ -459,10 +455,24 @@ public class ColumnFamilyStore implements ColumnFamilyStoreMBean
         streamManager = new CassandraStreamManager(this);
         repairManager = new CassandraTableRepairManager(this);
         sstableImporter = new SSTableImporter(this);
     }
 
+    public static String getTableMBeanName(String ks, String name, boolean isIndex)
+    {
+        return String.format("org.apache.cassandra.db:type=%s,keyspace=%s,table=%s",
+                      isIndex ? "IndexTables" : "Tables",
+                      ks, name);
+    }
+
+    public static String getColumnFamilieMBeanName(String ks, String name, boolean isIndex)
+    {
+       return String.format("org.apache.cassandra.db:type=%s,keyspace=%s,columnfamily=%s",
+                            isIndex ? "IndexColumnFamilies" : "ColumnFamilies",
+                            ks, name);
+    }
+
     public void updateSpeculationThreshold()
     {
         try
         {
             sampleReadLatencyNanos = metadata().params.speculativeRetry.calculateThreshold(metric.coordinatorReadLatency.getSnapshot(), sampleReadLatencyNanos);
```

### `src/java/org/apache/cassandra/metrics/TableMetrics.java`

```diff
diff --git a/src/java/org/apache/cassandra/metrics/TableMetrics.java b/src/java/org/apache/cassandra/metrics/TableMetrics.java
index eb42331bb1..634d9294b6 100644
--- a/src/java/org/apache/cassandra/metrics/TableMetrics.java
+++ b/src/java/org/apache/cassandra/metrics/TableMetrics.java
@@ -60,10 +60,22 @@ import com.codahale.metrics.RatioGauge;
 /**
  * Metrics for {@link ColumnFamilyStore}.
  */
 public class TableMetrics
 {
+    /**
+     * stores metrics that will be rolled into a single global metric
+     */
+    private static final ConcurrentMap<String, Set<Metric>> ALL_TABLE_METRICS = Maps.newConcurrentMap();
+    public static final long[] EMPTY = new long[0];
+    private static final MetricNameFactory GLOBAL_FACTORY = new AllTableMetricNameFactory("Table");
+    private static final MetricNameFactory GLOBAL_ALIAS_FACTORY = new AllTableMetricNameFactory("ColumnFamily");
+
+    public final static LatencyMetrics GLOBAL_READ_LATENCY = new LatencyMetrics(GLOBAL_FACTORY, GLOBAL_ALIAS_FACTORY, "Read");
+    public final static LatencyMetrics GLOBAL_WRITE_LATENCY = new LatencyMetrics(GLOBAL_FACTORY, GLOBAL_ALIAS_FACTORY, "Write");
+    public final static LatencyMetrics GLOBAL_RANGE_LATENCY = new LatencyMetrics(GLOBAL_FACTORY, GLOBAL_ALIAS_FACTORY, "Range");
+
     /** Total amount of data stored in the memtable that resides on-heap, including column related overhead and partitions overwritten. */
     public final Gauge<Long> memtableOnHeapDataSize;
     /** Total amount of data stored in the memtable that resides off-heap, including column related overhead and partitions overwritten. */
     public final Gauge<Long> memtableOffHeapDataSize;
     /** Total amount of live data stored in the memtable, excluding any data structure overhead */
@@ -203,12 +215,10 @@ public class TableMetrics
     @Deprecated
     public final Counter droppedMutations;
 
     private final MetricNameFactory factory;
     private final MetricNameFactory aliasFactory;
-    private static final MetricNameFactory globalFactory = new AllTableMetricNameFactory("Table");
-    private static final MetricNameFactory globalAliasFactory = new AllTableMetricNameFactory("ColumnFamily");
 
     public final Counter speculativeRetries;
     public final Counter speculativeFailedRetries;
     public final Counter speculativeInsufficientReplicas;
     public final Gauge<Long> speculativeSampleLatencyNanos;
@@ -236,14 +246,10 @@ public class TableMetrics
     // may read extra repaired data, up to the DataLimit of the command, so that the coordinator can compare
     // the repaired data on each replica. These are tracked on each replica.
     public final TableHistogram repairedDataTrackingOverreadRows;
     public final TableTimer repairedDataTrackingOverreadTime;
 
-    public final static LatencyMetrics globalReadLatency = new LatencyMetrics(globalFactory, globalAliasFactory, "Read");
-    public final static LatencyMetrics globalWriteLatency = new LatencyMetrics(globalFactory, globalAliasFactory, "Write");
-    public final static LatencyMetrics globalRangeLatency = new LatencyMetrics(globalFactory, globalAliasFactory, "Range");
-
     /** When sampler activated, will track the most frequently read partitions **/
     public final Sampler<ByteBuffer> topReadPartitionFrequency;
     /** When sampler activated, will track the most frequently written to partitions **/
     public final Sampler<ByteBuffer> topWritePartitionFrequency;
     /** When sampler activated, will track the largest mutations **/
@@ -282,11 +288,11 @@ public class TableMetrics
             }
         }
         return Pair.create(filtered, total);
     }
 
-    public static final Gauge<Double> globalPercentRepaired = Metrics.register(globalFactory.createMetricName("PercentRepaired"),
+    public static final Gauge<Double> globalPercentRepaired = Metrics.register(GLOBAL_FACTORY.createMetricName("PercentRepaired"),
                                                                                new Gauge<Double>()
     {
         public Double getValue()
         {
             Pair<Long, Long> result = totalNonSystemTablesSize(SSTableReader::isRepaired);
@@ -294,19 +300,19 @@ public class TableMetrics
             double total = result.right;
             return total > 0 ? (repaired / total) * 100 : 100.0;
         }
     });
 
-    public static final Gauge<Long> globalBytesRepaired = Metrics.register(globalFactory.createMetricName("BytesRepaired"),
+    public static final Gauge<Long> globalBytesRepaired = Metrics.register(GLOBAL_FACTORY.createMetricName("BytesRepaired"),
                                                                            () -> totalNonSystemTablesSize(SSTableReader::isRepaired).left);
 
     public static final Gauge<Long> globalBytesUnrepaired = 
-        Metrics.register(globalFactory.createMetricName("BytesUnrepaired"),
+        Metrics.register(GLOBAL_FACTORY.createMetricName("BytesUnrepaired"),
                          () -> totalNonSystemTablesSize(s -> !s.isRepaired() && !s.isPendingRepair()).left);
 
     public static final Gauge<Long> globalBytesPendingRepair = 
-        Metrics.register(globalFactory.createMetricName("BytesPendingRepair"),
+        Metrics.register(GLOBAL_FACTORY.createMetricName("BytesPendingRepair"),
                          () -> totalNonSystemTablesSize(SSTableReader::isPendingRepair).left);
 
     public final Meter readRepairRequests;
     public final Meter shortReadProtectionRequests;
     
@@ -319,19 +325,15 @@ public class TableMetrics
      * replica_filtering_protection thresholds in cassandra.yaml.
      */
     public final Histogram rfpRowsCachedPerQuery;
 
     public final EnumMap<SamplerType, Sampler<?>> samplers;
-    /**
-     * stores metrics that will be rolled into a single global metric
-     */
-    public final static ConcurrentMap<String, Set<Metric>> allTableMetrics = Maps.newConcurrentMap();
 
     /**
      * Stores all metrics created that can be used when unregistering
      */
-    public final static Set<ReleasableMetric> all = Sets.newHashSet();
+    private final Set<ReleasableMetric> all = Sets.newHashSet();
 
     private interface GetHistogram
     {
         EstimatedHistogram getHistogram(SSTableReader reader);
     }
@@ -564,13 +566,13 @@ public class TableMetrics
                 }
                 return size;
             }
         });
 
-        readLatency = createLatencyMetrics("Read", cfs.keyspace.metric.readLatency, globalReadLatency);
-        writeLatency = createLatencyMetrics("Write", cfs.keyspace.metric.writeLatency, globalWriteLatency);
-        rangeLatency = createLatencyMetrics("Range", cfs.keyspace.metric.rangeLatency, globalRangeLatency);
+        readLatency = createLatencyMetrics("Read", cfs.keyspace.metric.readLatency, GLOBAL_READ_LATENCY);
+        writeLatency = createLatencyMetrics("Write", cfs.keyspace.metric.writeLatency, GLOBAL_WRITE_LATENCY);
+        rangeLatency = createLatencyMetrics("Range", cfs.keyspace.metric.rangeLatency, GLOBAL_RANGE_LATENCY);
         pendingFlushes = createTableCounter("PendingFlushes");
         bytesFlushed = createTableCounter("BytesFlushed");
 
         compactionBytesWritten = createTableCounter("CompactionBytesWritten");
         pendingCompactions = createTableGauge("PendingCompactions", () -> cfs.getCompactionStrategyManager().getEstimatedRemainingTasks());
@@ -603,11 +605,11 @@ public class TableMetrics
         }, new Gauge<Long>() // global gauge
         {
             public Long getValue()
             {
                 long min = Long.MAX_VALUE;
-                for (Metric cfGauge : allTableMetrics.get("MinPartitionSize"))
+                for (Metric cfGauge : ALL_TABLE_METRICS.get("MinPartitionSize"))
                 {
                     min = Math.min(min, ((Gauge<? extends Number>) cfGauge).getValue().longValue());
                 }
                 return min;
             }
@@ -627,11 +629,11 @@ public class TableMetrics
         }, new Gauge<Long>() // global gauge
         {
             public Long getValue()
             {
                 long max = 0;
-                for (Metric cfGauge : allTableMetrics.get("MaxPartitionSize"))
+                for (Metric cfGauge : ALL_TABLE_METRICS.get("MaxPartitionSize"))
                 {
                     max = Math.max(max, ((Gauge<? extends Number>) cfGauge).getValue().longValue());
                 }
                 return max;
             }
@@ -895,11 +897,11 @@ public class TableMetrics
         repairedDataTrackingOverreadTime = createTableTimer("RepairedDataTrackingOverreadTime", cfs.keyspace.metric.repairedDataTrackingOverreadTime);
 
         unleveledSSTables = createTableGauge("UnleveledSSTables", cfs::getUnleveledSSTables, () -> {
             // global gauge
             int cnt = 0;
-            for (Metric cfGauge : allTableMetrics.get("UnleveledSSTables"))
+            for (Metric cfGauge : ALL_TABLE_METRICS.get("UnleveledSSTables"))
             {
                 cnt += ((Gauge<? extends Number>) cfGauge).getValue().intValue();
             }
             return cnt;
         });
@@ -942,11 +944,11 @@ public class TableMetrics
     protected <G,T> Gauge<T> createTableGauge(String name, String alias, Gauge<T> gauge, Gauge<G> globalGauge)
     {
         Gauge<T> cfGauge = Metrics.register(factory.createMetricName(name), aliasFactory.createMetricName(alias), gauge);
         if (register(name, alias, cfGauge) && globalGauge != null)
         {
-            Metrics.register(globalFactory.createMetricName(name), globalAliasFactory.createMetricName(alias), globalGauge);
+            Metrics.register(GLOBAL_FACTORY.createMetricName(name), GLOBAL_ALIAS_FACTORY.createMetricName(alias), globalGauge);
         }
         return cfGauge;
     }
 
     /**
@@ -967,15 +969,15 @@ public class TableMetrics
                                             factory.createMetricName(deprecated),
                                             aliasFactory.createMetricName(deprecated));
         
         if (register(name, name, deprecated, cfGauge))
         {
-            Metrics.register(globalFactory.createMetricName(name), 
+            Metrics.register(GLOBAL_FACTORY.createMetricName(name),
                              globalGauge,
-                             globalAliasFactory.createMetricName(name),
-                             globalFactory.createMetricName(deprecated),
-                             globalAliasFactory.createMetricName(deprecated));
+                             GLOBAL_ALIAS_FACTORY.createMetricName(name),
+                             GLOBAL_FACTORY.createMetricName(deprecated),
+                             GLOBAL_ALIAS_FACTORY.createMetricName(deprecated));
         }
         return cfGauge;
     }
 
     /**
@@ -990,18 +992,18 @@ public class TableMetrics
     protected Counter createTableCounter(final String name, final String alias)
     {
         Counter cfCounter = Metrics.counter(factory.createMetricName(name), aliasFactory.createMetricName(alias));
         if (register(name, alias, cfCounter))
         {
-            Metrics.register(globalFactory.createMetricName(name),
-                             globalAliasFactory.createMetricName(alias),
+            Metrics.register(GLOBAL_FACTORY.createMetricName(name),
+                             GLOBAL_ALIAS_FACTORY.createMetricName(alias),
                              new Gauge<Long>()
             {
                 public Long getValue()
                 {
                     long total = 0;
-                    for (Metric cfGauge : allTableMetrics.get(name))
+                    for (Metric cfGauge : ALL_TABLE_METRICS.get(name))
                     {
                         total += ((Counter) cfGauge).getCount();
                     }
                     return total;
                 }
@@ -1068,12 +1070,12 @@ public class TableMetrics
     {
         Histogram cfHistogram = Metrics.histogram(factory.createMetricName(name), aliasFactory.createMetricName(alias), considerZeroes);
         register(name, alias, cfHistogram);
         return new TableHistogram(cfHistogram,
                                   keyspaceHistogram,
-                                  Metrics.histogram(globalFactory.createMetricName(name),
-                                                    globalAliasFactory.createMetricName(alias),
+                                  Metrics.histogram(GLOBAL_FACTORY.createMetricName(name),
+                                                    GLOBAL_ALIAS_FACTORY.createMetricName(alias),
                                                     considerZeroes));
     }
 
     protected Histogram createTableHistogram(String name, boolean considerZeroes)
     {
@@ -1089,11 +1091,11 @@ public class TableMetrics
 
     protected TableTimer createTableTimer(String name, Timer keyspaceTimer)
     {
         Timer cfTimer = Metrics.timer(factory.createMetricName(name), aliasFactory.createMetricName(name));
         register(name, name, keyspaceTimer);
-        Timer global = Metrics.timer(globalFactory.createMetricName(name), globalAliasFactory.createMetricName(name));
+        Timer global = Metrics.timer(GLOBAL_FACTORY.createMetricName(name), GLOBAL_ALIAS_FACTORY.createMetricName(name));
 
         return new TableTimer(cfTimer, keyspaceTimer, global);
     }
 
     protected Timer createTableTimer(String name)
@@ -1112,12 +1114,12 @@ public class TableMetrics
     {
         Meter meter = Metrics.meter(factory.createMetricName(name), aliasFactory.createMetricName(alias));
         register(name, alias, meter);
         return new TableMeter(meter,
                               keyspaceMeter,
-                              Metrics.meter(globalFactory.createMetricName(name),
-                                            globalAliasFactory.createMetricName(alias)));
+                              Metrics.meter(GLOBAL_FACTORY.createMetricName(name),
+                                            GLOBAL_ALIAS_FACTORY.createMetricName(alias)));
     }
 
     private LatencyMetrics createLatencyMetrics(String namePrefix, LatencyMetrics ... parents)
     {
         LatencyMetrics metric = new LatencyMetrics(factory, namePrefix, parents);
@@ -1143,12 +1145,12 @@ public class TableMetrics
      * 
      * @return true if first time metric with that name has been registered
      */
     private boolean register(String name, String alias, String deprecated, Metric metric)
     {
-        boolean ret = allTableMetrics.putIfAbsent(name, ConcurrentHashMap.newKeySet()) == null;
-        allTableMetrics.get(name).add(metric);
+        boolean ret = ALL_TABLE_METRICS.putIfAbsent(name, ConcurrentHashMap.newKeySet()) == null;
+        ALL_TABLE_METRICS.get(name).add(metric);
         all.add(() -> releaseMetric(name, alias, deprecated));
         return ret;
     }
 
     private void releaseMetric(String tableMetricName, String cfMetricName, String tableMetricAlias)
@@ -1157,11 +1159,11 @@ public class TableMetrics
 
         final Metric metric = Metrics.getMetrics().get(name.getMetricName());
         if (metric != null)
         {
             // Metric will be null if we are releasing a view metric.  Views have null for ViewLockAcquireTime and ViewLockReadTime
-            allTableMetrics.get(tableMetricName).remove(metric);
+            ALL_TABLE_METRICS.get(tableMetricName).remove(metric);
             CassandraMetricsRegistry.MetricName cfAlias = aliasFactory.createMetricName(cfMetricName);
             
             if (tableMetricAlias != null)
             {
                 Metrics.remove(name, cfAlias, factory.createMetricName(tableMetricAlias), aliasFactory.createMetricName(tableMetricAlias));
@@ -1329,11 +1331,11 @@ public class TableMetrics
         }
 
         public Long getValue()
         {
             long total = 0;
-            for (Metric cfGauge : allTableMetrics.get(name))
+            for (Metric cfGauge : ALL_TABLE_METRICS.get(name))
             {
                 total = total + ((Gauge<? extends Number>) cfGauge).getValue().longValue();
             }
             return total;
         }
```

### `src/java/org/apache/cassandra/utils/MBeanWrapper.java`

```diff
diff --git a/src/java/org/apache/cassandra/utils/MBeanWrapper.java b/src/java/org/apache/cassandra/utils/MBeanWrapper.java
index 81d8dae071..f8bc439d7b 100644
--- a/src/java/org/apache/cassandra/utils/MBeanWrapper.java
+++ b/src/java/org/apache/cassandra/utils/MBeanWrapper.java
@@ -19,39 +19,54 @@
 package org.apache.cassandra.utils;
 
 import java.lang.management.ManagementFactory;
 import java.util.function.Consumer;
 import javax.management.MBeanServer;
+import javax.management.MalformedObjectNameException;
 import javax.management.ObjectName;
 
 import org.slf4j.Logger;
 import org.slf4j.LoggerFactory;
 
-import org.apache.cassandra.config.CassandraRelevantProperties;
-
 import static org.apache.cassandra.config.CassandraRelevantProperties.IS_DISABLED_MBEAN_REGISTRATION;
+import static org.apache.cassandra.config.CassandraRelevantProperties.MBEAN_REGISTRATION_CLASS;
 
 /**
  * Helper class to avoid catching and rethrowing checked exceptions on MBean and
  * allow turning of MBean registration for test purposes.
  */
 public interface MBeanWrapper
 {
     static final Logger logger = LoggerFactory.getLogger(MBeanWrapper.class);
 
-    static final MBeanWrapper instance = IS_DISABLED_MBEAN_REGISTRATION.getBoolean() ?
-                                         new NoOpMBeanWrapper() :
-                                         new PlatformMBeanWrapper();
+    static final MBeanWrapper instance = create();
+
+    static MBeanWrapper create()
+    {
+        if (IS_DISABLED_MBEAN_REGISTRATION.getBoolean())
+            return new NoOpMBeanWrapper();
+
+        String klass = MBEAN_REGISTRATION_CLASS.getString();
+        if (klass == null)
+            return new PlatformMBeanWrapper();
+        return FBUtilities.construct(klass, "mbean");
+    }
 
     // Passing true for graceful will log exceptions instead of rethrowing them
     public void registerMBean(Object obj, ObjectName mbeanName, OnException onException);
     default void registerMBean(Object obj, ObjectName mbeanName)
     {
         registerMBean(obj, mbeanName, OnException.THROW);
     }
 
-    public void registerMBean(Object obj, String mbeanName, OnException onException);
+    default void registerMBean(Object obj, String mbeanName, OnException onException)
+    {
+        ObjectName name = create(mbeanName, onException);
+        if (name == null)
+            return;
+        registerMBean(obj, name, onException);
+    }
     default void registerMBean(Object obj, String mbeanName)
     {
         registerMBean(obj, mbeanName, OnException.THROW);
     }
 
@@ -59,11 +74,17 @@ public interface MBeanWrapper
     default boolean isRegistered(ObjectName mbeanName)
     {
         return isRegistered(mbeanName, OnException.THROW);
     }
 
-    public boolean isRegistered(String mbeanName, OnException onException);
+    default boolean isRegistered(String mbeanName, OnException onException)
+    {
+        ObjectName name = create(mbeanName, onException);
+        if (name == null)
+            return false;
+        return isRegistered(name, onException);
+    }
     default boolean isRegistered(String mbeanName)
     {
         return isRegistered(mbeanName, OnException.THROW);
     }
 
@@ -71,16 +92,35 @@ public interface MBeanWrapper
     default void unregisterMBean(ObjectName mbeanName)
     {
         unregisterMBean(mbeanName, OnException.THROW);
     }
 
-    public void unregisterMBean(String mbeanName, OnException onException);
+    default void unregisterMBean(String mbeanName, OnException onException)
+    {
+        ObjectName name = create(mbeanName, onException);
+        if (name == null)
+            return;
+        unregisterMBean(name, onException);
+    }
     default void unregisterMBean(String mbeanName)
     {
         unregisterMBean(mbeanName, OnException.THROW);
     }
 
+    static ObjectName create(String mbeanName, OnException onException)
+    {
+        try
+        {
+            return new ObjectName(mbeanName);
+        }
+        catch (MalformedObjectNameException e)
+        {
+            onException.handler.accept(e);
+            return null;
+        }
+    }
+
     static class NoOpMBeanWrapper implements MBeanWrapper
     {
         public void registerMBean(Object obj, ObjectName mbeanName, OnException onException) {}
         public void registerMBean(Object obj, String mbeanName, OnException onException) {}
         public boolean isRegistered(ObjectName mbeanName, OnException onException) { return false; }
@@ -102,22 +142,10 @@ public interface MBeanWrapper
             {
                 onException.handler.accept(e);
             }
         }
 
-        public void registerMBean(Object obj, String mbeanName, OnException onException)
-        {
-            try
-            {
-                mbs.registerMBean(obj, new ObjectName(mbeanName));
-            }
-            catch (Exception e)
-            {
-                onException.handler.accept(e);
-            }
-        }
-
         public boolean isRegistered(ObjectName mbeanName, OnException onException)
         {
             try
             {
                 return mbs.isRegistered(mbeanName);
@@ -127,23 +155,10 @@ public interface MBeanWrapper
                 onException.handler.accept(e);
             }
             return false;
         }
 
-        public boolean isRegistered(String mbeanName, OnException onException)
-        {
-            try
-            {
-                return mbs.isRegistered(new ObjectName(mbeanName));
-            }
-            catch (Exception e)
-            {
-                onException.handler.accept(e);
-            }
-            return false;
-        }
-
         public void unregisterMBean(ObjectName mbeanName, OnException onException)
         {
             try
             {
                 mbs.unregisterMBean(mbeanName);
@@ -151,31 +166,19 @@ public interface MBeanWrapper
             catch (Exception e)
             {
                 onException.handler.accept(e);
             }
         }
-
-        public void unregisterMBean(String mbeanName, OnException onException)
-        {
-            try
-            {
-                mbs.unregisterMBean(new ObjectName(mbeanName));
-            }
-            catch (Exception e)
-            {
-                onException.handler.accept(e);
-            }
-        }
     }
 
     public enum OnException
     {
         THROW(e -> { throw new RuntimeException(e); }),
         LOG(e -> { logger.error("Error in MBean wrapper: ", e); }),
         IGNORE(e -> {});
 
-        private Consumer<Exception> handler;
+        public final Consumer<Exception> handler;
         OnException(Consumer<Exception> handler)
         {
             this.handler = handler;
         }
     }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
