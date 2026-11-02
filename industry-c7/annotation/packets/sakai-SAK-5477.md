# Annotation packet: SAK-5477  (sakai)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
can't find feedbackDateString in DeliveryBeanie

   I had a 2 parts assessment using the Problem Set template, with delayed feedback on 07/08/2006 01:51:38 PM   ( I think this might be the cause).  layout:  displayed one part per page.   part1 has 2 questions, part2 has 1 question.
after i answered the 2 questions in part1, i clicked on table of content, and all my answers were lost.  (okay, this is a small bug) .  I clicked on 'save and continue' to go to the next page which is part 2,  after I answered the question in part 2, I clicked on TOC, my answers were saved. 

now i clicked on submit for grading, and I got this:  


caused by: org.apache.jasper.JasperException: javax.servlet.jsp.JspException: Error getting property 'feedbackDateString' from bean of type org.sakaiproject.tool.assessment.ui.bean.delivery.DeliveryBeanie     at org.apache.jasper.servlet.JspServletWrapper.service(JspServletWrapper.java:375) caused by: javax.servlet.ServletException: javax.servlet.jsp.JspException: Error getting property 'feedbackDateString' from bean of type org.sakaiproject.tool.assessment.ui.bean.delivery.DeliveryBeanie     at org.apache.jasper.runtime.PageContextImpl.handlePageException(PageContextImpl.java:791) caused by: javax.faces.el.PropertyNotFoundException: Error getting property 'feedbackDateString' from bean of type org.sakaiproject.tool.assessment.ui.bean.delivery.DeliveryBeanie  
I tried looking at the log for qa1-us but it's impossible to read it.   i looked in DeliveryBeanie.java and there is no property called feedbackDateString.  maybe that's why?
```

## Fix commit message(s)

`dab7db82c33d`

```
SAK-5477 - please mergee to 2.2 maintainence branch

git-svn-id: https://source.sakaiproject.org/svn/sam/trunk@11746 66ffb92e-73f9-0310-93c1-f5514f145a0a
```

## Files the fix changed

Snapshot holds 495 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBeanie.java`
- `samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/ItemContentsBean.java`

## The fix diff

### `samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBeanie.java`

```diff
diff --git a/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBeanie.java b/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBeanie.java
index d0de8b3957..aa5148fa4c 100755
--- a/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBeanie.java
+++ b/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBeanie.java
@@ -246,10 +246,29 @@ public class DeliveryBeanie
   public java.util.Date getFeedbackDate()
   {
     return feedbackDate;
   }
 
+  public String getFeedbackDateString()
+  {
+    String dateString = "";
+    if (feedbackDate== null) {
+      return dateString;
+    }
+
+    try {
+      TimeUtil tu = new TimeUtil();
+      dateString = tu.getDisplayDateTime(displayFormat, feedbackDate);
+    }
+    catch (Exception ex) {
+      // we will leave it as an empty string
+      log.warn("Unable to format date.");
+      ex.printStackTrace();
+    }
+    return dateString;
+  }
+
   public void setFeedbackDate(java.util.Date feedbackDate)
   {
     this.feedbackDate = feedbackDate;
   }
```

### `samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/ItemContentsBean.java`

```diff
diff --git a/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/ItemContentsBean.java b/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/ItemContentsBean.java
index 8925c48e55..466659b02e 100755
--- a/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/ItemContentsBean.java
+++ b/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/ItemContentsBean.java
@@ -823,11 +823,11 @@ log.debug("setReview():  setreview at the end = " + preview);
 	else
           m.setDurationIsOver(false);
       }
     }
     catch(Exception e){
-      log.log("**duration recorded is not an integer value="+e.getMessage());
+      log.info("**duration recorded is not an integer value="+e.getMessage());
     }
   }
 
   /**
    * Show the student score currently earned?
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
