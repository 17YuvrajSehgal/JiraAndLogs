# Annotation packet: IGNITE-5204  (ignite)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
The Unicode character in the value of a field which are included in an un-unique index will cause "stack overhead" exception

When put  "草DX009090" as the value of BillId, which is a field of entity Bill. If I define a index includes the BillId, and execute the query like "select * from Bill where BillId=’草DX009090‘ in the H2 debug console, there throws an exception by the H2 with a code 5000. 
another scenario is, I have two entities, "Bill" and "Detail", both have field "BillId". If either of them have value like "草DX009090" and execute the query like "select bill.* from bill left join detail on bill.billid=detail.billid", the whole ignite cache node will halt ( suppose there should be an stack overhead exception, dead loop).
======================
I think the issue should relate to hash computing on the unicode character.
```

## Fix commit message(s)

`0d6fb1ad73e8`

```
IGNITE-5204: Fixed NPE on certain data with index inlining. This closes #2115.
```

`99713feea764`

```
IGNITE-5204: SQL: fixed incorrect partition calculation in case of unicast optimization, when WHERE clause argument type was different from key or affinity key type. This close #2107.
```

## Files the fix changed

Snapshot holds 3,954 non-test source files. The fix changed 8 file(s); 6 of them are non-test source files (listed below as gold).

- `modules/indexing/src/main/java/org/apache/ignite/internal/processors/cache/query/CacheQueryPartitionInfo.java`
- `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/DmlStatementsProcessor.java`
- `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/H2Utils.java`
- `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/IgniteH2Indexing.java`
- `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/database/InlineIndexHelper.java`
- `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/sql/GridSqlQuerySplitter.java`

## The fix diff

### `modules/indexing/src/main/java/org/apache/ignite/internal/processors/cache/query/CacheQueryPartitionInfo.java`

```diff
--- from commit 99713feea764 ---
diff --git a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/cache/query/CacheQueryPartitionInfo.java b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/cache/query/CacheQueryPartitionInfo.java
index 1329d5c397..42bf0707ca 100644
--- a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/cache/query/CacheQueryPartitionInfo.java
+++ b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/cache/query/CacheQueryPartitionInfo.java
@@ -37,26 +37,39 @@ import org.apache.ignite.internal.util.typedef.internal.S;
  * The given class holds the required info, so that effective partition
  * can be calculated during query parameter binding.
  */
 public class CacheQueryPartitionInfo {
     /** */
-    private int partId;
+    private final int partId;
 
     /** */
-    private String cacheName;
+    private final String cacheName;
 
     /** */
-    private int paramIdx;
+    private final String tableName;
+
+    /** */
+    private final int dataType;
+
+    /** */
+    private final int paramIdx;
 
     /**
      * @param partId Partition id, or -1 if parameter binding required.
      * @param cacheName Cache name required for partition calculation.
+     * @param tableName Table name required for proper type conversion.
+     * @param dataType Required data type id for the query parameter.
      * @param paramIdx Query parameter index required for partition calculation.
      */
-    public CacheQueryPartitionInfo(int partId, String cacheName, int paramIdx) {
+    public CacheQueryPartitionInfo(int partId, String cacheName, String tableName, int dataType, int paramIdx) {
+        // In case partition is not known, both cacheName and tableName must be provided.
+        assert (partId >= 0) ^ ((cacheName != null) && (tableName != null));
+
         this.partId = partId;
         this.cacheName = cacheName;
+        this.tableName = tableName;
+        this.dataType = dataType;
         this.paramIdx = paramIdx;
     }
 
     /**
      * @return Partition id, or -1 if parameter binding is required to calculate partition.
@@ -70,20 +83,36 @@ public class CacheQueryPartitionInfo {
      */
     public String cacheName() {
         return cacheName;
     }
 
+    /**
+     * @return Table name.
+     */
+    public String tableName() {
+        return tableName;
+    }
+
+    /**
+     * @return Required data type for the query parameter.
+     */
+    public int dataType() {
+        return dataType;
+    }
+
     /**
      * @return Query parameter index required for partition calculation.
      */
     public int paramIdx() {
         return paramIdx;
     }
 
     /** {@inheritDoc} */
     @Override public int hashCode() {
-        return partId ^ paramIdx ^ (cacheName == null ? 0 : cacheName.hashCode());
+        return partId ^ dataType ^ paramIdx ^
+            (cacheName == null ? 0 : cacheName.hashCode()) ^
+            (tableName == null ? 0 : tableName.hashCode());
     }
 
     /** {@inheritDoc} */
     @Override public boolean equals(Object obj) {
         if (this == obj)
@@ -95,14 +124,17 @@ public class CacheQueryPartitionInfo {
         CacheQueryPartitionInfo other = (CacheQueryPartitionInfo)obj;
 
         if (partId >= 0)
             return partId == other.partId;
 
-        if (other.cacheName == null)
+        if (other.cacheName == null || other.tableName == null)
             return false;
 
-        return other.cacheName.equals(cacheName) && other.paramIdx == paramIdx;
+        return other.cacheName.equals(cacheName) &&
+            other.tableName.equals(tableName) &&
+            other.dataType == dataType &&
+            other.paramIdx == paramIdx;
     }
 
     /** {@inheritDoc} */
     @Override public String toString() {
         return S.toString(CacheQueryPartitionInfo.class, this);
```

### `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/DmlStatementsProcessor.java`

```diff
--- from commit 99713feea764 ---
diff --git a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/DmlStatementsProcessor.java b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/DmlStatementsProcessor.java
index 0c1dbf983d..4f7c288f86 100644
--- a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/DmlStatementsProcessor.java
+++ b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/DmlStatementsProcessor.java
@@ -746,18 +746,11 @@ public class DmlStatementsProcessor {
             System.arraycopy(curr, 0, newArr, 0, curr.length);
 
             return newArr;
         }
 
-        int objType = DataType.getTypeFromClass(val.getClass());
-
-        if (objType == type)
-            return val;
-
-        Value h2Val = desc.wrap(val, objType);
-
-        return h2Val.convertTo(type).getObject();
+        return H2Utils.convert(val, desc, type);
     }
 
     /**
      * Process errors of entry processor - split the keys into duplicated/concurrently modified and those whose
      * processing yielded an exception.
```

### `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/H2Utils.java`

```diff
--- from commit 99713feea764 ---
diff --git a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/H2Utils.java b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/H2Utils.java
index ee88acf6a9..157e1ba7ac 100644
--- a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/H2Utils.java
+++ b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/H2Utils.java
@@ -15,10 +15,11 @@
  * limitations under the License.
  */
 
 package org.apache.ignite.internal.processors.query.h2;
 
+import org.apache.ignite.IgniteCheckedException;
 import org.apache.ignite.IgniteException;
 import org.apache.ignite.internal.processors.query.GridQueryFieldMetadata;
 import org.apache.ignite.internal.processors.query.h2.opt.GridH2IndexBase;
 import org.apache.ignite.internal.processors.query.h2.opt.GridH2RowDescriptor;
 import org.apache.ignite.internal.processors.query.h2.opt.GridH2Table;
@@ -27,10 +28,12 @@ import org.apache.ignite.internal.util.typedef.F;
 import org.apache.ignite.internal.util.typedef.internal.SB;
 import org.h2.engine.Session;
 import org.h2.jdbc.JdbcConnection;
 import org.h2.result.SortOrder;
 import org.h2.table.IndexColumn;
+import org.h2.value.DataType;
+import org.h2.value.Value;
 
 import java.lang.reflect.Constructor;
 import java.sql.Connection;
 import java.sql.ResultSetMetaData;
 import java.sql.SQLException;
@@ -233,10 +236,34 @@ public class H2Utils {
 
         s.setForceJoinOrder(enforceJoinOrder);
         s.setJoinBatchEnabled(distributedJoins);
     }
 
+    /**
+     * Convert value to column's expected type by means of H2.
+     *
+     * @param val Source value.
+     * @param desc Row descriptor.
+     * @param type Expected column type to convert to.
+     * @return Converted object.
+     * @throws IgniteCheckedException if failed.
+     */
+    public static Object convert(Object val, GridH2RowDescriptor desc, int type)
+        throws IgniteCheckedException {
+        if (val == null)
+            return null;
+
+        int objType = DataType.getTypeFromClass(val.getClass());
+
+        if (objType == type)
+            return val;
+
+        Value h2Val = desc.wrap(val, objType);
+
+        return h2Val.convertTo(type).getObject();
+    }
+
     /**
      * Private constructor.
      */
     private H2Utils() {
         // No-op.
```

### `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/IgniteH2Indexing.java`

```diff
--- from commit 99713feea764 ---
diff --git a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/IgniteH2Indexing.java b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/IgniteH2Indexing.java
index 255c5f1e10..40eae17657 100644
--- a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/IgniteH2Indexing.java
+++ b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/IgniteH2Indexing.java
@@ -2263,21 +2263,23 @@ public class IgniteH2Indexing implements GridQueryIndexing {
     }
 
     /**
      * Bind query parameters and calculate partitions derived from the query.
      *
+     * @param partInfoList Collection of query derived partition info.
+     * @param params Query parameters.
      * @return Partitions.
+     * @throws IgniteCheckedException, If fails.
      */
     private int[] calculateQueryPartitions(CacheQueryPartitionInfo[] partInfoList, Object[] params)
         throws IgniteCheckedException {
 
         ArrayList<Integer> list = new ArrayList<>(partInfoList.length);
 
         for (CacheQueryPartitionInfo partInfo: partInfoList) {
-            int partId = partInfo.partition() < 0 ?
-                kernalContext().affinity().partition(partInfo.cacheName(), params[partInfo.paramIdx()]) :
-                partInfo.partition();
+            int partId = (partInfo.partition() >= 0) ? partInfo.partition() :
+                bindPartitionInfoParameter(partInfo, params);
 
             int i = 0;
 
             while (i < list.size() && list.get(i) < partId)
                 i++;
@@ -2296,10 +2298,32 @@ public class IgniteH2Indexing implements GridQueryIndexing {
             result[i] = list.get(i);
 
         return result;
     }
 
+    /**
+     * Bind query parameter to partition info and calculate partition.
+     *
+     * @param partInfo Partition Info.
+     * @param params Query parameters.
+     * @return Partition.
+     * @throws IgniteCheckedException, If fails.
+     */
+    private int bindPartitionInfoParameter(CacheQueryPartitionInfo partInfo, Object[] params)
+        throws IgniteCheckedException {
+        assert partInfo != null;
+        assert partInfo.partition() < 0;
+
+        GridH2RowDescriptor desc = dataTable(partInfo.cacheName(),
+                partInfo.tableName()).rowDescriptor();
+
+        Object param = H2Utils.convert(params[partInfo.paramIdx()],
+                desc, partInfo.dataType());
+
+        return kernalContext().affinity().partition(partInfo.cacheName(), param);
+    }
+
     /** {@inheritDoc} */
     @Override public Collection<GridRunningQueryInfo> runningQueries(long duration) {
         Collection<GridRunningQueryInfo> res = new ArrayList<>();
 
         res.addAll(runs.values());
```

### `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/database/InlineIndexHelper.java`

```diff
--- from commit 0d6fb1ad73e8 ---
diff --git a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/database/InlineIndexHelper.java b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/database/InlineIndexHelper.java
index 1fd45f3ccf..19cf857fec 100644
--- a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/database/InlineIndexHelper.java
+++ b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/database/InlineIndexHelper.java
@@ -439,11 +439,11 @@ public class InlineIndexHelper {
                 byte[] s = val.getString().getBytes(CHARSET);
                 if (s.length + 3 <= maxSize)
                     size = (short)s.length;
                 else {
                     s = trimUTF8(s, maxSize - 3);
-                    size = (short)(s.length | 0x8000);
+                    size = (short)(s == null ? 0 : s.length | 0x8000);
                 }
 
                 if (s == null) {
                     // Can't fit anything to
                     PageUtils.putByte(pageAddr, off, (byte)Value.UNKNOWN);
```

### `modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/sql/GridSqlQuerySplitter.java`

```diff
--- from commit 99713feea764 ---
diff --git a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/sql/GridSqlQuerySplitter.java b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/sql/GridSqlQuerySplitter.java
index aebf59650b..1578f9fb78 100644
--- a/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/sql/GridSqlQuerySplitter.java
+++ b/modules/indexing/src/main/java/org/apache/ignite/internal/processors/query/h2/sql/GridSqlQuerySplitter.java
@@ -2316,18 +2316,19 @@ public class GridSqlQuerySplitter {
 
         if (right instanceof GridSqlConst) {
             GridSqlConst constant = (GridSqlConst)right;
 
             return new CacheQueryPartitionInfo(ctx.affinity().partition(tbl.cacheName(),
-                constant.value().getObject()), null, -1);
+                constant.value().getObject()), null, null, -1, -1);
         }
 
         assert right instanceof GridSqlParameter;
 
         GridSqlParameter param = (GridSqlParameter) right;
 
-        return new CacheQueryPartitionInfo(-1, tbl.cacheName(), param.index());
+        return new CacheQueryPartitionInfo(-1, tbl.cacheName(), tbl.getName(),
+            column.column().getType(), param.index());
     }
 
     /**
      * Merges two partition info arrays, removing duplicates
      *
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
