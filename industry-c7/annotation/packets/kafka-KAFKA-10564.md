# Annotation packet: KAFKA-10564  (kafka)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Continuous logging about deleting obsolete state directories

The internal process which automatically cleans up obsolete task state directories was modified in https://issues.apache.org/jira/browse/KAFKA-6647. The current logic in 2.6 is to remove all files from the task directory except the {{.lock}} file:

[https://github.com/apache/kafka/blob/2.6/streams/src/main/java/org/apache/kafka/streams/processor/internals/StateDirectory.java#L335]

However, the directory is only removed in its entirely for a manual cleanup:

[https://github.com/apache/kafka/blob/2.6/streams/src/main/java/org/apache/kafka/streams/processor/internals/StateDirectory.java#L349-L353]

The result of this is that Streams will continue revisiting this directory and trying to clean it up, since it determines what to clean based on last-modification time of the task directory (which is now no longer deleted during the automatic cleanup). So a user will see log messages like:
stream-thread [app-c2d773e6-8ac3-4435-9777-378e0ec0ab82-CleanupThread] Deleting obsolete state directory 0_8 for task 0_8 as 60600001ms has elapsed (cleanup delay is 600000ms)
repeated again and again.

This issue doesn't seem to break anything - it's more about avoiding unnecessary logging and cleaning up empty task directories.
```

## Fix commit message(s)

`250c71b53260`

```
KAFKA-10564: only process non-empty task directories when internally cleaning obsolete state stores (#9373)

Avoid continuous repeated logging by not trying to clean empty task directories, which are longer fully deleted during internal cleanup as of https://issues.apache.org/jira/browse/KAFKA-6647.

Reviewers: A. Sophie Blee-Goldman <sophie@confluent.io>, Guozhang Wang <wangguoz@gmail.com>
```

`c3c65de3f0c6`

```
KAFKA-10564: fix flaky test (#9466)

Minor update to fix flaky state directory test by advancing the MockTime.

Reviewers: Chia-Ping Tsai <chia7712@gmail.com>, A. Sophie Blee-Goldman <ableegoldman@apache.org>
```

## Files the fix changed

Snapshot holds 2,027 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `streams/src/main/java/org/apache/kafka/streams/processor/internals/StateDirectory.java`

## The fix diff

### `streams/src/main/java/org/apache/kafka/streams/processor/internals/StateDirectory.java`

```diff
--- from commit 250c71b53260 ---
diff --git a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StateDirectory.java b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StateDirectory.java
index de9fbead94..35f937a3ab 100644
--- a/streams/src/main/java/org/apache/kafka/streams/processor/internals/StateDirectory.java
+++ b/streams/src/main/java/org/apache/kafka/streams/processor/internals/StateDirectory.java
@@ -313,11 +313,11 @@ public class StateDirectory {
             throw new IllegalStateException("Should have swallowed exception.", cannotHappen);
         }
     }
 
     private void cleanRemovedTasksCalledByCleanerThread(final long cleanupDelayMs) {
-        for (final File taskDir : listAllTaskDirectories()) {
+        for (final File taskDir : listNonEmptyTaskDirectories()) {
             final String dirName = taskDir.getName();
             final TaskId id = TaskId.parse(dirName);
             if (!locks.containsKey(id)) {
                 try {
                     if (lock(id)) {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
