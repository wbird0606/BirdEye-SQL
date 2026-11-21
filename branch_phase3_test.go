package birdeye

import (
	"strings"
	"testing"
)

// 對照 python-final:tests/test_branch_phase3_mixed_suite.py
// —— parser / binder / intent / visualizer 混合的剩餘分支（多以直接建構節點 + 呼叫內部方法）。

func bp3Reg(t *testing.T) *MetadataRegistry {
	return mkReg(t, "table_name,column_name,data_type\nT,A,INT\n")
}

// recoverBail：呼叫 fn，把 engineBail panic 收成 *Error（其餘 re-panic）。
func recoverBail(fn func()) (err *Error) {
	defer func() {
		if r := recover(); r != nil {
			if eb, ok := r.(engineBail); ok {
				err = eb.err
				return
			}
			panic(r)
		}
	}()
	fn()
	return nil
}

func TestBranchP3_Parser(t *testing.T) {
	p := NewParser(nil, "")

	ci := NewCaseExpr(NewIdentifier("x", nil))
	if !p.containsIdentifier(ci) {
		t.Error("CASE input=Identifier 應含 identifier")
	}
	cb := NewCaseExpr(NewLiteral("1", NumericLiteral))
	cb.Branches = append(cb.Branches, CaseBranch{When: NewIdentifier("w", nil), Then: NewLiteral("2", NumericLiteral)})
	if !p.containsIdentifier(cb) {
		t.Error("CASE branch when=Identifier 應含 identifier")
	}

	if c := mustParse(t, "SELECT LEFT()").(*SelectStatement).Columns[0]; nodeTypeName(c) != "FunctionCallNode" || c.(*FunctionCallNode).Name != "LEFT" {
		t.Errorf("LEFT() -> %v", c)
	}
	for _, sql := range []string{
		"SELECT SUM(1) OVER (PARTITION BY A, B) FROM T",
		"SELECT SUM(1) OVER (ORDER BY A, B) FROM T",
	} {
		if mustParse(t, sql) == nil {
			t.Errorf("%q", sql)
		}
	}

	drop := mustParse(t, "DROP TABLE IF T").(*DropTableStatement)
	if drop.IfExists || drop.Table.Name != "T" {
		t.Errorf("DROP TABLE IF T: %+v", drop)
	}
	alter := mustParse(t, "ALTER TABLE T DROP c").(*AlterTableStatement)
	if alter.Action != "DROP" || alter.Column.(*IdentifierNode).Name != "c" {
		t.Errorf("ALTER TABLE T DROP c: %+v", alter)
	}
}

func TestBranchP3_BinderBindNodePaths(t *testing.T) {
	b := NewBinder(bp3Reg(t))
	// bulk / drop / alter
	bulk := &SqlBulkCopyStatement{Table: NewIdentifier("T", nil)}
	if err := recoverBail(func() { b.bindNode(bulk) }); err != nil {
		t.Errorf("bulk: %v", err)
	}
	if err := recoverBail(func() { b.bindNode(&DropTableStatement{}) }); err != nil {
		t.Errorf("drop: %v", err)
	}
	if err := recoverBail(func() { b.bindNode(&AlterTableStatement{}) }); err != nil {
		t.Errorf("alter: %v", err)
	}
}

func TestBranchP3_BinderTypeCompatGroups(t *testing.T) {
	b := NewBinder(bp3Reg(t))
	cases := [][2]string{
		{"DATE", "DATETIME"}, {"GEOGRAPHY", "GEOMETRY"}, {"VARBINARY", "IMAGE"}, {"XML", "XML"},
	}
	for _, c := range cases {
		if !b.isTypeCompatible(c[0], c[1]) {
			t.Errorf("isTypeCompatible(%q,%q) 應為 true", c[0], c[1])
		}
	}
}

func TestBranchP3_BinderVisitExprSubqueryVariants(t *testing.T) {
	mk := func() *Binder { return NewBinder(bp3Reg(t)) }
	left := NewLiteral("1", NumericLiteral)

	anyExpr := NewBinaryExpr(left, "> ANY", mustParse(t, "SELECT 1"))
	if got := mk().visitExpr(anyExpr); got != "BIT" {
		t.Errorf("> ANY subquery -> %q", got)
	}
	inExpr := NewBinaryExpr(NewLiteral("1", NumericLiteral), "IN", mustParse(t, "SELECT 1"))
	if got := mk().visitExpr(inExpr); got != "BIT" {
		t.Errorf("IN subquery -> %q", got)
	}
	union := mustParse(t, "SELECT 1 UNION SELECT 2")
	if got := mk().visitExpr(union); got != "TABLE" {
		t.Errorf("UNION -> %q", got)
	}
}

func TestBranchP3_BinderFalseyPaths(t *testing.T) {
	reg := NewMetadataRegistry()
	if err := reg.LoadFromCSV("table_name,column_name,data_type\nT,A,INT\n"); err != nil {
		t.Fatal(err)
	}

	b := NewBinder(reg)
	// bindInsert：values 少於 registry 欄位數以外的分支（T 只有 1 欄，給 1 值 OK）
	ins := &InsertStatement{Table: NewIdentifier("T", nil), Values: []Node{NewLiteral("1", NumericLiteral)}}
	if err := recoverBail(func() { b.bindInsert(ins) }); err != nil {
		t.Errorf("bindInsert: %v", err)
	}

	if err := recoverBail(func() { NewBinder(reg).bindIf(&IfStatement{}) }); err != nil {
		t.Errorf("bindIf 空: %v", err)
	}

	setVar := &SetStatement{Target: NewIdentifier("@X", nil), Value: nil, IsOption: false}
	if err := recoverBail(func() { NewBinder(reg).bindSet(setVar) }); err != nil {
		t.Errorf("bindSet var: %v", err)
	}
	setOpt := &SetStatement{IsOption: true, Value: nil}
	if err := recoverBail(func() { NewBinder(reg).bindSet(setOpt) }); err != nil {
		t.Errorf("bindSet option: %v", err)
	}
}

func TestBranchP3_BinderCreateMergePrintAgg(t *testing.T) {
	b := NewBinder(bp3Reg(t))

	if err := recoverBail(func() { b.bindCreateTable(&CreateTableStatement{Table: NewIdentifier("RealTable", nil)}) }); err != nil {
		t.Errorf("bindCreateTable: %v", err)
	}
	if err := recoverBail(func() { b.bindMerge(&MergeStatement{Clauses: []*MergeClauseNode{{}}}) }); err != nil {
		t.Errorf("bindMerge: %v", err)
	}
	if err := recoverBail(func() { b.bindPrint(&PrintStatement{}) }); err != nil {
		t.Errorf("bindPrint: %v", err)
	}

	caseExpr := NewCaseExpr(NewFunctionCall("SUM", []Node{NewLiteral("1", NumericLiteral)}))
	if !b.isAggRaw(caseExpr) {
		t.Error("isAggRaw(CASE input=SUM) 應為 true")
	}
	if err := recoverBail(func() {
		b.checkAggIntegrity(NewIdentifier("A", nil), []Node{NewIdentifier("A", nil)})
	}); err != nil {
		t.Errorf("checkAggIntegrity: %v", err)
	}
}

func TestBranchP3_IntentGuards(t *testing.T) {
	ie := NewIntentExtractor()
	var intents []Intent

	selNode := map[string]any{
		"node_type": "SelectStatement", "ctes": []any{},
		"table":  map[string]any{"node_type": "IdentifierNode", "name": "T", "qualifiers": []any{}},
		"joins":  []any{map[string]any{"table": map[string]any{"node_type": "SelectStatement"}}},
		"where":  nil, "having": nil, "group_by": []any{}, "order_by": []any{}, "applies": []any{}, "columns": []any{},
	}
	tabs := map[[2]string]bool{}
	ie.collectTables(selNode, tabs, strSetT{})
	ie.collectTables(map[string]any{"node_type": "UpdateStatement", "table": map[string]any{"node_type": "SelectStatement"}, "where": nil, "set": []any{}}, tabs, strSetT{})
	ie.collectTables(map[string]any{"node_type": "InsertStatement", "table": map[string]any{"node_type": "SelectStatement"}, "source": nil}, tabs, strSetT{})

	ie.walk(map[string]any{"node_type": "TruncateStatement", "table": map[string]any{"node_type": "IdentifierNode", "name": "CTE1", "qualifiers": []any{}}}, &intents, strSetT{"CTE1": true})
	ie.walk(map[string]any{"node_type": "SetStatement", "is_option": true, "value": nil}, &intents, strSetT{})
	ie.walk(map[string]any{"node_type": "DeclareStatement"}, &intents, strSetT{})

	// walkExpr：多表 alias_map + 無 qualifier 的 identifier → 略過（不 panic）
	am := newAliasMap()
	am.set("T1", schemaTable{"", "T1"})
	am.set("T2", schemaTable{"", "T2"})
	ie.walkExpr(map[string]any{"node_type": "IdentifierNode", "name": "A", "qualifiers": []any{}}, am, "READ", &intents, strSetT{}, nil)

	// buildAliasMap：table 為 SelectStatement + alias → derived 含該 alias
	_, derived := ie.buildAliasMap(map[string]any{
		"node_type": "SelectStatement",
		"table":     map[string]any{"node_type": "SelectStatement"},
		"alias":     "D", "joins": []any{},
	}, strSetT{}, nil)
	if !derived["D"] {
		t.Errorf("derived 應含 D：%v", derived)
	}
}

func TestBranchP3_VisualizerStatementFields(t *testing.T) {
	v := func() *Visualizer { return NewVisualizer() }
	checks := []struct {
		node Node
		want string
	}{
		{&DropTableStatement{}, "DROP_TABLE_STATEMENT"},
		{&CreateTableStatement{Table: NewIdentifier("T", nil)}, "CREATE_TABLE_STATEMENT"},
		{&AlterTableStatement{Table: NewIdentifier("T", nil)}, "ALTER_TABLE_STATEMENT"},
		{&SetStatement{IsOption: true}, "SET_OPTION"},
		{&SetStatement{IsOption: false}, "SET_STATEMENT"},
		{&IfStatement{Condition: NewLiteral("1", NumericLiteral)}, "IF_STATEMENT"},
		{&MergeStatement{Target: NewIdentifier("T", nil)}, "MERGE_STATEMENT"},
		{&PrintStatement{}, "PRINT_STATEMENT"},
	}
	for _, c := range checks {
		out := v().Dump(c.node)
		if !strings.Contains(out, c.want) {
			t.Errorf("%s 缺少 %q\n%s", nodeTypeName(c.node), c.want, out)
		}
	}

	caseNode := &CaseExpressionNode{Branches: []CaseBranch{{When: NewLiteral("1", NumericLiteral), Then: NewLiteral("2", NumericLiteral)}}}
	if out := v().Dump(caseNode); !strings.Contains(out, "CASE_EXPRESSION") {
		t.Errorf("case: %s", out)
	}

	fn := NewFunctionCall("SUM", []Node{NewLiteral("1", NumericLiteral)})
	fn.OverClause = &OverClauseNode{FrameType: "ROWS", FrameStart: "CURRENT ROW"}
	out := v().Dump(fn)
	if !strings.Contains(out, "OVER_CLAUSE") || !strings.Contains(out, "FRAME: ROWS") {
		t.Errorf("over clause: %s", out)
	}
}
