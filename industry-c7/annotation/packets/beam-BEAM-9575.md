# Annotation packet: BEAM-9575  (beam)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
beam_PostCommit_PortableJar_Flink and beam_PostCommit_PortableJar_Spark failing

Task :runners:flink:1.10:job-server:testJavaJarCreatorPy37 is failing:

11:23:49 Traceback (most recent call last):
11:23:49   File "<string>", line 24, in <module>
11:23:49   File "/home/jenkins/jenkins-slave/workspace/beam_PostCommit_PortableJar_Flink/src/sdks/python/apache_beam/runners/portability/portable_runner.py", line 545, in wait_until_finish
11:23:49     (self._job_id, self._state, self._last_error_message()))
11:23:49 RuntimeError: Pipeline BeamApp-jenkins-0323182347-56de7e22_388a77e1-7cd2-40cd-a0b8-5ea029aba475 failed in state FAILED: java.lang.IllegalArgumentException: Expected exactly one jar on sun.misc.Launcher$AppClassLoader@1b6d3586

Same error for :runners:spark:job-server:testJavaJarCreatorPy37.
```

## Fix commit message(s)

`a15dd3b57a24`

```
[BEAM-9575] Only copy the Spark runner jar, not whatever other jars happen to be on the classloader.
```

## Files the fix changed

Snapshot holds 3,556 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `runners/java-job-service/src/main/java/org/apache/beam/runners/jobsubmission/PortablePipelineJarCreator.java`

## The fix diff

### `runners/java-job-service/src/main/java/org/apache/beam/runners/jobsubmission/PortablePipelineJarCreator.java`

```diff
diff --git a/runners/java-job-service/src/main/java/org/apache/beam/runners/jobsubmission/PortablePipelineJarCreator.java b/runners/java-job-service/src/main/java/org/apache/beam/runners/jobsubmission/PortablePipelineJarCreator.java
index ef050752d76..a0c598308aa 100644
--- a/runners/java-job-service/src/main/java/org/apache/beam/runners/jobsubmission/PortablePipelineJarCreator.java
+++ b/runners/java-job-service/src/main/java/org/apache/beam/runners/jobsubmission/PortablePipelineJarCreator.java
@@ -26,11 +26,10 @@ import java.io.InputStream;
 import java.nio.channels.Channels;
 import java.nio.channels.WritableByteChannel;
 import java.nio.charset.StandardCharsets;
 import java.util.Enumeration;
 import java.util.HashSet;
-import java.util.List;
 import java.util.Map;
 import java.util.Set;
 import java.util.UUID;
 import java.util.jar.Attributes;
 import java.util.jar.Attributes.Name;
@@ -40,21 +39,18 @@ import java.util.jar.JarOutputStream;
 import java.util.jar.Manifest;
 import org.apache.beam.model.jobmanagement.v1.JobApi;
 import org.apache.beam.model.pipeline.v1.RunnerApi;
 import org.apache.beam.model.pipeline.v1.RunnerApi.Pipeline;
 import org.apache.beam.runners.core.construction.PipelineOptionsTranslation;
-import org.apache.beam.runners.core.construction.resources.PipelineResources;
 import org.apache.beam.runners.fnexecution.artifact.ArtifactRetrievalService;
 import org.apache.beam.runners.fnexecution.provisioning.JobInfo;
 import org.apache.beam.sdk.io.ClassLoaderFileSystem;
 import org.apache.beam.sdk.metrics.MetricResults;
-import org.apache.beam.sdk.options.PipelineOptions;
 import org.apache.beam.sdk.options.PortablePipelineOptions;
 import org.apache.beam.vendor.grpc.v1p26p0.com.google.protobuf.MessageOrBuilder;
 import org.apache.beam.vendor.grpc.v1p26p0.com.google.protobuf.util.JsonFormat;
 import org.apache.beam.vendor.guava.v26_0_jre.com.google.common.annotations.VisibleForTesting;
-import org.apache.beam.vendor.guava.v26_0_jre.com.google.common.base.Preconditions;
 import org.apache.beam.vendor.guava.v26_0_jre.com.google.common.collect.ImmutableList;
 import org.apache.beam.vendor.guava.v26_0_jre.com.google.common.io.ByteStreams;
 import org.apache.commons.compress.utils.IOUtils;
 import org.joda.time.Duration;
 import org.slf4j.Logger;
@@ -96,11 +92,12 @@ public class PortablePipelineJarCreator implements PortablePipelineRunner {
     LOG.info("Creating jar {} for job {}", outputFile.getAbsolutePath(), jobName);
     outputStream =
         new JarOutputStream(new FileOutputStream(outputFile), createManifest(mainClass, jobName));
     outputChannel = Channels.newChannel(outputStream);
     PortablePipelineJarUtils.writeDefaultJobName(outputStream, jobName);
-    writeClassPathResources(mainClass.getClassLoader(), pipelineOptions);
+    copyResourcesFromJar(
+        new JarFile(mainClass.getProtectionDomain().getCodeSource().getLocation().getPath()));
     writeAsJson(
         PipelineOptionsTranslation.toProto(pipelineOptions),
         PortablePipelineJarUtils.getPipelineOptionsUri(jobName));
     Pipeline pipelineWithClasspathArtifacts = writeArtifacts(pipeline, jobName);
     writeAsJson(pipelineWithClasspathArtifacts, PortablePipelineJarUtils.getPipelineUri(jobName));
@@ -133,20 +130,10 @@ public class PortablePipelineJarCreator implements PortablePipelineRunner {
       manifest.getMainAttributes().put(Name.MAIN_CLASS, mainClass.getName());
     }
     return manifest;
   }
 
-  /** Copy resources from {@code classLoader} to {@link #outputStream}. */
-  private void writeClassPathResources(ClassLoader classLoader, PipelineOptions options)
-      throws IOException {
-    List<String> classPathResources =
-        PipelineResources.detectClassPathResourcesToStage(classLoader, options);
-    Preconditions.checkArgument(
-        classPathResources.size() == 1, "Expected exactly one jar on " + classLoader.toString());
-    copyResourcesFromJar(new JarFile(classPathResources.get(0)));
-  }
-
   /** Copy resources from {@code inputJar} to {@link #outputStream}. */
   @VisibleForTesting
   protected void copyResourcesFromJar(JarFile inputJar) throws IOException {
     Enumeration<JarEntry> inputJarEntries = inputJar.entries();
     // The zip spec allows multiple files with the same name; the Java zip libraries do not.
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
