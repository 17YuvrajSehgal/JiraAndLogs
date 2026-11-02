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
(empty)
```

## Files the fix changed

Snapshot holds 5,843 non-test source files. The fix changed 3 file(s); 2 of them are non-test source files (listed below as gold).

- `src/plugins/platforms/android/qandroidplatformopenglwindow.cpp`
- `src/plugins/platforms/android/qandroidplatformvulkanwindow.cpp`

## The fix diff

### `src/plugins/platforms/android/qandroidplatformopenglwindow.cpp`

```diff
(no diff retrieved)
```

### `src/plugins/platforms/android/qandroidplatformvulkanwindow.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
