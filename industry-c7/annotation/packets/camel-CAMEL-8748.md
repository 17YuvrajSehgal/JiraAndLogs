# Annotation packet: CAMEL-8748  (camel)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
DozerBeanMapper cannot instantiate DozerThreadContextClassLoader 


{code}
15:26:16,518 SEVERE [org.jboss.arquillian.protocol.jmx.JMXTestRunner] (pool-2-thread-1) Failed: org.wildfly.camel.test.csv.CSVIntegrationTest.testMarshal: org.dozer.MappingException: java.lang.InstantiationException: org.apache.camel.converter.dozer.DozerThreadContextClassLoader
	at org.dozer.util.MappingUtils.throwMappingException(MappingUtils.java:82) [dozer-5.5.1.jar:]
	at org.dozer.util.ReflectionUtils.newInstance(ReflectionUtils.java:366) [dozer-5.5.1.jar:]
	at org.dozer.DozerInitializer.registerClassLoader(DozerInitializer.java:118) [dozer-5.5.1.jar:]
	at org.dozer.DozerInitializer.initialize(DozerInitializer.java:98) [dozer-5.5.1.jar:]
	at org.dozer.DozerInitializer.init(DozerInitializer.java:79) [dozer-5.5.1.jar:]
	at org.dozer.DozerInitializer.init(DozerInitializer.java:64) [dozer-5.5.1.jar:]
	at org.dozer.DozerBeanMapper.init(DozerBeanMapper.java:173) [dozer-5.5.1.jar:]
	at org.dozer.DozerBeanMapper.<init>(DozerBeanMapper.java:99) [dozer-5.5.1.jar:]
	at org.apache.camel.converter.dozer.DozerTypeConverterLoader.createDozerBeanMapper(DozerTypeConverterLoader.java:232) [camel-dozer-2.16-SNAPSHOT.jar:2.16-SNAPSHOT]
	at org.apache.camel.converter.dozer.DozerTypeConverterLoader.<init>(DozerTypeConverterLoader.java:118) [camel-dozer-2.16-SNAPSHOT.jar:2.16-SNAPSHOT]
	at org.wildfly.camel.test.csv.CSVIntegrationTest.testMarshal(CSVIntegrationTest.java:68) [csv-dataformat-tests:]
...
Caused by: java.lang.InstantiationException: org.apache.camel.converter.dozer.DozerThreadContextClassLoader
	at java.lang.Class.newInstance(Class.java:423) [rt.jar:1.8.0_31]
	at org.dozer.util.ReflectionUtils.newInstance(ReflectionUtils.java:364) [dozer-5.5.1.jar:]
	... 150 more
Caused by: java.lang.NoSuchMethodException: org.apache.camel.converter.dozer.DozerThreadContextClassLoader.<init>()
	at java.lang.Class.getConstructor0(Class.java:3074) [rt.jar:1.8.0_31]
	at java.lang.Class.newInstance(Class.java:408) [rt.jar:1.8.0_31]
	... 151 more
{code}

The {{org.dozer.DozerInitializer}} does

{code}
  private void registerClassLoader(GlobalSettings globalSettings, ClassLoader classLoader, BeanContainer beanContainer) {
    String classLoaderName = globalSettings.getClassLoaderName();
    if (!DozerConstants.DEFAULT_CLASS_LOADER_BEAN.equals(classLoaderName)) {
      DefaultClassLoader defaultClassLoader = new DefaultClassLoader(classLoader);
      Class<? extends DozerClassLoader> classLoaderType = loadBeanType(classLoaderName, defaultClassLoader, DozerClassLoader.class);
      DozerClassLoader classLoaderBean = ReflectionUtils.newInstance(classLoaderType);
      beanContainer.setClassLoader(classLoaderBean);
    }
  }
{code}
```

## Fix commit message(s)

`08a5722f5cf7`

```
[CAMEL-8748] DozerBeanMapper cannot instantiate DozerThreadContextClassLoader
```

## Files the fix changed

Snapshot holds 4,287 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerThreadContextClassLoader.java`
- `components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverterLoader.java`

## The fix diff

### `components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerThreadContextClassLoader.java`

```diff
diff --git a/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerThreadContextClassLoader.java b/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerThreadContextClassLoader.java
index b5d98064601..8d1d4829afe 100644
--- a/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerThreadContextClassLoader.java
+++ b/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerThreadContextClassLoader.java
@@ -27,30 +27,20 @@ import org.slf4j.Logger;
 import org.slf4j.LoggerFactory;
 
 public class DozerThreadContextClassLoader implements DozerClassLoader {
 
     private static final Logger LOG = LoggerFactory.getLogger(DozerThreadContextClassLoader.class);
-    
-    private final DozerClassLoader delegate;
 
-    public DozerThreadContextClassLoader(DozerClassLoader delegate) {
-        this.delegate = delegate;
-    }
-    
     @Override
     public Class<?> loadClass(String className) {
         LOG.debug("Loading class from classloader: {}.", Thread.currentThread().getContextClassLoader());
         Class<?> result = null;
         try {
             // try to resolve the class from the thread context classloader
             result = ClassUtils.getClass(Thread.currentThread().getContextClassLoader(), className);
         } catch (ClassNotFoundException e) {
-            // if unresolvable, ask the delegate
-            result = delegate.loadClass(className);
-            if (result == null) {
-                MappingUtils.throwMappingException(e);
-            }
+            MappingUtils.throwMappingException(e);
         }
         return result;
     }
 
     @Override
@@ -61,15 +51,10 @@ public class DozerThreadContextClassLoader implements DozerClassLoader {
         if (cl != null) {
             LOG.debug("Loading resource from classloader: {}.", cl);
             answer = cl.getResource(uri);
         }
 
-        // try loading it from the delegate
-        if (answer == null && delegate != null) {
-            answer = delegate.loadResource(uri);
-        }
-        
         // try treating it as a system resource
         if (answer == null) {
             answer = ClassLoader.getSystemResource(uri);
         }
```

### `components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverterLoader.java`

```diff
diff --git a/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverterLoader.java b/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverterLoader.java
index 080e621c4c9..66961158a0c 100644
--- a/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverterLoader.java
+++ b/components/camel-dozer/src/main/java/org/apache/camel/converter/dozer/DozerTypeConverterLoader.java
@@ -14,12 +14,13 @@
  * See the License for the specific language governing permissions and
  * limitations under the License.
  */
 package org.apache.camel.converter.dozer;
 
-import java.lang.reflect.Field;
+import static org.dozer.classmap.MappingDirection.ONE_WAY;
 
+import java.lang.reflect.Field;
 import java.net.MalformedURLException;
 import java.net.URL;
 import java.util.ArrayList;
 import java.util.Collections;
 import java.util.HashMap;
@@ -37,21 +38,18 @@ import org.apache.camel.util.ReflectionHelper;
 import org.apache.camel.util.ResourceHelper;
 import org.dozer.DozerBeanMapper;
 import org.dozer.Mapper;
 import org.dozer.classmap.ClassMap;
 import org.dozer.classmap.MappingFileData;
-import org.dozer.config.BeanContainer;
 import org.dozer.config.GlobalSettings;
 import org.dozer.loader.api.BeanMappingBuilder;
 import org.dozer.loader.xml.MappingFileReader;
 import org.dozer.loader.xml.XMLParserFactory;
 import org.dozer.util.DozerClassLoader;
 import org.slf4j.Logger;
 import org.slf4j.LoggerFactory;
 
-import static org.dozer.classmap.MappingDirection.ONE_WAY;
-
 /**
  * <code>DozerTypeConverterLoader</code> provides the mechanism for registering
  * a Dozer {@link Mapper} as {@link TypeConverter} for a {@link CamelContext}.
  * <p/>
  * While a mapper can be explicitly supplied as a parameter the
@@ -110,23 +108,28 @@ public class DozerTypeConverterLoader extends ServiceSupport implements CamelCon
             ReflectionHelper.setField(field, settings, DozerThreadContextClassLoader.class.getName());
         } catch (Exception e) {
             throw new IllegalStateException("Cannot configure Dozer GlobalSettings to use CamelToDozerClassResolverAdapter as classloader due " + e.getMessage(), e);
         }
 
-        switchClassloader();
-
-        log.info("Using DozerBeanMapperConfiguration: {}", configuration);
-        DozerBeanMapper mapper = createDozerBeanMapper(configuration);
+        ClassLoader tccl = Thread.currentThread().getContextClassLoader();
+        try {
+            ClassLoader appcl = camelContext.getApplicationContextClassLoader();
+            if (appcl != null) {
+                Thread.currentThread().setContextClassLoader(appcl);
+            }
+            log.info("Using DozerBeanMapperConfiguration: {}", configuration);
+            DozerBeanMapper mapper = createDozerBeanMapper(configuration);
 
-        this.camelContext = camelContext;
-        this.mapper = mapper;
-        this.configuration = configuration;
+            this.camelContext = camelContext;
+            this.mapper = mapper;
+            this.configuration = configuration;
 
-        try {
             camelContext.addService(this);
         } catch (Exception e) {
             throw ObjectHelper.wrapRuntimeCamelException(e);
+        } finally {
+            Thread.currentThread().setContextClassLoader(tccl);
         }
     }
 
     /**
      * Creates a <code>DozerTypeConverter</code> that will wrap the the given
@@ -161,64 +164,73 @@ public class DozerTypeConverterLoader extends ServiceSupport implements CamelCon
         this.camelContext = camelContext;
         if (mapper != null) {
             this.mapper = mapper;
         }
 
-        switchClassloader();
+        ClassLoader tccl = Thread.currentThread().getContextClassLoader();
+        try {
+            ClassLoader appcl = camelContext.getApplicationContextClassLoader();
+            if (appcl != null) {
+                Thread.currentThread().setContextClassLoader(appcl);
+            }
 
-        Map<String, DozerBeanMapper> mappers = lookupDozerBeanMappers();
-        // only add if we do not already have it
-        if (mapper != null && !mappers.containsValue(mapper)) {
-            mappers.put("parameter", mapper);
-        }
+            Map<String, DozerBeanMapper> mappers = lookupDozerBeanMappers();
+            // only add if we do not already have it
+            if (mapper != null && !mappers.containsValue(mapper)) {
+                mappers.put("parameter", mapper);
+            }
 
-        // add any dozer bean mapper configurations
-        Map<String, DozerBeanMapperConfiguration> configurations = lookupDozerBeanMapperConfigurations();
-        if (configurations != null && configuration != null) {
-            // filter out existing configuration, as we do not want to use it twice
-            String key = null;
-            for (Map.Entry<String, DozerBeanMapperConfiguration> entry : configurations.entrySet()) {
-                if (entry.getValue() == configuration) {
-                    key = entry.getKey();
-                    break;
+            // add any dozer bean mapper configurations
+            Map<String, DozerBeanMapperConfiguration> configurations = lookupDozerBeanMapperConfigurations();
+            if (configurations != null && configuration != null) {
+                // filter out existing configuration, as we do not want to use it twice
+                String key = null;
+                for (Map.Entry<String, DozerBeanMapperConfiguration> entry : configurations.entrySet()) {
+                    if (entry.getValue() == configuration) {
+                        key = entry.getKey();
+                        break;
+                    }
+                }
+                if (key != null) {
+                    configurations.remove(key);
                 }
             }
-            if (key != null) {
-                configurations.remove(key);
+
+            if (configurations != null) {
+                if (configurations.size() > 1) {
+                    log.warn("Loaded " + configurations.size() + " Dozer configurations from Camel registry."
+                            + " Dozer is most efficient when there is a single mapper instance. Consider amalgamating instances.");
+                }
+                for (Map.Entry<String, DozerBeanMapperConfiguration> entry : configurations.entrySet()) {
+                    String id = entry.getKey();
+                    DozerBeanMapper beanMapper = createDozerBeanMapper(entry.getValue());
+                    // only add if we do not already have it
+                    if (!mappers.containsValue(beanMapper)) {
+                        mappers.put(id, beanMapper);
+                    }
+                }
             }
-        }
 
-        if (configurations != null) {
-            if (configurations.size() > 1) {
-                log.warn("Loaded " + configurations.size() + " Dozer configurations from Camel registry."
+            if (mappers.size() > 1) {
+                log.warn("Loaded " + mappers.size() + " Dozer mappers from Camel registry."
                         + " Dozer is most efficient when there is a single mapper instance. Consider amalgamating instances.");
+            } else if (mappers.size() == 0) {
+                log.warn("No Dozer mappers found in Camel registry. You should add Dozer mappers as beans to the registry of the type: "
+                        + DozerBeanMapper.class.getName());
             }
-            for (Map.Entry<String, DozerBeanMapperConfiguration> entry : configurations.entrySet()) {
-                String id = entry.getKey();
-                DozerBeanMapper beanMapper = createDozerBeanMapper(entry.getValue());
-                // only add if we do not already have it
-                if (!mappers.containsValue(beanMapper)) {
-                    mappers.put(id, beanMapper);
-                }
-            }
-        }
 
-        if (mappers.size() > 1) {
-            log.warn("Loaded " + mappers.size() + " Dozer mappers from Camel registry."
-                    + " Dozer is most efficient when there is a single mapper instance. Consider amalgamating instances.");
-        } else if (mappers.size() == 0) {
-            log.warn("No Dozer mappers found in Camel registry. You should add Dozer mappers as beans to the registry of the type: "
-                    + DozerBeanMapper.class.getName());
-        }
 
+            TypeConverterRegistry registry = camelContext.getTypeConverterRegistry();
+            for (Map.Entry<String, DozerBeanMapper> entry : mappers.entrySet()) {
+                String mapperId = entry.getKey();
+                DozerBeanMapper dozer = entry.getValue();
+                List<ClassMap> all = loadMappings(camelContext, mapperId, dozer);
+                registerClassMaps(registry, mapperId, dozer, all);
+            }
 
-        TypeConverterRegistry registry = camelContext.getTypeConverterRegistry();
-        for (Map.Entry<String, DozerBeanMapper> entry : mappers.entrySet()) {
-            String mapperId = entry.getKey();
-            DozerBeanMapper dozer = entry.getValue();
-            List<ClassMap> all = loadMappings(camelContext, mapperId, dozer);
-            registerClassMaps(registry, mapperId, dozer, all);
+        } finally {
+            Thread.currentThread().setContextClassLoader(tccl);
         }
     }
 
     /**
      * Creates a {@link DozerBeanMapper} from the given configuration.
@@ -357,26 +369,10 @@ public class DozerTypeConverterLoader extends ServiceSupport implements CamelCon
 
     public void setMapper(DozerBeanMapper mapper) {
         this.mapper = mapper;
     }
 
-    protected void switchClassloader() {
-        // must set class loader before we create bean mapper
-        DozerClassLoader oldCl = BeanContainer.getInstance().getClassLoader();
-        log.info("Current Dozer container-wide classloader: {}.", oldCl);
-        
-        // if the classloader we're replacing is not a ThreadContextClassLoader, pass it on as delegate target
-        // otherwise, don't do anything as we have
-        if (!(oldCl instanceof DozerThreadContextClassLoader)) {
-            DozerThreadContextClassLoader newCl = new DozerThreadContextClassLoader(oldCl);
-            BeanContainer.getInstance().setClassLoader(newCl);
-            log.info("Switched Dozer container-wide classloader from: {} to {} (where the latter delegates to former).", oldCl, newCl);
-        } else {
-            log.info("Dozer container-wide classloader already set: {}. No switch necessary.", oldCl);
-        }
-    }
-    
     protected static URL loadMappingFile(ClassResolver classResolver, String mappingFile) {
         URL url = null;
         try {
             url = ResourceHelper.resolveResourceAsUrl(classResolver, mappingFile);
         } catch (MalformedURLException e) {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
