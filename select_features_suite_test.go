package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_select_features_suite.py
// （order_by_top / top_percent / group_by_having / distinct_null）

func sfReg(t *testing.T) *MetadataRegistry {
	return mkReg(t, "table_name,column_name,data_type\nUsers,UserID,INT\nUsers,UserName,VARCHAR\nUsers,Email,VARCHAR\n")
}

func TestSelectFeat_OrderByTop(t *testing.T) {
	for _, kw := range []TokenType{KwTop, KwOrder, KwBy, KwAsc, KwDesc} {
		if !tokenPresent(t, "SELECT TOP 10 * FROM Users ORDER BY UserID ASC DESC", kw) {
			t.Errorf("token %v 缺失", kw)
		}
	}

	cases := []struct {
		sql      string
		top      int // -1 = 無
		orderCnt int
	}{
		{"SELECT TOP 10 * FROM Users", 10, 0},
		{"SELECT * FROM Users ORDER BY UserID", -1, 1},
		{"SELECT TOP 5 UserName FROM Users ORDER BY UserID DESC", 5, 1},
		{"SELECT * FROM Users ORDER BY UserName ASC, UserID DESC", -1, 2},
	}
	for _, c := range cases {
		st := mustParse(t, c.sql).(*SelectStatement)
		if c.top >= 0 && (st.TopCount == nil || *st.TopCount != c.top) {
			t.Errorf("%q top %v", c.sql, st.TopCount)
		}
		if len(st.OrderBy) != c.orderCnt {
			t.Errorf("%q order count %d want %d", c.sql, len(st.OrderBy), c.orderCnt)
		}
	}

	reg := sfReg(t)
	obNode := mustBind(t, reg, "SELECT UserName FROM Users u ORDER BY u.UserID").(*SelectStatement).OrderBy[0]
	if strings.ToUpper(obNode.Column.(*IdentifierNode).Qualifiers[0]) != "U" {
		t.Errorf("ORDER BY scope: %+v", obNode.Column)
	}
	if _, err := NewRunner(reg).Run("SELECT * FROM Users ORDER BY GhostColumn", nil); err == nil ||
		!strings.Contains(err.Error(), "Column 'GhostColumn' not found in 'Users'") {
		t.Errorf("ORDER BY invalid col")
	}
	amb := mkReg(t, "table_name,column_name,data_type\nUsers,UserID,INT\nOrders,UserID,INT\n")
	if _, err := NewRunner(amb).Run("SELECT * FROM Users JOIN Orders ON Users.UserID = Orders.UserID ORDER BY UserID", nil); err == nil ||
		!strings.Contains(err.Error(), "Column 'UserID' is ambiguous") {
		t.Errorf("ORDER BY ambiguous")
	}

	if parseErr(t, "SELECT TOP * FROM Users") == nil {
		t.Error("TOP 缺數值應報錯")
	}
	if p := mustParse(t, "SELECT TOP (1000) [AddressID] FROM [Address]").(*SelectStatement); p.TopCount == nil || *p.TopCount != 1000 || p.TopPercent {
		t.Errorf("TOP (1000): %v %v", p.TopCount, p.TopPercent)
	}
	if p := mustParse(t, "SELECT TOP (10) PERCENT [AddressID] FROM [Address]").(*SelectStatement); p.TopCount == nil || *p.TopCount != 10 || !p.TopPercent {
		t.Errorf("TOP (10) PERCENT: %v %v", p.TopCount, p.TopPercent)
	}

	// ORDER BY alias resolution
	obAlias := mustBind(t, reg, "SELECT UserID + 100 AS Score FROM Users ORDER BY Score DESC").(*SelectStatement).OrderBy[0].Column
	if colType(obAlias) != "INT" {
		t.Errorf("ORDER BY alias type: %s", colType(obAlias))
	}
}

func mustBind(t *testing.T, reg *MetadataRegistry, sql string) Node {
	t.Helper()
	n := mustParse(t, sql)
	out, err := NewBinder(reg).Bind(n, nil)
	if err != nil {
		t.Fatalf("bind %q: %v", sql, err)
	}
	return out
}

func TestSelectFeat_ThreePartName(t *testing.T) {
	aw := loadAdventureWorks(t)
	res, err := NewRunner(aw).RunMulti("SELECT TOP (1000) [AddressID], [City] FROM [AdventureWorksLT2022].[SalesLT].[Address]", nil)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	json.Unmarshal([]byte(res.JSON), &m)
	stmt := m["statements"].([]any)[0].(map[string]any)
	if stmt["top"].(float64) != 1000 {
		t.Errorf("top: %v", stmt["top"])
	}
	found := false
	for _, c := range stmt["columns"].([]any) {
		if c.(map[string]any)["name"] == "City" {
			found = true
		}
	}
	if !found {
		t.Errorf("City col not found: %v", stmt["columns"])
	}
}

func TestSelectFeat_TopPercent(t *testing.T) {
	aw := loadAdventureWorks(t)
	if !tokenPresent(t, "SELECT TOP 10 PERCENT AddressID FROM Address", KwPercent) {
		t.Error("PERCENT token")
	}
	if p := mustParse(t, "SELECT TOP 10 PERCENT AddressID FROM T").(*SelectStatement); p.TopCount == nil || *p.TopCount != 10 || !p.TopPercent {
		t.Errorf("TOP PERCENT flag: %v %v", p.TopCount, p.TopPercent)
	}
	if p := mustParse(t, "SELECT TOP 10 AddressID FROM T").(*SelectStatement); p.TopPercent {
		t.Error("無 PERCENT 應為 false")
	}
	for _, sql := range []string{
		"SELECT TOP 10 PERCENT AddressID FROM Address",
		"SELECT TOP 50 PERCENT City FROM Address WHERE AddressID > 0",
		"SELECT TOP 10 PERCENT AddressID FROM Address ORDER BY AddressID",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	data := map[string]any{}
	json.Unmarshal([]byte(NewSerializer().ToJSON(mustParse(t, "SELECT TOP 10 PERCENT AddressID FROM T"))), &data)
	if data["top"].(float64) != 10 || data["top_percent"] != true {
		t.Errorf("serialize: %v", data)
	}
	data2 := map[string]any{}
	json.Unmarshal([]byte(NewSerializer().ToJSON(mustParse(t, "SELECT TOP 10 AddressID FROM T"))), &data2)
	if data2["top_percent"] != false {
		t.Errorf("serialize no percent: %v", data2["top_percent"])
	}
	if !strings.Contains(NewVisualizer().Dump(mustParse(t, "SELECT TOP 10 PERCENT AddressID FROM T")), "TOP: 10 PERCENT") {
		t.Error("viz TOP PERCENT")
	}
}

func TestSelectFeat_GroupByHaving(t *testing.T) {
	aw := loadAdventureWorks(t)
	gb := intgRun(t, aw, "SELECT ProductID, SUM(LineTotal) FROM SalesOrderDetail GROUP BY ProductID").AST.(*SelectStatement)
	if len(gb.GroupBy) != 1 || gb.GroupBy[0].(*IdentifierNode).Name != "ProductID" {
		t.Errorf("group by: %+v", gb.GroupBy)
	}
	hv := intgRun(t, aw, "SELECT ProductID FROM SalesOrderDetail GROUP BY ProductID HAVING SUM(LineTotal) > 1000").AST.(*SelectStatement)
	if hv.Having == nil || hv.Having.(*BinaryExpressionNode).Operator != ">" {
		t.Errorf("having: %+v", hv.Having)
	}
	intgErr(t, aw, "SELECT ProductID, SalesOrderID FROM SalesOrderDetail GROUP BY ProductID", "Column 'SalesOrderID' must appear in the GROUP BY clause")
	intgErr(t, aw, "SELECT ProductID FROM SalesOrderDetail WHERE SUM(LineTotal) > 100 GROUP BY ProductID", "Aggregate functions are not allowed in WHERE clause")
	intgErr(t, aw, "SELECT CASE WHEN ProductID > 0 THEN SUM(LineTotal) ELSE LineTotal END FROM SalesOrderDetail GROUP BY ProductID", "Column 'LineTotal' must appear in the GROUP BY clause")
	cx := intgRun(t, aw, "SELECT SUBSTRING(Name, 1, 5) AS ShortName, COUNT(ProductID) FROM Product GROUP BY SUBSTRING(Name, 1, 5)").AST.(*SelectStatement)
	if len(cx.Columns) != 2 {
		t.Errorf("group by complex expr: %d cols", len(cx.Columns))
	}
}

func TestSelectFeat_DistinctNull(t *testing.T) {
	aw := loadAdventureWorks(t)
	if !tokenPresent(t, "SELECT DISTINCT City FROM Address", KwDistinct) {
		t.Error("DISTINCT token")
	}
	if !mustParse(t, "SELECT DISTINCT City FROM T").(*SelectStatement).IsDistinct {
		t.Error("is_distinct true")
	}
	if mustParse(t, "SELECT City FROM T").(*SelectStatement).IsDistinct {
		t.Error("is_distinct false")
	}
	for _, sql := range []string{
		"SELECT DISTINCT City FROM Address",
		"SELECT DISTINCT City, StateProvince FROM Address",
		"SELECT DISTINCT City FROM Address WHERE AddressID > 0",
		"SELECT DISTINCT City FROM Address ORDER BY City",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	dd := map[string]any{}
	json.Unmarshal([]byte(NewSerializer().ToJSON(mustParse(t, "SELECT DISTINCT City FROM T"))), &dd)
	if dd["is_distinct"] != true {
		t.Errorf("distinct serialize: %v", dd["is_distinct"])
	}
	if !strings.Contains(NewVisualizer().Dump(mustParse(t, "SELECT DISTINCT City FROM T")), "DISTINCT") {
		t.Error("viz DISTINCT")
	}

	if !tokenPresent(t, "SELECT NULL", KwNull) {
		t.Error("NULL token")
	}
	nc := mustParse(t, "SELECT NULL").(*SelectStatement).Columns[0]
	if lit, ok := nc.(*LiteralNode); !ok || lit.Value != "NULL" {
		t.Errorf("NULL literal: %+v", nc)
	}
	for _, sql := range []string{
		"SELECT NULL",
		"SELECT CASE WHEN AddressID = 1 THEN City ELSE NULL END FROM Address",
		"SELECT AddressID FROM Address WHERE City IS NULL",
		"SELECT NULL AS EmptyCol",
		"SELECT AddressID FROM Address WHERE City = NULL",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
}
