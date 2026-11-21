package birdeye

import (
	"reflect"
	"testing"
)

// 對照 python-final:tests/test_row_filter_suite.py

func rfIdent(name string, quals ...string) map[string]any {
	q := []any{}
	for _, x := range quals {
		q = append(q, x)
	}
	return map[string]any{"node_type": "IdentifierNode", "name": name, "qualifiers": q, "alias": nil}
}
func rfLit(value string, typ ...string) map[string]any {
	t := "STRING_LITERAL"
	if len(typ) > 0 {
		t = typ[0]
	}
	return map[string]any{"node_type": "LiteralNode", "value": value, "type": t, "alias": nil}
}
func rfBin(op string, left, right any) map[string]any {
	return map[string]any{"node_type": "BinaryExpressionNode", "op": op, "left": left, "right": right, "alias": nil}
}
func rfSelect(table any, opts map[string]any) map[string]any {
	m := map[string]any{
		"node_type": "SelectStatement", "table": table, "alias": nil,
		"columns": []any{}, "where": nil, "joins": []any{}, "ctes": []any{},
		"having": nil, "order_by": []any{}, "applies": []any{},
	}
	for k, v := range opts {
		m[k] = v
	}
	return m
}
func rfUpdate(table any, opts map[string]any) map[string]any {
	m := map[string]any{"node_type": "UpdateStatement", "table": table, "alias": nil, "where": nil}
	for k, v := range opts {
		m[k] = v
	}
	return m
}
func rfFilt(schema, table, column string, opv ...string) RowFilter {
	f := RowFilter{Schema: schema, Table: table, Column: column, Operator: "=", Value: "1", ValueType: "LITERAL"}
	if len(opv) > 0 {
		f.Operator = opv[0]
	}
	if len(opv) > 1 {
		f.Value = opv[1]
	}
	return f
}

func samePtr(a, b any) bool {
	return reflect.ValueOf(a).Pointer() == reflect.ValueOf(b).Pointer()
}

var inj = NewRowFilterInjector()

func TestRowFilterInject(t *testing.T) {
	t.Run("empty_filters_returns_original", func(t *testing.T) {
		ast := map[string]any{"node_type": "SelectStatement"}
		if !samePtr(ast, inj.Inject(ast, nil)) {
			t.Fatal("expected same object")
		}
	})
	t.Run("matching_filter_deep_copy_with_where", func(t *testing.T) {
		ast := rfSelect(rfIdent("Product", "SalesLT"), nil)
		res := inj.Inject(ast, []RowFilter{rfFilt("SALESLT", "PRODUCT", "ProductID")})
		if samePtr(ast, res) || res["where"] == nil {
			t.Fatal(res)
		}
	})
}

func TestRowFilterWalk(t *testing.T) {
	f1 := rfFilt("SALESLT", "PRODUCT", "ProductID", "=", "1")

	t.Run("nil_and_nondict_noop", func(t *testing.T) {
		inj.walk(nil, nil)
		inj.walk("string", nil)
	})
	t.Run("list_walks_each", func(t *testing.T) {
		s0 := rfSelect(rfIdent("Product", "SalesLT"), nil)
		s1 := rfSelect(rfIdent("Product", "SalesLT"), nil)
		inj.walk([]any{s0, s1}, []RowFilter{f1})
		if s0["where"] == nil || s1["where"] == nil {
			t.Fatal()
		}
	})
	t.Run("script_node", func(t *testing.T) {
		s := rfSelect(rfIdent("Product", "SalesLT"), nil)
		script := map[string]any{"node_type": "ScriptNode", "statements": []any{s}}
		inj.walk(script, []RowFilter{f1})
		if s["where"] == nil {
			t.Fatal()
		}
		inj.walk(map[string]any{"node_type": "ScriptNode", "statements": nil}, []RowFilter{f1})
	})
	t.Run("select_no_match", func(t *testing.T) {
		s := rfSelect(rfIdent("Address"), nil)
		inj.walk(s, []RowFilter{rfFilt("", "PRODUCT", "ID")})
		if s["where"] != nil {
			t.Fatal()
		}
	})
	t.Run("select_and_with_existing", func(t *testing.T) {
		existing := rfBin("=", rfIdent("Col"), rfLit("'x'"))
		s := rfSelect(rfIdent("Product", "SalesLT"), map[string]any{"where": existing})
		inj.walk(s, []RowFilter{f1})
		if s["where"].(map[string]any)["op"] != "AND" {
			t.Fatal(s["where"])
		}
	})
	t.Run("update_and_delete", func(t *testing.T) {
		u := rfUpdate(rfIdent("Product", "SalesLT"), nil)
		inj.walk(u, []RowFilter{f1})
		if u["where"] == nil {
			t.Fatal("update")
		}
		d := map[string]any{"node_type": "DeleteStatement", "table": rfIdent("Product", "SalesLT"), "alias": nil, "where": nil}
		inj.walk(d, []RowFilter{f1})
		if d["where"] == nil {
			t.Fatal("delete")
		}
	})
	t.Run("union_and_if", func(t *testing.T) {
		l := rfSelect(rfIdent("Product", "SalesLT"), nil)
		r := rfSelect(rfIdent("Product", "SalesLT"), nil)
		inj.walk(map[string]any{"node_type": "UnionStatement", "left": l, "right": r}, []RowFilter{f1})
		if l["where"] == nil || r["where"] == nil {
			t.Fatal("union")
		}
		th := rfSelect(rfIdent("Product", "SalesLT"), nil)
		el := rfSelect(rfIdent("Product", "SalesLT"), nil)
		inj.walk(map[string]any{"node_type": "IfStatement", "then_block": []any{th}, "else_block": []any{el}}, []RowFilter{f1})
		if th["where"] == nil || el["where"] == nil {
			t.Fatal("if")
		}
		inj.walk(map[string]any{"node_type": "IfStatement", "then_block": nil, "else_block": nil}, []RowFilter{f1})
	})
	t.Run("update_no_match_and_unknown_node", func(t *testing.T) {
		u := rfUpdate(rfIdent("Product", "SalesLT"), nil)
		inj.walk(u, []RowFilter{rfFilt("", "ADDRESS", "ID")})
		if u["where"] != nil {
			t.Fatal()
		}
		inj.walk(map[string]any{"node_type": "UnknownNode", "data": 42}, []RowFilter{f1})
	})
}

func TestRowFilterWalkSubqueries(t *testing.T) {
	f1 := rfFilt("SALESLT", "PRODUCT", "ProductID", "=", "1")
	mkInner := func() map[string]any { return rfSelect(rfIdent("Product", "SalesLT"), nil) }

	cases := []struct {
		name  string
		build func() (outer map[string]any, inner map[string]any)
		want  bool // inner["where"] != nil
	}{
		{"cte", func() (map[string]any, map[string]any) {
			in := mkInner()
			return rfSelect(rfIdent("Address"), map[string]any{"ctes": []any{map[string]any{"name": "c", "query": in}}}), in
		}, true},
		{"table_subquery", func() (map[string]any, map[string]any) {
			in := mkInner()
			return rfSelect(in, map[string]any{"alias": "sub"}), in
		}, true},
		{"join_subquery", func() (map[string]any, map[string]any) {
			in := mkInner()
			return rfSelect(rfIdent("Address"), map[string]any{"joins": []any{map[string]any{"table": in, "alias": "p"}}}), in
		}, true},
		{"join_regular_table", func() (map[string]any, map[string]any) {
			return rfSelect(rfIdent("Address"), map[string]any{"joins": []any{map[string]any{"table": rfIdent("Customer", "SalesLT"), "alias": "c"}}}), nil
		}, false},
		{"apply", func() (map[string]any, map[string]any) {
			in := mkInner()
			return rfSelect(rfIdent("Address"), map[string]any{"applies": []any{map[string]any{"subquery": in}}}), in
		}, true},
		{"column_expr", func() (map[string]any, map[string]any) {
			in := mkInner()
			return rfSelect(rfIdent("Address"), map[string]any{"columns": []any{in}}), in
		}, true},
		{"where_expr", func() (map[string]any, map[string]any) {
			in := mkInner()
			return rfSelect(rfIdent("Address"), map[string]any{"where": rfBin("IN", rfIdent("ID"), in)}), in
		}, true},
		{"having_expr", func() (map[string]any, map[string]any) {
			in := mkInner()
			return rfSelect(rfIdent("Address"), map[string]any{"having": rfBin(">", rfIdent("cnt"), in)}), in
		}, true},
		{"order_by", func() (map[string]any, map[string]any) {
			in := mkInner()
			return rfSelect(rfIdent("Address"), map[string]any{"order_by": []any{map[string]any{"column": in, "direction": "ASC"}}}), in
		}, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			outer, inner := c.build()
			inj.walk(outer, []RowFilter{f1})
			if c.want {
				if inner["where"] == nil {
					t.Fatal("expected inner where injected")
				}
			} else if outer["where"] != nil {
				t.Fatal("expected outer where nil")
			}
		})
	}
}

func TestRowFilterWalkExpr(t *testing.T) {
	f1 := rfFilt("SALESLT", "PRODUCT", "ProductID", "=", "1")
	mk := func() map[string]any { return rfSelect(rfIdent("Product", "SalesLT"), nil) }

	inj.walkExpr(nil, nil)
	inj.walkExpr(99, nil)

	t.Run("list", func(t *testing.T) {
		in := mk()
		inj.walkExpr([]any{in, nil}, []RowFilter{f1})
		if in["where"] == nil {
			t.Fatal()
		}
	})
	t.Run("select_union_binary_fn_cast_between_case", func(t *testing.T) {
		checks := []func() map[string]any{
			func() map[string]any { in := mk(); inj.walkExpr(in, []RowFilter{f1}); return in },
			func() map[string]any {
				l := mk()
				inj.walkExpr(map[string]any{"node_type": "UnionStatement", "left": l, "right": mk()}, []RowFilter{f1})
				return l
			},
			func() map[string]any {
				in := mk()
				inj.walkExpr(rfBin("IN", rfIdent("Col"), []any{in}), []RowFilter{f1})
				return in
			},
			func() map[string]any {
				in := mk()
				inj.walkExpr(rfBin("=", rfIdent("Col"), in), []RowFilter{f1})
				return in
			},
			func() map[string]any {
				in := mk()
				inj.walkExpr(map[string]any{"node_type": "FunctionCallNode", "name": "COUNT", "args": []any{in}}, []RowFilter{f1})
				return in
			},
			func() map[string]any {
				in := mk()
				inj.walkExpr(map[string]any{"node_type": "CastExpressionNode", "expr": in}, []RowFilter{f1})
				return in
			},
			func() map[string]any {
				in := mk()
				inj.walkExpr(map[string]any{"node_type": "BetweenExpressionNode", "target": in,
					"low": rfLit("1", "NUMERIC_LITERAL"), "high": rfLit("10", "NUMERIC_LITERAL")}, []RowFilter{f1})
				return in
			},
			func() map[string]any {
				in := mk()
				inj.walkExpr(map[string]any{"node_type": "CaseExpressionNode", "input": in, "branches": []any{}, "else": nil}, []RowFilter{f1})
				return in
			},
		}
		for i, fn := range checks {
			if fn()["where"] == nil {
				t.Errorf("check %d: inner where not injected", i)
			}
		}
	})
	t.Run("case_when_then_else", func(t *testing.T) {
		w, th, el := mk(), mk(), mk()
		inj.walkExpr(map[string]any{"node_type": "CaseExpressionNode", "input": nil,
			"branches": []any{map[string]any{"when": w, "then": th}}, "else": el}, []RowFilter{f1})
		if w["where"] == nil || th["where"] == nil || el["where"] == nil {
			t.Fatal()
		}
	})
}

func TestRowFilterAliasEntries(t *testing.T) {
	eq := func(a []aliasEntry, b ...aliasEntry) bool { return reflect.DeepEqual(a, []aliasEntry(b)) }

	if !eq(buildAliasEntries(rfSelect(rfIdent("Product"), nil)), aliasEntry{"", "PRODUCT", "Product"}) {
		t.Fatal("simple")
	}
	if !eq(buildAliasEntries(rfSelect(rfIdent("Product", "SalesLT"), map[string]any{"alias": "p"})), aliasEntry{"SALESLT", "PRODUCT", "p"}) {
		t.Fatal("schema+alias")
	}
	if len(buildAliasEntries(rfSelect(rfSelect(rfIdent("Product"), nil), nil))) != 0 {
		t.Fatal("subquery table skipped")
	}
	if len(buildAliasEntries(rfSelect(nil, nil))) != 0 {
		t.Fatal("nil table")
	}
	emptyName := map[string]any{"node_type": "IdentifierNode", "name": "", "qualifiers": []any{}, "alias": nil}
	if len(buildAliasEntries(rfSelect(emptyName, nil))) != 0 {
		t.Fatal("empty name")
	}
	je := buildAliasEntries(rfSelect(rfIdent("Order", "SalesLT"),
		map[string]any{"joins": []any{map[string]any{"table": rfIdent("Product", "SalesLT"), "alias": "p"}}}))
	if len(je) != 2 || je[1] != (aliasEntry{"SALESLT", "PRODUCT", "p"}) {
		t.Fatal("join entries", je)
	}

	// DML
	if !eq(buildAliasEntriesDML(rfUpdate(rfIdent("Product", "SalesLT"), nil)), aliasEntry{"SALESLT", "PRODUCT", "Product"}) {
		t.Fatal("dml valid")
	}
	if len(buildAliasEntriesDML(map[string]any{"node_type": "UpdateStatement", "table": nil})) != 0 {
		t.Fatal("dml no table")
	}
	if len(buildAliasEntriesDML(map[string]any{"table": rfSelect(rfIdent("P"), nil)})) != 0 {
		t.Fatal("dml non-ident")
	}
	if !eq(buildAliasEntriesDML(map[string]any{"node_type": "UpdateStatement", "table": rfIdent("Product", "SalesLT"), "alias": "p"}), aliasEntry{"SALESLT", "PRODUCT", "p"}) {
		t.Fatal("dml alias")
	}
}

func TestRowFilterMatchAndCondition(t *testing.T) {
	e := []aliasEntry{{"SALESLT", "PRODUCT", "p"}}

	if len(matchFilters([]aliasEntry{{"", "PRODUCT", "Product"}}, []RowFilter{rfFilt("", "PRODUCT", "ID")})) != 1 {
		t.Fatal("match table only")
	}
	if len(matchFilters(e, []RowFilter{rfFilt("SALESLT", "PRODUCT", "ID")})) != 1 {
		t.Fatal("match schema")
	}
	if len(matchFilters([]aliasEntry{{"", "ADDRESS", "a"}}, []RowFilter{rfFilt("", "PRODUCT", "ID")})) != 0 {
		t.Fatal("wrong table")
	}
	if len(matchFilters([]aliasEntry{{"HR", "PRODUCT", "p"}}, []RowFilter{rfFilt("SALESLT", "PRODUCT", "ID")})) != 0 {
		t.Fatal("wrong schema")
	}
	pm := matchFilters(e, []RowFilter{rfFilt("SALESLT", "PRODUCT", "ID"), rfFilt("", "ADDRESS", "City")})
	if len(pm) != 1 || pm[0].Column != "ID" {
		t.Fatal("partial match")
	}

	// makeCondition
	c := makeCondition(RowFilter{Schema: "SALESLT", Table: "PRODUCT", Column: "ProductID", Operator: "=", Value: "42", ValueType: "LITERAL"}, e)
	if c["op"] != "=" || c["left"].(map[string]any)["name"] != "ProductID" || c["right"].(map[string]any)["value"] != "42" {
		t.Fatal("literal equals", c)
	}
	cin := makeCondition(RowFilter{Table: "PRODUCT", Column: "ProductID", Operator: "IN", Value: "1,2,3"}, e)
	if cin["op"] != "IN" || len(cin["right"].([]any)) != 3 {
		t.Fatal("in", cin)
	}
	cni := makeCondition(RowFilter{Table: "PRODUCT", Column: "Status", Operator: "NOT IN", Value: "X,Y"}, e)
	if cni["op"] != "NOT IN" || len(cni["right"].([]any)) != 2 {
		t.Fatal("not in")
	}
	if makeCondition(RowFilter{Table: "PRODUCT", Column: "Name", Operator: "LIKE", Value: "Bike%"}, e)["op"] != "LIKE" {
		t.Fatal("like")
	}
	sub := map[string]any{"node_type": "SelectStatement"}
	cs := makeCondition(RowFilter{Schema: "SALESLT", Table: "PRODUCT", Column: "ProductID", Operator: "IN", Value: sub, ValueType: "SUBQUERY"}, e)
	if !samePtr(cs["right"], sub) {
		t.Fatal("subquery dict")
	}
	func() {
		defer func() {
			if r := recover(); r == nil {
				t.Fatal("expected panic for string SUBQUERY")
			}
		}()
		makeCondition(RowFilter{Table: "PRODUCT", Column: "ProductID", Operator: "IN", Value: "SELECT 1", ValueType: "SUBQUERY"}, e)
	}()
	if q := makeCondition(rfFilt("SALESLT", "PRODUCT", "ProductID"), e)["left"].(map[string]any)["qualifiers"].([]any); len(q) != 1 || q[0] != "p" {
		t.Fatal("qualifier")
	}
	if makeCondition(RowFilter{Table: "PRODUCT", Column: "ID", Value: "5"}, []aliasEntry{{"", "PRODUCT", "Product"}})["op"] != "=" {
		t.Fatal("defaults")
	}
}

func TestRowFilterMakeLiteral(t *testing.T) {
	for _, v := range []string{"42", "-5", "3.14", "1e10"} {
		if makeLiteral(v)["type"] != "NUMERIC_LITERAL" {
			t.Errorf("%q should be numeric", v)
		}
	}
	if l := makeLiteral("hello"); l["type"] != "STRING_LITERAL" || l["value"] != "'hello'" {
		t.Fatal("ascii string", l)
	}
	if makeLiteral("it's")["value"] != "'it''s'" {
		t.Fatal("escape")
	}
	if l := makeLiteral("你好"); l["type"] != "STRING_LITERAL" || l["value"].(string)[:2] != "N'" {
		t.Fatal("unicode", l)
	}
}

func TestRowFilterFindQualifierAndAnd(t *testing.T) {
	if findQualifier("SALESLT", "PRODUCT", []aliasEntry{{"SALESLT", "PRODUCT", "p"}}) != "p" {
		t.Fatal("match schema")
	}
	if findQualifier("", "PRODUCT", []aliasEntry{{"", "PRODUCT", "Product"}}) != "Product" {
		t.Fatal("no schema")
	}
	if findQualifier("", "PRODUCT", []aliasEntry{{"", "ADDRESS", "a"}}) != "PRODUCT" {
		t.Fatal("no match → table up")
	}
	if findQualifier("SALESLT", "EMPLOYEE", []aliasEntry{{"HR", "EMPLOYEE", "e"}, {"SALESLT", "EMPLOYEE", "emp"}}) != "emp" {
		t.Fatal("schema disambiguates")
	}

	c := func(col string) map[string]any { return rfBin("=", rfIdent(col), rfLit("'1'")) }
	if andConditions(nil, nil) != nil {
		t.Fatal("empty → nil")
	}
	one := c("A")
	if !samePtr(andConditions(nil, []any{one}), one) {
		t.Fatal("single no existing")
	}
	existing := c("existing")
	cc := c("A")
	r := andConditions(existing, []any{cc}).(map[string]any)
	if r["op"] != "AND" || !samePtr(r["left"], existing) || !samePtr(r["right"], cc) {
		t.Fatal("single with existing")
	}
	c1, c2, c3 := c("A"), c("B"), c("C")
	r2 := andConditions(nil, []any{c1, c2, c3}).(map[string]any)
	if r2["op"] != "AND" || !samePtr(r2["right"], c3) {
		t.Fatal("chain")
	}
	if l := r2["left"].(map[string]any); l["op"] != "AND" || !samePtr(l["right"], c2) {
		t.Fatal("chain left")
	}
}
