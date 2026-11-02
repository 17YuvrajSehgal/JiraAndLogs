# Annotation packet: GROOVY-3685  (groovy)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Printing script causes the editor font to change

If you click the Print menu option from inside the Groovy Console, it causes the font in the editor to change

And writes:

{code}
2009-08-19 15:28:19.884 java[1597:613] Error loading /Library/Printers/hp/PDEs/hpPostScriptPDE.plugin/Contents/MacOS/hpPostScriptPDE:  dlopen(/Library/Printers/hp/PDEs/hpPostScriptPDE.plugin/Contents/MacOS/hpPostScriptPDE, 265): no suitable image found.  Did find:
	/Library/Printers/hp/PDEs/hpPostScriptPDE.plugin/Contents/MacOS/hpPostScriptPDE: no matching architecture in universal wrapper
{code}

to the command line
```

## Fix commit message(s)

`40a62cf58768`

```
GROOVY-3685: Printing script causes the editor font to change

git-svn-id: http://svn.codehaus.org/groovy/trunk/groovy/groovy-core@17577 a5544e8c-8a19-0410-ba12-f9af4593a198
```

## Files the fix changed

Snapshot holds 934 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/main/groovy/ui/text/TextEditor.java`

## The fix diff

### `src/main/groovy/ui/text/TextEditor.java`

```diff
diff --git a/src/main/groovy/ui/text/TextEditor.java b/src/main/groovy/ui/text/TextEditor.java
index fc3abff0d5..c27b73ae1e 100644
--- a/src/main/groovy/ui/text/TextEditor.java
+++ b/src/main/groovy/ui/text/TextEditor.java
@@ -262,10 +262,11 @@ public class TextEditor extends JTextPane implements Pageable, Printable {
 
             // initialize the PRINT_PANE (need this so that wrapping
             // can take place)
             PRINT_PANE.setDocument(getDocument());
 
+            PRINT_PANE.setFont(getFont());
             PRINT_SIZE.setSize(paper.getImageableWidth(),
                                getSize().getHeight());
             PRINT_PANE.setSize(PRINT_SIZE);
 
             // translate the graphics origin upwards so the area of the page we
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
