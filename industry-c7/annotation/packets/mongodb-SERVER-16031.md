# Annotation packet: SERVER-16031  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Race condition at shutdown for KVEngines

CC [~eliot]

[LOGS|http://buildlogs.mongodb.org/MCI_rhel70/builds/265407/test/slow2_WT_0/32bit.js]

{code}
2014-11-05T17:57:01.729+0000 F -        [conn3] Invalid access at address: 0x78c
2014-11-05T17:57:01.739+0000 F -        [conn3] Got signal: 11 (Segmentation fault).
 0xf6b949 0xf6b502 0xf6b82e 0x7f05cd4b2130 0x136b5b7 0x136d841 0x13787ca 0x1378977 0x1385ca6 0xd84be2 0xd8d920 0xd8b564 0xd8b649 0xafff91 0xafffb9 0x80d909 0xf1df51 0x7f05cd4aadf3 0x7f05cbf5c01d
----- BEGIN BACKTRACE -----
{"backtrace":[{"b":"400000","o":"B6B949"},{"b":"400000","o":"B6B502"},{"b":"400000","o":"B6B82E"},{"b":"7F05CD4A3000","o":"F130"},{"b":"400000","o":"F6B5B7"},{"b":"400000","o":"F6D841"},{"b":"400000","o":"F787CA"},{"b":"400000","o":"F78977"},{"b":"400000","o":"F85CA6"},{"b":"400000","o":"984BE2"},{"b":"400000","o":"98D920"},{"b":"400000","o":"98B564"},{"b":"400000","o":"98B649"},{"b":"400000","o":"6FFF91"},{"b":"400000","o":"6FFFB9"},{"b":"400000","o":"40D909"},{"b":"400000","o":"B1DF51"},{"b":"7F05CD4A3000","o":"7DF3"},{"b":"7F05CBE66000","o":"F601D"}],"processInfo":{ "mongodbVersion" : "2.7.9-pre-", "gitVersion" : "b0d74105634a3a2040743061c53b0e5b4eff919d", "uname" : { "sysname" : "Linux", "release" : "3.10.0-121.el7.x86_64", "version" : "#1 SMP Tue Apr 8 10:48:19 EDT 2014", "machine" : "x86_64" }, "somap" : [ { "elfType" : 2, "b" : "400000" }, { "b" : "7FFF0CAD4000", "elfType" : 3, "buildId" : "2E0D6061CA324F7A50926A1057278D4DDEF2A53E" }, { "b" : "7F05CD4A3000", "path" : "/lib64/libpthread.so.0", "elfType" : 3, "buildId" : "18562EE0363BC9BD7101610BD86469AA426D0C44" }, { "b" : "7F05CD237000", "path" : "/lib64/libssl.so.10", "elfType" : 3, "buildId" : "7D3BE79FBAC3789570769A87B19B237CD2EBD5F0" }, { "b" : "7F05CCE52000", "path" : "/lib64/libcrypto.so.10", "elfType" : 3, "buildId" : "A8CF24D1279557A3F2E563C21A858DCD8784B665" }, { "b" : "7F05CCC4A000", "path" : "/lib64/librt.so.1", "elfType" : 3, "buildId" : "8832E3070AB0758762836EEC8FCDDEDEF8235340" }, { "b" : "7F05CCA46000", "path" : "/lib64/libdl.so.2", "elfType" : 3, "buildId" : "B7C4BC0854BF5DE16B535353B38235CA42349C1E" }, { "b" : "7F05CC73F000", "path" : "/lib64/libstdc++.so.6", "elfType" : 3, "buildId" : "63C62D6263FF98E6DD6896CB3E716E499744A4C9" }, { "b" : "7F05CC43D000", "path" : "/lib64/libm.so.6", "elfType" : 3, "buildId" : "D70EAB176DDA46DE292FEB8208A0E8A6718BAF3B" }, { "b" : "7F05CC227000", "path" : "/lib64/libgcc_s.so.1", "elfType" : 3, "buildId" : "07120A9AC1BF3BCDD4A3EA1E0C47234A4A5C84F9" }, { "b" : "7F05CBE66000", "path" : "/lib64/libc.so.6", "elfType" : 3, "buildId" : "CFF370844D00EA5451D7ADD439646A93C64D48A5" }, { "b" : "7F05CD6BF000", "path" : "/lib64/ld-linux-x86-64.so.2", "elfType" : 3, "buildId" : "4EADCA6CB82E0A85EDB87C15B5E3980742514501" }, { "b" : "7F05CBC1C000", "path" : "/lib64/libgssapi_krb5.so.2", "elfType" : 3, "buildId" : "641A441AB91715A7E3AF8AD9AF38EE07F17866FE" }, { "b" : "7F05CB93C000", "path" : "/lib64/libkrb5.so.3", "elfType" : 3, "buildId" : "08E8BA638E79EC07F98198ED40F90FA87D5EEEB5" }, { "b" : "7F05CB738000", "path" : "/lib64/libcom_err.so.2", "elfType" : 3, "buildId" : "D2678F5F391BF2877E1BD6FAD16DBC589ED0BBF3" }, { "b" : "7F05CB503000", "path" : "/lib64/libk5crypto.so.3", "elfType" : 3, "buildId" : "8269E77C68B707158D2B1BEA356EE0FC2A1C0024" }, { "b" : "7F05CB2ED000", "path" : "/lib64/libz.so.1", "elfType" : 3, "buildId" : "8934632E74819BCC23A16BD5659F1FFBB5243D93" }, { "b" : "7F05CB0DF000", "path" : "/lib64/libkrb5support.so.0", "elfType" : 3, "buildId" : "577A21CDAA3D662B87D53AFAA12A1E7B34AD513F" }, { "b" : "7F05CAEDB000", "path" : "/lib64/libkeyutils.so.1", "elfType" : 3, "buildId" : "8CA73C16CFEB9A8B5660015B9223B09F87041CAD" }, { "b" : "7F05CACC1000", "path" : "/lib64/libresolv.so.2", "elfType" : 3, "buildId" : "519F19CF966514EAC9B25BE6FE953750E466D3C1" }, { "b" : "7F05CAA9C000", "path" : "/lib64/libselinux.so.1", "elfType" : 3, "buildId" : "5062031216B995004A297D555D834C0109F7598C" }, { "b" : "7F05CA83B000", "path" : "/lib64/libpcre.so.1", "elfType" : 3, "buildId" : "F8CF66F925DDF805E448B4131F396B40C587FE36" }, { "b" : "7F05CA616000", "path" : "/lib64/liblzma.so.5", "elfType" : 3, "buildId" : "59474E81F81B9FEA8C224678D1E157A8D6012A38" } ] }}
 mongod(_ZN5mongo15printStackTraceERSo+0x29) [0xf6b949]
 mongod(+0xB6B502) [0xf6b502]
 mongod(+0xB6B82E) [0xf6b82e]
 libpthread.so.0(+0xF130) [0x7f05cd4b2130]
 mongod(__wt_free_int+0x17) [0x136b5b7]
 mongod(__wt_remove+0x81) [0x136d841]
 mongod(__wt_schema_drop+0x2DA) [0x13787ca]
 mongod(__wt_schema_drop+0x487) [0x1378977]
 mongod(+0xF85CA6) [0x1385ca6]
 mongod(_ZN5mongo18WiredTigerKVEngine13dropAllQueuedEv+0x202) [0xd84be2]
 mongod(_ZN5mongo22WiredTigerSessionCache14releaseSessionEPNS_17WiredTigerSessionE+0x100) [0xd8d920]
 mongod(_ZN5mongo22WiredTigerRecoveryUnitD1Ev+0x44) [0xd8b564]
 mongod(_ZN5mongo22WiredTigerRecoveryUnitD0Ev+0x9) [0xd8b649]
 mongod(_ZN5mongo20OperationContextImplD1Ev+0x41) [0xafff91]
 mongod(_ZN5mongo20OperationContextImplD0Ev+0x9) [0xafffb9]
 mongod(_ZN5mongo16MyMessageHandler7processERNS_7MessageEPNS_21AbstractMessagingPortEPNS_9LastErrorE+0x5C9) [0x80d909]
 mongod(_ZN5mongo17PortMessageServer17handleIncomingMsgEPv+0x421) [0xf1df51]
 libpthread.so.0(+0x7DF3) [0x7f05cd4aadf3]
 libc.so.6(clone+0x6D) [0x7f05cbf5c01d]
-----  END BACKTRACE  -----
{code}
```

## Fix commit message(s)

`a29dc744d425`

```
(empty)
```

## Files the fix changed

Snapshot holds 9,099 non-test source files. The fix changed 10 file(s); 10 of them are non-test source files (listed below as gold).

- `src/mongo/db/storage/devnull/devnull_kv_engine.h`
- `src/mongo/db/storage/heap1/heap1_engine.h`
- `src/mongo/db/storage/kv/kv_engine.h`
- `src/mongo/db/storage/kv/kv_storage_engine.cpp`
- `src/mongo/db/storage/kv/kv_storage_engine.h`
- `src/mongo/db/storage/rocks/rocks_engine.h`
- `src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.cpp`
- `src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.h`
- `src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.cpp`
- `src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.h`

## The fix diff

### `src/mongo/db/storage/devnull/devnull_kv_engine.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/heap1/heap1_engine.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/kv/kv_engine.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/kv/kv_storage_engine.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/kv/kv_storage_engine.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/rocks/rocks_engine.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.h`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.cpp`

```diff
(no diff retrieved)
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.h`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
