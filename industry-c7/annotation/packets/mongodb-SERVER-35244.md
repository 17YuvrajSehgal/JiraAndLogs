# Annotation packet: SERVER-35244  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Dropping config db in 4.0.0-rc0 fails while it passes in 3.7.9 and earlier

trying to drop the config database in mongodb 4.0.0-rc0 fails with following exception:
{code:java}
com.mongodb.MongoCommandException: Command failed with error 40528: 'Direct writes against config.transactions cannot be performed using a transaction or on a session.' on server 127.0.0.1:27500. The full response is { "ok" : 0.0, "errmsg" : "Direct writes against config.transactions cannot be performed using a transaction or on a session.", "code" : 40528, "codeName" : "Location40528" }
 	at com.mongodb.connection.ProtocolHelper.getCommandFailureException(ProtocolHelper.java:164)
 	at com.mongodb.connection.InternalStreamConnection.receiveCommandMessageResponse(InternalStreamConnection.java:295)
 	at com.mongodb.connection.InternalStreamConnection.sendAndReceive(InternalStreamConnection.java:255)
 	at com.mongodb.connection.UsageTrackingInternalConnection.sendAndReceive(UsageTrackingInternalConnection.java:98)
 	at com.mongodb.connection.DefaultConnectionPool$PooledConnection.sendAndReceive(DefaultConnectionPool.java:441)
 	at com.mongodb.connection.CommandProtocolImpl.execute(CommandProtocolImpl.java:80)
 	at com.mongodb.connection.DefaultServer$DefaultServerProtocolExecutor.execute(DefaultServer.java:189)
 	at com.mongodb.connection.DefaultServerConnection.executeProtocol(DefaultServerConnection.java:264)
 	at com.mongodb.connection.DefaultServerConnection.command(DefaultServerConnection.java:126)
 	at com.mongodb.connection.DefaultServerConnection.command(DefaultServerConnection.java:118)
 	at com.mongodb.operation.CommandOperationHelper.executeWrappedCommandProtocol(CommandOperationHelper.java:226)
 	at com.mongodb.operation.CommandOperationHelper.executeWrappedCommandProtocol(CommandOperationHelper.java:217)
 	at com.mongodb.operation.CommandOperationHelper.executeWrappedCommandProtocol(CommandOperationHelper.java:154)
 	at com.mongodb.operation.CommandOperationHelper.executeWrappedCommandProtocol(CommandOperationHelper.java:147)
 	at com.mongodb.operation.DropDatabaseOperation$1.call(DropDatabaseOperation.java:89)
 	at com.mongodb.operation.DropDatabaseOperation$1.call(DropDatabaseOperation.java:86)
 	at com.mongodb.operation.OperationHelper.withConnectionSource(OperationHelper.java:462)
 	at com.mongodb.operation.OperationHelper.withConnection(OperationHelper.java:424)
 	at com.mongodb.operation.DropDatabaseOperation.execute(DropDatabaseOperation.java:86)
 	at com.mongodb.operation.DropDatabaseOperation.execute(DropDatabaseOperation.java:45)
 	at com.mongodb.Mongo$3.execute(Mongo.java:837)
 	at com.mongodb.Mongo$3.execute(Mongo.java:818)
 	at com.mongodb.DB.dropDatabase(DB.java:227)
{code}
```

## Fix commit message(s)

`d6e7f0c811ac`

```
SERVER-35244 Dropping config db in 4.0.0-rc0 fails while it passes in 3.7.9 and earlier
```

## Files the fix changed

Snapshot holds 11,372 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/session_catalog.cpp`

## The fix diff

### `src/mongo/db/session_catalog.cpp`

```diff
diff --git a/src/mongo/db/session_catalog.cpp b/src/mongo/db/session_catalog.cpp
index 62f01f567a1..614e2ed8144 100644
--- a/src/mongo/db/session_catalog.cpp
+++ b/src/mongo/db/session_catalog.cpp
@@ -156,15 +156,19 @@ ScopedSession SessionCatalog::getOrCreateSession(OperationContext* opCtx,
     return ss;
 }
 
 void SessionCatalog::invalidateSessions(OperationContext* opCtx,
                                         boost::optional<BSONObj> singleSessionDoc) {
-    uassert(40528,
-            str::stream() << "Direct writes against "
-                          << NamespaceString::kSessionTransactionsTableNamespace.ns()
-                          << " cannot be performed using a transaction or on a session.",
-            !opCtx->getLogicalSessionId());
+    auto replCoord = repl::ReplicationCoordinator::get(opCtx);
+    bool isReplSet = replCoord->getReplicationMode() == repl::ReplicationCoordinator::modeReplSet;
+    if (isReplSet) {
+        uassert(40528,
+                str::stream() << "Direct writes against "
+                              << NamespaceString::kSessionTransactionsTableNamespace.ns()
+                              << " cannot be performed using a transaction or on a session.",
+                !opCtx->getLogicalSessionId());
+    }
 
     const auto invalidateSessionFn = [&](WithLock, SessionRuntimeInfoMap::iterator it) {
         auto& sri = it->second;
         sri->txnState.invalidate();
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
