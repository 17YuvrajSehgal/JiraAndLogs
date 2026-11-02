# Annotation packet: QTBUG-84629  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
REG: Warnings when drawing text with DirectWrite

After bb67c3b68b00fb2075a971f4f0d58e1867ef7128, Qt Widgets applications may see warnings like this:

{code}
QPainter::begin: Paint device returned engine == 0, type: 3
QPainter::setCompositionMode: Painter not active
QPainter::end: Painter not active, aborted
{code}

This seems to be because we in certain cases before would return a blank image consisting only of margins, but since we now respect the glyph margins in the font engine, we return an invalid image instead.
```

## Fix commit message(s)

`c2dcb7eaa192`

```
(empty)
```

## Files the fix changed

Snapshot holds 6,149 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/platformsupport/fontdatabases/windows/qwindowsfontenginedirectwrite.cpp`

## The fix diff

### `src/platformsupport/fontdatabases/windows/qwindowsfontenginedirectwrite.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
