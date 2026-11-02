# Annotation packet: AMBARI-12280  (ambari)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
HiveServer2 upgrade/downgrade should deregister old server after new one is started

During upgrade/downgrade, the deregister is happening before the new HS2 is started. This can lead to a case where there is no HS2 up and running. The order needs to be fixed, to first start target version of HS2 and then do the deregister.
1. Switch hive-server2 to the new software version, start the new process, and deregister the old version of hive-server2:

Since the current version would have changed before hive version is obtained for deregister command, the version should be obtained using the HDP versioned path.
/usr/hdp/$HDP_VERSION/hive/bin/hive --version 
It will be safer to use the full path to hive for this, instead of relying on the $PATH variable setting.
```

## Fix commit message(s)

`23cdd769ae1e`

```
AMBARI-12280. HiveServer2 upgrade/downgrade should deregister old server after new one is started (srimanth)
```

## Files the fix changed

Snapshot holds 2,726 non-test source files. The fix changed 11 file(s); 9 of them are non-test source files (listed below as gold).

- `ambari-common/src/main/python/resource_management/libraries/functions/hdp_select.py`
- `ambari-common/src/main/python/resource_management/libraries/script/script.py`
- `ambari-server/src/main/java/org/apache/ambari/server/controller/internal/UpgradeResourceProvider.java`
- `ambari-server/src/main/java/org/apache/ambari/server/orm/dao/UpgradeDAO.java`
- `ambari-server/src/main/java/org/apache/ambari/server/orm/entities/UpgradeEntity.java`
- `ambari-server/src/main/java/org/apache/ambari/server/state/UpgradeContext.java`
- `ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server.py`
- `ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server_upgrade.py`
- `ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py`

## The fix diff

### `ambari-common/src/main/python/resource_management/libraries/functions/hdp_select.py`

```diff
diff --git a/ambari-common/src/main/python/resource_management/libraries/functions/hdp_select.py b/ambari-common/src/main/python/resource_management/libraries/functions/hdp_select.py
index 4583808efa..d0ee9ad14a 100644
--- a/ambari-common/src/main/python/resource_management/libraries/functions/hdp_select.py
+++ b/ambari-common/src/main/python/resource_management/libraries/functions/hdp_select.py
@@ -24,10 +24,11 @@ from resource_management.core.exceptions import Fail
 from resource_management.core.resources.system import Execute
 from resource_management.libraries.functions.default import default
 from resource_management.libraries.functions.get_hdp_version import get_hdp_version
 from resource_management.libraries.script.script import Script
 from resource_management.core.shell import call
+from resource_management.libraries.functions.version import format_hdp_stack_version
 
 # hdp-select set oozie-server 2.2.0.0-1234
 TEMPLATE = ('hdp-select', 'set')
 
 # a mapping of Ambari server role to hdp-select component name for all
@@ -147,22 +148,21 @@ def get_role_component_current_hdp_version():
       hdp_select_component, current_hdp_version))
 
   return current_hdp_version
 
 
-def get_hadoop_dir(target, force_latest_on_upgrade=False, upgrade_stack_only=False):
+def get_hadoop_dir(target, force_latest_on_upgrade=False):
   """
   Return the hadoop shared directory in the following override order
   1. Use default for 2.1 and lower
   2. If 2.2 and higher, use /usr/hdp/current/hadoop-client/{target}
   3. If 2.2 and higher AND for an upgrade, use /usr/hdp/<version>/hadoop/{target}.
   However, if the upgrade has not yet invoked hdp-select, return the current
   version of the component.
   :target: the target directory
   :force_latest_on_upgrade: if True, then this will return the "current" directory
   without the HDP version built into the path, such as /usr/hdp/current/hadoop-client
-  :upgrade_stack_only: if True, provides upgrade stack target if present and not current
   """
 
   if not target in HADOOP_DIR_DEFAULTS:
     raise Fail("Target {0} not defined".format(target))
 
@@ -184,21 +184,44 @@ def get_hadoop_dir(target, force_latest_on_upgrade=False, upgrade_stack_only=Fal
         stack_version = stack_info[1]
 
         # determine if hdp-select has been run and if not, then use the current
         # hdp version until this component is upgraded
         current_hdp_version = get_role_component_current_hdp_version()
-        if current_hdp_version is not None and stack_version != current_hdp_version and not upgrade_stack_only:
+        if current_hdp_version is not None and stack_version != current_hdp_version:
           stack_version = current_hdp_version
 
         if target == "home":
           # home uses a different template
           hadoop_dir = HADOOP_HOME_DIR_TEMPLATE.format(stack_version, "hadoop")
         else:
           hadoop_dir = HADOOP_DIR_TEMPLATE.format(stack_version, "hadoop", target)
 
   return hadoop_dir
 
+def get_hadoop_dir_for_stack_version(target, stack_version):
+  """
+  Return the hadoop shared directory for the provided stack version. This is necessary
+  when folder paths of downgrade-source stack-version are needed after hdp-select. 
+  :target: the target directory
+  :stack_version: stack version to get hadoop dir for
+  """
+
+  if not target in HADOOP_DIR_DEFAULTS:
+    raise Fail("Target {0} not defined".format(target))
+
+  hadoop_dir = HADOOP_DIR_DEFAULTS[target]
+
+  formatted_stack_version = format_hdp_stack_version(stack_version)
+  if Script.is_hdp_stack_greater_or_equal_to(formatted_stack_version, "2.2"):
+    # home uses a different template
+    if target == "home":
+      hadoop_dir = HADOOP_HOME_DIR_TEMPLATE.format(stack_version, "hadoop")
+    else:
+      hadoop_dir = HADOOP_DIR_TEMPLATE.format(stack_version, "hadoop", target)
+
+  return hadoop_dir
+
 
 def _get_upgrade_stack():
   """
   Gets the stack name and stack version if an upgrade is currently in progress.
   :return:  the stack name and stack version as a tuple, or None if an
```

### `ambari-common/src/main/python/resource_management/libraries/script/script.py`

```diff
diff --git a/ambari-common/src/main/python/resource_management/libraries/script/script.py b/ambari-common/src/main/python/resource_management/libraries/script/script.py
index b074fe5db5..c422ac8b69 100644
--- a/ambari-common/src/main/python/resource_management/libraries/script/script.py
+++ b/ambari-common/src/main/python/resource_management/libraries/script/script.py
@@ -302,15 +302,25 @@ class Script(object):
     Gets whether the hostLevelParams/stack_version, after being normalized,
     is greater than or equal to the specified stack version
     :param compare_to_version: the version to compare to
     :return: True if the command's stack is greater than the specified version
     """
-    hdp_stack_version = Script.get_hdp_stack_version()
-    if hdp_stack_version is None or hdp_stack_version == "":
+    return Script.is_hdp_stack_greater_or_equal_to(Script.get_hdp_stack_version(), compare_to_version)
+
+  @staticmethod
+  def is_hdp_stack_greater_or_equal_to(formatted_hdp_stack_version, compare_to_version):
+    """
+    Gets whether the provided formatted_hdp_stack_version (normalized)
+    is greater than or equal to the specified stack version
+    :param formatted_hdp_stack_version: the version of stack to compare
+    :param compare_to_version: the version of stack to compare to
+    :return: True if the command's stack is greater than the specified version
+    """
+    if formatted_hdp_stack_version is None or formatted_hdp_stack_version == "":
       return False
 
-    return compare_versions(hdp_stack_version, compare_to_version) >= 0
+    return compare_versions(formatted_hdp_stack_version, compare_to_version) >= 0
 
   @staticmethod
   def is_hdp_stack_less_than(compare_to_version):
     """
     Gets whether the hostLevelParams/stack_version, after being normalized,
```

### `ambari-server/src/main/java/org/apache/ambari/server/controller/internal/UpgradeResourceProvider.java`

```diff
diff --git a/ambari-server/src/main/java/org/apache/ambari/server/controller/internal/UpgradeResourceProvider.java b/ambari-server/src/main/java/org/apache/ambari/server/controller/internal/UpgradeResourceProvider.java
index 65e9eaf231..cd0a709d91 100644
--- a/ambari-server/src/main/java/org/apache/ambari/server/controller/internal/UpgradeResourceProvider.java
+++ b/ambari-server/src/main/java/org/apache/ambari/server/controller/internal/UpgradeResourceProvider.java
@@ -139,10 +139,11 @@ public class UpgradeResourceProvider extends AbstractControllerResourceProvider
   private static final String COMMAND_PARAM_CLUSTER_NAME = "clusterName";
   private static final String COMMAND_PARAM_DIRECTION = "upgrade_direction";
   private static final String COMMAND_PARAM_RESTART_TYPE = "restart_type";
   private static final String COMMAND_PARAM_TASKS = "tasks";
   private static final String COMMAND_PARAM_STRUCT_OUT = "structured_out";
+  private static final String COMMAND_DOWNGRADE_FROM_VERSION = "downgrade_from_version";
 
   /**
    * The original "current" stack of the cluster before the upgrade started.
    * This is the same regardless of whether the current direction is
    * {@link Direction#UPGRADE} or {@link Direction#DOWNGRADE}.
@@ -567,10 +568,19 @@ public class UpgradeResourceProvider extends AbstractControllerResourceProvider
     }
 
     UpgradeContext ctx = new UpgradeContext(resolver, sourceStackId, targetStackId, version,
         direction);
 
+    if (direction.isDowngrade()) {
+      if (requestMap.containsKey(UPGRADE_FROM_VERSION)) {
+        ctx.setDowngradeFromVersion((String) requestMap.get(UPGRADE_FROM_VERSION));
+      } else {
+        UpgradeEntity lastUpgradeItemForCluster = s_upgradeDAO.findLastUpgradeForCluster(cluster.getClusterId());
+        ctx.setDowngradeFromVersion(lastUpgradeItemForCluster.getToVersion());
+      }
+    }
+
     List<UpgradeGroupHolder> groups = s_upgradeHelper.createSequence(pack, ctx);
 
     if (groups.isEmpty()) {
       throw new AmbariException("There are no groupings available");
     }
@@ -842,10 +852,11 @@ public class UpgradeResourceProvider extends AbstractControllerResourceProvider
     params.put(COMMAND_PARAM_TASKS, entity.getTasks());
     params.put(COMMAND_PARAM_VERSION, context.getVersion());
     params.put(COMMAND_PARAM_DIRECTION, context.getDirection().name().toLowerCase());
     params.put(COMMAND_PARAM_ORIGINAL_STACK, context.getOriginalStackId().getStackId());
     params.put(COMMAND_PARAM_TARGET_STACK, context.getTargetStackId().getStackId());
+    params.put(COMMAND_DOWNGRADE_FROM_VERSION, context.getDowngradeFromVersion());
 
     // Because custom task may end up calling a script/function inside a
     // service, it is necessary to set the
     // service_package_folder and hooks_folder params.
     AmbariMetaInfo ambariMetaInfo = s_metaProvider.get();
@@ -917,10 +928,11 @@ public class UpgradeResourceProvider extends AbstractControllerResourceProvider
     restartCommandParams.put(COMMAND_PARAM_RESTART_TYPE, "rolling_upgrade");
     restartCommandParams.put(COMMAND_PARAM_VERSION, context.getVersion());
     restartCommandParams.put(COMMAND_PARAM_DIRECTION, context.getDirection().name().toLowerCase());
     restartCommandParams.put(COMMAND_PARAM_ORIGINAL_STACK,context.getOriginalStackId().getStackId());
     restartCommandParams.put(COMMAND_PARAM_TARGET_STACK, context.getTargetStackId().getStackId());
+    restartCommandParams.put(COMMAND_DOWNGRADE_FROM_VERSION, context.getDowngradeFromVersion());
 
     ActionExecutionContext actionContext = new ActionExecutionContext(cluster.getClusterName(),
         "RESTART", filters, restartCommandParams);
     actionContext.setTimeout(Short.valueOf(s_configuration.getDefaultAgentTaskTimeout(false)));
     actionContext.setIgnoreMaintenance(true);
@@ -966,10 +978,11 @@ public class UpgradeResourceProvider extends AbstractControllerResourceProvider
     Map<String, String> commandParams = getNewParameterMap();
     commandParams.put(COMMAND_PARAM_VERSION, context.getVersion());
     commandParams.put(COMMAND_PARAM_DIRECTION, context.getDirection().name().toLowerCase());
     commandParams.put(COMMAND_PARAM_ORIGINAL_STACK, context.getOriginalStackId().getStackId());
     commandParams.put(COMMAND_PARAM_TARGET_STACK, context.getTargetStackId().getStackId());
+    commandParams.put(COMMAND_DOWNGRADE_FROM_VERSION, context.getDowngradeFromVersion());
 
     ActionExecutionContext actionContext = new ActionExecutionContext(cluster.getClusterName(),
         "SERVICE_CHECK", filters, commandParams);
 
     actionContext.setTimeout(Short.valueOf(s_configuration.getDefaultAgentTaskTimeout(false)));
@@ -1010,10 +1023,11 @@ public class UpgradeResourceProvider extends AbstractControllerResourceProvider
     commandParams.put(COMMAND_PARAM_CLUSTER_NAME, cluster.getClusterName());
     commandParams.put(COMMAND_PARAM_VERSION, context.getVersion());
     commandParams.put(COMMAND_PARAM_DIRECTION, context.getDirection().name().toLowerCase());
     commandParams.put(COMMAND_PARAM_ORIGINAL_STACK, context.getOriginalStackId().getStackId());
     commandParams.put(COMMAND_PARAM_TARGET_STACK, context.getTargetStackId().getStackId());
+    commandParams.put(COMMAND_DOWNGRADE_FROM_VERSION, context.getDowngradeFromVersion());
 
     String itemDetail = entity.getText();
     String stageText = StringUtils.abbreviate(entity.getText(), 255);
 
     String hostName = null;
```

### `ambari-server/src/main/java/org/apache/ambari/server/orm/dao/UpgradeDAO.java`

```diff
diff --git a/ambari-server/src/main/java/org/apache/ambari/server/orm/dao/UpgradeDAO.java b/ambari-server/src/main/java/org/apache/ambari/server/orm/dao/UpgradeDAO.java
index e6ba152834..bc0652c640 100644
--- a/ambari-server/src/main/java/org/apache/ambari/server/orm/dao/UpgradeDAO.java
+++ b/ambari-server/src/main/java/org/apache/ambari/server/orm/dao/UpgradeDAO.java
@@ -24,10 +24,11 @@ import javax.persistence.TypedQuery;
 
 import org.apache.ambari.server.orm.RequiresSession;
 import org.apache.ambari.server.orm.entities.UpgradeEntity;
 import org.apache.ambari.server.orm.entities.UpgradeGroupEntity;
 import org.apache.ambari.server.orm.entities.UpgradeItemEntity;
+import org.apache.ambari.server.state.stack.upgrade.Direction;
 import org.eclipse.persistence.config.HintValues;
 import org.eclipse.persistence.config.QueryHints;
 
 import com.google.inject.Inject;
 import com.google.inject.Provider;
@@ -153,8 +154,24 @@ public class UpgradeDAO {
     query.setHint(QueryHints.REFRESH, HintValues.TRUE);
 
     return daoUtils.selectSingle(query);
   }
 
+  /**
+   * @param requestId the request id
+   * @param stageId the stage id
+   * @return the upgrade entity, or {@code null} if not found
+   */
+  @RequiresSession
+  public UpgradeEntity findLastUpgradeForCluster(long clusterId) {
+    TypedQuery<UpgradeEntity> query = entityManagerProvider.get().createNamedQuery(
+        "UpgradeEntity.findLatestForCluster", UpgradeEntity.class);
+    query.setMaxResults(1);
+    query.setParameter("clusterId", clusterId);
+    query.setParameter("direction", Direction.UPGRADE);
+
+    query.setHint(QueryHints.REFRESH, HintValues.TRUE);
 
+    return daoUtils.selectSingle(query);
+  }
 
 }
```

### `ambari-server/src/main/java/org/apache/ambari/server/orm/entities/UpgradeEntity.java`

```diff
diff --git a/ambari-server/src/main/java/org/apache/ambari/server/orm/entities/UpgradeEntity.java b/ambari-server/src/main/java/org/apache/ambari/server/orm/entities/UpgradeEntity.java
index e8723e0d7b..802ea03b16 100644
--- a/ambari-server/src/main/java/org/apache/ambari/server/orm/entities/UpgradeEntity.java
+++ b/ambari-server/src/main/java/org/apache/ambari/server/orm/entities/UpgradeEntity.java
@@ -46,10 +46,12 @@ import org.apache.ambari.server.state.stack.upgrade.Direction;
 @NamedQueries({
   @NamedQuery(name = "UpgradeEntity.findAllForCluster",
       query = "SELECT u FROM UpgradeEntity u WHERE u.clusterId = :clusterId"),
   @NamedQuery(name = "UpgradeEntity.findUpgrade",
       query = "SELECT u FROM UpgradeEntity u WHERE u.upgradeId = :upgradeId"),
+  @NamedQuery(name = "UpgradeEntity.findLatestForCluster",
+      query = "SELECT u FROM UpgradeEntity u WHERE u.clusterId = :clusterId AND u.direction = :direction ORDER BY u.upgradeId DESC"),
 })
 public class UpgradeEntity {
 
   @Id
   @Column(name = "upgrade_id", nullable = false, insertable = true, updatable = false)
```

### `ambari-server/src/main/java/org/apache/ambari/server/state/UpgradeContext.java`

```diff
diff --git a/ambari-server/src/main/java/org/apache/ambari/server/state/UpgradeContext.java b/ambari-server/src/main/java/org/apache/ambari/server/state/UpgradeContext.java
index 6dbde09ef7..86dbccd43a 100644
--- a/ambari-server/src/main/java/org/apache/ambari/server/state/UpgradeContext.java
+++ b/ambari-server/src/main/java/org/apache/ambari/server/state/UpgradeContext.java
@@ -51,10 +51,11 @@ public class UpgradeContext {
   private MasterHostResolver m_resolver;
   private AmbariMetaInfo m_metaInfo;
   private List<ServiceComponentHost> m_unhealthy = new ArrayList<ServiceComponentHost>();
   private Map<String, String> m_serviceNames = new HashMap<String, String>();
   private Map<String, String> m_componentNames = new HashMap<String, String>();
+  private String m_downgradeFromVersion = null;
 
   /**
    * Constructor.
    *
    * @param resolver
@@ -218,8 +219,24 @@ public class UpgradeContext {
   public void setComponentDisplay(String service, String component, String displayName) {
     String key = service + ":" + component;
     m_componentNames.put(key, displayName);
   }
 
+  /**
+   * This method returns the non-finalized version we are downgrading from.
+   * 
+   * @return version cluster is downgrading from
+   */
+  public String getDowngradeFromVersion() {
+    return m_downgradeFromVersion;
+  }
 
+  /**
+   * Set the HDP stack version we are downgrading from.
+   *  
+   * @param downgradeFromVersion
+   */
+  public void setDowngradeFromVersion(String downgradeFromVersion) {
+    this.m_downgradeFromVersion = downgradeFromVersion;
+  }
 
 }
```

### `ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server.py`

```diff
diff --git a/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server.py b/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server.py
index b20c46158f..3ec1747e07 100644
--- a/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server.py
+++ b/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server.py
@@ -82,18 +82,21 @@ class HiveServerDefault(HiveServer):
     env.set_params(params)
     self.configure(env) # FOR SECURITY
 
     setup_ranger_hive(rolling_upgrade=rolling_restart)
     hive_service( 'hiveserver2', action = 'start', rolling_restart=rolling_restart)
+    if rolling_restart:
+      hive_server_upgrade.post_upgrade_deregister()
 
   def stop(self, env, rolling_restart=False):
     import params
     env.set_params(params)
 
-    if rolling_restart:
-      hive_server_upgrade.pre_upgrade_deregister()
-    else:
+    # During rolling upgrade, HiveServer2 should not be stopped before new server is available.
+    # Once new server is started, old one is stopped by the --deregister command which is 
+    # invoked by the 'hive_server_upgrade.post_upgrade_deregister()' method
+    if not rolling_restart:
       hive_service( 'hiveserver2', action = 'stop' )
 
   def status(self, env):
     import status_params
     env.set_params(status_params)
```

### `ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server_upgrade.py`

```diff
diff --git a/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server_upgrade.py b/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server_upgrade.py
index 7533dc9ca9..d60e961f72 100644
--- a/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server_upgrade.py
+++ b/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/hive_server_upgrade.py
@@ -27,11 +27,11 @@ from resource_management.libraries.functions import format
 from resource_management.libraries.functions import hdp_select
 from resource_management.libraries.functions.version import format_hdp_stack_version
 from resource_management.libraries.functions.version import compare_versions
 
 
-def pre_upgrade_deregister():
+def post_upgrade_deregister():
   """
   Runs the "hive --service hiveserver2 --deregister <version>" command to
   de-provision the server in preparation for an upgrade. This will contact
   ZooKeeper to remove the server so that clients that attempt to connect
   will be directed to other servers automatically. Once all
@@ -40,11 +40,11 @@ def pre_upgrade_deregister():
   This function will obtain the Kerberos ticket if security is enabled.
   :return:
   """
   import params
 
-  Logger.info('HiveServer2 executing "deregister" command in preparation for upgrade...')
+  Logger.info('HiveServer2 executing "deregister" command to complete upgrade...')
 
   if params.security_enabled:
     kinit_command=format("{kinit_path_local} -kt {smoke_user_keytab} {smokeuser_principal}; ")
     Execute(kinit_command,user=params.smokeuser)
 
@@ -60,39 +60,70 @@ def pre_upgrade_deregister():
 
   # deregister
   hive_execute_path = params.execute_path
   # If upgrading, the upgrade-target hive binary should be used to call the --deregister command.
   # If downgrading, the downgrade-source hive binary should be used to call the --deregister command.
-  if "upgrade" == params.upgrade_direction:
+  # By now hdp-select has been called to set 'current' to target-stack
+  if "downgrade" == params.upgrade_direction:
     # hive_bin
-    upgrade_target_version = format_hdp_stack_version(params.version)
-    if upgrade_target_version and compare_versions(upgrade_target_version, "2.2") >= 0:
-      upgrade_target_hive_bin = format('/usr/hdp/{version}/hive/bin')
-      if (os.pathsep + params.hive_bin) in hive_execute_path:
-        hive_execute_path = hive_execute_path.replace(os.pathsep + params.hive_bin, os.pathsep + upgrade_target_hive_bin)
-    # hadoop_bin_dir
-    upgrade_target_hadoop_bin = hdp_select.get_hadoop_dir("bin", upgrade_stack_only=True)
-    upgrade_source_hadoop_bin = params.hadoop_bin_dir
-    if upgrade_target_hadoop_bin and len(upgrade_target_hadoop_bin) > 0 and (os.pathsep + upgrade_source_hadoop_bin) in hive_execute_path:
-      hive_execute_path = hive_execute_path.replace(os.pathsep + upgrade_source_hadoop_bin, os.pathsep + upgrade_target_hadoop_bin)
+    downgrade_version = params.current_version
+    if params.downgrade_from_version:
+      downgrade_version = params.downgrade_from_version
+    hive_execute_path = _get_hive_execute_path(downgrade_version)
 
   command = format('hive --config {hive_server_conf_dir} --service hiveserver2 --deregister ' + current_hiveserver_version)
   Execute(command, user=params.hive_user, path=hive_execute_path, tries=1 )
 
 
+def _get_hive_execute_path(hdp_stack_version):
+  """
+  Returns the exact execute path to use for the given stack-version.
+  This method does not return the "current" path
+  :param hdp_stack_version: Exact stack-version to use in the new path
+  :return: Hive execute path for the exact hdp stack-version
+  """
+  import params
+
+  hive_execute_path = params.execute_path
+  formatted_stack_version = format_hdp_stack_version(hdp_stack_version)
+  if formatted_stack_version and compare_versions(formatted_stack_version, "2.2") >= 0:
+    # hive_bin
+    new_hive_bin = format('/usr/hdp/{hdp_stack_version}/hive/bin')
+    if (os.pathsep + params.hive_bin) in hive_execute_path:
+      hive_execute_path = hive_execute_path.replace(os.pathsep + params.hive_bin, os.pathsep + new_hive_bin)
+    # hadoop_bin_dir
+    new_hadoop_bin = hdp_select.get_hadoop_dir_for_stack_version("bin", hdp_stack_version)
+    old_hadoop_bin = params.hadoop_bin_dir
+    if new_hadoop_bin and len(new_hadoop_bin) > 0 and (os.pathsep + old_hadoop_bin) in hive_execute_path:
+      hive_execute_path = hive_execute_path.replace(os.pathsep + old_hadoop_bin, os.pathsep + new_hadoop_bin)
+  return hive_execute_path
+
+
 def _get_current_hiveserver_version():
   """
   Runs "hive --version" and parses the result in order
   to obtain the current version of hive.
 
   :return:  the hiveserver2 version, returned by "hive --version"
   """
   import params
 
   try:
-    command = 'hive --version'
-    return_code, hdp_output = shell.call(command, user=params.hive_user, path=params.execute_path)
+    # When downgrading the source version should be the version we are downgrading from
+    if "downgrade" == params.upgrade_direction:
+      if not params.downgrade_from_version:
+        raise Fail('The version from which we are downgrading from should be provided in \'downgrade_from_version\'')
+      source_version = params.downgrade_from_version
+    else:
+      source_version = params.current_version
+    hive_execute_path = _get_hive_execute_path(source_version)
+    version_hive_bin = params.hive_bin
+    formatted_source_version = format_hdp_stack_version(source_version)
+    if formatted_source_version and compare_versions(formatted_source_version, "2.2") >= 0:
+      version_hive_bin = format('/usr/hdp/{source_version}/hive/bin')
+    command = format('{version_hive_bin}/hive --version')
+    return_code, hdp_output = shell.call(command, user=params.hive_user, path=hive_execute_path)
   except Exception, e:
     Logger.error(str(e))
     raise Fail('Unable to execute hive --version command to retrieve the hiveserver2 version.')
 
   if return_code != 0:
```

### `ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py`

```diff
diff --git a/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py b/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py
index db9d9da599..bee455f269 100644
--- a/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py
+++ b/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py
@@ -58,10 +58,14 @@ hdp_stack_version = functions.get_hdp_version('hive-server2')
 version = default("/commandParams/version", None)
 
 # current host stack version
 current_version = default("/hostLevelParams/current_version", None)
 
+# When downgrading the 'version' and 'current_version' are both pointing to the downgrade-target version
+# downgrade_from_version provides the source-version the downgrade is happening from 
+downgrade_from_version = default("/commandParams/downgrade_from_version", None)
+
 # Upgrade direction
 upgrade_direction = default("/commandParams/upgrade_direction", None)
 
 hadoop_bin_dir = "/usr/bin"
 hadoop_home = '/usr'
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
