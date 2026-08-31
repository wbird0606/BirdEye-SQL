package birdeye

import "testing"

// 對照 birdeye_1150831/tests/test_cte_suite.py（+ test_cte_dml_suite.py）

func TestCTE_Suite(t *testing.T) {
	aw := loadAdventureWorks(t)

	res := intgRun(t, aw, "WITH BasicCTE AS (SELECT AddressID, City FROM Address) SELECT City FROM BasicCTE")
	sel := res.AST.(*SelectStatement)
	if len(sel.CTEs) != 1 || sel.CTEs[0].Name != "BASICCTE" {
		t.Errorf("CTE parse: %+v", sel.CTEs)
	}

	star := intgRun(t, aw, "WITH SimpleCTE AS (SELECT AddressID, City FROM Address) SELECT * FROM SimpleCTE").AST.(*SelectStatement)
	if len(star.Columns) != 2 ||
		star.Columns[0].(*IdentifierNode).Name != "ADDRESSID" ||
		star.Columns[1].(*IdentifierNode).Name != "CITY" {
		t.Errorf("CTE star expansion: %+v", star.Columns)
	}

	multi := intgRun(t, aw, "WITH CTE1 AS (SELECT 1 AS A), CTE2 AS (SELECT 2 AS B) SELECT A, B FROM CTE1 JOIN CTE2 ON 1=1").AST.(*SelectStatement)
	if len(multi.CTEs) != 2 || multi.CTEs[0].Name != "CTE1" || multi.CTEs[1].Name != "CTE2" {
		t.Errorf("multiple CTE: %+v", multi.CTEs)
	}
}

func TestCTE_DML(t *testing.T) {
	aw := loadAdventureWorks(t)

	upd := mustParse(t, "WITH CTE AS (SELECT AddressID FROM Address) UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM CTE)").(*UpdateStatement)
	if len(upd.CTEs) != 1 || upd.CTEs[0].Name != "CTE" {
		t.Errorf("CTE UPDATE: %+v", upd.CTEs)
	}
	del := mustParse(t, "WITH CTE AS (SELECT AddressID FROM Address WHERE AddressID < 0) DELETE FROM Address WHERE AddressID IN (SELECT AddressID FROM CTE)").(*DeleteStatement)
	if len(del.CTEs) != 1 {
		t.Errorf("CTE DELETE: %+v", del.CTEs)
	}

	oks := []string{
		"WITH CTE AS (SELECT AddressID FROM Address) UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM CTE)",
		"WITH FilteredIDs AS (SELECT AddressID FROM Address WHERE AddressID > 10) UPDATE Address SET City = 'Updated' WHERE AddressID IN (SELECT AddressID FROM FilteredIDs)",
		"WITH CTE AS (SELECT AddressID FROM Address WHERE AddressID < 0) DELETE FROM Address WHERE AddressID IN (SELECT AddressID FROM CTE)",
		"WITH A AS (SELECT AddressID FROM Address), B AS (SELECT AddressID FROM Address WHERE AddressID > 5) UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM A) AND AddressID IN (SELECT AddressID FROM B)",
	}
	for _, sql := range oks {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}

	// CTE 只在該語句內有效
	if _, err := NewRunner(aw).Run("WITH TempCTE AS (SELECT AddressID FROM Address) UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM TempCTE)", nil); err != nil {
		t.Fatal(err)
	}
	if _, err := NewRunner(aw).Run("SELECT AddressID FROM TempCTE", nil); err == nil {
		t.Error("CTE 不應洩漏到後續查詢")
	}
}
