# Annotation packet: QTBUG-85683  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Windows: "Unable to enumerate family" for fonts with lengthy family name

Windows font database is tries to register extra names for fonts. For families with long names this may result in an attempt to register a too long name which would cause a warning:

_qt.qpa.fonts: Unable to enumerate family ' "Droid Sans Mono Dotted for Powerline" '_

The issue can be reproduced at least with the font mentioned above in the warning. If it's installed all that's required to reproduce the warning is to run the attached app.
```

## Fix commit message(s)

`29b2387587fe`

```
(empty)
```

## Files the fix changed

Snapshot holds 5,849 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/gui/text/windows/qwindowsfontdatabase.cpp`

## The fix diff

### `src/gui/text/windows/qwindowsfontdatabase.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
