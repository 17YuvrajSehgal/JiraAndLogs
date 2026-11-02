# Annotation packet: QTBUG-85529  (qt)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Polytonic Greek characters cannot be composed both ways

In any program using Qt, I can only input polytonic Greek character in one way, unlike in other toolkits, where I can compose them in multiple diacritic orders.

 

For instance, say I want to type ἄ. In Qt, I can only do this by typing the acute, then the smooth breathing, then α. In GTK and other toolkits, I can type either that or the smooth breathing, then the acute accent. then the α. This applies to all Greek characters having multiple diacritics.
```

## Fix commit message(s)

`73ea9f032864`

```
(empty)
```

## Files the fix changed

Snapshot holds 5,922 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/plugins/platforminputcontexts/compose/qcomposeplatforminputcontext.cpp`

## The fix diff

### `src/plugins/platforminputcontexts/compose/qcomposeplatforminputcontext.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
