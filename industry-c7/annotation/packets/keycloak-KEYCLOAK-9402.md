# Annotation packet: KEYCLOAK-9402  (keycloak)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
TokenNotActiveException and DISABLED policy enforcer returns status 200 with empty body

When calling service with configured policy-enforcer.enforcement-mode DISABLED and with expired token, I receive response with status 200 OK and empty body. Expected received status should be 401 Unauthorized or 403 Forbidden.

When calling service with configured UMA and with expired token, I also receive response with status 401 Unauthorized with WWW-Authenticate header with ticket in it. Then when calling _{{keycloak-url}}/realms/{{keycloak-realm}}/protocol/openid-connect/token_ with _grant_type urn:ietf:params:oauth:grant-type:uma-ticket_, i get response 401 Unauthorized with error_descrioption: Invalid bearer token. Is this expected behaviour?


{code:java}
2019-01-24 09:34:11,663 ERROR  Failed to verify token {} org.keycloak.exceptions.TokenNotActiveException: Token is not active
	at org.keycloak.TokenVerifier$2.test(TokenVerifier.java:86)
	at org.keycloak.TokenVerifier.verify(TokenVerifier.java:466)
	at org.keycloak.adapters.rotation.AdapterTokenVerifier.verifyToken(AdapterTokenVerifier.java:54)
	at org.keycloak.adapters.BearerTokenRequestAuthenticator.authenticateToken(BearerTokenRequestAuthenticator.java:103)
	at org.keycloak.adapters.BearerTokenRequestAuthenticator.authenticate(BearerTokenRequestAuthenticator.java:88)
	at org.keycloak.adapters.RequestAuthenticator.authenticate(RequestAuthenticator.java:68)
	at org.keycloak.adapters.jetty.core.AbstractKeycloakJettyAuthenticator.validateRequest(AbstractKeycloakJettyAuthenticator.java:303)
	at org.eclipse.jetty.security.SecurityHandler.handle(SecurityHandler.java:483)
	at org.eclipse.jetty.server.handler.HandlerWrapper.handle(HandlerWrapper.java:132)
	at org.eclipse.jetty.server.handler.ScopedHandler.nextHandle(ScopedHandler.java:190)
	at org.eclipse.jetty.server.session.SessionHandler.doHandle(SessionHandler.java:1595)
	at org.eclipse.jetty.server.handler.ScopedHandler.nextHandle(ScopedHandler.java:188)
	at org.eclipse.jetty.server.handler.ContextHandler.doHandle(ContextHandler.java:1253)
	at org.eclipse.jetty.server.handler.ScopedHandler.nextScope(ScopedHandler.java:168)
	at org.eclipse.jetty.servlet.ServletHandler.doScope(ServletHandler.java:473)
	at org.eclipse.jetty.server.session.SessionHandler.doScope(SessionHandler.java:1564)
	at org.eclipse.jetty.server.handler.ScopedHandler.nextScope(ScopedHandler.java:166)
	at org.eclipse.jetty.server.handler.ContextHandler.doScope(ContextHandler.java:1155)
	at org.eclipse.jetty.server.handler.ScopedHandler.handle(ScopedHandler.java:141)
	at org.eclipse.jetty.server.handler.HandlerWrapper.handle(HandlerWrapper.java:132)
	at org.eclipse.jetty.server.Server.handle(Server.java:530)
	at org.eclipse.jetty.server.HttpChannel.handle(HttpChannel.java:347)
	at org.eclipse.jetty.server.HttpConnection.onFillable(HttpConnection.java:256)
	at org.eclipse.jetty.io.AbstractConnection$ReadCallback.succeeded(AbstractConnection.java:279)
	at org.eclipse.jetty.io.FillInterest.fillable(FillInterest.java:102)
	at org.eclipse.jetty.io.ChannelEndPoint$2.run(ChannelEndPoint.java:124)
	at org.eclipse.jetty.util.thread.strategy.EatWhatYouKill.doProduce(EatWhatYouKill.java:247)
	at org.eclipse.jetty.util.thread.strategy.EatWhatYouKill.produce(EatWhatYouKill.java:140)
	at org.eclipse.jetty.util.thread.strategy.EatWhatYouKill.run(EatWhatYouKill.java:131)
	at org.eclipse.jetty.util.thread.ReservedThreadExecutor$ReservedThread.run(ReservedThreadExecutor.java:382)
	at org.eclipse.jetty.util.thread.QueuedThreadPool.runJob(QueuedThreadPool.java:708)
	at org.eclipse.jetty.util.thread.QueuedThreadPool$2.run(QueuedThreadPool.java:626)
	at java.lang.Thread.run(Thread.java:748)
 
2019-01-24 09:34:11,668 DEBUG  Bearer FAILED {}  
2019-01-24 09:34:11,668 DEBUG  Policy enforcement is enabled. Enforcing policy decisions for path [http://localhost:8080/photoz-restful-api/v1/album/shares]. {}  
2019-01-24 09:34:11,733 DEBUG  Policy enforcement result for path [http://localhost:8080/photoz-restful-api/v1/album/shares] is : GRANTED {}  
2019-01-24 09:34:11,733 DEBUG  Returning authorization context with permissions: {}
{code}
```

## Fix commit message(s)

`2a82ed6eea1c`

```
[KEYCLOAK-9402] - 401 response when enforcement mode is DISABLED
```

## Files the fix changed

Snapshot holds 3,368 non-test source files. The fix changed 3 file(s); 1 of them are non-test source files (listed below as gold).

- `adapters/oidc/adapter-core/src/main/java/org/keycloak/adapters/authorization/AbstractPolicyEnforcer.java`

## The fix diff

### `adapters/oidc/adapter-core/src/main/java/org/keycloak/adapters/authorization/AbstractPolicyEnforcer.java`

```diff
diff --git a/adapters/oidc/adapter-core/src/main/java/org/keycloak/adapters/authorization/AbstractPolicyEnforcer.java b/adapters/oidc/adapter-core/src/main/java/org/keycloak/adapters/authorization/AbstractPolicyEnforcer.java
index 138e143359..1f4438f0d0 100644
--- a/adapters/oidc/adapter-core/src/main/java/org/keycloak/adapters/authorization/AbstractPolicyEnforcer.java
+++ b/adapters/oidc/adapter-core/src/main/java/org/keycloak/adapters/authorization/AbstractPolicyEnforcer.java
@@ -57,18 +57,21 @@ public abstract class AbstractPolicyEnforcer {
         this.policyEnforcer = policyEnforcer;
     }
 
     public AuthorizationContext authorize(OIDCHttpFacade httpFacade) {
         EnforcementMode enforcementMode = getEnforcerConfig().getEnforcementMode();
+        KeycloakSecurityContext securityContext = httpFacade.getSecurityContext();
 
         if (EnforcementMode.DISABLED.equals(enforcementMode)) {
+            if (securityContext == null) {
+                httpFacade.getResponse().sendError(401, "Invalid bearer");
+            }
             return createEmptyAuthorizationContext(true);
         }
 
         Request request = httpFacade.getRequest();
         PathConfig pathConfig = getPathConfig(request);
-        KeycloakSecurityContext securityContext = httpFacade.getSecurityContext();
 
         if (securityContext == null) {
             if (!isDefaultAccessDeniedUri(request)) {
                 if (pathConfig != null) {
                     if (EnforcementMode.DISABLED.equals(pathConfig.getEnforcementMode())) {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
