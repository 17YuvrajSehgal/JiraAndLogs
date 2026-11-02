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
(empty)
```

## Files the fix changed

Snapshot holds 6,149 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/kernel/qeventdispatcher_win.cpp`

## The fix diff

### `src/corelib/kernel/qeventdispatcher_win.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
