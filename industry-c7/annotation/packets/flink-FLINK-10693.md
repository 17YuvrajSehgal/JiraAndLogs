# Annotation packet: FLINK-10693  (flink)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Fix Scala EitherSerializer duplication

The Scala Either Serializer has buggy duplication logic, resulting in sharing and incorrect concurrent use when the nested serializers are not thread safe.
```

## Fix commit message(s)

`68df7f969c89`

```
[FLINK-10693] [Scala API] Fix incorrect duplication in EitherSerializer

This closes #6951.
```

## Files the fix changed

Snapshot holds 4,668 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `flink-scala/src/main/scala/org/apache/flink/api/scala/typeutils/EitherSerializer.scala`

## The fix diff

### `flink-scala/src/main/scala/org/apache/flink/api/scala/typeutils/EitherSerializer.scala`

```diff
diff --git a/flink-scala/src/main/scala/org/apache/flink/api/scala/typeutils/EitherSerializer.scala b/flink-scala/src/main/scala/org/apache/flink/api/scala/typeutils/EitherSerializer.scala
index c2bda3dc3fc..14f2196b9cc 100644
--- a/flink-scala/src/main/scala/org/apache/flink/api/scala/typeutils/EitherSerializer.scala
+++ b/flink-scala/src/main/scala/org/apache/flink/api/scala/typeutils/EitherSerializer.scala
@@ -30,11 +30,20 @@ import org.apache.flink.core.memory.{DataInputView, DataOutputView}
 class EitherSerializer[A, B](
     val leftSerializer: TypeSerializer[A],
     val rightSerializer: TypeSerializer[B])
   extends TypeSerializer[Either[A, B]] {
 
-  override def duplicate: EitherSerializer[A,B] = this
+  override def duplicate: EitherSerializer[A,B] = {
+    val leftDup = leftSerializer.duplicate()
+    val rightDup = rightSerializer.duplicate()
+
+    if (leftDup.eq(leftSerializer) && rightDup.eq(rightSerializer)) {
+      this
+    } else {
+      new EitherSerializer[A, B](leftDup, rightDup)
+    }
+  }
 
   override def createInstance: Either[A, B] = {
     Left(null).asInstanceOf[Left[A, B]]
   }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
