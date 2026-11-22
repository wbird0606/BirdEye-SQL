package birdeye

import (
	"context"
	"strings"
	"testing"
	"time"
)

func TestQmarkToPositional(t *testing.T) {
	cases := map[string]string{
		"SELECT ? AS x":                         "SELECT @p1 AS x",
		"SELECT a FROM t WHERE b = ? AND c = ?": "SELECT a FROM t WHERE b = @p1 AND c = @p2",
		"SELECT '?' AS q, ? AS x -- ?":          "SELECT '?' AS q, @p1 AS x -- ?",
		"SELECT 1 /* ? */, ?":                   "SELECT 1 /* ? */, @p1",
		"SELECT 1":                              "SELECT 1",
	}
	for in, want := range cases {
		if got := QmarkToPositional(in); got != want {
			t.Errorf("%q => %q, want %q", in, got, want)
		}
	}
}

// 原生 @p1…@pN 位置參數：以清單傳入、SQL 不含 ?，應可通過分析且不產生欄位意圖。
func TestNativePositionalParams(t *testing.T) {
	reg := NewMetadataRegistry()
	if err := reg.LoadFromCSV("table_schema,table_name,column_name,data_type\nSalesLT,Product,ProductID,int\nSalesLT,Product,Name,nvarchar\n"); err != nil {
		t.Fatal(err)
	}
	for _, sql := range []string{
		"SELECT Name FROM SalesLT.Product WHERE ProductID > @p1 AND Name <> @p2",
		"SELECT Name FROM SalesLT.Product WHERE ProductID > @p1 OR ProductID < @p1",
	} {
		params := []any{700, "x"}
		if sql[len(sql)-2:] == "p1" {
			params = []any{700}
		}
		res, err := NewRunner(reg).RunMulti(sql, params)
		if err != nil {
			t.Fatalf("%q: %v", sql, err)
		}
		intents, err := NewIntentExtractor().ExtractFromStr(res.JSON)
		if err != nil {
			t.Fatal(err)
		}
		for _, in := range intents {
			if in.Column != nil && (*in.Column == "?" || (len(*in.Column) > 0 && (*in.Column)[0] == '@')) {
				t.Errorf("%q: parameter leaked as column intent: %+v", sql, in)
			}
		}
	}
	if _, err := NewRunner(reg).RunMulti("SELECT Name FROM SalesLT.Product WHERE ProductID > @p1", []any{1, 2}); err == nil {
		t.Log("extra unused parameter accepted")
	}
}

// 端到端：位置參數（? 與 @p1）經 Analyser 取意圖、再套列過濾改寫，佔位符保留且不產生欄位意圖。
func TestAnalyserParamStylesWithRowFilter(t *testing.T) {
	a := NewAnalyser(fakeFetch(SchemaColumn{"ProductID", "int"}, SchemaColumn{"Name", "nvarchar"}, SchemaColumn{"ListPrice", "money"}), time.Minute)
	rf := []RowFilter{{Schema: "SalesLT", Table: "Product", Column: "ListPrice", Operator: "<", ValueType: "NUMBER", Value: "1000"}}
	for _, c := range []struct{ sql, ph string }{
		{"SELECT Name FROM SalesLT.Product WHERE ProductID > ?", "?"},
		{"SELECT Name FROM SalesLT.Product WHERE ProductID > @p1", "@p1"},
	} {
		res, err := a.GetIntents(context.Background(), c.sql, 1, []any{700})
		if err != nil {
			t.Fatalf("%q: %v", c.sql, err)
		}
		for _, it := range res.Intents {
			if it.Column != nil && (*it.Column == "?" || strings.HasPrefix(*it.Column, "@")) {
				t.Errorf("%q: placeholder as column intent: %+v", c.sql, it)
			}
		}
		out, err := a.Rewrite(res.ASTJSON, rf)
		if err != nil {
			t.Fatalf("%q rewrite: %v", c.sql, err)
		}
		if !strings.Contains(out, c.ph) || !strings.Contains(out, "ListPrice") {
			t.Errorf("%q rewritten = %q", c.sql, out)
		}
		t.Logf("%s", out)
	}
}
