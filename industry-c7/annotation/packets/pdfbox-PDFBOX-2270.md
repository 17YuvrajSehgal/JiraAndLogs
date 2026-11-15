# Annotation packet: PDFBOX-2270  (pdfbox)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
PDField.getFullyQualifiedName() returns name adding suffix '.null'

We have several pdf files where each one contains one pdf form with their own fields. We need to read all pdf fields and list them into a txt file.
 
The problem comes when a pdf form has duplicated field names, so the field.getFullyQualifiedName() returns the name of the field wrong, adding '.null' at the final of field's names.

-->Situation:
1) PDf file containing a pdf form
2) The pdf form contains lot of fields, some of their field's names are duplicated, like for example 'Applicant.city'.
3) When I try to list all of field's names, duplicate field's names comes with a suffix '.null' --> this only happends on duplicated field's names.
----------------------------------------------------------------------------------------------

-->Example:
1) PDF Form with 4 fields whos names are: 'Applicant.name', 'Applicant.phone', 'Applicant.ssn', 'Applicant.name'.

2)After running the code shown bellow, the result list is: 'Applicant.name.null', 'Applicant.phone', 'Applicant.ssn', 'Applicant.name.null'.
----------------------------------------------------------------------------------------------

-->Attach the code for listing all pdf form field's names:

 public static Set<String> printFields( PDDocument doc ) throws IOException {
        PDDocumentCatalog docCatalog = doc.getDocumentCatalog();
        PDAcroForm acroForm = docCatalog.getAcroForm();
        List fields = acroForm.getFields();
        Iterator fieldsIter = fields.iterator();
        
        Set<String> fieldSet = new HashSet<String>();
        
        while ( fieldsIter.hasNext() ){
            PDField field = (PDField)fieldsIter.next();
            // String fieldFullName = processField(field);
            fieldSet.addAll( processField( field ) );
        }
        
        return fieldSet;
    }
    
    
    private static Set<String> processField( PDField field ) throws IOException {
        List kids = field.getKids();
        Set<String> result = new HashSet<String>();
        if( kids != null ){
            Iterator kidsIter = kids.iterator();
            
            while ( kidsIter.hasNext() ){
                Object pdfObj = kidsIter.next();
                if( pdfObj instanceof PDField ){
                    PDField kid = (PDField)pdfObj;
                    result.addAll( processField( kid ) );
                }
            }
        }else{
            
            //System.out.println( "field.getFullyQualifiedName(): " + field.getFullyQualifiedName() );
            
            result.add( field.getFullyQualifiedName() );
        }
        
        return result;
        
    }
--------------------------------------------------------------------------------
field.getFullyQualifiedName()  is returning duplicated field's names with a prefix '.null'.

Thanks in advance.
```

## Fix commit message(s)

`cd0095462228`

```
PDFBOX-2270: optimized handling of null values

git-svn-id: https://svn.apache.org/repos/asf/pdfbox/trunk@1621478 13f79535-47bb-0310-9956-ffa450edef68
```

## Files the fix changed

Snapshot holds 846 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `examples/src/main/java/org/apache/pdfbox/examples/fdf/PrintFields.java`
- `pdfbox/src/main/java/org/apache/pdfbox/pdmodel/interactive/form/PDFieldTreeNode.java`

## The fix diff

### `examples/src/main/java/org/apache/pdfbox/examples/fdf/PrintFields.java`

```diff
diff --git a/examples/src/main/java/org/apache/pdfbox/examples/fdf/PrintFields.java b/examples/src/main/java/org/apache/pdfbox/examples/fdf/PrintFields.java
index a54dbdcaec..5df9c69893 100644
--- a/examples/src/main/java/org/apache/pdfbox/examples/fdf/PrintFields.java
+++ b/examples/src/main/java/org/apache/pdfbox/examples/fdf/PrintFields.java
@@ -69,11 +69,14 @@ public class PrintFields
         if (kids != null)
         {
             Iterator<COSObjectable> kidsIter = kids.iterator();
             if (field != null && !sParent.equals(field.getPartialName()))
             {
-                sParent = sParent + "." + partialName;
+                if (partialName != null)
+                {
+                    sParent = sParent + "." + partialName;
+                }
             }
             System.out.println(sLevel + sParent);
             while (kidsIter.hasNext())
             {
                 Object pdfObj = kidsIter.next();
@@ -103,15 +106,20 @@ public class PrintFields
                 {
                     fieldValue = field.getValue().toString();
                 }
                 else
                 {
-                    fieldValue = "";
+                    fieldValue = "no value available";
                 }
             }
-            String outputString = sLevel + sParent + "." + partialName + " = " + fieldValue + ",  type="
-                    + field.getClass().getName();
+            StringBuilder outputString = new StringBuilder(sLevel + sParent);
+            if (partialName != null)
+            {
+                outputString.append( "." + partialName);
+            }
+            outputString.append(" = " + fieldValue);
+            outputString.append(",  type=" + field.getClass().getName());
             System.out.println(outputString);
         }
     }
 
     /**
```

### `pdfbox/src/main/java/org/apache/pdfbox/pdmodel/interactive/form/PDFieldTreeNode.java`

```diff
diff --git a/pdfbox/src/main/java/org/apache/pdfbox/pdmodel/interactive/form/PDFieldTreeNode.java b/pdfbox/src/main/java/org/apache/pdfbox/pdmodel/interactive/form/PDFieldTreeNode.java
index 2473eb9a4c..554a31eb24 100644
--- a/pdfbox/src/main/java/org/apache/pdfbox/pdmodel/interactive/form/PDFieldTreeNode.java
+++ b/pdfbox/src/main/java/org/apache/pdfbox/pdmodel/interactive/form/PDFieldTreeNode.java
@@ -564,15 +564,22 @@ public abstract class PDFieldTreeNode implements COSObjectable
      * 
      * @throws IOException If there is an error generating the fully qualified name.
      */
     public String getFullyQualifiedName() throws IOException
     {
-        String parentName = getParent() != null ? getParent().getFullyQualifiedName() : null;
         String finalName = getPartialName();
+        String parentName = getParent() != null ? getParent().getFullyQualifiedName() : null;
         if (parentName != null)
         {
-            finalName = parentName + "." + finalName;
+            if (finalName != null)
+            {
+                finalName = parentName + "." + finalName;
+            }
+            else
+            {
+                finalName = parentName;
+            }
         }
         return finalName;
     }
 
     /**
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
