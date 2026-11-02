# Annotation packet: PIG-1871  (pig)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Dont throw exception if partition filters  cannot be pushed up. 

Instead don't try to push partition filters up and continue execution.
```

## Fix commit message(s)

`67afa4fc1a54`

```
PIG-1871: Dont throw exception if partition filters cannot be pushed up.

git-svn-id: https://svn.apache.org/repos/asf/pig/trunk@1094671 13f79535-47bb-0310-9956-ffa450edef68
```

## Files the fix changed

Snapshot holds 1,051 non-test source files. The fix changed 4 file(s); 2 of them are non-test source files (listed below as gold).

- `src/org/apache/pig/newplan/PColFilterExtractor.java`
- `src/org/apache/pig/newplan/logical/rules/PartitionFilterOptimizer.java`

## The fix diff

### `src/org/apache/pig/newplan/PColFilterExtractor.java`

```diff
diff --git a/src/org/apache/pig/newplan/PColFilterExtractor.java b/src/org/apache/pig/newplan/PColFilterExtractor.java
index f0b2cd74..7e8c1ec3 100644
--- a/src/org/apache/pig/newplan/PColFilterExtractor.java
+++ b/src/org/apache/pig/newplan/PColFilterExtractor.java
@@ -20,10 +20,12 @@ package org.apache.pig.newplan;
 
 import java.io.IOException;
 import java.util.ArrayList;
 import java.util.List;
 
+import org.apache.commons.logging.Log;
+import org.apache.commons.logging.LogFactory;
 import org.apache.pig.Expression;
 import org.apache.pig.PigException;
 import org.apache.pig.impl.logicalLayer.FrontendException;
 import org.apache.pig.impl.util.Pair;
 
@@ -60,10 +62,13 @@ import org.apache.pig.newplan.DepthFirstWalker;
  * filter condition and extracts those conditions out of the filter condition.
  * The condition on partition cols will be used to prune partitions of the table.
  *
  */
 public class PColFilterExtractor extends PlanVisitor {
+    
+    private static final Log LOG = LogFactory.getLog(PColFilterExtractor.class);
+    
 	/**
 	 * partition columns associated with the table
 	 * present in the load on which the filter whose
 	 * inner plan is being visited is applied
 	 */
@@ -86,11 +91,13 @@ public class PColFilterExtractor extends PlanVisitor {
 
 	private enum Side { LEFT, RIGHT, NONE };
 	private Side replaceSide = Side.NONE;
 
 	private boolean filterRemovable = false;
-
+	
+    private boolean canPushDown = true;
+	
 	@Override
 	public void visit() throws FrontendException {
 		// we will visit the leaf and it will recursively walk the plan
 		LogicalExpression leaf = (LogicalExpression)plan.getSources().get( 0 );
 		// if the leaf is a unary operator it should be a FilterFunc in 
@@ -134,56 +141,64 @@ public class PColFilterExtractor extends PlanVisitor {
 			// scan and removed from the filter condition. Hence the condition 
 			// on the partition column will not be re applied when data is read,
 			// so the following cases should throw error until that changes.
 			List<Class<?>> opsToCheckFor = new ArrayList<Class<?>>();
 			opsToCheckFor.add(RegexExpression.class);
-			int errCode = 1110;
 			if(checkSuccessors(project, opsToCheckFor)) {
-				throw new FrontendException("Unsupported query: " +
-						"You have an partition column (" 
-						+ fieldName + ") inside a regexp operator in the " +
-						"filter condition.", errCode, PigException.INPUT);
+            LOG.warn("No partition filter push down: " +
+                "You have an partition column (" 
+                + fieldName + ") inside a regexp operator in the " +
+                "filter condition.");
+            canPushDown = false;
+            return;
 			} 
 			opsToCheckFor.set(0, UserFuncExpression.class);
 			if(checkSuccessors(project, opsToCheckFor)) {
-				throw new FrontendException("Unsupported query: " +
-						"You have an partition column (" 
-						+ fieldName + ") inside a function in the " +
-						"filter condition.", errCode, PigException.INPUT);
+            LOG.warn("No partition filter push down: " +
+                "You have an partition column (" 
+                + fieldName + ") inside a function in the " +
+                "filter condition.");
+            canPushDown = false;
+            return;
 			}
 			opsToCheckFor.set(0, CastExpression.class);
 			if(checkSuccessors(project, opsToCheckFor)) {
-				throw new FrontendException("Unsupported query: " +
-						"You have an partition column (" 
-						+ fieldName + ") inside a cast in the " +
-						"filter condition.", errCode, PigException.INPUT);
+            LOG.warn("No partition filter push down: " +
+                "You have an partition column (" 
+                + fieldName + ") inside a cast in the " +
+                "filter condition.");
+            canPushDown = false;
+            return;
 			}
-
 			opsToCheckFor.set(0, IsNullExpression.class);
 			if(checkSuccessors(project, opsToCheckFor)) {
-				throw new FrontendException("Unsupported query: " +
-						"You have an partition column (" 
-						+ fieldName + ") inside a null check operator in the " +
-						"filter condition.", errCode, PigException.INPUT);
+            LOG.warn("No partition filter push down: " +
+                "You have an partition column (" 
+                + fieldName + ") inside a null check operator in the " +
+                "filter condition.");
+            canPushDown = false;
+            return;
 			}
 			opsToCheckFor.set(0, BinCondExpression.class);
 			if(checkSuccessors(project, opsToCheckFor)) {
-				throw new FrontendException("Unsupported query: " +
-						"You have an partition column (" 
-						+ fieldName + ") inside a bincond operator in the " +
-						"filter condition.", errCode, PigException.INPUT);
+            LOG.warn("No partition filter push down: " +
+                "You have an partition column (" 
+                + fieldName + ") inside a bincond operator in the " +
+                "filter condition.");
+            canPushDown = false;
+            return;
 			}
 			opsToCheckFor.set(0, AndExpression.class);
 			opsToCheckFor.add(OrExpression.class);
 			if(checkSuccessors(project, opsToCheckFor)) {
-				errCode = 1112;
-				throw new FrontendException("Unsupported query: " +
-						"You have an partition column (" + fieldName +
-						" ) in a construction like: " +
-						"(pcond  and ...) or (pcond and ...) " +
-						"where pcond is a condition on a partition column.",
-						errCode, PigException.INPUT);
+            LOG.warn("No partition filter push down: " +
+                "You have an partition column (" + fieldName +
+                " ) in a construction like: " +
+                "(pcond  and ...) or (pcond and ...) " +
+                "where pcond is a condition on a partition column.");
+            canPushDown = false;
+            return;
 			}
 		} else {
 			sawNonKeyCol = true;
 		}
 	}
@@ -220,15 +235,15 @@ public class PColFilterExtractor extends PlanVisitor {
 				replaceSide = Side.LEFT;
 			}else if(rhsSawKey && lhsSawNonKeyCol){
 				replaceSide = Side.RIGHT;
 			}
 		} else if(lhsSawKey && rhsSawNonKeyCol || rhsSawKey && lhsSawNonKeyCol){
-			int errCode = 1111;
-			String errMsg = "Use of partition column/condition with" +
-			" non partition column/condition in filter expression is not " +
-			"supported." ;
-			throw new FrontendException(errMsg, errCode, PigException.INPUT);
+        LOG.warn("No partition filter push down: " +
+            "Use of partition column/condition with" +
+            " non partition column/condition in filter expression is not " +
+            "supported.");
+        canPushDown = false;
 		}
 
 		sawKey = lhsSawKey || rhsSawKey;
 		sawNonKeyCol = lhsSawNonKeyCol || rhsSawNonKeyCol;
 	}
@@ -237,12 +252,12 @@ public class PColFilterExtractor extends PlanVisitor {
 
 	/**
 	 * @return the condition on partition columns extracted from filter
 	 */
 	public  Expression getPColCondition(){
-		if(pColConditions.size() == 0)
-			return null;
+    if(!canPushDown || pColConditions.size() == 0)
+        return null;
 		Expression cond =  pColConditions.get(0);
 		for(int i=1; i<pColConditions.size(); i++){
 			//if there is more than one condition expression
 			// connect them using "AND"s
 			cond = new Expression.BinaryExpression(cond, pColConditions.get(i),
@@ -253,11 +268,11 @@ public class PColFilterExtractor extends PlanVisitor {
 
 	/**
 	 * @return the filterRemovable
 	 */
 	public boolean isFilterRemovable() {
-		return filterRemovable;
+    return canPushDown && filterRemovable;
 	}
 
 	//////// helper methods /////////////////////////
 	/**
 	 * check for the presence of a certain operator type in the Successors
@@ -297,11 +312,11 @@ public class PColFilterExtractor extends PlanVisitor {
 				if(opsToCheckFor.isEmpty()) {
 					return true; //no further checks required
 				}
 			}
 		} else {
-			throwException();
+		    logInternalErrorAndSetFlag();
 		}
 		return false; // more checking can be done
 	}
 
 	private void replaceChild(LogicalExpression childExpr) throws FrontendException {
@@ -323,11 +338,12 @@ public class PColFilterExtractor extends PlanVisitor {
 		//  binexpop
 		//  /
 		// Rt
 
 		if( !( childExpr instanceof BinaryExpression ) ) {
-			throwException();
+		     logInternalErrorAndSetFlag();
+	         return;
 		}
 		// child's lhs operand
 		LogicalExpression leftChild = 
 			((BinaryExpression)childExpr).getLhs();
 		// child's rhs operand
@@ -344,11 +360,12 @@ public class PColFilterExtractor extends PlanVisitor {
 		} else if(replaceSide == Side.RIGHT){
 			// remove right child and replace childExpr with its left child
 			remove(rightChild);
 			replace(childExpr, leftChild);
 		}else {
-			throwException();
+		     logInternalErrorAndSetFlag();
+	         return;
 		}
 		//reset 
 		replaceSide = Side.NONE;
 		sawKey = false;
 
@@ -401,22 +418,23 @@ public class PColFilterExtractor extends PlanVisitor {
 		}
 		
 		plan.remove( op );
 	}
 
-	public static Expression getExpression(LogicalExpression op) throws FrontendException
+	public Expression getExpression(LogicalExpression op) throws FrontendException
 	 {
 		if(op instanceof ConstantExpression) {
 			ConstantExpression constExpr =(ConstantExpression)op ;
 			return new Expression.Const( constExpr.getValue() );
 		} else if (op instanceof ProjectExpression) {
 			ProjectExpression projExpr = (ProjectExpression)op;
 			String fieldName = projExpr.getFieldSchema().alias;
             return new Expression.Column(fieldName);
         } else {
 			if( !( op instanceof BinaryExpression ) ) {
-				throwException();
+            logInternalErrorAndSetFlag();
+            return null;
 			}
 			BinaryExpression binOp = (BinaryExpression)op;
 			if(binOp instanceof AddExpression) {
 				return getExpression( binOp, OpType.OP_PLUS );
 			} else if(binOp instanceof SubtractExpression) {
@@ -442,30 +460,28 @@ public class PColFilterExtractor extends PlanVisitor {
 			} else if(binOp instanceof LessThanExpression) {
 				return getExpression(binOp, OpType.OP_LT);
 			} else if(binOp instanceof LessThanEqualExpression) {
 				return getExpression(binOp, OpType.OP_LE);
 			} else {
-				throwException();
+            logInternalErrorAndSetFlag();
 			}
 		}
 		return null;
 	}
 
-    private static Expression getExpression(BinaryExpression binOp, OpType 
+    private Expression getExpression(BinaryExpression binOp, OpType 
             opType) throws FrontendException {
         return new Expression.BinaryExpression(getExpression(binOp.getLhs())
                 ,getExpression(binOp.getRhs()), opType);
     }
-	private static void throwException() throws FrontendException {
-		int errCode = 2209;
-		throw new FrontendException(
-				"Internal error while processing any partition filter " +
-				"conditions in the filter after the load" ,
-				errCode,
-				PigException.BUG
-		);
-	}
+    
+    private void logInternalErrorAndSetFlag() throws FrontendException {
+        LOG.warn("No partition filter push down: "
+                + "Internal error while processing any partition filter "
+                + "conditions in the filter after the load");
+        canPushDown = false;
+    }
 
 	// this might get called from some visit() - in that case, delegate to
 	// the other visit()s which we have defined here 
 	private void visit(LogicalExpression op) throws FrontendException {
 		if(op instanceof ProjectExpression) {
@@ -515,6 +531,10 @@ public class PColFilterExtractor extends PlanVisitor {
 
 	private void visit(IsNullExpression isNull) throws FrontendException {
 		visit(isNull.getExpression());
 	}
 
+    public boolean canPushDown() {
+        return canPushDown;
+    }
+
 }
```

### `src/org/apache/pig/newplan/logical/rules/PartitionFilterOptimizer.java`

```diff
diff --git a/src/org/apache/pig/newplan/logical/rules/PartitionFilterOptimizer.java b/src/org/apache/pig/newplan/logical/rules/PartitionFilterOptimizer.java
index 819b5724..898f59e5 100644
--- a/src/org/apache/pig/newplan/logical/rules/PartitionFilterOptimizer.java
+++ b/src/org/apache/pig/newplan/logical/rules/PartitionFilterOptimizer.java
@@ -28,23 +28,23 @@ import org.apache.hadoop.mapreduce.Job;
 import org.apache.pig.Expression;
 import org.apache.pig.LoadFunc;
 import org.apache.pig.LoadMetadata;
 import org.apache.pig.Expression.BinaryExpression;
 import org.apache.pig.Expression.Column;
+import org.apache.pig.impl.logicalLayer.FrontendException;
+import org.apache.pig.newplan.Operator;
+import org.apache.pig.newplan.OperatorPlan;
+import org.apache.pig.newplan.OperatorSubPlan;
+import org.apache.pig.newplan.PColFilterExtractor;
+import org.apache.pig.newplan.logical.expression.LogicalExpressionPlan;
 import org.apache.pig.newplan.logical.relational.LOFilter;
 import org.apache.pig.newplan.logical.relational.LOLoad;
 import org.apache.pig.newplan.logical.relational.LogicalPlan;
 import org.apache.pig.newplan.logical.relational.LogicalRelationalOperator;
 import org.apache.pig.newplan.logical.relational.LogicalSchema;
-import org.apache.pig.newplan.Operator;
-import org.apache.pig.newplan.OperatorPlan;
-import org.apache.pig.newplan.OperatorSubPlan;
-import org.apache.pig.newplan.PColFilterExtractor;
 import org.apache.pig.newplan.optimizer.Rule;
 import org.apache.pig.newplan.optimizer.Transformer;
-import org.apache.pig.impl.logicalLayer.FrontendException;
-import org.apache.pig.impl.util.Pair;
 
 public class PartitionFilterOptimizer extends Rule {
     private String[] partitionKeys;
     
     /**
@@ -145,14 +145,23 @@ public class PartitionFilterOptimizer extends Rule {
         @Override
         public void transform(OperatorPlan matched) throws FrontendException {
         	subPlan = new OperatorSubPlan( currentPlan );
 
         	setupColNameMaps();
+        	
+        	// PIG-1871: Don't throw exception if partition filters cannot be pushed up. 
+        	// Perform transformation on a copy of the filter plan, and replace the 
+        	// original filter plan only if the transformation is successful 
+        	// (i.e. partition filter can be pushed down) 
+        	LogicalExpressionPlan filterExpr = loFilter.getFilterPlan();
+        	LogicalExpressionPlan filterExprCopy = filterExpr.deepCopy();
+        	
         	PColFilterExtractor pColFilterFinder = new PColFilterExtractor(
-        			loFilter.getFilterPlan(), getMappedKeys( partitionKeys ) );
+        	        filterExprCopy, getMappedKeys( partitionKeys ) );
         	pColFilterFinder.visit();
         	Expression partitionFilter = pColFilterFinder.getPColCondition();
+        	
         	if(partitionFilter != null) {
         		// the column names in the filter may be the ones provided by
         		// the user in the schema in the load statement - we may need
         		// to replace them with partition column names as given by
         		// LoadFunc.getSchema()
@@ -162,10 +171,12 @@ public class PartitionFilterOptimizer extends Rule {
 				} catch (IOException e) {
 					throw new FrontendException( e );
 				}
         		if(pColFilterFinder.isFilterRemovable()) {  
         			currentPlan.removeAndReconnect( loFilter );
+        		} else {
+        		    loFilter.setFilterPlan(filterExprCopy);
         		}
         	}
         }
         
         private void updateMappedColNames(Expression expr) {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
