# Annotation packet: HADOOP-13285  (hadoop)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
DecayRpcScheduler MXBean should only report decayed CallVolumeSummary

HADOOP-13197 added non-decayed call metrics in metrics2 source for DecayedRpcScheduler. However, CallVolumeSummary in MXBean was affected unexpectedly to include both decayed and non-decayed call volume. The root cause is Jackson ObjectMapper simply serialize all the content of the callCounts map which contains both non-decayed and decayed counter after HADOOP-13197. This ticket is opened to fix the CallVolumeSummary in MXBean to include only decayed call volume for backward compatibility and add unit test for DecayRpcScheduler MXBean to catch this in future. 

CallVolumeSummary JMX example before HADOOP-13197
{code}
"CallVolumeSummary" : "{\"hbase\":1,\"mapred\":1}"
{code}

 CallVolumeSummary JMX example after HADOOP-13197
{code}
"CallVolumeSummary" : "{\"user_x\":[1,2]}"
{code}
```

## Fix commit message(s)

`0761379fe458`

```
HADOOP-13285. DecayRpcScheduler MXBean should only report decayed CallVolumeSummary. Contributed by Xiaoyu Yao.
```

## Files the fix changed

Snapshot holds 4,690 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/ipc/DecayRpcScheduler.java`

## The fix diff

### `hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/ipc/DecayRpcScheduler.java`

```diff
diff --git a/hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/ipc/DecayRpcScheduler.java b/hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/ipc/DecayRpcScheduler.java
index ec87c753f58..f40bd172b62 100644
--- a/hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/ipc/DecayRpcScheduler.java
+++ b/hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/ipc/DecayRpcScheduler.java
@@ -899,11 +899,26 @@ public class DecayRpcScheduler implements RpcScheduler,
   }
 
   public String getCallVolumeSummary() {
     try {
       ObjectMapper om = new ObjectMapper();
-      return om.writeValueAsString(callCounts);
+      return om.writeValueAsString(getDecayedCallCounts());
     } catch (Exception e) {
       return "Error: " + e.getMessage();
     }
   }
+
+  private Map<Object, Long> getDecayedCallCounts() {
+    Map<Object, Long> decayedCallCounts = new HashMap<>(callCounts.size());
+    Iterator<Map.Entry<Object, List<AtomicLong>>> it =
+        callCounts.entrySet().iterator();
+    while (it.hasNext()) {
+      Map.Entry<Object, List<AtomicLong>> entry = it.next();
+      Object user = entry.getKey();
+      Long decayedCount = entry.getValue().get(0).get();
+      if (decayedCount > 0) {
+        decayedCallCounts.put(user, decayedCount);
+      }
+    }
+    return decayedCallCounts;
+  }
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
