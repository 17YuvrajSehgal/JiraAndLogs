# Annotation packet: MDEV-12609  (mariadb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Allow suppression of InnoDB log messages about reserving extents

A user is constantly seeing messages like the following:

{noformat}
2017-04-23 23:47:44 139336886889216 [Note] InnoDB: Space id 1131 trying to reserve 3 extents actually reserved 256 reserve 7010 free 201 size 44857344 rounds 51 total_reserved 13056
2017-04-23 23:47:44 139336886889216 [Note] InnoDB: Space id 1131 trying to reserve 3 extents actually reserved 256 reserve 7011 free 205 size 44857600 rounds 52 total_reserved 13312
{noformat}

It looks like these messages were added as part of the fix for MDEV-8386.

These messages are causing the user's error log to grow very large.

Would it be possible to make some way to suppress these log messages? Maybe they can be changed to warnings, and then suppressed by decreasing log_warnings? Or maybe it can be controlled by some other variable?
```

## Fix commit message(s)

`d03abc71a490`

```
MDEV-12609: Allow suppression of InnoDB log messages about reserving extents

Removed this output.
```

## Files the fix changed

Snapshot holds 4,005 non-test source files. The fix changed 2 file(s); 2 of them are non-test source files (listed below as gold).

- `storage/innobase/fsp/fsp0fsp.cc`
- `storage/xtradb/fsp/fsp0fsp.cc`

## The fix diff

### `storage/innobase/fsp/fsp0fsp.cc`

```diff
diff --git a/storage/innobase/fsp/fsp0fsp.cc b/storage/innobase/fsp/fsp0fsp.cc
index 1732a02aeac..d04cd7168ed 100644
--- a/storage/innobase/fsp/fsp0fsp.cc
+++ b/storage/innobase/fsp/fsp0fsp.cc
@@ -2727,11 +2727,10 @@ fsp_reserve_free_extents(
 	ulint		n_free_up;
 	ulint		reserve;
 	ibool		success;
 	ulint		n_pages_added;
 	size_t		total_reserved = 0;
-	ulint		rounds = 0;
 
 	ut_ad(mtr);
 	*n_reserved = n_ext;
 
 	latch = fil_space_get_latch(space, &flags);
@@ -2807,21 +2806,11 @@ try_again:
 try_to_extend:
 	success = fsp_try_extend_data_file(&n_pages_added, space,
 					   space_header, mtr);
 
 	if (success && n_pages_added > 0) {
-
-		rounds++;
 		total_reserved += n_pages_added;
-
-		if (rounds > 50) {
-			ib_logf(IB_LOG_LEVEL_INFO,
-				"Space id %lu trying to reserve %lu extents actually reserved %lu "
-				" reserve %lu free %lu size %lu rounds %lu total_reserved %llu",
-				space, n_ext, n_pages_added, reserve, n_free, size, rounds, (ullint) total_reserved);
-		}
-
 		goto try_again;
 	}
 
 	return(FALSE);
 }
```

### `storage/xtradb/fsp/fsp0fsp.cc`

```diff
diff --git a/storage/xtradb/fsp/fsp0fsp.cc b/storage/xtradb/fsp/fsp0fsp.cc
index 9292f84ab02..cf6fa4211ca 100644
--- a/storage/xtradb/fsp/fsp0fsp.cc
+++ b/storage/xtradb/fsp/fsp0fsp.cc
@@ -2736,11 +2736,10 @@ fsp_reserve_free_extents(
 	ulint		n_free_up;
 	ulint		reserve;
 	ibool		success;
 	ulint		n_pages_added;
 	size_t		total_reserved = 0;
-	ulint		rounds = 0;
 
 	ut_ad(mtr);
 	*n_reserved = n_ext;
 
 	latch = fil_space_get_latch(space, &flags);
@@ -2815,21 +2814,11 @@ try_again:
 	}
 try_to_extend:
 	success = fsp_try_extend_data_file(&n_pages_added, space,
 					   space_header, mtr);
 	if (success && n_pages_added > 0) {
-
-		rounds++;
 		total_reserved += n_pages_added;
-
-		if (rounds > 50) {
-			ib_logf(IB_LOG_LEVEL_INFO,
-				"Space id %lu trying to reserve %lu extents actually reserved %lu "
-				" reserve %lu free %lu size %lu rounds %lu total_reserved %llu",
-				space, n_ext, n_pages_added, reserve, n_free, size, rounds, (ullint) total_reserved);
-		}
-
 		goto try_again;
 	}
 
 	return(FALSE);
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
