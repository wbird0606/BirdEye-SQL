package birdeye

import (
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_binder_runner_coverage_suite.py
// —— binder.go / runner.go 的缺漏行。

func TestBRCov_Runner(t *testing.T) {
	// load_metadata_from_csv 吃字串
	r := NewRunner(nil)
	if err := r.LoadMetadataFromCSV("table_name,column_name,data_type\nAddress,AddressID,INT\n"); err != nil {
		t.Fatal(err)
	}
	if _, err := r.Run("SELECT AddressID FROM Address", nil); err != nil {
		t.Errorf("run: %v", err)
	}

	// ParseOnly 跳過 binder
	aw := loadAdventureWorks(t)
	if n, err := NewRunner(aw).ParseOnly("SELECT CustomerID FROM Customer", nil); err != nil || n == nil {
		t.Errorf("parse_only: %v", err)
	}
	if n, err := NewRunner(aw).ParseOnly("SELECT NonExistentColumn FROM NonExistentTable", nil); err != nil || n == nil {
		t.Errorf("parse_only 未知欄位應成功: %v", err)
	}

	// run_script 連續 GO / 空批次
	r2 := NewRunner(nil)
	r2.LoadMetadataFromCSV("table_name,column_name,data_type\nAddress,AddressID,INT\n")
	batches, err := r2.RunScript("SELECT AddressID FROM Address\nGO\n\nGO\nSELECT AddressID FROM Address", nil)
	if err != nil {
		t.Fatalf("run_script: %v", err)
	}
	if len(batches) != 2 {
		t.Errorf("連續 GO 應得 2 個非空批次，得 %d", len(batches))
	}
}

func TestBRCov_BinderViaRunner(t *testing.T) {
	aw := loadAdventureWorks(t)
	ok := func(sql string) {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q 應成功: %v", sql, err)
		}
	}
	semErr := func(sql, sub string) {
		_, err := NewRunner(aw).Run(sql, nil)
		if err == nil || (sub != "" && !strings.Contains(err.Error(), sub)) {
			t.Errorf("%q -> %v，want 含 %q", sql, err, sub)
		}
	}

	ok("DECLARE @x INT = 5")
	ok("WITH cte AS (SELECT CustomerID FROM Customer) SELECT CustomerID FROM cte")
	ok("SELECT AddressID FROM Address WHERE ModifiedDate > '2020-01-01'")
	ok("SELECT (SELECT CustomerID, CompanyName FROM Customer WHERE CustomerID = 1) FROM Customer")

	semErr("SELECT xyz.CustomerID FROM Customer", "Unknown qualifier 'xyz'")
	semErr("WITH cte AS (SELECT CustomerID FROM Customer) SELECT NonExistent FROM cte", "")
	semErr("WITH cte AS (SELECT CustomerID FROM Customer) SELECT CompanyName FROM cte", "")
	semErr("SELECT CustomerID FROM Customer WHERE CustomerID > ANY (SELECT CompanyName FROM Customer WHERE CustomerID = 1)", "")
	semErr("SELECT LEN(CompanyName), COUNT(*) FROM Customer GROUP BY CustomerID", "")
	semErr("SELECT CASE WHEN CompanyName = 'AW00000001' THEN 'yes' ELSE 'no' END, COUNT(*) FROM Customer GROUP BY CustomerID", "")
}

func TestBRCov_BinderDirect(t *testing.T) {
	reg := mkReg(t, "table_name,column_name,data_type\nT,Col1,INT\n")

	// bindUnion：右側為非 Select/Union 節點 → 欄位數為 0 → mismatch
	union := &UnionStatement{
		Left:     mustParse(t, "SELECT Col1 FROM T"),
		Right:    NewLiteral("1", NumericLiteral),
		Operator: "UNION",
	}
	err := recoverBail(func() { NewBinder(reg).bindUnion(union) })
	if err == nil || !strings.Contains(err.Msg, "equal number of expressions") {
		t.Errorf("bindUnion get_cols fallback -> %v", err)
	}

	// resolveIdentifier：表在 scope、qualifier 對得上，但 registry 無欄位清單 → pass-through
	ghost := NewMetadataRegistry()
	ghost.tables["GHOSTCOLS"] = map[string]string{}
	b := NewBinder(ghost)
	b.scopes = append(b.scopes, newScopeFrame())
	b.scopes[0].set("GHOSTCOLS", "GHOSTCOLS")
	b.nullableStack = append(b.nullableStack, map[string]bool{})
	node := NewIdentifier("SomeCol", []string{"GHOSTCOLS"})
	if err := recoverBail(func() { b.resolveIdentifier(node) }); err != nil {
		t.Errorf("resolveIdentifier pass-through 不應報錯：%v", err)
	}
}

func TestBRCov_DeclareInScript(t *testing.T) {
	r := NewRunner(nil)
	r.LoadMetadataFromCSV("table_name,column_name,data_type\nAddress,AddressID,INT\n")
	batches, err := r.RunScript("DECLARE @id INT = 5\nSELECT AddressID FROM Address WHERE AddressID = @id", nil)
	if err != nil {
		t.Fatalf("DECLARE + SELECT 同批次: %v", err)
	}
	if len(batches) != 1 || len(batches[0]) != 2 {
		t.Errorf("應為 1 批次 2 語句：%v", batches)
	}
}
