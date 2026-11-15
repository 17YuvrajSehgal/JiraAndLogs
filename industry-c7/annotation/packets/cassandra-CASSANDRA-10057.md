# Annotation packet: CASSANDRA-10057  (cassandra)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
RepairMessageVerbHandler.java:95 - Cannot start multiple repair sessions over the same sstables

I bootstrapped a DC2 by restoring the snapshots from DC1 into equivalent nodes in DC2. Everything comes up just fine, but when I tried to run a {code}repair -dcpar -j4{code} in DC2, I got this error:
{code}
[root@cassandra-i-2677cce3 ~]# nodetool repair -dcpar -j4
[2015-08-12 15:56:05,682] Nothing to repair for keyspace 'system_auth'
[2015-08-12 15:56:05,949] Starting repair command #4, repairing keyspace crawl with repair options (parallelism: dc_parallel, primary range: false, incremental: true, job threads: 4, ColumnFamilies: [], dataCenters: [], hosts: [], # of ranges: 2275)
[2015-08-12 15:59:33,050] Repair session 1b8d7810-410b-11e5-b71c-71288cf05b1d for range (-1630840392403060839,-1622173360499444177] finished (progress: 0%)
[2015-08-12 15:59:33,284] Repair session 1b92a830-410b-11e5-b71c-71288cf05b1d for range (-2766833977081486018,-2766120936176524808] failed with error Could not create snapshot at /10.20.144.15 (progress: 0%)
[2015-08-12 15:59:35,543] Repair session 1b8fe910-410b-11e5-b71c-71288cf05b1d for range (5127720400742928658,5138864412691114632] finished (progress: 0%)
[2015-08-12 15:59:36,040] Repair session 1b960390-410b-11e5-b71c-71288cf05b1d for range (749871306972906628,751065038788146229] failed with error Could not create snapshot at /10.20.144.15 (progress: 0%)
[2015-08-12 15:59:36,454] Repair session 1b9455e0-410b-11e5-b71c-71288cf05b1d for range (-8769666365699147423,-8767955202550789015] finished (progress: 0%)
[2015-08-12 15:59:38,765] Repair session 1b97b140-410b-11e5-b71c-71288cf05b1d for range (-4434580467371714601,-4433394767535421669] finished (progress: 0%)
[2015-08-12 15:59:41,520] Repair session 1b99d420-410b-11e5-b71c-71288cf05b1d for range (-1085112943862424751,-1083156277882030877] finished (progress: 0%)
[2015-08-12 15:59:43,806] Repair session 1b9da4b0-410b-11e5-b71c-71288cf05b1d for range (2125359121242932804,2126816999370470831] failed with error Could not create snapshot at /10.20.144.15 (progress: 0%)
[2015-08-12 15:59:43,874] Repair session 1b9ba8e0-410b-11e5-b71c-71288cf05b1d for range (-7469857353178912795,-7459624955099554284] finished (progress: 0%)
[2015-08-12 15:59:48,384] Repair session 1b9fa080-410b-11e5-b71c-71288cf05b1d for range (-8005238987831093686,-8005057803798566519] finished (progress: 0%)
[2015-08-12 15:59:48,392] Repair session 1ba17540-410b-11e5-b71c-71288cf05b1d for range (7291056720707652994,7292508243124389877] failed with error Could not create snapshot at /10.20.144.15 (progress: 0%)
{code}

It seems like now that all 4 threads ran into an error, the repair process just sits forever.

Looking at 10.20.144.15, I see this:
{code}
ERROR [AntiEntropyStage:2] 2015-08-12 15:59:35,965 RepairMessageVerbHandler.java:95 - Cannot start multiple repair sessions over the same sstables
ERROR [AntiEntropyStage:2] 2015-08-12 15:59:35,966 RepairMessageVerbHandler.java:153 - Got error, removing parent repair session
ERROR [AntiEntropyStage:2] 2015-08-12 15:59:35,966 CassandraDaemon.java:182 - Exception in thread Thread[AntiEntropyStage:2,5,main]
java.lang.RuntimeException: java.lang.RuntimeException: Cannot start multiple repair sessions over the same sstables
        at org.apache.cassandra.repair.RepairMessageVerbHandler.doVerb(RepairMessageVerbHandler.java:156) ~[apache-cassandra-2.2.0.jar:2.2.0]
        at org.apache.cassandra.net.MessageDeliveryTask.run(MessageDeliveryTask.java:64) ~[apache-cassandra-2.2.0.jar:2.2.0]
        at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1145) ~[na:1.7.0_85]
        at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:615) ~[na:1.7.0_85]
        at java.lang.Thread.run(Thread.java:745) ~[na:1.7.0_85]
Caused by: java.lang.RuntimeException: Cannot start multiple repair sessions over the same sstables
        at org.apache.cassandra.repair.RepairMessageVerbHandler.doVerb(RepairMessageVerbHandler.java:96) ~[apache-cassandra-2.2.0.jar:2.2.0]
        ... 4 common frames omitted
ERROR [AntiEntropyStage:3] 2015-08-12 15:59:38,722 RepairMessageVerbHandler.java:153 - Got error, removing parent repair session
ERROR [AntiEntropyStage:3] 2015-08-12 15:59:38,723 CassandraDaemon.java:182 - Exception in thread Thread[AntiEntropyStage:3,5,main]
java.lang.RuntimeException: java.lang.NullPointerException
        at org.apache.cassandra.repair.RepairMessageVerbHandler.doVerb(RepairMessageVerbHandler.java:156) ~[apache-cassandra-2.2.0.jar:2.2.0]
        at org.apache.cassandra.net.MessageDeliveryTask.run(MessageDeliveryTask.java:64) ~[apache-cassandra-2.2.0.jar:2.2.0]
        at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1145) ~[na:1.7.0_85]
        at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:615) ~[na:1.7.0_85]
        at java.lang.Thread.run(Thread.java:745) ~[na:1.7.0_85]
Caused by: java.lang.NullPointerException: null
        at org.apache.cassandra.repair.RepairMessageVerbHandler.doVerb(RepairMessageVerbHandler.java:98) ~[apache-cassandra-2.2.0.jar:2.2.0]
        ... 4 common frames omitted
...
{code}

I thought maybe the -j4 was causing the issue, but when I run it without the -j param, I get the same error but on a different node.

It seems like there are two problems:
* The error on the node: {code}RepairMessageVerbHandler.java:95 - Cannot start multiple repair sessions over the same sstables{code}
* The repair process on the initiating node just sits there forever after the threads ran into an error. It seems to me that it should exit out and report back an error to the user.
```

## Fix commit message(s)

`0a4ce4449f13`

```
Fix repair hang when snapshot failed

patch by yukim reviewed by marcuse for CASSANDRA-10057
```

## Files the fix changed

Snapshot holds 1,309 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java`

## The fix diff

### `src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java`

```diff
diff --git a/src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java b/src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java
index 796f135144..41d79aa2ef 100644
--- a/src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java
+++ b/src/java/org/apache/cassandra/repair/RepairMessageVerbHandler.java
@@ -86,11 +86,11 @@ public class RepairMessageVerbHandler implements IVerbHandler<RepairMessage>
                     MessagingService.instance().sendReply(new MessageOut(MessagingService.Verb.INTERNAL_RESPONSE), id, message.from);
                     break;
 
                 case SNAPSHOT:
                     logger.debug("Snapshotting {}", desc);
-                    ColumnFamilyStore cfs = Keyspace.open(desc.keyspace).getColumnFamilyStore(desc.columnFamily);
+                    final ColumnFamilyStore cfs = Keyspace.open(desc.keyspace).getColumnFamilyStore(desc.columnFamily);
                     final Range<Token> repairingRange = desc.range;
                     Set<SSTableReader> snapshottedSSSTables = cfs.snapshot(desc.sessionId.toString(), new Predicate<SSTableReader>()
                     {
                         public boolean apply(SSTableReader sstable)
                         {
@@ -101,12 +101,17 @@ public class RepairMessageVerbHandler implements IVerbHandler<RepairMessage>
                     }, true); //ephemeral snapshot, if repair fails, it will be cleaned next startup
 
                     Set<SSTableReader> currentlyRepairing = ActiveRepairService.instance.currentlyRepairing(cfs.metadata.cfId, desc.parentSessionId);
                     if (!Sets.intersection(currentlyRepairing, snapshottedSSSTables).isEmpty())
                     {
+                        // clear snapshot that we just created
+                        cfs.clearSnapshot(desc.sessionId.toString());
                         logger.error("Cannot start multiple repair sessions over the same sstables");
-                        throw new RuntimeException("Cannot start multiple repair sessions over the same sstables");
+                        MessageOut reply = new MessageOut(MessagingService.Verb.INTERNAL_RESPONSE)
+                                               .withParameter(MessagingService.FAILURE_RESPONSE_PARAM, MessagingService.ONE_BYTE);
+                        MessagingService.instance().sendReply(reply, id, message.from);
+                        return;
                     }
                     ActiveRepairService.instance.getParentRepairSession(desc.parentSessionId).addSSTables(cfs.metadata.cfId, snapshottedSSSTables);
                     logger.debug("Enqueuing response to snapshot request {} to {}", desc.sessionId, message.from);
                     MessagingService.instance().sendReply(new MessageOut(MessagingService.Verb.INTERNAL_RESPONSE), id, message.from);
                     break;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
