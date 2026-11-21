package birdeye

import (
	"strings"
	"testing"
)

// 對照 python-final:tests/test_coverage_100_suite.py
// —— 針對每個剩餘未覆蓋的 false 分支。

func c100Reg(t *testing.T) *MetadataRegistry {
	return mkReg(t, "table_name,column_name,data_type\nT,A,INT\n")
}

func TestCov100_Binder(t *testing.T) {
	// ORDER BY 非 identifier（算術式）→ 跳過結構性解析
	if err := recoverBail(func() {
		NewBinder(c100Reg(t)).bindSelect(mustParse(t, "SELECT A FROM T ORDER BY A + 1").(*SelectStatement))
	}); err != nil {
		t.Errorf("ORDER BY A+1: %v", err)
	}

	// scope 有表但 registry 完全沒登記 → not found
	b := NewBinder(NewMetadataRegistry())
	b.scopes = append(b.scopes, newScopeFrame())
	b.scopes[0].set("GHOSTTABLE", "GHOSTTABLE")
	b.nullableStack = append(b.nullableStack, map[string]bool{})
	err := recoverBail(func() { b.resolveIdentifier(NewIdentifier("col1", nil)) })
	if err == nil || !strings.Contains(err.Msg, "not found") {
		t.Errorf("ghost table resolve -> %v", err)
	}

	// ANY / IN 右側為純量 → BIT
	mk := func() *Binder { return NewBinder(c100Reg(t)) }
	anyScalar := NewBinaryExpr(NewLiteral("1", NumericLiteral), "> ANY", NewLiteral("2", NumericLiteral))
	if got := mk().visitExpr(anyScalar); got != "BIT" {
		t.Errorf("> ANY scalar -> %q", got)
	}
	inScalar := NewBinaryExpr(NewLiteral("1", NumericLiteral), "IN", NewLiteral("2", NumericLiteral))
	if got := mk().visitExpr(inScalar); got != "BIT" {
		t.Errorf("IN scalar -> %q", got)
	}
	// ANY 子查詢無欄位 → BIT
	emptySel := &SelectStatement{Columns: nil}
	anyEmpty := NewBinaryExpr(NewLiteral("1", NumericLiteral), "> ANY", emptySel)
	if got := mk().visitExpr(anyEmpty); got != "BIT" {
		t.Errorf("> ANY empty-cols subquery -> %q", got)
	}

	// INSERT-SELECT，ghost 表無欄位 → col_names 為空
	greg := NewMetadataRegistry()
	greg.tables["GHOST"] = map[string]string{}
	if err := recoverBail(func() {
		NewBinder(greg).bindNode(mustParse(t, "INSERT INTO Ghost SELECT 1"))
	}); err != nil {
		t.Errorf("INSERT INTO Ghost SELECT 1: %v", err)
	}

	// bindCreateTable table 為 nil → no-op
	if err := recoverBail(func() { NewBinder(c100Reg(t)).bindCreateTable(&CreateTableStatement{}) }); err != nil {
		t.Errorf("bindCreateTable(nil table): %v", err)
	}

	// bindMerge：set clause 的 right 為 nil → 跳過 visitExpr
	merge := &MergeStatement{Clauses: []*MergeClauseNode{{
		SetClauses: []*AssignmentNode{{Column: NewIdentifier("A", nil), Right: nil}},
	}}}
	if err := recoverBail(func() { NewBinder(c100Reg(t)).bindMerge(merge) }); err != nil {
		t.Errorf("bindMerge(nil right): %v", err)
	}
}

func TestCov100_IntentCollectTablesCTEExclusion(t *testing.T) {
	ie := NewIntentExtractor()

	cteQuery := map[string]any{
		"node_type": "SelectStatement", "ctes": []any{}, "table": nil,
		"joins": []any{}, "columns": []any{}, "where": nil, "group_by": []any{},
		"having": nil, "order_by": []any{}, "applies": []any{},
	}
	sel := map[string]any{
		"node_type": "SelectStatement",
		"ctes":      []any{map[string]any{"name": "MyCTE", "query": cteQuery}},
		"table":     map[string]any{"node_type": "IdentifierNode", "name": "RealTable", "qualifiers": []any{}},
		"joins":     []any{map[string]any{"table": map[string]any{"node_type": "IdentifierNode", "name": "MyCTE", "qualifiers": []any{}}}},
		"where":     nil, "having": nil, "group_by": []any{}, "order_by": []any{}, "applies": []any{}, "columns": []any{},
	}
	tabs := map[[2]string]bool{}
	ie.collectTables(sel, tabs, strSetT{})
	names := map[string]bool{}
	for k := range tabs {
		names[k[1]] = true
	}
	if names["MyCTE"] || names["MYCTE"] || !names["RealTable"] {
		t.Errorf("JOIN CTE 應被排除：%v", names)
	}

	// UPDATE / INSERT 目標名為 CTE → 排除
	t2 := map[[2]string]bool{}
	ie.collectTables(map[string]any{"node_type": "UpdateStatement",
		"table": map[string]any{"node_type": "IdentifierNode", "name": "MyCTE", "qualifiers": []any{}}, "where": nil, "set": []any{}},
		t2, strSetT{"MYCTE": true})
	if len(t2) != 0 {
		t.Errorf("UPDATE CTE target: %v", t2)
	}
	t3 := map[[2]string]bool{}
	ie.collectTables(map[string]any{"node_type": "InsertStatement",
		"table": map[string]any{"node_type": "IdentifierNode", "name": "MyCTE", "qualifiers": []any{}}, "source": nil},
		t3, strSetT{"MYCTE": true})
	if len(t3) != 0 {
		t.Errorf("INSERT CTE target: %v", t3)
	}
}

func TestCov100_IntentBuildAliasMapDerivedNoAlias(t *testing.T) {
	ie := NewIntentExtractor()
	_, derived := ie.buildAliasMap(map[string]any{
		"node_type": "SelectStatement",
		"table":     map[string]any{"node_type": "SelectStatement"},
		"alias":     "", "joins": []any{},
	}, strSetT{}, nil)
	if derived[""] || len(derived) != 0 {
		t.Errorf("無 alias 的 derived table 不應加入 derived：%v", derived)
	}
}

func TestCov100_ParserAnyEmptyParens(t *testing.T) {
	if parseErr(t, "SELECT 1 WHERE 1 > ANY ()") == nil {
		t.Error("> ANY () 應報 syntax error")
	}
}

func TestCov100_VisualizerNilFields(t *testing.T) {
	v := func() *Visualizer { return NewVisualizer() }
	checks := []struct {
		node Node
		want string
	}{
		{&CreateTableStatement{}, "CREATE_TABLE_STATEMENT"},
		{&AlterTableStatement{}, "ALTER_TABLE_STATEMENT"},
		{&IfStatement{}, "IF_STATEMENT"},
		{&MergeStatement{}, "MERGE_STATEMENT"},
	}
	for _, c := range checks {
		if out := v().Dump(c.node); !strings.Contains(out, c.want) {
			t.Errorf("%s: %s", nodeTypeName(c.node), out)
		}
	}

	fn := NewFunctionCall("SUM", []Node{NewLiteral("1", NumericLiteral)})
	fn.OverClause = &OverClauseNode{FrameType: "ROWS", FrameStart: "", FrameEnd: "UNBOUNDED FOLLOWING"}
	out := v().Dump(fn)
	if !strings.Contains(out, "FRAME: ROWS") || !strings.Contains(out, "END: UNBOUNDED FOLLOWING") {
		t.Errorf("over frame: %s", out)
	}
}
