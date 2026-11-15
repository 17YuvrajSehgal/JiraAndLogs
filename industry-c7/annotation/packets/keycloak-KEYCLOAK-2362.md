# Annotation packet: KEYCLOAK-2362  (keycloak)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
NPE if SSL certificate is not trusted by Java's default keystore

To be honest not sure if this really the reason. It could also be that NPE occurs if 

{code}
   "truststore": {
      "file": {
          "file": "/home/xxx/cacerts",
          "password": "changeit"
      }
  }
{code}

is not present. 

{code}
# https://confluence.atlassian.com/download/attachments/117455/SSLPoke.java
[yyy@xxx ~]$  java  -cp . SSLPoke some.server.com 443
javax.net.ssl.SSLHandshakeException: sun.security.validator.ValidatorException: PKIX path building failed: sun.security.provider.certpath.SunCertPathBuilderException: unable to find valid certification path to requested target
	at sun.security.ssl.Alerts.getSSLException(Alerts.java:192)
	at sun.security.ssl.SSLSocketImpl.fatal(SSLSocketImpl.java:1949)
	at sun.security.ssl.Handshaker.fatalSE(Handshaker.java:302)
	at sun.security.ssl.Handshaker.fatalSE(Handshaker.java:296)
	at sun.security.ssl.ClientHandshaker.serverCertificate(ClientHandshaker.java:1509)
	at sun.security.ssl.ClientHandshaker.processMessage(ClientHandshaker.java:216)
	at sun.security.ssl.Handshaker.processLoop(Handshaker.java:979)
	at sun.security.ssl.Handshaker.process_record(Handshaker.java:914)
	at sun.security.ssl.SSLSocketImpl.readRecord(SSLSocketImpl.java:1062)
	at sun.security.ssl.SSLSocketImpl.performInitialHandshake(SSLSocketImpl.java:1375)
	at sun.security.ssl.SSLSocketImpl.writeRecord(SSLSocketImpl.java:747)
	at sun.security.ssl.AppOutputStream.write(AppOutputStream.java:123)
	at sun.security.ssl.AppOutputStream.write(AppOutputStream.java:138)
	at SSLPoke.main(SSLPoke.java:23)
Caused by: sun.security.validator.ValidatorException: PKIX path building failed: sun.security.provider.certpath.SunCertPathBuilderException: unable to find valid certification path to requested target
	at sun.security.validator.PKIXValidator.doBuild(PKIXValidator.java:387)
	at sun.security.validator.PKIXValidator.engineValidate(PKIXValidator.java:292)
	at sun.security.validator.Validator.validate(Validator.java:260)
	at sun.security.ssl.X509TrustManagerImpl.validate(X509TrustManagerImpl.java:324)
	at sun.security.ssl.X509TrustManagerImpl.checkTrusted(X509TrustManagerImpl.java:229)
	at sun.security.ssl.X509TrustManagerImpl.checkServerTrusted(X509TrustManagerImpl.java:124)
	at sun.security.ssl.ClientHandshaker.serverCertificate(ClientHandshaker.java:1491)
	... 9 more
Caused by: sun.security.provider.certpath.SunCertPathBuilderException: unable to find valid certification path to requested target
	at sun.security.provider.certpath.SunCertPathBuilder.build(SunCertPathBuilder.java:146)
	at sun.security.provider.certpath.SunCertPathBuilder.engineBuild(SunCertPathBuilder.java:131)
	at java.security.cert.CertPathBuilder.build(CertPathBuilder.java:280)
	at sun.security.validator.PKIXValidator.doBuild(PKIXValidator.java:382)
	... 15 more
{code}

{code}
Caused by: java.lang.NullPointerException
        at java.util.Hashtable.put(Hashtable.java:459)
        at org.keycloak.email.DefaultEmailSenderProvider.setupTruststore(DefaultEmailSenderProvider.java:116)
        at org.keycloak.email.DefaultEmailSenderProvider.send(DefaultEmailSenderProvider.java:67)
        ... 58 more
{code}

At least after adding certificate as trusted and configuring truststore it worked.

BTW: It seems that {{-Djavax.net.ssl.trustStore=/home/xxx/cacerts}} doesn't work anymore. Not sure if this is good or bad. At least it confused me.
```

## Fix commit message(s)

`4f890e8f2e18`

```
KEYCLOAK-2362 NPE if SSL certificate is not trusted by Java's default keystore
```

## Files the fix changed

Snapshot holds 1,907 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `services/src/main/java/org/keycloak/email/DefaultEmailSenderProvider.java`

## The fix diff

### `services/src/main/java/org/keycloak/email/DefaultEmailSenderProvider.java`

```diff
diff --git a/services/src/main/java/org/keycloak/email/DefaultEmailSenderProvider.java b/services/src/main/java/org/keycloak/email/DefaultEmailSenderProvider.java
index 7069ef2f1a..57c17b58d3 100644
--- a/services/src/main/java/org/keycloak/email/DefaultEmailSenderProvider.java
+++ b/services/src/main/java/org/keycloak/email/DefaultEmailSenderProvider.java
@@ -13,10 +13,11 @@ import javax.mail.Session;
 import javax.mail.Transport;
 import javax.mail.internet.InternetAddress;
 import javax.mail.internet.MimeBodyPart;
 import javax.mail.internet.MimeMessage;
 import javax.mail.internet.MimeMultipart;
+import javax.net.ssl.SSLSocketFactory;
 import java.security.KeyManagementException;
 import java.security.NoSuchAlgorithmException;
 import java.util.Date;
 import java.util.Map;
 import java.util.Properties;
@@ -111,13 +112,16 @@ public class DefaultEmailSenderProvider implements EmailSenderProvider {
 
     private void setupTruststore(Properties props) throws NoSuchAlgorithmException, KeyManagementException {
 
         JSSETruststoreConfigurator configurator = new JSSETruststoreConfigurator(session);
 
-        props.put("mail.smtp.ssl.socketFactory", configurator.getSSLSocketFactory());
-        if (configurator.getProvider().getPolicy() == HostnameVerificationPolicy.ANY) {
-            props.setProperty("mail.smtp.ssl.trust", "*");
+        SSLSocketFactory factory = configurator.getSSLSocketFactory();
+        if (factory != null) {
+            props.put("mail.smtp.ssl.socketFactory", factory);
+            if (configurator.getProvider().getPolicy() == HostnameVerificationPolicy.ANY) {
+                props.setProperty("mail.smtp.ssl.trust", "*");
+            }
         }
     }
 
     @Override
     public void close() {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
