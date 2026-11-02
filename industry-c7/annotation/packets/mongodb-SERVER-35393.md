# Annotation packet: SERVER-35393  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Go Driver Unit Tests receive error code 9001 when doing a large insert many

When running the {{TestCollection_InsertMany_Batches}} unit test the Go driver returns the following error:
{code:go}
mongo.BulkWriteError{WriteErrors:mongo.WriteErrors{mongo.WriteError{Index:0, Code:9001, Message:"Write results unavailable from localhost:27026 :: caused by :: asio.ssl stream truncated"}}, WriteConcernError:(*mongo.WriteConcernError)(nil)}
{code}

This only occurs when for that test and the remainder of the tests pass. This only occurs on macOS.
```

## Fix commit message(s)

`99ac27f83e67`

```
SERVER-35393 Flush output buffer before attempting new writes
```

`573ebb251784`

```
SERVER-35393 Flush asio output and limit SecureTransport out buffer
```

## Files the fix changed

Snapshot holds 11,581 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/util/net/ssl/detail/io.hpp`

## The fix diff

### `src/mongo/util/net/ssl/detail/io.hpp`

```diff
--- from commit 573ebb251784 ---
diff --git a/src/mongo/util/net/ssl/detail/io.hpp b/src/mongo/util/net/ssl/detail/io.hpp
index 6c0bc5f69fc..b943b1fb16f 100644
--- a/src/mongo/util/net/ssl/detail/io.hpp
+++ b/src/mongo/util/net/ssl/detail/io.hpp
@@ -49,21 +49,25 @@ std::size_t io(Stream& next_layer, stream_core& core, const Operation& op, asio:
             case engine::want_output_and_retry:
 
                 core.output_ = core.engine_.get_output(core.output_buffer_);
                 // Get output data from the engine and write it to the underlying
                 // transport.
-                core.output_ += asio::write(next_layer, core.output_, ec);
+                while (!ec && core.output_.size()) {
+                    core.output_ += asio::write(next_layer, core.output_, ec);
+                }
 
                 // Try the operation again.
                 continue;
 
             case engine::want_output:
 
                 core.output_ = core.engine_.get_output(core.output_buffer_);
                 // Get output data from the engine and write it to the underlying
                 // transport.
-                core.output_ += asio::write(next_layer, core.output_, ec);
+                while (!ec && core.output_.size()) {
+                    core.output_ += asio::write(next_layer, core.output_, ec);
+                }
 
                 // Operation is complete. Return result to caller.
                 core.engine_.map_error_code(ec);
                 return bytes_transferred;
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
