# Annotation packet: SERVER-22458  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
KeyString::TypeBits incorrectly limits length to 63 bytes

This is only a theoretical issue, as the BSON size of a key is limited to 1024 bytes, so 63 bytes of data would require in 64*4 = 252 numeric fields, which is impossible.
```

## Fix commit message(s)

`e4474b03eaa1`

```
SERVER-22458: Return TypeBits size bytes values up to kMaxBytesNeeded
```

## Files the fix changed

Snapshot holds 8,537 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/db/storage/key_string.h`

## The fix diff

### `src/mongo/db/storage/key_string.h`

```diff
diff --git a/src/mongo/db/storage/key_string.h b/src/mongo/db/storage/key_string.h
index 7ef8ee0e723..02302498b0d 100644
--- a/src/mongo/db/storage/key_string.h
+++ b/src/mongo/db/storage/key_string.h
@@ -184,11 +184,11 @@ public:
     private:
         /**
          * size only includes data bytes, not the size byte itself.
          */
         uint8_t getSizeByte() const {
-            return _buf[0] & 0x3f;
+            return _buf[0] & 0x7f;
         }
         void setSizeByte(uint8_t size) {
             dassert(size < kMaxBytesNeeded);
             _buf[0] = 0x80 | size;
         }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
