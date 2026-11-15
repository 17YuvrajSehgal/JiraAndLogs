# Annotation packet: QTBUG-82142  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Cannot compile sources with -namespace enabled with mingw  

Steps to reproduce:
 # Download the Qt 5.15.0-alpha source package 
 # Configure with:

{noformat}
 configure -openssl -verbose -I C:\openssl\include -L C:\openssl\lib -platform win32-g++ -confirm-license -nomake tests -opengl dynamic -nomake examples -release -skip qtwebengine -skip qtwebview -skip qt3d -commercial -qtnamespace RTA -prefix C:\Users\qt\RTA\src-5.15\qtbase{noformat}
3. Build

Expected result:

Qt 5.15.0 compiles without errors.

Actual result:

The build fails with:
{noformat}
 
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/bits/shared_ptr_atomic.h: In function 'bool RTA::std::atomic_compare_exchange_weak(RTA::std::__shared_ptr<_Tp, _Lp>*, RTA::std::__shared_ptr<_Tp, _Lp>*, RTA::std::__shared_ptr<_Tp, _Lp>)':
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/bits/shared_ptr_atomic.h:321:9: error: 'move' is not a member of 'RTA::std'
    std::move(__w), memory_order_seq_cst, memory_order_seq_cst);
         ^~~~
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/bits/shared_ptr_atomic.h:321:9: note: suggested alternative:
In file included from C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/algorithm:61:0,
                 from ..\..\include/QtCore/../../src/corelib/global/qglobal.h:142,
                 from ..\..\include/QtCore/qglobal.h:1,
                 from ..\..\include/QtTest/../../src/testlib/qtestassert.h:43,
                 from ..\..\include/QtTest/qtestassert.h:1,
                 from qtestlog.cpp:40:
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/bits/stl_algobase.h:479:5: note:   'std::move'
     move(_II __first, _II __last, _OI __result)
     ^~~~
In file included from C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/memory:82:0,
                 from .moc/moc_qtestlog_p.cpp:9,
                 from qtestlog.cpp:600:
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/bits/shared_ptr_atomic.h:321:20: error: 'memory_order_seq_cst' was not declared in this scope
    std::move(__w), memory_order_seq_cst, memory_order_seq_cst);
                    ^~~~~~~~~~~~~~~~~~~~
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/bits/shared_ptr_atomic.h:321:20: note: suggested alternative:
In file included from C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/atomic:41:0,
                 from ..\..\include/QtCore/../../src/corelib/thread/qatomic_cxx11.h:45,
                 from ..\..\include/QtCore/qatomic_cxx11.h:1,
                 from ..\..\include/QtCore/../../src/corelib/thread/qbasicatomic.h:53,
                 from ..\..\include/QtCore/qbasicatomic.h:1,
                 from ..\..\include/QtCore/../../src/corelib/thread/qatomic.h:46,
                 from ..\..\include/QtCore/qatomic.h:1,
                 from ..\..\include/QtCore/../../src/corelib/global/qglobal.h:1304,
                 from ..\..\include/QtCore/qglobal.h:1,
                 from ..\..\include/QtTest/../../src/testlib/qtestassert.h:43,
                 from ..\..\include/QtTest/qtestassert.h:1,
                 from qtestlog.cpp:40:
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/bits/atomic_base.h:62:7: note:   'memory_order_seq_cst'
       memory_order_seq_cst
       ^~~~~~~~~~~~~~~~~~~~
In file included from C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/memory:84:0,
                 from .moc/moc_qtestlog_p.cpp:9,
                 from qtestlog.cpp:600:
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/backward/auto_ptr.h: In constructor 'RTA::std::__shared_ptr<_Tp, _Lp>::__shared_ptr(RTA::std::auto_ptr<_Up>&&)':
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/backward/auto_ptr.h:308:7: error: class 'RTA::std::__shared_ptr<_Tp, _Lp>' does not have any field named '_M_ptr'
     : _M_ptr(__r.get()), _M_refcount()
       ^~~~~~
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/backward/auto_ptr.h:313:46: error: 'move' is not a member of 'RTA::std'
       _M_refcount = __shared_count<_Lp>(std::move(__r));
                                              ^~~~
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/backward/auto_ptr.h:313:46: note: suggested alternative:
In file included from C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/algorithm:61:0,
                 from ..\..\include/QtCore/../../src/corelib/global/qglobal.h:142,
                 from ..\..\include/QtCore/qglobal.h:1,
                 from ..\..\include/QtTest/../../src/testlib/qtestassert.h:43,
                 from ..\..\include/QtTest/qtestassert.h:1,
                 from qtestlog.cpp:40:
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/bits/stl_algobase.h:479:5: note:   'std::move'
     move(_II __first, _II __last, _OI __result)
     ^~~~
In file included from C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/memory:84:0,
                 from .moc/moc_qtestlog_p.cpp:9,
                 from qtestlog.cpp:600:
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/backward/auto_ptr.h: In constructor 'RTA::std::shared_ptr<_Tp>::shared_ptr(RTA::std::auto_ptr<_Up>&&)':
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/backward/auto_ptr.h:321:30: error: 'move' is not a member of 'RTA::std'
     : __shared_ptr<_Tp>(std::move(__r)) { }
                              ^~~~
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/backward/auto_ptr.h:321:30: note: suggested alternative:
In file included from C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/algorithm:61:0,
                 from ..\..\include/QtCore/../../src/corelib/global/qglobal.h:142,
                 from ..\..\include/QtCore/qglobal.h:1,
                 from ..\..\include/QtTest/../../src/testlib/qtestassert.h:43,
                 from ..\..\include/QtTest/qtestassert.h:1,
                 from qtestlog.cpp:40:
C:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/bits/stl_algobase.h:479:5: note:   'std::move'
     move(_II __first, _II __last, _OI __result)
     ^~~~
mingw32-make[3]: *** [Makefile:1349: .obj/qtestlog.o] Error 1
mingw32-make[3]: Leaving directory 'C:/Users/qt/RTA/src-5.15/qtbase/src/testlib'
mingw32-make[2]: *** [Makefile:358: sub-testlib-make_first] Error 2
mingw32-make[2]: *** Waiting for unfinished jobs....
C:\Users\qt\RTA\src-5.15\qtbase\bin\moc.exe -DUNICODE -D_UNICODE -DWIN32 -DMINGW_HAS_SECURE_API=1 -DWINVER=0x0601 -D_WIN32_WINNT=0x0601 -DQT_NO_LINKED_LIST -DQT_NO_JAVA_STYLE_ITERATORS -DQT_NO_USING_NAMESPACE -DQT_NO_FOREACH -DQT_NO_NARROWING_CONVERSIONS_IN_CONNECT -DQT_BUILD_PRINTSUPPORT_LIB -DQT_BUILDING_QT -D_CRT_SECURE_NO_WARNINGS -D_USE_MATH_DEFINES -DQT_NO_CAST_TO_ASCII -DQT_ASCII_CAST_WARNINGS -DQT_MOC_COMPAT -DQT_USE_QSTRINGBUILDER -DQT_DEPRECATED_WARNINGS -DQT_DISABLE_DEPRECATED_BEFORE=0x040800 -DQT_DEPRECATED_WARNINGS_SINCE=0x060000 -DQT_NO_EXCEPTIONS -DQT_NO_DEBUG -DQT_WIDGETS_LIB -DQT_GUI_LIB -DQT_CORE_LIB -DQT_NAMESPACE=RTA --include C:/Users/qt/RTA/src-5.15/qtbase/src/printsupport/.moc/moc_predefs.h -IC:/Users/qt/RTA/src-5.15/qtbase/mkspecs/win32-g++ -IC:/Users/qt/RTA/src-5.15/qtbase/src/printsupport -IC:/Users/qt/RTA/src-5.15/qtbase/src/printsupport/widgets -IC:/Users/qt/RTA/src-5.15/qtbase/src/printsupport/dialogs -IC:/Users/qt/RTA/src-5.15/qtbase/include -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtPrintSupport -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtPrintSupport/5.15.0 -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtPrintSupport/5.15.0/QtPrintSupport -IC:/Users/qt/RTA/src-5.15/qtbase/src/printsupport/tmp -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtWidgets/5.15.0 -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtWidgets/5.15.0/QtWidgets -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtGui/5.15.0 -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtGui/5.15.0/QtGui -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtCore/5.15.0 -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtCore/5.15.0/QtCore -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtWidgets -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtGui -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtANGLE -IC:/Users/qt/RTA/src-5.15/qtbase/include/QtCore -IC:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++ -IC:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/x86_64-w64-mingw32 -IC:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include/c++/backward -IC:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include -IC:/MINGW730/mingw64/lib/gcc/x86_64-w64-mingw32/7.3.0/include-fixed -IC:/MINGW730/mingw64/x86_64-w64-mingw32/include widgets\qprintpreviewwidget.cpp -o .moc\qprintpreviewwidget.moc
g++ -c -fno-keep-inline-dllexport -O2 -std=c++1z -fno-exceptions -Wall -Wextra -Wextra -Wvla -Wdate-time -Wshift-overflow=2 -Wduplicated-cond -Wno-stringop-overflow -DUNICODE -D_UNICODE -DWIN32 -DMINGW_HAS_SECURE_API=1 -DWINVER=0x0601 -D_WIN32_WINNT=0x0601 -DQT_NO_LINKED_LIST -DQT_NO_JAVA_STYLE_ITERATORS -DQT_NO_USING_NAMESPACE -DQT_NO_FOREACH -DQT_NO_NARROWING_CONVERSIONS_IN_CONNECT -DQT_BUILD_PRINTSUPPORT_LIB -DQT_BUILDING_QT -D_CRT_SECURE_NO_WARNINGS -D_USE_MATH_DEFINES -DQT_NO_CAST_TO_ASCII -DQT_ASCII_CAST_WARNINGS -DQT_MOC_COMPAT -DQT_USE_QSTRINGBUILDER -DQT_DEPRECATED_WARNINGS -DQT_DISABLE_DEPRECATED_BEFORE=0x040800 -DQT_DEPRECATED_WARNINGS_SINCE=0x060000 -DQT_NO_EXCEPTIONS -DQT_NO_DEBUG -DQT_WIDGETS_LIB -DQT_GUI_LIB -DQT_CORE_LIB -DQT_NAMESPACE=RTA -I. -Iwidgets -Idialogs -I..\..\include -I..\..\include\QtPrintSupport -I..\..\include\QtPrintSupport\5.15.0 -I..\..\include\QtPrintSupport\5.15.0\QtPrintSupport -Itmp -I..\..\include\QtWidgets\5.15.0 -I..\..\include\QtWidgets\5.15.0\QtWidgets -I..\..\include\QtGui\5.15.0 -I..\..\include\QtGui\5.15.0\QtGui -I..\..\include\QtCore\5.15.0 -I..\..\include\QtCore\5.15.0\QtCore -I..\..\include\QtWidgets -I..\..\include\QtGui -I..\..\include\QtANGLE -I..\..\include\QtCore -I.moc -I.uic -IC:\VulkanSDK\1.0.51.0\include -IC:\openssl\include -I..\..\mkspecs\win32-g++  -o .obj\qprintpreviewdialog.o dialogs\qprintpreviewdialog.cpp
g++ -c -fno-keep-inline-dllexport -O2 -std=c++1z -fno-exceptions -Wall -Wextra -Wextra -Wvla -Wdate-time -Wshift-overflow=2 -Wduplicated-cond -Wno-stringop-overflow -DUNICODE -D_UNICODE -DWIN32 -DMINGW_HAS_SECURE_API=1 -DWINVER=0x0601 -D_WIN32_WINNT=0x0601 -DQT_NO_LINKED_LIST -DQT_NO_JAVA_STYLE_ITERATORS -DQT_NO_USING_NAMESPACE -DQT_NO_FOREACH -DQT_NO_NARROWING_CONVERSIONS_IN_CONNECT -DQT_BUILD_PRINTSUPPORT_LIB -DQT_BUILDING_QT -D_CRT_SECURE_NO_WARNINGS -D_USE_MATH_DEFINES -DQT_NO_CAST_TO_ASCII -DQT_ASCII_CAST_WARNINGS -DQT_MOC_COMPAT -DQT_USE_QSTRINGBUILDER -DQT_DEPRECATED_WARNINGS -DQT_DISABLE_DEPRECATED_BEFORE=0x040800 -DQT_DEPRECATED_WARNINGS_SINCE=0x060000 -DQT_NO_EXCEPTIONS -DQT_NO_DEBUG -DQT_WIDGETS_LIB -DQT_GUI_LIB -DQT_CORE_LIB -DQT_NAMESPACE=RTA -I. -Iwidgets -Idialogs -I..\..\include -I..\..\include\QtPrintSupport -I..\..\include\QtPrintSupport\5.15.0 -I..\..\include\QtPrintSupport\5.15.0\QtPrintSupport -Itmp -I..\..\include\QtWidgets\5.15.0 -I..\..\include\QtWidgets\5.15.0\QtWidgets -I..\..\include\QtGui\5.15.0 -I..\..\include\QtGui\5.15.0\QtGui -I..\..\include\QtCore\5.15.0 -I..\..\include\QtCore\5.15.0\QtCore -I..\..\include\QtWidgets -I..\..\include\QtGui -I..\..\include\QtANGLE -I..\..\include\QtCore -I.moc -I.uic -IC:\VulkanSDK\1.0.51.0\include -IC:\openssl\include -I..\..\mkspecs\win32-g++  -o .obj\qprintpreviewwidget.o widgets\qprintpreviewwidget.cpp
g++ -Wl,-s -shared -Wl,-subsystem,windows -Wl,--out-implib,C:\Users\qt\RTA\src-5.15\qtbase\lib\libQt5OpenGL.a -o ..\..\lib\Qt5OpenGL.dll @object_script.Qt5OpenGL  -LC:\openssl\lib C:\Users\qt\RTA\src-5.15\qtbase\lib\libQt5Widgets.a C:\Users\qt\RTA\src-5.15\qtbase\lib\libQt5Gui.a C:\Users\qt\RTA\src-5.15\qtbase\lib\libQt5Core.a .obj\Qt5OpenGL_resource_res.o   
copy /y ..\..\lib\Qt5OpenGL.dll ..\..\bin
        1 file(s) copied.
mingw32-make[3]: Leaving directory 'C:/Users/qt/RTA/src-5.15/qtbase/src/opengl'
g++ -Wl,-s -shared -Wl,-subsystem,windows -Wl,--out-implib,C:\Users\qt\RTA\src-5.15\qtbase\lib\libQt5PrintSupport.a -o ..\..\lib\Qt5PrintSupport.dll @object_script.Qt5PrintSupport  -LC:\openssl\lib C:\Users\qt\RTA\src-5.15\qtbase\lib\libQt5Widgets.a C:\Users\qt\RTA\src-5.15\qtbase\lib\libQt5Gui.a C:\Users\qt\RTA\src-5.15\qtbase\lib\libQt5Core.a .obj\Qt5PrintSupport_resource_res.o -lwinspool -lcomdlg32 -luser32 -lgdi32  
copy /y ..\..\lib\Qt5PrintSupport.dll ..\..\bin
        1 file(s) copied.
mingw32-make[3]: Leaving directory 'C:/Users/qt/RTA/src-5.15/qtbase/src/printsupport'
mingw32-make[2]: Leaving directory 'C:/Users/qt/RTA/src-5.15/qtbase/src'
mingw32-make[1]: *** [Makefile:54: sub-src-make_first] Error 2
mingw32-make[1]: Leaving directory 'C:/Users/qt/RTA/src-5.15/qtbase'
mingw32-make: *** [Makefile:88: module-qtbase-make_first] Error 2{noformat}
Find the configure and build outputs attached.
```

## Fix commit message(s)

`2a10a6f6d423`

```
Fix namespaced build of QTestLib

This amends 93b8cdc974e584d80dbaabf459610a555af25b81

Fixes: QTBUG-82142
Change-Id: Id77a35a1e1c244b6778159e85b50728f2e4103db
Reviewed-by: Tor Arne Vestbø <tor.arne.vestbo@qt.io>
```

## Files the fix changed

Snapshot holds 6,967 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/testlib/qtestlog.cpp`

## The fix diff

### `src/testlib/qtestlog.cpp`

```diff
diff --git a/src/testlib/qtestlog.cpp b/src/testlib/qtestlog.cpp
index 7bd108ab00c..a3887805324 100644
--- a/src/testlib/qtestlog.cpp
+++ b/src/testlib/qtestlog.cpp
@@ -595,8 +595,8 @@ qint64 QTestLog::nsecsTotalTime()
 qint64 QTestLog::nsecsFunctionTime()
 {
     return elapsedFunctionTime.nsecsElapsed();
 }
 
-#include "moc_qtestlog_p.cpp"
-
 QT_END_NAMESPACE
+
+#include "moc_qtestlog_p.cpp"
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
