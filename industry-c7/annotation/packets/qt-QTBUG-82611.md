# Annotation packet: QTBUG-82611  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Compilation broken on MSVC2019 

After c946b07d9c2023c56ec3cae3ef8a425d12f8d7df, Qt no longer compiles on MSVC2019. (log copy-pasted from https://codereview.qt-project.org/c/qt/qtbase/+/292232)

{code}
qtbase/src/corelib/tools/qvector.h(331): error C2664: 'QTypedArrayData<T>::iterator QVector<T>::erase(QTypedArrayData<T>::const_iterator)': cannot convert argument 1 from 'const QTypedArrayData<T>::iterator' to 'QTypedArrayData<T>::const_iterator'
        with
        [
            T=QItemSelectionRange
        ]
qtbase/src/corelib/tools/qvector.h(331): note: No user-defined-conversion operator available that can perform this conversion, or the operator cannot be called
qtbase/src/corelib/tools/qvector.h(374): note: see declaration of 'QVector<QItemSelectionRange>::erase'
qtbase/src/corelib/tools/qvector.h(322): note: while compiling class template member function 'int QVector<QItemSelectionRange>::removeAll(const T &)'
        with
        [
            T=QItemSelectionRange
        ]
qtbase\src\corelib\itemmodels\qitemselectionmodel.h(244): note: see reference to class template instantiation 'QVector<QItemSelectionRange>' being compiled
NMAKE : fatal error U1077: '"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Tools\MSVC\14.24.28314\bin\HostX86\x86\cl.EXE"' : return code '0x2'
Stop.
{code}
```

## Fix commit message(s)

`d1882c79f2e2`

```
(empty)
```

## Files the fix changed

Snapshot holds 6,900 non-test source files. The fix changed 6 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/tools/qarraydata.h`

## The fix diff

### `src/corelib/tools/qarraydata.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
