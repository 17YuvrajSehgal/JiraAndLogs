# Annotation packet: SERVER-30467  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Extend $_internalSchemaMinLength and $_internalSchemaMaxLength to count lengths of Unicode strings

{{$_internalSchemaMinLength}} and {{$_internalSchemaMaxLength}} must be updated to properly count the lengths of Unicode strings, which may contain multibyte characters.
```

## Fix commit message(s)

`83e1ff54a1ef`

```
SERVER-30467 $_internalSchema{Min|Max}Length counts UTF-8 code points.
```

## Files the fix changed

Snapshot holds 10,935 non-test source files. The fix changed 6 file(s); 3 of them are non-test source files (listed below as gold).

- `src/mongo/db/matcher/schema/expression_internal_schema_str_length.h`
- `src/mongo/db/pipeline/expression.cpp`
- `src/mongo/util/mongoutils/str.h`

## The fix diff

### `src/mongo/db/matcher/schema/expression_internal_schema_str_length.h`

```diff
diff --git a/src/mongo/db/matcher/schema/expression_internal_schema_str_length.h b/src/mongo/db/matcher/schema/expression_internal_schema_str_length.h
index 5ff2ff7f52d..f83c6d584dc 100644
--- a/src/mongo/db/matcher/schema/expression_internal_schema_str_length.h
+++ b/src/mongo/db/matcher/schema/expression_internal_schema_str_length.h
@@ -54,15 +54,12 @@ public:
                               MatchDetails* details = nullptr) const final {
         if (elem.type() != BSONType::String) {
             return false;
         }
 
-        // BSONElement::valuestrsize() includes the terminating null character, so subtract 1 before
-        // comparing its length.
-        int lenWithoutNullTerm = elem.valuestrsize() - 1;
-
-        return getComparator()(lenWithoutNullTerm);
+        auto len = str::lengthInUTF8CodePoints(elem.valueStringData());
+        return getComparator()(len);
     };
 
     void debugString(StringBuilder& debug, int level) const final;
 
     void serialize(BSONObjBuilder* out) const final;
```

### `src/mongo/db/pipeline/expression.cpp`

```diff
diff --git a/src/mongo/db/pipeline/expression.cpp b/src/mongo/db/pipeline/expression.cpp
index d1bdaf6c983..c5877f5eee1 100644
--- a/src/mongo/db/pipeline/expression.cpp
+++ b/src/mongo/db/pipeline/expression.cpp
@@ -167,19 +167,10 @@ intrusive_ptr<Expression> Expression::parseOperand(
         return ExpressionConstant::parse(expCtx, exprElement, vps);
     }
 }
 
 namespace {
-/**
- * UTF-8 multi-byte code points consist of one leading byte of the form 11xxxxxx, and potentially
- * many continuation bytes of the form 10xxxxxx. This method checks whether 'charByte' is a
- * continuation byte.
- */
-bool isContinuationByte(char charByte) {
-    return (charByte & 0xc0) == 0x80;
-}
-
 /**
  * UTF-8 multi-byte code points consist of one leading byte of the form 11xxxxxx, and potentially
  * many continuation bytes of the form 10xxxxxx. This method checks whether 'charByte' is a leading
  * byte.
  */
@@ -2690,12 +2681,13 @@ Value ExpressionIndexOfCP::evaluate(const Document& root) const {
         if (codePointLength == startCodePointIndex) {
             // We have determined the byte at which our search will start.
             startByteIndex = byteIx;
         }
 
-        uassert(
-            40095, "$indexOfCP found bad UTF-8 in the input", !isContinuationByte(input[byteIx]));
+        uassert(40095,
+                "$indexOfCP found bad UTF-8 in the input",
+                !str::isUTF8ContinuationByte(input[byteIx]));
         byteIx += getCodePointLength(input[byteIx]);
     }
 
     size_t endCodePointIndex = codePointLength;
     if (vpOperand.size() > 3) {
@@ -3880,19 +3872,19 @@ Value ExpressionSubstrBytes::evaluate(const Document& root) const {
     string::size_type length = static_cast<string::size_type>(pLength.coerceToLong());
 
     uassert(28656,
             str::stream() << getOpName()
                           << ":  Invalid range, starting index is a UTF-8 continuation byte.",
-            (lower >= str.length() || !isContinuationByte(str[lower])));
+            (lower >= str.length() || !str::isUTF8ContinuationByte(str[lower])));
 
     // Check the byte after the last character we'd return. If it is a continuation byte, that
     // means we're in the middle of a UTF-8 character.
     uassert(
         28657,
         str::stream() << getOpName()
                       << ":  Invalid range, ending index is in the middle of a UTF-8 character.",
-        (lower + length >= str.length() || !isContinuationByte(str[lower + length])));
+        (lower + length >= str.length() || !str::isUTF8ContinuationByte(str[lower + length])));
 
     if (lower >= str.length()) {
         // If lower > str.length() then string::substr() will throw out_of_range, so return an
         // empty string if lower is not a valid string index.
         return Value(StringData());
@@ -3953,11 +3945,11 @@ Value ExpressionSubstrCP::evaluate(const Document& root) const {
         if (startIndexBytes >= str.size()) {
             return Value(StringData());
         }
         uassert(34456,
                 str::stream() << getOpName() << ": invalid UTF-8 string",
-                !isContinuationByte(str[startIndexBytes]));
+                !str::isUTF8ContinuationByte(str[startIndexBytes]));
         size_t codePointLength = getCodePointLength(str[startIndexBytes]);
         uassert(
             34457, str::stream() << getOpName() << ": invalid UTF-8 string", codePointLength <= 4);
         startIndexBytes += codePointLength;
     }
@@ -3965,11 +3957,11 @@ Value ExpressionSubstrCP::evaluate(const Document& root) const {
     size_t endIndexBytes = startIndexBytes;
 
     for (int i = 0; i < length && endIndexBytes < str.size(); i++) {
         uassert(34458,
                 str::stream() << getOpName() << ": invalid UTF-8 string",
-                !isContinuationByte(str[endIndexBytes]));
+                !str::isUTF8ContinuationByte(str[endIndexBytes]));
         size_t codePointLength = getCodePointLength(str[endIndexBytes]);
         uassert(
             34459, str::stream() << getOpName() << ": invalid UTF-8 string", codePointLength <= 4);
         endIndexBytes += codePointLength;
     }
@@ -4014,15 +4006,11 @@ Value ExpressionStrLenCP::evaluate(const Document& root) const {
             str::stream() << "$strLenCP requires a string argument, found: "
                           << typeName(val.getType()),
             val.getType() == String);
 
     std::string stringVal = val.getString();
-
-    size_t strLen = 0;
-    for (char byte : stringVal) {
-        strLen += !isContinuationByte(byte);
-    }
+    size_t strLen = str::lengthInUTF8CodePoints(stringVal);
 
     uassert(34472,
             "string length could not be represented as an int.",
             strLen <= std::numeric_limits<int>::max());
```

### `src/mongo/util/mongoutils/str.h`

```diff
diff --git a/src/mongo/util/mongoutils/str.h b/src/mongo/util/mongoutils/str.h
index c1967003506..d85ddcb2abf 100644
--- a/src/mongo/util/mongoutils/str.h
+++ b/src/mongo/util/mongoutils/str.h
@@ -237,10 +237,32 @@ inline std::string ltrim(const std::string& s) {
     while (*p == ' ')
         p++;
     return p;
 }
 
+/**
+ * UTF-8 multi-byte code points consist of one leading byte of the form 11xxxxxx, and potentially
+ * many continuation bytes of the form 10xxxxxx. This method checks whether 'charByte' is a
+ * continuation byte.
+ */
+inline bool isUTF8ContinuationByte(char charByte) {
+    return (charByte & 0xc0) == 0x80;
+}
+
+/**
+ * Assuming 'str' stores a UTF-8 string, returns the number of UTF codepoints. The return value is
+ * undefined if the input is not a well formed UTF-8 string.
+ */
+inline size_t lengthInUTF8CodePoints(mongo::StringData str) {
+    size_t strLen = 0;
+    for (char byte : str) {
+        strLen += !isUTF8ContinuationByte(byte);
+    }
+
+    return strLen;
+}
+
 }  // namespace str
 
 }  // namespace mongoutils
 
 namespace mongo {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
