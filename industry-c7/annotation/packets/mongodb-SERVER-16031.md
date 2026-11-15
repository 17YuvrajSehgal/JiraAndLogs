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
SERVER-16031 Call cleanShutdown rather than deleting KVEngines

Resolves some race conditions on shutdown.
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
diff --git a/src/mongo/db/storage/devnull/devnull_kv_engine.h b/src/mongo/db/storage/devnull/devnull_kv_engine.h
index 1ec39bf5529..dd8075f447f 100644
--- a/src/mongo/db/storage/devnull/devnull_kv_engine.h
+++ b/src/mongo/db/storage/devnull/devnull_kv_engine.h
@@ -91,7 +91,8 @@ namespace mongo {
         virtual Status repairIdent( OperationContext* opCtx,
                                     const StringData& ident ) {
             return Status::OK();
         }
 
+        virtual void cleanShutdown(OperationContext* txn) {};
     };
 }
```

### `src/mongo/db/storage/heap1/heap1_engine.h`

```diff
diff --git a/src/mongo/db/storage/heap1/heap1_engine.h b/src/mongo/db/storage/heap1/heap1_engine.h
index 4e4af4df540..2d3b782642e 100644
--- a/src/mongo/db/storage/heap1/heap1_engine.h
+++ b/src/mongo/db/storage/heap1/heap1_engine.h
@@ -79,10 +79,12 @@ namespace mongo {
         virtual Status repairIdent( OperationContext* opCtx,
                                     const StringData& ident ) {
             return Status::OK();
         }
 
+        virtual void cleanShutdown(OperationContext* txn) {};
+
     private:
         typedef StringMap<boost::shared_ptr<void> > DataMap;
 
         mutable boost::mutex _mutex;
         DataMap _dataMap; // All actual data is owned in here
```

### `src/mongo/db/storage/kv/kv_engine.h`

```diff
diff --git a/src/mongo/db/storage/kv/kv_engine.h b/src/mongo/db/storage/kv/kv_engine.h
index 7c29aafdc1c..81c33e975eb 100644
--- a/src/mongo/db/storage/kv/kv_engine.h
+++ b/src/mongo/db/storage/kv/kv_engine.h
@@ -43,12 +43,10 @@ namespace mongo {
     class SortedDataInterface;
 
     class KVEngine {
     public:
 
-        virtual ~KVEngine() {}
-
         virtual RecoveryUnit* newRecoveryUnit() = 0;
 
         // ---------
 
         /**
@@ -110,8 +108,23 @@ namespace mongo {
                                    const StringData& ident,
                                    const RecordStore* originalRecordStore ) const {
             return Status::OK();
         }
 
+        /**
+         * This method will be called before there is a clean shutdown.  Storage engines should
+         * override this method if they have clean-up to do that is different from unclean shutdown.
+         * MongoDB will not call into the storage subsystem after calling this function.
+         *
+         * There is intentionally no uncleanShutdown().
+         */
+        virtual void cleanShutdown(OperationContext* txn) = 0;
+
+        /**
+         * The destructor will never be called from mongod, but may be called from tests.
+         * Engines may assume that this will only be called in the case of clean shutdown, even if
+         * cleanShutdown() hasn't been called.
+         */
+        virtual ~KVEngine() {}
     };
 
 }
```

### `src/mongo/db/storage/kv/kv_storage_engine.cpp`

```diff
diff --git a/src/mongo/db/storage/kv/kv_storage_engine.cpp b/src/mongo/db/storage/kv/kv_storage_engine.cpp
index d35e8be2c99..b8d3c16006f 100644
--- a/src/mongo/db/storage/kv/kv_storage_engine.cpp
+++ b/src/mongo/db/storage/kv/kv_storage_engine.cpp
@@ -79,11 +79,12 @@ namespace mongo {
         _dbs.clear();
 
         _catalog.reset( NULL );
         _catalogRecordStore.reset( NULL );
 
-        _engine.reset( NULL );
+        _engine->cleanShutdown(txn);
+        // intentionally not deleting _engine
     }
 
     KVStorageEngine::~KVStorageEngine() {
     }
```

### `src/mongo/db/storage/kv/kv_storage_engine.h`

```diff
diff --git a/src/mongo/db/storage/kv/kv_storage_engine.h b/src/mongo/db/storage/kv/kv_storage_engine.h
index 01e7218a5d1..916f77d4f94 100644
--- a/src/mongo/db/storage/kv/kv_storage_engine.h
+++ b/src/mongo/db/storage/kv/kv_storage_engine.h
@@ -89,11 +89,13 @@ namespace mongo {
         const KVCatalog* getCatalog() const { return _catalog.get(); }
 
     private:
         class RemoveDBChange;
 
+        // This must be the first member so it is destroyed last.
         boost::scoped_ptr<KVEngine> _engine;
+
         bool _initialized;
         const bool _supportsDocLocking;
 
         boost::scoped_ptr<RecordStore> _catalogRecordStore;
         boost::scoped_ptr<KVCatalog> _catalog;
```

### `src/mongo/db/storage/rocks/rocks_engine.h`

```diff
diff --git a/src/mongo/db/storage/rocks/rocks_engine.h b/src/mongo/db/storage/rocks/rocks_engine.h
index b6a3d5184c4..79d60580f6c 100644
--- a/src/mongo/db/storage/rocks/rocks_engine.h
+++ b/src/mongo/db/storage/rocks/rocks_engine.h
@@ -107,10 +107,12 @@ namespace mongo {
         virtual Status repairIdent(OperationContext* opCtx,
                                     const StringData& ident) {
             return Status::OK();
         }
 
+        virtual void cleanShutdown(OperationContext* txn) {}
+
         // rocks specific api
 
         rocksdb::DB* getDB() { return _db.get(); }
         const rocksdb::DB* getDB() const { return _db.get(); }
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.cpp`

```diff
diff --git a/src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.cpp b/src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.cpp
index f982103100c..52288e2c066 100644
--- a/src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.cpp
+++ b/src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.cpp
@@ -139,21 +139,31 @@ namespace mongo {
         }
     }
 
 
     WiredTigerKVEngine::~WiredTigerKVEngine() {
-        log() << "WiredTigerKVEngine shutting down";
-        syncSizeInfo();
+        if (_conn) {
+            cleanShutdown(NULL); // our impl doesn't use the OperationContext
+        }
+
         _sizeStorer.reset( NULL );
 
         _sessionCache.reset( NULL );
 
-        if ( _conn ) {
+    }
+
+    void WiredTigerKVEngine::cleanShutdown(OperationContext* txn) {
+        log() << "WiredTigerKVEngine shutting down";
+        syncSizeInfo();
+        if (_conn) {
+            // this must be the last thing we do before _conn->close();
+            _sessionCache->shuttingDown();
+
+            // TODO consider passing "leak_memory=true" to close() when not running a leak checker.
             invariantWTOK( _conn->close(_conn, NULL) );
             _conn = NULL;
         }
-
     }
 
     Status WiredTigerKVEngine::okToRename( OperationContext* opCtx,
                                            const StringData& fromNS,
                                            const StringData& toNS,
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.h`

```diff
diff --git a/src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.h b/src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.h
index b635c121e1f..4e49bf6c551 100644
--- a/src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.h
+++ b/src/mongo/db/storage/wiredtiger/wiredtiger_kv_engine.h
@@ -100,10 +100,12 @@ namespace mongo {
                                       const StringData& ident );
 
         virtual Status repairIdent( OperationContext* opCtx,
                                     const StringData& ident );
 
+        virtual void cleanShutdown(OperationContext* txn);
+
         // wiredtiger specific
 
         WT_CONNECTION* getConnection() { return _conn; }
         void dropAllQueued();
         bool haveDropsQueued() const;
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.cpp`

```diff
diff --git a/src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.cpp b/src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.cpp
index a2e861047da..9f65a49b544 100644
--- a/src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.cpp
+++ b/src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.cpp
@@ -110,23 +110,31 @@ namespace mongo {
     }
 
     // -----------------------
 
     WiredTigerSessionCache::WiredTigerSessionCache( WiredTigerKVEngine* engine )
-        : _engine( engine ), _conn( engine->getConnection() ) {
+        : _engine( engine ), _conn( engine->getConnection() ), _shuttingDown(false) {
     }
 
     WiredTigerSessionCache::WiredTigerSessionCache( WT_CONNECTION* conn )
-        : _engine( NULL ), _conn( conn ) {
+        : _engine( NULL ), _conn( conn ), _shuttingDown(false) {
     }
 
     WiredTigerSessionCache::~WiredTigerSessionCache() {
         _closeAll();
     }
 
+    void WiredTigerSessionCache::shuttingDown() {
+        boost::mutex::scoped_lock lk( _sessionLock );
+        _shuttingDown = true;
+        _closeAll();
+    }
+
     void WiredTigerSessionCache::closeAll() {
         boost::mutex::scoped_lock lk( _sessionLock );
+        if (_shuttingDown)
+            return; // leak sessions
         _closeAll();
     }
 
     void WiredTigerSessionCache::_closeAll() {
         for ( size_t i = 0; i < _sessionPool.size(); i++ ) {
@@ -136,10 +144,12 @@ namespace mongo {
     }
 
     WiredTigerSession* WiredTigerSessionCache::getSession() {
         {
             boost::mutex::scoped_lock lk( _sessionLock );
+            invariant(!_shuttingDown); // shouldn't get here after this is set.
+
             if ( !_sessionPool.empty() ) {
                 WiredTigerSession* s = _sessionPool.back();
                 _sessionPool.pop_back();
                 {
                     WT_SESSION* ss = s->getSession();
@@ -152,10 +162,14 @@ namespace mongo {
         }
         return new WiredTigerSession( _conn, _engine ? _engine->currentEpoch() : -1 );
     }
 
     void WiredTigerSessionCache::releaseSession( WiredTigerSession* session ) {
+        boost::mutex::scoped_lock lk( _sessionLock );
+        if (_shuttingDown)
+            return; // leak session to avoid race condition.
+
         invariant( session );
         invariant( session->cursorsOut() == 0 );
 
         {
             WT_SESSION* ss = session->getSession();
@@ -168,11 +182,10 @@ namespace mongo {
             delete session;
             _engine->dropAllQueued();
             return;
         }
 
-        boost::mutex::scoped_lock lk( _sessionLock );
         _sessionPool.push_back( session );
     }
 
     bool WiredTigerSessionCache::_shouldBeClosed( WiredTigerSession* session ) const {
         if ( !_engine )
```

### `src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.h`

```diff
diff --git a/src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.h b/src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.h
index 9d49311a742..898e14acd91 100644
--- a/src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.h
+++ b/src/mongo/db/storage/wiredtiger/wiredtiger_session_cache.h
@@ -90,19 +90,22 @@ namespace mongo {
         WiredTigerSession* getSession();
         void releaseSession( WiredTigerSession* session );
 
         void closeAll();
 
+        void shuttingDown();
+
     private:
 
         bool _shouldBeClosed( WiredTigerSession* session ) const;
 
         void _closeAll(); // does not lock
 
         WiredTigerKVEngine* _engine; // not owned, might be NULL
         WT_CONNECTION* _conn; // not owned
         typedef std::vector<WiredTigerSession*> SessionPool;
         SessionPool _sessionPool; // owned
+        bool _shuttingDown;
         mutable boost::mutex _sessionLock;
     };
 
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
