# Annotation packet: DERBY-2218  (derby)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Null Pointer Exception when an untyped NULL subquery ("values null") appears outside of the FROM list in a SELECT query.

If a SELECT query contains a subquery which includes an untyped NULL value at any place other than in the FROM list, Derby will throw an NPE at bind time.

ij> create table t1 (i int);
0 rows inserted/updated/deleted

-- If the untyped NULL is in the FROM list, a reasonable error is thrown.

ij> select * from (values null) x;
ERROR 42X07: Null is only allowed in a VALUES clause within an INSERT statement.

ij> select * from (select * from t1, (values null) x )y;
ERROR 42X07: Null is only allowed in a VALUES clause within an INSERT statement.

-- But if it appears anywhere else, the result is an NPE:

-- IN-list
ij> select * from t1 where i in (1, 2, (values null));
ERROR XJ001: Java exception: ': java.lang.NullPointerException'.

-- where clause
select * from t1 where (values null);

-- order by clause
select * from t1 order by (values null);

-- result column
select (values null) from t1;

-- group by clause (only works in 10.2 and later)
select * from t1 group by (values null);

-- having clause
select * from t1 group by i having (values null);

Stack trace (from 10.2.2) is:

java.lang.NullPointerException
	at org.apache.derby.impl.sql.compile.SubqueryNode.setDataTypeServices(SubqueryNode.java:2289)
	at org.apache.derby.impl.sql.compile.SubqueryNode.bindExpression(SubqueryNode.java:529)
	at org.apache.derby.impl.sql.compile.ValueNodeList.bindExpression(ValueNodeList.java:130)
	at org.apache.derby.impl.sql.compile.BinaryListOperatorNode.bindExpression(BinaryListOperatorNode.java:161)
	at org.apache.derby.impl.sql.compile.SelectNode.bindExpressions(SelectNode.java:540)
	at org.apache.derby.impl.sql.compile.DMLStatementNode.bindExpressions(DMLStatementNode.java:249)
	at org.apache.derby.impl.sql.compile.DMLStatementNode.bind(DMLStatementNode.java:162)
	at org.apache.derby.impl.sql.compile.CursorNode.bind(CursorNode.java:253)
	at org.apache.derby.impl.sql.GenericStatement.prepMinion(GenericStatement.java:345)
	at org.apache.derby.impl.sql.GenericStatement.prepare(GenericStatement.java:119)
```

## Fix commit message(s)

`a18352f76435`

```
DERBY-2218: Patch to catch untyped null in SubqueryNode at bind phase.

Contributed by Yip Ng (yipng168@gmail.com) 


git-svn-id: https://svn.apache.org/repos/asf/db/derby/code/trunk@498004 13f79535-47bb-0310-9956-ffa450edef68
```

`4a2cd3ce3276`

```
DERBY-2218: Follow-up patch for additional tests plus removal of an unneeded call to bindResultColumns in SubqueryNode.

Contributed by Yip Ng (yipng168@gmail.com)


git-svn-id: https://svn.apache.org/repos/asf/db/derby/code/trunk@498689 13f79535-47bb-0310-9956-ffa450edef68
```

## Files the fix changed

Snapshot holds 1,574 non-test source files. The fix changed 5 file(s); 1 of them are non-test source files (listed below as gold).

- `java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java`

## The fix diff

### `java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java`

```diff
--- from commit a18352f76435 ---
diff --git a/java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java b/java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java
index fbbfd8741..ae1c14e33 100644
--- a/java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java
+++ b/java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java
@@ -487,10 +487,18 @@ public class SubqueryNode extends ValueNode
 		if (subqueryType == EXISTS_SUBQUERY)
 		{
 			/* Bind the expression in the SELECT list */
 			resultSet.bindTargetExpressions(fromList);
 
+			resultSet.bindResultColumns(fromList);
+
+			/* 
+			 * reject any untyped nulls in the EXISTS subquery before 
+			 * SELECT TRUE transformation. 
+			 */
+			resultSet.bindUntypedNullsToResultColumns(null);
+	        
 			/* Transform the ResultColumn into true.
 			 * NOTE: This may be a 2nd instance of the same transformation for
 			 * an EXISTS (select * ...), since we had to transform the 
 			 * AllResultColumn above, but we have to also handle
 			 * EXISTS (select r from s ...)
@@ -508,10 +516,13 @@ public class SubqueryNode extends ValueNode
 		/* bind the expressions in the underlying subquery */
 		resultSet.bindExpressions(fromList);
 
 		resultSet.bindResultColumns(fromList);
 
+		/* reject any untyped nulls in the subquery */
+		resultSet.bindUntypedNullsToResultColumns(null);
+        
 		/* We need to reset resultColumns since the underlying resultSet may
 		 * be a UNION (and UnionNode.bindResultColumns() regens a new RCL).
 		 */
 		resultColumns = resultSet.getResultColumns();
--- from commit 4a2cd3ce3276 ---
diff --git a/java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java b/java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java
index ae1c14e33..a7af1fabf 100644
--- a/java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java
+++ b/java/engine/org/apache/derby/impl/sql/compile/SubqueryNode.java
@@ -487,12 +487,10 @@ public class SubqueryNode extends ValueNode
 		if (subqueryType == EXISTS_SUBQUERY)
 		{
 			/* Bind the expression in the SELECT list */
 			resultSet.bindTargetExpressions(fromList);
 
-			resultSet.bindResultColumns(fromList);
-
 			/* 
 			 * reject any untyped nulls in the EXISTS subquery before 
 			 * SELECT TRUE transformation. 
 			 */
 			resultSet.bindUntypedNullsToResultColumns(null);
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
