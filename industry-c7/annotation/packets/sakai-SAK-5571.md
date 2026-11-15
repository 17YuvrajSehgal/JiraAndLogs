# Annotation packet: SAK-5571  (sakai)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Remove hard-coded /portal path

"/portal" should not be hard-coded - see SAK-4576 for background:

sam/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/servlet/delivery/LoginServlet.java:            path = "/portal/login?url=" + URLEncoder.encode(req.getRequestURL().toString()+"?id="+alias, "UTF-8");
sam/samigo-app/src/webapp/jsf/delivery/beginTakingAssessment.jsp:     style="act" onclick="javascript:window.open('/portal/login','_top')"
sam/samigo-app/src/webapp/jsf/delivery/beginTakingAssessment.jsp:onkeypress="javascript:window.open('/portal/login','_top')"
sam/samigo-app/src/webapp/jsf/delivery/login.jsp:      <meta http-equiv="Refresh" content="0; URL=/portal/"/>
sam/samigo-app/src/webapp/jsf/delivery/anonymousThankyouMessage.jsp:     style="act" onclick="javascript:window.open('/portal/login','_top')" onkeypress="javascript:window.open('/portal/login','_top')" />
sam/samigo-app/src/webapp/jsf/delivery/anonymousQuitMessage.jsp:     onclick="javascript:window.open('/portal/login','_top')" onkeypress="javascript:window.open('/portal/login','_top')" />
sam/samigo-app/src/webapp/jsf/delivery/accessDenied.jsp:     styleClass="active" onclick="javascript:window.open('/portal/login','_top')" onkeypress="javascript:window.open('/portal/login','_top')" />
sam/samigo-app/src/webapp/jsf/delivery/mediaAccessDenied.jsp:     styleClass="active" onclick="javascript:window.open('/portal/login','_top')" onkeypress="javascript:window.open('/portal/login','_top')" />
sam/samigo-app/src/webapp/jsf/delivery/assessmentNotAvailable.jsp:       style="act" onclick="javascript:window.open('/portal/login','_top')" onkeypress="javascript:window.open('/portal/login','_top')" />
sam/samigo-app/sakai-samigo/webapp/jsf/index/index.jsp:      <meta http-equiv="Refresh" content="0; URL=/portal"/>
sam/samigo-app/sakai-samigo/webapp/jsf/delivery/login.jsp:      <meta http-equiv="Refresh" content="0; URL=/portal"/>
```

## Fix commit message(s)

`d49bc332ca90`

```
SAK-5571

git-svn-id: https://source.sakaiproject.org/svn/sam/trunk@17146 66ffb92e-73f9-0310-93c1-f5514f145a0a
```

## Files the fix changed

Snapshot holds 520 non-test source files. The fix changed 9 file(s); 2 of them are non-test source files (listed below as gold).

- `samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBean.java`
- `samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/shared/PersonBean.java`

## The fix diff

### `samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBean.java`

```diff
diff --git a/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBean.java b/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBean.java
index f1aff4da92..b61b875fca 100755
--- a/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBean.java
+++ b/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/delivery/DeliveryBean.java
@@ -71,10 +71,11 @@ import org.sakaiproject.tool.cover.ToolManager;
 import org.sakaiproject.tool.api.Placement; 
 // note: we should wrap above dependency in a backend service--esmiley
 
 import java.text.SimpleDateFormat;
 import org.sakaiproject.tool.assessment.ui.listener.util.TimeUtil;
+import org.sakaiproject.component.cover.ServerConfigurationService;
 
 /**
  *
  * @author casong
  * @author esmiley@stanford.edu added agentState
@@ -2545,6 +2546,11 @@ public class DeliveryBean
     if (assessmentGrading !=null){
       return assessmentGrading.getForGrade().booleanValue();
     }
     else return false;
   }
+
+  public String getPortal(){
+   return ServerConfigurationService.getString("portalPath");
+  }
+
 }
```

### `samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/shared/PersonBean.java`

```diff
diff --git a/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/shared/PersonBean.java b/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/shared/PersonBean.java
index d852e01128..26a228e647 100644
--- a/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/shared/PersonBean.java
+++ b/samigo/samigo-app/src/java/org/sakaiproject/tool/assessment/ui/bean/shared/PersonBean.java
@@ -128,6 +128,7 @@ private static Log log = LogFactory.getLog(PersonBean.class);
   public String cleanResourceIdListInPreview(){
     AssessmentService service = new AssessmentService();
     service.deleteResources(resourceIdList);
     return "editAssessment";
   }  
+
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
