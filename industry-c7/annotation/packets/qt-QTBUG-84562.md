# Annotation packet: QTBUG-84562  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
[REG 5.15.0 b3->5.15.0] window embedded using QWinWidget not receiving any event (Qt MFC solution) in some integrations

This is a very specific bug, but very blocking for me :

When embedding a Qt window as a plugin within a (non-Qt) host app, using QWinWidget ( [https://github.com/qtproject/qt-solutions/tree/master/qtwinmigrate/src] ), my Qt window displays once and then no longer refresh (unless during a resize), and no longer receive any input event (such as mouse or keyboard).
 For a little more context, I'm developping a VST3 plugin using Qt for the host app Cubase.

The issue occurs in the Steinberg Cubase and Steinberg Nuendo integrations, but not in Presonus Studio One or Cockos Reaper  integrations using the VST3 plugin.

I've narrowed down the problem to this commit:

*QEventDispatcherWin32: fix posted events delivering*

[https://github.com/qt/qtbase/commit/e0d80167c18b5a71acf4dac59f3e6f37292fa397#diff-76b4b966aaac13e64f6c131c1411fab8] https://codereview.qt-project.org/c/qt/qtbase/+/294403

Right before this commit everything works as expected, and after it's applied the problem occurs.

Any way this commit could be reverted or fixed ?
```

## Fix commit message(s)

`33e6e5fac3c8`

```
QEventDispatcherWin32: retrieve PM_REMOVE value as a bit flag

Windows unexpectedly passes PM_NOYIELD flag in wParam parameter to the
hook procedure, if ::PeekMessage(..., PM_REMOVE | PM_NOYIELD) is called
from the event loop. So, to ignore undocumented flag, we should
interpret wParam as a bit field.

Thanks to Robin Lobel for research.

Pick-to: 5.15
Fixes: QTBUG-84562
Change-Id: Ib16d7d747aebc9a3628e4ee67478c4d3edeb96f1
Reviewed-by: Friedemann Kleint <Friedemann.Kleint@qt.io>
```

## Files the fix changed

Snapshot holds 6,149 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/kernel/qeventdispatcher_win.cpp`

## The fix diff

### `src/corelib/kernel/qeventdispatcher_win.cpp`

```diff
diff --git a/src/corelib/kernel/qeventdispatcher_win.cpp b/src/corelib/kernel/qeventdispatcher_win.cpp
index d9b9d84e41d..43872fd0270 100644
--- a/src/corelib/kernel/qeventdispatcher_win.cpp
+++ b/src/corelib/kernel/qeventdispatcher_win.cpp
@@ -275,13 +275,17 @@ LRESULT QT_WIN_CALLBACK qt_GetMessageHook(int code, WPARAM wp, LPARAM lp)
 {
     QEventDispatcherWin32 *q = qobject_cast<QEventDispatcherWin32 *>(QAbstractEventDispatcher::instance());
     Q_ASSERT(q != 0);
     QEventDispatcherWin32Private *d = q->d_func();
     MSG *msg = reinterpret_cast<MSG *>(lp);
+    // Windows unexpectedly passes PM_NOYIELD flag to the hook procedure,
+    // if ::PeekMessage(..., PM_REMOVE | PM_NOYIELD) is called from the event loop.
+    // So, retrieve 'removed' tag as a bit field.
+    const bool messageRemoved = (wp & PM_REMOVE) != 0;
 
     if (msg->hwnd == d->internalHwnd && msg->message == WM_QT_SENDPOSTEDEVENTS
-        && wp == PM_REMOVE && d->sendPostedEventsTimerId == 0) {
+        && messageRemoved && d->sendPostedEventsTimerId == 0) {
         // Start a timer to deliver posted events when the message queue is emptied.
         d->sendPostedEventsTimerId = SetTimer(d->internalHwnd, SendPostedEventsTimerId,
                                               USER_TIMER_MINIMUM, NULL);
     }
     return d->getMessageHook ? CallNextHookEx(0, code, wp, lp) : 0;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
