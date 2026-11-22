package birdeye

import (
	"context"
	"strings"
	"testing"
)

// dml_from_test.go：UPDATE／DELETE ... FROM（KNOWN_DEVIATIONS A16）。
// 重點為安全性：FROM 來源之讀取須產生意圖、每個資料表（含自我 JOIN 之每個別名）須套用列過濾，
// 寫入目標不得被衍生資料表取代。

const (
	updHDJoin = "UPDATE h SET h.Status = 5 FROM " + tH + " h JOIN " + tD + " d ON h.SalesOrderID = d.SalesOrderID WHERE d.OrderQty > 3"
	delHDJoin = "DELETE h FROM " + tH + " h JOIN " + tD + " d ON h.SalesOrderID = d.SalesOrderID WHERE d.OrderQty > 3"
)

func TestDMLFromIntentsUpdate(t *testing.T) {
	_, got := rmIntents(t, updHDJoin)
	for _, want := range []string{
		"SalesOrderHeader.Status:" + IntentUpdate,
		"SalesOrderDetail.OrderQty:" + IntentFilter,
		"SalesOrderHeader.SalesOrderID:" + IntentFilter,
		"SalesOrderDetail.SalesOrderID:" + IntentFilter,
	} {
		if !got[want] {
			t.Errorf("缺少意圖 %s；實得 %v", want, got)
		}
	}
	for k := range got {
		if strings.HasPrefix(k, "h.") || strings.HasPrefix(k, "d.") {
			t.Errorf("別名不應被當成資料表：%s", k)
		}
	}
}

func TestDMLFromIntentsDeleteOnlyTargetIsDeleted(t *testing.T) {
	_, got := rmIntents(t, delHDJoin)
	if !got["SalesOrderHeader.*:"+IntentDelete] {
		t.Errorf("目標表應有 DELETE 意圖：%v", got)
	}
	if got["SalesOrderDetail.*:"+IntentDelete] {
		t.Errorf("僅 FROM 來源之表不得有 DELETE 意圖：%v", got)
	}
	if !got["SalesOrderDetail.OrderQty:"+IntentFilter] {
		t.Errorf("來源表之 WHERE 欄位須產生 FILTER 意圖：%v", got)
	}
}

// SET 右側讀取來源表之欄位，須為該表之 READ 意圖（否則來源表之讀取漏檢）。
func TestDMLFromIntentsSetReadsSource(t *testing.T) {
	_, got := rmIntents(t, "UPDATE SalesLT.SalesOrderHeader SET Status = d.OrderQty FROM "+tD+" d WHERE SalesOrderHeader.SalesOrderID = d.SalesOrderID")
	if !got["SalesOrderDetail.OrderQty:"+IntentRead] {
		t.Errorf("來源表欄位須為 READ：%v", got)
	}
	if !got["SalesOrderHeader.Status:"+IntentUpdate] {
		t.Errorf("目標欄位須為 UPDATE：%v", got)
	}
}

func TestDMLFromRewriteInnerJoin(t *testing.T) {
	for _, sql := range []string{updHDJoin, delHDJoin} {
		out := rewriteWith(t, sql, fH, fD)
		for _, want := range []string{"h.SubTotal > 20000", "d.OrderQty >= 5", "FROM " + tH + " AS h"} {
			if !strings.Contains(out, want) {
				t.Errorf("缺少 %q：%s", want, out)
			}
		}
	}
	if out := rewriteWith(t, delHDJoin, fH); !strings.HasPrefix(out, "DELETE h FROM ") {
		t.Errorf("DELETE 別名目標之形式不應改變：%s", out)
	}
}

// 外部 JOIN 之可為 NULL 側（非目標）：以過濾後衍生資料表取代，WHERE 不得剔除保留列。
func TestDMLFromRewriteLeftJoinNullableSide(t *testing.T) {
	out := rewriteWith(t, "UPDATE h SET h.Status = 1 FROM "+tH+" h LEFT JOIN "+tD+" d ON h.SalesOrderID = d.SalesOrderID WHERE h.SalesOrderID = 1", fD)
	if !strings.Contains(out, "(SELECT * FROM "+tD+" WHERE SalesOrderDetail.OrderQty >= 5) AS d") {
		t.Errorf("可為 NULL 側應以衍生資料表過濾：%s", out)
	}
	if strings.Contains(out, "d.OrderQty") {
		t.Errorf("可為 NULL 側不得把條件放進 WHERE：%s", out)
	}
}

// 寫入目標位於可為 NULL 側：目標不可被衍生資料表取代（UPDATE 不能以衍生資料表為目標），改以 WHERE 過濾。
func TestDMLFromRewriteTargetOnNullableSide(t *testing.T) {
	out := rewriteWith(t, "UPDATE h SET h.Status = 1 FROM "+tD+" d RIGHT JOIN "+tH+" h ON h.SalesOrderID = d.SalesOrderID WHERE h.SalesOrderID = 1", fH)
	if strings.Contains(out, "(SELECT * FROM "+tH) {
		t.Errorf("寫入目標不得被衍生資料表取代：%s", out)
	}
	if !strings.Contains(out, "h.SubTotal > 20000") {
		t.Errorf("目標過濾應位於 WHERE：%s", out)
	}
}

// 自我 JOIN：目標與來源為同一資料表之不同別名，兩者皆須過濾（對照 KNOWN_DEVIATIONS A8）。
func TestDMLFromRewriteSelfJoinBothAliases(t *testing.T) {
	out := rewriteWith(t, "UPDATE a SET a.Status = 1 FROM "+tH+" a JOIN "+tH+" b ON a.CustomerID = b.CustomerID WHERE b.SalesOrderID = 1", fH)
	for _, want := range []string{"a.SubTotal > 20000", "b.SubTotal > 20000"} {
		if !strings.Contains(out, want) {
			t.Errorf("自我 JOIN 缺少 %q：%s", want, out)
		}
	}
}

// 目標為獨立資料表（非 FROM 內之別名）：目標與來源各自過濾。
func TestDMLFromRewriteSeparateTarget(t *testing.T) {
	out := rewriteWith(t, "UPDATE "+tH+" SET Status = 1 FROM "+tD+" d WHERE SalesOrderHeader.SalesOrderID = d.SalesOrderID", fH, fD)
	for _, want := range []string{"SALESORDERHEADER.SubTotal > 20000", "d.OrderQty >= 5"} {
		if !strings.Contains(strings.ToUpper(out), strings.ToUpper(want)) {
			t.Errorf("缺少 %q：%s", want, out)
		}
	}
}

// ON 條件中之子查詢讀取受過濾之資料表時，亦須套用列過濾。
func TestDMLFromRewriteSubqueryInOn(t *testing.T) {
	out := rewriteWith(t, "UPDATE h SET h.Status = 1 FROM "+tH+" h JOIN "+tD+" d ON h.SalesOrderID = d.SalesOrderID AND d.ProductID IN (SELECT x.ProductID FROM "+tD+" x) WHERE h.SalesOrderID = 1", fD)
	if !strings.Contains(out, "x.OrderQty >= 5") {
		t.Errorf("ON 條件內子查詢未套用列過濾：%s", out)
	}
}

// SELECT 之 JOIN ... ON 條件中之子查詢亦須套用列過濾（A17；原先僅 WHERE／SELECT 清單內之子查詢被過濾）。
func TestSelectJoinOnSubqueryIsFiltered(t *testing.T) {
	out := rewriteWith(t, "SELECT h.SalesOrderID FROM "+tH+" h JOIN "+tD+" d ON h.SalesOrderID = d.SalesOrderID AND d.ProductID IN (SELECT x.ProductID FROM "+tD+" x)", fD)
	if !strings.Contains(out, "x.OrderQty >= 5") {
		t.Errorf("ON 條件內子查詢未套用列過濾：%s", out)
	}
	if strings.Count(out, "OrderQty >= 5") != 2 {
		t.Errorf("每個別名應各過濾一次（d 於 WHERE、x 於子查詢）：%s", out)
	}
}

// ON 條件內子查詢引用之資料表，須納入 schema 蒐集（否則綁定時找不到資料表）。
func TestSelectJoinOnSubqueryTableCollected(t *testing.T) {
	_, got := rmIntents(t, "SELECT h.SalesOrderID FROM "+tH+" h JOIN "+tD+" d ON h.SalesOrderID = d.SalesOrderID AND d.ProductID IN (SELECT c.CustomerID FROM SalesLT.Customer c)")
	if !got["Customer.CustomerID:"+IntentRead] {
		t.Errorf("ON 內子查詢之讀取須產生意圖：%v", got)
	}
}

// 無適用之列過濾時，語句應保持語意不變。
func TestDMLFromRewriteNoFilters(t *testing.T) {
	out := rewriteWith(t, updHDJoin)
	if !strings.Contains(out, "UPDATE h SET h.Status = 5 FROM "+tH+" AS h JOIN") {
		t.Errorf("無過濾時之重建結果異常：%s", out)
	}
}

func TestDMLFromFailClosed(t *testing.T) {
	bad := []string{
		// 缺 WHERE
		"UPDATE h SET h.Status = 1 FROM " + tH + " h",
		"DELETE h FROM " + tH + " h",
		// 逗號 JOIN
		"UPDATE h SET h.Status = 1 FROM " + tH + " h, " + tD + " d WHERE h.SalesOrderID = d.SalesOrderID",
		// APPLY
		"UPDATE h SET h.Status = 1 FROM " + tH + " h CROSS APPLY (SELECT 1 AS n) x WHERE h.SalesOrderID = 1",
		// 目標不存在
		"UPDATE nosuch SET Status = 1 FROM " + tH + " h WHERE h.SalesOrderID = 1",
		// 來源表不存在
		"DELETE h FROM " + tH + " h JOIN SalesLT.NoSuchTable n ON h.SalesOrderID = n.Id WHERE h.SalesOrderID = 1",
	}
	for _, sql := range bad {
		if _, err := NewAnalyser(tableFetch, 0).GetIntents(context.Background(), sql, 2, nil); err == nil {
			t.Errorf("應 Fail-Closed：%s", sql)
		}
	}
}
