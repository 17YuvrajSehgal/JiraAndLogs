# Annotation packet: QTBUG-83207  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Mutex deadlock in QPluginLoader, Krita fails to start

With the freshly released Qt 5.14.2, [Krita|https://krita.org/en/] 4.2.9 fails to start: the initial splash screen is shown, but gets stuck indefinitely at "Adding resource types". The back trace looks as follows, so I suspect a deadlock in {{QPluginLoader}}:
{noformat}
#0  0x00007ffff454ef8d in syscall () from /usr/lib/libc.so.6
#1  0x00007ffff48ea106 in QtLinuxFutex::_q_futex (val3=0, addr2=0x0, val2=0, val=3, op=0, addr=0x5555573d0310) at thread/qfutex_p.h:133
#2  QtLinuxFutex::futexWait > (expectedValue=0x3, futex=...) at thread/qfutex_p.h:135
#3  lockInternal_helper (timeout=-1, elapsedTimer=0x0, d_ptr=...) at thread/qmutex_linux.cpp:142
#4  QBasicMutex::lockInternal (this=0x5555573d0310) at thread/qmutex_linux.cpp:159
#5  0x00007ffff48ea2fb in QMutex::lock (this=this@entry=0x5555573d0310) at thread/qmutex.cpp:236
#6  0x00007ffff4abdd5a in QMutexLocker::QMutexLocker (m=0x5555573d0310, this=) at ../../include/QtCore/../../src/corelib/thread/qmutex.h:233
#7  QLibraryPrivate::updatePluginState (this=0x5555573d02f0) at plugin/qlibrary.cpp:753
#8  0x00007ffff4ab024a in QPluginLoader::setFileName (this=0x555557883930, fileName=...) at plugin/qpluginloader.cpp:372
#9  0x00007ffff4ab030d in QPluginLoader::QPluginLoader (this=0x555557883930, fileName=..., parent=) at plugin/qpluginloader.cpp:157
#10 0x00007ffff32b5e03 in KoJsonTrader::query(QString const&, QString const&) const () from /usr/lib/libkritaplugin.so.18
#11 0x00007ffff32af3dc in KoPluginLoader::load(QString const&, QString const&, KoPluginLoader::PluginsConfig const&, QObject*, bool) ()
   from /usr/lib/libkritaplugin.so.18
#12 0x00007ffff3722536 in KoColorSpaceRegistry::init() () from /usr/lib/libkritapigment.so.18
#13 0x00007ffff3722ef8 in KoColorSpaceRegistry::instance() () from /usr/lib/libkritapigment.so.18
#14 0x00007ffff36f13f6 in KoColor::KoColor() () from /usr/lib/libkritapigment.so.18
#15 0x00007ffff7fe209a in call_init.part () from /lib64/ld-linux-x86-64.so.2
#16 0x00007ffff7fe21a1 in _dl_init () from /lib64/ld-linux-x86-64.so.2
#17 0x00007ffff458e905 in _dl_catch_exception () from /usr/lib/libc.so.6
#18 0x00007ffff7fe60e8 in dl_open_worker () from /lib64/ld-linux-x86-64.so.2
#19 0x00007ffff458e8a8 in _dl_catch_exception () from /usr/lib/libc.so.6
#20 0x00007ffff7fe596e in _dl_open () from /lib64/ld-linux-x86-64.so.2
#21 0x00007ffff061934c in ?? () from /usr/lib/libdl.so.2
#22 0x00007ffff458e8a8 in _dl_catch_exception () from /usr/lib/libc.so.6
#23 0x00007ffff458e973 in _dl_catch_error () from /usr/lib/libc.so.6
#24 0x00007ffff0619ab9 in ?? () from /usr/lib/libdl.so.2
#25 0x00007ffff06193da in dlopen () from /usr/lib/libdl.so.2
#26 0x00007ffff4ac13b1 in QLibraryPrivate::load_sys (this=this@entry=0x5555573d02f0) at ../../include/QtCore/../../src/corelib/tools/qarraydata.h:208
#27 0x00007ffff4abadde in QLibraryPrivate::load (this=0x5555573d02f0) at plugin/qlibrary.cpp:580
#28 0x00007ffff4abb3d3 in QLibraryPrivate::loadPlugin (this=0x5555573d02f0) at plugin/qlibrary.cpp:638
#29 0x00007ffff4aaf1c8 in QPluginLoader::load (this=0x555557639370) at plugin/qpluginloader.cpp:238
#30 0x00007ffff4aaf2f7 in QPluginLoader::instance (this=0x555557639370) at plugin/qpluginloader.cpp:197
#31 0x00007ffff32b02c1 in KoPluginLoader::load(QString const&, QString const&, KoPluginLoader::PluginsConfig const&, QObject*, bool) ()
   from /usr/lib/libkritaplugin.so.18
#32 0x00007ffff5e9501e in KisPaintOpRegistry::initRegistry() () from /usr/lib/libkritaimage.so.18
#33 0x00007ffff5e954f1 in KisPaintOpRegistry::instance() () from /usr/lib/libkritaimage.so.18
#34 0x00007ffff70aef07 in KisApplication::loadPlugins() () from /usr/lib/libkritaui.so.18
#35 0x00007ffff70b15f3 in KisApplication::start(KisApplicationArguments const&) () from /usr/lib/libkritaui.so.18
#36 0x0000555555e4dc11 in main ()
{noformat}
This is a regression from Qt 5.14.1 to Qt 5.14.2 that I have bisected to the following three commits in qtbase (unfortunately these commits cannot be bisected any further because they don't compile independently without errors):
{noformat}
commit f6c1cebe42193a62fa0b9c6a881bb1a973b1b8a9
Author: Thiago Macieira 
Date:   2019-12-18 18:17:38 -0800

    QPluginLoader: rework the loading and the caching of instance

    There was a race condition in accessing the cached instance factory
    member, so rework loadPlugin() to return the cached or newly discovered
    instance, with proper, atomic caching. Because I had to change that, I
    took the opportunity to fix the QFactoryLoader code that calls
    loadPlugin().

    Note that QLibraryPrivate::loadPlugin() returns non-nullptr now if the
    instance is known, which means the last return in QPluginLoader::load()
    will convert to true, not false, if the instance got cached between the
    earlier check and the call to loadPlugin(). That's probably what was
    intended.

    Task-number: QTBUG-39642
    Change-Id: I46bf1f65e8db46afbde5fffd15e1a42d2b6cbf2c
    Reviewed-by: David Faure

commit ef92ac5636c2f0407fba8141c35ea61d391fd479
Author: Thiago Macieira 
Date:   2019-12-18 18:31:55 -0800

    QLibrary: stop setting errorString after resolve()

    resolve() is technically thread-safe if the library has been loadaed. We
    don't promise that, but it's there. More importantly, because
    QLibraryPrivate is shared among QPluginLoader and QLibrary that point to
    the same file, we can't thread-safely set the error string.

    [ChangeLog][Important Behavior Changes] QLibrary::resolve() will no
    longer set or clear the error string based on the success of finding the
    symbol. The error string will reflect the result of loading the library.

    Change-Id: I46bf1f65e8db46afbde5fffd15e1a4f4c2713c17
    Reviewed-by: David Faure

commit ae6f73e8566fa76470937aca737141183929a5ec
Author: Thiago Macieira 
Date:   2019-12-18 18:45:36 -0800

    QLibrary: introduce a mutex to protect non-atomic internals

    And make pHnd atomic.

    The majority of the variables is updated in QLibraryPrivate::load_sys
    and updatePluginState(), which get the mutex protection.
    QLibraryPrivate::unload_sys() doesn't need a mutex protection because we
    have the refcounting.

    [ChangeLog][QtCore][QLibrary & QPluginLoader] Fixed a number of race
    conditions caused by having two QLibrary objects pointing to the same
    library being operated in different threads.

    Fixes: QTBUG-39642
    Change-Id: I46bf1f65e8db46afbde5fffd15e1a5b3f5e74ea4
    Reviewed-by: Lars Knoll
{noformat}
The relevant code in Krita that exercises the {{QPluginLoader}} code to trigger this issue can be found in [libs/koplugin/KoJsonTrader.cpp|https://github.com/KDE/krita/blob/7bf67f29de69fd222b99c95179966310226ca53f/libs/koplugin/KoJsonTrader.cpp#L116].

Downstream bug report in Arch Linux: [FS#66046|https://bugs.archlinux.org/task/66046]
```

## Fix commit message(s)

`276fa8383a75`

```
(empty)
```

## Files the fix changed

Snapshot holds 6,986 non-test source files. The fix changed 3 file(s); 3 of them are non-test source files (listed below as gold).

- `src/corelib/plugin/qlibrary.cpp`
- `src/corelib/plugin/qlibrary_unix.cpp`
- `src/corelib/plugin/qlibrary_win.cpp`

## The fix diff

### `src/corelib/plugin/qlibrary.cpp`

```diff
(no diff retrieved)
```

### `src/corelib/plugin/qlibrary_unix.cpp`

```diff
(no diff retrieved)
```

### `src/corelib/plugin/qlibrary_win.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
