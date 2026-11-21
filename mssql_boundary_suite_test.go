package birdeye

import (
	"strings"
	"testing"
)

// 對照 python-final:tests/test_mssql_boundary_suite.py
// —— 負數字面值 / ##全域臨時表 / APPLY 無別名 / 位元 & 模 / UNION derived table /
//    字串函數 / CAST-CONVERT 增強 / COUNT(DISTINCT) / INTERSECT-EXCEPT /
//    純量子查詢 / TRY_CAST-TRY_CONVERT / 巢狀 derived table / bracket 別名。

func TestMSSQLBoundary_Suite(t *testing.T) {
	aw := loadAdventureWorks(t)
	ok := func(sql string) {
		t.Helper()
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	okMulti := func(sql string) {
		t.Helper()
		if _, err := NewRunner(aw).RunMulti(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	// Python 以兩次 global_runner.run() 依賴跨呼叫的 temp_schemas 外洩（KNOWN_DEVIATIONS B1）；
	// Go 每次 Run() 全新 binder，等價寫法是同一個 RunScript 內以 GO 分批。
	okScript := func(sql string) {
		t.Helper()
		if _, err := NewRunner(aw).RunScript(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}

	// Bug-1: 負數字面值
	ok("SELECT AddressID FROM Address WHERE AddressID = -1")
	ok("SELECT -1")
	ok("SELECT AddressID - -1 FROM Address")
	col := mustParse(t, "SELECT -5").(*SelectStatement).Columns[0]
	isNegLit := false
	if l, o := col.(*LiteralNode); o && strings.HasPrefix(l.Value, "-") {
		isNegLit = true
	}
	isUnary := false
	if b, o := col.(*BinaryExpressionNode); o && b.Operator == "-" {
		isUnary = true
	}
	if !isNegLit && !isUnary {
		t.Errorf("-5 應為負數 literal 或一元負號：%T", col)
	}

	// Bug-2: ##全域臨時表
	okMulti("SELECT AddressID, City INTO ##GAddr FROM Address")
	okScript("SELECT AddressID INTO ##GT1 FROM Address\nGO\nSELECT AddressID FROM ##GT1")
	okScript("SELECT AddressID, City INTO ##GT2 FROM Address\nGO\nSELECT AddressID FROM ##GT2 WHERE AddressID > 0")
	okScript("SELECT AddressID INTO ##GT3 FROM Address\nGO\nSELECT a.AddressID FROM Address a JOIN ##GT3 g ON a.AddressID = g.AddressID")

	// Bug-3: CROSS APPLY 無別名
	ok("SELECT a.AddressID FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID)")
	ok("SELECT a.City FROM Address a CROSS APPLY (SELECT AddressID FROM Address WHERE City = a.City)")
	if _, err := NewRunner(aw).Run("SELECT a.AddressID, ghost.City FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID)", nil); err == nil {
		t.Error("無別名 APPLY 的 qualifier 存取應報錯")
	}

	// 模 % / 位元 &
	for _, sql := range []string{
		"SELECT AddressID % 2 FROM Address",
		"SELECT AddressID FROM Address WHERE AddressID % 2 = 0",
		"SELECT AddressID % 10 AS Remainder FROM Address",
		"SELECT AddressID & 1 FROM Address",
		"SELECT AddressID FROM Address WHERE AddressID & 1 = 1",
		"SELECT AddressID & 255 AS Masked FROM Address",
		"SELECT AddressID % 10 AS Mod, AddressID & 255 AS Bits FROM Address",
	} {
		ok(sql)
	}

	// UNION 衍生資料表
	for _, sql := range []string{
		"SELECT Sub.AddressID FROM (SELECT AddressID FROM Address UNION SELECT AddressID FROM Address) AS Sub",
		"SELECT Sub.AddressID FROM (SELECT AddressID FROM Address UNION ALL SELECT AddressID FROM Address) AS Sub",
		"SELECT Sub.AddressID FROM (SELECT AddressID FROM Address WHERE AddressID = 1 UNION SELECT AddressID FROM Address WHERE AddressID = 2) AS Sub WHERE Sub.AddressID > 0",
		"SELECT * FROM (SELECT AddressID FROM Address UNION SELECT AddressID FROM Address) AS Sub",
	} {
		ok(sql)
	}

	// 字串函數
	for _, sql := range []string{
		"SELECT CONCAT(City, ', ', AddressLine1) FROM Address",
		"SELECT CONCAT(City, AddressLine1) FROM Address",
		"SELECT FORMAT(ModifiedDate, 'yyyy-MM-dd') FROM Address",
		"SELECT SPACE(5)",
		"SELECT ASCII(City) FROM Address",
		"SELECT CHAR(65)",
	} {
		ok(sql)
	}

	// CAST / CONVERT 增強
	for _, sql := range []string{
		"SELECT CAST(AddressID AS VARCHAR(10)) FROM Address",
		"SELECT CAST(AddressID AS DECIMAL(18,2)) FROM Address",
		"SELECT CONVERT(VARCHAR(20), ModifiedDate) FROM Address",
		"SELECT CONVERT(VARCHAR, ModifiedDate, 120) FROM Address",
		"SELECT CONVERT(VARCHAR(20), ModifiedDate, 120) FROM Address",
	} {
		ok(sql)
	}

	// COUNT(DISTINCT)
	ok("SELECT COUNT(DISTINCT City) FROM Address")
	ok("SELECT AddressID, COUNT(DISTINCT City) AS UniqCities FROM Address GROUP BY AddressID")

	// INTERSECT / EXCEPT
	for _, sql := range []string{
		"SELECT AddressID FROM Address INTERSECT SELECT AddressID FROM Address",
		"SELECT AddressID FROM Address EXCEPT SELECT AddressID FROM Address",
		"SELECT AddressID FROM Address WHERE AddressID = 1 INTERSECT SELECT AddressID FROM Address WHERE AddressID = 2",
		"SELECT Sub.AddressID FROM (SELECT AddressID FROM Address EXCEPT SELECT AddressID FROM Address WHERE AddressID < 0) AS Sub",
	} {
		ok(sql)
	}

	// 純量子查詢
	for _, sql := range []string{
		"SELECT (SELECT MAX(AddressID) FROM Address) AS MaxID",
		"SELECT AddressID, (SELECT MAX(AddressID) FROM Address) AS MaxID FROM Address",
		"SELECT AddressID FROM Address a WHERE AddressID IN (SELECT AddressID FROM Address a2 WHERE a2.AddressID = a.AddressID)",
	} {
		ok(sql)
	}

	// TRY_CAST / TRY_CONVERT
	for _, sql := range []string{
		"SELECT TRY_CAST(City AS INT) FROM Address",
		"SELECT TRY_CAST(AddressID AS VARCHAR) FROM Address",
		"SELECT TRY_CAST(AddressID AS VARCHAR(10)) FROM Address",
		"SELECT TRY_CAST(City AS INT) AS NumericCity FROM Address",
		"SELECT TRY_CONVERT(INT, City) FROM Address",
		"SELECT TRY_CONVERT(VARCHAR, ModifiedDate, 120) FROM Address",
		"SELECT TRY_CONVERT(VARCHAR(20), AddressID) FROM Address",
	} {
		ok(sql)
	}

	// 巢狀衍生資料表 / bracket 別名
	for _, sql := range []string{
		"SELECT Outer2.AddressID FROM (SELECT AddressID FROM (SELECT AddressID FROM Address) AS Inner2) AS Outer2",
		"SELECT Lvl2.AddressID FROM (SELECT AddressID FROM (SELECT AddressID FROM Address WHERE AddressID > 0) AS Lvl1) AS Lvl2 WHERE Lvl2.AddressID > 0",
		"SELECT Outer3.AddressID FROM (SELECT AddressID FROM Address UNION SELECT AddressID FROM Address) AS Outer3",
		"SELECT [Outer].AddressID FROM (SELECT AddressID FROM Address) AS [Outer]",
		"SELECT [Inner].AddressID FROM (SELECT AddressID FROM Address) AS [Inner]",
	} {
		ok(sql)
	}
}
