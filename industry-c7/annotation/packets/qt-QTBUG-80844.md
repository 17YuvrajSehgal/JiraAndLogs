# Annotation packet: QTBUG-80844  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Redraw problem with screen mirror

env: macbook pro 15 2019 with macOS 10.15.2, monitor DELL P2417H connected via HDMI. macOS settings for displays: Mirror Displays

Launch qt app on macOS, e.g. qt creator,  connect or disconnect monitor and then move mouse over app -> some problems with main window updating
```

## Fix commit message(s)

`7ac4e55cb979`

```
macOS Don't throw away backingstore buffers when backing properties change

Clients such as QtWidgets that do their own dirty tracking will assume
they can just flush in response to the expose event, without repainting
anything. Since we have no way at the moment to inform these clients that
the backingstore content might be invalid we can't just throw it away.

It turns out that to pick up changes in color spaces we can just tag
the existing buffers with the new color space, so we don't need to
throw it away. And for the older surface-backed mode we tag the color
space on flush, so we didn't need to invalidate anything in the first
place.

Fixes: QTBUG-80844
Task-number: QTBUG-77749
Change-Id: Icb1ceb178894bb43887cdf03fb855d2d614b5ab0
Reviewed-by: Timur Pocheptsov <timur.pocheptsov@qt.io>
```

## Files the fix changed

Snapshot holds 6,981 non-test source files. The fix changed 5 file(s); 5 of them are non-test source files (listed below as gold).

- `src/plugins/platforms/cocoa/qcocoabackingstore.h`
- `src/plugins/platforms/cocoa/qcocoabackingstore.mm`
- `src/plugins/platforms/cocoa/qcocoaintegration.mm`
- `src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.h`
- `src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.mm`

## The fix diff

### `src/plugins/platforms/cocoa/qcocoabackingstore.h`

```diff
diff --git a/src/plugins/platforms/cocoa/qcocoabackingstore.h b/src/plugins/platforms/cocoa/qcocoabackingstore.h
index a874936ce66..b57deacb57b 100644
--- a/src/plugins/platforms/cocoa/qcocoabackingstore.h
+++ b/src/plugins/platforms/cocoa/qcocoabackingstore.h
@@ -52,12 +52,10 @@ QT_BEGIN_NAMESPACE
 class QCocoaBackingStore : public QRasterBackingStore
 {
 protected:
     QCocoaBackingStore(QWindow *window);
     QCFType<CGColorSpaceRef> colorSpace() const;
-    QMacNotificationObserver m_backingPropertiesObserver;
-    virtual void backingPropertiesChanged() = 0;
 };
 
 class QNSWindowBackingStore : public QCocoaBackingStore
 {
 public:
@@ -69,11 +67,10 @@ public:
 
 private:
     bool windowHasUnifiedToolbar() const;
     QImage::Format format() const override;
     void redrawRoundedBottomCorners(CGRect) const;
-    void backingPropertiesChanged() override;
 };
 
 class QCALayerBackingStore : public QCocoaBackingStore
 {
 public:
@@ -116,11 +113,12 @@ private:
 
     void ensureBackBuffer();
     bool recreateBackBufferIfNeeded();
     bool prepareForFlush();
 
-    void backingPropertiesChanged() override;
+    void backingPropertiesChanged();
+    QMacNotificationObserver m_backingPropertiesObserver;
 
     std::list<std::unique_ptr<GraphicsBuffer>> m_buffers;
 };
 
 QT_END_NAMESPACE
```

### `src/plugins/platforms/cocoa/qcocoabackingstore.mm`

```diff
diff --git a/src/plugins/platforms/cocoa/qcocoabackingstore.mm b/src/plugins/platforms/cocoa/qcocoabackingstore.mm
index b17302a6404..8a815a7665e 100644
--- a/src/plugins/platforms/cocoa/qcocoabackingstore.mm
+++ b/src/plugins/platforms/cocoa/qcocoabackingstore.mm
@@ -49,21 +49,10 @@
 QT_BEGIN_NAMESPACE
 
 QCocoaBackingStore::QCocoaBackingStore(QWindow *window)
     : QRasterBackingStore(window)
 {
-    // Ideally this would be plumbed from the platform layer to QtGui, and
-    // the QBackingStore would be recreated, but we don't have that code yet,
-    // so at least make sure we invalidate our backingstore when the backing
-    // properties (color space e.g.) are changed.
-    NSView *view = static_cast<QCocoaWindow *>(window->handle())->view();
-    m_backingPropertiesObserver = QMacNotificationObserver(view.window,
-        NSWindowDidChangeBackingPropertiesNotification, [this]() {
-            qCDebug(lcQpaBackingStore) << "Backing properties for"
-                << this->window() << "did change";
-            backingPropertiesChanged();
-        });
 }
 
 QCFType<CGColorSpaceRef> QCocoaBackingStore::colorSpace() const
 {
     NSView *view = static_cast<QCocoaWindow *>(window()->handle())->view();
@@ -339,22 +328,29 @@ void QNSWindowBackingStore::redrawRoundedBottomCorners(CGRect windowRect) const
 #else
     Q_UNUSED(windowRect);
 #endif
 }
 
-void QNSWindowBackingStore::backingPropertiesChanged()
-{
-    m_image = QImage();
-}
-
 // ----------------------------------------------------------------------------
 
 QCALayerBackingStore::QCALayerBackingStore(QWindow *window)
     : QCocoaBackingStore(window)
 {
     qCDebug(lcQpaBackingStore) << "Creating QCALayerBackingStore for" << window;
     m_buffers.resize(1);
+
+    // Ideally this would be plumbed from the platform layer to QtGui, and
+    // the QBackingStore would be recreated, but we don't have that code yet,
+    // so at least make sure we update our backingstore when the backing
+    // properties (color space e.g.) are changed.
+    NSView *view = static_cast<QCocoaWindow *>(window->handle())->view();
+    m_backingPropertiesObserver = QMacNotificationObserver(view.window,
+        NSWindowDidChangeBackingPropertiesNotification, [this]() {
+            qCDebug(lcQpaBackingStore) << "Backing properties for"
+                << this->window() << "did change";
+            backingPropertiesChanged();
+        });
 }
 
 QCALayerBackingStore::~QCALayerBackingStore()
 {
 }
@@ -618,12 +614,13 @@ QImage QCALayerBackingStore::toImage() const
     return imageCopy;
 }
 
 void QCALayerBackingStore::backingPropertiesChanged()
 {
-    m_buffers.clear();
-    m_buffers.resize(1);
+    qCDebug(lcQpaBackingStore) << "Updating color space of existing buffers";
+    for (auto &buffer : m_buffers)
+        buffer->setColorSpace(colorSpace());
 }
 
 QPlatformGraphicsBuffer *QCALayerBackingStore::graphicsBuffer() const
 {
     return m_buffers.back().get();
@@ -696,14 +693,15 @@ bool QCALayerBackingStore::prepareForFlush()
 
 // ----------------------------------------------------------------------------
 
 QCALayerBackingStore::GraphicsBuffer::GraphicsBuffer(const QSize &size, qreal devicePixelRatio,
                                 const QPixelFormat &format, QCFType<CGColorSpaceRef> colorSpace)
-    : QIOSurfaceGraphicsBuffer(size, format, colorSpace)
+    : QIOSurfaceGraphicsBuffer(size, format)
     , dirtyRegion(0, 0, size.width() / devicePixelRatio, size.height() / devicePixelRatio)
     , m_devicePixelRatio(devicePixelRatio)
 {
+    setColorSpace(colorSpace);
 }
 
 QImage *QCALayerBackingStore::GraphicsBuffer::asImage()
 {
     if (m_image.isNull()) {
```

### `src/plugins/platforms/cocoa/qcocoaintegration.mm`

```diff
diff --git a/src/plugins/platforms/cocoa/qcocoaintegration.mm b/src/plugins/platforms/cocoa/qcocoaintegration.mm
index b7f15a2bf12..d8c931e9a17 100644
--- a/src/plugins/platforms/cocoa/qcocoaintegration.mm
+++ b/src/plugins/platforms/cocoa/qcocoaintegration.mm
@@ -394,10 +394,12 @@ QVariant QCocoaIntegration::styleHint(StyleHint hint) const
     switch (hint) {
     case FontSmoothingGamma:
         return QCoreTextFontEngine::fontSmoothingGamma();
     case ShowShortcutsInContextMenus:
         return QVariant(false);
+    // case CursorFlashTime:
+    //     return 50000;
     default: break;
     }
 
     return QPlatformIntegration::styleHint(hint);
 }
```

### `src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.h`

```diff
diff --git a/src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.h b/src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.h
index 872773cb7a3..e070ba977d5 100644
--- a/src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.h
+++ b/src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.h
@@ -46,13 +46,15 @@
 QT_BEGIN_NAMESPACE
 
 class QIOSurfaceGraphicsBuffer : public QPlatformGraphicsBuffer
 {
 public:
-    QIOSurfaceGraphicsBuffer(const QSize &size, const QPixelFormat &format, QCFType<CGColorSpaceRef> colorSpace);
+    QIOSurfaceGraphicsBuffer(const QSize &size, const QPixelFormat &format);
     ~QIOSurfaceGraphicsBuffer();
 
+    void setColorSpace(QCFType<CGColorSpaceRef> colorSpace);
+
     const uchar *data() const override;
     uchar *data() override;
     int bytesPerLine() const override;
 
     IOSurfaceRef surface();
```

### `src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.mm`

```diff
diff --git a/src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.mm b/src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.mm
index a367487e85f..285e316d4af 100644
--- a/src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.mm
+++ b/src/plugins/platforms/cocoa/qiosurfacegraphicsbuffer.mm
@@ -51,11 +51,11 @@ extern "C" CFPropertyListRef CGColorSpaceCopyPropertyList(CGColorSpaceRef space)
 
 QT_BEGIN_NAMESPACE
 
 Q_LOGGING_CATEGORY(lcQpaIOSurface, "qt.qpa.backingstore.iosurface");
 
-QIOSurfaceGraphicsBuffer::QIOSurfaceGraphicsBuffer(const QSize &size, const QPixelFormat &format, QCFType<CGColorSpaceRef> colorSpace)
+QIOSurfaceGraphicsBuffer::QIOSurfaceGraphicsBuffer(const QSize &size, const QPixelFormat &format)
     : QPlatformGraphicsBuffer(size, format)
 {
     const size_t width = size.width();
     const size_t height = size.height();
 
@@ -79,21 +79,23 @@ QIOSurfaceGraphicsBuffer::QIOSurfaceGraphicsBuffer(const QSize &size, const QPix
     m_surface = IOSurfaceCreate((CFDictionaryRef)options);
     Q_ASSERT(m_surface);
 
     Q_ASSERT(size_t(bytesPerLine()) == bytesPerRow);
     Q_ASSERT(size_t(byteCount()) == totalBytes);
-
-    if (colorSpace) {
-        IOSurfaceSetValue(m_surface, CFSTR("IOSurfaceColorSpace"),
-            QCFType<CFPropertyListRef>(CGColorSpaceCopyPropertyList(colorSpace)));
-    }
 }
 
 QIOSurfaceGraphicsBuffer::~QIOSurfaceGraphicsBuffer()
 {
 }
 
+void QIOSurfaceGraphicsBuffer::setColorSpace(QCFType<CGColorSpaceRef> colorSpace)
+{
+    Q_ASSERT(colorSpace);
+    IOSurfaceSetValue(m_surface, CFSTR("IOSurfaceColorSpace"),
+        QCFType<CFPropertyListRef>(CGColorSpaceCopyPropertyList(colorSpace)));
+}
+
 const uchar *QIOSurfaceGraphicsBuffer::data() const
 {
     return (const uchar *)IOSurfaceGetBaseAddress(m_surface);
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
