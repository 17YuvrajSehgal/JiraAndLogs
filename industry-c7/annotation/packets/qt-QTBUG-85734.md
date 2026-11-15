# Annotation packet: QTBUG-85734  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Crashes in qwindows.dll under WINE

Qt crashes in qwindows.dll. QWindowTheme::instance() is null when refreshFonts() is called. Looks like here [https://github.com/qt/qtbase/blob/dev/src/plugins/platforms/windows/qwindowsscreen.cpp#L572]
```

## Fix commit message(s)

`beb3916858dc`

```
Windows QPA: Potential crash fix for Wine

Add a check for theme instance.

Pick-to: 5.15
Fixes: QTBUG-85734
Change-Id: I10aced73379cd5e0b49d5cee08ceead060397a54
Reviewed-by: Oliver Wolff <oliver.wolff@qt.io>
```

## Files the fix changed

Snapshot holds 5,967 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/plugins/platforms/windows/qwindowsscreen.cpp`

## The fix diff

### `src/plugins/platforms/windows/qwindowsscreen.cpp`

```diff
diff --git a/src/plugins/platforms/windows/qwindowsscreen.cpp b/src/plugins/platforms/windows/qwindowsscreen.cpp
index 34e9e8fe310..a15a39c2a45 100644
--- a/src/plugins/platforms/windows/qwindowsscreen.cpp
+++ b/src/plugins/platforms/windows/qwindowsscreen.cpp
@@ -567,12 +567,14 @@ bool QWindowsScreenManager::handleScreenChanges()
         for (int i = m_screens.size() - 1; i >= 0; --i) {
             if (indexOfMonitor(newDataList, m_screens.at(i)->data().name) == -1)
                 removeScreen(i);
         }     // for existing screens
     }     // not lock screen
-    if (primaryScreenChanged)
-        QWindowsTheme::instance()->refreshFonts();
+    if (primaryScreenChanged) {
+        if (auto theme = QWindowsTheme::instance()) // QTBUG-85734/Wine
+            theme->refreshFonts();
+    }
     QHighDpiScaling::updateHighDpiScaling();
     return true;
 }
 
 void QWindowsScreenManager::clearScreens()
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
