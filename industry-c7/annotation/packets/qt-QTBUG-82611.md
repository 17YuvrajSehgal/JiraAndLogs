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
Get rid of some QT_STRICT_ITERATORS leftover

Amends 06456873fceddcd340431fc5999c50ff6d3c2371.

Fixes: QTBUG-82611
Change-Id: I8b1e01549f3e910b85a571833237e38a7c2b49a9
Reviewed-by: Simon Hausmann <simon.hausmann@qt.io>
```

## Files the fix changed

Snapshot holds 6,900 non-test source files. The fix changed 6 file(s); 1 of them are non-test source files (listed below as gold).

- `src/corelib/tools/qarraydata.h`

## The fix diff

### `src/corelib/tools/qarraydata.h`

```diff
diff --git a/src/corelib/tools/qarraydata.h b/src/corelib/tools/qarraydata.h
index 483f6d5edb5..d996b9c56b8 100644
--- a/src/corelib/tools/qarraydata.h
+++ b/src/corelib/tools/qarraydata.h
@@ -196,85 +196,12 @@ struct QArrayDataPointerRef
 
 template <class T>
 struct QTypedArrayData
     : QArrayData
 {
-#ifdef QT_STRICT_ITERATORS
-    class iterator {
-    public:
-        T *i;
-        typedef std::random_access_iterator_tag  iterator_category;
-        typedef int difference_type;
-        typedef T value_type;
-        typedef T *pointer;
-        typedef T &reference;
-
-        inline iterator() : i(nullptr) {}
-        inline iterator(T *n) : i(n) {}
-        inline iterator(const iterator &o): i(o.i){} // #### Qt 6: remove, the implicit version is fine
-        inline T &operator*() const { return *i; }
-        inline T *operator->() const { return i; }
-        inline T &operator[](int j) const { return *(i + j); }
-        inline bool operator==(const iterator &o) const { return i == o.i; }
-        inline bool operator!=(const iterator &o) const { return i != o.i; }
-        inline bool operator<(const iterator& other) const { return i < other.i; }
-        inline bool operator<=(const iterator& other) const { return i <= other.i; }
-        inline bool operator>(const iterator& other) const { return i > other.i; }
-        inline bool operator>=(const iterator& other) const { return i >= other.i; }
-        inline iterator &operator++() { ++i; return *this; }
-        inline iterator operator++(int) { T *n = i; ++i; return n; }
-        inline iterator &operator--() { i--; return *this; }
-        inline iterator operator--(int) { T *n = i; i--; return n; }
-        inline iterator &operator+=(int j) { i+=j; return *this; }
-        inline iterator &operator-=(int j) { i-=j; return *this; }
-        inline iterator operator+(int j) const { return iterator(i+j); }
-        inline iterator operator-(int j) const { return iterator(i-j); }
-        friend inline iterator operator+(int j, iterator k) { return k + j; }
-        inline int operator-(iterator j) const { return i - j.i; }
-        inline operator T*() const { return i; }
-    };
-    friend class iterator;
-
-    class const_iterator {
-    public:
-        const T *i;
-        typedef std::random_access_iterator_tag  iterator_category;
-        typedef int difference_type;
-        typedef T value_type;
-        typedef const T *pointer;
-        typedef const T &reference;
-
-        inline const_iterator() : i(nullptr) {}
-        inline const_iterator(const T *n) : i(n) {}
-        inline const_iterator(const const_iterator &o): i(o.i) {} // #### Qt 6: remove, the default version is fine
-        inline explicit const_iterator(const iterator &o): i(o.i) {}
-        inline const T &operator*() const { return *i; }
-        inline const T *operator->() const { return i; }
-        inline const T &operator[](int j) const { return *(i + j); }
-        inline bool operator==(const const_iterator &o) const { return i == o.i; }
-        inline bool operator!=(const const_iterator &o) const { return i != o.i; }
-        inline bool operator<(const const_iterator& other) const { return i < other.i; }
-        inline bool operator<=(const const_iterator& other) const { return i <= other.i; }
-        inline bool operator>(const const_iterator& other) const { return i > other.i; }
-        inline bool operator>=(const const_iterator& other) const { return i >= other.i; }
-        inline const_iterator &operator++() { ++i; return *this; }
-        inline const_iterator operator++(int) { const T *n = i; ++i; return n; }
-        inline const_iterator &operator--() { i--; return *this; }
-        inline const_iterator operator--(int) { const T *n = i; i--; return n; }
-        inline const_iterator &operator+=(int j) { i+=j; return *this; }
-        inline const_iterator &operator-=(int j) { i-=j; return *this; }
-        inline const_iterator operator+(int j) const { return const_iterator(i+j); }
-        inline const_iterator operator-(int j) const { return const_iterator(i-j); }
-        friend inline const_iterator operator+(int j, const_iterator k) { return k + j; }
-        inline int operator-(const_iterator j) const { return i - j.i; }
-        inline operator const T*() const { return i; }
-    };
-    friend class const_iterator;
-#else
     typedef T* iterator;
     typedef const T* const_iterator;
-#endif
 
     class AlignmentDummy { QArrayData header; T data; };
 
     Q_REQUIRED_RESULT static QPair<QTypedArrayData *, T *> allocate(size_t capacity,
             ArrayOptions options = DefaultAllocationFlags)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
