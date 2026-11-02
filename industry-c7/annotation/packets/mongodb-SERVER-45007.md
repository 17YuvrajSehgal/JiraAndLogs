# Annotation packet: SERVER-45007  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
PBWM acquisition in GlobalLock constructor ignores deadline

[This PBWM lock acquisition|https://github.com/mongodb/mongo/blob/c4a5310c8037c075cde7a0a1a32a7f00bfc19746/src/mongo/db/concurrency/d_concurrency.cpp#L153] ignores the passed in deadline. A consequence is that [this {{GlobalLock}} construction|https://github.com/mongodb/mongo/blob/c4a5310c8037c075cde7a0a1a32a7f00bfc19746/src/mongo/db/curop.cpp#L444-L447] can hang waiting for the PBWM lock.
```

## Fix commit message(s)

`25ffb326e1ec`

```
SERVER-45007 ResourceLock::lock() always requires OperationContext
```

`0f502c28c373`

```
SERVER-45007 ResourceLock::lock() supports deadline
```

`73acb91e3989`

```
SERVER-45007 PBWM lock acquisition in GlobalLock supports deadline
```

## Files the fix changed

Snapshot holds 14,754 non-test source files. The fix changed 4 file(s); 3 of them are non-test source files (listed below as gold).

- `src/mongo/db/commands/sleep_command.cpp`
- `src/mongo/db/concurrency/d_concurrency.cpp`
- `src/mongo/db/concurrency/d_concurrency.h`

## The fix diff

### `src/mongo/db/commands/sleep_command.cpp`

```diff
--- from commit 25ffb326e1ec ---
diff --git a/src/mongo/db/commands/sleep_command.cpp b/src/mongo/db/commands/sleep_command.cpp
index 877ba3eacf7..21407950cd8 100644
--- a/src/mongo/db/commands/sleep_command.cpp
+++ b/src/mongo/db/commands/sleep_command.cpp
@@ -106,11 +106,11 @@ public:
         opCtx->sleepFor(Milliseconds(millis));
     }
 
     void _sleepInPBWM(mongo::OperationContext* opCtx, long long millis) {
         Lock::ResourceLock pbwm(opCtx->lockState(), resourceIdParallelBatchWriterMode);
-        pbwm.lock(MODE_X);
+        pbwm.lock(nullptr, MODE_X);
         opCtx->sleepFor(Milliseconds(millis));
         pbwm.unlock();
     }
 
     CmdSleep() : BasicCommand("sleep") {}
```

### `src/mongo/db/concurrency/d_concurrency.cpp`

```diff
--- from commit 25ffb326e1ec ---
diff --git a/src/mongo/db/concurrency/d_concurrency.cpp b/src/mongo/db/concurrency/d_concurrency.cpp
index 59a09012695..4138e537298 100644
--- a/src/mongo/db/concurrency/d_concurrency.cpp
+++ b/src/mongo/db/concurrency/d_concurrency.cpp
@@ -311,14 +311,10 @@ Lock::CollectionLock::~CollectionLock() {
 
 Lock::ParallelBatchWriterMode::ParallelBatchWriterMode(Locker* lockState)
     : _pbwm(lockState, resourceIdParallelBatchWriterMode, MODE_X),
       _shouldNotConflictBlock(lockState) {}
 
-void Lock::ResourceLock::lock(LockMode mode) {
-    lock(nullptr, mode);
-}
-
 void Lock::ResourceLock::lock(OperationContext* opCtx, LockMode mode) {
     invariant(_result == LOCK_INVALID);
     _locker->lock(opCtx, _rid, mode);
     _result = LOCK_OK;
 }
--- from commit 0f502c28c373 ---
diff --git a/src/mongo/db/concurrency/d_concurrency.cpp b/src/mongo/db/concurrency/d_concurrency.cpp
index 4138e537298..e4c13f7cfe5 100644
--- a/src/mongo/db/concurrency/d_concurrency.cpp
+++ b/src/mongo/db/concurrency/d_concurrency.cpp
@@ -311,13 +311,13 @@ Lock::CollectionLock::~CollectionLock() {
 
 Lock::ParallelBatchWriterMode::ParallelBatchWriterMode(Locker* lockState)
     : _pbwm(lockState, resourceIdParallelBatchWriterMode, MODE_X),
       _shouldNotConflictBlock(lockState) {}
 
-void Lock::ResourceLock::lock(OperationContext* opCtx, LockMode mode) {
+void Lock::ResourceLock::lock(OperationContext* opCtx, LockMode mode, Date_t deadline) {
     invariant(_result == LOCK_INVALID);
-    _locker->lock(opCtx, _rid, mode);
+    _locker->lock(opCtx, _rid, mode, deadline);
     _result = LOCK_OK;
 }
 
 void Lock::ResourceLock::unlock() {
     if (_result == LOCK_OK) {
--- from commit 73acb91e3989 ---
diff --git a/src/mongo/db/concurrency/d_concurrency.cpp b/src/mongo/db/concurrency/d_concurrency.cpp
index e4c13f7cfe5..3e0018aa3d0 100644
--- a/src/mongo/db/concurrency/d_concurrency.cpp
+++ b/src/mongo/db/concurrency/d_concurrency.cpp
@@ -148,11 +148,11 @@ Lock::GlobalLock::GlobalLock(OperationContext* opCtx,
       _isOutermostLock(!opCtx->lockState()->isLocked()) {
     _opCtx->lockState()->getFlowControlTicket(_opCtx, lockMode);
 
     try {
         if (_opCtx->lockState()->shouldConflictWithSecondaryBatchApplication()) {
-            _pbwm.lock(opCtx, MODE_IS);
+            _pbwm.lock(opCtx, MODE_IS, deadline);
         }
         auto unlockPBWM = makeGuard([this] {
             if (_opCtx->lockState()->shouldConflictWithSecondaryBatchApplication()) {
                 _pbwm.unlock();
             }
```

### `src/mongo/db/concurrency/d_concurrency.h`

```diff
--- from commit 25ffb326e1ec ---
diff --git a/src/mongo/db/concurrency/d_concurrency.h b/src/mongo/db/concurrency/d_concurrency.h
index 03511aa8fd5..ddf7da380de 100644
--- a/src/mongo/db/concurrency/d_concurrency.h
+++ b/src/mongo/db/concurrency/d_concurrency.h
@@ -80,11 +80,11 @@ public:
         ResourceLock(Locker* locker, ResourceId rid)
             : _rid(rid), _locker(locker), _result(LOCK_INVALID) {}
 
         ResourceLock(Locker* locker, ResourceId rid, LockMode mode)
             : _rid(rid), _locker(locker), _result(LOCK_INVALID) {
-            lock(mode);
+            lock(nullptr, mode);
         }
 
         ResourceLock(ResourceLock&& otherLock)
             : _rid(otherLock._rid), _locker(otherLock._locker), _result(otherLock._result) {
             // Mark as moved so the destructor doesn't invalidate the newly-
@@ -96,12 +96,19 @@ public:
             if (isLocked()) {
                 unlock();
             }
         }
 
-        void lock(LockMode mode);                           // Uninterruptible
-        void lock(OperationContext* opCtx, LockMode mode);  // Interruptible
+        /**
+         * Acquires lock on this specified resource in the specified mode.
+         *
+         * If 'opCtx' is provided, it will be used to interrupt a LOCK_WAITING state.
+         *
+         * This function may throw an exception if it is interrupted.
+         */
+        void lock(OperationContext* opCtx, LockMode mode);
+
         void unlock();
 
         bool isLocked() const {
             return _result == LOCK_OK;
         }
@@ -163,11 +170,11 @@ public:
         /**
          * Parameterless overload to allow ExclusiveLock to be used with stdx::unique_lock and
          * stdx::condition_variable_any
          */
         void lock() {
-            lock(MODE_X);
+            lock(nullptr, MODE_X);
         }
     };
 
     /**
      * Obtains a ResourceMutex for shared/non-exclusive use. This uses MODE_IS rather than MODE_S
--- from commit 0f502c28c373 ---
diff --git a/src/mongo/db/concurrency/d_concurrency.h b/src/mongo/db/concurrency/d_concurrency.h
index ddf7da380de..a392c0c2f2d 100644
--- a/src/mongo/db/concurrency/d_concurrency.h
+++ b/src/mongo/db/concurrency/d_concurrency.h
@@ -100,14 +100,16 @@ public:
 
         /**
          * Acquires lock on this specified resource in the specified mode.
          *
          * If 'opCtx' is provided, it will be used to interrupt a LOCK_WAITING state.
+         * If 'deadline' is provided, we will wait until 'deadline' for the lock to be granted.
+         * Otherwise, this parameter defaults to an infinite deadline.
          *
          * This function may throw an exception if it is interrupted.
          */
-        void lock(OperationContext* opCtx, LockMode mode);
+        void lock(OperationContext* opCtx, LockMode mode, Date_t deadline = Date_t::max());
 
         void unlock();
 
         bool isLocked() const {
             return _result == LOCK_OK;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
