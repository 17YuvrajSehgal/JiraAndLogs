# Annotation packet: ISPN-1010  (infinispan)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
ClusteredCacheLoader not detecting multiple responses are equal

Infinispan's clustered cache loader does not seem to be capable of dealing with two or more identical responses:

{code}[JBoss] org.infinispan.loaders.CacheLoaderException: Response length is always 0 or 1, received: [SuccessfulResponse{responseValue=ImmortalCacheValue{value=TopologyView(2,List(TopologyAddress(172.17.65.254,11222,Map(),perf02-7642), TopologyAddress(172.17.67.254,11222,Map(),perf04-36806)))}} , SuccessfulResponse{responseValue=ImmortalCacheValue{value=TopologyView(2,List(TopologyAddress(172.17.65.254,11222,Map(),perf02-7642), TopologyAddress(172.17.67.254,11222,Map(),perf04-36806)))}} ]
[JBoss] 	at org.infinispan.loaders.cluster.ClusterCacheLoader.load(ClusterCacheLoader.java:57){code}
```

## Fix commit message(s)

`4299a35c69c3`

```
ISPN-1010 ClusterCacheLoader now detects multiple identical responses
```

`edebbba1a1a6`

```
ISPN-1010 Optimise when only one response
```

## Files the fix changed

Snapshot holds 787 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java`

## The fix diff

### `core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java`

```diff
--- from commit 4299a35c69c3 ---
diff --git a/core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java b/core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java
index 349536d026..8c2a370a04 100644
--- a/core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java
+++ b/core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java
@@ -52,21 +52,27 @@ public class ClusterCacheLoader extends AbstractCacheLoader {
    }
 
    public InternalCacheEntry load(Object key) throws CacheLoaderException {
       if (!(isCacheReady() && isLocalCall())) return null;
       ClusteredGetCommand clusteredGetCommand = new ClusteredGetCommand(key, cache.getName());
-      Collection<Response> response = doRemoteCall(clusteredGetCommand);
-      if (response.isEmpty()) return null;
-      if (response.size() > 1)
-         throw new CacheLoaderException("Response length is always 0 or 1, received: " + response);
-      for (Response r : response) {
+      Collection<Response> responses = doRemoteCall(clusteredGetCommand);
+      if (responses.isEmpty()) return null;
+
+      // Remove duplicates before deciding if multiple responses were received
+      Set<Response> setResponses = new HashSet(responses);
+      if (setResponses.size() > 1)
+         throw new CacheLoaderException(String.format(
+               "Responses contains more than 1 element and these elements are not equal, so can't decide which one to use: %s",
+               setResponses));
+
+      for (Response r : setResponses) {
          if (r.isSuccessful() && r instanceof SuccessfulResponse) {
             InternalCacheValue value = (InternalCacheValue) ((SuccessfulResponse) r).getResponseValue();
             return value.toInternalCacheEntry(key);
          }
       }
-      String message = "Unknown response from remote cache: " + response;
+      String message = "Unknown responses from remote cache: " + responses;
       log.error(message);
       throw new CacheLoaderException(message);
    }
 
    @SuppressWarnings(value = "unchecked")
--- from commit edebbba1a1a6 ---
diff --git a/core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java b/core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java
index 8c2a370a04..b55dc9e225 100644
--- a/core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java
+++ b/core/src/main/java/org/infinispan/loaders/cluster/ClusterCacheLoader.java
@@ -55,23 +55,28 @@ public class ClusterCacheLoader extends AbstractCacheLoader {
       if (!(isCacheReady() && isLocalCall())) return null;
       ClusteredGetCommand clusteredGetCommand = new ClusteredGetCommand(key, cache.getName());
       Collection<Response> responses = doRemoteCall(clusteredGetCommand);
       if (responses.isEmpty()) return null;
 
-      // Remove duplicates before deciding if multiple responses were received
-      Set<Response> setResponses = new HashSet(responses);
-      if (setResponses.size() > 1)
-         throw new CacheLoaderException(String.format(
-               "Responses contains more than 1 element and these elements are not equal, so can't decide which one to use: %s",
-               setResponses));
-
-      for (Response r : setResponses) {
-         if (r.isSuccessful() && r instanceof SuccessfulResponse) {
-            InternalCacheValue value = (InternalCacheValue) ((SuccessfulResponse) r).getResponseValue();
-            return value.toInternalCacheEntry(key);
-         }
+      Response response;
+      if (responses.size() > 1) {
+         // Remove duplicates before deciding if multiple responses were received
+         Set<Response> setResponses = new HashSet(responses);
+         if (setResponses.size() > 1)
+            throw new CacheLoaderException(String.format(
+                  "Responses contains more than 1 element and these elements are not equal, so can't decide which one to use: %s",
+                  setResponses));
+         response = setResponses.iterator().next();
+      } else {
+         response = responses.iterator().next();
       }
+
+      if (response.isSuccessful() && response instanceof SuccessfulResponse) {
+         InternalCacheValue value = (InternalCacheValue) ((SuccessfulResponse) response).getResponseValue();
+         return value.toInternalCacheEntry(key);
+      }
+
       String message = "Unknown responses from remote cache: " + responses;
       log.error(message);
       throw new CacheLoaderException(message);
    }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
