# Annotation packet: ISPN-8568  (infinispan)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
ClassNotFoundException with Compat mode and deployed Pojos

The cache is configured with:

{code:xml}
<cache-container name="local">
     <modules>
          <module name="deployment.myTask.jar"/>
     </modules>
     <local-cache name="compat">
          <compatibility enabled="true"/>
     </local-cache>
</cache-container>
{code}

The {{myTask.jar}} contains Entity.class that is the Pojo to be stored in the cache.

When doing a 

{code:java}
remoteCache.put(1, new Entity());
{code}

The error is 

{noformat}
18:13:42,142 ERROR (main) [TestSuiteProgress] Test failed: LocalServerTestCompatModeIT.shouldRunPriceTask
org.infinispan.client.hotrod.exceptions.HotRodClientException:Request for messageId=9 returned 
server error (status=0x85): java.lang.ClassNotFoundException: org.infinispan.server.test.Entity from [Module "org.infinispan.commons:main" from 
local module loader @4ae82894 (finder: local module finder @543788f3 (roots: /home/gfernandes/github/infinispan/server/integration/testsuite/target/server/node1/modules,/home/gfernandes/github/infinispan/server/integration/testsuite/target/server/node1/modules/system/layers/base))]
{noformat}	





I noticed that in this case, the Marshaller used is {{GenericJBossMarshaller}} who lives in infinispan-commons,  and when asked to de-serialize the pojo in byte[] form, the classloader  used is ModuleClassLoader for Module "org.infinispan.commons:main" that does not have visibility of the deployed jar's classes.
```

## Fix commit message(s)

`b042793b6089`

```
ISPN-8568 ClassNotFoundException with Compat mode and custom Pojos
```

## Files the fix changed

Snapshot holds 4,031 non-test source files. The fix changed 10 file(s); 4 of them are non-test source files (listed below as gold).

- `commons/src/main/java/org/infinispan/commons/dataconversion/CompatModeEncoder.java`
- `commons/src/main/java/org/infinispan/commons/dataconversion/GenericJbossMarshallerEncoder.java`
- `core/src/main/java/org/infinispan/encoding/DataConversion.java`
- `core/src/main/java/org/infinispan/factories/EncoderRegistryFactory.java`

## The fix diff

### `commons/src/main/java/org/infinispan/commons/dataconversion/CompatModeEncoder.java`

```diff
diff --git a/commons/src/main/java/org/infinispan/commons/dataconversion/CompatModeEncoder.java b/commons/src/main/java/org/infinispan/commons/dataconversion/CompatModeEncoder.java
index 4caacb2a11..0dca1b2e42 100644
--- a/commons/src/main/java/org/infinispan/commons/dataconversion/CompatModeEncoder.java
+++ b/commons/src/main/java/org/infinispan/commons/dataconversion/CompatModeEncoder.java
@@ -16,11 +16,15 @@ import org.infinispan.commons.marshall.jboss.GenericJBossMarshaller;
 public class CompatModeEncoder implements Encoder {
 
    protected final Marshaller marshaller;
 
    public CompatModeEncoder(Marshaller marshaller) {
-      this.marshaller = marshaller == null ? new GenericJBossMarshaller() : marshaller;
+      this(marshaller, CompatModeEncoder.class.getClassLoader());
+   }
+
+   public CompatModeEncoder(Marshaller marshaller, ClassLoader classLoader) {
+      this.marshaller = marshaller == null ? new GenericJBossMarshaller(classLoader) : marshaller;
    }
 
    @Override
    public Object toStorage(Object content) {
       if (content instanceof byte[]) {
```

### `commons/src/main/java/org/infinispan/commons/dataconversion/GenericJbossMarshallerEncoder.java`

```diff
diff --git a/commons/src/main/java/org/infinispan/commons/dataconversion/GenericJbossMarshallerEncoder.java b/commons/src/main/java/org/infinispan/commons/dataconversion/GenericJbossMarshallerEncoder.java
index 34b5dd55fd..349113dc7d 100644
--- a/commons/src/main/java/org/infinispan/commons/dataconversion/GenericJbossMarshallerEncoder.java
+++ b/commons/src/main/java/org/infinispan/commons/dataconversion/GenericJbossMarshallerEncoder.java
@@ -8,11 +8,15 @@ import org.infinispan.commons.marshall.jboss.GenericJBossMarshaller;
 public class GenericJbossMarshallerEncoder extends MarshallerEncoder {
 
    public static final GenericJbossMarshallerEncoder INSTANCE = new GenericJbossMarshallerEncoder();
 
    private GenericJbossMarshallerEncoder() {
-      super(new GenericJBossMarshaller());
+      this(GenericJbossMarshallerEncoder.class.getClassLoader());
+   }
+
+   public GenericJbossMarshallerEncoder(ClassLoader classLoader) {
+      super(new GenericJBossMarshaller(classLoader));
    }
 
    @Override
    public MediaType getStorageFormat() {
       return MediaType.APPLICATION_JBOSS_MARSHALLED;
```

### `core/src/main/java/org/infinispan/encoding/DataConversion.java`

```diff
diff --git a/core/src/main/java/org/infinispan/encoding/DataConversion.java b/core/src/main/java/org/infinispan/encoding/DataConversion.java
index 9831ad4040..bc8a5bace7 100644
--- a/core/src/main/java/org/infinispan/encoding/DataConversion.java
+++ b/core/src/main/java/org/infinispan/encoding/DataConversion.java
@@ -152,11 +152,11 @@ public class DataConversion {
          if (compat) {
             this.encoderClass = embeddedMode ? IdentityEncoder.class : CompatModeEncoder.class;
          }
       }
       this.lookupWrapper(encoderRegistry);
-      this.lookupEncoder(encoderRegistry, compatibility);
+      this.lookupEncoder(encoderRegistry, compatibility, gcr.classLoader());
       this.storageMediaType = getStorageMediaType(configuration, embeddedMode);
       this.lookupTranscoder(encoderRegistry);
    }
 
    private void lookupTranscoder(EncoderRegistry encoderRegistry) {
@@ -178,18 +178,18 @@ public class DataConversion {
             transcoder = encoderRegistry.getTranscoder(requestMediaType, storageMediaType);
          }
       }
    }
 
-   private void lookupEncoder(EncoderRegistry encoderRegistry, CompatibilityModeConfiguration compatConfig) {
+   private void lookupEncoder(EncoderRegistry encoderRegistry, CompatibilityModeConfiguration compatConfig, ClassLoader classLoader) {
       if (!compatConfig.enabled()) {
          this.encoder = encoderRegistry.getEncoder(encoderClass, encoderId);
       } else {
          if (encoderClass == null || encoderClass.equals(CompatModeEncoder.class)) {
             this.encoderClass = CompatModeEncoder.class;
             Marshaller compatMarshaller = compatConfig.marshaller();
-            this.encoder = new CompatModeEncoder(compatMarshaller);
+            this.encoder = new CompatModeEncoder(compatMarshaller, classLoader);
          } else {
             this.encoder = encoderRegistry.getEncoder(encoderClass, encoderId);
          }
       }
    }
```

### `core/src/main/java/org/infinispan/factories/EncoderRegistryFactory.java`

```diff
diff --git a/core/src/main/java/org/infinispan/factories/EncoderRegistryFactory.java b/core/src/main/java/org/infinispan/factories/EncoderRegistryFactory.java
index 757f9a619d..109d1374ef 100644
--- a/core/src/main/java/org/infinispan/factories/EncoderRegistryFactory.java
+++ b/core/src/main/java/org/infinispan/factories/EncoderRegistryFactory.java
@@ -29,17 +29,19 @@ public class EncoderRegistryFactory extends AbstractComponentFactory implements
    private StreamingMarshaller globalMarshaller;
 
    @Override
    public <T> T construct(Class<T> componentType) {
       EncoderRegistryImpl encoderRegistry = new EncoderRegistryImpl();
+      ClassLoader classLoader = globalConfiguration.classLoader();
+
       encoderRegistry.registerEncoder(IdentityEncoder.INSTANCE);
       encoderRegistry.registerEncoder(UTF8Encoder.INSTANCE);
       encoderRegistry.registerEncoder(JavaSerializationEncoder.INSTANCE);
       encoderRegistry.registerEncoder(new BinaryEncoder(globalMarshaller));
-      encoderRegistry.registerEncoder(GenericJbossMarshallerEncoder.INSTANCE);
+      encoderRegistry.registerEncoder(new GenericJbossMarshallerEncoder(classLoader));
       encoderRegistry.registerEncoder(new GlobalMarshallerEncoder(globalMarshaller));
-      encoderRegistry.registerEncoder(new CompatModeEncoder(globalMarshaller));
+      encoderRegistry.registerEncoder(new CompatModeEncoder(globalMarshaller, classLoader));
       encoderRegistry.registerEncoder(JavaCompatEncoder.INSTANCE);
       encoderRegistry.registerEncoder(UTF8CompatEncoder.INSTANCE);
       encoderRegistry.registerTranscoder(TextTranscoder.INSTANCE);
 
       encoderRegistry.registerWrapper(ByteArrayWrapper.INSTANCE);
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
