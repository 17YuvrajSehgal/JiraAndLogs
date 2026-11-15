# Annotation packet: HIVE-2334  (hive)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
DESCRIBE TABLE causes NPE when hive.cli.print.header=true
```

## Fix commit message(s)

`53cf27b41253`

```
HIVE-2334. DESCRIBE TABLE causes NPE when hive.cli.print.header=true (Jakob Homan via cws)

git-svn-id: https://svn.apache.org/repos/asf/hive/trunk@1159742 13f79535-47bb-0310-9956-ffa450edef68
```

## Files the fix changed

Snapshot holds 1,122 non-test source files. The fix changed 6 file(s); 1 of them are non-test source files (listed below as gold).

- `cli/src/java/org/apache/hadoop/hive/cli/CliDriver.java`

## The fix diff

### `cli/src/java/org/apache/hadoop/hive/cli/CliDriver.java`

```diff
diff --git a/cli/src/java/org/apache/hadoop/hive/cli/CliDriver.java b/cli/src/java/org/apache/hadoop/hive/cli/CliDriver.java
index a2976b511d..a689a2b7f9 100644
--- a/cli/src/java/org/apache/hadoop/hive/cli/CliDriver.java
+++ b/cli/src/java/org/apache/hadoop/hive/cli/CliDriver.java
@@ -46,11 +46,10 @@ import org.apache.hadoop.conf.Configuration;
 import org.apache.hadoop.hive.common.HiveInterruptUtils;
 import org.apache.hadoop.hive.common.LogUtils;
 import org.apache.hadoop.hive.common.LogUtils.LogInitializationException;
 import org.apache.hadoop.hive.conf.HiveConf;
 import org.apache.hadoop.hive.metastore.api.FieldSchema;
-import org.apache.hadoop.hive.metastore.api.Schema;
 import org.apache.hadoop.hive.ql.CommandNeedRetryException;
 import org.apache.hadoop.hive.ql.Driver;
 import org.apache.hadoop.hive.ql.exec.FunctionRegistry;
 import org.apache.hadoop.hive.ql.exec.HadoopJobExecHelper;
 import org.apache.hadoop.hive.ql.exec.Utilities;
@@ -81,25 +80,23 @@ public class CliDriver {
   public static final int LINES_TO_FETCH = 40; // number of lines to fetch in batch from remote hive server
 
   public static final String HIVERCFILE = ".hiverc";
 
   private final LogHelper console;
-  private final Configuration conf;
+  private Configuration conf;
 
   public CliDriver() {
     SessionState ss = SessionState.get();
     conf = (ss != null) ? ss.getConf() : new Configuration();
     Log LOG = LogFactory.getLog("CliDriver");
     console = new LogHelper(LOG);
   }
 
   public int processCmd(String cmd) {
     CliSessionState ss = (CliSessionState) SessionState.get();
-
     String cmd_trimmed = cmd.trim();
-    String[] tokens = cmd_trimmed.split("\\s+");
-    String cmd_1 = cmd_trimmed.substring(tokens[0].length()).trim();
+    String[] tokens = tokenizeCmd(cmd_trimmed);
     int ret = 0;
 
     if (cmd_trimmed.toLowerCase().equals("quit") || cmd_trimmed.toLowerCase().equals("exit")) {
 
       // if we have come this far - either the previous commands
@@ -107,10 +104,12 @@ public class CliDriver {
       // this counts as a successful run
       ss.close();
       System.exit(0);
 
     } else if (tokens[0].equalsIgnoreCase("source")) {
+      String cmd_1 = getFirstCmd(cmd_trimmed, tokens[0].length());
+
       File sourceFile = new File(cmd_1);
       if (! sourceFile.isFile()){
         console.printError("File: "+ cmd_1 + " is not a file.");
         ret = 1;
       } else {
@@ -205,95 +204,136 @@ public class CliDriver {
           err.println("[Thrift Error]: Hive server is not cleaned due to thrift exception: "
               + errMsg);
         }
       }
     } else { // local mode
-      CommandProcessor proc = CommandProcessorFactory.get(tokens[0], (HiveConf)conf);
-      int tryCount = 0;
-      boolean needRetry;
+      CommandProcessor proc = CommandProcessorFactory.get(tokens[0], (HiveConf) conf);
+      ret = processLocalCmd(cmd, proc, ss);
+    }
 
-      do {
-        try {
-          needRetry = false;
-          if (proc != null) {
-            if (proc instanceof Driver) {
-              Driver qp = (Driver) proc;
-              PrintStream out = ss.out;
-              long start = System.currentTimeMillis();
-              if (ss.getIsVerbose()) {
-                out.println(cmd);
-              }
+    return ret;
+  }
 
-              qp.setTryCount(tryCount);
-              ret = qp.run(cmd).getResponseCode();
-              if (ret != 0) {
-                qp.close();
-                return ret;
-              }
+  /**
+   * For testing purposes to inject Configuration dependency
+   * @param conf to replace default
+   */
+  void setConf(Configuration conf) {
+    this.conf = conf;
+  }
 
-              ArrayList<String> res = new ArrayList<String>();
-
-              if (HiveConf.getBoolVar(conf, HiveConf.ConfVars.HIVE_CLI_PRINT_HEADER)) {
-                // Print the column names
-                boolean first_col = true;
-                Schema sc = qp.getSchema();
-                for (FieldSchema fs : sc.getFieldSchemas()) {
-                  if (!first_col) {
-                    out.print('\t');
-                  }
-                  out.print(fs.getName());
-                  first_col = false;
-                }
-                out.println();
-              }
+  /**
+   * Extract and clean up the first command in the input.
+   */
+  private String getFirstCmd(String cmd, int length) {
+    return cmd.substring(length).trim();
+  }
+
+  private String[] tokenizeCmd(String cmd) {
+    return cmd.split("\\s+");
+  }
+
+  int processLocalCmd(String cmd, CommandProcessor proc, CliSessionState ss) {
+    int tryCount = 0;
+    boolean needRetry;
+    int ret = 0;
+
+    do {
+      try {
+        needRetry = false;
+        if (proc != null) {
+          if (proc instanceof Driver) {
+            Driver qp = (Driver) proc;
+            PrintStream out = ss.out;
+            long start = System.currentTimeMillis();
+            if (ss.getIsVerbose()) {
+              out.println(cmd);
+            }
 
-              try {
-                while (qp.getResults(res)) {
-                  for (String r : res) {
-                    out.println(r);
-                  }
-                  res.clear();
-                  if (out.checkError()) {
-                    break;
-                  }
+            qp.setTryCount(tryCount);
+            ret = qp.run(cmd).getResponseCode();
+            if (ret != 0) {
+              qp.close();
+              return ret;
+            }
+
+            ArrayList<String> res = new ArrayList<String>();
+
+            printHeader(qp, out);
+
+            try {
+              while (qp.getResults(res)) {
+                for (String r : res) {
+                  out.println(r);
+                }
+                res.clear();
+                if (out.checkError()) {
+                  break;
                 }
-              } catch (IOException e) {
-                console.printError("Failed with exception " + e.getClass().getName() + ":"
-                    + e.getMessage(), "\n"
-                    + org.apache.hadoop.util.StringUtils.stringifyException(e));
-                ret = 1;
               }
+            } catch (IOException e) {
+              console.printError("Failed with exception " + e.getClass().getName() + ":"
+                  + e.getMessage(), "\n"
+                  + org.apache.hadoop.util.StringUtils.stringifyException(e));
+              ret = 1;
+            }
 
-              int cret = qp.close();
-              if (ret == 0) {
-                ret = cret;
-              }
+            int cret = qp.close();
+            if (ret == 0) {
+              ret = cret;
+            }
 
-              long end = System.currentTimeMillis();
-              if (end > start) {
-                double timeTaken = (end - start) / 1000.0;
-                console.printInfo("Time taken: " + timeTaken + " seconds", null);
-              }
+            long end = System.currentTimeMillis();
+            if (end > start) {
+              double timeTaken = (end - start) / 1000.0;
+              console.printInfo("Time taken: " + timeTaken + " seconds", null);
+            }
 
-            } else {
-              if (ss.getIsVerbose()) {
-                ss.out.println(tokens[0] + " " + cmd_1);
-              }
-              ret = proc.run(cmd_1).getResponseCode();
+          } else {
+            String firstToken = tokenizeCmd(cmd.trim())[0];
+            String cmd_1 = getFirstCmd(cmd.trim(), firstToken.length());
+
+            if (ss.getIsVerbose()) {
+              ss.out.println(firstToken + " " + cmd_1);
             }
+            ret = proc.run(cmd_1).getResponseCode();
           }
-        } catch (CommandNeedRetryException e) {
-          console.printInfo("Retry query with a different approach...");
-          tryCount++;
-          needRetry = true;
         }
-      } while (needRetry);
-    }
+      } catch (CommandNeedRetryException e) {
+        console.printInfo("Retry query with a different approach...");
+        tryCount++;
+        needRetry = true;
+      }
+    } while (needRetry);
 
     return ret;
   }
 
+  /**
+   * If enabled and applicable to this command, print the field headers
+   * for the output.
+   *
+   * @param qp Driver that executed the command
+   * @param out Printstream which to send output to
+   */
+  private void printHeader(Driver qp, PrintStream out) {
+    List<FieldSchema> fieldSchemas = qp.getSchema().getFieldSchemas();
+    if (HiveConf.getBoolVar(conf, HiveConf.ConfVars.HIVE_CLI_PRINT_HEADER)
+          && fieldSchemas != null) {
+      // Print the column names
+      boolean first_col = true;
+      for (FieldSchema fs : fieldSchemas) {
+        if (!first_col) {
+          out.print('\t');
+        }
+        out.print(fs.getName());
+        first_col = false;
+      }
+      out.println();
+    }
+  }
+
   public int processLine(String line) {
     return processLine(line, false);
   }
 
   /**
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
