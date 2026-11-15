# Annotation packet: DERBY-4451  (derby)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
ArrayIndexOutOfBoundsException or ASSERT FAILED when inserting generated columns out of order

I see this error when I specify the columns in a different order than in the table definition. It only fails if a multi-row table constructor is used.

ij> create table t(a int, b generated always as (-a));
0 rows inserted/updated/deleted
ij> insert into t(b,a) values (default,1);
1 row inserted/updated/deleted
ij> insert into t(b,a) values (default,1), (default, 2);
ERROR XJ001: Java exception: '1 >= 1: java.lang.ArrayIndexOutOfBoundsException'.

And in a sane build:

ij> insert into t(b,a) values (default,1),(default,2);
ERROR XJ001: Java exception: 'ASSERT FAILED More columns in result column list than in base table: org.apache.derby.shared.common.sanity.AssertFailure'.

This bug may be similar to DERBY-4448, but the stack trace is different, and DERBY-4448 does not raise an ASSERT FAILED in sane builds.
```

## Fix commit message(s)

`47611b15f959`

```
DERBY-4451 ArrayIndexOutOfBoundsException or ASSERT FAILED when inserting generated columns out of order

This patch fixes this issue as well as DERBY-4448, since they share
the same underlying problem: the former way of checking for illegal
override of generated columns in the presence of an explicit target
column list failed to look below the top level UnionNode in a table
constructor.

This specialized treatment for the case of an explicit target column
list has been removed for INSERT (it was shared with logic for
UPDATE), so checking is now done by the code for the case of no
explicit targte column list.



git-svn-id: https://svn.apache.org/repos/asf/db/derby/code/trunk@884163 13f79535-47bb-0310-9956-ffa450edef68
```

## Files the fix changed

Snapshot holds 1,965 non-test source files. The fix changed 4 file(s); 3 of them are non-test source files (listed below as gold).

- `java/engine/org/apache/derby/impl/sql/compile/DMLModStatementNode.java`
- `java/engine/org/apache/derby/impl/sql/compile/InsertNode.java`
- `java/engine/org/apache/derby/impl/sql/compile/UpdateNode.java`

## The fix diff

### `java/engine/org/apache/derby/impl/sql/compile/DMLModStatementNode.java`

```diff
diff --git a/java/engine/org/apache/derby/impl/sql/compile/DMLModStatementNode.java b/java/engine/org/apache/derby/impl/sql/compile/DMLModStatementNode.java
index ee666d14b..c8f50cee4 100644
--- a/java/engine/org/apache/derby/impl/sql/compile/DMLModStatementNode.java
+++ b/java/engine/org/apache/derby/impl/sql/compile/DMLModStatementNode.java
@@ -405,91 +405,10 @@ abstract class DMLModStatementNode extends DMLStatementNode
 			resultColumnList.bindResultColumnsByName(targetTableDescriptor,
 													(DMLStatementNode) this);
 		}
 	}
 
-    /**
-     * Do not allow generation clauses to be overriden. Throws an exception
-     * if the user attempts to override the value of a generated column.
-     * The only value allowed in a generated column is DEFAULT. If we find
-     * a generated column which is being explicitly set to DEFAULT in an INSERT, we remove
-     * it from the column lists--it will be added back in during the enhance
-     * phase. For an update, addedGeneratedColumns will be non-null and we will
-     * use this list to pass through the generated columns which have already
-     * been added to the update list.
-     *
-     * @param targetRCL  the row in the table being INSERTed or UPDATEd
-     * @param forUpdate  true if this is an UPDATE. false otherwise.
-     * @param addedGeneratedColumns generated columns which the compiler added earlier on
-     */
-    void forbidGenerationOverrides( ResultColumnList targetRCL, boolean forUpdate, ColumnDescriptorList addedGeneratedColumns )
-        throws StandardException
-    {
-        int  count = targetRCL.size();
-
-        ResultColumnList    resultRCL = resultSet.getResultColumns();
-        
-        for ( int i = 0; i < count; i++ )
-        {
-            ResultColumn    rc = (ResultColumn) targetRCL.elementAt( i );
-
-            if ( rc.hasGenerationClause() )
-            {
-                ValueNode   resultExpression = ((ResultColumn) resultRCL.elementAt( i )).getExpression();
-
-                if ( !( resultExpression instanceof DefaultNode) )
-                {
-                    //
-                    // For updates, we may have added the generation clause
-                    // ourselves. Here we forgive ourselves for this pro-active behavior.
-                    //
-                    boolean allIsForgiven = false;
-                    
-                    if ( forUpdate )
-                    {
-                        String      columnName = rc.getTableColumnDescriptor().getColumnName();
-                        int         addedCount = addedGeneratedColumns.size();
-
-                        for ( int j = 0; j < addedCount; j++ )
-                        {
-                            String  addedColumnName = addedGeneratedColumns.elementAt( j ).getColumnName();
-
-                            if ( columnName.equals( addedColumnName ) )
-                            {
-                                allIsForgiven = true;
-                                break;
-                            }
-                        }
-                    }
-                    if ( allIsForgiven ) { continue; }
-                    
-                    throw StandardException.newException
-                        ( SQLState.LANG_CANT_OVERRIDE_GENERATION_CLAUSE, rc.getName() );
-                }
-                else
-                {
-                    // skip this step if we're working on an update statement.
-                    // for updates, the target list has already been enhanced.
-                    if ( forUpdate ) { continue; }
-                    
-                    // Prune the generated column and its default. They will be
-                    // added back in during the enhance phase.
-                    targetRCL.removeElementAt( i );
-                    resultRCL.removeElementAt( i );
-
-                    targetRCL.resetVirtualColumnIds();
-                    resultRCL.resetVirtualColumnIds();
-
-                    // account for the dropped entries
-                    count--;
-                    i--;
-                }
-            }
-
-        }
-    }
-    
     /**
      * Parse and bind the generating expressions of computed columns.
      *
      * @param dataDictionary    metadata
      * @param targetTableDescriptor metadata for the table that has the generated columns
```

### `java/engine/org/apache/derby/impl/sql/compile/InsertNode.java`

```diff
diff --git a/java/engine/org/apache/derby/impl/sql/compile/InsertNode.java b/java/engine/org/apache/derby/impl/sql/compile/InsertNode.java
index 908876da4..9d65e9d67 100644
--- a/java/engine/org/apache/derby/impl/sql/compile/InsertNode.java
+++ b/java/engine/org/apache/derby/impl/sql/compile/InsertNode.java
@@ -282,13 +282,10 @@ public final class InsertNode extends DMLModStatementNode
 			{
 				targetColumnList.bindResultColumnsByName(targetVTI.getResultColumns(), targetVTI,
 														this);
 			}
 			getCompilerContext().popCurrentPrivType();
-
-            // don't allow overriding of generation clauses
-            forbidGenerationOverrides( targetColumnList, false, null );
 		}
 
 		/* Verify that all underlying ResultSets reclaimed their FromList */
 		if (SanityManager.DEBUG)
 		{
```

### `java/engine/org/apache/derby/impl/sql/compile/UpdateNode.java`

```diff
diff --git a/java/engine/org/apache/derby/impl/sql/compile/UpdateNode.java b/java/engine/org/apache/derby/impl/sql/compile/UpdateNode.java
index a12411c33..03866bbc5 100644
--- a/java/engine/org/apache/derby/impl/sql/compile/UpdateNode.java
+++ b/java/engine/org/apache/derby/impl/sql/compile/UpdateNode.java
@@ -372,11 +372,12 @@ public final class UpdateNode extends DMLModStatementNode
 					resultSet.resultColumns, this,
 					fromList);
 		getCompilerContext().popCurrentPrivType();
 
         // don't allow overriding of generation clauses
-        forbidGenerationOverrides( resultSet.getResultColumns(), true, addedGeneratedColumns );
+        forbidGenerationOverrides( resultSet.getResultColumns(),
+								   addedGeneratedColumns );
         
 		LanguageConnectionContext lcc = getLanguageConnectionContext();
 		if (lcc.getAutoincrementUpdate() == false)
 			resultSet.getResultColumns().forbidOverrides(null);
 
@@ -1291,6 +1292,77 @@ public final class UpdateNode extends DMLModStatementNode
 		}
 		
 		super.normalizeSynonymColumns(rcl, tableNameNode);
 	}
     
+    /**
+     * Do not allow generation clauses to be overriden. Throws an exception if
+     * the user attempts to override the value of a generated column.  The only
+     * value allowed in a generated column is DEFAULT. We will use
+     * addedGeneratedColumns list to pass through the generated columns which
+     * have already been added to the update list.
+     *
+     * @param targetRCL  the row in the table being UPDATEd
+     * @param addedGeneratedColumns generated columns which the compiler added
+     *        earlier on
+     * @throws StandardException on error
+     */
+    private void forbidGenerationOverrides(
+        ResultColumnList targetRCL,
+        ColumnDescriptorList addedGeneratedColumns)
+            throws StandardException
+    {
+        int  count = targetRCL.size();
+
+        ResultColumnList    resultRCL = resultSet.getResultColumns();
+
+        for ( int i = 0; i < count; i++ )
+        {
+            ResultColumn    rc = (ResultColumn) targetRCL.elementAt( i );
+
+            if ( rc.hasGenerationClause() )
+            {
+                ValueNode   resultExpression =
+                    ((ResultColumn) resultRCL.elementAt( i )).getExpression();
+
+                if ( !( resultExpression instanceof DefaultNode) )
+                {
+                    //
+                    // We may have added the generation clause
+                    // ourselves. Here we forgive ourselves for this
+                    // pro-active behavior.
+                    //
+                    boolean allIsForgiven = false;
+
+                    String columnName =
+                        rc.getTableColumnDescriptor().getColumnName();
+
+                    int addedCount = addedGeneratedColumns.size();
+
+                    for ( int j = 0; j < addedCount; j++ )
+                    {
+                        String addedColumnName = addedGeneratedColumns.
+                            elementAt(j).getColumnName();
+
+                        if ( columnName.equals( addedColumnName ) )
+                        {
+                            allIsForgiven = true;
+                            break;
+                        }
+                    }
+                    if ( allIsForgiven ) { continue; }
+
+                    throw StandardException.newException
+                        (SQLState.LANG_CANT_OVERRIDE_GENERATION_CLAUSE,
+                         rc.getName() );
+                }
+                else
+                {
+                    // Skip this step if we're working on an update
+                    // statement. For updates, the target list has already
+                    // been enhanced.
+                    continue;
+                }
+            }
+        }
+    }
 } // end of UpdateNode
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
