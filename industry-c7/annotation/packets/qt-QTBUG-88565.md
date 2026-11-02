# Annotation packet: QTBUG-88565  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
error: conversion from ‘QString’ to non-scalar type ‘QFileInfo’ requested

{noformat}
src/client/CMakeFiles/WaylandClient.dir/qwaylandwindow.cpp.o.d -o src/client/CMakeFiles/WaylandClient.dir/qwaylandwindow.cpp.o -c src/client/qwaylandwindow.cpp
agent:2020/11/17 04:25:52 build.go:379: src/client/qwaylandwindow.cpp: In member function ‘void QtWaylandClient::QWaylandWindow::initWindow()’:
agent:2020/11/17 04:25:52 build.go:379: src/client/qwaylandwindow.cpp:165:81: error: conversion from ‘QString’ to non-scalar type ‘QFileInfo’ requested
agent:2020/11/17 04:25:52 build.go:379:   165 |                 QFileInfo fi = QCoreApplication::instance()->applicationFilePath();
agent:2020/11/17 04:25:52 build.go:379:       |                                ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^~
{noformat}

Build log: https://testresults.qt.io/logs/qt/qtwayland/a2b7fe3bc1b4d552bf55b95053f72a0404c25479/LinuxUbuntu_20_04x86_64LinuxUbuntu_20_04x86_64GCCqtci-linux-Ubuntu-20.04-x86_64-50-9be9a0Sccache/c510c4c754828eb7abf999c9844830ac6012aec7/build_1605587104/log.txt.gz

Details: https://testresults.qt.io/coin/integration/qt/qtwayland/tasks/1605587080

Tested changes (refs/builds/qtci/dev/1605587014):
  https://codereview.qt-project.org/c/qt/qtwayland/+/321903/4 Update dependencies on 'dev' in qt/qtwayland
```

## Fix commit message(s)

`4db304cc9e34`

```
(empty)
```

## Files the fix changed

Snapshot holds 128 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/plugins/platforms/wayland/qwaylandwindow.cpp`

## The fix diff

### `src/plugins/platforms/wayland/qwaylandwindow.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
