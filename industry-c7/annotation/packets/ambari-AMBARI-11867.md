# Annotation packet: AMBARI-11867  (ambari)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
JPA persistence failure when adding hosts to an existing config group

Adding a host to an existing config group results in a JPA exception. 
This breaks blueprint provisioning/scaling where a host with host group configuration is added to a cluster.
The BP processor is adding a host to a ConfigGroup instance and persisting it:
group.addHost(host)
group.persist();
To reproduce, provision a cluster with a master and a slave. For the slave, add a host group scoped configuration (one property is sufficient). After the cluster is provisioned, add a new slave to the cluster. This will result in the below exception.
This may also occur when provisioning a large cluster where not all slaves have joined the cluster when the config group is created and with very large clusters it may occur even of all hosts have already registered with the cluster prior to provisioning.
avax.persistence.PersistenceException: java.util.ConcurrentModificationException
at org.eclipse.persistence.internal.jpa.QueryImpl.executeUpdate(QueryImpl.java:308)
at org.apache.ambari.server.orm.dao.DaoUtils.executeUpdate(DaoUtils.java:88)
at org.apache.ambari.server.orm.dao.ConfigGroupConfigMappingDAO.removeAllByGroup(ConfigGroupConfigMappingDAO.java:101)
at org.apache.ambari.server.orm.AmbariJpaLocalTxnInterceptor.invoke(AmbariJpaLocalTxnInterceptor.java:60)
at org.apache.ambari.server.state.configgroup.ConfigGroupImpl.persistConfigMapping(ConfigGroupImpl.java:403)
at org.apache.ambari.server.orm.AmbariJpaLocalTxnInterceptor.invoke(AmbariJpaLocalTxnInterceptor.java:60)
at org.apache.ambari.server.state.configgroup.ConfigGroupImpl.saveIfPersisted(ConfigGroupImpl.java:460)
at org.apache.ambari.server.orm.AmbariJpaLocalTxnInterceptor.invoke(AmbariJpaLocalTxnInterceptor.java:68)
at org.apache.ambari.server.state.configgroup.ConfigGroupImpl.persist(ConfigGroupImpl.java:330)
at org.apache.ambari.server.topology.AmbariContext.addHostToExistingConfigGroups(AmbariContext.java:409)
at org.apache.ambari.server.topology.AmbariContext.registerHostWithConfigGroup(AmbariContext.java:285)
at org.apache.ambari.server.topology.HostRequest$RegisterWithConfigGroupTask.run(HostRequest.java:450)
at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1142)
at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:617)
at java.lang.Thread.run(Thread.java:745)
Caused by: java.util.ConcurrentModificationException
at java.util.IdentityHashMap$IdentityHashMapIterator.nextIndex(IdentityHashMap.java:734)
at java.util.IdentityHashMap$KeyIterator.next(IdentityHashMap.java:825)
at org.eclipse.persistence.internal.sessions.CollectionChangeRecord.mergeRecord(CollectionChangeRecord.java:260)
at org.eclipse.persistence.internal.sessions.ObjectChangeSet.mergeObjectChanges(ObjectChangeSet.java:740)
at org.eclipse.persistence.internal.sessions.UnitOfWorkChangeSet.mergeObjectChanges(UnitOfWorkChangeSet.java:492)
at org.eclipse.persistence.internal.sessions.UnitOfWorkChangeSet.mergeUnitOfWorkChangeSet(UnitOfWorkChangeSet.java:509)
at org.eclipse.persistence.internal.sessions.RepeatableWriteUnitOfWork.writeChanges(RepeatableWriteUnitOfWork.java:466)
at org.eclipse.persistence.internal.jpa.EntityManagerImpl.flush(EntityManagerImpl.java:863)
at org.eclipse.persistence.internal.jpa.QueryImpl.performPreQueryFlush(QueryImpl.java:963)
at org.eclipse.persistence.internal.jpa.QueryImpl.executeUpdate(QueryImpl.java:296)
... 14 more
Exception in thread "pool-3-thread-1" java.lang.RuntimeException: Unable to register config group for host: c6404.ambari.apache.org
at org.apache.ambari.server.topology.AmbariContext.registerHostWithConfigGroup(AmbariContext.java:290)
at org.apache.ambari.server.topology.HostRequest$RegisterWithConfigGroupTask.run(HostRequest.java:450)
at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1142)
at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:617)
at java.lang.Thread.run(Thread.java:745)
```

## Fix commit message(s)

`043e35a6b5bf`

```
AMBARI-11867.  Fix adding of host to config group during blueprint provisioning
```

## Files the fix changed

Snapshot holds 2,719 non-test source files. The fix changed 4 file(s); 3 of them are non-test source files (listed below as gold).

- `ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroup.java`
- `ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroupImpl.java`
- `ambari-server/src/main/java/org/apache/ambari/server/topology/AmbariContext.java`

## The fix diff

### `ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroup.java`

```diff
diff --git a/ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroup.java b/ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroup.java
index 4c806e5b38..7ed7ba5d9e 100644
--- a/ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroup.java
+++ b/ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroup.java
@@ -16,11 +16,10 @@
  * limitations under the License.
  */
 
 package org.apache.ambari.server.state.configgroup;
 
-import com.google.inject.persist.Transactional;
 import org.apache.ambari.server.AmbariException;
 import org.apache.ambari.server.controller.ConfigGroupResponse;
 import org.apache.ambari.server.state.Config;
 import org.apache.ambari.server.state.Host;
 
@@ -94,13 +93,17 @@ public interface ConfigGroup {
 
   /**
    * Persist the Config group along with the related host and config mapping
    * entities to the persistence store
    */
-  @Transactional
   void persist();
 
+  /**
+   * Persist the host mapping entity to the persistence store
+   */
+  void persistHostMapping();
+
   /**
    * Delete config group and the related host and config mapping
    * entities from the persistence store
    */
   public void delete();
@@ -128,11 +131,10 @@ public interface ConfigGroup {
   public ConfigGroupResponse convertToResponse() throws AmbariException;
 
   /**
    * Refresh Config group and the host and config mappings for the group
    */
-  @Transactional
   public void refresh();
 
   /**
    * Reassign the set of hosts associated with this config group
    * @param hosts
```

### `ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroupImpl.java`

```diff
diff --git a/ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroupImpl.java b/ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroupImpl.java
index d32273510d..3b83f61a1e 100644
--- a/ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroupImpl.java
+++ b/ambari-server/src/main/java/org/apache/ambari/server/state/configgroup/ConfigGroupImpl.java
@@ -359,11 +359,11 @@ public class ConfigGroupImpl implements ConfigGroup {
    * Persist host mapping
    *
    * @throws Exception
    */
   @Transactional
-  void persistHostMapping() {
+  public void persistHostMapping() {
     if (isPersisted) {
       // Delete existing mappings and create new ones
       configGroupHostMappingDAO.removeAllByGroup(configGroupEntity.getGroupId());
       configGroupEntity.getConfigGroupHostMappingEntities().clear();
     }
```

### `ambari-server/src/main/java/org/apache/ambari/server/topology/AmbariContext.java`

```diff
diff --git a/ambari-server/src/main/java/org/apache/ambari/server/topology/AmbariContext.java b/ambari-server/src/main/java/org/apache/ambari/server/topology/AmbariContext.java
index 091018ae93..42676aab13 100644
--- a/ambari-server/src/main/java/org/apache/ambari/server/topology/AmbariContext.java
+++ b/ambari-server/src/main/java/org/apache/ambari/server/topology/AmbariContext.java
@@ -403,17 +403,21 @@ public class AmbariContext {
     Map<Long, ConfigGroup> configGroups = cluster.getConfigGroups();
     String qualifiedGroupName = getConfigurationGroupName(topology.getBlueprint().getName(), groupName);
     for (ConfigGroup group : configGroups.values()) {
       if (group.getName().equals(qualifiedGroupName)) {
         try {
-          group.addHost(clusters.getHost(hostName));
-          group.persist();
+          Host host = clusters.getHost(hostName);
           addedHost = true;
+          if (! group.getHosts().containsKey(host.getHostId())) {
+            group.addHost(host);
+            group.persistHostMapping();
+          }
+
         } catch (AmbariException e) {
           // shouldn't occur, this host was just added to the cluster
           throw new RuntimeException(String.format(
-              "Unable to obtain newly created host '%s' from cluster '%s'", hostName, topology.getClusterName()));
+              "An error occurred while registering host '%s' with config group '%s' ", hostName, group.getName()), e);
         }
       }
     }
     return addedHost;
   }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
