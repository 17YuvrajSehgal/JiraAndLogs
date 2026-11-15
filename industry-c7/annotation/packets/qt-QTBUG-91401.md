# Annotation packet: QTBUG-91401  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Error loading PNG: Unsupported ICC profile class 70727472

Steps to reproduce:
- Launch examples/widgets/widgets/imageviewer
- Open attached png
- Observe warnings

Occurs when trying to load an image with an alpha channel
{noformat}
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
qt.gui.icc: Unsupported ICC profile class 70727472
qt.gui.imageio: QPngHandler: Failed to parse ICC profile
{noformat}
```

## Fix commit message(s)

`63152571844a`

```
Reduce warnings from ICC parsing

Messages about Qt deficiencies reduced to info, and info set as the
default message level.

Pick-to: 6.1 6.0 5.15
Fixes: QTBUG-91401
Change-Id: Ia97438f08de5e0383e77631dca9b253b47ef8167
Reviewed-by: Eirik Aavitsland <eirik.aavitsland@qt.io>
```

## Files the fix changed

Snapshot holds 5,896 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `src/gui/image/qpnghandler.cpp`
- `src/gui/painting/qicc.cpp`

## The fix diff

### `src/gui/image/qpnghandler.cpp`

```diff
diff --git a/src/gui/image/qpnghandler.cpp b/src/gui/image/qpnghandler.cpp
index de913af320b..20a86b4f8f8 100644
--- a/src/gui/image/qpnghandler.cpp
+++ b/src/gui/image/qpnghandler.cpp
@@ -498,11 +498,11 @@ static void read_image_scaled(QImage *outImage, png_structp png_ptr, png_infop i
 }
 
 extern "C" {
 static void qt_png_warning(png_structp /*png_ptr*/, png_const_charp message)
 {
-    qCWarning(lcImageIo, "libpng warning: %s", message);
+    qCInfo(lcImageIo, "libpng warning: %s", message);
 }
 
 }
 
 
@@ -588,11 +588,11 @@ bool QPngHandlerPrivate::readPngHeader()
 #endif
         png_uint_32 profLen;
         png_get_iCCP(png_ptr, info_ptr, &name, &compressionType, &profileData, &profLen);
         colorSpace = QColorSpace::fromIccProfile(QByteArray((const char *)profileData, profLen));
         if (!colorSpace.isValid()) {
-            qCWarning(lcImageIo) << "QPngHandler: Failed to parse ICC profile";
+            qCDebug(lcImageIo) << "QPngHandler: Failed to parse ICC profile";
         } else {
             QColorSpacePrivate *csD = QColorSpacePrivate::get(colorSpace);
             if (csD->description.isEmpty())
                 csD->description = QString::fromLatin1((const char *)name);
             colorSpaceState = Icc;
```

### `src/gui/painting/qicc.cpp`

```diff
diff --git a/src/gui/painting/qicc.cpp b/src/gui/painting/qicc.cpp
index 25389121f38..028e800c48e 100644
--- a/src/gui/painting/qicc.cpp
+++ b/src/gui/painting/qicc.cpp
@@ -50,11 +50,11 @@
 #include "qcolortrc_p.h"
 
 #include <array>
 
 QT_BEGIN_NAMESPACE
-Q_LOGGING_CATEGORY(lcIcc, "qt.gui.icc")
+Q_LOGGING_CATEGORY(lcIcc, "qt.gui.icc", QtWarningMsg)
 
 struct ICCProfileHeader
 {
     quint32_be profileSize;
 
@@ -235,22 +235,24 @@ static bool isValidIccProfile(const ICCProfileHeader &header)
         qCWarning(lcIcc, "Failed basic size sanity");
         return false;
     }
 
     if (header.profileClass != uint(ProfileClass::Input)
-        && header.profileClass != uint(ProfileClass::Display)) {
-        qCWarning(lcIcc, "Unsupported ICC profile class %x", quint32(header.profileClass));
+        && header.profileClass != uint(ProfileClass::Display)
+        && (header.profileClass != uint(ProfileClass::Output)
+            || header.inputColorSpace != uint(ColorSpaceType::Gray)))  {
+        qCInfo(lcIcc, "Unsupported ICC profile class 0x%x", quint32(header.profileClass));
         return false;
     }
     if (header.inputColorSpace != uint(ColorSpaceType::Rgb)
         && header.inputColorSpace != uint(ColorSpaceType::Gray)) {
-        qCWarning(lcIcc, "Unsupported ICC input color space %x", quint32(header.inputColorSpace));
+        qCInfo(lcIcc, "Unsupported ICC input color space 0x%x", quint32(header.inputColorSpace));
         return false;
     }
     if (header.pcs != 0x58595a20 /* 'XYZ '*/) {
         // ### support PCSLAB
-        qCWarning(lcIcc, "Unsupported ICC profile connection space %x", quint32(header.pcs));
+        qCInfo(lcIcc, "Unsupported ICC profile connection space 0x%x", quint32(header.pcs));
         return false;
     }
 
     QColorVector illuminant;
     illuminant.x = fromFixedS1516(header.illuminantXyz[0]);
@@ -700,11 +702,11 @@ bool fromIccProfile(const QByteArray &data, QColorSpace *colorSpace)
     // Check the profile is three-component matrix based (what we currently support):
     if (header.inputColorSpace == uint(ColorSpaceType::Rgb)) {
         if (!tagIndex.contains(Tag::rXYZ) || !tagIndex.contains(Tag::gXYZ) || !tagIndex.contains(Tag::bXYZ) ||
             !tagIndex.contains(Tag::rTRC) || !tagIndex.contains(Tag::gTRC) || !tagIndex.contains(Tag::bTRC) ||
             !tagIndex.contains(Tag::wtpt)) {
-            qCWarning(lcIcc) << "fromIccProfile: Unsupported ICC profile - not three component matrix based";
+            qCInfo(lcIcc) << "fromIccProfile: Unsupported ICC profile - not three component matrix based";
             return false;
         }
     } else {
         Q_ASSERT(header.inputColorSpace == uint(ColorSpaceType::Gray));
         if (!tagIndex.contains(Tag::kTRC) || !tagIndex.contains(Tag::wtpt)) {
@@ -760,11 +762,11 @@ bool fromIccProfile(const QByteArray &data, QColorSpace *colorSpace)
             float y = 1.0f / (1.0f + whitePoint.z + whitePoint.x);
             float x = whitePoint.x * y;
             QColorSpacePrimaries primaries(QColorSpace::Primaries::SRgb);
             primaries.whitePoint = QPointF(x,y);
             if (!primaries.areValid()) {
-                qCWarning(lcIcc) << "fromIccProfile: Invalid ICC profile - invalid white-point";
+                qCWarning(lcIcc, "fromIccProfile: Invalid ICC profile - invalid white-point(%f, %f)", x, y);
                 return false;
             }
             colorspaceDPtr->toXyz = primaries.toXyzMatrix();
         }
     }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
