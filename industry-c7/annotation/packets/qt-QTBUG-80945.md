# Annotation packet: QTBUG-80945  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
QPrintDialog constructor is crashing

The constructor of QPrintDialog crashes. According to the adress sanitizer it is a heap-use-after-free error. The problem has been found with the bode example you find in the qwt ( qwt.sf.net ) examples from svn trunk.

Below you find the out, when Qt has been build with asan support:

=================================================================
==17993==ERROR: AddressSanitizer: heap-use-after-free on address 0x6040001c3498 at pc 0x7fad8993f0d7 bp 0x7ffc56521af0 sp 0x7ffc56521ae8
READ of size 8 at 0x6040001c3498 thread T0
 #0 0x7fad8993f0d6 in QScopedPointer<QObjectData, QScopedPointerDeleter<QObjectData> >::operator->() const ../../include/QtCore/../../src/corelib/tools/qscopedpointer.h:118
 #1 0x7fad8993f0d6 in decltype ((\{parm#1}.(operator->))()) qGetPtrHelper<QScopedPointer<QObjectData, QScopedPointerDeleter<QObjectData> > >(QScopedPointer<QObjectData, QScopedPointerDeleter<QObjectData> >&) ../../include/QtCore/../../src/corelib/global/qglobal.h:1127
 #2 0x7fad8993f0d6 in QWidget::d_func() ../../include/QtWidgets/../../src/widgets/kernel/qwidget.h:132
 #3 0x7fad8993f0d6 in QWidget::setEnabled(bool) kernel/qwidget.cpp:3221
 #4 0x7fad8c73fc37 in QPrintDialogPrivate::selectPrinter(QPrinter::OutputFormat) dialogs/qprintdialog_unix.cpp:733
 #5 0x7fad8c744234 in QUnixPrintWidgetPrivate::setOptionsPane(QPrintDialogPrivate*) dialogs/qprintdialog_unix.cpp:1275
 #6 0x7fad8c744d99 in QPrintDialogPrivate::init() dialogs/qprintdialog_unix.cpp:644
 #7 0x7fad8c745d2c in QPrintDialog::QPrintDialog(QPrinter*, QWidget*) dialogs/qprintdialog_unix.cpp:1061
 #8 0x40fd0a in MainWindow::print() /home/uwe/qwt/qwt-git/examples/bode/mainwindow.cpp:171
 #9 0x412858 in MainWindow::qt_static_metacall(QObject*, QMetaObject::Call, int, void**) moc/moc_mainwindow.cpp:87
 #10 0x7fad87ac8f35 in void doActivate<false>(QObject*, int, void**) kernel/qobject.cpp:3882
 #11 0x7fad87ab1ddb in QMetaObject::activate(QObject*, QMetaObject const*, int, void**) kernel/qobject.cpp:3930
 #12 0x7fad89cef994 in QAbstractButton::clicked(bool) .moc/moc_qabstractbutton.cpp:313
 #13 0x7fad89cf02aa in QAbstractButtonPrivate::emitClicked() widgets/qabstractbutton.cpp:415
 #14 0x7fad89cf6679 in QAbstractButtonPrivate::click() widgets/qabstractbutton.cpp:408
 #15 0x7fad89cf6da3 in QAbstractButton::mouseReleaseEvent(QMouseEvent*) widgets/qabstractbutton.cpp:1012
 #16 0x7fad8a15bc21 in QToolButton::mouseReleaseEvent(QMouseEvent*) widgets/qtoolbutton.cpp:622
 #17 0x7fad8995a66c in QWidget::event(QEvent*) kernel/qwidget.cpp:8631
 #18 0x7fad89cfbab9 in QAbstractButton::event(QEvent*) widgets/qabstractbutton.cpp:969
 #19 0x7fad8a15bf67 in QToolButton::event(QEvent*) widgets/qtoolbutton.cpp:1002
 #20 0x7fad89800102 in QApplicationPrivate::notify_helper(QObject*, QEvent*) kernel/qapplication.cpp:3693
 #21 0x7fad8982295f in QApplication::notify(QObject*, QEvent*) kernel/qapplication.cpp:3137
 #22 0x7fad879f611f in QCoreApplication::notifyInternal2(QObject*, QEvent*) kernel/qcoreapplication.cpp:1092
 #23 0x7fad879f6a9c in QCoreApplication::sendSpontaneousEvent(QObject*, QEvent*) kernel/qcoreapplication.cpp:1499
 #24 0x7fad8981cdb0 in QApplicationPrivate::sendMouseEvent(QWidget*, QMouseEvent*, QWidget*, QWidget*, QWidget**, QPointer<QWidget>&, bool, bool) kernel/qapplication.cpp:2623
 #25 0x7fad899d71b0 in QWidgetWindow::handleMouseEvent(QMouseEvent*) kernel/qwidgetwindow.cpp:673
 #26 0x7fad899e0205 in QWidgetWindow::event(QEvent*) kernel/qwidgetwindow.cpp:295
 #27 0x7fad89800102 in QApplicationPrivate::notify_helper(QObject*, QEvent*) kernel/qapplication.cpp:3693
 #28 0x7fad898211f8 in QApplication::notify(QObject*, QEvent*) kernel/qapplication.cpp:3033
 #29 0x7fad879f611f in QCoreApplication::notifyInternal2(QObject*, QEvent*) kernel/qcoreapplication.cpp:1092
 #30 0x7fad879f6a9c in QCoreApplication::sendSpontaneousEvent(QObject*, QEvent*) kernel/qcoreapplication.cpp:1499
 #31 0x7fad88464930 in QGuiApplicationPrivate::processMouseEvent(QWindowSystemInterfacePrivate::MouseEvent*) kernel/qguiapplication.cpp:2188
 #32 0x7fad884699ae in QGuiApplicationPrivate::processWindowSystemEvent(QWindowSystemInterfacePrivate::WindowSystemEvent*) kernel/qguiapplication.cpp:1920
 #33 0x7fad883bc836 in QWindowSystemInterface::sendWindowSystemEvents(QFlags<QEventLoop::ProcessEventsFlag>) kernel/qwindowsysteminterface.cpp:1163
 #34 0x7fad7e430570 in xcbSourceDispatch /disk3/qt/qt-everywhere-src-5.14.0/qtbase/src/plugins/platforms/xcb/qxcbeventdispatcher.cpp:105
 #35 0x7fad84616e86 in g_main_context_dispatch (/usr/lib64/libglib-2.0.so.0+0x4de86)
 #36 0x7fad8461722f (/usr/lib64/libglib-2.0.so.0+0x4e22f)
 #37 0x7fad846172bb in g_main_context_iteration (/usr/lib64/libglib-2.0.so.0+0x4e2bb)
 #38 0x7fad87b5c659 in QEventDispatcherGlib::processEvents(QFlags<QEventLoop::ProcessEventsFlag>) kernel/qeventdispatcher_glib.cpp:423
 #39 0x7fad7e430ef9 in QXcbGlibEventDispatcher::processEvents(QFlags<QEventLoop::ProcessEventsFlag>) /disk3/qt/qt-everywhere-src-5.14.0/qtbase/src/plugins/platforms/xcb/qxcbeventdispatcher.cpp:143
 #40 0x7fad879edc13 in QEventLoop::processEvents(QFlags<QEventLoop::ProcessEventsFlag>) kernel/qeventloop.cpp:138
 #41 0x7fad879ef02b in QEventLoop::exec(QFlags<QEventLoop::ProcessEventsFlag>) kernel/qeventloop.cpp:225
 #42 0x7fad87a0f6d7 in QCoreApplication::exec() kernel/qcoreapplication.cpp:1400
 #43 0x7fad88438d1b in QGuiApplication::exec() kernel/qguiapplication.cpp:1845
 #44 0x7fad897fff9e in QApplication::exec() kernel/qapplication.cpp:2833
 #45 0x412487 in main /home/uwe/qwt/qwt-git/examples/bode/main.cpp:21
 #46 0x7fad86085f89 in __libc_start_main (/lib64/libc.so.6+0x20f89)
 #47 0x409819 in _start (/home/uwe/qwt/qwt-git/examples/bin/bode+0x409819)

0x6040001c3498 is located 8 bytes inside of 48-byte region [0x6040001c3490,0x6040001c34c0)
freed by thread T0 here:
 #0 0x7fad8b6f2428 in operator delete(void*, unsigned long) (/usr/lib64/libasan.so.5+0xee428)
 #1 0x7fad89fcd8f7 in QRadioButton::~QRadioButton() widgets/qradiobutton.cpp:145
 #2 0x7fad8c744c79 in QPrintDialogPrivate::init() dialogs/qprintdialog_unix.cpp:641
 #3 0x7fad8c745d2c in QPrintDialog::QPrintDialog(QPrinter*, QWidget*) dialogs/qprintdialog_unix.cpp:1061
 #4 0x40fd0a in MainWindow::print() /home/uwe/qwt/qwt-git/examples/bode/mainwindow.cpp:171
 #5 0x412858 in MainWindow::qt_static_metacall(QObject*, QMetaObject::Call, int, void**) moc/moc_mainwindow.cpp:87
 #6 0x7fad87ac8f35 in void doActivate<false>(QObject*, int, void**) kernel/qobject.cpp:3882
 #7 0x7fad87ab1ddb in QMetaObject::activate(QObject*, QMetaObject const*, int, void**) kernel/qobject.cpp:3930
 #8 0x7fad89cef994 in QAbstractButton::clicked(bool) .moc/moc_qabstractbutton.cpp:313
 #9 0x7fad89cf02aa in QAbstractButtonPrivate::emitClicked() widgets/qabstractbutton.cpp:415
 #10 0x7fad89cf6679 in QAbstractButtonPrivate::click() widgets/qabstractbutton.cpp:408
 #11 0x7fad89cf6da3 in QAbstractButton::mouseReleaseEvent(QMouseEvent*) widgets/qabstractbutton.cpp:1012
 #12 0x7fad8a15bc21 in QToolButton::mouseReleaseEvent(QMouseEvent*) widgets/qtoolbutton.cpp:622
 #13 0x7fad8995a66c in QWidget::event(QEvent*) kernel/qwidget.cpp:8631
 #14 0x7fad89cfbab9 in QAbstractButton::event(QEvent*) widgets/qabstractbutton.cpp:969
 #15 0x7fad8a15bf67 in QToolButton::event(QEvent*) widgets/qtoolbutton.cpp:1002
 #16 0x7fad89800102 in QApplicationPrivate::notify_helper(QObject*, QEvent*) kernel/qapplication.cpp:3693
 #17 0x7fad8982295f in QApplication::notify(QObject*, QEvent*) kernel/qapplication.cpp:3137
 #18 0x7fad879f611f in QCoreApplication::notifyInternal2(QObject*, QEvent*) kernel/qcoreapplication.cpp:1092
 #19 0x7fad879f6a9c in QCoreApplication::sendSpontaneousEvent(QObject*, QEvent*) kernel/qcoreapplication.cpp:1499
 #20 0x7fad8981cdb0 in QApplicationPrivate::sendMouseEvent(QWidget*, QMouseEvent*, QWidget*, QWidget*, QWidget**, QPointer<QWidget>&, bool, bool) kernel/qapplication.cpp:2623
 #21 0x7fad899d71b0 in QWidgetWindow::handleMouseEvent(QMouseEvent*) kernel/qwidgetwindow.cpp:673
 #22 0x7fad899e0205 in QWidgetWindow::event(QEvent*) kernel/qwidgetwindow.cpp:295
 #23 0x7fad89800102 in QApplicationPrivate::notify_helper(QObject*, QEvent*) kernel/qapplication.cpp:3693
 #24 0x7fad898211f8 in QApplication::notify(QObject*, QEvent*) kernel/qapplication.cpp:3033
 #25 0x7fad879f611f in QCoreApplication::notifyInternal2(QObject*, QEvent*) kernel/qcoreapplication.cpp:1092
 #26 0x7fad879f6a9c in QCoreApplication::sendSpontaneousEvent(QObject*, QEvent*) kernel/qcoreapplication.cpp:1499
 #27 0x7fad88464930 in QGuiApplicationPrivate::processMouseEvent(QWindowSystemInterfacePrivate::MouseEvent*) kernel/qguiapplication.cpp:2188
 #28 0x7fad884699ae in QGuiApplicationPrivate::processWindowSystemEvent(QWindowSystemInterfacePrivate::WindowSystemEvent*) kernel/qguiapplication.cpp:1920
 #29 0x7fad883bc836 in QWindowSystemInterface::sendWindowSystemEvents(QFlags<QEventLoop::ProcessEventsFlag>) kernel/qwindowsysteminterface.cpp:1163

previously allocated by thread T0 here:
 #0 0x7fad8b6f1030 in operator new(unsigned long) (/usr/lib64/libasan.so.5+0xed030)
 #1 0x7fad8c74c439 in Ui_QPrintSettingsOutput::setupUi(QWidget*) .uic/ui_qprintsettingsoutput.h:149
 #2 0x7fad8c744677 in QPrintDialogPrivate::init() dialogs/qprintdialog_unix.cpp:628
 #3 0x7fad8c745d2c in QPrintDialog::QPrintDialog(QPrinter*, QWidget*) dialogs/qprintdialog_unix.cpp:1061
 #4 0x40fd0a in MainWindow::print() /home/uwe/qwt/qwt-git/examples/bode/mainwindow.cpp:171
 #5 0x412858 in MainWindow::qt_static_metacall(QObject*, QMetaObject::Call, int, void**) moc/moc_mainwindow.cpp:87
 #6 0x7fad87ac8f35 in void doActivate<false>(QObject*, int, void**) kernel/qobject.cpp:3882
 #7 0x7fad87ab1ddb in QMetaObject::activate(QObject*, QMetaObject const*, int, void**) kernel/qobject.cpp:3930
 #8 0x7fad89cef994 in QAbstractButton::clicked(bool) .moc/moc_qabstractbutton.cpp:313
 #9 0x7fad89cf02aa in QAbstractButtonPrivate::emitClicked() widgets/qabstractbutton.cpp:415
 #10 0x7fad89cf6679 in QAbstractButtonPrivate::click() widgets/qabstractbutton.cpp:408
 #11 0x7fad89cf6da3 in QAbstractButton::mouseReleaseEvent(QMouseEvent*) widgets/qabstractbutton.cpp:1012
 #12 0x7fad8a15bc21 in QToolButton::mouseReleaseEvent(QMouseEvent*) widgets/qtoolbutton.cpp:622
 #13 0x7fad8995a66c in QWidget::event(QEvent*) kernel/qwidget.cpp:8631
 #14 0x7fad89cfbab9 in QAbstractButton::event(QEvent*) widgets/qabstractbutton.cpp:969
 #15 0x7fad8a15bf67 in QToolButton::event(QEvent*) widgets/qtoolbutton.cpp:1002
 #16 0x7fad89800102 in QApplicationPrivate::notify_helper(QObject*, QEvent*) kernel/qapplication.cpp:3693
 #17 0x7fad8982295f in QApplication::notify(QObject*, QEvent*) kernel/qapplication.cpp:3137
 #18 0x7fad879f611f in QCoreApplication::notifyInternal2(QObject*, QEvent*) kernel/qcoreapplication.cpp:1092
 #19 0x7fad879f6a9c in QCoreApplication::sendSpontaneousEvent(QObject*, QEvent*) kernel/qcoreapplication.cpp:1499
 #20 0x7fad8981cdb0 in QApplicationPrivate::sendMouseEvent(QWidget*, QMouseEvent*, QWidget*, QWidget*, QWidget**, QPointer<QWidget>&, bool, bool) kernel/qapplication.cpp:2623
 #21 0x7fad899d71b0 in QWidgetWindow::handleMouseEvent(QMouseEvent*) kernel/qwidgetwindow.cpp:673
 #22 0x7fad899e0205 in QWidgetWindow::event(QEvent*) kernel/qwidgetwindow.cpp:295
 #23 0x7fad89800102 in QApplicationPrivate::notify_helper(QObject*, QEvent*) kernel/qapplication.cpp:3693
 #24 0x7fad898211f8 in QApplication::notify(QObject*, QEvent*) kernel/qapplication.cpp:3033
 #25 0x7fad879f611f in QCoreApplication::notifyInternal2(QObject*, QEvent*) kernel/qcoreapplication.cpp:1092
 #26 0x7fad879f6a9c in QCoreApplication::sendSpontaneousEvent(QObject*, QEvent*) kernel/qcoreapplication.cpp:1499
 #27 0x7fad88464930 in QGuiApplicationPrivate::processMouseEvent(QWindowSystemInterfacePrivate::MouseEvent*) kernel/qguiapplication.cpp:2188
 #28 0x7fad884699ae in QGuiApplicationPrivate::processWindowSystemEvent(QWindowSystemInterfacePrivate::WindowSystemEvent*) kernel/qguiapplication.cpp:1920
 #29 0x7fad883bc836 in QWindowSystemInterface::sendWindowSystemEvents(QFlags<QEventLoop::ProcessEventsFlag>) kernel/qwindowsysteminterface.cpp:1163
```

## Fix commit message(s)

`2ad3348031d8`

```
QPrintDialog: don't access dangling pointer when cups is disabled

When no cups support is available, ui.pagesRadioButton is destroyed in
QPrintDialogPrivate::init() but was accessed later on. Fix it by moving
the cups check one line above.

Fixes: QTBUG-80945
Change-Id: Ieb062b39e1461f39665ef612dfea1d7757274b7e
Reviewed-by: Timur Pocheptsov <timur.pocheptsov@qt.io>
```

## Files the fix changed

Snapshot holds 6,981 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/printsupport/dialogs/qprintdialog_unix.cpp`

## The fix diff

### `src/printsupport/dialogs/qprintdialog_unix.cpp`

```diff
diff --git a/src/printsupport/dialogs/qprintdialog_unix.cpp b/src/printsupport/dialogs/qprintdialog_unix.cpp
index c7328d97329..7bbf1379771 100644
--- a/src/printsupport/dialogs/qprintdialog_unix.cpp
+++ b/src/printsupport/dialogs/qprintdialog_unix.cpp
@@ -635,12 +635,14 @@ void QPrintDialogPrivate::init()
     // Add Page Set widget if CUPS is available
     options.pageSetCombo->addItem(tr("All Pages"), QVariant::fromValue(QCUPSSupport::AllPages));
     options.pageSetCombo->addItem(tr("Odd Pages"), QVariant::fromValue(QCUPSSupport::OddPages));
     options.pageSetCombo->addItem(tr("Even Pages"), QVariant::fromValue(QCUPSSupport::EvenPages));
 #else
-    for (int i = options.pagesLayout->count() - 1; i >= 0; --i)
-        delete options.pagesLayout->itemAt(i)->widget();
+    delete options.pagesRadioButton;
+    delete options.pagesLineEdit;
+    options.pagesRadioButton = nullptr;
+    options.pagesLineEdit = nullptr;
 #endif
 
     top->d->setOptionsPane(this);
 
     buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, Qt::Horizontal, q);
@@ -725,16 +727,16 @@ void QPrintDialogPrivate::selectPrinter(const QPrinter::OutputFormat outputForma
 
             options.pageSetCombo->setEnabled(false);
         else
             options.pageSetCombo->setEnabled(true);
 
+#if QT_CONFIG(cups)
         // Disable complex page ranges widget when printing to pdf
         // It doesn't work since it relies on cups to do the heavy lifting and cups
         // is not used when printing to PDF
         options.pagesRadioButton->setEnabled(outputFormat != QPrinter::PdfFormat);
 
-#if QT_CONFIG(cups)
         // Disable color options on main dialog if not printing to file, it will be handled by CUPS advanced dialog
         options.colorMode->setVisible(outputFormat == QPrinter::PdfFormat);
 #endif
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
