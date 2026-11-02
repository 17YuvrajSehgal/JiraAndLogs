# Annotation packet: BEAM-3793  (beam)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
SDK harness should log bad gRPC responses

As of now, if a null ProvisionInfo is passed to the boot code, it panics when trying to convert to JSON. It should at the very least log a useful error message if a bad ProvisionInfo is received.

 

Sample stack trace:

panic: reflect: call of reflect.Value.Field on zero Value

goroutine 1 [running]:
reflect.Value.Field(0x0, 0x0, 0x0, 0x0, 0x0, 0x1, 0x81f2e0)
 /Users/sidhom/.gradle/go/binary/1.9/go/src/reflect/value.go:759 +0x12e
github.com/apache/beam/sdks/java/boot/vendor/github.com/golang/protobuf/jsonpb.(*Marshaler).marshalObject(0xc42015cb10, 0xc4201bbbb0, 0xb7a7e0, 0x0, 0x0, 0x0, 0x0, 0x0, 0xc4201bbbd0, 0x410e58)
 /Users/sidhom/Downloads/git/beam/sdks/java/container/.gogradle/project_gopath/src/github.com/apache/beam/sdks/java/boot/vendor/github.com/golang/protobuf/jsonpb/jsonpb.go:207 +0x1040
github.com/apache/beam/sdks/java/boot/vendor/github.com/golang/protobuf/jsonpb.(*Marshaler).Marshal(0xc42015cb10, 0xb70ae0, 0xc4201ac770, 0xb7a7e0, 0x0, 0x8a53e0, 0x4c3601)
 /Users/sidhom/Downloads/git/beam/sdks/java/container/.gogradle/project_gopath/src/github.com/apache/beam/sdks/java/boot/vendor/github.com/golang/protobuf/jsonpb/jsonpb.go:122 +0xc1
github.com/apache/beam/sdks/java/boot/vendor/github.com/golang/protobuf/jsonpb.(*Marshaler).MarshalToString(0xc42015cb10, 0xb7a7e0, 0x0, 0x1, 0x15, 0x0, 0x0)
 /Users/sidhom/Downloads/git/beam/sdks/java/container/.gogradle/project_gopath/src/github.com/apache/beam/sdks/java/boot/vendor/github.com/golang/protobuf/jsonpb/jsonpb.go:128 +0x6e
github.com/apache/beam/sdks/java/boot/vendor/github.com/apache/beam/sdks/go/pkg/beam/provision.ProtoToJSON(0x0, 0x12, 0xc4201bbdc0, 0x1, 0x1)
 /Users/sidhom/Downloads/git/beam/sdks/java/container/.gogradle/project_gopath/src/github.com/apache/beam/sdks/java/boot/vendor/github.com/apache/beam/sdks/go/pkg/beam/provision/provison.go:79 +0x51
main.main()
 /Users/sidhom/Downloads/git/beam/sdks/java/container/.gogradle/project_gopath/src/github.com/apache/beam/sdks/java/boot/boot.go:80 +0x309
```

## Fix commit message(s)

`952f571074c0`

```
[BEAM-3793] Validate provision response and add beamctl support
```

## Files the fix changed

Snapshot holds 1,894 non-test source files. The fix changed 4 file(s); 1 of them are non-test source files (listed below as gold).

- `sdks/go/cmd/beamctl/cmd/root.go`

## The fix diff

### `sdks/go/cmd/beamctl/cmd/root.go`

```diff
diff --git a/sdks/go/cmd/beamctl/cmd/root.go b/sdks/go/cmd/beamctl/cmd/root.go
index a4e79456f9f..7aedb57c77e 100644
--- a/sdks/go/cmd/beamctl/cmd/root.go
+++ b/sdks/go/cmd/beamctl/cmd/root.go
@@ -36,11 +36,11 @@ var (
 	id       string
 	endpoint string
 )
 
 func init() {
-	RootCmd.AddCommand(artifactCmd)
+	RootCmd.AddCommand(artifactCmd, provisionCmd)
 	RootCmd.PersistentFlags().StringVarP(&endpoint, "endpoint", "e", "", "Server endpoint, such as localhost:123")
 	RootCmd.PersistentFlags().StringVarP(&id, "id", "i", "", "Client ID")
 }
 
 // dial connects via gRPC to the given endpoint and returns the connection
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
