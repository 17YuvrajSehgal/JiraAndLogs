# Annotation packet: WFLY-2582  (wildfly)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Intermittent CNFE when booting xts subsystem

The changes for https://issues.jboss.org/browse/WFLY-2565 revealed a problem with XTS subsystem accessing WS code that relies on a setup performed during WS subsystem boot. So we have yet another race condition (this time between the 2 subsystems boot).
This might possibly be solved either by introducing a new service and setting dependencies or by removing the need for such a setup in the code exercised by XTS.

{noformat}
^[[0m^[[31m16:00:09,783 ERROR [org.jboss.as.controller.management-operation] (ServerService Thread Pool -- 57) JBAS014612: Operation ("add") failed - address: ([("subsystem" => "xts")]): java.lang.ExceptionInInitializerError
        at org.jboss.as.webservices.publish.EndpointPublisherImpl.doPrepare(EndpointPublisherImpl.java:137)
        at org.jboss.as.webservices.service.EndpointDeployService.install(EndpointDeployService.java:95)
        at org.jboss.as.webservices.service.EndpointPublishService.createServiceBuilder(EndpointPublishService.java:115)
        at org.jboss.as.webservices.service.EndpointPublishService.createServiceBuilder(EndpointPublishService.java:109)
        at org.jboss.as.xts.XTSSubsystemAdd.performBoottime(XTSSubsystemAdd.java:197)
        at org.jboss.as.controller.AbstractBoottimeAddStepHandler.performRuntime(AbstractBoottimeAddStepHandler.java:69) [wildfly-controller-8.0.0.Beta2-SNAPSHOT.jar:8.0.0.Beta2-SNAPSHOT]
        at org.jboss.as.controller.AbstractAddStepHandler$1.execute(AbstractAddStepHandler.java:75) [wildfly-controller-8.0.0.Beta2-SNAPSHOT.jar:8.0.0.Beta2-SNAPSHOT]
        at org.jboss.as.controller.AbstractOperationContext.executeStep(AbstractOperationContext.java:592) [wildfly-controller-8.0.0.Beta2-SNAPSHOT.jar:8.0.0.Beta2-SNAPSHOT]
        at org.jboss.as.controller.AbstractOperationContext.doCompleteStep(AbstractOperationContext.java:470) [wildfly-controller-8.0.0.Beta2-SNAPSHOT.jar:8.0.0.Beta2-SNAPSHOT]
        at org.jboss.as.controller.AbstractOperationContext.completeStepInternal(AbstractOperationContext.java:274) [wildfly-controller-8.0.0.Beta2-SNAPSHOT.jar:8.0.0.Beta2-SNAPSHOT]
        at org.jboss.as.controller.AbstractOperationContext.executeOperation(AbstractOperationContext.java:269) [wildfly-controller-8.0.0.Beta2-SNAPSHOT.jar:8.0.0.Beta2-SNAPSHOT]
        at org.jboss.as.controller.ParallelBootOperationStepHandler$ParallelBootTask.run(ParallelBootOperationStepHandler.java:343) [wildfly-controller-8.0.0.Beta2-SNAPSHOT.jar:8.0.0.Beta2-SNAPSHOT]
        at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1110) [rt.jar:1.7.0_09]
        at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:603) [rt.jar:1.7.0_09]
        at java.lang.Thread.run(Thread.java:722) [rt.jar:1.7.0_09]
        at org.jboss.threads.JBossThread.run(JBossThread.java:122) [jboss-threads-2.1.1.Final.jar:2.1.1.Final]
Caused by: java.lang.IllegalStateException: JBWS020000: Failed to load org.jboss.ws.common.spi.DefaultSPIProviderResolver
        at org.jboss.ws.api.util.ServiceLoader.loadDefault(ServiceLoader.java:274)
        at org.jboss.ws.api.util.ServiceLoader.loadFromSystemProperty(ServiceLoader.java:217)
        at org.jboss.ws.api.util.ServiceLoader.loadService(ServiceLoader.java:106)
        at org.jboss.wsf.spi.SPIProviderResolver.getInstance(SPIProviderResolver.java:53)
        at org.jboss.wsf.spi.SPIProviderResolver.getInstance(SPIProviderResolver.java:43)
        at org.jboss.as.webservices.deployers.deployment.AbstractDeploymentModelBuilder.<init>(AbstractDeploymentModelBuilder.java:78)
        at org.jboss.as.webservices.deployers.deployment.DeploymentModelBuilderJAXWS_POJO.<init>(DeploymentModelBuilderJAXWS_POJO.java:43)
        at org.jboss.as.webservices.deployers.deployment.WSDeploymentBuilder.<clinit>(WSDeploymentBuilder.java:42)
        ... 16 more
Caused by: java.lang.ClassNotFoundException: org.jboss.ws.common.spi.DefaultSPIProviderResolver from [Module "org.jboss.as.controller:main" from local module loader @3a6e15 (finder: local module finder @1145a4 (roots: /home/hudson/gytis/narayana/jboss-as/build/target/wildfly-8.0.0.Beta2-SNAPSHOT/modules,/home/hudson/gytis/narayana/jboss-as/build/target/wildfly-8.0.0.Beta2-SNAPSHOT/modules/system/layers/base))]
        at org.jboss.modules.ModuleClassLoader.findClass(ModuleClassLoader.java:197) [jboss-modules.jar:1.3.0.Final]
        at org.jboss.modules.ConcurrentClassLoader.performLoadClassUnchecked(ConcurrentClassLoader.java:443) [jboss-modules.jar:1.3.0.Final]
        at org.jboss.modules.ConcurrentClassLoader.performLoadClassChecked(ConcurrentClassLoader.java:431) [jboss-modules.jar:1.3.0.Final]
        at org.jboss.modules.ConcurrentClassLoader.performLoadClass(ConcurrentClassLoader.java:373) [jboss-modules.jar:1.3.0.Final]
        at org.jboss.modules.ConcurrentClassLoader.loadClass(ConcurrentClassLoader.java:118) [jboss-modules.jar:1.3.0.Final]
        at org.jboss.ws.api.util.SecurityActions.loadClass(SecurityActions.java:123)
        at org.jboss.ws.api.util.ServiceLoader.loadDefault(ServiceLoader.java:269)
        ... 23 more
{noformat}
```

## Fix commit message(s)

`7454d230788b`

```
[WFLY-2582] Always use webservices module classloader for building up DeploymentModelBuilder
```

## Files the fix changed

Snapshot holds 4,928 non-test source files. The fix changed 1 file(s); 1 of them are non-test source files (listed below as gold).

- `webservices/server-integration/src/main/java/org/jboss/as/webservices/deployers/deployment/AbstractDeploymentModelBuilder.java`

## The fix diff

### `webservices/server-integration/src/main/java/org/jboss/as/webservices/deployers/deployment/AbstractDeploymentModelBuilder.java`

```diff
diff --git a/webservices/server-integration/src/main/java/org/jboss/as/webservices/deployers/deployment/AbstractDeploymentModelBuilder.java b/webservices/server-integration/src/main/java/org/jboss/as/webservices/deployers/deployment/AbstractDeploymentModelBuilder.java
index 5b4991b7b3..52afbc8660 100644
--- a/webservices/server-integration/src/main/java/org/jboss/as/webservices/deployers/deployment/AbstractDeploymentModelBuilder.java
+++ b/webservices/server-integration/src/main/java/org/jboss/as/webservices/deployers/deployment/AbstractDeploymentModelBuilder.java
@@ -73,12 +73,13 @@ abstract class AbstractDeploymentModelBuilder implements DeploymentModelBuilder
     /**
      * Constructor.
      */
     protected AbstractDeploymentModelBuilder(final DeploymentType deploymentType, final EndpointType endpointType) {
         // deployment factory
-        final SPIProvider spiProvider = SPIProviderResolver.getInstance().getProvider();
-        this.deploymentModelFactory = spiProvider.getSPI(DeploymentModelFactory.class);
+        final ClassLoader cl = AbstractDeploymentModelBuilder.class.getClassLoader();
+        final SPIProvider spiProvider = SPIProviderResolver.getInstance(cl).getProvider();
+        this.deploymentModelFactory = spiProvider.getSPI(DeploymentModelFactory.class, cl);
         this.deploymentType = deploymentType;
         this.endpointType = endpointType;
     }
 
     /**
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
