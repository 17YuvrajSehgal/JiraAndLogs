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
xkb.compose: get locale from user env settings

The setlocale call will only give useful results if the program
had previously set the current locale using setlocale...

See also "Compose Locale" section in xkbcommon doc:
https://xkbcommon.org/doc/current/group__compose.html#compose-locale

Fixes: QTBUG-85529
Pick-to: 6.2 6.1 6.0 5.15
Change-Id: I65b1ac86ea54445bc3a2e1707df79bd9f732ab46
Reviewed-by: Edward Welbourne <edward.welbourne@qt.io>
```

## Files the fix changed

Snapshot holds 5,922 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/plugins/platforminputcontexts/compose/qcomposeplatforminputcontext.cpp`

## The fix diff

### `src/plugins/platforminputcontexts/compose/qcomposeplatforminputcontext.cpp`

```diff
diff --git a/src/plugins/platforminputcontexts/compose/qcomposeplatforminputcontext.cpp b/src/plugins/platforminputcontexts/compose/qcomposeplatforminputcontext.cpp
index 4e9828663f6..da5235e491e 100644
--- a/src/plugins/platforminputcontexts/compose/qcomposeplatforminputcontext.cpp
+++ b/src/plugins/platforminputcontexts/compose/qcomposeplatforminputcontext.cpp
@@ -69,14 +69,20 @@ void QComposeInputContext::ensureInitialized()
         qCWarning(lcXkbCompose) << "error: xkb context has not been set on" << metaObject()->className();
         return;
     }
 
     m_initialized = true;
-    const char *locale = setlocale(LC_CTYPE, "");
-    if (!locale)
-        locale = setlocale(LC_CTYPE, nullptr);
-    qCDebug(lcXkbCompose) << "detected locale (LC_CTYPE):" << locale;
+    // Get locale from user env settings, see also
+    // https://xkbcommon.org/doc/current/group__compose.html#compose-locale
+    const char *locale = getenv("LC_ALL");
+    if (!locale || !*locale)
+        locale = getenv("LC_CTYPE");
+    if (!locale || !*locale)
+        locale = getenv("LANG");
+    if (!locale || !*locale)
+         locale = "C";
+    qCDebug(lcXkbCompose) << "detected locale:" << locale;
 
     m_composeTable = xkb_compose_table_new_from_locale(m_XkbContext, locale, XKB_COMPOSE_COMPILE_NO_FLAGS);
     if (m_composeTable)
         m_composeState = xkb_compose_state_new(m_composeTable, XKB_COMPOSE_STATE_NO_FLAGS);
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
