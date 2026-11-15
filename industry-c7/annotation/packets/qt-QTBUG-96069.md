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
Android: check if objectClass() is not null in registerNativeMethods()

In case the class doens't have a default constructor, checking for
object.isValid() will give false because the object won't be created,
however, the class could still be loaded and we could have a valid
jclass.

Pick-to: 6.2
Fixes: QTBUG-96069
Change-Id: I8d59e26d9d7c0e8e363ce443937091a374a24473
Reviewed-by: Ivan Solovev <ivan.solovev@qt.io>
```

## Files the fix changed

Snapshot holds 5,873 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/kernel/qjnienvironment.cpp`

## The fix diff

### `src/corelib/kernel/qjnienvironment.cpp`

```diff
diff --git a/src/corelib/kernel/qjnienvironment.cpp b/src/corelib/kernel/qjnienvironment.cpp
index a72078d2cf5..9766ff4d3b9 100644
--- a/src/corelib/kernel/qjnienvironment.cpp
+++ b/src/corelib/kernel/qjnienvironment.cpp
@@ -345,15 +345,16 @@ JavaVM *QJniEnvironment::javaVM()
     \endcode
 */
 bool QJniEnvironment::registerNativeMethods(const char *className, const JNINativeMethod methods[],
                                             int size)
 {
-    QJniObject classObject(className);
+    const jclass clazz = findClass(className);
 
-    if (!classObject.isValid())
+    if (!clazz)
         return false;
-    return registerNativeMethods(classObject.objectClass(), methods, size);
+
+    return registerNativeMethods(clazz, methods, size);
 }
 #if QT_DEPRECATED_SINCE(6, 2)
 /*!
     \overload
     \deprecated [6.2] Use the overload with a const JNINativeMethod[] instead.
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
