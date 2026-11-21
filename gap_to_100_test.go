package birdeye

import (
	"strings"
	"testing"
)

// 對照 python-final:tests/test_gap_to_100_suite.py

const gapCSV = `table_name,column_name,data_type
Address,AddressID,INT
Address,City,NVARCHAR
Customer,CustomerID,INT
Customer,CompanyName,NVARCHAR
`

func TestGap100_RunnerQmarkAndPrepareErrors(t *testing.T) {
	sql := "-- ? in line comment\nSELECT 1 /* block ? body */"
	rewritten, qn := rewriteQmarkSQL(sql)
	if qn != 0 || strings.Contains(rewritten, "@P") {
		t.Errorf("註解內 ? 不應改寫：qn=%d rewritten=%q", qn, rewritten)
	}

	if _, _, _, err := prepareSQL("SELECT ?", nil); err == nil || !strings.Contains(err.Error(), "PARAM_MISSING") {
		t.Errorf("SELECT ? 無參數 -> %v", err)
	}
	if _, _, _, err := prepareSQL("SELECT 1", 123); err == nil || !strings.Contains(err.Error(), "PARAM_FORMAT_INVALID") {
		t.Errorf("純量 params -> %v", err)
	}
}

func TestGap100_ParserScriptEmptyAndDispatch(t *testing.T) {
	if _, err := NewParser(mustTokens(t, ""), "").ParseScript(); err == nil {
		t.Error("空來源 ParseScript 應報錯")
	}

	sn, err := NewParser(mustTokens(t,
		"WITH C AS (SELECT 1 AS X) UPDATE Address SET City = 'A' WHERE 1=1;"+
			"WITH D AS (SELECT 1 AS X) DELETE FROM Address WHERE 1=1;"),
		"").ParseScript()
	if err != nil {
		t.Fatal(err)
	}
	if len(sn.(*ScriptNode).Statements) != 2 {
		t.Errorf("CTE UPDATE/DELETE dispatch: %d", len(sn.(*ScriptNode).Statements))
	}

	script2 := "BULK INSERT INTO Address;IF 1=1 SELECT 1;BEGIN SELECT 1 END;" +
		"CREATE TABLE T1 (C1 INT);ALTER TABLE Address ADD NewCol INT;" +
		"MERGE Address USING Address ON 1=1 WHEN MATCHED THEN UPDATE SET AddressID = 1;PRINT 1;SET NOCOUNT ON;"
	sn2, err := NewParser(mustTokens(t, script2), script2).ParseScript()
	if err != nil {
		t.Fatal(err)
	}
	if len(sn2.(*ScriptNode).Statements) != 8 {
		t.Errorf("8-way dispatch: %d", len(sn2.(*ScriptNode).Statements))
	}
}

func TestGap100_BinderHelpers(t *testing.T) {
	b := NewBinder(NewMetadataRegistry())

	if inferTypeFromValue(nil) != "UNKNOWN" || inferTypeFromValue(true) != "BIT" ||
		inferTypeFromValue(1.2) != "FLOAT" || inferTypeFromValue([]byte("x")) != "VARBINARY" ||
		inferTypeFromValue(struct{}{}) != "UNKNOWN" {
		t.Error("inferTypeFromValue")
	}

	b.normalizeExternalParams(&ParamInput{Ordered: []ParamKV{
		{Name: "city", Raw: map[string]any{"data_type": "nvarchar", "value": "Taipei"}},
		{Name: "blob", Raw: []byte("abc")},
	}})
	if b.externalParams["@CITY"] != "NVARCHAR" || b.externalParamValues["@CITY"] != "Taipei" || b.externalParams["@BLOB"] != "VARBINARY" {
		t.Errorf("normalizeExternalParams: %v / %v", b.externalParams, b.externalParamValues)
	}

	if b.isSafeIdentifier("dbo.Address", false) || b.isSafeIdentifier("a.b.c", true) {
		t.Error("isSafeIdentifier")
	}

	node := NewIdentifier("@tbl", nil)
	b.externalParamValues = map[string]any{}
	if err := recoverBail(func() { b.resolveStructuralIdentifier(node, "FROM/JOIN table", true) }); err == nil || !strings.Contains(err.Msg, "requires a runtime parameter value") {
		t.Errorf("no value -> %v", err)
	}
	b.externalParamValues = map[string]any{"@TBL": "   "}
	if err := recoverBail(func() { b.resolveStructuralIdentifier(NewIdentifier("@tbl", nil), "FROM/JOIN table", true) }); err == nil || !strings.Contains(err.Msg, "non-empty identifier string") {
		t.Errorf("blank -> %v", err)
	}
	b.externalParamValues = map[string]any{"@TBL": "A;DROP"}
	if err := recoverBail(func() { b.resolveStructuralIdentifier(NewIdentifier("@tbl", nil), "FROM/JOIN table", true) }); err == nil || !strings.Contains(err.Msg, "unsafe identifier") {
		t.Errorf("unsafe -> %v", err)
	}
}

func TestGap100_BinderMergeInsertValues(t *testing.T) {
	reg := mkReg(t, gapCSV)
	_, err := NewRunner(reg).Run("MERGE Address AS t USING Address AS s ON 1=0 WHEN NOT MATCHED THEN INSERT (AddressID, City) VALUES (1, 'X')", nil)
	if err != nil {
		t.Errorf("merge insert values: %v", err)
	}
}

func TestGap100_IntentWalkMergeBranches(t *testing.T) {
	ie := NewIntentExtractor()
	var intents []Intent
	mergeNode := map[string]any{
		"node_type":    "MergeStatement",
		"target":       map[string]any{"node_type": "IdentifierNode", "name": "Address", "qualifiers": []any{}},
		"target_alias": "t",
		"source": map[string]any{"node_type": "SelectStatement",
			"columns": []any{map[string]any{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": []any{"Address"}}},
			"table":   map[string]any{"node_type": "IdentifierNode", "name": "Address", "qualifiers": []any{}}},
		"source_alias": "s",
		"on_condition": map[string]any{"node_type": "BinaryExpressionNode",
			"left":  map[string]any{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": []any{"s"}},
			"right": map[string]any{"node_type": "IdentifierNode", "name": "AddressID", "qualifiers": []any{"t"}}},
		"clauses": []any{
			map[string]any{"action": "UPDATE", "set_clauses": []any{map[string]any{
				"column": map[string]any{"node_type": "IdentifierNode", "name": "City", "qualifiers": []any{"t"}},
				"expr":   map[string]any{"node_type": "IdentifierNode", "name": "@p"}}}},
			map[string]any{"action": "INSERT",
				"insert_columns": []any{map[string]any{"node_type": "IdentifierNode", "name": "City"}},
				"insert_values": []any{map[string]any{"node_type": "FunctionCallNode", "name": "UPPER",
					"args": []any{map[string]any{"node_type": "IdentifierNode", "name": "City", "qualifiers": []any{"t"}}}}}},
			map[string]any{"action": "DELETE"},
		},
	}
	ie.walkMerge(mergeNode, &intents, strSetT{})
	got := map[string]bool{}
	for _, i := range intents {
		got[i.Intent] = true
	}
	if !got["UPDATE"] || !got["INSERT"] || !got["DELETE"] {
		t.Errorf("walkMerge intents: %+v", intents)
	}
}

func TestGap100_MermaidCreateDropAlter(t *testing.T) {
	txt := NewMermaidExporter().ExportJSON(`{"node_type":"ScriptNode","statements":[
		{"node_type":"CreateTableStatement","table":{"node_type":"IdentifierNode","name":"T","qualifiers":["dbo"]}},
		{"node_type":"AlterTableStatement"},
		{"node_type":"DropTableStatement","table":{"node_type":"IdentifierNode","name":"T","qualifiers":["dbo"]}}]}`)
	for _, w := range []string{"CREATE TABLE dbo.T", "ALTER TABLE", "DROP TABLE dbo.T"} {
		if !strings.Contains(txt, w) {
			t.Errorf("缺少 %q\n%s", w, txt)
		}
	}
}

func TestGap100_ReconstructorQmarkIdentifier(t *testing.T) {
	sql := NewReconstructor().ReconstructValue(map[string]any{
		"node_type": "IdentifierNode", "name": "@P1", "param_input_mode": "qmark",
	})
	if sql != "?" {
		t.Errorf("qmark identifier -> %q", sql)
	}
}

func TestGap100_VisualizerStatementBranches(t *testing.T) {
	createStmt := &CreateTableStatement{IfNotExists: true, Table: NewIdentifier("T1", nil),
		Columns: []*ColumnDefinitionNode{{Name: "C1", DataType: "INT"}}}
	alterStmt := &AlterTableStatement{Table: NewIdentifier("Address", nil), Action: "ADD",
		Column: &ColumnDefinitionNode{Name: "NewCol", DataType: "INT"}}
	bulkStmt := &SqlBulkCopyStatement{Table: NewIdentifier("Address", nil)}
	setStmt := &SetStatement{IsOption: false, Target: NewIdentifier("@x", nil), Value: NewLiteral("1", NumericLiteral)}
	ifStmt := &IfStatement{Condition: NewLiteral("1", NumericLiteral), ThenBlock: []Node{createStmt}, ElseBlock: []Node{alterStmt}}
	execStmt := &ExecStatement{ProcName: NewIdentifier("ProcAsString", nil), ReturnVar: NewIdentifier("@ret", nil),
		NamedArgs: []*AssignmentNode{{Column: NewIdentifier("@p", nil), Right: NewLiteral("1", NumericLiteral)}}}
	mergeClause := &MergeClauseNode{MatchType: "MATCHED", Action: "UPDATE", Condition: NewLiteral("1", NumericLiteral),
		SetClauses: []*AssignmentNode{{Column: NewIdentifier("City", nil), Right: NewLiteral("X", StringLiteral)}}}
	mergeStmt := &MergeStatement{Target: NewIdentifier("Address", nil), TargetAlias: "t",
		Source: NewIdentifier("Address", nil), SourceAlias: "s", OnCondition: NewLiteral("1", NumericLiteral),
		Clauses: []*MergeClauseNode{mergeClause}}
	dropStmt := &DropTableStatement{Table: NewIdentifier("T1", nil), IfExists: true}

	script := &ScriptNode{Statements: []Node{dropStmt, createStmt, alterStmt, bulkStmt, setStmt, ifStmt, execStmt, mergeStmt}}
	out := NewVisualizer().Dump(script)
	for _, w := range []string{
		"DROP_TABLE_STATEMENT", "CREATE_TABLE_STATEMENT", "ALTER_TABLE_STATEMENT",
		"BULK_COPY_STATEMENT", "SET_STATEMENT", "IF_STATEMENT", "EXEC_STATEMENT", "MERGE_STATEMENT",
	} {
		if !strings.Contains(out, w) {
			t.Errorf("缺少 %q\n%s", w, out)
		}
	}
}
