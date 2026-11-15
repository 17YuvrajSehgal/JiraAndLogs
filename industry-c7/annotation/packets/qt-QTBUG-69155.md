# Annotation packet: QTBUG-69155  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Android: tst_QWindow::exposeEventOnShrink_QTBUG54040 fails

{noformat}
I/QTestLib(11729): FAIL! : tst_QWindow::exposeEventOnShrink_QTBUG54040() '(window.received(QEvent::Expose) > exposeCount)' returned FALSE. ()
I/QTestLib(11729): Loc: [D:\projects\qt\clean-dev\src\qtbase\tests\auto\gui\kernel\qwindow\tst_qwindow.cpp(415)]{noformat}
```

## Fix commit message(s)

`a02ea26b469a`

```
[Android] Make sure expose events are emitted after window resize

Expose event would not be sent when window was resized

Fixes: QTBUG-69155
Pick-to: 5.15
Change-Id: I81bf2d54f830a0dabf15398e1f25b55ff7ff4479
Reviewed-by: Tor Arne Vestbø <tor.arne.vestbo@qt.io>
Reviewed-by: Rami Potinkara <rami.potinkara@qt.io>
Reviewed-by: Andy Shaw <andy.shaw@qt.io>
Reviewed-by: Heikki Halmet <heikki.halmet@qt.io>
```

## Files the fix changed

Snapshot holds 5,843 non-test source files. The fix changed 3 file(s); 2 of them are non-test source files (listed below as gold).

- `src/plugins/platforms/android/qandroidplatformopenglwindow.cpp`
- `src/plugins/platforms/android/qandroidplatformvulkanwindow.cpp`

## The fix diff

### `src/plugins/platforms/android/qandroidplatformopenglwindow.cpp`

```diff
diff --git a/src/plugins/platforms/android/qandroidplatformopenglwindow.cpp b/src/plugins/platforms/android/qandroidplatformopenglwindow.cpp
index dff7e6ec544..333fc2a25f8 100644
--- a/src/plugins/platforms/android/qandroidplatformopenglwindow.cpp
+++ b/src/plugins/platforms/android/qandroidplatformopenglwindow.cpp
@@ -105,13 +105,11 @@ void QAndroidPlatformOpenGLWindow::setGeometry(const QRect &rect)
     QAndroidPlatformWindow::setGeometry(rect);
     if (m_nativeSurfaceId != -1)
         QtAndroid::setSurfaceGeometry(m_nativeSurfaceId, rect);
 
     QRect availableGeometry = screen()->availableGeometry();
-    if (m_oldGeometry.width() == 0
-            && m_oldGeometry.height() == 0
-            && rect.width() > 0
+    if (rect.width() > 0
             && rect.height() > 0
             && availableGeometry.width() > 0
             && availableGeometry.height() > 0) {
         QWindowSystemInterface::handleExposeEvent(window(), QRect(QPoint(0, 0), rect.size()));
     }
```

### `src/plugins/platforms/android/qandroidplatformvulkanwindow.cpp`

```diff
diff --git a/src/plugins/platforms/android/qandroidplatformvulkanwindow.cpp b/src/plugins/platforms/android/qandroidplatformvulkanwindow.cpp
index cc41a871f31..6a1a51b2720 100644
--- a/src/plugins/platforms/android/qandroidplatformvulkanwindow.cpp
+++ b/src/plugins/platforms/android/qandroidplatformvulkanwindow.cpp
@@ -82,13 +82,11 @@ void QAndroidPlatformVulkanWindow::setGeometry(const QRect &rect)
     QAndroidPlatformWindow::setGeometry(rect);
     if (m_nativeSurfaceId != -1)
         QtAndroid::setSurfaceGeometry(m_nativeSurfaceId, rect);
 
     QRect availableGeometry = screen()->availableGeometry();
-    if (m_oldGeometry.width() == 0
-            && m_oldGeometry.height() == 0
-            && rect.width() > 0
+    if (rect.width() > 0
             && rect.height() > 0
             && availableGeometry.width() > 0
             && availableGeometry.height() > 0) {
         QWindowSystemInterface::handleExposeEvent(window(), QRect(QPoint(0, 0), rect.size()));
     }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
