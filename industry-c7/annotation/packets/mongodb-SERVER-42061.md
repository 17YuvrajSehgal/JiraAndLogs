# Annotation packet: SERVER-42061  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Validate decrypted payload in ESE
```

## Fix commit message(s)

`7eab0b598578`

```
SERVER-42061 Validate decrypted payload in AEAD decrypt
```

## Files the fix changed

Snapshot holds 13,911 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/crypto/aead_encryption.cpp`

## The fix diff

### `src/mongo/crypto/aead_encryption.cpp`

```diff
diff --git a/src/mongo/crypto/aead_encryption.cpp b/src/mongo/crypto/aead_encryption.cpp
index 77ec7ed41c4..e3dc9c8072d 100644
--- a/src/mongo/crypto/aead_encryption.cpp
+++ b/src/mongo/crypto/aead_encryption.cpp
@@ -152,10 +152,29 @@ Status _aesDecrypt(const SymmetricKey& key,
                               << "]"
                               << "but found "
                               << *resultLen};
     }
 
+    /* Check that padding was removed.
+     *
+     * PKCS7 padding guarantees that the encrypted payload has
+     * between 1 and blocksize bytes of padding which should be
+     * removed during the decrypt process.
+     *
+     * If resultLen is the same as the payload len,
+     * that means no padding was removed.
+     *
+     * macOS CommonCrypto will return such payloads when either the
+     * key or ciphertext are corrupted and its unable to find any
+     * expected padding.  It fails open by returning whatever it can.
+     */
+    if (*resultLen >= dataSize) {
+        return {ErrorCodes::BadValue,
+                "Decrypt error, plaintext is as large or larger than "
+                "the ciphertext. This usually indicates an invalid key."};
+    }
+
     return Status::OK();
 } catch (const AssertionException& ex) {
     return ex.toStatus();
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
