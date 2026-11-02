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
(empty)
```

## Files the fix changed

Snapshot holds 6,971 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/io/qsettings.cpp`

## The fix diff

### `src/corelib/io/qsettings.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
