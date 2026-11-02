# Annotation packet: SOLR-14247  (solr)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
IndexSizeTriggerMixedBoundsTest does a lot of sleeping

When I run tests locally, the slowest reported test is always IndexSizeTriggerMixedBoundsTest  coming in at around 2 minutes.

I took a look at the code and discovered that at least 80s of that is all sleeps!

There might need to be more synchronization and ordering added back in, but when I removed all of the sleeps the test still passed locally for me, so I'm not too sure what the point was or why we were slowing the system down so much.
```

## Fix commit message(s)

`71b869381ef0`

```
SOLR-14247 Remove unneeded sleeps (#1244)
```

## Files the fix changed

Snapshot holds 5,661 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `solr/test-framework/src/java/org/apache/solr/SolrTestCase.java`

## The fix diff

### `solr/test-framework/src/java/org/apache/solr/SolrTestCase.java`

```diff
diff --git a/solr/test-framework/src/java/org/apache/solr/SolrTestCase.java b/solr/test-framework/src/java/org/apache/solr/SolrTestCase.java
index c4c40e74b2b..4e371ed1f2b 100644
--- a/solr/test-framework/src/java/org/apache/solr/SolrTestCase.java
+++ b/solr/test-framework/src/java/org/apache/solr/SolrTestCase.java
@@ -15,19 +15,16 @@
  * limitations under the License.
  */
 
 package org.apache.solr;
 
-import java.lang.invoke.MethodHandles;
 
 import org.apache.lucene.util.LuceneTestCase;
 import org.apache.solr.util.StartupLoggingUtils;
 import org.junit.AfterClass;
 import org.junit.Before;
 import org.junit.BeforeClass;
-import org.slf4j.Logger;
-import org.slf4j.LoggerFactory;
 
 import static com.carrotsearch.randomizedtesting.RandomizedTest.systemPropertyAsBoolean;
 
 /**
  * All Solr test cases should derive from this class eventually. This is originally a result of async logging, see:
@@ -40,14 +37,11 @@ import static com.carrotsearch.randomizedtesting.RandomizedTest.systemPropertyAs
  * Other changes that should affect every Solr test case may go here if they don't require the added capabilities in
  * SolrTestCaseJ4.
  */
 
 public class SolrTestCase extends LuceneTestCase {
-
-  private static final Logger log = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());
-
-  /** 
+  /**
    * Special hook for sanity checking if any tests trigger failures when an
    * Assumption failure occures in a {@link BeforeClass} method
    * @lucene.internal
    */
   @BeforeClass
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
