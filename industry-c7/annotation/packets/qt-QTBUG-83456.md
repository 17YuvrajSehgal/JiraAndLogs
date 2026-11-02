# Annotation packet: QTBUG-83456  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
QMake: qt.conf ignored if it contains BOM

Example:
{code:java}
$ file qt.conf
qt.conf: UTF-8 Unicode (with BOM) text

$ cat qt.conf
[Paths]
Prefix = /foo/bar

$ ./qmake -query QT_INSTALL_PREFIX   # expected: /foo/bar
/home/jil/Qt/5.14.2/gcc_64/bin{code}
```

## Fix commit message(s)

`9ba09e26d7fc`

```
QSettings: Read past UTF-8 BOM even without textcodec support

Try to read past an UTF-8 BOM even if no textcodec support is available,
but do set the status to FormatError then.

This is in line with the general 'best effort' approach in QSettings.
It also allows qmake (that is built without textcodec support) to
gracefully load qt.conf files with a UTF-8 BOM, though non-Latin1
characters might still be misrepresented.

Fixes: QTBUG-83456
Change-Id: I31b45dc5a8adf7950910897a2b33ae16990d3818
Reviewed-by: Thiago Macieira <thiago.macieira@intel.com>
Reviewed-by: Joerg Bornemann <joerg.bornemann@qt.io>
```

## Files the fix changed

Snapshot holds 6,971 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/io/qsettings.cpp`

## The fix diff

### `src/corelib/io/qsettings.cpp`

```diff
diff --git a/src/corelib/io/qsettings.cpp b/src/corelib/io/qsettings.cpp
index b191397e7ee..c69ec908edc 100644
--- a/src/corelib/io/qsettings.cpp
+++ b/src/corelib/io/qsettings.cpp
@@ -1671,18 +1671,20 @@ bool QConfFileSettingsPrivate::readIniFile(const QByteArray &data,
     int equalsPos;
     int position = 0;
     int sectionPosition = 0;
     bool ok = true;
 
-#if QT_CONFIG(textcodec)
     // detect utf8 BOM
     const uchar *dd = (const uchar *)data.constData();
     if (data.size() >= 3 && dd[0] == 0xef && dd[1] == 0xbb && dd[2] == 0xbf) {
+#if QT_CONFIG(textcodec)
         iniCodec = QTextCodec::codecForName("UTF-8");
+#else
+        ok = false;
+#endif
         dataPos = 3;
     }
-#endif
 
     while (readIniLine(data, dataPos, lineStart, lineLen, equalsPos)) {
         char ch = data.at(lineStart);
         if (ch == '[') {
             FLUSH_CURRENT_SECTION();
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
