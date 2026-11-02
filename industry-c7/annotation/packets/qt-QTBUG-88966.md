# Annotation packet: QTBUG-88966  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
[REG 5.15 -> 6.0.0] Crash when expanding items in QTreeView

Add below test to tst_qtreeview.cpp:

{noformat}
static void populateModel(QStandardItemModel *model)
{
    const int depth = 10;
    for (int i1 = 0; i1 < depth; ++i1) {
        QStandardItem *s1 = new QStandardItem;
        s1->setText(QString::number(i1));
        model->appendRow(s1);
        for (int i2 = 0; i2 < depth; ++i2) {
            QStandardItem *s2 = new QStandardItem;
            s2->setText(QStringLiteral("%1 - %2").arg(i1).arg(i2));
            s1->appendRow(s2);
            for (int i3 = 0; i3 < depth; ++i3) {
                QStandardItem *s3 = new QStandardItem;
                s3->setText(QStringLiteral("%1 - %2 - %3").arg(i1).arg(i2).arg(i3));
                s2->appendRow(s3);
            }
        }
    }
}

void tst_QTreeView::expandAfterTake()
{
    QStandardItemModel model;
    populateModel(&model);
    QTreeView view;
    view.setUniformRowHeights(true);
    view.setModel(&model);
    view.show();
    QVERIFY(QTest::qWaitForWindowExposed(&view));

    view.expandAll();
    while (model.takeItem(0))
        ; // mimic clear, but this leaves QTreeViewPrivate::expandedIndexes dirty with corrupted items

    populateModel(&model); // populate model again, having corrupted items inside QTreeViewPrivate::expandedIndexes
    view.expandAll(); // adding new items to QTreeViewPrivate::expandedIndexes with corrupted persistent indices, causing crash sometimes
}
{noformat}

Sometimes it happens, that this test passes, however, in more than 50% cases it crashes with assert:
{noformat}
QFATAL : tst_QTreeView::expandAfterTake() ASSERT: "it.isUnused()" in file ../../include/QtCore/../../../../qt-dev/qtbase/src/corelib/tools/qhash.h, line 519
FAIL!  : tst_QTreeView::expandAfterTake() Received a fatal error.
   Loc: [Unknown file(0)]
Totals: 96 passed, 1 failed, 0 skipped, 0 blacklisted, 7099ms
{noformat}

Call stack:
{noformat}
#0  0x00007ffff580e9d5 in raise () from /lib64/libc.so.6
#1  0x00007ffff57f78a4 in abort () from /lib64/libc.so.6
#2  0x00007ffff5e98f99 in qt_message_fatal (context=..., message=...)
    at /home/jarek/dev/qt-dev/qtbase/src/corelib/global/qlogging.cpp:1893
#3  0x00007ffff5e9524e in QMessageLogger::fatal (this=0x7fffffffbf50, msg=0x7ffff631bea8 "ASSERT: \"%s\" in file %s, line %d")
    at /home/jarek/dev/qt-dev/qtbase/src/corelib/global/qlogging.cpp:889
#4  0x00007ffff5e87864 in qt_assert (assertion=0x7ffff7d2c00a "it.isUnused()", 
    file=0x7ffff7d2bb38 "../../include/QtCore/../../../../qt-dev/qtbase/src/corelib/tools/qhash.h", line=519)
    at /home/jarek/dev/qt-dev/qtbase/src/corelib/global/qglobal.cpp:3108
#5  0x00007ffff7ac5137 in QHashPrivate::Data<QHashPrivate::Node<QPersistentModelIndex, QHashDummyValue> >::rehash (this=0x659290, 
    sizeHint=2049) at ../../include/QtCore/../../../../qt-dev/qtbase/src/corelib/tools/qhash.h:519
#6  0x00007ffff7ac38e2 in QHashPrivate::Data<QHashPrivate::Node<QPersistentModelIndex, QHashDummyValue> >::findOrInsert (
    this=0x659290, key=...) at ../../include/QtCore/../../../../qt-dev/qtbase/src/corelib/tools/qhash.h:589
#7  0x00007ffff7ac1f83 in QHash<QPersistentModelIndex, QHashDummyValue>::emplace<QHashDummyValue const&> (this=0x9119d0, key=...)
    at ../../include/QtCore/../../../../qt-dev/qtbase/src/corelib/tools/qhash.h:1121
#8  0x00007ffff7ac01a0 in QHash<QPersistentModelIndex, QHashDummyValue>::emplace<QHashDummyValue const&> (this=0x9119d0, key=...)
    at ../../include/QtCore/../../../../qt-dev/qtbase/src/corelib/tools/qhash.h:1113
#9  0x00007ffff7abe3b7 in QHash<QPersistentModelIndex, QHashDummyValue>::insert (this=0x9119d0, key=..., value=...)
    at ../../include/QtCore/../../../../qt-dev/qtbase/src/corelib/tools/qhash.h:1091
#10 0x00007ffff7abc9c8 in QSet<QPersistentModelIndex>::insert (this=0x9119d0, value=...)
    at ../../include/QtCore/../../../../qt-dev/qtbase/src/corelib/tools/qset.h:181
#11 0x00007ffff7b1e5b9 in QTreeViewPrivate::storeExpanded (this=0x9114d0, idx=...)
    at ../../include/QtWidgets/6.0.0/QtWidgets/private/../../../../../../../qt-dev/qtbase/src/widgets/itemviews/qtreeview_p.h:215
#12 0x00007ffff7b1a5e7 in QTreeViewPrivate::layout (this=0x9114d0, i=1933, recursiveExpanding=true, afterIsUninitialized=true)
    at /home/jarek/dev/qt-dev/qtbase/src/widgets/itemviews/qtreeview.cpp:3404
#13 0x00007ffff7b1a663 in QTreeViewPrivate::layout (this=0x9114d0, i=1888, recursiveExpanding=true, afterIsUninitialized=true)
    at /home/jarek/dev/qt-dev/qtbase/src/widgets/itemviews/qtreeview.cpp:3407
#14 0x00007ffff7b1a663 in QTreeViewPrivate::layout (this=0x9114d0, i=-1, recursiveExpanding=true, afterIsUninitialized=true)
    at /home/jarek/dev/qt-dev/qtbase/src/widgets/itemviews/qtreeview.cpp:3407
#15 0x00007ffff7b170cd in QTreeView::expandAll (this=0x7fffffffc5f0)
    at /home/jarek/dev/qt-dev/qtbase/src/widgets/itemviews/qtreeview.cpp:2699
#16 0x0000000000435dd3 in tst_QTreeView::expandAfterTake (this=0x7fffffffd620)
    at /home/jarek/dev/qt-dev/qtbase/tests/auto/widgets/itemviews/qtreeview/tst_qtreeview.cpp:1829
#17 0x0000000000465ae3 in tst_QTreeView::qt_static_metacall (_o=0x7fffffffd620, _c=QMetaObject::InvokeMetaMethod, _id=38, 
    _a=0x7fffffffc710) at .moc/tst_qtreeview.moc:640
#18 0x00007ffff61efd48 in QMetaMethod::invoke (this=0x5ddd50, object=0x7fffffffd620, connectionType=Qt::DirectConnection, 
    returnValue=..., val0=..., val1=..., val2=..., val3=..., val4=..., val5=..., val6=..., val7=..., val8=..., val9=...)
    at /home/jarek/dev/qt-dev/qtbase/src/corelib/kernel/qmetaobject.cpp:2322
#19 0x00007ffff663f588 in QMetaMethod::invoke (this=0x5ddd50, object=0x7fffffffd620, connectionType=Qt::DirectConnection, val0=..., 
    val1=..., val2=..., val3=..., val4=..., val5=..., val6=..., val7=..., val8=..., val9=...)
    at ../../include/QtCore/../../../../qt-dev/qtbase/src/corelib/kernel/qmetaobject.h:125
#20 0x00007ffff66373d7 in QTest::TestMethods::invokeTestOnData (this=0x7fffffffd420, index=31)
    at /home/jarek/dev/qt-dev/qtbase/src/testlib/qtestcase.cpp:934
#21 0x00007ffff6637f1b in QTest::TestMethods::invokeTest (this=0x7fffffffd420, index=31, data=0x0, watchDog=0x0)
    at /home/jarek/dev/qt-dev/qtbase/src/testlib/qtestcase.cpp:1163
--Type <RET> for more, q to quit, c to continue without paging-- 
#22 0x00007ffff663928f in QTest::TestMethods::invokeTests (this=0x7fffffffd420, testObject=0x7fffffffd620)
    at /home/jarek/dev/qt-dev/qtbase/src/testlib/qtestcase.cpp:1506
#23 0x00007ffff6639aa3 in QTest::qRun () at /home/jarek/dev/qt-dev/qtbase/src/testlib/qtestcase.cpp:1933
#24 0x00007ffff6639581 in QTest::qExec (testObject=0x7fffffffd620, argc=1, argv=0x7fffffffd748)
    at /home/jarek/dev/qt-dev/qtbase/src/testlib/qtestcase.cpp:1841
#25 0x000000000046563e in main (argc=1, argv=0x7fffffffd748)
    at /home/jarek/dev/qt-dev/qtbase/tests/auto/widgets/itemviews/qtreeview/tst_qtreeview.cpp:5261
{noformat}

For Qt 5.15 I cannot crash on the above test.

Please see https://codereview.qt-project.org/c/qt/qtbase/+/324206

This issue is a result of investigation on: QTCREATORBUG-24981
```

## Fix commit message(s)

`6012285e7ded`

```
Fix hashing of QPersistentModelIndex

The hash and equality operators used need to be consistent with
each other. Unfortunately, QPMI::operator==() is not suitable to do
this. So specialize qHashEquals() for QPMI.

Fixes: QTBUG-88966
Change-Id: If5f19a722ae9fc4e78e93537e7ea15726f148768
Reviewed-by: Jarek Kobus <jaroslaw.kobus@qt.io>
Reviewed-by: Volker Hilsheimer <volker.hilsheimer@qt.io>
(cherry picked from commit 83e95956ed58e88b11e2cc3cb61c5beacb7985db)
Reviewed-by: Qt Cherry-pick Bot <cherrypick_bot@qt-project.org>
```

## Files the fix changed

Snapshot holds 5,844 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/itemmodels/qabstractitemmodel.h`

## The fix diff

### `src/corelib/itemmodels/qabstractitemmodel.h`

```diff
diff --git a/src/corelib/itemmodels/qabstractitemmodel.h b/src/corelib/itemmodels/qabstractitemmodel.h
index 9b101061879..7479f4b043b 100644
--- a/src/corelib/itemmodels/qabstractitemmodel.h
+++ b/src/corelib/itemmodels/qabstractitemmodel.h
@@ -240,10 +240,12 @@ public:
     const QAbstractItemModel *model() const;
     bool isValid() const;
 private:
     QPersistentModelIndexData *d;
     friend size_t qHash(const QPersistentModelIndex &, size_t seed) noexcept;
+    friend bool qHashEquals(const QPersistentModelIndex &a, const QPersistentModelIndex &b) noexcept
+    { return a.d == b.d; }
 #ifndef QT_NO_DEBUG_STREAM
     friend Q_CORE_EXPORT QDebug operator<<(QDebug, const QPersistentModelIndex &);
 #endif
 };
 Q_DECLARE_SHARED(QPersistentModelIndex)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
