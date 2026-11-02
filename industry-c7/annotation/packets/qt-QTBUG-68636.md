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
(empty)
```

## Files the fix changed

Snapshot holds 5,901 non-test source files. The fix changed 3 file(s); 2 of them are non-test source files (listed below as gold).

- `src/widgets/widgets/qmenu.cpp`
- `src/widgets/widgets/qmenu_p.h`

## The fix diff

### `src/widgets/widgets/qmenu.cpp`

```diff
(no diff retrieved)
```

### `src/widgets/widgets/qmenu_p.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
