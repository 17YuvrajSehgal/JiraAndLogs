# Annotation packet: SOLR-6706  (solr)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
/update/json/docs throws RuntimeException if a nested structure contains a non-leaf float field

The following JSON throws an exception:
{code}
{
        "a_string" : "abc",
        "a_num" : 2.0,
        "a" : {
                        "b" : [
                                {"id":"1", "title" : "test1"},
                                {"id":"2", "title" : "test2"}
                        ]
                }
}
{code}

{code}
curl 'http://localhost:8983/solr/collection1/update/json/docs?split=/a/b&f=id:/a/b/id&f=title_s:/a/b/title&indent=on' -H 'Content-type:application/json' -d @test2.json
{
  "responseHeader":{
    "status":500,
    "QTime":0},
  "error":{
    "msg":"unexpected token 3",
    "trace":"java.lang.RuntimeException: unexpected token 3\n\tat org.apache.solr.common.util.JsonRecordReader$Node.handleObjectStart(JsonRecordReader.java:400)\n\tat org.apache.solr.common.util.JsonRecordReader$Node.parse(JsonRecordReader.java:281)\n\tat org.apache.solr.common.util.JsonRecordReader$Node.access$200(JsonRecordReader.java:152)\n\tat org.apache.solr.common.util.JsonRecordReader.streamRecords(JsonRecordReader.java:136)\n\tat org.apache.solr.handler.loader.JsonLoader$SingleThreadedJsonLoader.handleSplitMode(JsonLoader.java:200)\n\tat org.apache.solr.handler.loader.JsonLoader$SingleThreadedJsonLoader.processUpdate(JsonLoader.java:120)\n\tat org.apache.solr.handler.loader.JsonLoader$SingleThreadedJsonLoader.load(JsonLoader.java:106)\n\tat org.apache.solr.handler.loader.JsonLoader.load(JsonLoader.java:68)\n\tat org.apache.solr.handler.UpdateRequestHandler$1.load(UpdateRequestHandler.java:99)\n\tat org.apache.solr.handler.ContentStreamHandlerBase.handleRequestBody(ContentStreamHandlerBase.java:74)\n\tat org.apache.solr.handler.RequestHandlerBase.handleRequest(RequestHandlerBase.java:135)\n\tat org.apache.solr.core.SolrCore.execute(SolrCore.java:1967)\n\tat org.apache.solr.servlet.SolrDispatchFilter.execute(SolrDispatchFilter.java:777)\n\tat org.apache.solr.servlet.SolrDispatchFilter.doFilter(SolrDispatchFilter.java:418)\n\tat org.apache.solr.servlet.SolrDispatchFilter.doFilter(SolrDispatchFilter.java:207)\n\tat org.eclipse.jetty.servlet.ServletHandler$CachedChain.doFilter(ServletHandler.java:1419)\n\tat org.eclipse.jetty.servlet.ServletHandler.doHandle(ServletHandler.java:455)\n\tat org.eclipse.jetty.server.handler.ScopedHandler.handle(ScopedHandler.java:137)\n\tat org.eclipse.jetty.security.SecurityHandler.handle(SecurityHandler.java:557)\n\tat org.eclipse.jetty.server.session.SessionHandler.doHandle(SessionHandler.java:231)\n\tat org.eclipse.jetty.server.handler.ContextHandler.doHandle(ContextHandler.java:1075)\n\tat org.eclipse.jetty.servlet.ServletHandler.doScope(ServletHandler.java:384)\n\tat org.eclipse.jetty.server.session.SessionHandler.doScope(SessionHandler.java:193)\n\tat org.eclipse.jetty.server.handler.ContextHandler.doScope(ContextHandler.java:1009)\n\tat org.eclipse.jetty.server.handler.ScopedHandler.handle(ScopedHandler.java:135)\n\tat org.eclipse.jetty.server.handler.ContextHandlerCollection.handle(ContextHandlerCollection.java:255)\n\tat org.eclipse.jetty.server.handler.HandlerCollection.handle(HandlerCollection.java:154)\n\tat org.eclipse.jetty.server.handler.HandlerWrapper.handle(HandlerWrapper.java:116)\n\tat org.eclipse.jetty.server.Server.handle(Server.java:368)\n\tat org.eclipse.jetty.server.AbstractHttpConnection.handleRequest(AbstractHttpConnection.java:489)\n\tat org.eclipse.jetty.server.BlockingHttpConnection.handleRequest(BlockingHttpConnection.java:53)\n\tat org.eclipse.jetty.server.AbstractHttpConnection.content(AbstractHttpConnection.java:953)\n\tat org.eclipse.jetty.server.AbstractHttpConnection$RequestHandler.content(AbstractHttpConnection.java:1014)\n\tat org.eclipse.jetty.http.HttpParser.parseNext(HttpParser.java:861)\n\tat org.eclipse.jetty.http.HttpParser.parseAvailable(HttpParser.java:240)\n\tat org.eclipse.jetty.server.BlockingHttpConnection.handle(BlockingHttpConnection.java:72)\n\tat org.eclipse.jetty.server.bio.SocketConnector$ConnectorEndPoint.run(SocketConnector.java:264)\n\tat org.eclipse.jetty.util.thread.QueuedThreadPool.runJob(QueuedThreadPool.java:608)\n\tat org.eclipse.jetty.util.thread.QueuedThreadPool$3.run(QueuedThreadPool.java:543)\n\tat java.lang.Thread.run(Thread.java:745)\n",
    "code":500}}
{code}

If I change a_num to an integer or remove it entirely then the document is indexed successfully.
```

## Fix commit message(s)

`d32a68961bfa`

```
SOLR-6706

git-svn-id: https://svn.apache.org/repos/asf/lucene/dev/trunk@1636900 13f79535-47bb-0310-9956-ffa450edef68
```

`d40e7fc0f9b2`

```
SOLR-6706 missed changes.txt

git-svn-id: https://svn.apache.org/repos/asf/lucene/dev/trunk@1636904 13f79535-47bb-0310-9956-ffa450edef68
```

## Files the fix changed

Snapshot holds 3,175 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `solr/solrj/src/java/org/apache/solr/common/util/JsonRecordReader.java`

## The fix diff

### `solr/solrj/src/java/org/apache/solr/common/util/JsonRecordReader.java`

```diff
--- from commit d32a68961bfa ---
diff --git a/solr/solrj/src/java/org/apache/solr/common/util/JsonRecordReader.java b/solr/solrj/src/java/org/apache/solr/common/util/JsonRecordReader.java
index 45f244ac4d1..81bf221106f 100644
--- a/solr/solrj/src/java/org/apache/solr/common/util/JsonRecordReader.java
+++ b/solr/solrj/src/java/org/apache/solr/common/util/JsonRecordReader.java
@@ -392,10 +392,11 @@ public class JsonRecordReader {
           } else {
             //this is not something we are interested in  . skip it
             event = parser.nextEvent();
             if (event == STRING ||
                 event == LONG ||
+                event == NUMBER ||
                 event == BIGNUMBER ||
                 event == BOOLEAN ||
                 event == NULL) {
               continue;
             }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
