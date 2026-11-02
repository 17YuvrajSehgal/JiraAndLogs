# Annotation packet: QTBUG-91061  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
[REG 6.0.1->6.1.0] qml/quick examples not compiling on iOS (Undefined symbols for architecture arm64)

Qt6.1.0 iOS binaries (117bdd98673a7db6c6e8ff79745447efbff68941) via online installer. Launch Creator and open e.g. qml/shell and compile, fails with:
{code:java}
Undefined symbols for architecture arm64:
 "qt_static_plugin_QSCNetworkReachabilityNetworkInformationBackend()", referenced from:
 StaticQSCNetworkReachabilityNetworkInformationBackendPluginInstance::StaticQSCNetworkReachabilityNetworkInformationBackendPluginInstance() in shell_plugin_import.o 
ld: symbol(s) not found for architecture arm64 
clang: error: linker command failed with exit code 1 (use -v to see invocation)
** BUILD FAILED ** 
The following build commands failed: 
Ld Debug-iphoneos/shell.app/shell normal arm64 (1 failure) 
make: *** [xcodebuild-debug-device] Error 65
{code}
Full log attached.

Reproduces with examples in qml and quick, I didn't try all of them, but with few. Examples are compiled with Qt6.0.1.

gui/analogclock does compile, and deploys to device, also some widget examples.
```

## Fix commit message(s)

`92b15beb9aa0`

```
(empty)
```

## Files the fix changed

Snapshot holds 5,881 non-test source files. The fix changed 8 file(s); 4 of them are non-test source files (listed below as gold).

- `src/network/kernel/qnetworkinformation.cpp`
- `src/network/kernel/qnetworkinformation.h`
- `src/network/kernel/qnetworkinformation_p.h`
- `src/plugins/networkinformationbackends/networkmanager/qnetworkmanagernetworkinformationbackend.cpp`

## The fix diff

### `src/network/kernel/qnetworkinformation.cpp`

```diff
(no diff retrieved)
```

### `src/network/kernel/qnetworkinformation.h`

```diff
(no diff retrieved)
```

### `src/network/kernel/qnetworkinformation_p.h`

```diff
(no diff retrieved)
```

### `src/plugins/networkinformationbackends/networkmanager/qnetworkmanagernetworkinformationbackend.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
