# Annotation packet: GROOVY-8953  (groovy)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Imported enum causes compilation bug preventing tests from compiling

In early December our spock tests were compiling fine, but at the start of this year they're all breaking with the following error:

Error:Groovyc: While compiling tests of REDACTED: BUG! exception in phase 'semantic analysis' in source unit 'REDACTEDSpec.groovy' Constructor parameter annotations length [5] does not match the parameter length: private REDACTEDENUMCLASS(java.lang.String,int,int,java.lang.String,ANOTHERREDACTEDENUMCLASS,java.lang.String,java.util.regex.Pattern)
    at org.codehaus.groovy.vmplugin.v5.Java5.getConstructorParameterAnnotations(Java5.java:438)
    at org.codehaus.groovy.vmplugin.v5.Java5.configureClassNode(Java5.java:386)
    at org.codehaus.groovy.ast.ClassNode.lazyClassInit(ClassNode.java:280)
    at org.codehaus.groovy.ast.ClassNode.getDeclaredMethods(ClassNode.java:877)
    at org.codehaus.groovy.ast.ClassNode.getMethods(ClassNode.java:892)
    at org.codehaus.groovy.ast.ClassNode.hasPossibleStaticMethod(ClassNode.java:1313)
    at org.codehaus.groovy.control.StaticImportVisitor.findStaticMethod(StaticImportVisitor.java:597)
    at org.codehaus.groovy.control.StaticImportVisitor.findStaticPropertyAccessorByFullName(StaticImportVisitor.java:565)
    at org.codehaus.groovy.control.StaticImportVisitor.findStaticPropertyAccessor(StaticImportVisitor.java:532)
    at org.codehaus.groovy.control.StaticImportVisitor.findStaticFieldOrPropAccessorImportFromModule(StaticImportVisitor.java:440)
    at org.codehaus.groovy.control.StaticImportVisitor.transformVariableExpression(StaticImportVisitor.java:198)
    at org.codehaus.groovy.control.StaticImportVisitor.transform(StaticImportVisitor.java:99)
    at org.codehaus.groovy.ast.expr.Expression.transformExpressions(Expression.java:51)
    at org.codehaus.groovy.ast.expr.ArgumentListExpression.transformExpression(ArgumentListExpression.java:69)
    at org.codehaus.groovy.control.StaticImportVisitor.transform(StaticImportVisitor.java:117)
    at org.codehaus.groovy.ast.expr.ConstructorCallExpression.transformExpression(ConstructorCallExpression.java:50)
    at org.codehaus.groovy.control.StaticImportVisitor.transformConstructorCallExpression(StaticImportVisitor.java:339)
    at org.codehaus.groovy.control.StaticImportVisitor.transform(StaticImportVisitor.java:114)
    at org.codehaus.groovy.ast.ClassCodeExpressionTransformer.visitField(ClassCodeExpressionTransformer.java:70)
    at org.codehaus.groovy.ast.ClassNode.visitContents(ClassNode.java:1073)
    at org.codehaus.groovy.ast.ClassCodeVisitorSupport.visitClass(ClassCodeVisitorSupport.java:53)
    at org.codehaus.groovy.control.StaticImportVisitor.visitClass(StaticImportVisitor.java:78)
    at org.codehaus.groovy.control.CompilationUnit$13.call(CompilationUnit.java:692)
    at org.codehaus.groovy.control.CompilationUnit.applyToPrimaryClassNodes(CompilationUnit.java:1087)
    at org.codehaus.groovy.control.CompilationUnit.doPhaseOperation(CompilationUnit.java:624)
    at org.codehaus.groovy.control.CompilationUnit.processPhaseOperations(CompilationUnit.java:602)
    at org.codehaus.groovy.control.CompilationUnit.compile(CompilationUnit.java:579)
    at org.jetbrains.groovy.compiler.rt.GroovyCompilerWrapper.compile(GroovyCompilerWrapper.java:62)
    at org.jetbrains.groovy.compiler.rt.DependentGroovycRunner.runGroovyc(DependentGroovycRunner.java:118)
    at sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
    at sun.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:62)
    at sun.reflect.DelegatingMethodAccessorImpl.invoke(DelegatingMethodAccessorImpl.java:43)
    at java.lang.reflect.Method.invoke(Method.java:498)
    at org.jetbrains.groovy.compiler.rt.GroovycRunner.intMain2(GroovycRunner.java:91)
    at sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
    at sun.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:62)
    at sun.reflect.DelegatingMethodAccessorImpl.invoke(DelegatingMethodAccessorImpl.java:43)
    at java.lang.reflect.Method.invoke(Method.java:498)
    at org.jetbrains.jps.incremental.groovy.InProcessGroovyc.runGroovycInThisProcess(InProcessGroovyc.java:160)
    at org.jetbrains.jps.incremental.groovy.InProcessGroovyc.lambda$runGroovyc$0(InProcessGroovyc.java:89)
    at java.util.concurrent.FutureTask.run(FutureTask.java:266)
    at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1149)
    at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:624)
    at java.lang.Thread.run(Thread.java:748)

The thing it's complaining about appears to be when using one of our enums in a spock test.
```

## Fix commit message(s)

`179d193a5a5f`

```
GROOVY-8953: Imported enum causes compilation bug preventing tests from compiling (closes #885)
```

## Files the fix changed

Snapshot holds 1,630 non-test source files. The fix changed 4 file(s); 1 of them are non-test source files (listed below as gold).

- `src/main/java/org/codehaus/groovy/vmplugin/v5/Java5.java`

## The fix diff

### `src/main/java/org/codehaus/groovy/vmplugin/v5/Java5.java`

```diff
diff --git a/src/main/java/org/codehaus/groovy/vmplugin/v5/Java5.java b/src/main/java/org/codehaus/groovy/vmplugin/v5/Java5.java
index b7454055ee..44d18ee138 100644
--- a/src/main/java/org/codehaus/groovy/vmplugin/v5/Java5.java
+++ b/src/main/java/org/codehaus/groovy/vmplugin/v5/Java5.java
@@ -448,22 +448,24 @@ public class Java5 implements VMPlugin {
          */
         int parameterCount = constructor.getParameterTypes().length;
         Annotation[][] annotations = constructor.getParameterAnnotations();
         int diff = parameterCount - annotations.length;
         if (diff > 0) {
-            // May happen on JDK8 and below, but we only expect to have to
-            // add a single element to the front of the array to account
-            // for the synthetic outer reference
-            if (diff > 1) {
+            // May happen on JDK8 and below. We add elements to the front of the array to account for the synthetic params:
+            // - for an inner class we expect one param to account for the synthetic outer reference
+            // - for an enum we expect two params to account for the synthetic name and ordinal
+            if ((!constructor.getDeclaringClass().isEnum() && diff > 1) || diff > 2) {
                 throw new GroovyBugError(
                         "Constructor parameter annotations length [" + annotations.length + "] " +
                         "does not match the parameter length: " + constructor
                 );
             }
             Annotation[][] adjusted = new Annotation[parameterCount][];
-            adjusted[0] = EMPTY_ANNOTATION_ARRAY;
-            System.arraycopy(annotations, 0, adjusted, 1, annotations.length);
+            for (int i = 0; i < diff; i++) {
+                adjusted[i] = EMPTY_ANNOTATION_ARRAY;
+            }
+            System.arraycopy(annotations, 0, adjusted, diff, annotations.length);
             return adjusted;
         }
         return annotations;
     }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
