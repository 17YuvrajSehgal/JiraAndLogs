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
(empty)
```

## Files the fix changed

Snapshot holds 130 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/plugins/platforms/wayland/qwaylandwindow.cpp`

## The fix diff

### `src/plugins/platforms/wayland/qwaylandwindow.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
