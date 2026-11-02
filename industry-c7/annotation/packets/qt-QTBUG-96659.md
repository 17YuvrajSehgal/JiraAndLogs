# Annotation packet: QTBUG-96659  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Compiler error in qproperty_p.h

When building Qt -6.2.0-rc I'm running into the following compiler error:
{noformat}
/disk3/qt/qt-everywhere-src-6.2.0-rc/qtbase/include/QtCore/6.2.0/QtCore/private/../../../../../src/corelib/kernel/qproperty_p.h:554:30: error: ‘(QItemSelectionModelPrivate::modelChanged != 0)’ is not a constant expression
         if constexpr (Signal != nullptr) {
                       ~~~~~~~^~~~~~~~~~
{noformat}

My compiler:

gcc (SUSE Linux) 10.2.1 20200825 [revision c0746a1beb1ba073c7981eb09f55b3d993b32e5c]
```

## Fix commit message(s)

`8cc6c7cd6eb8`

```
(empty)
```

## Files the fix changed

Snapshot holds 5,886 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/kernel/qproperty_p.h`

## The fix diff

### `src/corelib/kernel/qproperty_p.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
