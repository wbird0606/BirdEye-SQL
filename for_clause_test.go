package birdeye

import (
	"strings"
	"testing"
)

const forRegCSV = "table_schema,table_name,column_name,data_type\n" +
	"SalesLT,Customer,CustomerID,INT\nSalesLT,Customer,Name,NVARCHAR\n" +
	"SalesLT,Product,ProductID,INT\nSalesLT,Product,Name,NVARCHAR\n"

func forRecon(t *testing.T, sql string) (string, error) {
	t.Helper()
	res, err := NewRunner(mkReg(t, forRegCSV)).Run(sql, nil)
	if err != nil {
		return "", err
	}
	return NewReconstructor().Reconstruct(res.JSON)
}

func TestForClauseAccepted(t *testing.T) {
	cases := map[string]string{
		"SELECT CustomerID, Name FROM SalesLT.Customer FOR XML AUTO":                                                                     "FOR XML AUTO",
		"SELECT CustomerID FROM SalesLT.Customer c FOR XML RAW":                                                                          "FOR XML RAW",
		"SELECT CustomerID FROM SalesLT.Customer FOR XML RAW('row'), ROOT('rows'), ELEMENTS":                                             "FOR XML RAW('row'), ROOT('rows'), ELEMENTS",
		"SELECT Name FROM SalesLT.Customer ORDER BY Name FOR XML PATH('')":                                                               "FOR XML PATH('')",
		"SELECT Name FROM SalesLT.Customer FOR XML PATH(''), TYPE":                                                                       "FOR XML PATH(''), TYPE",
		"SELECT CustomerID FROM SalesLT.Customer FOR JSON PATH":                                                                          "FOR JSON PATH",
		"SELECT CustomerID FROM SalesLT.Customer FOR JSON AUTO, ROOT('r'), INCLUDE_NULL_VALUES":                                          "FOR JSON AUTO, ROOT('r'), INCLUDE_NULL_VALUES",
		"SELECT CustomerID FROM SalesLT.Customer FOR JSON PATH, WITHOUT_ARRAY_WRAPPER":                                                   "FOR JSON PATH, WITHOUT_ARRAY_WRAPPER",
		"SELECT 1 AS n FOR XML PATH":                                                                                                     "FOR XML PATH",
		"SELECT c.CustomerID FROM SalesLT.Customer c JOIN SalesLT.Product p ON c.CustomerID = p.ProductID FOR XML AUTO":                  "FOR XML AUTO",
		"SELECT p.Name FROM SalesLT.Customer c JOIN SalesLT.Product p ON c.CustomerID = p.ProductID WHERE c.CustomerID = 1 FOR XML PATH": "FOR XML PATH",
	}
	for sql, want := range cases {
		out, err := forRecon(t, sql)
		if err != nil {
			t.Errorf("應解析成功 %q: %v", sql, err)
			continue
		}
		if !strings.HasSuffix(out, want) {
			t.Errorf("重建 SQL 應以 %q 結尾：%q → %q", want, sql, out)
		}
	}
}

// 子查詢內之 FOR XML PATH(”)（字串聚合慣用法）須可解析並於重建時保留。
func TestForClauseInSubquery(t *testing.T) {
	sql := "SELECT c.CustomerID, (SELECT p.Name + ',' FROM SalesLT.Product p WHERE p.ProductID = c.CustomerID FOR XML PATH('')) AS names FROM SalesLT.Customer c"
	out, err := forRecon(t, sql)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "FOR XML PATH('')") {
		t.Fatalf("子查詢之 FOR 子句遺失：%q", out)
	}
}

// FOR 並非資料表別名；方括號形式之 [FOR] 仍為合法識別字。
func TestForClauseDoesNotBreakAliases(t *testing.T) {
	for _, sql := range []string{
		"SELECT [FOR].CustomerID FROM SalesLT.Customer [FOR]",
		"SELECT x.CustomerID FROM SalesLT.Customer AS x",
	} {
		if _, err := forRecon(t, sql); err != nil {
			t.Errorf("%q 應可解析: %v", sql, err)
		}
	}
}

// 未知模式、未知選項與含引號之名稱一律 Fail-Closed（重建後之 SQL 會被執行）。
func TestForClauseFailClosed(t *testing.T) {
	bad := []string{
		"SELECT Name FROM SalesLT.Customer FOR XML",
		"SELECT Name FROM SalesLT.Customer FOR XML BOGUS",
		"SELECT Name FROM SalesLT.Customer FOR JSON RAW",
		"SELECT Name FROM SalesLT.Customer FOR XML AUTO, EVIL",
		"SELECT Name FROM SalesLT.Customer FOR XML AUTO, TYPE, TYPE",
		"SELECT Name FROM SalesLT.Customer FOR XML PATH('x'');DROP TABLE t;--')",
		"SELECT Name FROM SalesLT.Customer FOR XML PATH('a' 'b')",
		"SELECT Name FROM SalesLT.Customer FOR XML PATH(x)",
		"SELECT Name FROM SalesLT.Customer FOR XML AUTO FOR XML RAW",
		"SELECT Name FROM SalesLT.Customer FOR BROWSE",
		"SELECT Name FROM SalesLT.Customer FOR UPDATE",
		"SELECT Name FROM SalesLT.Customer FOR XML AUTO, ROOT('r'), BINARY BASE65",
		"SELECT Name FROM SalesLT.Customer FOR XML AUTO, ELEMENTS XSINIL, ELEMENTS",
	}
	for _, sql := range bad {
		if _, err := forRecon(t, sql); err == nil {
			t.Errorf("應 Fail-Closed：%q", sql)
		}
	}
	// 多語句：FOR 子句後接分號與第二條語句，須整體被拒（單語句 Run）
	if _, err := forRecon(t, "SELECT Name FROM SalesLT.Customer FOR XML AUTO; DROP TABLE t"); err == nil {
		t.Error("FOR XML 後接第二條語句應被拒")
	}
}

// 列過濾仍須套用於帶 FOR XML 之查詢，且改寫後 FOR 子句仍位於最後。
func TestForClauseWithRowFilterRewrite(t *testing.T) {
	out := rewriteWith(t, "SELECT h.SalesOrderID FROM "+tH+" h WHERE h.SalesOrderID > 0 FOR XML PATH('')", fH)
	if !strings.Contains(out, "h.SubTotal > 20000") {
		t.Errorf("列過濾未套用：%s", out)
	}
	if !strings.HasSuffix(out, "FOR XML PATH('')") {
		t.Errorf("FOR 子句應位於最後：%s", out)
	}
	// 子查詢內之 FOR XML：內層資料表之列過濾亦須套用
	out = rewriteWith(t, "SELECT h.SalesOrderID, (SELECT d.OrderQty FROM "+tD+" d WHERE d.SalesOrderID = h.SalesOrderID FOR XML PATH('')) AS q FROM "+tH+" h", fD)
	if !strings.Contains(out, "d.OrderQty >= 5") || !strings.Contains(out, "FOR XML PATH('')") {
		t.Errorf("子查詢之列過濾或 FOR 子句缺失：%s", out)
	}
}
