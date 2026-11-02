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
(empty)
```

## Files the fix changed

Snapshot holds 5,967 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/plugins/platforms/windows/qwindowsscreen.cpp`

## The fix diff

### `src/plugins/platforms/windows/qwindowsscreen.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
