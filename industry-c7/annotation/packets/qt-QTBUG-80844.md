# Annotation packet: QTBUG-80844  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Redraw problem with screen mirror

env: macbook pro 15 2019 with macOS 10.15.2, monitor DELL P2417H connected via HDMI. macOS settings for displays: Mirror Displays

Launch qt app on macOS, e.g. qt creator,  connect or disconnect monitor and then move mouse over app -> some problems with main window updating
```

## Fix commit message(s)

`7ac4e55cb979`

```
(empty)
```

## Files the fix changed

Snapshot holds 6,981 non-test source files. The fix changed 5 file(s); 5 of them are non-test source files (listed below as gold).

- `src/plugins/platforms/cocoa/qcocoabackingstore.h`
- `src/plugins/platforms/cocoa/qcocoabackingstore.mm`
- `src/plugins/platforms/cocoa/qcocoaintegration.mm`
- `src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.h`
- `src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.mm`

## The fix diff

### `src/plugins/platforms/cocoa/qcocoabackingstore.h`

```diff
(no diff retrieved)
```

### `src/plugins/platforms/cocoa/qcocoabackingstore.mm`

```diff
(no diff retrieved)
```

### `src/plugins/platforms/cocoa/qcocoaintegration.mm`

```diff
(no diff retrieved)
```

### `src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.h`

```diff
(no diff retrieved)
```

### `src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.mm`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
