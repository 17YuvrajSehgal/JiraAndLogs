# Annotation packet: HDFS-10457  (hadoop)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
DataNode should not auto-format block pool directory if VERSION is missing

HDFS-10360 prevents DN to auto-formats a volume directory if the current/VERSION is missing. However, if instead, the current/VERSION in a block pool directory is missing, DN still auto-formats the directory.

Filing this jira to fix the bug.
```

## Fix commit message(s)

`cc48251bfdef`

```
HDFS-10457. DataNode should not auto-format block pool directory if VERSION is missing. (Wei-Chiu Chuang via lei)
```

## Files the fix changed

Snapshot holds 4,909 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java`

## The fix diff

### `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java`

```diff
diff --git a/hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java b/hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java
index 90a46698a86..fd90ae921aa 100644
--- a/hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java
+++ b/hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java
@@ -149,11 +149,11 @@ public class BlockPoolSliceStorage extends Storage {
       File dataDir, StartupOption startOpt,
       List<Callable<StorageDirectory>> callables, Configuration conf)
           throws IOException {
     StorageDirectory sd = new StorageDirectory(dataDir, null, true);
     try {
-      StorageState curState = sd.analyzeStorage(startOpt, this);
+      StorageState curState = sd.analyzeStorage(startOpt, this, true);
       // sd is locked but not opened
       switch (curState) {
       case NORMAL:
         break;
       case NON_EXISTENT:
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
