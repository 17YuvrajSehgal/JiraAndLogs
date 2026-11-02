# Annotation packet: QTBUG-68636  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Some popups (i.e.) menus are misplaced on gnome-shell

On gnome-shell, in some widget applications, if one menu is opened while another is being closed, it's positioned in the top-left corner instead of the expected position.

-This issue does not occur with the mainwindow or menus examples, but happens with qtcreator. Please add a comment if you know about a simpler example that exposes the issue.-

The issue happens when a QMenu is created without a parent, i.e. QWidget::parentWidget() == nullptr

There are no such issues on weston or kwin. As far as I know, it only happens on gnome-shell.
```

## Fix commit message(s)

`493a85a9e468`

```
Widgets: setTransientParent() when a QMenu is a window

On some platforms, such as X11 and Wayland with some compositors,
QMenu could be a popup window, which should be set a transient parent
to get relative position, which is requested by Wayland.

Added transientParentWindow() for QMenuPrivate like QDialogPrivate.

Fixes: QTBUG-68636
Pick-to: 6.2
Change-Id: I6d8880cb008ecf61a4c005898b38e3953379a13d
Reviewed-by: Volker Hilsheimer <volker.hilsheimer@qt.io>
```

## Files the fix changed

Snapshot holds 5,901 non-test source files. The fix changed 3 file(s); 2 of them are non-test source files (listed below as gold).

- `src/widgets/widgets/qmenu.cpp`
- `src/widgets/widgets/qmenu_p.h`

## The fix diff

### `src/widgets/widgets/qmenu.cpp`

```diff
diff --git a/src/widgets/widgets/qmenu.cpp b/src/widgets/widgets/qmenu.cpp
index 5ecac2c7c6e..c6d1dd0e7ec 100644
--- a/src/widgets/widgets/qmenu.cpp
+++ b/src/widgets/widgets/qmenu.cpp
@@ -623,10 +623,33 @@ void QMenuPrivate::hideMenu(QMenu *menu)
     menu->d_func()->causedPopup.action = nullptr;
     menu->close();
     menu->d_func()->causedPopup.widget = nullptr;
 }
 
+QWindow *QMenuPrivate::transientParentWindow() const
+{
+    Q_Q(const QMenu);
+    if (const QWidget *parent = q->nativeParentWidget()) {
+        if (parent->windowHandle())
+            return parent->windowHandle();
+    }
+
+    if (const QWindow *w = q->windowHandle()) {
+        if (w->transientParent())
+            return w->transientParent();
+    }
+
+    if (causedPopup.widget) {
+        if (const QWidget *w = causedPopup.widget.data()) {
+            if (const QWidget *ww = w->window())
+                return ww->windowHandle();
+        }
+    }
+
+    return nullptr;
+}
+
 void QMenuPrivate::popupAction(QAction *action, int delay, bool activateFirst)
 {
     Q_Q(QMenu);
     if (action) {
         if (action->isEnabled()) {
@@ -2981,10 +3004,12 @@ bool QMenu::event(QEvent *e)
         QMenuPrivate::mouseDown = nullptr;
         d->updateActionRects();
         d->sloppyState.reset();
         if (d->currentAction)
             d->popupAction(d->currentAction, 0, false);
+        if (isWindow() && window() && window()->windowHandle() && !window()->windowHandle()->transientParent())
+            window()->windowHandle()->setTransientParent(d->transientParentWindow());
         break;
 #if QT_CONFIG(tooltip)
     case QEvent::ToolTip:
         if (d->toolTipsVisible) {
             const QHelpEvent *ev = static_cast<const QHelpEvent*>(e);
```

### `src/widgets/widgets/qmenu_p.h`

```diff
diff --git a/src/widgets/widgets/qmenu_p.h b/src/widgets/widgets/qmenu_p.h
index ffe956d007a..bad9c294f8c 100644
--- a/src/widgets/widgets/qmenu_p.h
+++ b/src/widgets/widgets/qmenu_p.h
@@ -438,10 +438,11 @@ public:
     };
     virtual QList<QPointer<QWidget>> calcCausedStack() const;
     QMenuCaused causedPopup;
     void hideUpToMenuBar();
     void hideMenu(QMenu *menu);
+    QWindow *transientParentWindow() const;
 
     //index mappings
     inline QAction *actionAt(int i) const { return q_func()->actions().at(i); }
     inline int indexOf(QAction *act) const { return q_func()->actions().indexOf(act); }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
