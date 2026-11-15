# Annotation packet: FLINK-11136  (flink)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Fix the logical of merge for DISTINCT aggregates

The logic of merge for DISTINCT aggregates has bug. For the following query:
{code:java}
SELECT
  c,
  COUNT(DISTINCT b),
  SUM(DISTINCT b),
  SESSION_END(rowtime, INTERVAL '0.005' SECOND)
FROM MyTable
GROUP BY SESSION(rowtime, INTERVAL '0.005' SECOND), c{code}
the following exception will be thrown:
{code:java}
Caused by: java.lang.ClassCastException: org.apache.flink.types.Row cannot be cast to java.lang.Integer
at scala.runtime.BoxesRunTime.unboxToInt(BoxesRunTime.java:101)
at scala.math.Numeric$IntIsIntegral$.plus(Numeric.scala:58)
at org.apache.flink.table.functions.aggfunctions.SumAggFunction.accumulate(SumAggFunction.scala:50)
at GroupingWindowAggregateHelper$18.mergeAccumulatorsPair(Unknown Source)
at org.apache.flink.table.runtime.aggregate.AggregateAggFunction.merge(AggregateAggFunction.scala:66)
at org.apache.flink.table.runtime.aggregate.AggregateAggFunction.merge(AggregateAggFunction.scala:33)
at org.apache.flink.runtime.state.heap.HeapAggregatingState.mergeState(HeapAggregatingState.java:117)
at org.apache.flink.runtime.state.heap.AbstractHeapMergingState$MergeTransformation.apply(AbstractHeapMergingState.java:102)
at org.apache.flink.runtime.state.heap.CopyOnWriteStateTable.transform(CopyOnWriteStateTable.java:463)
at org.apache.flink.runtime.state.heap.CopyOnWriteStateTable.transform(CopyOnWriteStateTable.java:341)
at org.apache.flink.runtime.state.heap.AbstractHeapMergingState.mergeNamespaces(AbstractHeapMergingState.java:91)
at org.apache.flink.streaming.runtime.operators.windowing.WindowOperator$2.merge(WindowOperator.java:341)
at org.apache.flink.streaming.runtime.operators.windowing.WindowOperator$2.merge(WindowOperator.java:311)
at org.apache.flink.streaming.runtime.operators.windowing.MergingWindowSet.addWindow(MergingWindowSet.java:212)
at org.apache.flink.streaming.runtime.operators.windowing.WindowOperator.processElement(WindowOperator.java:311)
at org.apache.flink.streaming.runtime.io.StreamInputProcessor.processInput(StreamInputProcessor.java:202)
at org.apache.flink.streaming.runtime.tasks.OneInputStreamTask.run(OneInputStreamTask.java:105)
at org.apache.flink.streaming.runtime.tasks.StreamTask.invoke(StreamTask.java:300)
at org.apache.flink.runtime.taskmanager.Task.run(Task.java:704)
at java.lang.Thread.run(Thread.java:745)
{code}
```

## Fix commit message(s)

`ed0aefa6775f`

```
[FLINK-11136] [table] Fix the merge logic of DISTINCT aggregates.

This closes #7284.
```

## Files the fix changed

Snapshot holds 4,662 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `flink-libraries/flink-table/src/main/scala/org/apache/flink/table/codegen/AggregationCodeGenerator.scala`

## The fix diff

### `flink-libraries/flink-table/src/main/scala/org/apache/flink/table/codegen/AggregationCodeGenerator.scala`

```diff
diff --git a/flink-libraries/flink-table/src/main/scala/org/apache/flink/table/codegen/AggregationCodeGenerator.scala b/flink-libraries/flink-table/src/main/scala/org/apache/flink/table/codegen/AggregationCodeGenerator.scala
index 566e3d7cbc5..57cc815fee0 100644
--- a/flink-libraries/flink-table/src/main/scala/org/apache/flink/table/codegen/AggregationCodeGenerator.scala
+++ b/flink-libraries/flink-table/src/main/scala/org/apache/flink/table/codegen/AggregationCodeGenerator.scala
@@ -140,10 +140,25 @@ class AggregationCodeGenerator(
       }
 
       fields.mkString(", ")
     }
 
+    val parametersCodeForDistinctMerge = aggFields.map { inFields =>
+      val fields = inFields.filter(_ > -1).zipWithIndex.map { case (f, i) =>
+        // index to constant
+        if (f >= physicalInputTypes.length) {
+          constantFields(f - physicalInputTypes.length)
+        }
+        // index to input field
+        else {
+          s"(${CodeGenUtils.boxedTypeTermForTypeInfo(physicalInputTypes(f))}) k.getField($i)"
+        }
+      }
+
+      fields.mkString(", ")
+    }
+
     // get method signatures
     val classes = UserDefinedFunctionUtils.typeInfoToClass(physicalInputTypes)
     val constantClasses = UserDefinedFunctionUtils.typeInfoToClass(constantTypes)
     val methodSignaturesList = aggFields.map { inFields =>
       inFields.filter(_ > -1).map { f =>
@@ -641,11 +656,11 @@ class AggregationCodeGenerator(
                |      java.util.Map.Entry entry = (java.util.Map.Entry) mergeIt$i.next();
                |      ${classOf[Row].getCanonicalName} k =
                |          (${classOf[Row].getCanonicalName}) entry.getKey();
                |      Long v = (Long) entry.getValue();
                |      if (aDistinctAcc$i.add(k, v)) {
-               |        ${aggs(i)}.accumulate(aAcc$i, k);
+               |        ${aggs(i)}.accumulate(aAcc$i, ${parametersCodeForDistinctMerge(i)});
                |      }
                |    }
                |    a.setField($i, aDistinctAcc$i);
                """.stripMargin
           } else {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
