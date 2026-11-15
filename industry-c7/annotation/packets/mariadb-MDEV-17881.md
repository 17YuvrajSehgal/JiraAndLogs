# Annotation packet: MDEV-17881  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Assertion failure in cmp_dtuple_rec_with_match_bytes after instant ADD COLUMN

The special flag {{REC_INFO_MIN_REC_FLAG}} used to be only set on the first record in the leftmost node pointer page of each level of the tree. It was never set on leaf pages.

MDEV-11369 Instant {{ADD COLUMN}} in MariaDB Server 10.3 repurposed the flag to identify a hidden metadata record, which is stored in the first record on the leftmost leaf page.

If the adaptive hash index points to records in the leftmost leaf page after instant {{ADD COLUMN}} (or MDEV-15562 instant {{DROP COLUMN}} in 10.4.0), we would have such a metadata record in the table, an assertion could fail when trying to validate the index record:
{noformat}
mysqld: /mariadb/10.4/storage/innobase/rem/rem0cmp.cc:799: int cmp_dtuple_rec_with_match_bytes(const dtuple_t*, const rec_t*, const dict_index_t*, const ulint*, ulint*, ulint*): Assertion `!(0x10UL & rec_get_info_bits(rec, rec_offs_comp(offsets)))' failed.
{noformat}
I only repeated this in a 10.4-based development tree. Due to the highly nondeterministic nature of the adaptive hash index, it could be difficult to construct a deterministic test case for this.
```

## Fix commit message(s)

`e46a3aa42e1d`

```
MDEV-17881 Assertion failure in cmp_dtuple_rec_with_match_bytes after instant ADD COLUMN

The special flag REC_INFO_MIN_REC_FLAG used to be only set on the
first record in the leftmost node pointer page of each level of the tree.
It was never set on leaf pages.

MDEV-11369 Instant ADD COLUMN in MariaDB Server 10.3 repurposed the flag
to identify a hidden metadata record, which is stored in the first record
on the leftmost leaf page.

If the adaptive hash index points to records in the leftmost leaf page
after instant ALTER TABLE, we would have such a metadata record in the
table, an assertion could fail when trying to validate the index record.
In a release build, we might wrongly qualify the hidden metadata record
and thus return garbage results.

cmp_dtuple_rec_with_match_bytes(): If the REC_INFO_MIN_REC_FLAG is
set on the record, assert that this is the first record on the
leftmost page and that the record is a metadata record, and finally
return 1, because by definition, anything is greater than the
minimum record.
```

`95f3c142a4f2`

```
MDEV-17881: Fix a debug assertion

In 10.3, rec_is_metadata() takes a pointer, while in 10.4 it
takes a reference as a parameter. I ported this patch from
10.4 to 10.3, and then only ran a release build, not debug build.
```

## Files the fix changed

Snapshot holds 3,327 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `storage/innobase/rem/rem0cmp.cc`

## The fix diff

### `storage/innobase/rem/rem0cmp.cc`

```diff
--- from commit e46a3aa42e1d ---
diff --git a/storage/innobase/rem/rem0cmp.cc b/storage/innobase/rem/rem0cmp.cc
index f8449e5443f..623d0bd1aa9 100644
--- a/storage/innobase/rem/rem0cmp.cc
+++ b/storage/innobase/rem/rem0cmp.cc
@@ -23,10 +23,11 @@ Comparison services for records
 Created 7/1/1994 Heikki Tuuri
 ************************************************************************/
 
 #include "rem0cmp.h"
 #include "rem0rec.h"
+#include "page0page.h"
 #include "dict0mem.h"
 #include "handler0alter.h"
 
 /*		ALPHABETICAL ORDER
 		==================
@@ -785,24 +786,27 @@ cmp_dtuple_rec_with_match_bytes(
 	const dict_index_t*	index,
 	const ulint*		offsets,
 	ulint*			matched_fields,
 	ulint*			matched_bytes)
 {
-	ulint		n_cmp	= dtuple_get_n_fields_cmp(dtuple);
-	ulint		cur_field;	/* current field number */
-	ulint		cur_bytes;
-	int		ret;		/* return value */
-
 	ut_ad(dtuple_check_typed(dtuple));
 	ut_ad(rec_offs_validate(rec, index, offsets));
 	ut_ad(!(REC_INFO_MIN_REC_FLAG
 		& dtuple_get_info_bits(dtuple)));
-	ut_ad(!(REC_INFO_MIN_REC_FLAG
-		& rec_get_info_bits(rec, rec_offs_comp(offsets))));
 
-	cur_field = *matched_fields;
-	cur_bytes = *matched_bytes;
+	if (UNIV_UNLIKELY(REC_INFO_MIN_REC_FLAG
+			  & rec_get_info_bits(rec, rec_offs_comp(offsets)))) {
+		ut_ad(page_rec_is_first(rec, page_align(rec)));
+		ut_ad(!page_has_prev(page_align(rec)));
+		ut_ad(rec_is_metadata(rec, *index));
+		return 1;
+	}
+
+	ulint cur_field = *matched_fields;
+	ulint cur_bytes = *matched_bytes;
+	ulint n_cmp = dtuple_get_n_fields_cmp(dtuple);
+	int ret;
 
 	ut_ad(n_cmp <= dtuple_get_n_fields(dtuple));
 	ut_ad(cur_field <= n_cmp);
 	ut_ad(cur_field + (cur_bytes > 0) <= rec_offs_n_fields(offsets));
--- from commit 95f3c142a4f2 ---
diff --git a/storage/innobase/rem/rem0cmp.cc b/storage/innobase/rem/rem0cmp.cc
index 623d0bd1aa9..6b914c46ecf 100644
--- a/storage/innobase/rem/rem0cmp.cc
+++ b/storage/innobase/rem/rem0cmp.cc
@@ -795,11 +795,11 @@ cmp_dtuple_rec_with_match_bytes(
 
 	if (UNIV_UNLIKELY(REC_INFO_MIN_REC_FLAG
 			  & rec_get_info_bits(rec, rec_offs_comp(offsets)))) {
 		ut_ad(page_rec_is_first(rec, page_align(rec)));
 		ut_ad(!page_has_prev(page_align(rec)));
-		ut_ad(rec_is_metadata(rec, *index));
+		ut_ad(rec_is_metadata(rec, index));
 		return 1;
 	}
 
 	ulint cur_field = *matched_fields;
 	ulint cur_bytes = *matched_bytes;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
