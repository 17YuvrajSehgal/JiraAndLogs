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
Windows: Fix QPainter warnings when using some fonts

Some fonts, like Segoe UI, have empty glyphs defined for
characters such as space. When there is a margin on the glyphs,
we would previously render them as 4x4 completely transparent
images. This is a waste of time, and in the case of DirectWrite,
we fixed it in bb67c3b68b00fb2075a971f4f0d58e1867ef7128 so that
it will always return an invalid image when the glyph does not
have dimensions.

But since we did not account for this in alphaMapBoundingBox(),
the texture glyph cache did not detect this case and would
request the empty image and try to add it to the cache.

Fixes: QTBUG-84629
Pick-to: 5.15
Change-Id: I470a4a55577c5e9239bf77de81c2b381bf8e6a49
Reviewed-by: Alessandro Portale <alessandro.portale@qt.io>
```

## Files the fix changed

Snapshot holds 6,149 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/platformsupport/fontdatabases/windows/qwindowsfontenginedirectwrite.cpp`

## The fix diff

### `src/platformsupport/fontdatabases/windows/qwindowsfontenginedirectwrite.cpp`

```diff
diff --git a/src/platformsupport/fontdatabases/windows/qwindowsfontenginedirectwrite.cpp b/src/platformsupport/fontdatabases/windows/qwindowsfontenginedirectwrite.cpp
index 6070d59a3e5..4c1bfc4d43f 100644
--- a/src/platformsupport/fontdatabases/windows/qwindowsfontenginedirectwrite.cpp
+++ b/src/platformsupport/fontdatabases/windows/qwindowsfontenginedirectwrite.cpp
@@ -1044,10 +1044,13 @@ glyph_metrics_t QWindowsFontEngineDirectWrite::alphaMapBoundingBox(glyph_t glyph
         glyphAnalysis->GetAlphaTextureBounds(DWRITE_TEXTURE_CLEARTYPE_3x1, &rect);
         glyphAnalysis->Release();
 
         int margin = glyphMargin(format);
 
+        if (rect.left == rect.right || rect.top == rect.bottom)
+            return glyph_metrics_t();
+
         return glyph_metrics_t(rect.left,
                                rect.top,
                                rect.right - rect.left + margin * 2,
                                rect.bottom - rect.top + margin * 2,
                                bbox.xoff, bbox.yoff);
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
