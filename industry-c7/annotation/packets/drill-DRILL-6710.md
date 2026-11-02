# Annotation packet: DRILL-6710  (drill)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Disallow negative scale for VarDecimal

Query is:
select cast('999999999999999999' as decimal(18,0)) + cast('9999999999999999999999999999999999999' as decimal(38,0)) from data limit 1

This is the error I get when my test program calls SQLExecDirect:

The driver reported the following diagnostics whilst running SQLExecDirect

HY000:1:40140:[MapR][Support] (40140) Scale can't be less than zero.
```

## Fix commit message(s)

`fa0d78d16eaf`

```
DRILL-6710: Disallow negative scale for decimal data type
```

## Files the fix changed

Snapshot holds 2,518 non-test source files. The fix changed 13 file(s); 9 of them are non-test source files (listed below as gold).

- `exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions1.java`
- `exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions3.java`
- `exec/java-exec/src/main/codegen/templates/Decimal/DecimalFunctions.java`
- `exec/java-exec/src/main/java/org/apache/drill/exec/expr/fn/output/DecimalReturnTypeInference.java`
- `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionAddFunction.java`
- `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionDivideFunction.java`
- `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionModFunction.java`
- `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionMulFunction.java`
- `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DrillBaseComputeScalePrecision.java`

## The fix diff

### `exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions1.java`

```diff
diff --git a/exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions1.java b/exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions1.java
index 7f4ca154c..083a3cdd3 100644
--- a/exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions1.java
+++ b/exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions1.java
@@ -90,22 +90,23 @@ public class Decimal${aggrtype.className}Functions {
           .getBigDecimalFromDrillBuf(in.buffer, in.start, in.end - in.start, in.scale);
       value.obj = ((java.math.BigDecimal) value.obj).add(currentValue);
       if (outputScale.value == Integer.MIN_VALUE) {
         outputScale.value = in.scale;
       }
+      org.apache.drill.exec.util.DecimalUtility.checkValueOverflow((java.math.BigDecimal) value.obj,
+          org.apache.drill.exec.planner.types.DrillRelDataTypeSystem.DRILL_REL_DATATYPE_SYSTEM.getMaxNumericPrecision(), outputScale.value);
       <#if type.inputType?starts_with("Nullable")>
       } // end of sout block
       </#if>
     }
 
     @Override
     public void output() {
       if (nonNullCount.value > 0) {
         out.isSet = 1;
         out.start  = 0;
-        out.scale = Math.min(outputScale.value,
-            org.apache.drill.exec.planner.types.DrillRelDataTypeSystem.DRILL_REL_DATATYPE_SYSTEM.getMaxNumericScale());
+        out.scale = outputScale.value;
         out.precision =
             org.apache.drill.exec.planner.types.DrillRelDataTypeSystem.DRILL_REL_DATATYPE_SYSTEM.getMaxNumericPrecision();
         value.obj = ((java.math.BigDecimal) value.obj).setScale(out.scale, java.math.BigDecimal.ROUND_HALF_UP);
         byte[] bytes = ((java.math.BigDecimal) value.obj).unscaledValue().toByteArray();
         int len = bytes.length;
```

### `exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions3.java`

```diff
diff --git a/exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions3.java b/exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions3.java
index 3058381d9..211bab9ba 100644
--- a/exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions3.java
+++ b/exec/java-exec/src/main/codegen/templates/Decimal/DecimalAggrTypeFunctions3.java
@@ -153,10 +153,11 @@ public class Decimal${aggrtype.className}Functions {
       </#if>
           out.scale = scale.value;
           result = result.setScale(out.scale, java.math.RoundingMode.HALF_UP);
           out.start  = 0;
           out.precision = org.apache.drill.exec.planner.types.DrillRelDataTypeSystem.DRILL_REL_DATATYPE_SYSTEM.getMaxNumericPrecision();
+          org.apache.drill.exec.util.DecimalUtility.checkValueOverflow(result, out.precision, out.scale);
           byte[] bytes = result.unscaledValue().toByteArray();
           int len = bytes.length;
           out.buffer = buffer.reallocIfNeeded(len);
           out.buffer.setBytes(0, bytes);
           out.end = len;
```

### `exec/java-exec/src/main/codegen/templates/Decimal/DecimalFunctions.java`

```diff
diff --git a/exec/java-exec/src/main/codegen/templates/Decimal/DecimalFunctions.java b/exec/java-exec/src/main/codegen/templates/Decimal/DecimalFunctions.java
index da18cb11f..9b055f1be 100644
--- a/exec/java-exec/src/main/codegen/templates/Decimal/DecimalFunctions.java
+++ b/exec/java-exec/src/main/codegen/templates/Decimal/DecimalFunctions.java
@@ -181,10 +181,12 @@ public class ${type.name}Functions {
         leftInput.remainder(rightInput,
       </#if>
               new java.math.MathContext(result.precision, java.math.RoundingMode.HALF_UP))
             .setScale(result.scale, java.math.BigDecimal.ROUND_HALF_UP);
 
+      org.apache.drill.exec.util.DecimalUtility.checkValueOverflow(opResult, result.precision, result.scale);
+
       byte[] bytes = opResult.unscaledValue().toByteArray();
       int len = bytes.length;
       result.buffer = buffer.reallocIfNeeded(len);
       result.buffer.setBytes(0, bytes);
       result.end = len;
@@ -283,11 +285,11 @@ public class ${type.name}Functions {
     public void setup() {
     }
 
     public void eval() {
       result.start = 0;
-      result.scale = right.value;
+      result.scale = Math.max(right.value, 0);
       result.precision = left.precision;
       java.math.BigDecimal opResult =
           org.apache.drill.exec.util.DecimalUtility
               .getBigDecimalFromDrillBuf(left.buffer, left.start, left.end - left.start, left.scale)
                   .setScale(result.scale, java.math.BigDecimal.ROUND_DOWN);
@@ -311,11 +313,11 @@ public class ${type.name}Functions {
 
     public void setup() {
     }
 
     public void eval() {
-      result.scale = right.value;
+      result.scale = Math.max(right.value, 0);
       result.precision = left.precision;
       result.start = 0;
       java.math.BigDecimal bd =
           org.apache.drill.exec.util.DecimalUtility
               .getBigDecimalFromDrillBuf(left.buffer, left.start, left.end - left.start, left.scale)
```

### `exec/java-exec/src/main/java/org/apache/drill/exec/expr/fn/output/DecimalReturnTypeInference.java`

```diff
diff --git a/exec/java-exec/src/main/java/org/apache/drill/exec/expr/fn/output/DecimalReturnTypeInference.java b/exec/java-exec/src/main/java/org/apache/drill/exec/expr/fn/output/DecimalReturnTypeInference.java
index 442514f79..b30703d7b 100644
--- a/exec/java-exec/src/main/java/org/apache/drill/exec/expr/fn/output/DecimalReturnTypeInference.java
+++ b/exec/java-exec/src/main/java/org/apache/drill/exec/expr/fn/output/DecimalReturnTypeInference.java
@@ -275,11 +275,11 @@ public class DecimalReturnTypeInference {
         scale = ((ValueExpressions.IntExpression) logicalExpressions.get(1)).getInt();
       }
 
       return TypeProtos.MajorType.newBuilder()
           .setMinorType(attributes.getReturnValue().getType().getMinorType())
-          .setScale(scale)
+          .setScale(Math.max(scale, 0))
           .setPrecision(precision)
           .setMode(mode)
           .build();
     }
   }
```

### `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionAddFunction.java`

```diff
diff --git a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionAddFunction.java b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionAddFunction.java
index 138f97f63..db00c51a9 100644
--- a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionAddFunction.java
+++ b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionAddFunction.java
@@ -29,8 +29,8 @@ public class DecimalScalePrecisionAddFunction extends DrillBaseComputeScalePreci
     outputScale = Math.max(leftScale, rightScale);
     int maxResultIntegerDigits = Math.max((leftPrecision - leftScale), (rightPrecision - rightScale)) + 1;
 
     outputPrecision = (outputScale + maxResultIntegerDigits);
 
-    checkPrecisionRange();
+    adjustScaleAndPrecision();
   }
 }
```

### `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionDivideFunction.java`

```diff
diff --git a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionDivideFunction.java b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionDivideFunction.java
index eb79d44ae..af04f2bc8 100644
--- a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionDivideFunction.java
+++ b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionDivideFunction.java
@@ -32,7 +32,8 @@ public class DecimalScalePrecisionDivideFunction extends DrillBaseComputeScalePr
     int maxResultIntegerDigits = Math.min(leftPrecision - leftScale + rightScale, MAX_NUMERIC_PRECISION);
     outputScale = Math.max(6, leftScale + rightPrecision + 1);
     outputScale = Math.min(outputScale, MAX_NUMERIC_PRECISION - maxResultIntegerDigits);
     outputScale = Math.min(outputScale, DRILL_REL_DATATYPE_SYSTEM.getMaxNumericScale());
     outputPrecision = maxResultIntegerDigits + outputScale;
+    adjustScaleAndPrecision();
   }
 }
```

### `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionModFunction.java`

```diff
diff --git a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionModFunction.java b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionModFunction.java
index 6901580eb..9508f3d4e 100644
--- a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionModFunction.java
+++ b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionModFunction.java
@@ -36,9 +36,9 @@ public class DecimalScalePrecisionModFunction extends DrillBaseComputeScalePreci
 
     if (outputScale + leftIntegerDigits > outputPrecision) {
       outputScale = outputPrecision - leftIntegerDigits;
     }
 
-    // Output precision should atleast be greater or equal to the input precision
-    outputPrecision = Math.max(outputPrecision, Math.max(leftPrecision, rightPrecision));
+    // Output precision should at least be greater or equal to the input precision
+    outputPrecision = Math.min(outputPrecision, Math.max(leftPrecision, rightPrecision));
   }
 }
```

### `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionMulFunction.java`

```diff
diff --git a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionMulFunction.java b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionMulFunction.java
index 2a8b22b9d..6cc553707 100644
--- a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionMulFunction.java
+++ b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DecimalScalePrecisionMulFunction.java
@@ -30,12 +30,11 @@ public class DecimalScalePrecisionMulFunction extends DrillBaseComputeScalePreci
 
   @Override
   public void computeScalePrecision(int leftPrecision, int leftScale, int rightPrecision, int rightScale) {
     // compute the output scale and precision here
     outputScale = leftScale + rightScale;
-
     outputPrecision = leftPrecision + rightPrecision;
 
-    checkPrecisionRange();
+    adjustScaleAndPrecision();
   }
 }
```

### `exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DrillBaseComputeScalePrecision.java`

```diff
diff --git a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DrillBaseComputeScalePrecision.java b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DrillBaseComputeScalePrecision.java
index 1c3c18667..af671e01b 100644
--- a/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DrillBaseComputeScalePrecision.java
+++ b/exec/java-exec/src/main/java/org/apache/drill/exec/planner/types/decimal/DrillBaseComputeScalePrecision.java
@@ -15,13 +15,18 @@
  * See the License for the specific language governing permissions and
  * limitations under the License.
  */
 package org.apache.drill.exec.planner.types.decimal;
 
+import org.slf4j.Logger;
+import org.slf4j.LoggerFactory;
+
 import static org.apache.drill.exec.planner.types.DrillRelDataTypeSystem.DRILL_REL_DATATYPE_SYSTEM;
 
 public abstract class DrillBaseComputeScalePrecision {
+  private static final Logger logger = LoggerFactory.getLogger(DrillBaseComputeScalePrecision.class);
+
   protected final static int MAX_NUMERIC_PRECISION = DRILL_REL_DATATYPE_SYSTEM.getMaxNumericPrecision();
 
   protected int outputScale = 0;
   protected int outputPrecision = 0;
 
@@ -41,12 +46,18 @@ public abstract class DrillBaseComputeScalePrecision {
 
   /**
    * Cuts down the fractional part if the current precision
    * exceeds the maximum precision range.
    */
-  protected void checkPrecisionRange() {
+  protected void adjustScaleAndPrecision() {
     if (outputPrecision > MAX_NUMERIC_PRECISION) {
       outputScale = outputScale - (outputPrecision - MAX_NUMERIC_PRECISION);
       outputPrecision = MAX_NUMERIC_PRECISION;
     }
+    if (outputScale < 0) {
+      logger.warn("Resulting precision: {} may overflow max allowed precision: {}.\n" +
+          "Forced setting max allowed precision and 0 scale.",
+          MAX_NUMERIC_PRECISION - outputScale, MAX_NUMERIC_PRECISION);
+      outputScale = 0;
+    }
   }
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
