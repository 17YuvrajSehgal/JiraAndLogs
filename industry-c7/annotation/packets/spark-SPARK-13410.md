# Annotation packet: SPARK-13410  (spark)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
unionAll AnalysisException with DataFrames containing UDT columns.

Unioning two DataFrames that contain UDTs fails with 
{quote}
AnalysisException: u"unresolved operator 'Union;"
{quote}

I tracked this down to this line https://github.com/apache/spark/blob/master/sql/catalyst/src/main/scala/org/apache/spark/sql/catalyst/plans/logical/basicOperators.scala#L202

Which compares datatypes between the output attributes of both logical plans. However for UDTs this will be a new instance of the UserDefinedType or PythonUserDefinedType https://github.com/apache/spark/blob/master/sql/catalyst/src/main/scala/org/apache/spark/sql/types/DataType.scala#L158 

So this equality check will check if the two instances are the same and since they aren't references to a singleton this check fails. 

*Note: this will work fine if you are unioning the dataframe with itself.*

I have a proposed patch for this which overrides the equality operator on the two classes here: https://github.com/apache/spark/pull/11279

Reproduction steps

{code}
from pyspark.sql.tests import PythonOnlyPoint, PythonOnlyUDT
from pyspark.sql import types

schema = types.StructType([types.StructField("point", PythonOnlyUDT(), True)])

#note they need to be two separate dataframes
a = sqlCtx.createDataFrame([[PythonOnlyPoint(1.0, 2.0)]], schema)
b = sqlCtx.createDataFrame([[PythonOnlyPoint(3.0, 4.0)]], schema)

c = a.unionAll(b)
{code}
```

## Fix commit message(s)

`0f90f4e6ac9e`

```
[SPARK-13410][SQL] Support unionAll for DataFrames with UDT columns.

## What changes were proposed in this pull request?

This PR adds equality operators to UDT classes so that they can be correctly tested for dataType equality during union operations.

This was previously causing `"AnalysisException: u"unresolved operator 'Union;""` when trying to unionAll two dataframes with UDT columns as below.

```
from pyspark.sql.tests import PythonOnlyPoint, PythonOnlyUDT
from pyspark.sql import types

schema = types.StructType([types.StructField("point", PythonOnlyUDT(), True)])

a = sqlCtx.createDataFrame([[PythonOnlyPoint(1.0, 2.0)]], schema)
b = sqlCtx.createDataFrame([[PythonOnlyPoint(3.0, 4.0)]], schema)

c = a.unionAll(b)
```

## How was the this patch tested?

Tested using two unit tests in sql/test.py and the DataFrameSuite.

Additional information here : https://issues.apache.org/jira/browse/SPARK-13410

Author: Franklyn D'souza <franklynd@gmail.com>

Closes #11279 from damnMeddlingKid/udt-union-all.
```

## Files the fix changed

Snapshot holds 1,829 non-test source files. The fix changed 4 file(s); 1 of them are non-test source files (listed below as gold).

- `sql/catalyst/src/main/scala/org/apache/spark/sql/types/UserDefinedType.scala`

## The fix diff

### `sql/catalyst/src/main/scala/org/apache/spark/sql/types/UserDefinedType.scala`

```diff
diff --git a/sql/catalyst/src/main/scala/org/apache/spark/sql/types/UserDefinedType.scala b/sql/catalyst/src/main/scala/org/apache/spark/sql/types/UserDefinedType.scala
index d7a2c23be8a..7664c30ee76 100644
--- a/sql/catalyst/src/main/scala/org/apache/spark/sql/types/UserDefinedType.scala
+++ b/sql/catalyst/src/main/scala/org/apache/spark/sql/types/UserDefinedType.scala
@@ -84,10 +84,15 @@ abstract class UserDefinedType[UserType] extends DataType with Serializable {
 
   override private[sql] def acceptsType(dataType: DataType) =
     this.getClass == dataType.getClass
 
   override def sql: String = sqlType.sql
+
+  override def equals(other: Any): Boolean = other match {
+    case that: UserDefinedType[_] => this.acceptsType(that)
+    case _ => false
+  }
 }
 
 /**
  * ::DeveloperApi::
  * The user defined type in Python.
@@ -110,6 +115,11 @@ private[sql] class PythonUserDefinedType(
     ("type" -> "udt") ~
       ("pyClass" -> pyUDT) ~
       ("serializedClass" -> serializedPyClass) ~
       ("sqlType" -> sqlType.jsonValue)
   }
+
+  override def equals(other: Any): Boolean = other match {
+    case that: PythonUserDefinedType => this.pyUDT.equals(that.pyUDT)
+    case _ => false
+  }
 }
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
