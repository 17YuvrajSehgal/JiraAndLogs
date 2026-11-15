# Annotation packet: PDFBOX-5046  (pdfbox)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
StringIndexOutOfBoundsException when doing DateConverter.parseDate()

Happens with "D:   " as a date.

{noformat}
java.lang.StringIndexOutOfBoundsException: String index out of range: 16
	at java.base/java.lang.StringLatin1.charAt(StringLatin1.java:48)
	at java.base/java.lang.String.charAt(String.java:711)
	at org.apache.pdfbox.util.DateConverter.parseDate(DateConverter.java:656)
	at org.apache.pdfbox.util.DateConverter.toCalendar(DateConverter.java:724)
{noformat}
```

## Fix commit message(s)

`81b8d4711442`

```
PDFBOX-5046: catch more empty dates

git-svn-id: https://svn.apache.org/repos/asf/pdfbox/trunk@1884416 13f79535-47bb-0310-9956-ffa450edef68
```

## Files the fix changed

Snapshot holds 1,140 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `pdfbox/src/main/java/org/apache/pdfbox/util/DateConverter.java`

## The fix diff

### `pdfbox/src/main/java/org/apache/pdfbox/util/DateConverter.java`

```diff
diff --git a/pdfbox/src/main/java/org/apache/pdfbox/util/DateConverter.java b/pdfbox/src/main/java/org/apache/pdfbox/util/DateConverter.java
index 9c642a7e08..3b20ff9ec0 100644
--- a/pdfbox/src/main/java/org/apache/pdfbox/util/DateConverter.java
+++ b/pdfbox/src/main/java/org/apache/pdfbox/util/DateConverter.java
@@ -618,11 +618,11 @@ public final class DateConverter
      * - The formats tried are alphaStartFormats or digitStartFormat and
      * any listed in the value of moreFmts.
      */
     private static Calendar parseDate(String text, ParsePosition initialWhere)
     {
-        if (text == null || text.isEmpty())
+        if (text == null || text.isEmpty() || "D:".equals(text.trim()))
         {
             return null;
         }
 
         // remember longestr date string
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
