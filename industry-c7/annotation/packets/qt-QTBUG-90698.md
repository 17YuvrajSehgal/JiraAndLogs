# Annotation packet: QTBUG-90698  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
tst_QTextLayout::softHyphens() failed on macos 11 in CI

http://coin/coin/integration/qt/qtbase/tasks/web_qt_qtbase_1611780670491

qt5: https://codereview.qt-project.org/c/qt/qt5/+/331835
qtbase dev: 71e3857f7c1ea94c711a773c689762f580d1e0d5

http://coin/coin/api/results/qt/qtbase/f693a68580dbe384c40ec9d1f167c92e145823d7/MacOSMacOS_11_00x86_64MacOSMacOS_11_00x86_64Clangqtci-macos-11.0-x86_64-100-dee26fSccache_TestOnly/31a7e3d5295ed48600fb49a9937b7b6ede945b1c/test_1611780705/log.txt.gz

{code}
agent:2021/01/27 21:15:06 build.go:379: 341: Test command: /Applications/CMake.app/Contents/bin/cmake "-P" "/Users/qt/work/qt/qtbase_standalone_tests/tests/auto/gui/text/qtextlayout/tst_qtextlayoutWrapperRelWithDebInfo.cmake"
agent:2021/01/27 21:15:06 build.go:379: 341: Test timeout computed to be: 1500
agent:2021/01/27 21:15:06 build.go:379: 341: ********* Start testing of tst_QTextLayout *********
agent:2021/01/27 21:15:06 build.go:379: 341: Config: Using QtTest library 6.1.0, Qt 6.1.0 (x86_64-little_endian-lp64 shared (dynamic) release build; by Clang 12.0.0 (clang-1200.0.32.28) (Apple)), macos 11.0
agent:2021/01/27 21:15:06 build.go:379: 341: PASS   : tst_QTextLayout::initTestCase()
...
agent:2021/01/27 21:15:07 build.go:379: 341: FAIL!  : tst_QTextLayout::softHyphens() Compared values are not the same
agent:2021/01/27 21:15:07 build.go:379: 341:    Actual   (line.textLength()): 4
agent:2021/01/27 21:15:07 build.go:379: 341:    Expected (5)                : 5
agent:2021/01/27 21:15:07 build.go:379: 341:    Loc: [/Users/qt/work/qt/qtbase/tests/auto/gui/text/qtextlayout/tst_qtextlayout.cpp(2431)]
agent:2021/01/27 21:15:07 build.go:379: 341: PASS   : tst_QTextLayout::min_maximumWidth()
agent:2021/01/27 21:15:07 build.go:379: 341: PASS   : tst_QTextLayout::cleanupTestCase()
agent:2021/01/27 21:15:07 build.go:379: 341: Totals: 148 passed, 1 failed, 0 skipped, 0 blacklisted, 1397ms
agent:2021/01/27 21:15:07 build.go:379: 341: ********* Finished testing of tst_QTextLayout *********
{code}
```

## Fix commit message(s)

`0ffdbb21261e`

```
Handle macOS 11 issues in softHyphens test

Calculate the effective width of the hyphen better, and compare with
ceiled sizes.

Pick-to: 6.1 6.0
Fixes: QTBUG-90698
Change-Id: I7ed2eb44c54240ecb2f8a38e5acf1f32608b2bfb
Reviewed-by: Eskil Abrahamsen Blomfeldt <eskil.abrahamsen-blomfeldt@qt.io>
```

## Files the fix changed

Snapshot holds 5,876 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/gui/text/qtextengine.cpp`

## The fix diff

### `src/gui/text/qtextengine.cpp`

```diff
diff --git a/src/gui/text/qtextengine.cpp b/src/gui/text/qtextengine.cpp
index 28802c9bed3..675e87b3223 100644
--- a/src/gui/text/qtextengine.cpp
+++ b/src/gui/text/qtextengine.cpp
@@ -1371,13 +1371,19 @@ static void applyVisibilityRules(ushort ucs, QGlyphLayout *glyphs, uint glyphPos
         break;
     case QChar::SoftHyphen:
         if (!fontEngine->symbol) {
             // U+00AD [SOFT HYPHEN] is a default ignorable codepoint,
             // so we replace its glyph and metrics with ones for
-            // U+002D [HYPHEN-MINUS] and make it visible if it appears at line-break
+            // U+002D [HYPHEN-MINUS] or U+2010 [HYPHEN] and make
+            // it visible if it appears at line-break
             const uint engineIndex = glyphs->glyphs[glyphPosition] & 0xff000000;
-            glyphs->glyphs[glyphPosition] = fontEngine->glyphIndex('-');
+            glyph_t glyph = fontEngine->glyphIndex(0x002d);
+            if (glyph == 0)
+                glyph = fontEngine->glyphIndex(0x2010);
+            if (glyph == 0)
+                glyph = fontEngine->glyphIndex(0x00ad);
+            glyphs->glyphs[glyphPosition] = glyph;
             if (Q_LIKELY(glyphs->glyphs[glyphPosition] != 0)) {
                 glyphs->glyphs[glyphPosition] |= engineIndex;
                 QGlyphLayout tmp = glyphs->mid(glyphPosition, 1);
                 fontEngine->recalcAdvances(&tmp, { });
             }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
