# Annotation packet: PHOENIX-3308  (phoenix)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Shutdown minicluster after parallel tests complete

We're currently not shutting down the mini cluster for tests that don't run in their own mini cluster. This might be the cause of the hangs we're seeing.
```

## Fix commit message(s)

`8174fc44b736`

```
PHOENIX-3308 Shutdown minicluster after parallel tests complete
```

`ad07077c7271`

```
PHOENIX-3308 Shutdown minicluster after parallel tests complete
```

## Files the fix changed

Snapshot holds 1,330 non-test source files. The fix changed 11 file(s); 7 of them are non-test source files (listed below as gold).

- `phoenix-core/src/it/java/org/apache/phoenix/end2end/index/ImmutableIndexIT.java`
- `phoenix-flume/src/it/java/org/apache/phoenix/flume/PhoenixSinkIT.java`
- `phoenix-flume/src/it/java/org/apache/phoenix/flume/RegexEventSerializerIT.java`
- `phoenix-pherf/src/it/java/org/apache/phoenix/pherf/ResultBaseTestIT.java`
- `phoenix-pherf/src/it/java/org/apache/phoenix/pherf/SchemaReaderIT.java`
- `phoenix-pig/src/it/java/org/apache/phoenix/pig/BasePigIT.java`
- `phoenix-queryserver/src/it/java/org/apache/phoenix/end2end/QueryServerBasicsIT.java`

## The fix diff

### `phoenix-core/src/it/java/org/apache/phoenix/end2end/index/ImmutableIndexIT.java`

```diff
--- from commit ad07077c7271 ---
diff --git a/phoenix-core/src/it/java/org/apache/phoenix/end2end/index/ImmutableIndexIT.java b/phoenix-core/src/it/java/org/apache/phoenix/end2end/index/ImmutableIndexIT.java
index 3e413e2dc..40faaf4ce 100644
--- a/phoenix-core/src/it/java/org/apache/phoenix/end2end/index/ImmutableIndexIT.java
+++ b/phoenix-core/src/it/java/org/apache/phoenix/end2end/index/ImmutableIndexIT.java
@@ -46,32 +46,30 @@ import org.apache.hadoop.hbase.client.Put;
 import org.apache.hadoop.hbase.coprocessor.ObserverContext;
 import org.apache.hadoop.hbase.coprocessor.RegionCoprocessorEnvironment;
 import org.apache.hadoop.hbase.coprocessor.SimpleRegionObserver;
 import org.apache.hadoop.hbase.regionserver.wal.WALEdit;
 import org.apache.hadoop.hbase.util.Bytes;
-import org.apache.phoenix.end2end.ParallelStatsDisabledIT;
-import org.apache.phoenix.end2end.Shadower;
+import org.apache.phoenix.end2end.BaseOwnClusterIT;
 import org.apache.phoenix.exception.SQLExceptionCode;
 import org.apache.phoenix.query.BaseTest;
 import org.apache.phoenix.query.QueryServices;
 import org.apache.phoenix.util.PropertiesUtil;
 import org.apache.phoenix.util.ReadOnlyProps;
 import org.apache.phoenix.util.SchemaUtil;
 import org.apache.phoenix.util.TestUtil;
 import org.junit.BeforeClass;
-import org.junit.Ignore;
 import org.junit.Test;
 import org.junit.runner.RunWith;
 import org.junit.runners.Parameterized;
 import org.junit.runners.Parameterized.Parameters;
 
 import com.google.common.collect.Lists;
 import com.google.common.collect.Maps;
 
 
 @RunWith(Parameterized.class)
-public class ImmutableIndexIT extends ParallelStatsDisabledIT {
+public class ImmutableIndexIT extends BaseOwnClusterIT {
 
     private final boolean localIndex;
     private final String tableDDLOptions;
 
     private volatile boolean stopThreads = false;
@@ -89,11 +87,10 @@ public class ImmutableIndexIT extends ParallelStatsDisabledIT {
         this.tableDDLOptions = optionBuilder.toString();
 
     }
 
     @BeforeClass
-    @Shadower(classBeingShadowed = ParallelStatsDisabledIT.class)
     public static void doSetup() throws Exception {
         Map<String, String> serverProps = Maps.newHashMapWithExpectedSize(1);
         serverProps.put("hbase.coprocessor.region.classes", CreateIndexRegionObserver.class.getName());
         Map<String, String> clientProps = Maps.newHashMapWithExpectedSize(2);
         clientProps.put(QueryServices.TRANSACTIONS_ENABLED, "true");
@@ -107,11 +104,10 @@ public class ImmutableIndexIT extends ParallelStatsDisabledIT {
 				{ false, false }, { false, true },
 				{ true, false }, { true, true } });
     }
 
     @Test
-    @Ignore
     public void testDropIfImmutableKeyValueColumn() throws Exception {
         Properties props = PropertiesUtil.deepCopy(TEST_PROPERTIES);
         String tableName = "TBL_" + generateRandomString();
         String indexName = "IND_" + generateRandomString();
         String fullTableName = SchemaUtil.getTableName(TestUtil.DEFAULT_SCHEMA_NAME, tableName);
@@ -156,11 +152,10 @@ public class ImmutableIndexIT extends ParallelStatsDisabledIT {
         Properties props = PropertiesUtil.deepCopy(TEST_PROPERTIES);
         props.setProperty(QueryServices.MUTATE_BATCH_SIZE_ATTRIB, Integer.toString(100));
         String tableName = "TBL_" + generateRandomString();
         String indexName = "IND_" + generateRandomString();
         String fullTableName = SchemaUtil.getTableName(TestUtil.DEFAULT_SCHEMA_NAME, tableName);
-        String fullIndexName = SchemaUtil.getTableName(TestUtil.DEFAULT_SCHEMA_NAME, indexName);
         TABLE_NAME = fullTableName;
         String ddl ="CREATE TABLE " + TABLE_NAME + BaseTest.TEST_TABLE_SCHEMA + tableDDLOptions;
         INDEX_DDL = "CREATE " + (localIndex ? "LOCAL" : "") + " INDEX IF NOT EXISTS " + indexName + " ON " + TABLE_NAME
                 + " (long_pk, varchar_pk)"
                 + " INCLUDE (long_col1, long_col2)";
```

### `phoenix-flume/src/it/java/org/apache/phoenix/flume/PhoenixSinkIT.java`

```diff
--- from commit ad07077c7271 ---
diff --git a/phoenix-flume/src/it/java/org/apache/phoenix/flume/PhoenixSinkIT.java b/phoenix-flume/src/it/java/org/apache/phoenix/flume/PhoenixSinkIT.java
index 9b5988c76..2d52fc2d0 100644
--- a/phoenix-flume/src/it/java/org/apache/phoenix/flume/PhoenixSinkIT.java
+++ b/phoenix-flume/src/it/java/org/apache/phoenix/flume/PhoenixSinkIT.java
@@ -18,39 +18,42 @@
 package org.apache.phoenix.flume;
 
 import static org.apache.phoenix.util.TestUtil.TEST_PROPERTIES;
 import static org.junit.Assert.assertTrue;
 import static org.junit.Assert.fail;
+import static org.mockito.Mockito.mock;
+import static org.mockito.Mockito.verify;
 
-import org.apache.flume.*;
+import java.sql.Connection;
+import java.sql.DriverManager;
+import java.sql.ResultSet;
+import java.util.Properties;
+
+import org.apache.flume.Channel;
+import org.apache.flume.Context;
+import org.apache.flume.Sink;
+import org.apache.flume.SinkFactory;
+import org.apache.flume.Transaction;
 import org.apache.flume.channel.MemoryChannel;
 import org.apache.flume.conf.Configurables;
 import org.apache.flume.event.EventBuilder;
 import org.apache.flume.lifecycle.LifecycleState;
 import org.apache.flume.sink.DefaultSinkFactory;
 import org.apache.hadoop.hbase.client.HBaseAdmin;
 import org.apache.hadoop.hbase.util.Bytes;
-import org.apache.phoenix.end2end.ParallelStatsDisabledIT;
-import org.apache.phoenix.flume.serializer.EventSerializers;
+import org.apache.phoenix.end2end.BaseHBaseManagedTimeIT;
 import org.apache.phoenix.flume.serializer.CustomSerializer;
+import org.apache.phoenix.flume.serializer.EventSerializers;
 import org.apache.phoenix.flume.sink.NullPhoenixSink;
 import org.apache.phoenix.flume.sink.PhoenixSink;
 import org.apache.phoenix.util.PropertiesUtil;
 import org.apache.phoenix.util.TestUtil;
 import org.junit.Assert;
 import org.junit.Test;
 
-import java.sql.Connection;
-import java.sql.DriverManager;
-import java.sql.ResultSet;
-import java.util.Properties;
-
-import static org.mockito.Mockito.mock;
-import static org.mockito.Mockito.verify;
-
 
-public class PhoenixSinkIT extends ParallelStatsDisabledIT {
+public class PhoenixSinkIT extends BaseHBaseManagedTimeIT {
 
     private Context sinkContext;
     private PhoenixSink sink;
```

### `phoenix-flume/src/it/java/org/apache/phoenix/flume/RegexEventSerializerIT.java`

```diff
--- from commit ad07077c7271 ---
diff --git a/phoenix-flume/src/it/java/org/apache/phoenix/flume/RegexEventSerializerIT.java b/phoenix-flume/src/it/java/org/apache/phoenix/flume/RegexEventSerializerIT.java
index eb3f9e8c7..7348a6563 100644
--- a/phoenix-flume/src/it/java/org/apache/phoenix/flume/RegexEventSerializerIT.java
+++ b/phoenix-flume/src/it/java/org/apache/phoenix/flume/RegexEventSerializerIT.java
@@ -38,22 +38,22 @@ import org.apache.flume.Transaction;
 import org.apache.flume.channel.MemoryChannel;
 import org.apache.flume.conf.Configurables;
 import org.apache.flume.event.EventBuilder;
 import org.apache.flume.lifecycle.LifecycleState;
 import org.apache.hadoop.hbase.util.Bytes;
-import org.apache.phoenix.end2end.ParallelStatsDisabledIT;
+import org.apache.phoenix.end2end.BaseHBaseManagedTimeIT;
 import org.apache.phoenix.flume.serializer.EventSerializers;
 import org.apache.phoenix.flume.sink.PhoenixSink;
 import org.apache.phoenix.util.PropertiesUtil;
 import org.junit.Test;
 
 import com.google.common.base.Preconditions;
 import com.google.common.collect.Lists;
 import com.google.common.collect.Maps;
 
 
-public class RegexEventSerializerIT extends ParallelStatsDisabledIT {
+public class RegexEventSerializerIT extends BaseHBaseManagedTimeIT {
 
     private Context sinkContext;
     private PhoenixSink sink;
     
     @Test
```

### `phoenix-pherf/src/it/java/org/apache/phoenix/pherf/ResultBaseTestIT.java`

```diff
--- from commit ad07077c7271 ---
diff --git a/phoenix-pherf/src/it/java/org/apache/phoenix/pherf/ResultBaseTestIT.java b/phoenix-pherf/src/it/java/org/apache/phoenix/pherf/ResultBaseTestIT.java
index c300701f7..1e77f480f 100644
--- a/phoenix-pherf/src/it/java/org/apache/phoenix/pherf/ResultBaseTestIT.java
+++ b/phoenix-pherf/src/it/java/org/apache/phoenix/pherf/ResultBaseTestIT.java
@@ -16,23 +16,23 @@
  *   limitations under the License.
  */
 
 package org.apache.phoenix.pherf;
 
-import org.apache.phoenix.end2end.ParallelStatsDisabledIT;
+import java.nio.file.Path;
+import java.util.List;
+import java.util.Properties;
+
+import org.apache.phoenix.end2end.BaseHBaseManagedTimeIT;
 import org.apache.phoenix.pherf.configuration.XMLConfigParser;
 import org.apache.phoenix.pherf.result.ResultUtil;
 import org.apache.phoenix.pherf.schema.SchemaReader;
 import org.apache.phoenix.pherf.util.PhoenixUtil;
 import org.junit.AfterClass;
 import org.junit.BeforeClass;
 
-import java.nio.file.Path;
-import java.util.List;
-import java.util.Properties;
-
-public class ResultBaseTestIT extends ParallelStatsDisabledIT {
+public class ResultBaseTestIT extends BaseHBaseManagedTimeIT {
     protected static final String matcherScenario = ".*scenario/.*test.*xml";
     protected static final String matcherSchema = ".*datamodel/.*test.*sql";
 
     protected static PhoenixUtil util = PhoenixUtil.create(true);
     protected static Properties properties;
```

### `phoenix-pherf/src/it/java/org/apache/phoenix/pherf/SchemaReaderIT.java`

```diff
--- from commit ad07077c7271 ---
diff --git a/phoenix-pherf/src/it/java/org/apache/phoenix/pherf/SchemaReaderIT.java b/phoenix-pherf/src/it/java/org/apache/phoenix/pherf/SchemaReaderIT.java
index c2bfdc1ef..a897a463e 100644
--- a/phoenix-pherf/src/it/java/org/apache/phoenix/pherf/SchemaReaderIT.java
+++ b/phoenix-pherf/src/it/java/org/apache/phoenix/pherf/SchemaReaderIT.java
@@ -28,21 +28,21 @@ import java.nio.file.Paths;
 import java.sql.Connection;
 import java.sql.SQLException;
 import java.util.ArrayList;
 import java.util.List;
 
-import org.apache.phoenix.end2end.ParallelStatsDisabledIT;
+import org.apache.phoenix.end2end.BaseHBaseManagedTimeIT;
 import org.apache.phoenix.pherf.configuration.Column;
 import org.apache.phoenix.pherf.configuration.DataModel;
 import org.apache.phoenix.pherf.configuration.Scenario;
 import org.apache.phoenix.pherf.configuration.XMLConfigParser;
 import org.apache.phoenix.pherf.schema.SchemaReader;
 import org.apache.phoenix.pherf.util.PhoenixUtil;
 import org.junit.Test;
 
 
-public class SchemaReaderIT extends ParallelStatsDisabledIT {
+public class SchemaReaderIT extends BaseHBaseManagedTimeIT {
     protected static PhoenixUtil util = PhoenixUtil.create(true);
 
     @Test 
     public void testSchemaReader() {
         // Test for the unit test version of the schema files.
```

### `phoenix-pig/src/it/java/org/apache/phoenix/pig/BasePigIT.java`

```diff
--- from commit ad07077c7271 ---
diff --git a/phoenix-pig/src/it/java/org/apache/phoenix/pig/BasePigIT.java b/phoenix-pig/src/it/java/org/apache/phoenix/pig/BasePigIT.java
index 2840a624c..94ccc253f 100644
--- a/phoenix-pig/src/it/java/org/apache/phoenix/pig/BasePigIT.java
+++ b/phoenix-pig/src/it/java/org/apache/phoenix/pig/BasePigIT.java
@@ -25,11 +25,11 @@ import java.sql.Connection;
 import java.sql.DriverManager;
 import java.util.Map;
 import java.util.Properties;
 
 import org.apache.hadoop.conf.Configuration;
-import org.apache.phoenix.end2end.ParallelStatsDisabledIT;
+import org.apache.phoenix.end2end.BaseHBaseManagedTimeIT;
 import org.apache.phoenix.end2end.Shadower;
 import org.apache.phoenix.query.QueryServices;
 import org.apache.phoenix.query.QueryServicesOptions;
 import org.apache.phoenix.util.PropertiesUtil;
 import org.apache.phoenix.util.ReadOnlyProps;
@@ -40,19 +40,19 @@ import org.junit.After;
 import org.junit.Before;
 import org.junit.BeforeClass;
 
 import com.google.common.collect.Maps;
 
-public class BasePigIT extends ParallelStatsDisabledIT {
+public class BasePigIT extends BaseHBaseManagedTimeIT {
     protected TupleFactory tupleFactory;
     protected String zkQuorum;
     protected Connection conn;
     protected Configuration conf;
     protected PigServer pigServer;
 
     @BeforeClass
-    @Shadower(classBeingShadowed = ParallelStatsDisabledIT.class)
+    @Shadower(classBeingShadowed = BaseHBaseManagedTimeIT.class)
     public static void doSetup() throws Exception {
         Map<String,String> props = Maps.newHashMapWithExpectedSize(3);
         props.put(QueryServices.EXTRA_JDBC_ARGUMENTS_ATTRIB, QueryServicesOptions.DEFAULT_EXTRA_JDBC_ARGUMENTS);
         // Must update config before starting server
         setUpTestDriver(new ReadOnlyProps(props.entrySet().iterator()));
```

### `phoenix-queryserver/src/it/java/org/apache/phoenix/end2end/QueryServerBasicsIT.java`

```diff
--- from commit ad07077c7271 ---
diff --git a/phoenix-queryserver/src/it/java/org/apache/phoenix/end2end/QueryServerBasicsIT.java b/phoenix-queryserver/src/it/java/org/apache/phoenix/end2end/QueryServerBasicsIT.java
index 967e320aa..ba49bab35 100644
--- a/phoenix-queryserver/src/it/java/org/apache/phoenix/end2end/QueryServerBasicsIT.java
+++ b/phoenix-queryserver/src/it/java/org/apache/phoenix/end2end/QueryServerBasicsIT.java
@@ -48,11 +48,11 @@ import org.junit.BeforeClass;
 import org.junit.Test;
 
 /**
  * Smoke test for query server.
  */
-public class QueryServerBasicsIT extends ParallelStatsDisabledIT {
+public class QueryServerBasicsIT extends BaseHBaseManagedTimeIT {
 
   private static final Log LOG = LogFactory.getLog(QueryServerBasicsIT.class);
 
   private static QueryServerThread AVATICA_SERVER;
   private static Configuration CONF;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
