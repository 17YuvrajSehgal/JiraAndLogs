# Annotation packet: QTBUG-91401  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Error loading PNG: Unsupported ICC profile class 70727472

Steps to reproduce:
- Launch examples/widgets/widgets/imageviewer
- Open attached png
- Observe warnings

Occurs when trying to load an image with an alpha channel
{noformat}
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
{noformat}
```

## Fix commit message(s)

`63152571844a`

```
(empty)
```

## Files the fix changed

Snapshot holds 5,896 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `src/gui/image/qpnghandler.cpp`
- `src/gui/painting/qicc.cpp`

## The fix diff

### `src/gui/image/qpnghandler.cpp`

```diff
(no diff retrieved)
```

### `src/gui/painting/qicc.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
