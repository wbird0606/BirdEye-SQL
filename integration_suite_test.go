package birdeye

import (
	"strings"
	"testing"
)

// 對照 python-final:tests/test_integration_suite.py

func intgRun(t *testing.T, aw *MetadataRegistry, sql string) *Result {
	t.Helper()
	res, err := NewRunner(aw).Run(sql, nil)
	if err != nil {
		t.Fatalf("run %q: %v", sql, err)
	}
	return res
}

func intgErr(t *testing.T, aw *MetadataRegistry, sql, want string) {
	t.Helper()
	_, err := NewRunner(aw).Run(sql, nil)
	if err == nil || !strings.Contains(err.Error(), want) {
		t.Errorf("%q -> %v，want 含 %q", sql, err, want)
	}
}

func colType(n Node) string { return inferredTypeOf(n) }

func TestIntegration_FullPipeline(t *testing.T) {
	aw := loadAdventureWorks(t)
	res := intgRun(t, aw, "SELECT AddressID, City FROM Address WHERE AddressID > 0")
	if !strings.Contains(res.Tree, "SELECT_STATEMENT") || !strings.Contains(res.Tree, "IDENTIFIER: AddressID") {
		t.Errorf("tree: %s", res.Tree)
	}
	if !strings.Contains(res.Mermaid, "flowchart TD") {
		t.Errorf("mermaid: %s", res.Mermaid)
	}
	if colType(res.AST.(*SelectStatement).Columns[0]) != "INT" {
		t.Errorf("AddressID type %s", colType(res.AST.(*SelectStatement).Columns[0]))
	}
}

func TestIntegration_SemanticDefenses(t *testing.T) {
	aw := loadAdventureWorks(t)
	intgErr(t, aw, "SELECT CustomerID FROM SalesOrderHeader AS h JOIN Customer AS c ON h.CustomerID = c.CustomerID", "Column 'CustomerID' is ambiguous")
	intgErr(t, aw, "UPDATE Product SET ListPrice = 99.9 WHERE GhostColumn = 1", "Column 'GhostColumn' not found in 'Product'")
	intgErr(t, aw, "SELECT Address.AddressID FROM Address AS a", "Original table name 'Address' cannot be used")
	intgErr(t, aw, "SELECT ModifiedDate FROM SalesOrderHeader h JOIN Address a ON h.BillToAddressID = a.AddressID", "Column 'ModifiedDate' is ambiguous")
	intgErr(t, aw, "SELECT ProductID, Name FROM Product GROUP BY ProductID", "Column 'Name' must appear in the GROUP BY clause")
}

func TestIntegration_TypeInference(t *testing.T) {
	aw := loadAdventureWorks(t)
	if colType(intgRun(t, aw, "SELECT UnitPrice * OrderQty FROM SalesOrderDetail").AST.(*SelectStatement).Columns[0]) != "INT" {
		t.Error("UnitPrice * OrderQty -> INT")
	}
	whereNode := intgRun(t, aw, "SELECT SalesOrderID FROM SalesOrderHeader WHERE OrderDate >= '2023-01-01'").AST.(*SelectStatement).Where
	if eb := exprOf(whereNode); eb == nil || eb.InferredType != "BIT" {
		t.Errorf("where inferred_type: %v", whereNode)
	}
	ob := intgRun(t, aw, "SELECT (ListPrice - StandardCost) / StandardCost AS ProfitMargin FROM Product ORDER BY ProfitMargin DESC").AST.(*SelectStatement).OrderBy[0].Column
	if colType(ob) != "INT" {
		t.Errorf("order by alias type: %s", colType(ob))
	}
	if colType(intgRun(t, aw, "SELECT CASE WHEN ListPrice > 1000 THEN 'Premium' ELSE 'Standard' END AS Tier FROM Product").AST.(*SelectStatement).Columns[0]) != "NVARCHAR" {
		t.Error("CASE -> NVARCHAR")
	}
}

func TestIntegration_StringEscaping(t *testing.T) {
	aw := loadAdventureWorks(t)
	lit := intgRun(t, aw, "SELECT 'O''Brien' FROM Address").AST.(*SelectStatement).Columns[0].(*LiteralNode)
	if lit.Value != "O'Brien" {
		t.Errorf("escape: %q", lit.Value)
	}
}

func TestIntegration_RunScript(t *testing.T) {
	aw := loadAdventureWorks(t)

	b1, err := NewRunner(aw).RunScript("DECLARE @city NVARCHAR(50)\nSELECT City INTO #FilteredAddr FROM Address WHERE City = @city", nil)
	if err != nil {
		t.Fatalf("declare+into: %v", err)
	}
	if len(b1) != 1 || len(b1[0]) != 2 {
		t.Errorf("batches: %v", b1)
	}

	b2, err := NewRunner(aw).RunScript("SELECT AddressID, City INTO #BatchTemp FROM Address\nGO\nSELECT AddressID FROM #BatchTemp", nil)
	if err != nil {
		t.Fatalf("go batch: %v", err)
	}
	if len(b2) != 2 {
		t.Errorf("go batches len %d", len(b2))
	}

	for _, sql := range []string{
		"DECLARE @id INT\nSELECT a.City FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = @id) sub",
		"DECLARE @uid UNIQUEIDENTIFIER",
		"DECLARE @uid UNIQUEIDENTIFIER\nSELECT rowguid FROM Address WHERE rowguid = @uid",
	} {
		if _, err := NewRunner(aw).RunScript(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}

	// 錯誤路徑：; 後非關鍵字片段解析失敗、前導非語句內容、bind 失敗
	for _, sql := range []string{
		"SELECT AddressID FROM Address; FOOBAR",
		"x\nSELECT AddressID FROM Address",
		"UPDATE GhostTable SET c = 1",
	} {
		if _, err := NewRunner(aw).RunScript(sql, nil); err == nil {
			t.Errorf("%q 應報錯", sql)
		}
	}
	// 參數格式錯誤（prepareSQL 失敗路徑）
	if _, err := NewRunner(aw).RunScript("SELECT ?", nil); err == nil {
		t.Error("SELECT ? 無參數應報錯")
	}
}

func TestIntegration_ApplyCrossFeature(t *testing.T) {
	aw := loadAdventureWorks(t)
	oks := []string{
		"SELECT a.AddressID, sub.City FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub ORDER BY a.AddressID",
		"SELECT a.AddressID, sub.City FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub WHERE a.AddressID > 1",
		"SELECT a.AddressID, s1.City, s2.City FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) s1 CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) s2",
		"SELECT a.AddressID FROM Address a CROSS APPLY (SELECT rowguid FROM Address WHERE rowguid = NEWID()) sub",
		"WITH AddrCTE AS (SELECT AddressID FROM Address) SELECT c.AddressID, sub.City FROM AddrCTE c CROSS APPLY (SELECT City FROM Address WHERE AddressID = c.AddressID) sub",
		"SELECT a.AddressID FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub UNION SELECT AddressID FROM Address",
		"SELECT t.AddressID, sub.City FROM Address t CROSS APPLY (SELECT City FROM Address WHERE AddressID = t.AddressID) sub",
	}
	for _, sql := range oks {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
}
