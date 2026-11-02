# Annotation packet: CAMEL-9227  (camel)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
No type converter available to convert from Bean to List

{code}
Tests in error: 
  CSVIntegrationTest.testMarshalViaDozer:101 » CamelExecution Exception occurred...

Tests run: 3, Failures: 0, Errors: 1, Skipped: 0

Caused by: org.apache.camel.NoTypeConversionAvailableException: No type converter available to convert from type: org.wildfly.camel.test.common.types.Customer to the required type: java.util.List with value org.wildfly.camel.test.common.types.Customer@42776551
	at org.apache.camel.impl.converter.BaseTypeConverterRegistry.mandatoryConvertTo(BaseTypeConverterRegistry.java:185)
	at org.apache.camel.util.ExchangeHelper.convertToMandatoryType(ExchangeHelper.java:187)
	at org.apache.camel.dataformat.csv.CsvMarshaller.getRecordValues(CsvMarshaller.java:95)
	at org.apache.camel.dataformat.csv.CsvMarshaller.marshal(CsvMarshaller.java:82)
	at org.apache.camel.dataformat.csv.CsvDataFormat.marshal(CsvDataFormat.java:82)
{code}
```

## Fix commit message(s)

`7c0377b9faef`

```
[CAMEL-9227] No type converter available to convert from Bean to List
```

`a3520ddd59f2`

```
Fixes #647. CAMEL-9227: Fixed CS
```

## Files the fix changed

Snapshot holds 4,363 non-test source files. The fix changed 6 file(s); 1 of them are non-test source files (listed below as gold).

- `components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverter.java`

## The fix diff

### `components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverter.java`

```diff
--- from commit 7c0377b9faef ---
diff --git a/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverter.java b/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverter.java
index e5114e48ab9..0505a64599c 100644
--- a/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverter.java
+++ b/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverter.java
@@ -38,11 +38,11 @@ import org.slf4j.LoggerFactory;
  * @see DozerTypeConverterLoader
  */
 public class DozerTypeConverter extends TypeConverterSupport {
 
     private static final Logger LOG = LoggerFactory.getLogger(DozerTypeConverter.class);
-    
+
     private final DozerBeanMapper mapper;
 
     public DozerTypeConverter(DozerBeanMapper mapper) {
         this.mapper = mapper;
     }
@@ -51,44 +51,41 @@ public class DozerTypeConverter extends TypeConverterSupport {
         return mapper;
     }
 
     @Override
     public <T> T convertTo(Class<T> type, Exchange exchange, Object value) throws TypeConversionException {
-        // find the map id, so we can provide that when trying to map from source to destination
-        String mapId = null;
-        if (value != null) {
-            Class<?> sourceType = value.getClass();
-            Class<?> destType = type;
-            ClassMappingMetadata metadata = mapper.getMappingMetadata().getClassMapping(sourceType, destType);
-            if (metadata != null) {
-                mapId = metadata.getMapId();
+
+        CamelContext context = exchange != null ? exchange.getContext() : null;
+        ClassLoader appcl = context != null ? context.getApplicationContextClassLoader() : null;
+
+        T result;
+
+        ClassLoader tccl = Thread.currentThread().getContextClassLoader();
+        try {
+            if (appcl != null && appcl != tccl) {
+                LOG.debug("Switching TCCL to: {}", appcl);
+                Thread.currentThread().setContextClassLoader(appcl);
             }
-        }
 
-        // if the exchange is null, we have no chance to ensure that the TCCL is the one from the CamelContext
-        if (exchange == null) {
-            return mapper.map(value, type, mapId);
-        }
-        
-        T answer = null;
+            // find the map id, so we can provide that when trying to map from source to destination
+            String mapId = null;
+            if (value != null) {
+                Class<?> sourceType = value.getClass();
+                Class<?> destType = type;
+                ClassMappingMetadata metadata = mapper.getMappingMetadata().getClassMapping(sourceType, destType);
+                if (metadata != null) {
+                    mapId = metadata.getMapId();
+                }
+            }
 
-        ClassLoader prev = Thread.currentThread().getContextClassLoader();
-        ClassLoader contextCl = exchange.getContext().getApplicationContextClassLoader();
-        if (contextCl != null) {
-            // otherwise, we ensure that the TCCL is the correct one
-            LOG.debug("Switching TCCL to: {}.", contextCl);
-            try {
-                Thread.currentThread().setContextClassLoader(contextCl);
-                answer = mapper.map(value, type, mapId);
-            } finally {
-                LOG.debug("Restored TCCL to: {}.", prev);
-                Thread.currentThread().setContextClassLoader(prev);
+            result = mapper.map(value, type, mapId);
+
+        } finally {
+            if (appcl != null && appcl != tccl) {
+                Thread.currentThread().setContextClassLoader(tccl);
+                LOG.debug("Restored TCCL to: {}", tccl);
             }
-        } else {
-            // just try with the current TCCL as-is
-            answer = mapper.map(value, type, mapId);
         }
 
-        return answer;
+        return result;
     }
-
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
