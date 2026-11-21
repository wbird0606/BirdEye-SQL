package birdeye

import (
	"context"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// analyser_test.go：對照 zta-proxy 的 native_test.go —— Analyser 端到端行為。

func fakeFetch(cols ...SchemaColumn) SchemaFetcher {
	return func(_ context.Context, _ int, _, _ string) ([]SchemaColumn, error) { return cols, nil }
}

func TestAnalyser_GetIntents_ProjectionAndFilter(t *testing.T) {
	a := NewAnalyser(fakeFetch(
		SchemaColumn{"AddressID", "int"}, SchemaColumn{"City", "nvarchar"}, SchemaColumn{"PostalCode", "nvarchar"},
	), time.Minute)

	res, err := a.GetIntents(context.Background(),
		"SELECT AddressID FROM SalesLT.Address WHERE City = 'Seattle'", 1, nil)
	if err != nil {
		t.Fatalf("GetIntents: %v", err)
	}
	if !strings.Contains(res.ASTJSON, `"node_type": "ScriptNode"`) {
		t.Fatalf("ASTJSON 非 ScriptNode: %s", res.ASTJSON[:80])
	}
	got := map[string]string{}
	for _, it := range res.Intents {
		col := ""
		if it.Column != nil {
			col = *it.Column
		}
		got[it.Table+"."+col] = it.Intent
	}
	if got["Address.AddressID"] != "READ" || got["Address.City"] != "FILTER" {
		t.Errorf("意圖不符：%+v", res.Intents)
	}
}

func TestAnalyser_GetIntents_StarExpansion(t *testing.T) {
	a := NewAnalyser(fakeFetch(SchemaColumn{"AddressID", "int"}, SchemaColumn{"City", "nvarchar"}), time.Minute)

	// SELECT *：binder（有 schema）在 Pass 2 就展開成逐欄 → registry 大寫（與 IntentExtractor.extract 一致）
	star, err := a.GetIntents(context.Background(), "SELECT * FROM SalesLT.Address", 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	sc := intentCols(star.Intents)
	if !sc["ADDRESSID"] || !sc["CITY"] {
		t.Errorf("SELECT * 應展開全欄（大寫）：%v", sc)
	}

	// COUNT(*)：table-level READ（column=nil）→ Analyser 以 fetch 回來的「原始大小寫」展開
	// （對照 birdeye-svc/app.py 的自訂展開迴圈）
	cnt, err := a.GetIntents(context.Background(), "SELECT COUNT(*) FROM SalesLT.Address", 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	cc := intentCols(cnt.Intents)
	if !cc["AddressID"] || !cc["City"] {
		t.Errorf("COUNT(*) 應以原始大小寫展開：%v", cc)
	}
	for _, it := range cnt.Intents {
		if it.Column == nil {
			t.Errorf("展開後不應有 column=nil：%+v", cnt.Intents)
		}
	}
}

func intentCols(is []AnalyserIntent) map[string]bool {
	m := map[string]bool{}
	for _, it := range is {
		if it.Column != nil {
			m[*it.Column] = true
		}
	}
	return m
}

func TestAnalyser_GetIntents_Cache(t *testing.T) {
	var calls int32
	a := NewAnalyser(func(_ context.Context, _ int, _, _ string) ([]SchemaColumn, error) {
		atomic.AddInt32(&calls, 1)
		return []SchemaColumn{{"AddressID", "int"}}, nil
	}, time.Minute)
	sql := "SELECT AddressID FROM SalesLT.Address"
	for i := 0; i < 3; i++ {
		if _, err := a.GetIntents(context.Background(), sql, 7, nil); err != nil {
			t.Fatal(err)
		}
	}
	if n := atomic.LoadInt32(&calls); n != 1 {
		t.Errorf("預期 fetch 1 次（其餘命中 cache），實際 %d", n)
	}
	if _, err := a.GetIntents(context.Background(), sql, 8, nil); err != nil {
		t.Fatal(err)
	}
	if n := atomic.LoadInt32(&calls); n != 2 {
		t.Errorf("不同 db_id 應重新 fetch，實際 %d", n)
	}

	// TTL <= 0 → 不快取
	var calls2 int32
	nc := NewAnalyser(func(_ context.Context, _ int, _, _ string) ([]SchemaColumn, error) {
		atomic.AddInt32(&calls2, 1)
		return []SchemaColumn{{"AddressID", "int"}}, nil
	}, 0)
	nc.GetIntents(context.Background(), sql, 1, nil)
	nc.GetIntents(context.Background(), sql, 1, nil)
	if atomic.LoadInt32(&calls2) != 2 {
		t.Errorf("TTL=0 不應快取")
	}
}

func TestAnalyser_GetIntents_BadSQL(t *testing.T) {
	a := NewAnalyser(fakeFetch(), time.Minute)
	if _, err := a.GetIntents(context.Background(), "SELECT * FROM", 1, nil); err == nil {
		t.Fatal("畸形 SQL 應報錯")
	}
}

func TestAnalyser_GetIntents_RejectsDDL(t *testing.T) {
	a := NewAnalyser(fakeFetch(SchemaColumn{"AddressID", "int"}), time.Minute)
	reject := []string{
		"DROP TABLE SalesLT.Address",
		"SELECT AddressID FROM SalesLT.Address; DROP TABLE SalesLT.Address",
		"CREATE TABLE SalesLT.Evil (a int)",
		"SELECT AddressID FROM SalesLT.Address; ALTER TABLE SalesLT.Address ADD c int",
		"TRUNCATE TABLE SalesLT.Address",
		"SELECT AddressID FROM SalesLT.Address; TRUNCATE TABLE SalesLT.Address",
		"SELECT AddressID INTO SalesLT.Copy FROM SalesLT.Address",
		"SELECT AddressID FROM SalesLT.Address; SELECT AddressID INTO SalesLT.Copy FROM SalesLT.Address",
	}
	for _, sql := range reject {
		_, err := a.GetIntents(context.Background(), sql, 1, nil)
		if err == nil {
			t.Errorf("應拒絕 DDL：%q", sql)
			continue
		}
		if be, ok := err.(*Error); !ok || be.Kind != ErrSemantic {
			t.Errorf("%q：預期 ErrSemantic，得 %v", sql, err)
		}
	}
	// 暫存資料表之 DDL 不在此限（session 範疇，非 schema 變更）
	okCases := []string{
		"SELECT AddressID FROM SalesLT.Address; CREATE TABLE #tmp (a int); DROP TABLE #tmp",
	}
	for _, sql := range okCases {
		if _, err := a.GetIntents(context.Background(), sql, 1, nil); err != nil {
			t.Errorf("暫存表 DDL 應放行：%q → %v", sql, err)
		}
	}
}

func TestAnalyser_Rewrite(t *testing.T) {
	a := NewAnalyser(fakeFetch(SchemaColumn{"AddressID", "int"}, SchemaColumn{"City", "nvarchar"}), time.Minute)
	res, _ := a.GetIntents(context.Background(), "SELECT AddressID FROM SalesLT.Address", 1, nil)

	// 無 filter → 原樣重建
	sql, err := a.Rewrite(res.ASTJSON, nil)
	if err != nil || !strings.Contains(sql, "SELECT AddressID") {
		t.Fatalf("no-filter rewrite: %q %v", sql, err)
	}

	// LITERAL filter → 注入 WHERE
	sql2, err := a.Rewrite(res.ASTJSON, []RowFilter{
		{Schema: "SalesLT", Table: "Address", Column: "City", Operator: "=", ValueType: "LITERAL", Value: "Seattle"},
	})
	if err != nil || !strings.Contains(sql2, "WHERE") || !strings.Contains(sql2, "City = 'Seattle'") {
		t.Fatalf("literal filter: %q %v", sql2, err)
	}

	// SUBQUERY 字串值 → 先預先 parse（schemaless 可行者）
	sql3, err := a.Rewrite(res.ASTJSON, []RowFilter{
		{Schema: "SalesLT", Table: "Address", Column: "AddressID", Operator: "IN", ValueType: "SUBQUERY", Value: "SELECT 1"},
	})
	if err != nil || !strings.Contains(sql3, "IN (SELECT") {
		t.Fatalf("subquery filter: %q %v", sql3, err)
	}

	// SUBQUERY 引用未知表 → 錯誤（與 Python 一致）
	if _, err := a.Rewrite(res.ASTJSON, []RowFilter{
		{Schema: "SalesLT", Table: "Address", Column: "AddressID", Operator: "IN", ValueType: "SUBQUERY", Value: "SELECT X FROM Ghost"},
	}); err == nil {
		t.Error("未知表子查詢應報錯")
	}
}
