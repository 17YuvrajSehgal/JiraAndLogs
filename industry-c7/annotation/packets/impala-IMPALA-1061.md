# Annotation packet: IMPALA-1061  (impala)

Label this against `annotation/RUBRIC.md`. You are seeing the issue as the reporter filed it, plus the change that eventually fixed it.

## Issue report (as filed)

```
Unqualified implicit table alias does not work with '*' expr or views.

This query works as expected:
{code}
select alltypes.id from fnuctional.alltypes
{code}

This query does not work:
{code}
[localhost:21000] > select alltypes.* from functional.alltypes;
Query: select alltypes.* from functional.alltypes
ERROR: AnalysisException: unknown table: alltypes
{code}

This query also does not work:
{code}
[localhost:21000] > select alltypes_view.id from functional.alltypes_view;
Query: select alltypes_view.id from functional.alltypes_view
ERROR: AnalysisException: unknown table alias: 'alltypes_view'
{code}
```

## Fix commit message(s)

`003da0ec59db`

```
IMPALA-1061: Fix resolution of implicit table aliases in views and star expressions.

This patch cleans up registration and resolution of implicit table aliases as follows:
During analysis, we register all legal aliases of table/view references and remember
implicit table aliases that are ambiguous. When resolving table or column references
we consider all legal table aliases.

A table/view may have either one explicit alias or two implicit aliases.
The implicit aliases are the fully-qualified and the unqualified table name.
Within a single query, explicit and implicit aliases can be mixed as long as there
are no clashes between explicit and fully-qualified implicit aliases, and there are
no ambiguous references to implicit unqualified aliases.

Change-Id: I5734539aa821d130882491ec628dae8128d22e2f
Reviewed-on: http://gerrit.ent.cloudera.com:8080/3258
Reviewed-by: Alex Behm <alex.behm@cloudera.com>
Tested-by: jenkins
Reviewed-on: http://gerrit.ent.cloudera.com:8080/3359
```

## Files the fix changed

Snapshot holds 749 non-test source files. The fix changed 11 file(s); 8 of them are non-test source files (listed below as gold).

- `fe/src/main/java/com/cloudera/impala/analysis/Analyzer.java`
- `fe/src/main/java/com/cloudera/impala/analysis/BaseTableRef.java`
- `fe/src/main/java/com/cloudera/impala/analysis/InlineViewRef.java`
- `fe/src/main/java/com/cloudera/impala/analysis/SelectStmt.java`
- `fe/src/main/java/com/cloudera/impala/analysis/TableRef.java`
- `fe/src/main/java/com/cloudera/impala/analysis/TupleDescriptor.java`
- `fe/src/main/java/com/cloudera/impala/analysis/ViewRef.java`
- `fe/src/main/java/com/cloudera/impala/catalog/InlineView.java`

## The fix diff

### `fe/src/main/java/com/cloudera/impala/analysis/Analyzer.java`

```diff
diff --git a/fe/src/main/java/com/cloudera/impala/analysis/Analyzer.java b/fe/src/main/java/com/cloudera/impala/analysis/Analyzer.java
index 1049d0100..edfaf2432 100644
--- a/fe/src/main/java/com/cloudera/impala/analysis/Analyzer.java
+++ b/fe/src/main/java/com/cloudera/impala/analysis/Analyzer.java
@@ -202,14 +202,21 @@ public class Analyzer {
   private final ArrayList<Analyzer> ancestors_;
 
   // map from lowercase table alias to a view definition of a WITH clause.
   private final Map<String, ViewRef> withClauseViews_ = Maps.newHashMap();
 
-  // map from lowercase table alias to descriptor.
+  // Map from lowercase table alias to descriptor. Tables without an explicit alias
+  // are assigned two implicit aliases: the unqualified and fully-qualified table name.
+  // Such tables have two entries pointing to the same descriptor. If an alias is
+  // ambiguous, then this map retains the first entry with that alias to simplify error
+  // checking (duplicate vs. ambiguous alias).
   private final Map<String, TupleDescriptor> aliasMap_ = Maps.newHashMap();
 
-  // map from lowercase qualified column name ("alias.col") to descriptor
+  // Set of lowercase ambiguous implicit table aliases.
+  private final Set<String> ambiguousAliases_ = Sets.newHashSet();
+
+  // map from lowercase explicit or fully-qualified implicit alias to descriptor
   private final Map<String, SlotDescriptor> slotRefMap_ = Maps.newHashMap();
 
   // Tracks the all tables/views found during analysis that were missing metadata.
   private Set<TableName> missingTbls_ = new HashSet<TableName>();
 
@@ -311,31 +318,53 @@ public class Analyzer {
           String.format("Duplicate table alias: '%s'", ref.getAlias()));
     }
   }
 
   /**
-   * Checks that 'name' references an existing base table and that alias
-   * isn't already registered. Creates and returns an empty TupleDescriptor
-   * and registers it against alias. If alias is empty, register
-   * "name.tbl" and "name.db.tbl" as aliases.
-   * Requires that all views have been substituted.
+   * Creates an returns an empty TupleDescriptor for the given table ref and registers
+   * it against all its legal aliases. For tables refs with an explicit alias, only the
+   * explicit alias is legal. For tables refs with no explicit alias, the fully-qualified
+   * and unqualified table names are legal aliases. Column references against unqualified
+   * implicit aliases can be ambiguous, therefore, we register such ambiguous aliases
+   * here. Requires that all views have been substituted.
+   * Throws if an existing explicit alias or implicit fully-qualified alias
+   * has already been registered for another table ref.
    */
-  public TupleDescriptor registerBaseTableRef(BaseTableRef ref)
+  public TupleDescriptor registerTableRef(TableRef ref)
       throws AnalysisException, AuthorizationException {
-    String lookupAlias = ref.getAlias().toLowerCase();
-    if (aliasMap_.containsKey(lookupAlias)) {
-      throw new AnalysisException("Duplicate table alias: '" + lookupAlias + "'");
+    // Alias is the explicit alias or the fully-qualified table name.
+    String alias = ref.getAlias().toLowerCase();
+    if (aliasMap_.containsKey(alias)) {
+      throw new AnalysisException("Duplicate table alias: '" + alias + "'");
+    }
+
+    // If ref has no explicit alias, then the unqualified and the fully-qualified table
+    // names are legal implicit aliases. Column references against unqualified implicit
+    // aliases can be ambiguous, therefore, we register such ambiguous aliases here.
+    String unqualifiedAlias = null;
+    if (!ref.hasExplicitAlias()) {
+      unqualifiedAlias = ref.getName().getTbl().toLowerCase();
+      TupleDescriptor tupleDesc = aliasMap_.get(unqualifiedAlias);
+      if (tupleDesc != null) {
+        if (tupleDesc.hasExplicitAlias()) {
+          throw new AnalysisException(
+              "Duplicate table alias: '" + unqualifiedAlias + "'");
+        } else {
+          ambiguousAliases_.add(unqualifiedAlias);
+        }
+      }
     }
 
-    Table tbl = getTable(ref.getName(), ref.getPrivilegeRequirement(), true);
-    // Views should have been substituted already.
-    Preconditions.checkState(!(tbl instanceof View),
-        String.format("View %s has not been properly substituted.", tbl.getFullName()));
-    TupleDescriptor result = globalState_.descTbl.createTupleDescriptor();
-    result.setTable(tbl);
-    result.setAlias(lookupAlias);
-    aliasMap_.put(lookupAlias, result);
+    TupleDescriptor result = ref.createTupleDescriptor(this);
+    result.setAlias(ref.getAlias(), ref.hasExplicitAlias());
+    // Register explicit or fully-qualified implicit alias.
+    aliasMap_.put(alias, result);
+    if (!ref.hasExplicitAlias()) {
+      // Register unqualified implicit alias.
+      Preconditions.checkNotNull(unqualifiedAlias);
+      aliasMap_.put(unqualifiedAlias, result);
+    }
     return result;
   }
 
   /**
    * Register tids as being outer-joined by Join clause represented by rhsRef.
@@ -346,37 +375,22 @@ public class Analyzer {
     }
     LOG.trace("registerOuterJoinedTids: " + globalState_.outerJoinedTupleIds.toString());
   }
 
   /**
-   * Register an inline view. The enclosing select block of the inline view should have
-   * been analyzed.
-   * Checks that the alias isn't already registered. Checks the inline view doesn't have
-   * duplicate column names.
-   * Creates and returns an empty, non-materialized TupleDescriptor for the inline view
-   * and registers it against alias.
-   * An InlineView object is created and is used as the underlying table of the tuple
-   * descriptor.
+   * Return descriptor of registered table/alias or null if no matching descriptor was
+   * found. Attempts to resolve name in the context of any of the registered tuples.
+   * Throws an analysis exception if name is unqualified and could match multiple
+   * registered descriptors (i.e., is ambiguous).
    */
-  public TupleDescriptor registerInlineViewRef(InlineViewRef ref)
-      throws AnalysisException {
-    String lookupAlias = ref.getAlias().toLowerCase();
-    if (aliasMap_.containsKey(lookupAlias)) {
-      throw new AnalysisException("Duplicate table alias: '" + lookupAlias + "'");
+  public TupleDescriptor getDescriptor(TableName name) throws AnalysisException {
+    String lookupAlias = name.toString().toLowerCase();
+    if (!name.isFullyQualified() && ambiguousAliases_.contains(lookupAlias)) {
+      throw new AnalysisException(
+          "unqualified table alias '" + name.toString() + "' is ambiguous");
     }
-    // Delegate creation of the tuple descriptor to the concrete inline view ref.
-    TupleDescriptor tupleDesc = ref.createTupleDescriptor(globalState_.descTbl);
-    tupleDesc.setAlias(lookupAlias);
-    aliasMap_.put(lookupAlias, tupleDesc);
-    return tupleDesc;
-  }
-
-  /**
-   * Return descriptor of registered table/alias.
-   */
-  public TupleDescriptor getDescriptor(TableName name) {
-    return aliasMap_.get(name.toString().toLowerCase());
+    return aliasMap_.get(lookupAlias);
   }
 
   public TupleDescriptor getTupleDesc(TupleId id) {
     return globalState_.descTbl.getTupleDesc(id);
   }
@@ -401,47 +415,53 @@ public class Analyzer {
    * column hasn't previously been registered, otherwise returns the existing
    * descriptor.
    */
   public SlotDescriptor registerColumnRef(TableName tblName, String colName)
       throws AnalysisException {
-    String alias;
+    TupleDescriptor tupleDesc = null;
+    Column col = null;
     if (tblName == null) {
-      alias = resolveColumnRef(colName, null);
-      if (alias == null) {
+      // Resolve colName in the context of all registered tables.
+      tupleDesc = resolveColumnRef(colName);
+      if (tupleDesc == null) {
         throw new AnalysisException("couldn't resolve column reference: '" +
             colName + "'");
       }
+      col = tupleDesc.getTable().getColumn(colName);
+      Preconditions.checkNotNull(col);
     } else {
-      alias = tblName.toString().toLowerCase();
-    }
-
-    TupleDescriptor tupleDesc = aliasMap_.get(alias);
-    // Try to resolve column references ("table.col") that do not refer to an explicit
-    // alias, and that do not use a fully-qualified table name.
-    String tmpAlias = alias;
-    if (tupleDesc == null && tblName != null) {
-      tmpAlias = resolveColumnRef(colName, tblName.getTbl());
-      tupleDesc = aliasMap_.get(tmpAlias);
-    }
-    if (tupleDesc == null) {
-      throw new AnalysisException("unknown table alias: '" + alias + "'");
-    }
-    alias = tmpAlias;
-
-    Column col = tupleDesc.getTable().getColumn(colName);
-    if (col == null) {
-      throw new AnalysisException("unknown column '" + colName +
-          "' (table alias '" + alias + "')");
+      // Resolve colName in the context of tblName.
+      String lookupAlias = tblName.toString().toLowerCase();
+      if (!tblName.isFullyQualified() && ambiguousAliases_.contains(lookupAlias)) {
+        throw new AnalysisException(
+            String.format("unqualified table alias '%s' in column " +
+                "reference '%s' is ambiguous",
+                tblName.toString(), tblName.toString() + "." + colName));
+      }
+      tupleDesc = aliasMap_.get(lookupAlias);
+      if (tupleDesc == null) {
+        throw new AnalysisException(
+            String.format("unknown table alias '%s' in column reference '%s'",
+                tblName.toString(), tblName.toString() + "." + colName));
+      }
+      col = tupleDesc.getTable().getColumn(colName);
+      if (col == null) {
+        throw new AnalysisException(
+            String.format("couldn't resolve column reference: '%s'",
+                tblName.toString() + "." + colName));
+      }
     }
 
-    String key = alias + "." + col.getName();
+    // SlotRefs are registered against the tuple's explicit or fully-qualified
+    // implicit alias.
+    String key = tupleDesc.getAlias() + "." + col.getName();
     SlotDescriptor result = slotRefMap_.get(key);
     if (result != null) return result;
     result = addSlotDescriptor(tupleDesc);
     result.setColumn(col);
     result.setLabel(col.getName());
-    slotRefMap_.put(alias + "." + col.getName(), result);
+    slotRefMap_.put(key, result);
     return result;
   }
 
   /**
    * Creates a new slot descriptor and related state in globalState.
@@ -451,29 +471,28 @@ public class Analyzer {
     globalState_.blockBySlot.put(result.getId(), this);
     return result;
   }
 
   /**
-   * Resolves column name in context of any of the registered table aliases.
-   * Returns null if not found or multiple bindings to different tables exist,
-   * otherwise returns the table alias.
-   * If a specific table name was given (tableName != null) then only
-   * columns from registered tables with a matching name are considered.
+   * Resolves column name in context of any of the registered tuple descriptors.
+   * Returns the matching tuple descriptor or null if none could be found.
+   * Throws if multiple bindings to different tables exist.
    */
-  private String resolveColumnRef(String colName, String tableName)
-      throws AnalysisException {
-    String result = null;
+  private TupleDescriptor resolveColumnRef(String colName) throws AnalysisException {
+    TupleDescriptor result = null;
     for (Map.Entry<String, TupleDescriptor> entry: aliasMap_.entrySet()) {
-      Table table = entry.getValue().getTable();
-      Column col = table.getColumn(colName);
-      if (col != null &&
-          (tableName == null || tableName.equalsIgnoreCase(table.getName()))) {
-        if (result != null) {
+      TupleDescriptor tupleDesc = entry.getValue();
+      Column col = tupleDesc.getTable().getColumn(colName);
+      if (col != null) {
+        // The same tuple descriptor may have been registered for multiple
+        // implicit aliases, so only throw an error if the tuple descriptors
+        // are different.
+        if (result != null && result != tupleDesc) {
           throw new AnalysisException(
-              "Unqualified column reference '" + colName + "' is ambiguous");
+              "unqualified column reference '" + colName + "' is ambiguous");
         }
-        result = entry.getKey();
+        result = tupleDesc;
       }
     }
     return result;
   }
```

### `fe/src/main/java/com/cloudera/impala/analysis/BaseTableRef.java`

```diff
diff --git a/fe/src/main/java/com/cloudera/impala/analysis/BaseTableRef.java b/fe/src/main/java/com/cloudera/impala/analysis/BaseTableRef.java
index e3d060a95..31ed80740 100644
--- a/fe/src/main/java/com/cloudera/impala/analysis/BaseTableRef.java
+++ b/fe/src/main/java/com/cloudera/impala/analysis/BaseTableRef.java
@@ -15,10 +15,12 @@
 package com.cloudera.impala.analysis;
 
 import java.util.List;
 
 import com.cloudera.impala.catalog.AuthorizationException;
+import com.cloudera.impala.catalog.Table;
+import com.cloudera.impala.catalog.View;
 import com.cloudera.impala.common.AnalysisException;
 import com.cloudera.impala.common.InternalException;
 import com.google.common.base.Preconditions;
 
 /**
@@ -29,93 +31,64 @@ import com.google.common.base.Preconditions;
  * should represent a base table or a view. Clean up parsing/analysis of TableRefs
  * and the replacement of views, e.g., analysis should go through the list
  * of abstract TableRefs in a SelectStmt and replace them with Views or BaseTableRefs.
  */
 public class BaseTableRef extends TableRef {
-  private TableName name_;
-
   // Indicates whether this table should be considered for view replacement
   // from WITH-clause views. Used to distinguish non-fully-qualified references
   // to catalog entries (base table or view) from WITH-clause views.
   private boolean allowWithViewReplacement_ = true;
 
   public BaseTableRef(TableName name, String alias) {
-    super(alias);
-    Preconditions.checkArgument(!name.toString().isEmpty());
-    Preconditions.checkArgument(alias == null || !alias.isEmpty());
-    this.name_ = name;
+    super(name, alias);
   }
 
   /**
    * C'tor for cloning.
    */
   public BaseTableRef(BaseTableRef other) {
     super(other);
-    this.name_ = other.name_;
     this.allowWithViewReplacement_ = other.allowWithViewReplacement_;
   }
 
-  /**
-   * Returns the name of the table referred to. Before analysis, the table name
-   * may not be fully qualified. If the table name is unqualified, the current
-   * default database from the analyzer will be used as the db name.
-   */
-  public TableName getName() { return name_; }
-
-  /**
-   * Replaces name_ with the fully-qualified table name.
-   */
-  public void setFullyQualifiedTableName(Analyzer analyzer) {
-    name_ = analyzer.getFullyQualifiedTableName(name_);
-  }
-
   /**
    * Register this table ref and then analyze the Join clause.
    */
   @Override
   public void analyze(Analyzer analyzer) throws AnalysisException,
       AuthorizationException {
     Preconditions.checkNotNull(getPrivilegeRequirement());
     setFullyQualifiedTableName(analyzer);
-    desc_ = analyzer.registerBaseTableRef(this);
+    desc_ = analyzer.registerTableRef(this);
     isAnalyzed_ = true;  // true that we have assigned desc
     try {
       analyzeJoin(analyzer);
     } catch (InternalException e) {
       throw new AnalysisException(e.getMessage(), e);
     }
   }
 
+  @Override
+  public TupleDescriptor createTupleDescriptor(Analyzer analyzer)
+      throws AnalysisException, AuthorizationException {
+    TupleDescriptor result = analyzer.getDescTbl().createTupleDescriptor();
+    Table tbl = analyzer.getTable(name_, getPrivilegeRequirement(), true);
+    // Views should have been substituted already.
+    Preconditions.checkState(!(tbl instanceof View),
+        String.format("View %s has not been properly substituted.", tbl.getFullName()));
+    result.setTable(tbl);
+    return result;
+  }
+
   @Override
   public List<TupleId> getMaterializedTupleIds() {
     // This function should only be called after analyze().
     Preconditions.checkState(isAnalyzed_);
     Preconditions.checkState(desc_ != null);
     return desc_.getId().asList();
   }
 
-  /**
-   * Return alias by which this table is referenced in select block.
-   */
-  @Override
-  public String getAlias() {
-    if (alias_ == null) {
-      return name_.toString().toLowerCase();
-    } else {
-      return alias_;
-    }
-  }
-
-  @Override
-  public TableName getAliasAsName() {
-    if (alias_ != null) {
-      return new TableName(null, alias_);
-    } else {
-      return name_;
-    }
-  }
-
   @Override
   protected String tableRefToSql() {
     // Enclose the alias in quotes if Hive cannot parse it without quotes.
     // This is needed for view compatibility between Impala and Hive.
     String aliasSql = null;
```

### `fe/src/main/java/com/cloudera/impala/analysis/InlineViewRef.java`

```diff
diff --git a/fe/src/main/java/com/cloudera/impala/analysis/InlineViewRef.java b/fe/src/main/java/com/cloudera/impala/analysis/InlineViewRef.java
index c35e530a0..f9279763b 100644
--- a/fe/src/main/java/com/cloudera/impala/analysis/InlineViewRef.java
+++ b/fe/src/main/java/com/cloudera/impala/analysis/InlineViewRef.java
@@ -62,12 +62,12 @@ public class InlineViewRef extends TableRef {
   /**
    * Constructor with alias and inline view select statement
    * @param alias inline view alias
    * @param inlineViewStmt the select statement of the inline view
    */
-  public InlineViewRef(String alias, QueryStmt queryStmt) {
-    super(alias);
+  public InlineViewRef(TableName name, String alias, QueryStmt queryStmt) {
+    super(name, alias);
     Preconditions.checkNotNull(queryStmt);
     this.queryStmt_ = queryStmt;
   }
 
   /**
@@ -99,11 +99,11 @@ public class InlineViewRef extends TableRef {
     queryStmt_.analyze(inlineViewAnalyzer_);
 
     inlineViewAnalyzer_.setHasLimitOffsetClause(
         queryStmt_.hasLimit() || queryStmt_.hasOffset());
     queryStmt_.getMaterializedTupleIds(materializedTupleIds_);
-    desc_ = analyzer.registerInlineViewRef(this);
+    desc_ = analyzer.registerTableRef(this);
     isAnalyzed_ = true;  // true now that we have assigned desc
 
     // For constant selects we materialize its exprs into a tuple.
     if (materializedTupleIds_.isEmpty()) {
       Preconditions.checkState(queryStmt_ instanceof SelectStmt);
@@ -141,14 +141,14 @@ public class InlineViewRef extends TableRef {
 
   /**
    * Create a non-materialized tuple descriptor in descTbl for this inline view.
    * This method is called from the analyzer when registering this inline view.
    */
-  public TupleDescriptor createTupleDescriptor(DescriptorTable descTbl)
+  @Override
+  public TupleDescriptor createTupleDescriptor(Analyzer analyzer)
       throws AnalysisException {
-    // Create a fake catalog table for the inline view
-    InlineView inlineView = new InlineView(alias_);
+    InlineView inlineView = createDummyTable();
     for (int i = 0; i < queryStmt_.getColLabels().size(); ++i) {
       // inline view select statement has been analyzed. Col label should be filled.
       Expr selectItemExpr = queryStmt_.getResultExprs().get(i);
       String colAlias = queryStmt_.getColLabels().get(i);
 
@@ -162,16 +162,23 @@ public class InlineViewRef extends TableRef {
       Column col = new Column(colAlias, selectItemExpr.getType(), i);
       inlineView.addColumn(col);
     }
 
     // Create the non-materialized tuple and set the fake table in it.
-    TupleDescriptor result = descTbl.createTupleDescriptor();
+    TupleDescriptor result = analyzer.getDescTbl().createTupleDescriptor();
     result.setIsMaterialized(false);
     result.setTable(inlineView);
     return result;
   }
 
+  /**
+   * Creates a fake catalog table for the inline view.
+   * TODO: Clean up resolution and replacement of view/table refs and remove this
+   * function.
+   */
+  protected InlineView createDummyTable() { return new InlineView(alias_); }
+
   /**
    * Makes each rhs expr in baseTblSmap_ nullable, if necessary by wrapping as follows:
    * IF(TupleIsNull(), NULL, rhs expr)
    * Should be called only if this inline view is on the nullable side of an outer join.
    *
@@ -264,12 +271,10 @@ public class InlineViewRef extends TableRef {
 
   public QueryStmt getViewStmt() { return queryStmt_; }
   @Override
   public String getAlias() { return alias_; }
   @Override
-  public TableName getAliasAsName() { return new TableName(null, alias_); }
-  @Override
   public TableRef clone() { return new InlineViewRef(this); }
 
   @Override
   protected String tableRefToSql() {
     // Enclose the alias in quotes if Hive cannot parse it without quotes.
```

### `fe/src/main/java/com/cloudera/impala/analysis/SelectStmt.java`

```diff
diff --git a/fe/src/main/java/com/cloudera/impala/analysis/SelectStmt.java b/fe/src/main/java/com/cloudera/impala/analysis/SelectStmt.java
index 11aacdf30..f0357a940 100644
--- a/fe/src/main/java/com/cloudera/impala/analysis/SelectStmt.java
+++ b/fe/src/main/java/com/cloudera/impala/analysis/SelectStmt.java
@@ -305,11 +305,11 @@ public class SelectStmt extends QueryStmt {
    */
   private void expandStar(Analyzer analyzer, TableName tblName)
       throws AnalysisException, AuthorizationException {
     TupleDescriptor tupleDesc = analyzer.getDescriptor(tblName);
     if (tupleDesc == null) {
-      throw new AnalysisException("unknown table: " + tblName.toString());
+      throw new AnalysisException("unknown table alias '" + tblName.toString() + "'");
     }
     expandStar(analyzer, tblName, tupleDesc);
   }
 
   /**
```

### `fe/src/main/java/com/cloudera/impala/analysis/TableRef.java`

```diff
diff --git a/fe/src/main/java/com/cloudera/impala/analysis/TableRef.java b/fe/src/main/java/com/cloudera/impala/analysis/TableRef.java
index fdbd16e59..68d76a889 100644
--- a/fe/src/main/java/com/cloudera/impala/analysis/TableRef.java
+++ b/fe/src/main/java/com/cloudera/impala/analysis/TableRef.java
@@ -32,11 +32,11 @@ import com.google.common.collect.Sets;
  * An abstract representation of a table reference. The actual table reference could be
  * an inline view, or a base table, such as Hive table or HBase table. This abstract
  * representation of table also contains the JOIN specification.
  */
 public abstract class TableRef implements ParseNode {
-  // Table alias
+  protected TableName name_;
   protected final String alias_;
 
   protected JoinOperator joinOp_;
   protected ArrayList<String> joinHints_;
   protected Expr onClause_;
@@ -57,21 +57,33 @@ public abstract class TableRef implements ParseNode {
   protected List<TupleId> onClauseTupleIds_ = Lists.newArrayList();
 
   // analysis output
   protected TupleDescriptor desc_;
 
-  public TableRef(String alias) {
+  public TableRef(TableName name, String alias) {
     super();
+    Preconditions.checkArgument(name == null || !name.toString().isEmpty());
+    Preconditions.checkArgument(alias == null || !alias.isEmpty());
+    this.name_ = name;
     this.alias_ = alias;
     isAnalyzed_ = false;
   }
 
+  /**
+   * Creates and returns a empty TupleDescriptor registered with the analyzer. The
+   * returned tuple descriptor must have its source table set via descTbl.setTable()).
+   * This method is called from the analyzer when registering this table reference.
+   */
+  public abstract TupleDescriptor createTupleDescriptor(Analyzer analyzer)
+      throws AnalysisException, AuthorizationException;
+
   /**
    * C'tor for cloning.
    */
   protected TableRef(TableRef other) {
     super();
+    this.name_ = other.name_;
     this.alias_ = other.alias_;
     this.joinOp_ = other.joinOp_;
     this.joinHints_ =
         (other.joinHints_ != null) ? Lists.newArrayList(other.joinHints_) : null;
     this.usingColNames_ =
@@ -321,22 +333,51 @@ public abstract class TableRef implements ParseNode {
     }
     return output.toString();
   }
 
   /**
-   * Return alias by which table is referenced in select block.
-   * @return
+   * Returns the name of the table referred to. Before analysis, the table name
+   * may not be fully qualified. If the table name is unqualified, the current
+   * default database from the analyzer will be used as the db name.
    */
-  abstract public String getAlias();
+  public TableName getName() { return name_; }
 
-  abstract public TableName getAliasAsName();
+  /**
+   * Replaces name_ with the fully-qualified table name.
+   */
+  public void setFullyQualifiedTableName(Analyzer analyzer) {
+    name_ = analyzer.getFullyQualifiedTableName(name_);
+  }
+
+  /**
+   * Returns true if this table ref has an explicit table alias.
+   */
+  public boolean hasExplicitAlias() { return alias_ != null; }
+
+  /**
+   * Return the explicit alias of this table ref if one was given, otherwise the
+   * fully-qualified table name.
+   */
+  public String getAlias() {
+    if (alias_ == null) {
+      return name_.toString().toLowerCase();
+    } else {
+      return alias_;
+    }
+  }
+
+  public TableName getAliasAsName() {
+    if (alias_ != null) {
+      return new TableName(null, alias_);
+    } else {
+      return name_;
+    }
+  }
 
   @Override
   public abstract TableRef clone();
 
-  /*
+  /**
    * Gets the privilege requirement. This is always SELECT for TableRefs.
    */
-  public Privilege getPrivilegeRequirement() {
-    return Privilege.SELECT;
-  }
+  public Privilege getPrivilegeRequirement() { return Privilege.SELECT; }
 }
```

### `fe/src/main/java/com/cloudera/impala/analysis/TupleDescriptor.java`

```diff
diff --git a/fe/src/main/java/com/cloudera/impala/analysis/TupleDescriptor.java b/fe/src/main/java/com/cloudera/impala/analysis/TupleDescriptor.java
index 16cd2edc9..4ca945861 100644
--- a/fe/src/main/java/com/cloudera/impala/analysis/TupleDescriptor.java
+++ b/fe/src/main/java/com/cloudera/impala/analysis/TupleDescriptor.java
@@ -15,28 +15,31 @@
 package com.cloudera.impala.analysis;
 
 import java.util.ArrayList;
 import java.util.List;
 
-import org.slf4j.Logger;
-import org.slf4j.LoggerFactory;
-
 import com.cloudera.impala.catalog.ColumnStats;
 import com.cloudera.impala.catalog.PrimitiveType;
 import com.cloudera.impala.catalog.Table;
 import com.cloudera.impala.thrift.TTupleDescriptor;
 import com.google.common.base.Joiner;
 import com.google.common.base.Objects;
 import com.google.common.base.Preconditions;
 import com.google.common.collect.Lists;
 
 public class TupleDescriptor {
-  private final static Logger LOG = LoggerFactory.getLogger(TupleDescriptor.class);
   private final TupleId id_;
-  private String alias_;
   private final ArrayList<SlotDescriptor> slots_;
-  private Table table_;  // underlying table, if there is one
+
+  // Underlying table, if there is one.
+  private Table table_;
+
+  // Explicit or fully-qualified implicit alias.
+  private String alias_;
+
+  // True if alias_ is an explicit alias.
+  private boolean hasExplicitAlias_;
 
   // if false, this tuple doesn't need to be materialized
   private boolean isMaterialized_ = true;
 
   private int byteSize_;  // of all slots plus null indicators
@@ -70,11 +73,15 @@ public class TupleDescriptor {
   public int getByteSize() { return byteSize_; }
   public float getAvgSerializedSize() { return avgSerializedSize_; }
   public boolean getIsMaterialized() { return isMaterialized_; }
   public void setIsMaterialized(boolean value) { isMaterialized_ = value; }
   public String getAlias() { return alias_; }
-  public void setAlias(String alias) { alias_ = alias; }
+  public boolean hasExplicitAlias() { return hasExplicitAlias_; }
+  public void setAlias(String alias, boolean isExplicit) {
+    alias_ = alias;
+    hasExplicitAlias_ = isExplicit;
+  }
 
   public String debugString() {
     String tblStr = (table_ == null ? "null" : table_.getFullName());
     List<String> slotStrings = Lists.newArrayList();
     for (SlotDescriptor slot : slots_) {
```

### `fe/src/main/java/com/cloudera/impala/analysis/ViewRef.java`

```diff
diff --git a/fe/src/main/java/com/cloudera/impala/analysis/ViewRef.java b/fe/src/main/java/com/cloudera/impala/analysis/ViewRef.java
index 6984a9a0b..a047ede14 100644
--- a/fe/src/main/java/com/cloudera/impala/analysis/ViewRef.java
+++ b/fe/src/main/java/com/cloudera/impala/analysis/ViewRef.java
@@ -15,10 +15,11 @@
 package com.cloudera.impala.analysis;
 
 import com.cloudera.impala.authorization.ImpalaInternalAdminUser;
 import com.cloudera.impala.authorization.Privilege;
 import com.cloudera.impala.catalog.AuthorizationException;
+import com.cloudera.impala.catalog.InlineView;
 import com.cloudera.impala.catalog.View;
 import com.cloudera.impala.common.AnalysisException;
 import com.cloudera.impala.thrift.TAccessEvent;
 import com.google.common.base.Preconditions;
 
@@ -52,33 +53,32 @@ public class ViewRef extends InlineViewRef {
 
   /**
    * C'tor used for creating a view definition in a WITH clause.
    */
   public ViewRef(String alias, QueryStmt queryStmt) {
-    super(alias, queryStmt);
+    super(null, alias, queryStmt);
     Preconditions.checkNotNull(alias);
     table_ = null;
     origTblRef_ = null;
   }
 
   /**
    * C'tor used for creating a view definition from a view registered in the catalog.
    */
   public ViewRef(String alias, QueryStmt queryStmt, View table) {
-    super(alias, queryStmt);
+    super(table.getTableName(), alias, queryStmt);
     Preconditions.checkNotNull(alias);
     this.table_ = table;
     origTblRef_ = null;
   }
 
   /**
    * C'tor for view instantiations that replace the given BaseTableRef.
    * Only accessible via instantiate().
    */
   private ViewRef(BaseTableRef origTblRef, QueryStmt queryStmt, View table) {
-    // Use tblRef's explicit alias if it has one, otherwise the table name.
-    super(origTblRef.getAlias(), queryStmt);
+    super(origTblRef.name_, origTblRef.alias_, queryStmt);
     this.table_ = table;
     this.origTblRef_ = origTblRef;
     // Set context-dependent attributes from the original table.
     // Do not use originalTblRef.getJoinOp() because we want to record the fact that the
     // joinOp may be NULL, such that toSql() can work correctly.
@@ -144,10 +144,23 @@ public class ViewRef extends InlineViewRef {
     }
     analyzer.addAccessEvent(new TAccessEvent(table_.getFullName(),
         table_.getCatalogObjectType(), Privilege.SELECT.toString()));
   }
 
+  @Override
+  protected InlineView createDummyTable() {
+    if (table_ != null) {
+      // Catalog view.
+      return new InlineView(table_);
+    } else {
+      // WITH-clause view.
+      Preconditions.checkNotNull(name_);
+      Preconditions.checkNotNull(!name_.isFullyQualified());
+      return new InlineView(name_.getTbl());
+    }
+  }
+
   @Override
   protected String tableRefToSql() {
     if (origTblRef_ != null) return origTblRef_.tableRefToSql();
     // Enclose the alias in quotes if Hive cannot parse it without quotes.
     // This is needed for view compatibility between Impala and Hive.
@@ -162,13 +175,10 @@ public class ViewRef extends InlineViewRef {
   public String getAlias() {
     if (origTblRef_ == null) return alias_;
     return origTblRef_.getAlias().toLowerCase();
   }
 
-  @Override
-  public TableName getAliasAsName() { return new TableName(null, alias_); }
-
   /**
    * Returns true if this refers to a view registered in the catalog.
    * Returns false for views from a WITH clause.
    */
   public boolean isCatalogView() { return table_ != null; }
```

### `fe/src/main/java/com/cloudera/impala/catalog/InlineView.java`

```diff
diff --git a/fe/src/main/java/com/cloudera/impala/catalog/InlineView.java b/fe/src/main/java/com/cloudera/impala/catalog/InlineView.java
index 6da152196..b805d77f5 100644
--- a/fe/src/main/java/com/cloudera/impala/catalog/InlineView.java
+++ b/fe/src/main/java/com/cloudera/impala/catalog/InlineView.java
@@ -19,26 +19,36 @@ import org.apache.hadoop.hive.metastore.HiveMetaStoreClient;
 import com.cloudera.impala.thrift.TCatalogObjectType;
 import com.cloudera.impala.thrift.TTableDescriptor;
 import com.google.common.base.Preconditions;
 
 /**
- * A fake catalog representation of an inline view. It's like a table. It has name
- * and columns, but it won't have ids and it shouldn't be converted to Thrift.
- * An inline view is constructed by providing an alias (required) and then adding columns
- * one-by-one.
+ * A fake catalog representation of an inline view that is similar to a table.
+ * Inline views originating directly from the query or from WITH-clause views can only
+ * be referenced by their explicit alias, so their table name is the alias. Inline views
+ * instantiated from a catalog view have a real table name. Giving such fake tables
+ * a real table name is important to resolve their implicit aliases properly.
+ * Fake tables for inline views do not have an id, msTbl or an owner and cannot be
+ * converted to Thrift.
  */
 public class InlineView extends Table {
 
   /**
-   * An inline view only has an alias and columns, but it won't have id, db and owner.
-   * @param alias alias of the inline view; must not be null;
+   * C'tor for inline views that only have an explicit alias and not a real table name.
    */
   public InlineView(String alias) {
     super(null, null, null, alias, null);
     Preconditions.checkArgument(alias != null);
   }
 
+  /**
+   * C'tor for inline views with a real table name instantiated from a catalog view.
+   */
+  public InlineView(Table tbl) {
+    super(null, null, tbl.getDb(), tbl.getName(), null);
+    Preconditions.checkArgument(tbl != null);
+  }
+
   /**
    * An inline view has to be constructed by adding columns one by one.
    * @param col Column of the inline view
    */
   public void addColumn(Column col) {
```

---

## What to produce

A JSON object matching `annotation/schema.json`: a role for every gold file above, the symptom and log locations, the relation, a rationale citing specific diff hunks or report lines, and a confidence. Use `unclear` rather than guessing.
