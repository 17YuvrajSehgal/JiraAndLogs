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
QNetworkInformation fixups

Addressing feedback that came after the reviews
ended from both bot and people.

Added CLASS_NAME to the CMakeLists files for the plugins so that
cmake can generate the correct import.

Fixes: QTBUG-91061
Change-Id: Ib3f1e863100c1c421a6c0a4081b1d40696d67b23
Reviewed-by: Thiago Macieira <thiago.macieira@intel.com>
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
diff --git a/src/network/kernel/qnetworkinformation.cpp b/src/network/kernel/qnetworkinformation.cpp
index 2b0493ee269..9696a4fcc23 100644
--- a/src/network/kernel/qnetworkinformation.cpp
+++ b/src/network/kernel/qnetworkinformation.cpp
@@ -89,11 +89,10 @@ public:
 
 private:
     static bool initializeList();
 
     std::unique_ptr<QNetworkInformationBackend> backend;
-    bool m_isOnline = true; // cached
 };
 
 bool QNetworkInformationPrivate::initializeList()
 {
     if (!loader())
@@ -459,11 +458,11 @@ QNetworkInformationBackendFactory::~QNetworkInformationBackendFactory()
 */
 QNetworkInformation::QNetworkInformation(QNetworkInformationBackend *backend)
     : QObject(*(new QNetworkInformationPrivate(backend)))
 {
     connect(backend, &QNetworkInformationBackend::reachabilityChanged, this,
-            [this]() { emit reachabilityChanged(d_func()->backend->m_reachability); });
+            [this]() { emit reachabilityChanged(d_func()->backend->reachability()); });
 }
 
 /*!
     \internal dtor
 */
@@ -483,11 +482,11 @@ QNetworkInformation::~QNetworkInformation() = default;
     pre-check before attempting to make a connection.
 */
 
 QNetworkInformation::Reachability QNetworkInformation::reachability() const
 {
-    return d_func()->backend->m_reachability;
+    return d_func()->backend->reachability();
 }
 
 /*!
     Returns the name of the currently loaded backend.
 */
```

### `src/network/kernel/qnetworkinformation.h`

```diff
diff --git a/src/network/kernel/qnetworkinformation.h b/src/network/kernel/qnetworkinformation.h
index eddabc9707a..a04e7253006 100644
--- a/src/network/kernel/qnetworkinformation.h
+++ b/src/network/kernel/qnetworkinformation.h
@@ -68,11 +68,11 @@ public:
         Reachability = 0x1,
     };
     Q_ENUM(Feature)
     Q_DECLARE_FLAGS(Features, Feature)
 
-    ~QNetworkInformation();
+    ~QNetworkInformation() override;
 
     Reachability reachability() const;
 
     QString backendName() const;
```

### `src/network/kernel/qnetworkinformation_p.h`

```diff
diff --git a/src/network/kernel/qnetworkinformation_p.h b/src/network/kernel/qnetworkinformation_p.h
index 389310cc431..8cb31e66414 100644
--- a/src/network/kernel/qnetworkinformation_p.h
+++ b/src/network/kernel/qnetworkinformation_p.h
@@ -62,15 +62,17 @@ QT_BEGIN_NAMESPACE
 class Q_NETWORK_EXPORT QNetworkInformationBackend : public QObject
 {
     Q_OBJECT
 public:
     QNetworkInformationBackend() = default;
-    virtual ~QNetworkInformationBackend();
+    ~QNetworkInformationBackend() override;
 
     virtual QString name() const = 0;
     virtual QNetworkInformation::Features featuresSupported() const = 0;
 
+    QNetworkInformation::Reachability reachability() const { return m_reachability; }
+
 Q_SIGNALS:
     void reachabilityChanged();
 
 protected:
     void setReachability(QNetworkInformation::Reachability reachability)
```

### `src/plugins/networkinformationbackends/networkmanager/qnetworkmanagernetworkinformationbackend.cpp`

```diff
diff --git a/src/plugins/networkinformationbackends/networkmanager/qnetworkmanagernetworkinformationbackend.cpp b/src/plugins/networkinformationbackends/networkmanager/qnetworkmanagernetworkinformationbackend.cpp
index 1677f36fe11..1356078ee0a 100644
--- a/src/plugins/networkinformationbackends/networkmanager/qnetworkmanagernetworkinformationbackend.cpp
+++ b/src/plugins/networkinformationbackends/networkmanager/qnetworkmanagernetworkinformationbackend.cpp
@@ -95,10 +95,12 @@ public:
     }
 
     bool isValid() const { return iface.isValid(); }
 
 private:
+    Q_DISABLE_COPY_MOVE(QNetworkManagerNetworkInformationBackend)
+
     QNetworkManagerInterface iface;
     QNetworkManagerInterface::NMState prevState;
 };
 
 class QNetworkManagerNetworkInformationBackendFactory : public QNetworkInformationBackendFactory
@@ -126,10 +128,12 @@ public:
         auto backend = new QNetworkManagerNetworkInformationBackend();
         if (!backend->isValid())
             delete std::exchange(backend, nullptr);
         return backend;
     }
+private:
+    Q_DISABLE_COPY_MOVE(QNetworkManagerNetworkInformationBackendFactory)
 };
 
 QNetworkManagerNetworkInformationBackend::QNetworkManagerNetworkInformationBackend()
 {
     prevState = iface.state();
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
