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
QMetaType: specialize typenameHelper for std::pair

The string representation of std::pair<T1,T2> is now always
"std::pair<T1,T2>". This is in line with how we translate QPair,
avoiding typename mismatches that would previoulsy occur, because the
full name of pair on libc++ was "std::__1::pair".

Fixes: QTBUG-84924
Change-Id: Ia6c044a7327d69e4b4f4a31496c6b2408d85ebb9
Reviewed-by: Qt CI Bot <qt_ci_bot@qt-project.org>
Reviewed-by: Thiago Macieira <thiago.macieira@intel.com>
```

## Files the fix changed

Snapshot holds 5,963 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/kernel/qmetatype.h`

## The fix diff

### `src/corelib/kernel/qmetatype.h`

```diff
diff --git a/src/corelib/kernel/qmetatype.h b/src/corelib/kernel/qmetatype.h
index a7916cfb137..ced3444020c 100644
--- a/src/corelib/kernel/qmetatype.h
+++ b/src/corelib/kernel/qmetatype.h
@@ -1634,10 +1634,11 @@ struct QMetaTypeId : public QMetaTypeIdQObject<T>
 };
 
 template <typename T>
 struct QMetaTypeId2
 {
+    using NameAsArrayType = void;
     enum { Defined = QMetaTypeId<T>::Defined, IsBuiltIn=false };
     static inline constexpr int qt_metatype_id() { return QMetaTypeId<T>::qt_metatype_id(); }
 };
 
 template <typename T>
@@ -1933,13 +1934,14 @@ inline int qRegisterMetaTypeStreamOperators()
 
 #define Q_DECLARE_BUILTIN_METATYPE(TYPE, METATYPEID, NAME) \
     QT_BEGIN_NAMESPACE \
     template<> struct QMetaTypeId2<NAME> \
     { \
+        using NameAsArrayType = std::array<char, sizeof(#NAME)>; \
         enum { Defined = 1, IsBuiltIn = true, MetaType = METATYPEID };   \
         static inline constexpr int qt_metatype_id() { return METATYPEID; } \
-        static constexpr const char * const name = #NAME; \
+        static constexpr NameAsArrayType nameAsArray = { #NAME }; \
     }; \
     QT_END_NAMESPACE
 
 #define QT_FORWARD_DECLARE_STATIC_TYPES_ITER(TypeName, TypeId, Name) \
     class Name;
@@ -2466,15 +2468,11 @@ public:
             appendStr("QList");
         }
 
         if (skipToken(begin, end, "QPair")) {
             // replace QPair by std::pair
-#ifdef _LIBCPP_VERSION
-            appendStr("std::" QT_STRINGIFY(_LIBCPP_ABI_NAMESPACE) "::pair");
-#else
             appendStr("std::pair");
-#endif
         }
 
         if (!hasMiddleConst) {
             // Normalize the integer types
             int numLong = 0;
@@ -2574,47 +2572,90 @@ public:
 constexpr int qNormalizeType(const char *begin, const char *end, char *output)
 {
     return QTypeNormalizer { output }.normalizeType(begin, end);
 }
 
+template<typename T>
+struct is_std_pair : std::false_type {};
+
+template <typename T1_, typename T2_>
+struct is_std_pair<std::pair<T1_, T2_>> : std::true_type {
+    using T1 = T1_;
+    using T2 = T2_;
+};
+
 template<typename T>
 constexpr auto typenameHelper()
 {
-    constexpr auto prefix = sizeof(
+    if constexpr (is_std_pair<T>::value) {
+        using T1 = typename is_std_pair<T>::T1;
+        using T2 = typename is_std_pair<T>::T2;
+        std::remove_const_t<std::conditional_t<bool (QMetaTypeId2<T1>::IsBuiltIn), typename QMetaTypeId2<T1>::NameAsArrayType, decltype(typenameHelper<T1>())>> t1Name {};
+        std::remove_const_t<std::conditional_t<bool (QMetaTypeId2<T2>::IsBuiltIn), typename QMetaTypeId2<T2>::NameAsArrayType, decltype(typenameHelper<T2>())>> t2Name {};
+        if constexpr (bool (QMetaTypeId2<T1>::IsBuiltIn) ) {
+            t1Name = QMetaTypeId2<T1>::nameAsArray;
+        } else {
+            t1Name = typenameHelper<T1>();
+        }
+        if constexpr (bool (QMetaTypeId2<T2>::IsBuiltIn) ) {
+            t2Name = QMetaTypeId2<T2>::nameAsArray;
+        } else {
+            t2Name = typenameHelper<T2>();
+        }
+        constexpr auto nonTypeDependentLen = sizeof("std::pair<,>");
+        constexpr auto t1Len = t1Name.size() - 1;
+        constexpr auto t2Len = t2Name.size() - 1;
+        constexpr auto length = nonTypeDependentLen + t1Len + t2Len;
+        std::array<char, length + 1> result {};
+        constexpr auto prefix = "std::pair<";
+        int currentLength = 0;
+        for (; currentLength < int(sizeof("std::pair<")-1); ++currentLength)
+            result[currentLength] = prefix[currentLength];
+        for (int i = 0; i < int(t1Len); ++currentLength, ++i)
+            result[currentLength] = t1Name[i];
+        result[currentLength++] = ',';
+        for (int i = 0; i < int(t2Len); ++currentLength, ++i)
+            result[currentLength] = t2Name[i];
+        result[currentLength++] = '>';
+        result[currentLength++] = '\0';
+        return result;
+    } else {
+        constexpr auto prefix = sizeof(
 #ifdef QT_NAMESPACE
-        QT_STRINGIFY(QT_NAMESPACE) "::"
+            QT_STRINGIFY(QT_NAMESPACE) "::"
 #endif
 #ifdef Q_CC_MSVC
-        "auto __cdecl QtPrivate::typenameHelper<"
+            "auto __cdecl QtPrivate::typenameHelper<"
 #elif defined(Q_CC_CLANG)
-        "auto QtPrivate::typenameHelper() [T = "
+            "auto QtPrivate::typenameHelper() [T = "
 #else
-        "constexpr auto QtPrivate::typenameHelper() [with T = "
+            "constexpr auto QtPrivate::typenameHelper() [with T = "
 #endif
-        ) - 1;
+            ) - 1;
 #ifdef Q_CC_MSVC
-    constexpr int suffix = sizeof(">(void)");
+        constexpr int suffix = sizeof(">(void)");
 #else
-    constexpr int suffix = sizeof("]");
+        constexpr int suffix = sizeof("]");
 #endif
 
 #if !(defined(Q_CC_GNU) && !defined(Q_CC_INTEL) && !defined(Q_CC_CLANG))
-    constexpr auto func = Q_FUNC_INFO;
-    constexpr const char *begin = func + prefix;
-    constexpr const char *end = func + sizeof(Q_FUNC_INFO) - suffix;
-    constexpr int len = qNormalizeType(begin, end, nullptr);
+        constexpr auto func = Q_FUNC_INFO;
+        constexpr const char *begin = func + prefix;
+        constexpr const char *end = func + sizeof(Q_FUNC_INFO) - suffix;
+        constexpr int len = qNormalizeType(begin, end, nullptr);
 #else // GCC < 8.1 did not have Q_FUNC_INFO as constexpr, and GCC 9 has a precompiled header bug
-    auto func = Q_FUNC_INFO;
-    const char *begin = func + prefix;
-    const char *end = func + sizeof(Q_FUNC_INFO) - suffix;
-    // This is an upper bound of the size since the normalized signature should always be smaller
-    // (Unless there is a QList -> QVector change, but that should not happen)
-    constexpr int len = sizeof(Q_FUNC_INFO) - suffix - prefix;
+        auto func = Q_FUNC_INFO;
+        const char *begin = func + prefix;
+        const char *end = func + sizeof(Q_FUNC_INFO) - suffix;
+        // This is an upper bound of the size since the normalized signature should always be smaller
+        // (Unless there is a QList -> QVector change, but that should not happen)
+        constexpr int len = sizeof(Q_FUNC_INFO) - suffix - prefix;
 #endif
-    std::array<char, len + 1> result {};
-    qNormalizeType(begin, end, result.data());
-    return result;
+        std::array<char, len + 1> result {};
+        qNormalizeType(begin, end, result.data());
+        return result;
+    }
 }
 
 template<typename T, typename = void>
 struct BuiltinMetaType : std::integral_constant<int, 0>
 {
@@ -2710,11 +2751,11 @@ class QMetaTypeForType
     }
 
     static constexpr const char *getName()
     {
         if constexpr (bool(QMetaTypeId2<S>::IsBuiltIn)) {
-            return QMetaTypeId2<S>::name;
+            return QMetaTypeId2<S>::nameAsArray.data();
         } else {
             return name.data();
         }
     }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
