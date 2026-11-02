# Annotation packet: QTBUG-96285  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
QProcess can't be restarted

If the example application is built with MSVC2019 64bit, the QProcess can't be restarted.

To reproduce
1) build the example in release with MSVC2019.
2) run the project
3) Go to task manager and kill the cmd.exe process
    -> the process is restarted
4) Repeat kill 2-3 more times - the application crashes:

{code:java}
ProcessTest::processFinished  30
ProcessTest::processFinished  29
21:31:46: The program has unexpectedly finished.
{code}

In debug it hardly crashes.
Not reproducible with MinGW.
```

## Fix commit message(s)

`4e0082a9cacf`

```
Allow destruction of QWinEventNotifier in its signal

Avoid use-after-free issue in QProcess.

Fixes: QTBUG-96285
Fixes: QTBUG-96359
Pick-to: 6.2 6.1
Change-Id: I953d7a8ecaf301ec3a27db37e13748f905c3d097
Reviewed-by: Christoph Cullmann <cullmann@kde.org>
Reviewed-by: Thiago Macieira <thiago.macieira@intel.com>
Reviewed-by: Oswald Buddenhagen <oswald.buddenhagen@gmx.de>
```

## Files the fix changed

Snapshot holds 5,886 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/kernel/qwineventnotifier.cpp`

## The fix diff

### `src/corelib/kernel/qwineventnotifier.cpp`

```diff
diff --git a/src/corelib/kernel/qwineventnotifier.cpp b/src/corelib/kernel/qwineventnotifier.cpp
index 3371e101b64..073b8f61abc 100644
--- a/src/corelib/kernel/qwineventnotifier.cpp
+++ b/src/corelib/kernel/qwineventnotifier.cpp
@@ -39,10 +39,11 @@
 
 #include "qwineventnotifier_p.h"
 
 #include "qcoreapplication.h"
 #include "qthread.h"
+#include <QPointer>
 
 QT_BEGIN_NAMESPACE
 
 /*!
     \class QWinEventNotifier
@@ -236,13 +237,14 @@ bool QWinEventNotifier::event(QEvent * e)
             == QWinEventNotifierPrivate::Posted && d->enabled) {
             // Clear the flag, as the wait object is implicitly unregistered
             // when the callback is queued.
             d->registered = false;
 
+            QPointer<QWinEventNotifier> alive(this);
             emit activated(d->handleToEvent, QPrivateSignal());
 
-            if (d->enabled && !d->registered) {
+            if (alive && d->enabled && !d->registered) {
                 SetThreadpoolWait(d->waitObject, d->handleToEvent, NULL);
                 d->registered = true;
             }
         }
         return true;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
