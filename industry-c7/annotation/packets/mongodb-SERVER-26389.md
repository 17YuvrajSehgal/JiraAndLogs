# Annotation packet: SERVER-26389  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Make javascript periodic interrupts disabled by default
```

## Fix commit message(s)

`cb9e5e2f0a8e`

```
SERVER-26389 Make javascript periodic interrupts disabled by default
```

## Files the fix changed

Snapshot holds 10,289 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `src/mongo/scripting/deadline_monitor.cpp`
- `src/mongo/scripting/deadline_monitor.h`

## The fix diff

### `src/mongo/scripting/deadline_monitor.cpp`

```diff
diff --git a/src/mongo/scripting/deadline_monitor.cpp b/src/mongo/scripting/deadline_monitor.cpp
index 5eb0f52e5de..f75c34a0cc2 100644
--- a/src/mongo/scripting/deadline_monitor.cpp
+++ b/src/mongo/scripting/deadline_monitor.cpp
@@ -32,11 +32,11 @@
 
 #include "mongo/db/server_parameters.h"
 
 namespace mongo {
 
-MONGO_EXPORT_SERVER_PARAMETER(scriptingEngineInterruptIntervalMS, int, 1000);
+MONGO_EXPORT_SERVER_PARAMETER(scriptingEngineInterruptIntervalMS, int, 0);
 
 int getScriptingEngineInterruptInterval() {
     return scriptingEngineInterruptIntervalMS.load();
 }
```

### `src/mongo/scripting/deadline_monitor.h`

```diff
diff --git a/src/mongo/scripting/deadline_monitor.h b/src/mongo/scripting/deadline_monitor.h
index 127bc81288d..a39b78971c5 100644
--- a/src/mongo/scripting/deadline_monitor.h
+++ b/src/mongo/scripting/deadline_monitor.h
@@ -137,23 +137,27 @@ private:
         while (!_inShutdown) {
             // get the next interval to wait
             const Date_t now = Date_t::now();
             const auto interruptInterval = Milliseconds{getScriptingEngineInterruptInterval()};
 
-            if (now - lastInterruptCycle > interruptInterval) {
+            if ((interruptInterval.count() > 0) && (now - lastInterruptCycle > interruptInterval)) {
                 for (const auto& task : _tasks) {
                     if (task.second > now)
                         task.first->interrupt();
                 }
                 lastInterruptCycle = now;
             }
 
             // wait for a task to be added or a deadline to expire
             if (_nearestDeadlineWallclock > now) {
-                if (_nearestDeadlineWallclock == Date_t::max() ||
-                    _nearestDeadlineWallclock - now > interruptInterval) {
-                    _newDeadlineAvailable.wait_for(lk, interruptInterval.toSystemDuration());
+                if (_nearestDeadlineWallclock == Date_t::max()) {
+                    if ((interruptInterval.count() > 0) &&
+                        (_nearestDeadlineWallclock - now > interruptInterval)) {
+                        _newDeadlineAvailable.wait_for(lk, interruptInterval.toSystemDuration());
+                    } else {
+                        _newDeadlineAvailable.wait(lk);
+                    }
                 } else {
                     _newDeadlineAvailable.wait_until(lk,
                                                      _nearestDeadlineWallclock.toSystemTimePoint());
                 }
                 continue;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
