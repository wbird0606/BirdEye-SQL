package birdeye

import (
	"encoding/json"
	"testing"
)

// 對照 tests/test_intent_coverage_suite.py 與 tests/test_intent_coverage_extra.py
// —— IntentExtractor 的內部方法與防禦性分支。

const intentCovCSV = `table_name,column_name,data_type
Customer,CustomerID,int
Customer,FirstName,nvarchar
Customer,LastName,nvarchar
Customer,EmailAddress,nvarchar
Customer,Phone,nvarchar
Customer,SalesPerson,nvarchar
CustomerAddress,CustomerID,int
CustomerAddress,AddressID,int
Address,AddressID,int
Address,AddressLine1,nvarchar
Address,AddressLine2,nvarchar
Address,City,nvarchar
Address,StateProvince,nvarchar
Address,PostalCode,nvarchar
SalesOrderHeader,SalesOrderID,int
SalesOrderHeader,CustomerID,int
SalesOrderHeader,TotalDue,money
`

// intentParseOnly：lex + parse + serialize，不跑 binder，回傳 map。
func intentParseOnly(t *testing.T, sql string) map[string]any {
	t.Helper()
	js := NewSerializer().ToJSON(mustParse(t, sql))
	var m map[string]any
	if err := json.Unmarshal([]byte(js), &m); err != nil {
		t.Fatalf("json: %v", err)
	}
	return m
}

func tableIn(tabs [][2]string, name string) bool {
	for _, tb := range tabs {
		if tb[1] == name {
			return true
		}
	}
	return false
}

func TestIntentCoverage_ExtractFromStr(t *testing.T) {
	reg := mkReg(t, intentCovCSV)
	res, err := NewRunner(reg).Run("SELECT CustomerID FROM SalesLT.Customer", nil)
	if err != nil {
		t.Fatal(err)
	}
	var m any
	json.Unmarshal([]byte(res.JSON), &m)
	viaExtract := NewIntentExtractor().Extract(m)
	viaStr, err := NewIntentExtractor().ExtractFromStr(res.JSON)
	if err != nil {
		t.Fatal(err)
	}
	if len(viaExtract) != len(viaStr) {
		t.Fatalf("extract %d vs extract_from_str %d", len(viaExtract), len(viaStr))
	}
	for i := range viaExtract {
		if !intentSame(viaExtract[i], viaStr[i]) {
			t.Errorf("[%d] %+v != %+v", i, viaExtract[i], viaStr[i])
		}
	}

	it, _ := NewIntentExtractor().ExtractFromStr(
		mustRunJSON(t, reg, "SELECT FirstName FROM SalesLT.Customer"))
	if !hasIntent(it, "Customer", "FirstName", "READ", "") {
		t.Errorf("%+v", it)
	}
}

func mustRunJSON(t *testing.T, reg *MetadataRegistry, sql string) string {
	t.Helper()
	res, err := NewRunner(reg).Run(sql, nil)
	if err != nil {
		t.Fatalf("run %q: %v", sql, err)
	}
	return res.JSON
}

func intentSame(a, b Intent) bool {
	if a.Schema != b.Schema || a.Table != b.Table || a.Intent != b.Intent {
		return false
	}
	if (a.Column == nil) != (b.Column == nil) {
		return false
	}
	return a.Column == nil || *a.Column == *b.Column
}

func TestIntentCoverage_ExpandStarFallbacks(t *testing.T) {
	reg := mkReg(t, intentCovCSV)
	ie := NewIntentExtractor()

	// 未知表 → 保留原意圖
	unknown := []Intent{{Schema: "dbo", Table: "NonExistentTable", Column: nil, Intent: "READ"}}
	r1 := ie.ExpandStarIntents(unknown, reg)
	if len(r1) != 1 || r1[0].Table != "NonExistentTable" || r1[0].Column != nil {
		t.Errorf("未知表應原樣保留：%+v", r1)
	}

	// 已知表 → 展開
	known := []Intent{{Schema: "", Table: "Customer", Column: nil, Intent: "READ"}}
	r2 := ie.ExpandStarIntents(known, reg)
	if !(len(r2) > 1 || (len(r2) == 1 && r2[0].Column != nil)) {
		t.Errorf("已知表應展開：%+v", r2)
	}

	// 非 READ 的 column=nil 不展開
	del := []Intent{{Schema: "", Table: "Customer", Column: nil, Intent: "DELETE"}}
	r3 := ie.ExpandStarIntents(del, reg)
	if len(r3) != 1 || r3[0].Intent != "DELETE" || r3[0].Column != nil {
		t.Errorf("DELETE 不應展開：%+v", r3)
	}
}

func TestIntentCoverage_ExtractTables(t *testing.T) {
	ie := NewIntentExtractor()
	cases := []struct {
		sql   string
		wants []string
	}{
		{"SELECT CustomerID FROM SalesLT.Customer", []string{"Customer"}},
		{"SELECT c.CustomerID FROM SalesLT.Customer c JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID", []string{"Customer", "CustomerAddress"}},
		{"SELECT CustomerID FROM SalesLT.Customer UNION SELECT AddressID FROM SalesLT.Address", []string{"Customer", "Address"}},
		{"UPDATE SalesLT.Customer SET FirstName = 'Alice' WHERE CustomerID = 1", []string{"Customer"}},
		{"DELETE FROM SalesLT.Customer WHERE CustomerID = 1", []string{"Customer"}},
		{"TRUNCATE TABLE SalesLT.Customer", []string{"Customer"}},
		{"INSERT INTO SalesLT.Customer (FirstName) VALUES ('Alice')", []string{"Customer"}},
		{"INSERT INTO SalesLT.Customer (FirstName) SELECT FirstName FROM SalesLT.Address", []string{"Customer", "Address"}},
		{"SELECT CustomerID FROM SalesLT.Customer WHERE CustomerID IN (SELECT CustomerID FROM SalesLT.CustomerAddress)", []string{"Customer", "CustomerAddress"}},
		{"SELECT CustomerID FROM SalesLT.Customer WHERE CustomerID > (SELECT MIN(CustomerID) FROM SalesLT.Address)", []string{"Address"}},
		{"WITH cte AS (SELECT CustomerID FROM SalesLT.Customer) SELECT CustomerID FROM cte", []string{"Customer"}},
		{"SELECT sub.CustomerID FROM (SELECT CustomerID FROM SalesLT.Customer) sub", []string{"Customer"}},
		{"SELECT CustomerID, COUNT(*) FROM SalesLT.Customer GROUP BY CustomerID", []string{"Customer"}},
		{"SELECT CustomerID FROM SalesLT.Customer ORDER BY CustomerID", []string{"Customer"}},
		{"SELECT c.CustomerID, sub.x FROM SalesLT.Customer c CROSS APPLY (SELECT 1 AS x) sub", []string{"Customer"}},
		{"SELECT CustomerID FROM SalesLT.Customer WHERE CAST(CustomerID AS VARCHAR) = '1'", []string{"Customer"}},
		{"SELECT CustomerID FROM SalesLT.Customer WHERE CustomerID BETWEEN 1 AND 100", []string{"Customer"}},
		{"SELECT CustomerID FROM SalesLT.Customer WHERE CASE WHEN CustomerID > 0 THEN 1 ELSE 0 END = 1", []string{"Customer"}},
	}
	for _, c := range cases {
		tabs := ie.ExtractTables(intentParseOnly(t, c.sql))
		for _, w := range c.wants {
			if !tableIn(tabs, w) {
				t.Errorf("%q -> %v missing %q", c.sql, tabs, w)
			}
		}
	}

	// ('SalesLT', 'Customer') tuple 形式
	tabs := ie.ExtractTables(intentParseOnly(t, "SELECT CustomerID FROM SalesLT.Customer"))
	found := false
	for _, tb := range tabs {
		if tb[0] == "SalesLT" && tb[1] == "Customer" {
			found = true
		}
	}
	if !found {
		t.Errorf("預期 (SalesLT, Customer)：%v", tabs)
	}
}

func TestIntentCoverage_WalkListAndStarNoBinder(t *testing.T) {
	ie := NewIntentExtractor()

	// _walk list handling：多語句包成 list
	ast1 := intentParseOnly(t, "SELECT CustomerID FROM SalesLT.Customer")
	ast2 := intentParseOnly(t, "SELECT AddressID FROM SalesLT.Address")
	it := ie.Extract([]any{ast1, ast2})
	names := map[string]bool{}
	for _, i := range it {
		names[i.Table] = true
	}
	if !names["Customer"] || !names["Address"] {
		t.Errorf("list 走訪應涵蓋兩表：%+v", it)
	}

	// is_star=true 但無 columns（parse-only，binder 未展開）→ table-level READ
	starAst := intentParseOnly(t, "SELECT * FROM SalesLT.Customer")
	starIt := NewIntentExtractor().Extract(starAst)
	n := 0
	for _, i := range starIt {
		if i.Table == "Customer" && i.Intent == "READ" {
			n++
		}
	}
	if n == 0 {
		t.Errorf("SELECT *（parse-only）應至少一筆 Customer READ：%+v", starIt)
	}

	// SELECT INTO → 目的表 INSERT
	intoAst := intentParseOnly(t, "SELECT CustomerID INTO #TmpCustomer FROM SalesLT.Customer")
	intoIt := NewIntentExtractor().Extract(intoAst)
	ok := false
	for _, i := range intoIt {
		if i.Table == "#TmpCustomer" && i.Intent == "INSERT" {
			ok = true
		}
	}
	if !ok {
		t.Errorf("SELECT INTO 應對目的表產生 INSERT：%+v", intoIt)
	}
}

func TestIntentCoverage_WalkInternals(t *testing.T) {
	// _walk(nil) 立即返回
	NewIntentExtractor().walk(nil, &[]Intent{}, strSetT{})

	// _walk_update 無 table → 立即返回
	var iu []Intent
	NewIntentExtractor().walkUpdate(map[string]any{"node_type": "UpdateStatement", "set": []any{}, "where": nil}, &iu, strSetT{})
	if len(iu) != 0 {
		t.Errorf("walkUpdate 無 table 應空：%+v", iu)
	}

	// _walk_update 帶 alias
	var iu2 []Intent
	NewIntentExtractor().walkUpdate(map[string]any{
		"node_type": "UpdateStatement",
		"table":     map[string]any{"node_type": "IdentifierNode", "name": "Customer", "qualifiers": []any{"SalesLT"}},
		"alias":     "c",
		"set": []any{map[string]any{
			"column": map[string]any{"node_type": "IdentifierNode", "name": "FirstName", "qualifiers": []any{"c"}},
			"expr":   map[string]any{"node_type": "LiteralNode", "value": "Alice", "type": "STRING_LITERAL"},
		}},
		"where": nil,
	}, &iu2, strSetT{})
	if !anyIntent(iu2, "UPDATE") {
		t.Errorf("walkUpdate alias 應產生 UPDATE：%+v", iu2)
	}

	// _walk_delete 無 table → 立即返回
	var id []Intent
	NewIntentExtractor().walkDelete(map[string]any{"node_type": "DeleteStatement", "where": nil}, &id, strSetT{})
	if len(id) != 0 {
		t.Errorf("walkDelete 無 table 應空：%+v", id)
	}

	// _walk_delete 帶 alias
	var id2 []Intent
	NewIntentExtractor().walkDelete(map[string]any{
		"node_type": "DeleteStatement",
		"table":     map[string]any{"node_type": "IdentifierNode", "name": "Customer", "qualifiers": []any{"SalesLT"}},
		"alias":     "c", "where": nil,
	}, &id2, strSetT{})
	if !anyIntent(id2, "DELETE") {
		t.Errorf("walkDelete alias 應產生 DELETE：%+v", id2)
	}

	// _walk_insert 無 table → 立即返回
	var ii []Intent
	NewIntentExtractor().walkInsert(map[string]any{"node_type": "InsertStatement", "columns": []any{}, "source": nil}, &ii, strSetT{})
	if len(ii) != 0 {
		t.Errorf("walkInsert 無 table 應空：%+v", ii)
	}

	// _walk_subquery：UnionStatement 與 else 分支不 panic
	sel := func() map[string]any {
		return map[string]any{"node_type": "SelectStatement", "table": nil, "columns": []any{},
			"ctes": []any{}, "joins": []any{}, "applies": []any{}, "where": nil,
			"group_by": []any{}, "having": nil, "order_by": []any{}, "is_star": false}
	}
	var isq []Intent
	NewIntentExtractor().walkSubquery(map[string]any{"node_type": "UnionStatement", "left": sel(), "right": sel()}, &isq, strSetT{}, newAliasMap())
	NewIntentExtractor().walkSubquery(map[string]any{"node_type": "LiteralNode", "value": "1"}, &isq, strSetT{}, newAliasMap())
	NewIntentExtractor().walkSubquery(nil, &isq, strSetT{}, newAliasMap())

	// _build_alias_map：table 為 nil
	var ib []Intent
	am, derived := NewIntentExtractor().buildAliasMap(map[string]any{
		"node_type": "SelectStatement", "table": nil, "alias": nil, "joins": []any{}, "columns": []any{}, "is_star": false,
	}, strSetT{}, &ib)
	if len(am.order) != 0 || len(derived) != 0 {
		t.Errorf("buildAliasMap(table=nil) 應皆空：am=%v derived=%v", am.order, derived)
	}
}

func anyIntent(items []Intent, intent string) bool {
	for _, i := range items {
		if i.Intent == intent {
			return true
		}
	}
	return false
}

func TestIntentCoverage_TableInfoAndResolveCol(t *testing.T) {
	// _table_info(nil)
	s, tb := tableInfo(nil)
	if s != "" || tb != "" {
		t.Errorf("tableInfo(nil) = %q,%q", s, tb)
	}

	// 大小寫不敏感的 qualifier fallback
	am := newAliasMap()
	am.set("customer", schemaTable{"SalesLT", "Customer"})
	sc, tc, cc := resolveCol(map[string]any{
		"node_type": "IdentifierNode", "name": "CustomerID", "qualifiers": []any{"CUSTOMER"},
	}, am)
	if tc != "Customer" || cc != "CustomerID" || sc != "SalesLT" {
		t.Errorf("case-insensitive resolve = %q,%q,%q", sc, tc, cc)
	}

	am2 := newAliasMap()
	am2.set("CUSTOMER", schemaTable{"SalesLT", "Customer"})
	_, tc2, cc2 := resolveCol(map[string]any{
		"node_type": "IdentifierNode", "name": "FirstName", "qualifiers": []any{"customer"},
	}, am2)
	if tc2 != "Customer" || cc2 != "FirstName" {
		t.Errorf("resolve = %q,%q", tc2, cc2)
	}

	// 唯一表 fallback（無 qualifier、無 resolved_table）
	am3 := newAliasMap()
	am3.set("Customer", schemaTable{"SalesLT", "Customer"})
	sc3, tc3, cc3 := resolveCol(map[string]any{
		"node_type": "IdentifierNode", "name": "FirstName", "qualifiers": []any{},
	}, am3)
	if sc3 != "SalesLT" || tc3 != "Customer" || cc3 != "FirstName" {
		t.Errorf("unique fallback = %q,%q,%q", sc3, tc3, cc3)
	}

	// 多表且無 qualifier → table 為空（呼叫端會略過）
	am4 := newAliasMap()
	am4.set("Customer", schemaTable{"SalesLT", "Customer"})
	am4.set("Address", schemaTable{"SalesLT", "Address"})
	_, tc4, cc4 := resolveCol(map[string]any{
		"node_type": "IdentifierNode", "name": "SomeColumn", "qualifiers": []any{},
	}, am4)
	if tc4 != "" || cc4 != "SomeColumn" {
		t.Errorf("ambiguous = table %q col %q（預期 table 空）", tc4, cc4)
	}

	// resolved_table（binder 設定）優先於 fallback
	sc5, tc5, cc5 := resolveCol(map[string]any{
		"node_type": "IdentifierNode", "name": "CustomerID", "qualifiers": []any{}, "resolved_table": "Customer",
	}, am4)
	if sc5 != "SalesLT" || tc5 != "Customer" || cc5 != "CustomerID" {
		t.Errorf("resolved_table = %q,%q,%q", sc5, tc5, cc5)
	}
}

func TestIntentCoverage_BehaviouralLocalRunner(t *testing.T) {
	reg := mkReg(t, intentCovCSV)

	t.Run("cross_apply_inner_columns", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT c.FirstName, sub.SalesOrderID FROM SalesLT.Customer c "+
			"CROSS APPLY (SELECT TOP 1 SalesOrderID FROM SalesLT.SalesOrderHeader soh WHERE soh.CustomerID = c.CustomerID) sub")
		if !hasIntent(it, "SalesOrderHeader", "SalesOrderID", "READ", "") ||
			!hasIntent(it, "SalesOrderHeader", "CustomerID", "FILTER", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("union_both_sides", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT CustomerID FROM SalesLT.Customer UNION SELECT CustomerID FROM SalesLT.SalesOrderHeader")
		if !hasIntent(it, "Customer", "CustomerID", "READ", "") ||
			!hasIntent(it, "SalesOrderHeader", "CustomerID", "READ", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("union_where_one_side", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT CustomerID FROM SalesLT.Customer WHERE CustomerID = 1 UNION SELECT CustomerID FROM SalesLT.SalesOrderHeader")
		if !hasIntent(it, "Customer", "CustomerID", "FILTER", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("derived_table_outer_ref_skipped", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT x.CustomerID FROM (SELECT CustomerID FROM SalesLT.Customer) x")
		if !hasIntent(it, "Customer", "CustomerID", "READ", "") {
			t.Errorf("%+v", it)
		}
		for _, i := range it {
			if i.Table == "x" {
				t.Errorf("derived alias 'x' 不應成為 table：%+v", it)
			}
		}
	})

	t.Run("cast_expression_column", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT CAST(CustomerID AS VARCHAR) FROM SalesLT.Customer")
		if !hasIntent(it, "Customer", "CustomerID", "READ", "") {
			t.Errorf("%+v", it)
		}
		it2 := intentsOf(t, reg, "SELECT FirstName FROM SalesLT.Customer WHERE CAST(CustomerID AS VARCHAR) = '1'")
		if !hasIntent(it2, "Customer", "CustomerID", "FILTER", "") {
			t.Errorf("%+v", it2)
		}
	})

	t.Run("between_filter_and_read", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT FirstName FROM SalesLT.Customer WHERE CustomerID BETWEEN 1 AND 10")
		if !hasIntent(it, "Customer", "CustomerID", "FILTER", "") {
			t.Errorf("%+v", it)
		}
		it2 := intentsOf(t, reg, "SELECT CASE WHEN CustomerID BETWEEN 1 AND 100 THEN 'low' ELSE 'high' END FROM SalesLT.Customer")
		if !hasIntent(it2, "Customer", "CustomerID", "READ", "") {
			t.Errorf("%+v", it2)
		}
	})

	t.Run("subquery_in_where_in_clause", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT FirstName FROM SalesLT.Customer WHERE CustomerID IN (SELECT CustomerID FROM SalesLT.Customer WHERE CustomerID = 1)")
		if !hasIntent(it, "Customer", "FirstName", "READ", "") ||
			!hasIntent(it, "Customer", "CustomerID", "FILTER", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("update_set_rhs_read", func(t *testing.T) {
		it := intentsOf(t, reg, "UPDATE SalesLT.Customer SET FirstName = LastName WHERE CustomerID = 1")
		if !hasIntent(it, "Customer", "FirstName", "UPDATE", "") {
			t.Errorf("%+v", it)
		}
		if !hasIntent(it, "Customer", "LastName", "READ", "") && !hasIntent(it, "Customer", "LastName", "UPDATE", "") {
			t.Errorf("RHS LastName 應被萃取：%+v", it)
		}
		if !hasIntent(it, "Customer", "CustomerID", "FILTER", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("join_table_registered", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT c.FirstName, ca.AddressID FROM SalesLT.Customer AS c JOIN SalesLT.CustomerAddress AS ca ON c.CustomerID = ca.CustomerID")
		checks := [][3]string{
			{"Customer", "FirstName", "READ"},
			{"Customer", "CustomerID", "FILTER"},
			{"CustomerAddress", "CustomerID", "FILTER"},
			{"CustomerAddress", "AddressID", "READ"},
		}
		for _, c := range checks {
			if !hasIntent(it, c[0], c[1], c[2], "") {
				t.Errorf("缺少 %v\n%+v", c, it)
			}
		}
	})

	t.Run("truncate_delete_intent", func(t *testing.T) {
		it := intentsOf(t, reg, "TRUNCATE TABLE SalesLT.Customer")
		if !hasIntent(it, "Customer", tableLevel, "DELETE", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("insert_without_columns_table_level", func(t *testing.T) {
		it := NewIntentExtractor().Extract(intentParseOnly(t, "INSERT INTO SalesLT.Customer VALUES ('Alice', 'Smith')"))
		if !hasIntent(it, "Customer", tableLevel, "INSERT", "") {
			t.Errorf("%+v", it)
		}
	})
}
