# Annotation packet: BEAM-4066  (beam)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Nexmark fails when running with PubSub as source/sink

Running Nexmark with PubSub cause this exception:

{noformat}
Caused by: java.io.NotSerializableException: org.apache.beam.sdk.nexmark.NexmarkLauncher
{noformat}

Full log is attached.
```

## Fix commit message(s)

`30261ce1d45f`

```
[BEAM-4066] Moved anonymous classes into inner ones
```

## Files the fix changed

Snapshot holds 1,960 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `sdks/java/nexmark/src/main/java/org/apache/beam/sdk/nexmark/NexmarkLauncher.java`

## The fix diff

### `sdks/java/nexmark/src/main/java/org/apache/beam/sdk/nexmark/NexmarkLauncher.java`

```diff
diff --git a/sdks/java/nexmark/src/main/java/org/apache/beam/sdk/nexmark/NexmarkLauncher.java b/sdks/java/nexmark/src/main/java/org/apache/beam/sdk/nexmark/NexmarkLauncher.java
index cd24897664a..8f0213669cd 100644
--- a/sdks/java/nexmark/src/main/java/org/apache/beam/sdk/nexmark/NexmarkLauncher.java
+++ b/sdks/java/nexmark/src/main/java/org/apache/beam/sdk/nexmark/NexmarkLauncher.java
@@ -753,24 +753,12 @@ public class NexmarkLauncher<OptionT extends NexmarkOptions> {
             .withIdAttribute(NexmarkUtils.PUBSUB_ID);
     if (!configuration.usePubsubPublishTime) {
       io = io.withTimestampAttribute(NexmarkUtils.PUBSUB_TIMESTAMP);
     }
 
-    return p
-      .apply(queryName + ".ReadPubsubEvents", io)
-      .apply(queryName + ".PubsubMessageToEvent", ParDo.of(new DoFn<PubsubMessage, Event>() {
-        @ProcessElement
-        public void processElement(ProcessContext c) {
-          byte[] payload = c.element().getPayload();
-          try {
-            Event event = CoderUtils.decodeFromByteArray(Event.CODER, payload);
-            c.output(event);
-          } catch (CoderException e) {
-            LOG.error("Error while decoding Event from pusbSub message: serialization error");
-          }
-        }
-      }));
+    return p.apply(queryName + ".ReadPubsubEvents", io)
+        .apply(queryName + ".PubsubMessageToEvent", ParDo.of(new PubsubMessageEventDoFn()));
   }
 
   static final DoFn<Event, byte[]> EVENT_TO_BYTEARRAY =
           new DoFn<Event, byte[]>() {
             @ProcessElement
@@ -862,26 +850,11 @@ public class NexmarkLauncher<OptionT extends NexmarkOptions> {
     if (!configuration.usePubsubPublishTime) {
       io = io.withTimestampAttribute(NexmarkUtils.PUBSUB_TIMESTAMP);
     }
 
     events
-        .apply(
-            queryName + ".EventToPubsubMessage",
-            ParDo.of(
-                new DoFn<Event, PubsubMessage>() {
-                  @ProcessElement
-                  public void processElement(ProcessContext c) {
-                    try {
-                      byte[] payload = CoderUtils.encodeToByteArray(Event.CODER, c.element());
-                      c.output(new PubsubMessage(payload, new HashMap<>()));
-                    } catch (CoderException e1) {
-                      LOG.error(
-                          "Error while sending Event {} to pusbSub: serialization error",
-                          c.element().toString());
-                    }
-                  }
-                }))
+        .apply(queryName + ".EventToPubsubMessage", ParDo.of(new EventPubsubMessageDoFn()))
         .apply(queryName + ".WritePubsubEvents", io);
   }
 
   /**
    * Send {@code formattedResults} to Kafka.
@@ -1321,6 +1294,34 @@ public class NexmarkLauncher<OptionT extends NexmarkOptions> {
         new Query9(configuration),
         new Query10(configuration),
         new Query11(configuration),
         new Query12(configuration));
   }
+
+  private static class PubsubMessageEventDoFn extends DoFn<PubsubMessage, Event> {
+
+    @ProcessElement
+    public void processElement(ProcessContext c) {
+      byte[] payload = c.element().getPayload();
+      try {
+        Event event = CoderUtils.decodeFromByteArray(Event.CODER, payload);
+        c.output(event);
+      } catch (CoderException e) {
+        LOG.error("Error while decoding Event from pusbSub message: serialization error");
+      }
+    }
+  }
+
+  private static class EventPubsubMessageDoFn extends DoFn<Event, PubsubMessage> {
+
+    @ProcessElement
+    public void processElement(ProcessContext c) {
+      try {
+        byte[] payload = CoderUtils.encodeToByteArray(Event.CODER, c.element());
+        c.output(new PubsubMessage(payload, new HashMap<>()));
+      } catch (CoderException e1) {
+        LOG.error(
+            "Error while sending Event {} to pusbSub: serialization error", c.element().toString());
+      }
+    }
+  }
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
