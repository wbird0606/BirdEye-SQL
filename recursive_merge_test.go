package birdeye

import (
	"context"
	"strings"
	"testing"
	"time"
)

// recursive_merge_test.go：遞迴 CTE、CTE 欄位清單、帶 schema 之 MERGE。
// 這些在 VM 實測（2026-11）曾被拒絕，附錄卻宣稱支援，故以測試鎖定行為。

func tableFetch(_ context.Context, _ int, _, table string) ([]SchemaColumn, error) {
	switch strings.ToUpper(table) {
	case "CUSTOMER":
		return []SchemaColumn{{"CustomerID", "int"}, {"Title", "nvarchar"}, {"LastName", "nvarchar"}}, nil
	case "SALESORDERHEADER":
		return []SchemaColumn{{"SalesOrderID", "int"}, {"CustomerID", "int"}, {"Status", "int"}, {"SubTotal", "money"}}, nil
	case "SALESORDERDETAIL":
		return []SchemaColumn{{"SalesOrderID", "int"}, {"SalesOrderDetailID", "int"}, {"OrderQty", "smallint"}, {"ProductID", "int"}}, nil
	case "PRODUCTCATEGORY":
		return []SchemaColumn{{"ProductCategoryID", "int"}, {"ParentProductCategoryID", "int"}, {"Name", "nvarchar"}}, nil
	}
	return nil, nil
}

func rmIntents(t *testing.T, sql string) (AnalyserResult, map[string]bool) {
	t.Helper()
	a := NewAnalyser(tableFetch, time.Minute)
	res, err := a.GetIntents(context.Background(), sql, 2, nil)
	if err != nil {
		t.Fatalf("GetIntents(%q): %v", sql, err)
	}
	got := map[string]bool{}
	for _, it := range res.Intents {
		col := "*"
		if it.Column != nil {
			col = *it.Column
		}
		got[it.Table+"."+col+":"+it.Intent] = true
	}
	return res, got
}

const recCTE = "WITH r AS (SELECT ProductCategoryID, ParentProductCategoryID, 0 AS lvl FROM SalesLT.ProductCategory " +
	"WHERE ParentProductCategoryID IS NULL UNION ALL " +
	"SELECT p.ProductCategoryID, p.ParentProductCategoryID, r.lvl + 1 FROM SalesLT.ProductCategory p " +
	"JOIN r ON p.ParentProductCategoryID = r.ProductCategoryID) SELECT ProductCategoryID, lvl FROM r"

func TestRecursiveCTE_NoColumnList(t *testing.T) {
	_, got := rmIntents(t, recCTE)
	for _, want := range []string{
		"ProductCategory.ProductCategoryID:READ",
		"ProductCategory.ParentProductCategoryID:FILTER",
	} {
		if !got[want] {
			t.Errorf("缺少意圖 %s；實得 %v", want, got)
		}
	}
}

const recCTECols = "WITH r(id, pid, lvl) AS (SELECT ProductCategoryID, ParentProductCategoryID, 0 FROM SalesLT.ProductCategory " +
	"WHERE ParentProductCategoryID IS NULL UNION ALL " +
	"SELECT p.ProductCategoryID, p.ParentProductCategoryID, r.lvl + 1 FROM SalesLT.ProductCategory p " +
	"JOIN r ON p.ParentProductCategoryID = r.id) SELECT id, lvl FROM r"

func TestRecursiveCTE_WithColumnList(t *testing.T) {
	res, got := rmIntents(t, recCTECols)
	if !got["ProductCategory.ProductCategoryID:READ"] {
		t.Errorf("實得 %v", got)
	}
	// 以 AST 重建，欄位清單必須保留，否則 SQL 語意改變
	sql, err := NewAnalyser(tableFetch, time.Minute).Rewrite(res.ASTJSON, nil)
	if err != nil {
		t.Fatalf("Rewrite: %v", err)
	}
	if !strings.Contains(strings.ToUpper(sql), "R(ID, PID, LVL) AS") && !strings.Contains(strings.ToUpper(sql), "R (ID, PID, LVL) AS") {
		t.Errorf("重建 SQL 遺失 CTE 欄位清單：%s", sql)
	}
}

func TestCTE_ColumnListNonRecursive(t *testing.T) {
	_, got := rmIntents(t, "WITH c(a) AS (SELECT CustomerID FROM SalesLT.Customer) SELECT a FROM c")
	if !got["Customer.CustomerID:READ"] {
		t.Errorf("實得 %v", got)
	}
}

func TestCTE_ColumnListCountMismatchRejected(t *testing.T) {
	a := NewAnalyser(tableFetch, time.Minute)
	_, err := a.GetIntents(context.Background(),
		"WITH c(a, b) AS (SELECT CustomerID FROM SalesLT.Customer) SELECT a FROM c", 2, nil)
	if err == nil {
		t.Fatal("欄位清單數量與查詢不符應被拒絕")
	}
}

func TestCTE_NonUnionSelfReferenceStillRejected(t *testing.T) {
	a := NewAnalyser(tableFetch, time.Minute)
	_, err := a.GetIntents(context.Background(), "WITH r AS (SELECT * FROM r) SELECT 1 FROM r", 2, nil)
	if err == nil {
		t.Fatal("非 UNION 之自我引用在 T-SQL 為非法，應維持拒絕（Fail-Closed）")
	}
}

func TestMerge_SchemaQualified(t *testing.T) {
	_, got := rmIntents(t,
		"MERGE SalesLT.Customer AS t USING SalesLT.SalesOrderHeader AS s ON t.CustomerID = s.CustomerID "+
			"WHEN MATCHED THEN UPDATE SET Title = 'x'")
	for _, want := range []string{"Customer.Title:UPDATE", "Customer.CustomerID:FILTER", "SalesOrderHeader.CustomerID:FILTER"} {
		if !got[want] {
			t.Errorf("缺少意圖 %s；實得 %v", want, got)
		}
	}
}

func TestMerge_SubquerySourceAndInsertDelete(t *testing.T) {
	_, got := rmIntents(t,
		"MERGE SalesLT.Customer AS t USING (SELECT CustomerID FROM SalesLT.SalesOrderHeader WHERE Status = 1) AS s "+
			"ON t.CustomerID = s.CustomerID WHEN MATCHED THEN DELETE")
	if !got["Customer.*:DELETE"] || !got["SalesOrderHeader.Status:FILTER"] {
		t.Errorf("實得 %v", got)
	}
}

func TestCTE_NameNotEmittedAsTable(t *testing.T) {
	// CTE 名稱不得出現於意圖（權限服務會因查無該「資料表」而拒絕整個查詢）；真實資料表意圖須保留。
	for _, sql := range []string{
		"WITH c AS (SELECT CustomerID FROM SalesLT.Customer) SELECT CustomerID FROM c",
		"WITH C AS (SELECT CustomerID FROM SalesLT.Customer) SELECT c.CustomerID FROM C c",
		recCTE,
		recCTECols,
	} {
		_, got := rmIntents(t, sql)
		for k := range got {
			up := strings.ToUpper(k)
			if strings.HasPrefix(up, "C.") || strings.HasPrefix(up, "R.") {
				t.Errorf("CTE 名稱被輸出為資料表：%s（SQL: %.60s）", k, sql)
			}
		}
	}
	_, got := rmIntents(t, "WITH c AS (SELECT CustomerID FROM SalesLT.Customer) SELECT CustomerID FROM c")
	if !got["Customer.CustomerID:READ"] {
		t.Errorf("真實資料表意圖遺失：%v", got)
	}
}

func TestCTE_RealTableWithSameNameStillTracked(t *testing.T) {
	// CTE 內部對真實資料表之讀取，即使外層引用 CTE，意圖仍須完整保留（不得因修正而放寬授權）。
	_, got := rmIntents(t,
		"WITH c AS (SELECT CustomerID, Title FROM SalesLT.Customer WHERE LastName = 'x') SELECT CustomerID FROM c")
	for _, want := range []string{"Customer.CustomerID:READ", "Customer.Title:READ", "Customer.LastName:FILTER"} {
		if !got[want] {
			t.Errorf("缺少 %s；實得 %v", want, got)
		}
	}
}

func TestThreePartColumnName(t *testing.T) {
	_, got := rmIntents(t, "SELECT SalesLT.Customer.CustomerID FROM SalesLT.Customer")
	if !got["Customer.CustomerID:READ"] {
		t.Errorf("實得 %v", got)
	}
	_, got = rmIntents(t,
		"SELECT SalesLT.Customer.Title, h.Status FROM SalesLT.Customer "+
			"JOIN SalesLT.SalesOrderHeader h ON SalesLT.Customer.CustomerID = h.CustomerID")
	for _, want := range []string{"Customer.Title:READ", "SalesOrderHeader.Status:READ", "Customer.CustomerID:FILTER"} {
		if !got[want] {
			t.Errorf("缺少 %s；實得 %v", want, got)
		}
	}
}

func TestThreePartColumnName_AliasedTableStillRejected(t *testing.T) {
	// T-SQL 規則：已定義別名時不得使用原始表名。修正不得放寬此規則。
	a := NewAnalyser(tableFetch, time.Minute)
	_, err := a.GetIntents(context.Background(),
		"SELECT SalesLT.Customer.CustomerID FROM SalesLT.Customer c", 2, nil)
	if err == nil {
		t.Fatal("已有別名卻使用原始表名，應拒絕")
	}
}
