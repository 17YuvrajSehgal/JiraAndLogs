# Annotation packet: QTBUG-96464  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Wayland client race condition in applyConfigure

When windows are repeatedly shown and hidden, xdg_surface_configure() may be called again before QWaylandXdgSurface::applyConfigure(). This causes 

ASSERT: "m_pendingConfigureSerial != 0" in file qtwayland/src/plugins/shellintegration/xdg-shell/qwaylandxdgshell.cpp, line 351

 

To reproduce: Run the example from QTBUG-87624 with the fix for that bug. Do this in a small compositor window so that the overlay window is always shown under the mouse. This will cause it to be repeatedly shown and hidden.
```

## Fix commit message(s)

`430ab36bb48e`

```
Wayland client: Don't applyConfigure for destroyed surface

If a window is rapidly hidden and re-shown multiple times, the configure
for a deleted wl_surface may be invoked after a new surface has been
created. This change makes sure we always reset mWaitingToApplyConfigure
before a new wl_surface is created. The superfluous applyConfigure
invocation will then be safely ignored.

Fixes: QTBUG-96464
Pick-to: 6.2
Change-Id: Ie2d718f77dc8de93674c6b86b5128c4f50414df1
Reviewed-by: Vlad Zahorodnii <vlad.zahorodnii@kde.org>
Reviewed-by: David Edmundson <davidedmundson@kde.org>
```

## Files the fix changed

Snapshot holds 130 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/plugins/platforms/wayland/qwaylandwindow.cpp`

## The fix diff

### `src/plugins/platforms/wayland/qwaylandwindow.cpp`

```diff
diff --git a/src/plugins/platforms/wayland/qwaylandwindow.cpp b/src/plugins/platforms/wayland/qwaylandwindow.cpp
index 2ca45259f72..a708afcedc0 100644
--- a/src/plugins/platforms/wayland/qwaylandwindow.cpp
+++ b/src/plugins/platforms/wayland/qwaylandwindow.cpp
@@ -259,10 +259,11 @@ void QWaylandWindow::reset()
     }
 
     mFrameCallbackElapsedTimer.invalidate();
     mWaitingForFrameCallback = false;
     mFrameCallbackTimedOut = false;
+    mWaitingToApplyConfigure = false;
 
     mMask = QRegion();
     mQueuedBuffer = nullptr;
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
