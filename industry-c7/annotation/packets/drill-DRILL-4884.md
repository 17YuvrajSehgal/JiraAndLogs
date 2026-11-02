# Annotation packet: DRILL-4884  (drill)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Fix IOB exception in limit n query when n is beyond 65535.

Drill produces IOB while using a non batched scanner and limiting SQL by 65536.

SQL:
{noformat}
select id from xx limit 1 offset 65535
{noformat}

Result:
{noformat}
	at org.apache.drill.common.exceptions.UserException$Builder.build(UserException.java:534) ~[classes/:na]
	at org.apache.drill.exec.work.fragment.FragmentExecutor.sendFinalState(FragmentExecutor.java:324) [classes/:na]
	at org.apache.drill.exec.work.fragment.FragmentExecutor.cleanup(FragmentExecutor.java:184) [classes/:na]
	at org.apache.drill.exec.work.fragment.FragmentExecutor.run(FragmentExecutor.java:290) [classes/:na]
	at org.apache.drill.common.SelfCleaningRunnable.run(SelfCleaningRunnable.java:38) [classes/:na]
	at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1142) [na:1.8.0_101]
	at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:617) [na:1.8.0_101]
	at java.lang.Thread.run(Thread.java:745) [na:1.8.0_101]
Caused by: java.lang.IndexOutOfBoundsException: index: 131072, length: 2 (expected: range(0, 131072))
	at io.netty.buffer.DrillBuf.checkIndexD(DrillBuf.java:175) ~[classes/:4.0.27.Final]
	at io.netty.buffer.DrillBuf.chk(DrillBuf.java:197) ~[classes/:4.0.27.Final]
	at io.netty.buffer.DrillBuf.setChar(DrillBuf.java:517) ~[classes/:4.0.27.Final]
	at org.apache.drill.exec.record.selection.SelectionVector2.setIndex(SelectionVector2.java:79) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.limit.LimitRecordBatch.limitWithNoSV(LimitRecordBatch.java:167) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.limit.LimitRecordBatch.doWork(LimitRecordBatch.java:145) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractSingleRecordBatch.innerNext(AbstractSingleRecordBatch.java:93) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.limit.LimitRecordBatch.innerNext(LimitRecordBatch.java:115) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractRecordBatch.next(AbstractRecordBatch.java:162) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.validate.IteratorValidatorBatchIterator.next(IteratorValidatorBatchIterator.java:215) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractRecordBatch.next(AbstractRecordBatch.java:119) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractRecordBatch.next(AbstractRecordBatch.java:109) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractSingleRecordBatch.innerNext(AbstractSingleRecordBatch.java:51) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.svremover.RemovingRecordBatch.innerNext(RemovingRecordBatch.java:94) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractRecordBatch.next(AbstractRecordBatch.java:162) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.validate.IteratorValidatorBatchIterator.next(IteratorValidatorBatchIterator.java:215) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractRecordBatch.next(AbstractRecordBatch.java:119) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractRecordBatch.next(AbstractRecordBatch.java:109) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractSingleRecordBatch.innerNext(AbstractSingleRecordBatch.java:51) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.project.ProjectRecordBatch.innerNext(ProjectRecordBatch.java:132) ~[classes/:na]
	at org.apache.drill.exec.record.AbstractRecordBatch.next(AbstractRecordBatch.java:162) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.validate.IteratorValidatorBatchIterator.next(IteratorValidatorBatchIterator.java:215) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.BaseRootExec.next(BaseRootExec.java:104) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.ScreenCreator$ScreenRoot.innerNext(ScreenCreator.java:81) ~[classes/:na]
	at org.apache.drill.exec.physical.impl.BaseRootExec.next(BaseRootExec.java:94) ~[classes/:na]
	at org.apache.drill.exec.work.fragment.FragmentExecutor$1.run(FragmentExecutor.java:256) ~[classes/:na]
	at org.apache.drill.exec.work.fragment.FragmentExecutor$1.run(FragmentExecutor.java:250) ~[classes/:na]
	at java.security.AccessController.doPrivileged(Native Method) ~[na:1.8.0_101]
	at javax.security.auth.Subject.doAs(Subject.java:422) ~[na:1.8.0_101]
	at org.apache.hadoop.security.UserGroupInformation.doAs(UserGroupInformation.java:1657) ~[hadoop-common-2.7.1.jar:na]
	at org.apache.drill.exec.work.fragment.FragmentExecutor.run(FragmentExecutor.java:250) [classes/:na]
	... 4 common frames omitted
{noformat}

Code from IteratorValidatorBatchIterator.java said that it is OK incoming returning 65536 records:

{noformat}
if (incoming.getRecordCount() > MAX_BATCH_SIZE) { // MAX_BATCH_SIZE == 65536
          throw new IllegalStateException(
              String.format(
                  "Incoming batch [#%d, %s] has size %d, which is beyond the"
                  + " limit of %d",
                  instNum, batchTypeName, incoming.getRecordCount(), MAX_BATCH_SIZE
                  ));
        }
{noformat}

Code from LimitRecordBatch.java shows that a loop will not break as expected when the incoming returns 65536 records:
{noformat}
  private void limitWithNoSV(int recordCount) {
    final int offset = Math.max(0, Math.min(recordCount - 1, recordsToSkip));
    recordsToSkip -= offset;
    int fetch;

    if(noEndLimit) {
      fetch = recordCount;
    } else {
      fetch = Math.min(recordCount, offset + recordsLeft);
      recordsLeft -= Math.max(0, fetch - offset);
    }

    int svIndex = 0;
    for(char i = (char) offset; i < fetch; svIndex++, i++) { // since fetch==recordCount==65536, param i can be increased from 65535 to 65536, then be limited to 0 by the char type limitation, the loop abnormally continues.
      outgoingSv.setIndex(svIndex, i);
    }
    outgoingSv.setRecordCount(svIndex);
  }
{noformat}

The IllegalStateException should be thrown when incoming returns 65535 records rather than 65536.
```

## Fix commit message(s)

`1e6fa00cd4b0`

```
DRILL-4884: Fix IOB exception in limit n query when n is beyond 65535.

close apache/drill#584
```

## Files the fix changed

Snapshot holds 1,823 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `exec/java-exec/src/main/java/org/apache/drill/exec/physical/impl/limit/LimitRecordBatch.java`

## The fix diff

### `exec/java-exec/src/main/java/org/apache/drill/exec/physical/impl/limit/LimitRecordBatch.java`

```diff
diff --git a/exec/java-exec/src/main/java/org/apache/drill/exec/physical/impl/limit/LimitRecordBatch.java b/exec/java-exec/src/main/java/org/apache/drill/exec/physical/impl/limit/LimitRecordBatch.java
index 176ee1704..08ffc0b77 100644
--- a/exec/java-exec/src/main/java/org/apache/drill/exec/physical/impl/limit/LimitRecordBatch.java
+++ b/exec/java-exec/src/main/java/org/apache/drill/exec/physical/impl/limit/LimitRecordBatch.java
@@ -161,12 +161,12 @@ public class LimitRecordBatch extends AbstractSingleRecordBatch<Limit> {
       fetch = Math.min(recordCount, offset + recordsLeft);
       recordsLeft -= Math.max(0, fetch - offset);
     }
 
     int svIndex = 0;
-    for(char i = (char) offset; i < fetch; svIndex++, i++) {
-      outgoingSv.setIndex(svIndex, i);
+    for(int i = offset; i < fetch; svIndex++, i++) {
+      outgoingSv.setIndex(svIndex, (char) i);
     }
     outgoingSv.setRecordCount(svIndex);
   }
 
   private void limitWithSV(int recordCount) {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
