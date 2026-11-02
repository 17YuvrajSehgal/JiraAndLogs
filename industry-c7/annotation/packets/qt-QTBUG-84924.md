# Annotation packet: QTBUG-84924  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
moc_qnetworkreplyhttpimpl_p.cpp build failed for android on macos

https://codereview.qt-project.org/c/qt/qt5/+/304063 Update submodules on 'dev' in qt/qt5

https://testresults.qt.io/coin/integration/qt/qt5/tasks/1591893317

https://testresults.qt.io/coin/api/results/qt/qtbase/bf381ad746b5186c0cc26b2de744a191443d4f3a/MacOSMacOS_10_14x86_64AndroidAndroid_ANYmultiClangqtci-macos-10.14-x86_64-e0be02DisableTests_UseLegacyInstructions/c8ed89fca0a4ee8fc5d9878f967b403ba5463bbc/build_1591893392/log.txt.gz

{code}
agent:2020/06/11 16:46:52 build.go:253: .moc/x86_64/moc_qnetworkreplyhttpimpl_p.cpp:235:87: error: no member named '__1' in namespace 'std'
agent:2020/06/11 16:46:52 build.go:253:         case 15: _t->d_func()->replyDownloadMetaData((*reinterpret_cast< QVector<std::__1::pair<QByteArray,QByteArray>>(*)>(_a[1])),(*reinterpret_cast< int(*)>(_a[2])),(*reinterpret_cast< QString(*)>(_a[3])),(*reinterpret_cast< bool(*)>(_a[4])),(*reinterpret_cast< QSharedPointer<char>(*)>(_a[5])),(*reinterpret_cast< qint64(*)>(_a[6])),(*reinterpret_cast< qint64(*)>(_a[7])),(*reinterpret_cast< bool(*)>(_a[8]))); break;
agent:2020/06/11 16:46:52 build.go:253:                                                                                  ~~~~~^
agent:2020/06/11 16:46:52 build.go:253: .moc/x86_64/moc_qnetworkreplyhttpimpl_p.cpp:235:97: error: 'QByteArray' does not refer to a value
agent:2020/06/11 16:46:52 build.go:253:         case 15: _t->d_func()->replyDownloadMetaData((*reinterpret_cast< QVector<std::__1::pair<QByteArray,QByteArray>>(*)>(_a[1])),(*reinterpret_cast< int(*)>(_a[2])),(*reinterpret_cast< QString(*)>(_a[3])),(*reinterpret_cast< bool(*)>(_a[4])),(*reinterpret_cast< QSharedPointer<char>(*)>(_a[5])),(*reinterpret_cast< qint64(*)>(_a[6])),(*reinterpret_cast< qint64(*)>(_a[7])),(*reinterpret_cast< bool(*)>(_a[8]))); break;
agent:2020/06/11 16:46:52 build.go:253:                                                                                                 ^
agent:2020/06/11 16:46:52 build.go:253: ../../include/QtNetwork/../../src/network/access/qnetworkaccessmanager.h:59:7: note: declared here
agent:2020/06/11 16:46:52 build.go:253: class QByteArray;
agent:2020/06/11 16:46:52 build.go:253:       ^
agent:2020/06/11 16:46:52 build.go:253: .moc/x86_64/moc_qnetworkreplyhttpimpl_p.cpp:235:125: error: type-id cannot have a name
agent:2020/06/11 16:46:52 build.go:253:         case 15: _t->d_func()->replyDownloadMetaData((*reinterpret_cast< QVector<std::__1::pair<QByteArray,QByteArray>>(*)>(_a[1])),(*reinterpret_cast< int(*)>(_a[2])),(*reinterpret_cast< QString(*)>(_a[3])),(*reinterpret_cast< bool(*)>(_a[4])),(*reinterpret_cast< QSharedPointer<char>(*)>(_a[5])),(*reinterpret_cast< qint64(*)>(_a[6])),(*reinterpret_cast< qint64(*)>(_a[7])),(*reinterpret_cast< bool(*)>(_a[8]))); break;
agent:2020/06/11 16:46:52 build.go:253:                                                                                                                             ^~
agent:2020/06/11 16:46:52 build.go:253: .moc/x86_64/moc_qnetworkreplyhttpimpl_p.cpp:235:131: error: expected '>'
agent:2020/06/11 16:46:52 build.go:253:         case 15: _t->d_func()->replyDownloadMetaData((*reinterpret_cast< QVector<std::__1::pair<QByteArray,QByteArray>>(*)>(_a[1])),(*reinterpret_cast< int(*)>(_a[2])),(*reinterpret_cast< QString(*)>(_a[3])),(*reinterpret_cast< bool(*)>(_a[4])),(*reinterpret_cast< QSharedPointer<char>(*)>(_a[5])),(*reinterpret_cast< qint64(*)>(_a[6])),(*reinterpret_cast< qint64(*)>(_a[7])),(*reinterpret_cast< bool(*)>(_a[8]))); break;
agent:2020/06/11 16:46:52 build.go:253:                                                                                                                                   ^
agent:2020/06/11 16:46:52 build.go:253:                                                                                                                                   >
agent:2020/06/11 16:46:52 build.go:253: .moc/x86_64/moc_qnetworkreplyhttpimpl_p.cpp:235:72: note: to match this '<'
agent:2020/06/11 16:46:52 build.go:253:         case 15: _t->d_func()->replyDownloadMetaData((*reinterpret_cast< QVector<std::__1::pair<QByteArray,QByteArray>>(*)>(_a[1])),(*reinterpret_cast< int(*)>(_a[2])),(*reinterpret_cast< QString(*)>(_a[3])),(*reinterpret_cast< bool(*)>(_a[4])),(*reinterpret_cast< QSharedPointer<char>(*)>(_a[5])),(*reinterpret_cast< qint64(*)>(_a[6])),(*reinterpret_cast< qint64(*)>(_a[7])),(*reinterpret_cast< bool(*)>(_a[8]))); break;
agent:2020/06/11 16:46:52 build.go:253:                                                                        ^
{code}
```

## Fix commit message(s)

`a2cec17407b8`

```
(empty)
```

## Files the fix changed

Snapshot holds 5,963 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/kernel/qmetatype.h`

## The fix diff

### `src/corelib/kernel/qmetatype.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
