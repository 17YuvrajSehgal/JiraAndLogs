# Annotation packet: SERVER-50097  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
inaccurate exhaustIsMasterMetrics if an isMaster command alias is used

The exhaust isMaster metrics rely on the [command name|https://github.com/mongodb/mongo/blob/f8be36eca7f5d17b0cbea557e8825046352eea19/src/mongo/db/service_entry_point_common.cpp#L1365] when [keeping track|https://github.com/mongodb/mongo/blob/f8be36eca7f5d17b0cbea557e8825046352eea19/src/mongo/transport/ismaster_metrics.cpp#L87-L94] of exhaust isMaster requests.

On mongod, we search the [command registry|https://github.com/mongodb/mongo/blob/f8be36eca7f5d17b0cbea557e8825046352eea19/src/mongo/db/service_entry_point_common.cpp#L1330-L1344] for the command name specified in the request object. This ensures that aliases like "ismaster" are properly covered in the exhaust isMaster metrics.

On mongos, however, we only look at the command name passed into the [request|https://github.com/mongodb/mongo/blob/f8be36eca7f5d17b0cbea557e8825046352eea19/src/mongo/s/commands/strategy.cpp#L1029]. This means that we will incorrectly mark inExhaustIsMaster as false if we send "ismaster" instead of "isMaster" to mongos. 

Mongos should look up the request's command name in the command registry so that any aliases to the isMaster command are correctly covered.
```

## Fix commit message(s)

`9e4b6e5c2f9e`

```
SERVER-50097 isMaster aliases should correctly populate exhaustIsMasterMetrics
```

## Files the fix changed

Snapshot holds 15,014 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/s/commands/strategy.cpp`

## The fix diff

### `src/mongo/s/commands/strategy.cpp`

```diff
diff --git a/src/mongo/s/commands/strategy.cpp b/src/mongo/s/commands/strategy.cpp
index 81eee3ef4bc..f90d6d1beb6 100644
--- a/src/mongo/s/commands/strategy.cpp
+++ b/src/mongo/s/commands/strategy.cpp
@@ -294,13 +294,14 @@ MONGO_FAIL_POINT_DEFINE(doNotRefreshShardsOnRetargettingError);
  * Executes the command for the given request, and appends the result to replyBuilder
  * and error labels, if any, to errorBuilder.
  */
 void runCommand(OperationContext* opCtx,
                 const OpMsgRequest& request,
-                const NetworkOp opType,
+                const Message& m,
                 rpc::ReplyBuilderInterface* replyBuilder,
                 BSONObjBuilder* errorBuilder) {
+    auto const opType = m.operation();
     auto const commandName = request.getCommandName();
     auto const command = CommandHelpers::findCommand(commandName);
     if (!command) {
         auto builder = replyBuilder->getBodyBuilder();
         CommandHelpers::appendCommandStatusNoThrow(
@@ -309,10 +310,18 @@ void runCommand(OperationContext* opCtx,
         globalCommandRegistry()->incrementUnknownCommands();
         appendRequiredFieldsToResponse(opCtx, &builder);
         return;
     }
 
+    opCtx->setExhaust(OpMsg::isFlagSet(m, OpMsg::kExhaustSupported));
+    const auto session = opCtx->getClient()->session();
+    if (session) {
+        if (!opCtx->isExhaust() || command->getName() != "isMaster"_sd) {
+            InExhaustIsMaster::get(session.get())->setInExhaustIsMaster(false);
+        }
+    }
+
     CommandHelpers::uassertShouldAttemptParse(opCtx, command, request);
 
     // Parse the 'maxTimeMS' command option, and use it to set a deadline for the operation on
     // the OperationContext. Be sure to do this as soon as possible so that further processing by
     // subsequent code has the deadline available. The 'maxTimeMS' option unfortunately has a
@@ -1021,28 +1030,20 @@ DbResponse Strategy::clientCommand(OperationContext* opCtx, const Message& m) {
                             "error"_attr = redact(ex));
                 throw;
             }
         }();
 
-        opCtx->setExhaust(OpMsg::isFlagSet(m, OpMsg::kExhaustSupported));
-        const auto session = opCtx->getClient()->session();
-        if (session) {
-            if (!opCtx->isExhaust() || request.getCommandName() != "isMaster"_sd) {
-                InExhaustIsMaster::get(session.get())->setInExhaustIsMaster(false);
-            }
-        }
-
         // Execute.
         std::string db = request.getDatabase().toString();
         try {
             LOGV2_DEBUG(22770,
                         3,
                         "Command begin db: {db} msg id: {headerId}",
                         "Command begin",
                         "db"_attr = db,
                         "headerId"_attr = m.header().getId());
-            runCommand(opCtx, request, m.operation(), reply.get(), &errorBuilder);
+            runCommand(opCtx, request, m, reply.get(), &errorBuilder);
             LOGV2_DEBUG(22771,
                         3,
                         "Command end db: {db} msg id: {headerId}",
                         "Command end",
                         "db"_attr = db,
@@ -1230,11 +1231,11 @@ void Strategy::writeOp(OperationContext* opCtx, DbMessage* dbm) {
                        }
                        default:
                            MONGO_UNREACHABLE;
                    }
                }(),
-               msg.operation(),
+               msg,
                &reply,
                &errorBuilder);  // built objects are ignored
 }
 
 void Strategy::explainFind(OperationContext* opCtx,
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
