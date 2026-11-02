# Annotation packet: PHOENIX-1551  (phoenix)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Upgrading from Phoenix 4.0.x to 4.2.2 and throw can't find SYSTEM.STATS

I download phoenix-4.2.2-bin.tar.gz and put phoenix-4.2.2-server.jar into the HBase lib directory and remove any phoenix-4.0.jar,restart hbase
When I used bin/sqlline.py to connection phoenix throw

Error: org.apache.hadoop.hbase.DoNotRetryIOException: SYSTEM.CATALOG: org.apache.hadoop.hbase.TableNotFoundException: SYSTEM.STATS
	at org.apache.phoenix.util.ServerUtil.createIOException(ServerUtil.java:84)
	at org.apache.phoenix.coprocessor.MetaDataEndpointImpl.createTable(MetaDataEndpointImpl.java:794)
	at org.apache.phoenix.coprocessor.generated.MetaDataProtos$MetaDataService.callMethod(MetaDataProtos.java:7763)
	at org.apache.hadoop.hbase.regionserver.HRegion.execService(HRegion.java:5296)
	at org.apache.hadoop.hbase.regionserver.HRegionServer.execService(HRegionServer.java:3205)
	at org.apache.hadoop.hbase.protobuf.generated.ClientProtos$ClientService$2.callBlockingMethod(ClientProtos.java:26933)
	at org.apache.hadoop.hbase.ipc.RpcServer.call(RpcServer.java:2175)
	at org.apache.hadoop.hbase.ipc.RpcServer$Handler.run(RpcServer.java:1879)
Caused by: java.lang.RuntimeException: org.apache.hadoop.hbase.TableNotFoundException: SYSTEM.STATS
	at org.apache.hadoop.hbase.client.HTableFactory.createHTableInterface(HTableFactory.java:41)
	at org.apache.hadoop.hbase.client.HTablePool.createHTable(HTablePool.java:271)
	at org.apache.hadoop.hbase.client.HTablePool.findOrCreateTable(HTablePool.java:201)
	at org.apache.hadoop.hbase.client.HTablePool.getTable(HTablePool.java:180)
	at org.apache.hadoop.hbase.client.HTablePool.getTable(HTablePool.java:219)
	at org.apache.phoenix.util.ServerUtil.getTableFromSingletonPool(ServerUtil.java:151)
	at org.apache.phoenix.util.ServerUtil.getHTableForCoprocessorScan(ServerUtil.java:165)
	at org.apache.phoenix.coprocessor.MetaDataEndpointImpl.getTable(MetaDataEndpointImpl.java:609)
	at org.apache.phoenix.coprocessor.MetaDataEndpointImpl.buildTable(MetaDataEndpointImpl.java:359)
	at org.apache.phoenix.coprocessor.MetaDataEndpointImpl.loadTable(MetaDataEndpointImpl.java:665)
	at org.apache.phoenix.coprocessor.MetaDataEndpointImpl.createTable(MetaDataEndpointImpl.java:743)
	... 6 more
Caused by: org.apache.hadoop.hbase.TableNotFoundException: SYSTEM.STATS
	at org.apache.hadoop.hbase.client.HConnectionManager$HConnectionImplementation.locateRegionInMeta(HConnectionManager.java:1181)
	at org.apache.hadoop.hbase.client.HConnectionManager$HConnectionImplementation.locateRegion(HConnectionManager.java:1054)
	at org.apache.hadoop.hbase.client.HConnectionManager$HConnectionImplementation.locateRegion(HConnectionManager.java:1011)
	at org.apache.hadoop.hbase.client.HTable.finishSetup(HTable.java:326)
	at org.apache.hadoop.hbase.client.HTable.<init>(HTable.java:192)
	at org.apache.hadoop.hbase.client.HTable.<init>(HTable.java:165)
	at org.apache.hadoop.hbase.client.HTableFactory.createHTableInterface(HTableFactory.java:39)
	... 16 more (state=08000,code=101)
```

## Fix commit message(s)

`ddcb591f3ed3`

```
PHOENIX-1551 Upgrading from Phoenix 4.0.x to 4.2.2 and throw can't find SYSTEM.STATS
```

## Files the fix changed

Snapshot holds 914 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `phoenix-core/src/main/java/org/apache/phoenix/util/ServerUtil.java`

## The fix diff

### `phoenix-core/src/main/java/org/apache/phoenix/util/ServerUtil.java`

```diff
diff --git a/phoenix-core/src/main/java/org/apache/phoenix/util/ServerUtil.java b/phoenix-core/src/main/java/org/apache/phoenix/util/ServerUtil.java
index 7205faab9..0998e72d8 100644
--- a/phoenix-core/src/main/java/org/apache/phoenix/util/ServerUtil.java
+++ b/phoenix-core/src/main/java/org/apache/phoenix/util/ServerUtil.java
@@ -140,17 +140,26 @@ public class ServerUtil {
     
     /*
      * This code works around HBASE-11837 which causes HTableInterfaces retrieved from
      * RegionCoprocessorEnvironment to not read local data.
      */
-    private static HTableInterface getTableFromSingletonPool(RegionCoprocessorEnvironment env, byte[] tableName) {
+    private static HTableInterface getTableFromSingletonPool(RegionCoprocessorEnvironment env, byte[] tableName) throws IOException {
         // It's ok to not ever do a pool.close() as we're storing a single
         // table only. The HTablePool holds no other resources that this table
         // which will be closed itself when it's no longer needed.
         @SuppressWarnings("resource")
         HTablePool pool = new HTablePool(env.getConfiguration(),1);
-        return pool.getTable(tableName);
+        try {
+            return pool.getTable(tableName);
+        } catch (RuntimeException t) {
+            // handle cases that an IOE is wrapped inside a RuntimeException like HTableInterface#createHTableInterface
+            if(t.getCause() instanceof IOException) {
+                throw (IOException)t.getCause();
+            } else {
+                throw t;
+            }
+        }
     }
     
     public static HTableInterface getHTableForCoprocessorScan (RegionCoprocessorEnvironment env, HTableInterface writerTable) throws IOException {
         if (coprocessorScanWorks(env)) {
             return writerTable;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
