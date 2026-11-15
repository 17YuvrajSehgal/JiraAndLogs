# Annotation packet: AMBARI-10949  (ambari)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Hcat install task fails on a secure cluster

**Hcat install Task log:**
    
    
    
    Traceback (most recent call last):
      File "/var/lib/ambari-agent/cache/common-services/HIVE/0.12.0.2.0/package/scripts/hcat_client.py", line 55, in <module>
        HCatClient().execute()
      File "/usr/lib/python2.6/site-packages/resource_management/libraries/script/script.py", line 214, in execute
        method(env)
      File "/var/lib/ambari-agent/cache/common-services/HIVE/0.12.0.2.0/package/scripts/hcat_client.py", line 30, in install
        import params
      File "/var/lib/ambari-agent/cache/common-services/HIVE/0.12.0.2.0/package/scripts/params.py", line 26, in <module>
        from params_linux import *
      File "/var/lib/ambari-agent/cache/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py", line 403, in <module>
        'jdbc.url': format("{hive_url}/default;principal={hive_principal}") if security_enabled else hive_url,
      File "/usr/lib/python2.6/site-packages/resource_management/libraries/functions/format.py", line 83, in format
        return ConfigurationFormatter().format(format_string, args, **result)
      File "/usr/lib/python2.6/site-packages/resource_management/libraries/functions/format.py", line 47, in format
        result_protected = self.vformat(format_string, args, all_params)
      File "/usr/lib64/python2.6/string.py", line 549, in vformat
        result = self._vformat(format_string, args, kwargs, used_args, 2)
      File "/usr/lib64/python2.6/string.py", line 571, in _vformat
        obj, arg_used = self.get_field(field_name, args, kwargs)
      File "/usr/lib64/python2.6/string.py", line 632, in get_field
        obj = self.get_value(first, args, kwargs)
      File "/usr/lib64/python2.6/string.py", line 591, in get_value
        return kwargs[key]
    KeyError: 'hive_principal'
```

## Fix commit message(s)

`28a88d3f51d0`

```
AMBARI-10949. Hcat install task fails on a secure cluster (aonishuk)
```

## Files the fix changed

Snapshot holds 2,675 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py`

## The fix diff

### `ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py`

```diff
diff --git a/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py b/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py
index 38bdced2be..8af69d78a4 100644
--- a/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py
+++ b/ambari-server/src/main/resources/common-services/HIVE/0.12.0.2.0/package/scripts/params_linux.py
@@ -360,10 +360,13 @@ repo_config_password = config['configurations']['ranger-hive-plugin-properties']
 
 ranger_env = config['configurations']['ranger-env']
 ranger_plugin_properties = config['configurations']['ranger-hive-plugin-properties']
 policy_user = config['configurations']['ranger-hive-plugin-properties']['policy_user']
 
+if security_enabled:
+  hive_principal = hive_server_principal.replace('_HOST',hostname.lower())
+  
 #For curl command in ranger plugin to get db connector
 if has_ranger_admin:
   if xa_audit_db_flavor and xa_audit_db_flavor.lower() == 'mysql':
     ranger_jdbc_symlink_name = "mysql-jdbc-driver.jar"
     ranger_jdbc_jar_name = "mysql-connector-java.jar"
@@ -396,8 +399,5 @@ if has_ranger_admin:
     'description': 'hive repo',
     'name': repo_name,
     'repositoryType': 'hive',
     'assetType': '3'
   }
-
-if security_enabled:
-  hive_principal = hive_server_principal.replace('_HOST',hostname.lower())
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
