# Annotation packet: QTBUG-81604  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
A QImage created from certain jpg files cannot be saved as a PNG

Please see the attached project. It loads two jpg images and tries to save them as png. Image two gets converted to sRGB before saving. Both save calls return false, though the converted one actually does get saved. For the unconverted image a zero size file is created.

This is the debug output:

 

{color:#0000aa}09:35:21: Starting /home/boud/src/build-qimagetest-5_14-Debug/qimagetest ...{color}

{color:#aa0000}image1 false result true{color}

{color:#aa0000}image2 false result true{color}

{color:#aa0000}libpng error: known incorrect sRGB profile{color}

{color:#aa0000}Result of saving image1 as png false{color}

{color:#aa0000}Result of saving image2 as png false{color}

{color:#0000aa}09:35:22: /home/boud/src/build-qimagetest-5_14-Debug/qimagetest exited with code 0{color}
```

## Fix commit message(s)

`2d57dc2f3358`

```
(empty)
```

## Files the fix changed

Snapshot holds 6,983 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/gui/image/qpnghandler.cpp`

## The fix diff

### `src/gui/image/qpnghandler.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
