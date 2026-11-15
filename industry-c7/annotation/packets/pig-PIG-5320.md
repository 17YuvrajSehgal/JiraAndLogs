# Annotation packet: PIG-5320  (pig)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
TestCubeOperator#testRollupBasic is flaky on Spark 2.2

TestCubeOperator#testRollupBasic occasionally fails with
{code}
org.apache.pig.impl.logicalLayer.FrontendException: ERROR 1002: Unable to store alias c
	at org.apache.pig.PigServer$Graph.registerQuery(PigServer.java:1779)
	at org.apache.pig.PigServer.registerQuery(PigServer.java:708)
	at org.apache.pig.tools.grunt.GruntParser.processPig(GruntParser.java:1110)
	at org.apache.pig.tools.pigscript.parser.PigScriptParser.parse(PigScriptParser.java:512)
	at org.apache.pig.tools.grunt.GruntParser.parseStopOnError(GruntParser.java:230)
	at org.apache.pig.PigServer.registerScript(PigServer.java:781)
	at org.apache.pig.PigServer.registerScript(PigServer.java:858)
	at org.apache.pig.PigServer.registerScript(PigServer.java:821)
	at org.apache.pig.test.Util.registerMultiLineQuery(Util.java:972)
	at org.apache.pig.test.TestCubeOperator.testRollupBasic(TestCubeOperator.java:124)
Caused by: org.apache.pig.impl.plan.VisitorException: ERROR 0: fail to get the rdds of this spark operator: 
	at org.apache.pig.backend.hadoop.executionengine.spark.JobGraphBuilder.visitSparkOp(JobGraphBuilder.java:115)
	at org.apache.pig.backend.hadoop.executionengine.spark.plan.SparkOperator.visit(SparkOperator.java:140)
	at org.apache.pig.backend.hadoop.executionengine.spark.plan.SparkOperator.visit(SparkOperator.java:37)
	at org.apache.pig.impl.plan.DependencyOrderWalker.walk(DependencyOrderWalker.java:87)
	at org.apache.pig.impl.plan.PlanVisitor.visit(PlanVisitor.java:46)
	at org.apache.pig.backend.hadoop.executionengine.spark.SparkLauncher.launchPig(SparkLauncher.java:237)
	at org.apache.pig.backend.hadoop.executionengine.HExecutionEngine.launchPig(HExecutionEngine.java:293)
	at org.apache.pig.PigServer.launchPlan(PigServer.java:1475)
	at org.apache.pig.PigServer.executeCompiledLogicalPlan(PigServer.java:1460)
	at org.apache.pig.PigServer.execute(PigServer.java:1449)
	at org.apache.pig.PigServer.access$500(PigServer.java:119)
	at org.apache.pig.PigServer$Graph.registerQuery(PigServer.java:1774)
Caused by: java.lang.RuntimeException: Unexpected job execution status RUNNING
	at org.apache.pig.tools.pigstats.spark.SparkStatsUtil.isJobSuccess(SparkStatsUtil.java:138)
	at org.apache.pig.tools.pigstats.spark.SparkPigStats.addJobStats(SparkPigStats.java:75)
	at org.apache.pig.tools.pigstats.spark.SparkStatsUtil.waitForJobAddStats(SparkStatsUtil.java:59)
	at org.apache.pig.backend.hadoop.executionengine.spark.JobGraphBuilder.sparkOperToRDD(JobGraphBuilder.java:225)
	at org.apache.pig.backend.hadoop.executionengine.spark.JobGraphBuilder.visitSparkOp(JobGraphBuilder.java:112)
{code}

I think the problem is that in JobStatisticCollector#waitForJobToEnd {{sparkListener.wait()}} is not inside a loop, like suggested in wait's javadoc:
{code}
     * As in the one argument version, interrupts and spurious wakeups are
     * possible, and this method should always be used in a loop:
{code}

Thus due to a spurious wakeup, the wait might pass without a notify getting called.
```

## Fix commit message(s)

`235e7c5294f5`

```
PIG-5320: TestCubeOperator#testRollupBasic is flaky on Spark 2.2 (nkollar via szita)

git-svn-id: https://svn.apache.org/repos/asf/pig/trunk@1821165 13f79535-47bb-0310-9956-ffa450edef68
```

## Files the fix changed

Snapshot holds 1,260 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/org/apache/pig/backend/hadoop/executionengine/spark/JobStatisticCollector.java`

## The fix diff

### `src/org/apache/pig/backend/hadoop/executionengine/spark/JobStatisticCollector.java`

```diff
diff --git a/src/org/apache/pig/backend/hadoop/executionengine/spark/JobStatisticCollector.java b/src/org/apache/pig/backend/hadoop/executionengine/spark/JobStatisticCollector.java
index 8e16eac8..abbd76e3 100644
--- a/src/org/apache/pig/backend/hadoop/executionengine/spark/JobStatisticCollector.java
+++ b/src/org/apache/pig/backend/hadoop/executionengine/spark/JobStatisticCollector.java
@@ -50,19 +50,17 @@ public class JobStatisticCollector {
         synchronized (sparkListener) {
             return allJobStatistics.get(jobId);
         }
     }
 
-    public boolean waitForJobToEnd(int jobId) throws InterruptedException {
+    public void waitForJobToEnd(int jobId) throws InterruptedException {
         synchronized (sparkListener) {
-            if (finishedJobIds.contains(jobId)) {
-                finishedJobIds.remove(jobId);
-                return true;
+            while (!finishedJobIds.contains(jobId)) {
+                sparkListener.wait();
             }
 
-            sparkListener.wait();
-            return false;
+            finishedJobIds.remove(jobId);
         }
     }
 
     public void cleanup(int jobId) {
         synchronized (sparkListener) {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
