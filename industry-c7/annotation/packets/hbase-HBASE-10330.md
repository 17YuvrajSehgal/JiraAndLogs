# Annotation packet: HBASE-10330  (hbase)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
TableInputFormat/TableRecordReaderImpl leaks HTable

As far as I can tell, TableInputFormat creates an instance of HTable which is used by TableRecordReaderImpl. However TableRecordReaderImpl.close() only closes the scanner, not the table. In turn the HTable's HConnection's reference count is never decreased which leads to leaking HConnections.

TableOutputFormat might have a similar bug.
```

## Fix commit message(s)

`e04009c9894b`

```
HBASE-10330 TableInputFormat/TableRecordReaderImpl leaks HTable
```

## Files the fix changed

Snapshot holds 1,337 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `hbase-server/src/main/java/org/apache/hadoop/hbase/mapred/TableRecordReaderImpl.java`
- `hbase-server/src/main/java/org/apache/hadoop/hbase/mapreduce/TableRecordReaderImpl.java`

## The fix diff

### `hbase-server/src/main/java/org/apache/hadoop/hbase/mapred/TableRecordReaderImpl.java`

```diff
diff --git a/hbase-server/src/main/java/org/apache/hadoop/hbase/mapred/TableRecordReaderImpl.java b/hbase-server/src/main/java/org/apache/hadoop/hbase/mapred/TableRecordReaderImpl.java
index 08c1873dba..f4043f4836 100644
--- a/hbase-server/src/main/java/org/apache/hadoop/hbase/mapred/TableRecordReaderImpl.java
+++ b/hbase-server/src/main/java/org/apache/hadoop/hbase/mapred/TableRecordReaderImpl.java
@@ -153,10 +153,15 @@ public class TableRecordReaderImpl {
     this.trrRowFilter = rowFilter;
   }
 
   public void close() {
     this.scanner.close();
+    try {
+      this.htable.close();
+    } catch (IOException ioe) {
+      LOG.warn("Error closing table", ioe);
+    }
   }
 
   /**
    * @return ImmutableBytesWritable
    *
```

### `hbase-server/src/main/java/org/apache/hadoop/hbase/mapreduce/TableRecordReaderImpl.java`

```diff
diff --git a/hbase-server/src/main/java/org/apache/hadoop/hbase/mapreduce/TableRecordReaderImpl.java b/hbase-server/src/main/java/org/apache/hadoop/hbase/mapreduce/TableRecordReaderImpl.java
index a95055dbbe..7eb7871d3a 100644
--- a/hbase-server/src/main/java/org/apache/hadoop/hbase/mapreduce/TableRecordReaderImpl.java
+++ b/hbase-server/src/main/java/org/apache/hadoop/hbase/mapreduce/TableRecordReaderImpl.java
@@ -157,10 +157,15 @@ public class TableRecordReaderImpl {
    *
    *
    */
   public void close() {
     this.scanner.close();
+    try {
+      this.htable.close();
+    } catch (IOException ioe) {
+      LOG.warn("Error closing table", ioe);
+    }
   }
 
   /**
    * Returns the current key.
    *
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
