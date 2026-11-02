# Annotation packet: SERVER-50097  (mongodb)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
inaccurate exhaustIsMasterMetrics if an isMaster command alias is used

The exhaust isMaster metrics rely on the [command name|https://github.com/mongodb/mongo/blob/f8be36eca7f5d17b0cbea557e8825046352eea19/src/mongo/db/service_entry_point_common.cpp#L1365] when [keeping track|https://github.com/mongodb/mongo/blob/f8be36eca7f5d17b0cbea557e8825046352eea19/src/mongo/transport/ismaster_metrics.cpp#L87-L94] of exhaust isMaster requests.

On mongod, we search the [command registry|https://github.com/mongodb/mongo/blob/f8be36eca7f5d17b0cbea557e8825046352eea19/src/mongo/db/service_entry_point_common.cpp#L1330-L1344] for the command name specified in the request object. This ensures that aliases like "ismaster" are properly covered in the exhaust isMaster metrics.

On mongos, however, we only look at the command name passed into the [request|https://github.com/mongodb/mongo/blob/f8be36eca7f5d17b0cbea557e8825046352eea19/src/mongo/s/commands/strategy.cpp#L1029]. This means that we will incorrectly mark inExhaustIsMaster as false if we send "ismaster" instead of "isMaster" to mongos. 

Mongos should look up the request's command name in the command registry so that any aliases to the isMaster command are correctly covered.
```

## Fix commit message(s)

`9e4b6e5c2f9e`

```
(empty)
```

## Files the fix changed

Snapshot holds 15,014 non-test source files. The fix changed 2 file(s); 1 of them are non-test source files (listed below as gold).

- `src/mongo/s/commands/strategy.cpp`

## The fix diff

### `src/mongo/s/commands/strategy.cpp`

```diff
(no diff retrieved)
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
