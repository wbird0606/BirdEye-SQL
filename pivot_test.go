package birdeye

import (
	"context"
	"strings"
	"testing"
)

// pivot_test.go：PIVOT／UNPIVOT（KNOWN_DEVIATIONS A18）。
// 重點為安全性：來源讀取須產生意圖；列過濾須套用於「來源」而非轉置後之輸出。

const (
	pvDirect  = "SELECT p.CustomerID, p.[1], p.[2] FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1], [2])) AS p"
	pvDerived = "SELECT p.CustomerID, p.[1] FROM (SELECT CustomerID, Status, SubTotal FROM " + tH + ") AS s PIVOT (MAX(SubTotal) FOR Status IN ([1])) AS p"
	unpvSQL   = "SELECT u.SalesOrderID, u.col, u.val FROM (SELECT SalesOrderID, CustomerID, Status FROM " + tH + ") AS s UNPIVOT (val FOR col IN (CustomerID, Status)) AS u"
)

func TestPivotIntentsDirectTableReadsWholeTable(t *testing.T) {
	_, got := rmIntents(t, pvDirect)
	for _, col := range []string{"SalesOrderID", "CustomerID", "Status", "SubTotal"} {
		if !got["SalesOrderHeader."+col+":"+IntentRead] {
			t.Errorf("直接以資料表為來源時，所有欄位皆須為 READ：缺 %s；實得 %v", col, got)
		}
	}
	for k := range got {
		if strings.HasPrefix(k, "p.") {
			t.Errorf("PIVOT 別名不應被當成資料表：%s", k)
		}
	}
}

func TestPivotIntentsDerivedSource(t *testing.T) {
	_, got := rmIntents(t, pvDerived)
	for _, want := range []string{"SalesOrderHeader.CustomerID:" + IntentRead, "SalesOrderHeader.SubTotal:" + IntentRead, "SalesOrderHeader.Status:" + IntentRead} {
		if !got[want] {
			t.Errorf("缺少意圖 %s；實得 %v", want, got)
		}
	}
	for k := range got {
		if strings.HasPrefix(k, "p.") || strings.HasPrefix(k, "s.") {
			t.Errorf("別名不應被當成資料表：%s", k)
		}
	}
}

func TestUnpivotIntents(t *testing.T) {
	_, got := rmIntents(t, unpvSQL)
	for _, want := range []string{"SalesOrderHeader.SalesOrderID:" + IntentRead, "SalesOrderHeader.CustomerID:" + IntentRead, "SalesOrderHeader.Status:" + IntentRead} {
		if !got[want] {
			t.Errorf("缺少意圖 %s；實得 %v", want, got)
		}
	}
}

// 直接以資料表為來源：列過濾須改在來源（衍生資料表），不得放在轉置後之 WHERE。
func TestPivotRewriteFiltersSourceNotOutput(t *testing.T) {
	out := rewriteWith(t, pvDirect, fH)
	if !strings.Contains(out, "(SELECT * FROM "+tH+" WHERE SalesOrderHeader.SubTotal > 20000) AS SalesOrderHeader PIVOT (SUM([SubTotal]) FOR [Status] IN ([1], [2])) AS p") {
		t.Errorf("列過濾應套用於 PIVOT 之來源：%s", out)
	}
	if strings.Contains(out, "WHERE p.") || strings.HasSuffix(out, "> 20000") {
		t.Errorf("不得把過濾放在轉置後之輸出：%s", out)
	}
}

// 衍生資料表為來源：內層查詢各自過濾，PIVOT 子句原樣保留。
func TestPivotRewriteDerivedSource(t *testing.T) {
	out := rewriteWith(t, pvDerived, fH)
	if !strings.Contains(out, "SubTotal > 20000") || !strings.Contains(out, ") AS s PIVOT (MAX([SubTotal]) FOR [Status] IN ([1])) AS p") {
		t.Errorf("衍生來源之過濾或 PIVOT 子句異常：%s", out)
	}
}

func TestUnpivotRewrite(t *testing.T) {
	out := rewriteWith(t, unpvSQL, fH)
	if !strings.Contains(out, "SubTotal") && !strings.Contains(out, ") AS s UNPIVOT ([val] FOR [col] IN ([CustomerID], [Status])) AS u") {
		t.Errorf("UNPIVOT 改寫異常：%s", out)
	}
}

func TestPivotBinderOutputColumns(t *testing.T) {
	// 轉置後原來源之別名不可見；輸出欄位須存在
	for _, sql := range []string{
		"SELECT p.SalesOrderID FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1])) AS p", // 合法：分組欄位
	} {
		if _, err := NewAnalyser(tableFetch, 0).GetIntents(context.Background(), sql, 2, nil); err != nil {
			t.Errorf("應可解析 %q：%v", sql, err)
		}
	}
	bad := []string{
		"SELECT p.SubTotal FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1])) AS p",                            // 被聚合之欄位不在輸出
		"SELECT p.Status FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1])) AS p",                              // 轉置欄位不在輸出
		"SELECT SalesLT.SalesOrderHeader.SalesOrderID FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1])) AS p", // 原來源已不可見
		"SELECT p.x FROM " + tH + " PIVOT (SUM(Nope) FOR Status IN ([1])) AS p",                                       // 聚合欄位不存在
		"SELECT p.x FROM " + tH + " PIVOT (SUM(SubTotal) FOR Nope IN ([1])) AS p",                                     // FOR 欄位不存在
	}
	for _, sql := range bad {
		if _, err := NewAnalyser(tableFetch, 0).GetIntents(context.Background(), sql, 2, nil); err == nil {
			t.Errorf("應被拒絕：%s", sql)
		}
	}
}

func TestPivotFailClosed(t *testing.T) {
	bad := []string{
		"SELECT * FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1]))",                                    // 缺別名
		"SELECT * FROM " + tH + " PIVOT (EVIL(SubTotal) FOR Status IN ([1])) AS p",                              // 非白名單聚合
		"SELECT * FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ()) AS p",                                  // 空 IN
		"SELECT * FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1]) AS p",                                // 括號未閉合
		"SELECT * FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1'; DROP TABLE t;--])) AS p",             // 名稱含引號
		"SELECT * FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1])) AS [p]]x]",                          // 別名含括號
		"SELECT * FROM " + tH + " h JOIN " + tD + " d PIVOT (SUM(OrderQty) FOR ProductID IN ([1])) AS p ON 1=1", // JOIN 來源之 PIVOT
		"UPDATE h SET h.Status = 1 FROM " + tH + " h PIVOT (SUM(SubTotal) FOR Status IN ([1])) AS p WHERE h.SalesOrderID = 1",
		"SELECT * FROM " + tH + " PIVOT (SUM(SubTotal) FOR Status IN ([1])) AS p, " + tD, // 逗號 JOIN
	}
	for _, sql := range bad {
		if _, err := NewAnalyser(tableFetch, 0).GetIntents(context.Background(), sql, 2, nil); err == nil {
			t.Errorf("應 Fail-Closed：%s", sql)
		}
	}
}

// [PIVOT] 作為資料表別名仍為合法識別字；PIVOT 之後非 "(" 時不當成子句。
func TestPivotKeywordAsAliasStillWorks(t *testing.T) {
	for _, sql := range []string{
		"SELECT [PIVOT].SalesOrderID FROM " + tH + " [PIVOT]",
		"SELECT x.SalesOrderID FROM " + tH + " AS x",
	} {
		if _, err := NewAnalyser(tableFetch, 0).GetIntents(context.Background(), sql, 2, nil); err != nil {
			t.Errorf("%q 應可解析：%v", sql, err)
		}
	}
}
