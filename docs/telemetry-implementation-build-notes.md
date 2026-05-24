# Telemetry Implementation Build Notes

**Created:** 2026-05-24
**Companion to:** `microservice-changes-todo.md` execution

This file records build-system tweaks the user must apply before the
shared interceptor packages (`src/_shared-go/`, `src/_shared-dotnet/`,
`src/_shared-node/`, `src/_shared-python/`) build successfully in their
fork.

---

## Go services (frontend, checkoutservice, productcatalogservice, shippingservice)

**Status:** ready to build.

Each consuming service's `go.mod` now has:
```
replace github.com/GoogleCloudPlatform/microservices-demo/src/_shared-go/rpclog => ../_shared-go/rpclog
```

The Go build inside the existing Dockerfile (`go build ./...`) will resolve
the `replace` directive because the Docker build context for each Go service
is typically the service's own directory. **This requires the build context
to include the sibling `_shared-go/` directory.**

Three options:

1. **Extend the docker build context** to the `src/` root for Go services,
   and pass `--build-arg SERVICE=checkoutservice` to identify the target.
   Cleanest long-term solution.
2. **Run `go mod vendor` first** so the shared package is captured in
   `vendor/` and the Dockerfile doesn't need the sibling.
3. **Multi-stage Dockerfile** that COPYs the sibling explicitly via
   BuildKit `--mount=type=bind`.

The user's existing `scripts/research-lab/render-online-boutique.ps1`
probably builds from the service dir, so option 2 (`go mod vendor`) is
the lowest-friction.

Action item: add `go mod vendor && go build` to the Go service Dockerfiles.

---

## .NET cartservice

**Status:** ready to build.

`cartservice.csproj` now has:
```xml
<ProjectReference Include="..\..\_shared-dotnet\RpcLogging\RpcLogging.csproj" />
```

The .NET SDK resolves project references via the `dotnet restore`/`dotnet
publish` steps in the existing Dockerfile. **This requires the docker build
context to include `_shared-dotnet/`.**

Action item: change the cartservice Dockerfile context to `src/` (the parent
of `cartservice/`) and adjust the COPY lines:

```dockerfile
# Before
COPY cartservice.csproj .
# After
COPY cartservice/src/cartservice.csproj cartservice/src/
COPY _shared-dotnet/ _shared-dotnet/
```

Or, simpler: pin a published NuGet of the shared lib. Out of scope for the
research fork; option above is fine.

---

## Node services (paymentservice, currencyservice)

**Status:** ready to build.

`package.json` now has:
```json
"@hipstershop/rpc-logging": "file:../_shared-node/rpc-logging"
```

npm's `file:` reference resolves at install time. **The docker build context
must include `_shared-node/`** so `npm install` can find it.

Action item: change the Node service Dockerfile context to `src/` and copy
both the service dir and `_shared-node/`:

```dockerfile
COPY paymentservice/ paymentservice/
COPY _shared-node/ _shared-node/
WORKDIR /app/paymentservice
RUN npm install
```

---

## Python services (recommendationservice, emailservice)

**Status:** action required in Dockerfile.

The Python services use `pip install -r requirements.txt`. The shared
package is referenced as an editable install. The Dockerfile must:

```dockerfile
# Build context = src/ (parent of recommendationservice/)
COPY _shared-python/ _shared-python/
COPY recommendationservice/ recommendationservice/
WORKDIR /app/recommendationservice
RUN pip install -e ../_shared-python/rpc_logging
RUN pip install -r requirements.txt
```

Also need to update `requirements.in` / `requirements.txt` to NOT pin
`hipstershop-rpc-logging` (it's editable).

---

## Java adservice

**Status:** no shared interceptor; using OTel Java agent only.

The OTel Java agent auto-instruments every gRPC handler and emits server
spans with timing + status info. Per microservice-changes.md L1, the goal
of the shared interceptor was per-RPC structured logs. Java agent spans
carry the same fields as `trace_id`, `span_id`, `method`, `latency_ms`,
`status_code`. **For adservice, we accept the spans as the L1 signal** —
duplicating in a Logback config would only inflate log volume.

If a follow-up phase shows we need an actual log line (for the Drain-lite
template miner), the M2.1-Java work plan is:

1. Add `logback-classic` + `logstash-logback-encoder` to `build.gradle`.
2. Add a Logback `appender` that emits one JSON line per gRPC method
   handler using `io.grpc.ServerInterceptor`.
3. Wire it via `ServerInterceptors.intercept(...)` at server creation
   time in `AdService.java`.

Tracked as **deferred** in `microservice-changes-todo.md`.

---

## Image registry push order

After all builds work, push images in this order to avoid stale-image races
during a kind reload:

1. Push shared-lib-only builders first (if any are tagged as images;
   currently none are — they are project references not separate images).
2. Push leaf services (no inbound deps from other modified services):
   adservice, currencyservice, emailservice, paymentservice,
   productcatalogservice, recommendationservice, shippingservice.
3. Push fan-in services last: cartservice, checkoutservice, frontend.

Order matters only if the image registry is a remote (Artifact Registry);
for local kind, it doesn't.

---

## Validation that builds work

Per-service smoke test (run from inside the service dir after the build
context fix):

| Service | Smoke command |
| --- | --- |
| Go | `docker build -t test-<svc> .. -f <svc>/Dockerfile` |
| .NET cartservice | `docker build -t test-cartservice ../.. -f cartservice/src/Dockerfile` |
| Node paymentservice | `docker build -t test-paymentservice ../ -f paymentservice/Dockerfile` |
| Python recommendationservice | `docker build -t test-recommend ../ -f recommendationservice/Dockerfile` |
| Java adservice | unchanged build path |

If any of these fail with "package not found", the build context is
still wrong; check the Dockerfile COPY paths.
