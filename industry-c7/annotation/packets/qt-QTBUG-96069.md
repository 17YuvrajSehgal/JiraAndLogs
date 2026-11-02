# Annotation packet: QTBUG-96069  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Qt 6.2.0 Beta3 runtime link error when run multimediawidgets sample on android arm

 

Steps to reproduce

1.) Open qt 6.2.0 multimediawidgets.pro sample

2.) Configure for Qt_6_2_0_Clang_armeabi_v7a

3.) Build and run

Application Stops because of

W System.err: java.lang.NoSuchMethodError: no non-static method "Lorg/qtproject/qt/android/multimedia/QtAndroidMediaPlayer;.<init>()V"

And

E AndroidRuntime: FATAL EXCEPTION: qtMainLoopThread
E AndroidRuntime: Process: org.qtproject.example.camera, PID: 30583
E AndroidRuntime: java.lang.UnsatisfiedLinkError: JNI_ERR returned from JNI_OnLoad in "/data/app/org.qtproject.example.camera-1/lib/arm/libQt6Multimedia_armeabi-v7a.so"
```

## Fix commit message(s)

`dfb4b7856a82`

```
(empty)
```

## Files the fix changed

Snapshot holds 5,873 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/kernel/qjnienvironment.cpp`

## The fix diff

### `src/corelib/kernel/qjnienvironment.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
