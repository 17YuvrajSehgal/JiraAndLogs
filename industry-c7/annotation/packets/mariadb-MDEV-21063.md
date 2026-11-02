# Annotation packet: MDEV-21063  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Very many test failures on big-endian PowerPC

The builder kvm-rpm-centos73-ppc64 builder is effectively disabled from running any tests on 10.5, because it aborts very early:
{noformat:title=bb-10.5-19708}
Too many failed: Failed 8/80 tests, 90.00% were successful.

Failing test(s): binlog_encryption.encrypted_slave binlog_encryption.encrypted_master_switch_to_unencrypted binlog_encryption.encrypted_master binlog_encryption.rpl_loadfile binlog_encryption.rpl_switch_stm_row_mixed
{noformat}
This was first observed in the bb-10.5-19708 branch:
http://buildbot.askmonty.org/buildbot/builders/kvm-rpm-centos73-ppc64/builds/10061/steps/mtr/logs/stdio
The previous 10.5 build on that platform completed fine:
http://buildbot.askmonty.org/buildbot/builders/kvm-rpm-centos73-ppc64/builds/10047/
Ever since the problematic push to 10.5, the platform has been broken:
http://buildbot.askmonty.org/buildbot/builders/kvm-rpm-centos73-ppc64/builds/10069

The culprit seems to be MDEV-20477 [Merge binlog extended metadata support from the upstream|https://github.com/MariaDB/server/commit/967c14c04e9e14062bd2b8288e054514af3cd322].
```

## Fix commit message(s)

`20b474be5b75`

```
MDEV-21063 Very many test failures on big-endian PowerPC

Memcpy is endian dependent, So instead of memcpy we will use int2store.
And m_metadata_size can be 0,1 or 2, And int2store will take care of it.
```

## Files the fix changed

Snapshot holds 3,296 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/log_event_server.cc`

## The fix diff

### `sql/log_event_server.cc`

```diff
diff --git a/sql/log_event_server.cc b/sql/log_event_server.cc
index 04cf70984a2..202a41c2837 100644
--- a/sql/log_event_server.cc
+++ b/sql/log_event_server.cc
@@ -5916,13 +5916,12 @@ int Table_map_log_event::save_field_metadata()
   int index= 0;
   Binlog_type_info *info;
   for (unsigned int i= 0 ; i < m_table->s->fields ; i++)
   {
     DBUG_PRINT("debug", ("field_type: %d", m_coltype[i]));
-    //index+= m_table->s->field[i]->save_field_metadata(&m_field_metadata[index]);
     info= binlog_type_info_array + i;
-    memcpy(&m_field_metadata[index], (uchar *)&info->m_metadata, info->m_metadata_size);
+    int2store(&m_field_metadata[index], info->m_metadata);
     index+= info->m_metadata_size;
     DBUG_EXECUTE_IF("inject_invalid_blob_size",
                     {
                       if (m_coltype[i] == MYSQL_TYPE_BLOB)
                         m_field_metadata[index-1] = 5;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
