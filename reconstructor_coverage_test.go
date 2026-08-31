package birdeye

import (
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_reconstructor_coverage_suite.py
// —— reconstructor.go 中 conformance 語料未觸及的分支（直接建構 dict 呼叫內部方法）。

func rcLit(val, typ string) map[string]any {
	return map[string]any{"node_type": "LiteralNode", "value": val, "type": typ}
}

func rcID(name string) map[string]any {
	return map[string]any{
		"node_type": "IdentifierNode", "name": name,
		"qualifiers": []any{}, "alias": nil, "resolved_table": nil,
	}
}

func rcSelectStar(table string) map[string]any {
	return map[string]any{
		"node_type": "SelectStatement", "ctes": []any{}, "top": nil, "top_percent": false,
		"is_distinct": false, "is_star": true, "columns": []any{},
		"table": rcID(table), "alias": nil, "joins": []any{}, "applies": []any{},
		"into_table": nil, "where": nil, "group_by": []any{}, "having": nil,
		"order_by": []any{}, "offset_count": nil, "fetch_count": nil,
	}
}

func TestReconstructor_ToSQL_NilAndUnknown(t *testing.T) {
	if got := NewReconstructor().ReconstructValue(nil); got != "" {
		t.Errorf("to_sql(nil) = %q, want \"\"", got)
	}
	if got := NewReconstructor().ReconstructValue(map[string]any{"node_type": "UnknownNodeXYZ"}); got != "" {
		t.Errorf("to_sql(unknown) = %q, want \"\"", got)
	}
}

// Python to_sql 以 getattr(self, f"_sql_{nt}") 分派，任何節點型別皆可為頂層。
// Go 的 toSQL switch 對每個型別各有分支 —— 逐一驗證分派正確。
func TestReconstructor_ToSQL_ExpressionDispatch(t *testing.T) {
	rc := NewReconstructor()
	id := func(name string) map[string]any { return rcID(name) }
	num := func(v string) map[string]any { return rcLit(v, "NUMERIC_LITERAL") }

	cases := []struct {
		node map[string]any
		want string
	}{
		{num("5"), "5"},
		{map[string]any{"node_type": "FunctionCallNode", "name": "LEN", "args": []any{id("City")}}, "LEN(City)"},
		{map[string]any{"node_type": "BetweenExpressionNode", "target": id("x"), "low": num("1"), "high": num("10")}, "x BETWEEN 1 AND 10"},
		{map[string]any{"node_type": "CastExpressionNode", "expr": id("x"), "target": "INT"}, "CAST(x AS INT)"},
		{map[string]any{"node_type": "JoinNode", "join_type": "INNER", "table": id("T"),
			"on": map[string]any{"node_type": "BinaryExpressionNode", "op": "=", "left": id("a"), "right": id("b")}}, "JOIN T ON a = b"},
		{map[string]any{"node_type": "AssignmentNode", "column": id("C"), "expr": num("1")}, "C = 1"},
		{map[string]any{"node_type": "OrderByNode", "column": id("x"), "direction": "DESC"}, "x DESC"},
		{map[string]any{"node_type": "OverClauseNode", "order_by": []any{map[string]any{"column": id("x")}}}, "OVER (ORDER BY x ASC)"},
		{map[string]any{"node_type": "ColumnDefinitionNode", "name": "C", "data_type": "INT"}, "C INT"},
		{map[string]any{"node_type": "MergeClauseNode", "match_type": "MATCHED", "action": "DELETE"}, "WHEN MATCHED THEN DELETE"},
		{map[string]any{"node_type": "ApplyNode", "type": "CROSS", "subquery": rcSelectStar("T"), "alias": nil}, "CROSS APPLY (SELECT * FROM T)"},
	}
	for _, c := range cases {
		if got := rc.ReconstructValue(c.node); got != c.want {
			t.Errorf("ReconstructValue(%v) = %q, want %q", c.node["node_type"], got, c.want)
		}
	}
}

func TestReconstructor_SelectInto(t *testing.T) {
	sql := roundtrip(t, "SELECT AddressID INTO #TmpAddr FROM Address")
	for _, w := range []string{"INTO", "SELECT", "Address"} {
		if !strings.Contains(sql, w) {
			t.Errorf("%q missing %q", sql, w)
		}
	}
}

func TestReconstructor_ApplyRoundtrips(t *testing.T) {
	for _, sql := range []string{
		"SELECT a.AddressID, x.val FROM Address a CROSS APPLY (SELECT 1 AS val) x",
		"SELECT a.AddressID, x.val FROM Address a OUTER APPLY (SELECT 1 AS val) x",
	} {
		got := roundtrip(t, sql)
		if !strings.Contains(got, "APPLY") || !strings.Contains(got, "Address") {
			t.Errorf("%q -> %q", sql, got)
		}
	}
}

func TestReconstructor_UpdateWithCTE_Direct(t *testing.T) {
	node := map[string]any{
		"node_type": "UpdateStatement",
		"ctes": []any{map[string]any{
			"name": "CTE1", "query": rcSelectStar("Address"),
		}},
		"table": rcID("Address"), "alias": nil,
		"set_clauses": []any{map[string]any{
			"node_type": "AssignmentNode",
			"column":    rcID("City"),
			"expr":      rcLit("X", "STRING_LITERAL"),
		}},
		"where": nil,
	}
	sql := NewReconstructor().ReconstructValue(node)
	for _, w := range []string{"WITH", "CTE1", "UPDATE"} {
		if !strings.Contains(sql, w) {
			t.Errorf("%q missing %q", sql, w)
		}
	}
}

func TestReconstructor_DeleteWithCTE_Direct(t *testing.T) {
	node := map[string]any{
		"node_type": "DeleteStatement",
		"ctes": []any{map[string]any{
			"name": "DEL_CTE", "query": rcSelectStar("Address"),
		}},
		"table": rcID("Address"), "alias": nil, "where": nil,
	}
	sql := NewReconstructor().ReconstructValue(node)
	for _, w := range []string{"WITH", "DEL_CTE", "DELETE"} {
		if !strings.Contains(sql, w) {
			t.Errorf("%q missing %q", sql, w)
		}
	}
}

func TestReconstructor_InsertSelect(t *testing.T) {
	sql := roundtrip(t, "INSERT INTO Address SELECT AddressID FROM Address")
	if !strings.Contains(sql, "INSERT") || !strings.Contains(sql, "SELECT") {
		t.Errorf("got %q", sql)
	}
}

func TestReconstructor_InsertSingleValues_Direct(t *testing.T) {
	node := map[string]any{
		"node_type": "InsertStatement",
		"table":     rcID("Address"),
		"columns":   []any{},
		"values": []any{
			rcLit("42", "NUMERIC_LITERAL"),
			rcLit("Seattle", "STRING_LITERAL"),
		},
		"value_rows": nil,
		"source":     nil,
	}
	sql := NewReconstructor().ReconstructValue(node)
	for _, w := range []string{"INSERT", "VALUES", "42"} {
		if !strings.Contains(sql, w) {
			t.Errorf("%q missing %q", sql, w)
		}
	}
}

func TestReconstructor_Declare(t *testing.T) {
	s1 := roundtrip(t, "DECLARE @counter INT")
	for _, w := range []string{"DECLARE", "@counter", "INT"} {
		if !strings.Contains(s1, w) {
			t.Errorf("%q missing %q", s1, w)
		}
	}
	s2 := roundtrip(t, "DECLARE @counter INT = 5")
	for _, w := range []string{"DECLARE", "@counter", "5"} {
		if !strings.Contains(s2, w) {
			t.Errorf("%q missing %q", s2, w)
		}
	}
}

func TestReconstructor_SQLExpr_NilAndList(t *testing.T) {
	rc := NewReconstructor()
	if got := rc.sqlExpr(nil); got != "NULL" {
		t.Errorf("sqlExpr(nil) = %q, want NULL", got)
	}
	list := []any{
		rcLit("1", "NUMERIC_LITERAL"),
		rcLit("2", "NUMERIC_LITERAL"),
		rcLit("3", "NUMERIC_LITERAL"),
	}
	if got := rc.sqlExpr(list); got != "(1, 2, 3)" {
		t.Errorf("sqlExpr(list) = %q, want (1, 2, 3)", got)
	}
}

func TestReconstructor_InSubquery(t *testing.T) {
	sql := roundtrip(t, "SELECT AddressID FROM Address WHERE AddressID IN (SELECT AddressID FROM Address WHERE AddressID > 0)")
	if !strings.Contains(sql, "IN") || !strings.Contains(sql, "SELECT") {
		t.Errorf("got %q", sql)
	}

	node := map[string]any{
		"node_type": "SelectStatement", "ctes": []any{}, "top": nil, "top_percent": false,
		"is_distinct": false, "is_star": false,
		"columns": []any{rcID("AddressID")},
		"table":   rcID("Address"), "alias": nil, "joins": []any{}, "applies": []any{},
		"into_table": nil,
		"where": map[string]any{
			"node_type": "BinaryExpressionNode", "op": "NOT IN",
			"left":  rcID("AddressID"),
			"right": rcSelectStarCols("Address", "AddressID"),
		},
		"group_by": []any{}, "having": nil, "order_by": []any{}, "offset_count": nil, "fetch_count": nil,
	}
	got := NewReconstructor().ReconstructValue(node)
	if !strings.Contains(got, "NOT IN") || !strings.Contains(got, "SELECT") {
		t.Errorf("NOT IN subquery -> %q", got)
	}
}

func rcSelectStarCols(table string, col string) map[string]any {
	m := rcSelectStar(table)
	m["is_star"] = false
	m["columns"] = []any{rcID(col)}
	return m
}

func TestReconstructor_Exists(t *testing.T) {
	sql := roundtrip(t, "SELECT AddressID FROM Address a WHERE EXISTS (SELECT 1 FROM Address b WHERE b.AddressID = a.AddressID)")
	if !strings.Contains(sql, "EXISTS") {
		t.Errorf("got %q", sql)
	}
	node := map[string]any{
		"node_type": "FunctionCallNode", "name": "NOT EXISTS",
		"args":  []any{rcSelectStar("Address")},
		"alias": nil,
	}
	if got := NewReconstructor().sqlExpr(node); !strings.Contains(got, "NOT EXISTS") {
		t.Errorf("NOT EXISTS -> %q", got)
	}
}

func TestReconstructor_CaseWithInput(t *testing.T) {
	sql := roundtrip(t, "SELECT CASE AddressID WHEN 1 THEN 'one' ELSE 'other' END FROM Address")
	for _, w := range []string{"CASE", "WHEN", "THEN", "END"} {
		if !strings.Contains(sql, w) {
			t.Errorf("%q missing %q", sql, w)
		}
	}
}

func TestReconstructor_CaseBranchListFormat_Direct(t *testing.T) {
	node := map[string]any{
		"node_type": "CaseExpressionNode",
		"input":     nil,
		"branches": []any{
			[]any{rcLit("1", "NUMERIC_LITERAL"), rcLit("one", "STRING_LITERAL")},
			[]any{rcLit("2", "NUMERIC_LITERAL"), rcLit("two", "STRING_LITERAL")},
		},
		"else":  rcLit("other", "STRING_LITERAL"),
		"alias": nil,
	}
	got := NewReconstructor().sqlExpr(node)
	for _, w := range []string{"CASE", "WHEN", "THEN", "END", "'one'", "'two'"} {
		if !strings.Contains(got, w) {
			t.Errorf("%q missing %q", got, w)
		}
	}
}

func TestReconstructor_Convert(t *testing.T) {
	sql := roundtrip(t, "SELECT CONVERT(INT, AddressID) FROM Address")
	if !strings.Contains(sql, "CONVERT") || !strings.Contains(sql, "INT") {
		t.Errorf("got %q", sql)
	}
	node := map[string]any{
		"node_type":  "CastExpressionNode",
		"expr":       rcID("AddressID"),
		"target":     "VARCHAR(50)",
		"is_convert": true,
	}
	got := NewReconstructor().sqlExpr(node)
	for _, w := range []string{"CONVERT", "VARCHAR(50)", "AddressID"} {
		if !strings.Contains(got, w) {
			t.Errorf("%q missing %q", got, w)
		}
	}
}

func TestReconstructor_JoinTypes(t *testing.T) {
	cross := roundtrip(t, "SELECT a.AddressID FROM Address a CROSS JOIN StateProvince s")
	if !strings.Contains(cross, "CROSS JOIN") {
		t.Errorf("cross join -> %q", cross)
	}
	full := roundtrip(t, "SELECT a.AddressID FROM Address a FULL OUTER JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID")
	if !strings.Contains(full, "FULL OUTER JOIN") {
		t.Errorf("full outer join -> %q", full)
	}
}

func TestReconstructor_ApplyNode_Direct(t *testing.T) {
	rc := NewReconstructor()
	withAlias := map[string]any{
		"node_type": "ApplyNode", "type": "OUTER",
		"subquery": map[string]any{
			"node_type": "SelectStatement", "ctes": []any{}, "top": nil, "top_percent": false,
			"is_distinct": false, "is_star": false,
			"columns": []any{map[string]any{"node_type": "LiteralNode", "value": "1", "type": "NUMERIC_LITERAL", "alias": "val"}},
			"table":   nil, "alias": nil, "joins": []any{}, "applies": []any{}, "into_table": nil,
			"where": nil, "group_by": []any{}, "having": nil, "order_by": []any{}, "offset_count": nil, "fetch_count": nil,
		},
		"alias": "sub",
	}
	got := rc.sqlApply(withAlias)
	for _, w := range []string{"OUTER APPLY", "SELECT", "sub"} {
		if !strings.Contains(got, w) {
			t.Errorf("%q missing %q", got, w)
		}
	}

	noAlias := map[string]any{
		"node_type": "ApplyNode", "type": "CROSS",
		"subquery": rcSelectStar("T"), "alias": nil,
	}
	if got := rc.sqlApply(noAlias); !strings.Contains(got, "CROSS APPLY") {
		t.Errorf("no-alias apply -> %q", got)
	}
}

func TestReconstructor_AssignmentNode_Direct(t *testing.T) {
	node := map[string]any{
		"node_type": "AssignmentNode",
		"column":    rcID("City"),
		"expr":      rcLit("Seattle", "STRING_LITERAL"),
	}
	got := NewReconstructor().sqlAssignment(node)
	for _, w := range []string{"City", "=", "Seattle"} {
		if !strings.Contains(got, w) {
			t.Errorf("%q missing %q", got, w)
		}
	}
}

func TestReconstructor_CTENode_Direct(t *testing.T) {
	node := map[string]any{
		"node_type": "CTENode", "name": "MyCTE", "query": rcSelectStar("Address"),
	}
	got := NewReconstructor().sqlCTE(node)
	for _, w := range []string{"MyCTE", "AS", "SELECT"} {
		if !strings.Contains(got, w) {
			t.Errorf("%q missing %q", got, w)
		}
	}
	// 經 toSQL 分派亦可
	if viaToSQL := NewReconstructor().ReconstructValue(node); viaToSQL != got {
		t.Errorf("toSQL(CTENode)=%q != sqlCTE=%q", viaToSQL, got)
	}
}

// 對照 tests/test_reconstructor_subquery_right.py
func TestReconstructor_BinaryWithSubqueryRight(t *testing.T) {
	node := map[string]any{
		"node_type": "BinaryExpressionNode",
		"op":        "=",
		"left":      map[string]any{"node_type": "IdentifierNode", "name": "col"},
		"right":     map[string]any{"node_type": "SelectStatement", "is_star": true},
	}
	if got := NewReconstructor().ReconstructValue(node); got != "col = (SELECT *)" {
		t.Errorf("got %q, want %q", got, "col = (SELECT *)")
	}
}

func TestReconstructor_TableRef_Direct(t *testing.T) {
	rc := NewReconstructor()
	if got := rc.sqlTableRef(nil, "someAlias"); got != "" {
		t.Errorf("sqlTableRef(nil) = %q, want \"\"", got)
	}
	inner := rcSelectStarCols("Address", "AddressID")
	got := rc.sqlTableRef(inner, "sub")
	if !strings.HasPrefix(got, "(") || !strings.Contains(got, "SELECT") || !strings.Contains(got, "sub") {
		t.Errorf("derived table ref -> %q", got)
	}

	sql := roundtrip(t, "SELECT sub.AddressID FROM (SELECT AddressID FROM Address) sub")
	for _, w := range []string{"SELECT", "FROM", "Address"} {
		if !strings.Contains(sql, w) {
			t.Errorf("%q missing %q", sql, w)
		}
	}
}
