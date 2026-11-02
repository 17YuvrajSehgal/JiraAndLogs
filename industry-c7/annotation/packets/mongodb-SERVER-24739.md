# Annotation packet: SERVER-24739  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Unhandled duration_cast exception in DataFileSync::run can terminate server

It's possible for the server to terminate with an unhandled duration_cast exception if an invalid syncdelay value is specified:

{noformat}
d20000| 2016-06-22T17:25:51.587-0400 E COMMAND  [DataFileSync] backgroundjob DataFileSync exception: Overflow casting from a lower-precision duration to a higher-precision duration
d20000| 2016-06-22T17:25:51.588-0400 F -        [DataFileSync] terminate() called. An exception is active; attempting to gather more information
d20000| 2016-06-22T17:25:51.590-0400 F -        [DataFileSync] DBException::toString(): 159 Overflow casting from a lower-precision duration to a higher-precision duration
d20000| Actual exception type: mongo::UserException
{noformat}

This bug seems to have been introduced after 3.3.6.
```

## Fix commit message(s)

`df8ee2e1ffcf`

```
SERVER-24739: Validate syncdelay at startup and on setParameter
```

## Files the fix changed

Snapshot holds 10,463 non-test source files. The fix changed 5 file(s); 3 of them are non-test source files (listed below as gold).

- `src/mongo/db/mongod_options.cpp`
- `src/mongo/db/storage/storage_options.cpp`
- `src/mongo/db/storage/storage_options.h`

## The fix diff

### `src/mongo/db/mongod_options.cpp`

```diff
diff --git a/src/mongo/db/mongod_options.cpp b/src/mongo/db/mongod_options.cpp
index 9a3f4f3b4fe..67344ece83a 100644
--- a/src/mongo/db/mongod_options.cpp
+++ b/src/mongo/db/mongod_options.cpp
@@ -1044,10 +1044,17 @@ Status storeMongodOptions(const moe::Environment& params) {
         serverGlobalParams.slowMS = params["operationProfiling.slowOpThresholdMs"].as<int>();
     }
 
     if (params.count("storage.syncPeriodSecs")) {
         storageGlobalParams.syncdelay = params["storage.syncPeriodSecs"].as<double>();
+        if (storageGlobalParams.syncdelay < 0 ||
+            storageGlobalParams.syncdelay > StorageGlobalParams::kMaxSyncdelaySecs) {
+            return Status(ErrorCodes::BadValue,
+                          str::stream() << "syncdelay out of allowed range (0-"
+                                        << StorageGlobalParams::kMaxSyncdelaySecs
+                                        << "s)");
+        }
     }
 
     if (params.count("storage.directoryPerDB")) {
         storageGlobalParams.directoryperdb = params["storage.directoryPerDB"].as<bool>();
     }
```

### `src/mongo/db/storage/storage_options.cpp`

```diff
diff --git a/src/mongo/db/storage/storage_options.cpp b/src/mongo/db/storage/storage_options.cpp
index 8b031ff7a59..2756720a24c 100644
--- a/src/mongo/db/storage/storage_options.cpp
+++ b/src/mongo/db/storage/storage_options.cpp
@@ -47,10 +47,11 @@ const char* StorageGlobalParams::kDefaultConfigDbPath = "\\data\\configdb\\";
 const char* StorageGlobalParams::kDefaultDbPath = "/data/db";
 const char* StorageGlobalParams::kDefaultConfigDbPath = "/data/configdb";
 #endif
 
 const int StorageGlobalParams::kMaxJournalCommitIntervalMs = 500;
+const double StorageGlobalParams::kMaxSyncdelaySecs = 9.0 * 1000.0 * 1000.0;
 
 /**
  * Specify whether all queries must use indexes.
  * If 1, MongoDB will not execute queries that require a table scan and will return an error.
  * NOT recommended for production use.
@@ -61,12 +62,29 @@ ExportedServerParameter<bool, ServerParameterType::kStartupAndRuntime> NoTableSc
 /**
  * Specify the interval in seconds between fsync operations where mongod flushes its
  * working memory to disk. By default, mongod flushes memory to disk every 60 seconds.
  * In almost every situation you should not set this value and use the default setting.
  */
-ExportedServerParameter<double, ServerParameterType::kStartupAndRuntime> SyncdelaySetting(
-    ServerParameterSet::getGlobal(), "syncdelay", &storageGlobalParams.syncdelay);
+class SyncdelaySetting
+    : public ExportedServerParameter<double, ServerParameterType::kStartupAndRuntime> {
+public:
+    SyncdelaySetting()
+        : ExportedServerParameter<double, ServerParameterType::kStartupAndRuntime>(
+              ServerParameterSet::getGlobal(), "syncdelay", &storageGlobalParams.syncdelay) {}
+
+    virtual Status validate(const double& potentialNewValue) {
+        if (potentialNewValue < 0.0 || potentialNewValue > StorageGlobalParams::kMaxSyncdelaySecs) {
+            return Status(ErrorCodes::BadValue,
+                          str::stream() << "syncdelay must be between 0 and "
+                                        << StorageGlobalParams::kMaxSyncdelaySecs
+                                        << ", but attempted to set to: "
+                                        << potentialNewValue);
+        }
+
+        return Status::OK();
+    }
+} syncdelaySetting;
 
 /**
  * Specify an integer between 1 and kMaxJournalCommitInterval signifying the number of milliseconds
  * (ms) between journal commits.
  */
```

### `src/mongo/db/storage/storage_options.h`

```diff
diff --git a/src/mongo/db/storage/storage_options.h b/src/mongo/db/storage/storage_options.h
index 2e4f936e60e..8ae1467e307 100644
--- a/src/mongo/db/storage/storage_options.h
+++ b/src/mongo/db/storage/storage_options.h
@@ -96,10 +96,11 @@ struct StorageGlobalParams {
     // --syncdelay
     // Controls how much time can pass before MongoDB flushes data to the data files
     // via an fsync operation.
     // Do not set this value on production systems.
     // In almost every situation, you should use the default setting.
+    static const double kMaxSyncdelaySecs;
     AtomicDouble syncdelay{60.0};  // seconds between fsyncs
 
     bool readOnly = false;
 };
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
