# Annotation packet: AMBARI-9125  (ambari)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Secondary Namenode fails when trying to create multiple SecondaryNameNode Checkpoint directories via Ambari

PROBLEM:
If we specify a comma separated list of directories for SecondaryNameNode Checkpoint directories via Ambari, the directories are not getting created and Secondary Nemnode fails to start. Below error message is seen in the Secondary Namenode logs:
2015-01-05 20:24:55,077 FATAL namenode.SecondaryNameNode (SecondaryNameNode.java:main(673)) - Failed to start secondary namenode
org.apache.hadoop.hdfs.server.common.InconsistentFSStateException: Directory /hadoop/hdfs/namesecondary2 is in an inconsistent state: checkpoint directory does not exist or is not accessible.
at org.apache.hadoop.hdfs.server.namenode.SecondaryNameNode$CheckpointStorage.recoverCreate(SecondaryNameNode.java:967)
at org.apache.hadoop.hdfs.server.namenode.SecondaryNameNode.initialize(SecondaryNameNode.java:243)
at org.apache.hadoop.hdfs.server.namenode.SecondaryNameNode.<init>(SecondaryNameNode.java:192)
at org.apache.hadoop.hdfs.server.namenode.SecondaryNameNode.main(SecondaryNameNode.java:671)
2015-01-05 20:24:55,082 INFO util.ExitUtil (ExitUtil.java:terminate(124)) - Exiting with status 1
2015-01-05 20:24:55,085 INFO namenode.SecondaryNameNode (StringUtils.java:run(659)) - SHUTDOWN_MSG:
/************************************************************
SHUTDOWN_MSG: Shutting down SecondaryNameNode at hdp22.local.com/192.168.56.80
************************************************************/
```

## Fix commit message(s)

`b5c907032321`

```
AMBARI-9125. Secondary Namenode fails when trying to create multiple SecondaryNameNode Checkpoint directories via Ambari.(vbrodetskyi)
```

## Files the fix changed

Snapshot holds 2,348 non-test source files. The fix changed 4 file(s); 2 of them are non-test source files (listed below as gold).

- `ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/hdfs_snamenode.py`
- `ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/params.py`

## The fix diff

### `ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/hdfs_snamenode.py`

```diff
diff --git a/ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/hdfs_snamenode.py b/ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/hdfs_snamenode.py
index c650c4d687..7f0d536f96 100644
--- a/ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/hdfs_snamenode.py
+++ b/ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/hdfs_snamenode.py
@@ -24,16 +24,17 @@ from utils import hdfs_directory
 
 def snamenode(action=None, format=False):
   import params
 
   if action == "configure":
-    Directory(params.fs_checkpoint_dir,
-              recursive=True,
-              recursive_permission=True,
-              mode=0755,
-              owner=params.hdfs_user,
-              group=params.user_group)
+    for fs_checkpoint_dir in params.fs_checkpoint_dirs:
+      Directory(fs_checkpoint_dir,
+                recursive=True,
+                recursive_permission=True,
+                mode=0755,
+                owner=params.hdfs_user,
+                group=params.user_group)
     File(params.exclude_file_path,
          content=Template("exclude_hosts_list.j2"),
          owner=params.hdfs_user,
          group=params.user_group)
   elif action == "start" or action == "stop":
```

### `ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/params.py`

```diff
diff --git a/ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/params.py b/ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/params.py
index cfef5c4dcd..a4a0d3d904 100644
--- a/ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/params.py
+++ b/ambari-server/src/main/resources/common-services/HDFS/2.1.0.2.0/package/scripts/params.py
@@ -173,11 +173,11 @@ smoke_hdfs_user_dir = format("/user/{smoke_user}")
 smoke_hdfs_user_mode = 0770
 
 namenode_formatted_old_mark_dir = format("{hadoop_pid_dir_prefix}/hdfs/namenode/formatted/")
 namenode_formatted_mark_dir = format("/var/lib/hdfs/namenode/formatted/")
 
-fs_checkpoint_dir = config['configurations']['hdfs-site']['dfs.namenode.checkpoint.dir']
+fs_checkpoint_dirs = config['configurations']['hdfs-site']['dfs.namenode.checkpoint.dir'].split(',')
 
 dfs_data_dir = config['configurations']['hdfs-site']['dfs.datanode.data.dir']
 dfs_data_dir = ",".join([re.sub(r'^\[.+\]', '', dfs_dir.strip()) for dfs_dir in dfs_data_dir.split(",")])
 
 data_dir_mount_file = config['configurations']['hadoop-env']['dfs.datanode.data.dir.mount.file']
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
