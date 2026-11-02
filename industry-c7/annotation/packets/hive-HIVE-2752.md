# Annotation packet: HIVE-2752  (hive)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Index names are case sensitive

The following script:

DROP TABLE IF EXISTS TestTable;

CREATE TABLE TestTable (a INT);

DROP INDEX IF EXISTS TestTableA_IDX ON TestTable;

CREATE INDEX TestTableA_IDX ON TABLE TestTable (a) AS 'org.apache.hadoop.hive.ql.index.compact.CompactIndexHandler' WITH DEFERRED REBUILD;

ALTER INDEX TestTableA_IDX ON TestTable REBUILD;

results in the following exception:

MetaException(message:index testtablea_idx doesn't exist)
	at org.apache.hadoop.hive.metastore.ObjectStore.alterIndex(ObjectStore.java:1880)
	at org.apache.hadoop.hive.metastore.HiveMetaStore$HMSHandler$30.run(HiveMetaStore.java:1930)
	at org.apache.hadoop.hive.metastore.HiveMetaStore$HMSHandler$30.run(HiveMetaStore.java:1927)
	at org.apache.hadoop.hive.metastore.HiveMetaStore$HMSHandler.executeWithRetry(HiveMetaStore.java:356)
	at org.apache.hadoop.hive.metastore.HiveMetaStore$HMSHandler.alter_index(HiveMetaStore.java:1927)
	at org.apache.hadoop.hive.metastore.HiveMetaStoreClient.alter_index(HiveMetaStoreClient.java:868)
	at org.apache.hadoop.hive.ql.metadata.Hive.alterIndex(Hive.java:398)
	at org.apache.hadoop.hive.ql.exec.DDLTask.alterIndex(DDLTask.java:902)
	at org.apache.hadoop.hive.ql.exec.DDLTask.execute(DDLTask.java:236)
	at org.apache.hadoop.hive.ql.exec.Task.executeTask(Task.java:134)
	at org.apache.hadoop.hive.ql.exec.TaskRunner.runSequential(TaskRunner.java:57)
	at org.apache.hadoop.hive.ql.Driver.launchTask(Driver.java:1332)
	at org.apache.hadoop.hive.ql.Driver.execute(Driver.java:1123)
	at org.apache.hadoop.hive.ql.Driver.run(Driver.java:931)
	at org.apache.hadoop.hive.cli.CliDriver.processLocalCmd(CliDriver.java:255)
	at org.apache.hadoop.hive.cli.CliDriver.processCmd(CliDriver.java:212)
	at org.apache.hadoop.hive.cli.CliDriver.processLine(CliDriver.java:403)
	at org.apache.hadoop.hive.cli.CliDriver.processLine(CliDriver.java:338)
	at org.apache.hadoop.hive.cli.CliDriver.processReader(CliDriver.java:436)
	at org.apache.hadoop.hive.cli.CliDriver.processFile(CliDriver.java:446)
	at org.apache.hadoop.hive.cli.CliDriver.run(CliDriver.java:642)
	at org.apache.hadoop.hive.cli.CliDriver.main(CliDriver.java:554)
	at sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
	at sun.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:39)
	at sun.reflect.DelegatingMethodAccessorImpl.invoke(DelegatingMethodAccessorImpl.java:25)
	at java.lang.reflect.Method.invoke(Method.java:597)
	at org.apache.hadoop.util.RunJar.main(RunJar.java:156)

When you execute: "SHOW INDEXES ON TestTable;", you get:

TestTableA_IDX      	testtable           	a                   	default__testtable_testtablea_idx__	compact

so it looks like things don't get lower cased when they go into the metastore, but they do when the rebuild op is trying to execute.
```

## Fix commit message(s)

`839f9cd1c1fb`

```
HIVE-2752 Index names are case sensitive (Navis Ryu via Harish Butani)

git-svn-id: https://svn.apache.org/repos/asf/hive/trunk@1582354 13f79535-47bb-0310-9956-ffa450edef68
```

## Files the fix changed

Snapshot holds 2,528 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `metastore/src/java/org/apache/hadoop/hive/metastore/ObjectStore.java`

## The fix diff

### `metastore/src/java/org/apache/hadoop/hive/metastore/ObjectStore.java`

```diff
diff --git a/metastore/src/java/org/apache/hadoop/hive/metastore/ObjectStore.java b/metastore/src/java/org/apache/hadoop/hive/metastore/ObjectStore.java
index 7ae41e557b..6a0eabe25d 100644
--- a/metastore/src/java/org/apache/hadoop/hive/metastore/ObjectStore.java
+++ b/metastore/src/java/org/apache/hadoop/hive/metastore/ObjectStore.java
@@ -2842,11 +2842,11 @@ public class ObjectStore implements RawStore, Configurable {
     if (indexTable == null) {
       throw new InvalidObjectException(
           "Underlying index table does not exist for the given index.");
     }
 
-    return new MIndex(index.getIndexName(), origTable, index.getCreateTime(),
+    return new MIndex(index.getIndexName().toLowerCase(), origTable, index.getCreateTime(),
         index.getLastAccessTime(), index.getParameters(), indexTable, msd,
         index.getIndexHandlerClass(), index.isDeferredRebuild());
   }
 
   @Override
@@ -2883,11 +2883,11 @@ public class ObjectStore implements RawStore, Configurable {
 
       Query query = pm.newQuery(MIndex.class,
         "origTable.tableName == t1 && origTable.database.name == t2 && indexName == t3");
       query.declareParameters("java.lang.String t1, java.lang.String t2, java.lang.String t3");
       query.setUnique(true);
-      midx = (MIndex) query.execute(originalTblName, dbName, indexName);
+      midx = (MIndex) query.execute(originalTblName, dbName, indexName.toLowerCase());
       pm.retrieve(midx);
       commited = commitTransaction();
     } finally {
       if (!commited) {
         rollbackTransaction();
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
