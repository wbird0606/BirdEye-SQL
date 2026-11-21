package birdeye

import (
	"context"
	"strings"
	"testing"
	"time"
)

// rewrite_semantics_test.go：差分測試（VM 上對真實資料庫比對）所發現缺陷之離線鎖定測試。
// 對照：birdeye-go_diff_test/差分測試結果.md

func rf(table, col, op, val string) RowFilter {
	return RowFilter{Schema: "SalesLT", Table: table, Column: col, Operator: op, ValueType: "LITERAL", Value: val}
}

func rewriteWith(t *testing.T, sql string, filters ...RowFilter) string {
	t.Helper()
	a := NewAnalyser(tableFetch, time.Minute)
	res, err := a.GetIntents(context.Background(), sql, 2, nil)
	if err != nil {
		t.Fatalf("GetIntents(%q): %v", sql, err)
	}
	out, err := a.Rewrite(res.ASTJSON, filters)
	if err != nil {
		t.Fatalf("Rewrite(%q): %v", sql, err)
	}
	// 重建結果必須能被引擎自身重新解析（至少語法合法）
	if _, err := NewRunner(nil).ParseOnlyMulti(out, nil); err != nil {
		t.Fatalf("重建 SQL 無法重新解析：%v\nSQL: %s", err, out)
	}
	return out
}

const (
	tH = "SalesLT.SalesOrderHeader"
	tD = "SalesLT.SalesOrderDetail"
	tC = "SalesLT.ProductCategory"
)

var fD = rf("SalesOrderDetail", "OrderQty", ">=", "5")
var fH = rf("SalesOrderHeader", "SubTotal", ">", "20000")

func TestRewrite_ExistsSubqueryIsValid(t *testing.T) {
	out := rewriteWith(t, "SELECT h.SalesOrderID FROM "+tH+" h WHERE EXISTS (SELECT 1 FROM "+tD+" d WHERE d.SalesOrderID = h.SalesOrderID)", fD)
	if strings.Contains(out, ") AS d)") || !strings.Contains(out, "EXISTS (SELECT 1 FROM "+tD+" AS d WHERE (d.SalesOrderID = h.SalesOrderID AND d.OrderQty >= 5))") {
		t.Errorf("EXISTS 子查詢重建不正確：%s", out)
	}
	out = rewriteWith(t, "SELECT h.SalesOrderID FROM "+tH+" h WHERE NOT EXISTS (SELECT 1 FROM "+tD+" d WHERE d.SalesOrderID = h.SalesOrderID)", fD)
	if strings.Contains(out, ") AS d)") || !strings.Contains(out, "NOT EXISTS (SELECT 1 FROM") {
		t.Errorf("NOT EXISTS 子查詢重建不正確：%s", out)
	}
}

func TestRewrite_ScalarSubqueryParenthesizedAndAliased(t *testing.T) {
	out := rewriteWith(t, "SELECT h.SalesOrderID, (SELECT COUNT(*) FROM "+tD+" d WHERE d.SalesOrderID = h.SalesOrderID) n FROM "+tH+" h", fD)
	if !strings.Contains(out, ", (SELECT COUNT(*) FROM "+tD+" AS d WHERE (d.SalesOrderID = h.SalesOrderID AND d.OrderQty >= 5)) AS n FROM") {
		t.Errorf("純量子查詢缺括號或別名：%s", out)
	}
}

func TestRewrite_LiteralColumnAliasPreserved(t *testing.T) {
	out := rewriteWith(t, "SELECT 0 AS lvl, CustomerID FROM SalesLT.Customer")
	if !strings.Contains(out, "SELECT 0 AS lvl, CustomerID FROM") {
		t.Errorf("字面值別名遺失：%s", out)
	}
	out = rewriteWith(t, recCTE)
	if !strings.Contains(out, "0 AS lvl") {
		t.Errorf("遞迴 CTE 錨點之字面值別名遺失：%s", out)
	}
}

func TestRewrite_OuterJoinNullableSideUsesFilteredDerivedTable(t *testing.T) {
	left := rewriteWith(t, "SELECT h.SalesOrderID, d.OrderQty FROM "+tH+" h LEFT JOIN "+tD+" d ON h.SalesOrderID = d.SalesOrderID", fD)
	if !strings.Contains(left, "LEFT JOIN (SELECT * FROM "+tD+" WHERE ") || strings.Contains(left, ") WHERE") && strings.Contains(left, "WHERE d.OrderQty") {
		t.Errorf("LEFT JOIN 右表應以過濾後衍生資料表取代：%s", left)
	}
	if strings.Contains(strings.SplitN(left, ") AS d", 2)[len(strings.SplitN(left, ") AS d", 2))-1], "OrderQty >= 5") {
		t.Errorf("過濾條件不應再出現在外層 WHERE：%s", left)
	}
	right := rewriteWith(t, "SELECT h.SalesOrderID, d.OrderQty FROM "+tH+" h RIGHT JOIN "+tD+" d ON h.SalesOrderID = d.SalesOrderID", fH)
	if !strings.Contains(right, "FROM (SELECT * FROM "+tH+" WHERE ") {
		t.Errorf("RIGHT JOIN 左表應以過濾後衍生資料表取代：%s", right)
	}
	full := rewriteWith(t, "SELECT h.SalesOrderID, d.SalesOrderDetailID FROM "+tH+" h FULL JOIN "+tD+" d ON h.SalesOrderID = d.SalesOrderID", fH, fD)
	if !strings.Contains(full, "FROM (SELECT * FROM "+tH+" WHERE ") || !strings.Contains(full, "JOIN (SELECT * FROM "+tD+" WHERE ") {
		t.Errorf("FULL JOIN 兩側皆應以衍生資料表取代：%s", full)
	}
}

func TestRewrite_InnerAndPreservedSideStillUseWhere(t *testing.T) {
	// 非 NULL 側維持原本之 WHERE 注入（輸出簡潔、與既有行為一致）
	inner := rewriteWith(t, "SELECT h.SalesOrderID FROM "+tH+" h JOIN "+tD+" d ON h.SalesOrderID = d.SalesOrderID", fH, fD)
	if strings.Contains(inner, "(SELECT * FROM") || !strings.Contains(inner, "WHERE (h.SubTotal > 20000 AND d.OrderQty >= 5)") {
		t.Errorf("INNER JOIN 應維持 WHERE 注入：%s", inner)
	}
	left := rewriteWith(t, "SELECT h.SalesOrderID, d.OrderQty FROM "+tH+" h LEFT JOIN "+tD+" d ON h.SalesOrderID = d.SalesOrderID", fH)
	if strings.Contains(left, "(SELECT * FROM") || !strings.Contains(left, "WHERE h.SubTotal > 20000") {
		t.Errorf("LEFT JOIN 之保留側（左表）應維持 WHERE 注入：%s", left)
	}
}

func TestRewrite_SelfJoinFiltersEveryAlias(t *testing.T) {
	// 先前只對第一個別名套用過濾，第二個別名可繞過列過濾
	out := rewriteWith(t,
		"SELECT a.ProductCategoryID, b.ProductCategoryID FROM "+tC+" a JOIN "+tC+" b ON b.ParentProductCategoryID = a.ProductCategoryID",
		rf("ProductCategory", "ProductCategoryID", "<=", "30"))
	if !strings.Contains(out, "a.ProductCategoryID <= 30") || !strings.Contains(out, "b.ProductCategoryID <= 30") {
		t.Errorf("自我 JOIN 之每個別名皆須套用過濾：%s", out)
	}
}

func TestRewrite_OrPrecedenceParenthesized(t *testing.T) {
	out := rewriteWith(t, "SELECT SalesOrderID FROM "+tH+" WHERE SubTotal < 100 OR SubTotal > 90000", fH)
	if !strings.Contains(out, "WHERE ((SubTotal < 100 OR SubTotal > 90000) AND ") && !strings.Contains(out, "(SubTotal < 100 OR SubTotal > 90000) AND") {
		t.Errorf("原 WHERE 含 OR 時必須加括號再與過濾條件 AND：%s", out)
	}
}

func TestReconstruct_SubqueryShapesAreValidAndStable(t *testing.T) {
	// 這些形態在基準版會產生多餘的 "AS 別名" 或缺括號；現須合法且重建後穩定（fixed point）
	for _, sql := range []string{
		"SELECT LastName FROM SalesLT.Customer u WHERE EXISTS (SELECT 1 FROM SalesLT.SalesOrderHeader o WHERE o.CustomerID = u.CustomerID)",
		"SELECT CustomerID FROM SalesLT.Customer a WHERE CustomerID IN (SELECT CustomerID FROM SalesLT.Customer a2 WHERE a2.CustomerID = a.CustomerID)",
		"SELECT (SELECT MAX(CustomerID) FROM SalesLT.Customer) AS MaxID",
		"SELECT CustomerID, (SELECT MAX(CustomerID) FROM SalesLT.Customer) AS MaxID FROM SalesLT.Customer",
		"UPDATE SalesLT.Customer SET Title = (SELECT TOP 1 Title FROM SalesLT.Customer c2 WHERE c2.CustomerID < 100) WHERE CustomerID = 10",
		"DELETE FROM SalesLT.Customer WHERE CustomerID IN (SELECT CustomerID FROM SalesLT.SalesOrderHeader ca WHERE ca.CustomerID = Customer.CustomerID)",
		"SELECT 1 AS A",
		"SELECT NULL AS EmptyCol",
		"SELECT c.CustomerID, sub.x FROM SalesLT.Customer c CROSS APPLY (SELECT 1 AS x) sub",
	} {
		a := NewAnalyser(tableFetch, time.Minute)
		res, err := a.GetIntents(context.Background(), sql, 2, nil)
		if err != nil {
			t.Fatalf("GetIntents(%q): %v", sql, err)
		}
		out1, err := a.Rewrite(res.ASTJSON, nil)
		if err != nil {
			t.Fatalf("Rewrite(%q): %v", sql, err)
		}
		node, err := NewRunner(nil).ParseOnlyMulti(out1, nil)
		if err != nil {
			t.Fatalf("重建 SQL 無法重新解析：%v\n原：%s\n重建：%s", err, sql, out1)
		}
		out2, err := NewReconstructor().Reconstruct(NewSerializer().ToJSON(node))
		if err != nil || out2 != out1 {
			t.Errorf("重建不穩定（非 fixed point）：\n 1: %s\n 2: %s (err=%v)", out1, out2, err)
		}
	}
}
