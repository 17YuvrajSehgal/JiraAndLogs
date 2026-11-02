# Annotation packet: WFLY-11010  (wildfly)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Document 2lc/JTA integration properties and add better detection of ehcache/JTA platform class use

Document the "wildfly.jpa.regionfactory" and "wildfly.jpa.jtaplatform" properties for Hibernate ORM 5.3+ integration.

Also automatically treat "wildfly.jpa.regionfactory" as false if [ehcache is being used|http://www.ehcache.org/documentation/2.7/integrations/hibernate.html] (e.g. check if the hibernate.cache.region.factory_class value starts with "net.sf.ehcache").  This should help applications that have configured to use Ehcache.

Also automatically treat "wildfly.jpa.jtaplatform" as false if the application sets "hibernate.transaction.jta.platform".  This should help applications that have configured the transaction platform class.
```

## Fix commit message(s)

`0d151a1a50f3`

```
WFLY-11010 Document 2lc/JTA integration properties and add better detection of ehcache/JTAFactoryClass use
```

## Files the fix changed

Snapshot holds 4,030 non-test source files. The fix changed 4 file(s); 3 of them are non-test source files (listed below as gold).

- `jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/HibernatePersistenceProviderAdaptor.java`
- `jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/ServiceContributorImpl.java`
- `jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/WildFlyCustomRegionFactoryInitiator.java`

## The fix diff

### `jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/HibernatePersistenceProviderAdaptor.java`

```diff
diff --git a/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/HibernatePersistenceProviderAdaptor.java b/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/HibernatePersistenceProviderAdaptor.java
index 33b73b1e0c..7943ed2b14 100644
--- a/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/HibernatePersistenceProviderAdaptor.java
+++ b/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/HibernatePersistenceProviderAdaptor.java
@@ -47,10 +47,11 @@ public class HibernatePersistenceProviderAdaptor implements PersistenceProviderA
 
     public static final String NAMING_STRATEGY_JPA_COMPLIANT_IMPL = "org.hibernate.boot.model.naming.ImplicitNamingStrategyJpaCompliantImpl";
     private volatile Platform platform;
     private static final String SHARED_CACHE_MODE = "javax.persistence.sharedCache.mode";
     private static final String NONE = SharedCacheMode.NONE.name();
+    private static final String UNSPECIFIED = SharedCacheMode.UNSPECIFIED.name();
     private static final String HIBERNATE_EXTENDED_BEANMANAGER = "org.hibernate.jpa.event.spi.jpa.ExtendedBeanManager";
 
     @Override
     public void injectJtaManager(JtaManager jtaManager) {
     }
@@ -101,11 +102,13 @@ public class HibernatePersistenceProviderAdaptor implements PersistenceProviderA
             pu.setSharedCacheMode(SharedCacheMode.NONE);
         }
         // check if 2lc is explicitly disabled which takes precedence over other settings
         boolean sharedCacheDisabled = SharedCacheMode.NONE.equals(pu.getSharedCacheMode())
                 ||
-                NONE.equals(sharedCacheMode);
+                NONE.equals(sharedCacheMode) ||
+                SharedCacheMode.UNSPECIFIED.equals(pu.getSharedCacheMode()) ||
+                UNSPECIFIED.equals(sharedCacheMode);
         if (!sharedCacheDisabled &&
                 (null == properties.getProperty(AvailableSettings.USE_SECOND_LEVEL_CACHE) ||
                         Boolean.parseBoolean(properties.getProperty(AvailableSettings.USE_SECOND_LEVEL_CACHE))))
                 {
             HibernateSecondLevelCache.addSecondLevelCacheDependencies(pu.getProperties(), pu.getScopedPersistenceUnitName());
@@ -114,10 +117,11 @@ public class HibernatePersistenceProviderAdaptor implements PersistenceProviderA
             JPA_LOGGER.tracef("second level cache disabled for %s, pu %s property = %s, pu.getSharedCacheMode = %s",
                     pu.getScopedPersistenceUnitName(),
                     SHARED_CACHE_MODE,
                     sharedCacheMode,
                     pu.getSharedCacheMode().toString());
+            pu.setSharedCacheMode(SharedCacheMode.NONE);  // ensure that Hibernate doesn't try to use the 2lc for UNSPECIFIED
         }
     }
 
     private void putPropertyIfAbsent(PersistenceUnitMetadata pu, Map properties, String property, Object value) {
         if (!pu.getProperties().containsKey(property)) {
```

### `jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/ServiceContributorImpl.java`

```diff
diff --git a/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/ServiceContributorImpl.java b/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/ServiceContributorImpl.java
index a91534ba2c..9e7597c7f7 100644
--- a/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/ServiceContributorImpl.java
+++ b/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/ServiceContributorImpl.java
@@ -14,10 +14,12 @@
  * See the License for the specific language governing permissions and
  * limitations under the License.
  */
 package org.jboss.as.jpa.hibernate5.service;
 
+import static org.jboss.as.jpa.hibernate5.JpaLogger.JPA_LOGGER;
+
 import org.hibernate.boot.registry.StandardServiceRegistryBuilder;
 import org.hibernate.service.spi.ServiceContributor;
 
 /**
  * Contribute specialized Hibernate Service impls
@@ -26,26 +28,39 @@ import org.hibernate.service.spi.ServiceContributor;
  * @author Scott Marlow
  */
 public class ServiceContributorImpl implements ServiceContributor {
     private static final String CONTROLJTAINTEGRATION = "wildfly.jpa.jtaplatform"; // these properties are documented in org.jboss.as.jpa.config.Configuration
     private static final String CONTROL2LCINTEGRATION = "wildfly.jpa.regionfactory";
+    private static final String TRANSACTION_PLATFORM = "hibernate.transaction.jta.platform";
+    private static final String EHCACHE = "ehcache";
+    private static final String HIBERNATE_REGION_FACTORY_CLASS = "hibernate.cache.region.factory_class";
 
     @Override
     public void contribute(StandardServiceRegistryBuilder serviceRegistryBuilder) {
         // note that the following deprecated getSettings() is agreed to be replaced with method that returns immutable copy of configuration settings.
         final Object jtaPlatformInitiatorEnabled = serviceRegistryBuilder.getSettings().getOrDefault(CONTROLJTAINTEGRATION, true);
 
-        if (jtaPlatformInitiatorEnabled == null ||
+        if (serviceRegistryBuilder.getSettings().get(TRANSACTION_PLATFORM) != null) {
+            // applications that already specify the transaction platform property which will override the WildFlyCustomJtaPlatform.
+            JPA_LOGGER.tracef("ServiceContributorImpl#contribute application configured the JTA Platform to be used instead of WildFlyCustomJtaPlatform (%s=%s)",
+                    TRANSACTION_PLATFORM, serviceRegistryBuilder.getSettings().get(TRANSACTION_PLATFORM));
+        } else if (jtaPlatformInitiatorEnabled == null ||
                 (jtaPlatformInitiatorEnabled instanceof Boolean && ((Boolean) jtaPlatformInitiatorEnabled).booleanValue()) ||
                 Boolean.parseBoolean(jtaPlatformInitiatorEnabled.toString())) {
+            // use WildFlyCustomJtaPlatform unless they explicitly set wildfly.jpa.jtaplatform to false.
+            JPA_LOGGER.tracef("ServiceContributorImpl#contribute application will use WildFlyCustomJtaPlatform");
             serviceRegistryBuilder.addInitiator(new WildFlyCustomJtaPlatformInitiator());
         }
 
         final Object regionFactoryInitiatorEnabled = serviceRegistryBuilder.getSettings().getOrDefault(CONTROL2LCINTEGRATION, true);
-
-        if (regionFactoryInitiatorEnabled == null ||
+        final Object regionFactory = serviceRegistryBuilder.getSettings().get(HIBERNATE_REGION_FACTORY_CLASS);
+        if ((regionFactory instanceof String) && (((String) regionFactory)).contains(EHCACHE)) {
+            JPA_LOGGER.tracef("ServiceContributorImpl#contribute application is using Ehcache via regionFactory=%s",
+                    regionFactory);
+        } else if (regionFactoryInitiatorEnabled == null ||
                 (regionFactoryInitiatorEnabled instanceof Boolean && ((Boolean) regionFactoryInitiatorEnabled).booleanValue()) ||
                 Boolean.parseBoolean(regionFactoryInitiatorEnabled.toString())) {
+            JPA_LOGGER.tracef("ServiceContributorImpl#contribute adding ORM initiator for 2lc region factory");
             serviceRegistryBuilder.addInitiator(new WildFlyCustomRegionFactoryInitiator());
         }
     }
 }
```

### `jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/WildFlyCustomRegionFactoryInitiator.java`

```diff
diff --git a/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/WildFlyCustomRegionFactoryInitiator.java b/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/WildFlyCustomRegionFactoryInitiator.java
index 56558c446e..1610b5e6d8 100644
--- a/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/WildFlyCustomRegionFactoryInitiator.java
+++ b/jpa/hibernate5_3/src/main/java/org/jboss/as/jpa/hibernate5/service/WildFlyCustomRegionFactoryInitiator.java
@@ -16,10 +16,11 @@
  */
 package org.jboss.as.jpa.hibernate5.service;
 
 import static org.hibernate.cfg.AvailableSettings.JPA_SHARED_CACHE_MODE;
 import static org.hibernate.cfg.AvailableSettings.USE_SECOND_LEVEL_CACHE;
+import static org.jboss.as.jpa.hibernate5.JpaLogger.JPA_LOGGER;
 
 import java.util.Map;
 
 import org.hibernate.cache.internal.NoCachingRegionFactory;
 import org.hibernate.cache.internal.RegionFactoryInitiator;
@@ -34,27 +35,34 @@ public class WildFlyCustomRegionFactoryInitiator extends RegionFactoryInitiator
 
     private static final String HIBERNATE_REGION_FACTORY_CLASS = "hibernate.cache.region.factory_class";
     private static final String V53_INFINISPAN_REGION_FACTORY = "org.infinispan.hibernate.cache.v53.InfinispanRegionFactory";
     private static final String UNSPECIFIED = "UNSPECIFIED";
     private static final String NONE = "NONE";
+
     @Override
     protected RegionFactory resolveRegionFactory(Map configurationValues, ServiceRegistryImplementor registry) {
         final Object useSecondLevelCache = configurationValues.get(USE_SECOND_LEVEL_CACHE);
         final String jpaSharedCodeModeValue = configurationValues.get(JPA_SHARED_CACHE_MODE) != null ? configurationValues.get(JPA_SHARED_CACHE_MODE).toString() : UNSPECIFIED;
-
+        final Object regionFactory = configurationValues.get(HIBERNATE_REGION_FACTORY_CLASS);
 
         // treat Hibernate 2lc as off, if not specified.
         // Note that Hibernate 2lc in 5.1.x, defaults to disabled, so this code is only needed in 5.3.x+.
         if(Boolean.parseBoolean((String)useSecondLevelCache)) {
+            JPA_LOGGER.tracef("WildFlyCustomRegionFactoryInitiator#resolveRegionFactory using %s for 2lc, useSecondLevelCache=%s, jpaSharedCodeModeValue=%s, regionFactory=%s",
+                    V53_INFINISPAN_REGION_FACTORY, useSecondLevelCache,jpaSharedCodeModeValue, regionFactory);
             configurationValues.put(HIBERNATE_REGION_FACTORY_CLASS, V53_INFINISPAN_REGION_FACTORY);
             return super.resolveRegionFactory(configurationValues, registry);
         } else if(UNSPECIFIED.equals(jpaSharedCodeModeValue)
              || NONE.equals(jpaSharedCodeModeValue)) {
             // explicitly disable 2lc cache
+            JPA_LOGGER.tracef("WildFlyCustomRegionFactoryInitiator#resolveRegionFactory not using a 2lc, useSecondLevelCache=%s, jpaSharedCodeModeValue=%s, regionFactory=%s",
+                    useSecondLevelCache,jpaSharedCodeModeValue, regionFactory);
             return NoCachingRegionFactory.INSTANCE;
         }
         else {
+            JPA_LOGGER.tracef("WildFlyCustomRegionFactoryInitiator#resolveRegionFactory using %s for 2lc, useSecondLevelCache=%s, jpaSharedCodeModeValue=%s, regionFactory=%s",
+                    V53_INFINISPAN_REGION_FACTORY, useSecondLevelCache,jpaSharedCodeModeValue, regionFactory);
             configurationValues.put(HIBERNATE_REGION_FACTORY_CLASS, V53_INFINISPAN_REGION_FACTORY);
             return super.resolveRegionFactory(configurationValues, registry);
         }
     }
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
