# Annotation packet: SERVER-14268  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Potential information leak

{panel:title=Issue Status as of Aug 08, 2014|borderColor=#ccc|titleBGColor=#6CB33F|bgColor=#EEEEEE}

*ISSUE SUMMARY*
Using a specially crafted message, a remote user could obtain a limited amount of information from the server heap memory.

*USER IMPACT*
Potentially sensitive information could be disclosed from the server.

*WORKAROUNDS*
Implement *[MongoDB Security Best Practices|http://docs.mongodb.org/manual/core/security-network/]* and ensure access to the database server is restricted.

*AFFECTED VERSIONS*
MongoDB production releases up to 2.6.3 are affected by this issue.

*FIX VERSION*
The fix is included in the 2.6.4 production release.

*RESOLUTION DETAILS*
The response sent by the server returns only validated data.

{panel}
```

## Fix commit message(s)

`dac9ac4a4634`

```
SERVER-14268: Improve server message parsing
```

## Files the fix changed

Snapshot holds 7,705 non-test source files. The fix changed 12 file(s); 9 of them are non-test source files (listed below as gold).

- `src/mongo/db/catalog/collection_cursor_cache.cpp`
- `src/mongo/db/catalog/collection_cursor_cache.h`
- `src/mongo/db/dbmessage.cpp`
- `src/mongo/db/dbmessage.h`
- `src/mongo/db/instance.cpp`
- `src/mongo/s/cursors.cpp`
- `src/mongo/s/request.cpp`
- `src/mongo/tools/sniffer.cpp`
- `src/mongo/util/net/message.h`

## The fix diff

### `src/mongo/db/catalog/collection_cursor_cache.cpp`

```diff
diff --git a/src/mongo/db/catalog/collection_cursor_cache.cpp b/src/mongo/db/catalog/collection_cursor_cache.cpp
index d358e7a4a52..2822117c9c7 100644
--- a/src/mongo/db/catalog/collection_cursor_cache.cpp
+++ b/src/mongo/db/catalog/collection_cursor_cache.cpp
@@ -234,15 +234,17 @@ namespace mongo {
         return totalTimedOut;
     }
 
     // ---
 
-    std::size_t CollectionCursorCache::timeoutCursorsGlobal(OperationContext* txn, int millisSinceLastCall) {;
+    std::size_t CollectionCursorCache::timeoutCursorsGlobal(OperationContext* txn, 
+        int millisSinceLastCall) {;
     return _globalCursorIdCache.timeoutCursors(txn, millisSinceLastCall);
     }
 
-    int CollectionCursorCache::eraseCursorGlobalIfAuthorized(OperationContext* txn, int n, long long* ids) {
+    int CollectionCursorCache::eraseCursorGlobalIfAuthorized(OperationContext* txn, int n, 
+        const long long* ids) {
         int numDeleted = 0;
         for ( int i = 0; i < n; i++ ) {
             if ( eraseCursorGlobalIfAuthorized(txn, ids[i] ) )
                 numDeleted++;
             if ( inShutdown() )
@@ -375,11 +377,12 @@ namespace mongo {
             ClientCursor* cc = i->second;
             if ( cc->shouldTimeout( millisSinceLastCall ) )
                 toDelete.push_back( cc );
         }
 
-        for ( vector<ClientCursor*>::const_iterator i = toDelete.begin(); i != toDelete.end(); ++i ) {
+        for ( vector<ClientCursor*>::const_iterator i = toDelete.begin();
+                i != toDelete.end(); ++i ) {
             ClientCursor* cc = *i;
             _deregisterCursor_inlock( cc );
             cc->kill();
             delete cc;
         }
```

### `src/mongo/db/catalog/collection_cursor_cache.h`

```diff
diff --git a/src/mongo/db/catalog/collection_cursor_cache.h b/src/mongo/db/catalog/collection_cursor_cache.h
index 524f1e12e11..2015b7049d3 100644
--- a/src/mongo/db/catalog/collection_cursor_cache.h
+++ b/src/mongo/db/catalog/collection_cursor_cache.h
@@ -108,11 +108,12 @@ namespace mongo {
 
         void unpin( ClientCursor* cursor );
 
         // ----------------------
 
-        static int eraseCursorGlobalIfAuthorized(OperationContext* txn, int n, long long* ids);
+        static int eraseCursorGlobalIfAuthorized(OperationContext* txn, int n, 
+            const long long* ids);
         static bool eraseCursorGlobalIfAuthorized(OperationContext* txn, CursorId id);
 
         static bool eraseCursorGlobal(OperationContext* txn, CursorId id);
 
         /**
```

### `src/mongo/db/dbmessage.cpp`

```diff
diff --git a/src/mongo/db/dbmessage.cpp b/src/mongo/db/dbmessage.cpp
index 4e951cc5e78..a3b06058547 100644
--- a/src/mongo/db/dbmessage.cpp
+++ b/src/mongo/db/dbmessage.cpp
@@ -63,10 +63,111 @@ namespace mongo {
 
         }
         return ss.str();
     }
 
+    DbMessage::DbMessage(const Message& msg) : _msg(msg), _nsStart(NULL), _mark(NULL), _nsLen(0) {
+        // for received messages, Message has only one buffer
+        _theEnd = _msg.singleData()->_data + _msg.singleData()->dataLen();
+        _nextjsobj = _msg.singleData()->_data;
+
+        _reserved = readAndAdvance<int>();
+
+        // Read packet for NS
+        if (messageShouldHaveNs()) {
+
+            // Limit = buffer size of message -
+            //        (first int4 in message which is either flags or a zero constant)
+            size_t limit = _msg.singleData()->dataLen() - sizeof(int);
+
+            _nsStart = _nextjsobj;
+            _nsLen = strnlen(_nsStart, limit);
+
+            // Validate there is room for a null byte in the buffer
+            // Strings can be zero length
+            uassert(18633, "Failed to parse ns string", _nsLen <= (limit - 1));
+
+            _nextjsobj += _nsLen + 1; // skip namespace + null
+        }
+    }
+
+    const char * DbMessage::getns() const {
+        verify(messageShouldHaveNs());
+        return _nsStart;
+    }
+
+    int DbMessage::getQueryNToReturn() const {
+        verify(messageShouldHaveNs());
+        const char* p = _nsStart + _nsLen + 1;
+        checkRead<int>(p, 2);
+
+        return ((reinterpret_cast<const int*>(p)))[1];
+    }
+
+    int DbMessage::pullInt() {
+        return readAndAdvance<int>();
+    }
+
+    long long DbMessage::pullInt64() {
+        return readAndAdvance<long long>();
+    }
+
+    const long long* DbMessage::getArray(size_t count) const {
+        checkRead<long long>(_nextjsobj, count);
+        return reinterpret_cast<const long long*>(_nextjsobj);
+    }
+
+    BSONObj DbMessage::nextJsObj() {
+        massert(10304,
+            "Client Error: Remaining data too small for BSON object",
+            _nextjsobj != NULL && _theEnd - _nextjsobj >= 5);
+
+        if (serverGlobalParams.objcheck) {
+            Status status = validateBSON(_nextjsobj, _theEnd - _nextjsobj);
+            massert(10307,
+                str::stream() << "Client Error: bad object in message: " << status.reason(),
+                status.isOK());
+        }
+
+        BSONObj js(_nextjsobj);
+        verify(js.objsize() >= 5);
+        verify(js.objsize() <= (_theEnd - _nextjsobj));
+
+        _nextjsobj += js.objsize();
+        if (_nextjsobj >= _theEnd)
+            _nextjsobj = NULL;
+        return js;
+    }
+
+    void DbMessage::markReset(const char * toMark = NULL) {
+        if (toMark == NULL) {
+            toMark = _mark;
+        }
+
+        verify(toMark);
+        _nextjsobj = toMark;
+    }
+
+    template<typename T>
+    void DbMessage::checkRead(const char* start, size_t count) const {
+        if ((_theEnd - start) < static_cast<int>(sizeof(T) * count)) {
+            uassert(18634, "Not enough data to read", false);
+        }
+    }
+
+    template<typename T>
+    T DbMessage::read() const {
+        checkRead<T>(_nextjsobj, 1);
+
+        return *(reinterpret_cast<const T*>(_nextjsobj));
+    }
+
+    template<typename T> T DbMessage::readAndAdvance() {
+        T t = read<T>();
+        _nextjsobj += sizeof(T);
+        return t;
+    }
 
     void replyToQuery(int queryResultFlags,
                       AbstractMessagingPort* p, Message& requestMsg,
                       void *data, int size,
                       int nReturned, int startingFrom,
```

### `src/mongo/db/dbmessage.h`

```diff
diff --git a/src/mongo/db/dbmessage.h b/src/mongo/db/dbmessage.h
index 621624dd9be..5131e2d30a2 100644
--- a/src/mongo/db/dbmessage.h
+++ b/src/mongo/db/dbmessage.h
@@ -120,139 +120,78 @@ namespace mongo {
        the various messages transmitted over the connection.
 
        See http://dochub.mongodb.org/core/mongowireprotocol
     */
     class DbMessage {
+    // Assume sizeof(int) == 4 bytes
+    BOOST_STATIC_ASSERT(sizeof(int) == 4);
+
     public:
-        DbMessage(const Message& _m) : m(_m) , mark(0) {
-            // for received messages, Message has only one buffer
-            theEnd = _m.singleData()->_data + _m.header()->dataLen();
-            char *r = _m.singleData()->_data;
-            reserved = (int *) r;
-            data = r + 4;
-            nextjsobj = data;
+        // Note: DbMessage constructor reads the first 4 bytes and stores it in reserved
+        DbMessage(const Message& msg);
+
+        // Indicates whether this message is expected to have a ns
+        // or in the case of dbMsg, a string in the same place as ns
+        bool messageShouldHaveNs() const {
+            return (_msg.operation() >= dbMsg) & (_msg.operation() <= dbDelete);
         }
 
-        /** the 32 bit field before the ns 
+        /** the 32 bit field before the ns
          * track all bit usage here as its cross op
          * 0: InsertOption_ContinueOnError
          * 1: fromWriteback
          */
-        int& reservedField() { return *reserved; }
-
-        const char * getns() const {
-            return data;
-        }
+        int reservedField() const { return _reserved; }
 
-        const char * afterNS() const {
-            return data + strlen( data ) + 1;
-        }
-
-        int getInt( int num ) const {
-            const int * foo = (const int*)afterNS();
-            return foo[num];
-        }
+        const char * getns() const;
+        int getQueryNToReturn() const;
 
-        int getQueryNToReturn() const {
-            return getInt( 1 );
-        }
+        int pullInt();
+        long long pullInt64();
+        const long long* getArray(size_t count) const;
 
-        /**
-         * get an int64 at specified offsetBytes after ns
-         */
-        long long getInt64( int offsetBytes ) const {
-            const char * x = afterNS();
-            x += offsetBytes;
-            const long long * ll = (const long long*)x;
-            return ll[0];
+        /* for insert and update msgs */
+        bool moreJSObjs() const {
+            return _nextjsobj != 0;
         }
 
-        void resetPull() { nextjsobj = data; }
-        int pullInt() const { return pullInt(); }
-        int& pullInt() {
-            if ( nextjsobj == data )
-                nextjsobj += strlen(data) + 1; // skip namespace
-            int& i = *((int *)nextjsobj);
-            nextjsobj += 4;
-            return i;
-        }
-        long long pullInt64() const {
-            return pullInt64();
-        }
-        long long &pullInt64() {
-            if ( nextjsobj == data )
-                nextjsobj += strlen(data) + 1; // skip namespace
-            long long &i = *((long long *)nextjsobj);
-            nextjsobj += 8;
-            return i;
-        }
+        BSONObj nextJsObj();
 
-        OID* getOID() const {
-            return (OID *) (data + strlen(data) + 1); // skip namespace
-        }
+        const Message& msg() const { return _msg; }
 
-        void getQueryStuff(const char *&query, int& ntoreturn) {
-            int *i = (int *) (data + strlen(data) + 1);
-            ntoreturn = *i;
-            i++;
-            query = (const char *) i;
+        const char * markGet() const {
+            return _nextjsobj;
         }
 
-        /* for insert and update msgs */
-        bool moreJSObjs() const {
-            return nextjsobj != 0;
+        void markSet() {
+            _mark = _nextjsobj;
         }
-        BSONObj nextJsObj() {
-            if ( nextjsobj == data ) {
-                nextjsobj += strlen(data) + 1; // skip namespace
-                massert( 13066 ,  "Message contains no documents", theEnd > nextjsobj );
-            }
-            massert( 10304,
-                     "Client Error: Remaining data too small for BSON object",
-                     theEnd - nextjsobj >= 5 );
-
-            if (serverGlobalParams.objcheck) {
-                Status status = validateBSON( nextjsobj, theEnd - nextjsobj );
-                massert( 10307,
-                         str::stream() << "Client Error: bad object in message: " << status.reason(),
-                         status.isOK() );
-            }
 
-            BSONObj js(nextjsobj);
-            verify( js.objsize() >= 5 );
-            verify( js.objsize() < ( theEnd - data ) );
+        void markReset(const char * toMark);
 
-            nextjsobj += js.objsize();
-            if ( nextjsobj >= theEnd )
-                nextjsobj = 0;
-            return js;
-        }
+    private:
+        // Check if we have enough data to read
+        template<typename T>
+        void checkRead(const char* start, size_t count = 0) const;
 
-        const Message& msg() const { return m; }
+        // Read some type without advancing our position
+        template<typename T>
+        T read() const;
 
-        const char * markGet() {
-            return nextjsobj;
-        }
+        // Read some type, and advance our position
+        template<typename T> T readAndAdvance();
 
-        void markSet() {
-            mark = nextjsobj;
-        }
+        const Message& _msg;
+        int _reserved; // flags or zero depending on packet, starts the packet
 
-        void markReset( const char * toMark = 0) {
-            if( toMark == 0 ) toMark = mark;
-            verify( toMark );
-            nextjsobj = toMark;
-        }
+        const char* _nsStart; // start of namespace string, +4 from message start
+        const char* _nextjsobj; // current position reading packet
+        const char* _theEnd; // end of packet
 
-    private:
-        const Message& m;
-        int* reserved;
-        const char *data;
-        const char *nextjsobj;
-        const char *theEnd;
+        const char* _mark;
 
-        const char * mark;
+        unsigned int _nsLen;
     };
 
 
     /* a request to run a query, received from the database */
     class QueryMessage {
```

### `src/mongo/db/instance.cpp`

```diff
diff --git a/src/mongo/db/instance.cpp b/src/mongo/db/instance.cpp
index 7534a1a8f82..695f081880f 100644
--- a/src/mongo/db/instance.cpp
+++ b/src/mongo/db/instance.cpp
@@ -328,22 +328,25 @@ namespace mongo {
                            const HostAndPort& remote ) {
 
         // before we lock...
         int op = m.operation();
         bool isCommand = false;
-        const char *ns = m.singleData()->_data + 4;
+
+        DbMessage dbmsg(m);
 
         Client& c = cc();
         if (!c.isGod()) {
             c.getAuthorizationSession()->startRequest(txn);
 
             // We should not be holding any locks at this point
             invariant(!txn->lockState()->isLocked());
         }
 
         if ( op == dbQuery ) {
-            if( strstr(ns, ".$cmd") ) {
+            const char *ns = dbmsg.getns();
+
+            if (strstr(ns, ".$cmd")) {
                 isCommand = true;
                 opwrite(m);
                 if( strstr(ns, ".$cmd.sys.") ) {
                     if( strstr(ns, "$cmd.sys.inprog") ) {
                         inProgCmd(txn, m, dbresponse);
@@ -424,11 +427,12 @@ namespace mongo {
             if ( ! receivedGetMore(txn, dbresponse, m, currentOp) )
                 shouldLog = true;
         }
         else if ( op == dbMsg ) {
             // deprecated - replaced by commands
-            char *p = m.singleData()->_data;
+            const char *p = dbmsg.getns();
+
             int len = strlen(p);
             if ( len > 400 )
                 log() << curTimeMillis64() % 10000 <<
                       " long msg received, len:" << len << endl;
 
@@ -441,39 +445,44 @@ namespace mongo {
             dbresponse.response = resp;
             dbresponse.responseTo = m.header()->id;
         }
         else {
             try {
-                const NamespaceString nsString( ns );
-
                 // The following operations all require authorization.
                 // dbInsert, dbUpdate and dbDelete can be easily pre-authorized,
                 // here, but dbKillCursors cannot.
                 if ( op == dbKillCursors ) {
                     currentOp.ensureStarted();
                     logThreshold = 10;
                     receivedKillCursors(txn, m);
                 }
-                else if ( !nsString.isValid() ) {
-                    // Only killCursors doesn't care about namespaces
-                    uassert( 16257, str::stream() << "Invalid ns [" << ns << "]", false );
-                }
-                else if ( op == dbInsert ) {
-                    receivedInsert(txn, m, currentOp);
-                }
-                else if ( op == dbUpdate ) {
-                    receivedUpdate(txn, m, currentOp);
-                }
-                else if ( op == dbDelete ) {
-                    receivedDelete(txn, m, currentOp);
-                }
-                else {
+                else if (op != dbInsert && op != dbUpdate && op != dbDelete) {
                     mongo::log() << "    operation isn't supported: " << op << endl;
                     currentOp.done();
                     shouldLog = true;
                 }
-            }
+                else {
+                    const char* ns = dbmsg.getns();
+                    const NamespaceString nsString(ns);
+
+                    if (!nsString.isValid()) {
+                        uassert(16257, str::stream() << "Invalid ns [" << ns << "]", false);
+                    }
+                    else if (op == dbInsert) {
+                        receivedInsert(txn, m, currentOp);
+                    }
+                    else if (op == dbUpdate) {
+                        receivedUpdate(txn, m, currentOp);
+                    }
+                    else if (op == dbDelete) {
+                        receivedDelete(txn, m, currentOp);
+                    }
+                    else {
+                        invariant(false);
+                    }
+                }
+             }
             catch (const UserException& ue) {
                 setLastError(ue.getCode(), ue.getInfo().msg.c_str());
                 LOG(3) << " Caught Assertion in " << opToString(op) << ", continuing "
                        << ue.toString() << endl;
                 debug.exceptionInfo = ue.getInfo();
@@ -512,24 +521,25 @@ namespace mongo {
         debug.recordStats();
         debug.reset();
     } /* assembleResponse() */
 
     void receivedKillCursors(OperationContext* txn, Message& m) {
-        int *x = (int *) m.singleData()->_data;
-        x++; // reserved
-        int n = *x++;
+        DbMessage dbmessage(m);
+        int n = dbmessage.pullInt();
 
         uassert( 13659 , "sent 0 cursors to kill" , n != 0 );
         massert( 13658 , str::stream() << "bad kill cursors size: " << m.dataSize() , m.dataSize() == 8 + ( 8 * n ) );
         uassert( 13004 , str::stream() << "sent negative cursors to kill: " << n  , n >= 1 );
 
         if ( n > 2000 ) {
             ( n < 30000 ? warning() : error() ) << "receivedKillCursors, n=" << n << endl;
             verify( n < 30000 );
         }
 
-        int found = CollectionCursorCache::eraseCursorGlobalIfAuthorized(txn, n, (long long *) x);
+        const long long* cursorArray = dbmessage.getArray(n);
+
+        int found = CollectionCursorCache::eraseCursorGlobalIfAuthorized(txn, n, cursorArray);
 
         if ( logger::globalLogDomain()->shouldLog(logger::LogSeverity::Debug(1)) || found != n ) {
             LOG( found == n ? 1 : 0 ) << "killcursors: found " << found << " of " << n << endl;
         }
```

### `src/mongo/s/cursors.cpp`

```diff
diff --git a/src/mongo/s/cursors.cpp b/src/mongo/s/cursors.cpp
index b33f3ad6fc2..6f2b588e3fd 100644
--- a/src/mongo/s/cursors.cpp
+++ b/src/mongo/s/cursors.cpp
@@ -331,23 +331,24 @@ namespace mongo {
             return x;
         }
     }
 
     void CursorCache::gotKillCursors(Message& m ) {
-        int *x = (int *) m.singleData()->_data;
-        x++; // reserved
-        int n = *x++;
+        DbMessage dbmessage(m);
+        int n = dbmessage.pullInt();
 
         if ( n > 2000 ) {
             ( n < 30000 ? warning() : error() ) << "receivedKillCursors, n=" << n << endl;
         }
 
-
         uassert( 13286 , "sent 0 cursors to kill" , n >= 1 );
         uassert( 13287 , "too many cursors to kill" , n < 30000 );
+        massert( 18632 , str::stream() << "bad kill cursors size: " << m.dataSize(), 
+                    m.dataSize() == 8 + ( 8 * n ) );
+
 
-        long long * cursors = (long long *)x;
+        const long long* cursors = dbmessage.getArray(n);
         ClientBasic* client = ClientBasic::getCurrent();
         AuthorizationSession* authSession = client->getAuthorizationSession();
         for ( int i=0; i<n; i++ ) {
             long long id = cursors[i];
             LOG(_myLogLevel) << "CursorCache::gotKillCursors id: " << id << endl;
```

### `src/mongo/s/request.cpp`

```diff
diff --git a/src/mongo/s/request.cpp b/src/mongo/s/request.cpp
index 984bfdfabe9..f3d09e191f9 100644
--- a/src/mongo/s/request.cpp
+++ b/src/mongo/s/request.cpp
@@ -51,11 +51,10 @@ namespace mongo {
     MONGO_LOG_DEFAULT_COMPONENT_FILE(::mongo::logger::LogComponent::kSharding);
 
     Request::Request( Message& m, AbstractMessagingPort* p ) :
         _m(m) , _d( m ) , _p(p) , _didInit(false) {
 
-        verify( _d.getns() );
         _id = _m.header()->id;
 
         _txn.reset(new OperationContextNoop());
 
         _clientInfo = ClientInfo::get();
@@ -75,20 +74,20 @@ namespace mongo {
         _clientInfo->getAuthorizationSession()->startRequest(_txn.get());
     }
 
     // Deprecated, will move to the strategy itself
     void Request::reset() {
-        if ( _m.operation() == dbKillCursors ) {
+        _m.header()->id = _id;
+        _clientInfo->clearRequestInfo();
+
+        if ( !_d.messageShouldHaveNs()) {
             return;
         }
 
         uassert( 13644 , "can't use 'local' database through mongos" , ! str::startsWith( getns() , "local." ) );
 
         grid.getDBConfig( getns() );
-
-        _m.header()->id = _id;
-        _clientInfo->clearRequestInfo();
     }
 
     void Request::process( int attempt ) {
         init();
         int op = _m.operation();
```

### `src/mongo/tools/sniffer.cpp`

```diff
diff --git a/src/mongo/tools/sniffer.cpp b/src/mongo/tools/sniffer.cpp
index 75fa6f5eee1..9e39a3b1d15 100644
--- a/src/mongo/tools/sniffer.cpp
+++ b/src/mongo/tools/sniffer.cpp
@@ -336,13 +336,11 @@ void processMessage( Connection& c , Message& m ) {
             BSONObj q = d.nextJsObj( "delete" );
             out() << "\tdelete flags: " << flags << " q: " << q << endl;
             break;
         }
         case mongo::dbKillCursors: {
-            int *x = (int *) m.singleData()->_data;
-            x++; // reserved
-            int n = *x;
+            int n = d.pullInt();
             out() << "\tkillCursors n: " << n << endl;
             break;
         }
         default:
             out() << "\tunknown opcode " << m.operation() << endl;
@@ -364,11 +362,11 @@ void processMessage( Connection& c , Message& m ) {
             }
             if ( m.operation() == mongo::dbQuery || m.operation() == mongo::dbGetMore ) {
                 if ( m.operation() == mongo::dbGetMore ) {
                     DbMessage d( m );
                     d.pullInt();
-                    long long &cId = d.pullInt64();
+                    long long cId = d.pullInt64();
                     cId = mapCursor[ c ][ cId ];
                 }
                 Message response;
                 conn->port().call( m, response );
                 QueryResult *qr = (QueryResult *) response.singleData();
```

### `src/mongo/util/net/message.h`

```diff
diff --git a/src/mongo/util/net/message.h b/src/mongo/util/net/message.h
index 154242f4fd5..80205e1d1f5 100644
--- a/src/mongo/util/net/message.h
+++ b/src/mongo/util/net/message.h
@@ -118,26 +118,30 @@ namespace mongo {
     };
 #pragma pack()
 
 #pragma pack(1)
     /* todo merge this with MSGHEADER (or inherit from it). */
-    struct MsgData {
+    class MsgData {
+        friend class Message;
+        friend class DbMessage;
+        friend class MessagingPort;
+    public:
         int len; /* len of the msg, including this field */
         MSGID id; /* request/reply id's match... */
         MSGID responseTo; /* id of the message we are responding to */
         short _operation;
         char _flags;
         char _version;
+
         int operation() const {
             return _operation;
         }
         void setOperation(int o) {
             _flags = 0;
             _version = 0;
             _operation = o;
         }
-        char _data[4];
 
         int& dataAsInt() {
             return *((int *) _data);
         }
 
@@ -155,10 +159,12 @@ namespace mongo {
             long long * l = (long long *)(_data + 4);
             return l[0];
         }
 
         int dataLen(); // len without header
+    private:
+        char _data[4]; //must be last member
     };
     const int MsgDataHeaderSize = sizeof(MsgData) - 4;
     inline int MsgData::dataLen() {
         return len - MsgDataHeaderSize;
     }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
