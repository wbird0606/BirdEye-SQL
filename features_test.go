package birdeye

import (
	"strings"
	"testing"
)

// features_test.go：跨 test_functions / test_window_functions / test_dml / test_join /
// test_subquery / test_cte / test_mssql_boundary / test_select_features 的高價值斷言
// （SemanticError 路徑、AST 結構、型別推導、覆蓋率邊角）。
// 每條 SQL 的完整 pipeline 輸出已由 conformance byte 驗。

func awRun(t *testing.T) func(string) (*SelectStatement, error) {
	aw := loadAdventureWorks(t)
	return func(sql string) (*SelectStatement, error) {
		res, err := NewRunner(aw).Run(sql, nil)
		if err != nil {
			return nil, err
		}
		st, _ := res.AST.(*SelectStatement)
		return st, nil
	}
}

func wantMsg(t *testing.T, err error, sub string) {
	t.Helper()
	if err == nil {
		t.Fatalf("預期錯誤含 %q，卻成功", sub)
	}
	if !strings.Contains(err.Error(), sub) {
		t.Fatalf("錯誤 %q 未含 %q", err.Error(), sub)
	}
}

func TestFunctionSandbox(t *testing.T) {
	run := awRun(t)
	if st, err := run("SELECT UPPER(FirstName), LEN(LastName) FROM Customer"); err != nil ||
		st.Columns[0].(*FunctionCallNode).Name != "UPPER" || st.Columns[1].(*FunctionCallNode).Name != "LEN" {
		t.Errorf("scalar func binding: %v", err)
	}
	_, err := run("SELECT LEN(FirstName, LastName) FROM Customer")
	wantMsg(t, err, "Function 'LEN' expects 1 arguments, got 2")
	_, err = run("SELECT SUBSTRING(FirstName, 'A', 'B') FROM Customer")
	wantMsg(t, err, "Function 'SUBSTRING' expects INT, but got NVARCHAR")
	_, err = run("SELECT GHOST_FUNC(FirstName) FROM Customer")
	wantMsg(t, err, "Unknown function 'GHOST_FUNC'")
	_, err = run("SELECT IS_SRVROLEMEMBER('sysadmin')")
	wantMsg(t, err, "Function 'IS_SRVROLEMEMBER' is restricted")

	// NULL 處理 / 數值 / 日期函數皆應成功
	for _, sql := range []string{
		"SELECT ISNULL(City, 'Unknown') FROM Address",
		"SELECT COALESCE(City, AddressLine1) FROM Address",
		"SELECT NULLIF(City, AddressLine1) FROM Address",
		"SELECT IIF(AddressID > 0, 'Positive', 'Zero') FROM Address",
		"SELECT ABS(AddressID), CEILING(AddressID), FLOOR(AddressID) FROM Address",
		"SELECT DATEDIFF(DAY, ModifiedDate, GETDATE()) FROM Address",
		"SELECT YEAR(ModifiedDate), MONTH(ModifiedDate), DAY(ModifiedDate) FROM Address",
		"SELECT COUNT(DISTINCT City) FROM Address",
	} {
		if _, err := run(sql); err != nil {
			t.Errorf("%q 應成功: %v", sql, err)
		}
	}
}

func TestWindowFunctions(t *testing.T) {
	run := awRun(t)
	for _, sql := range []string{
		"SELECT ROW_NUMBER() OVER (ORDER BY AddressID) FROM Address",
		"SELECT RANK() OVER (PARTITION BY City ORDER BY AddressID) FROM Address",
		"SELECT SUM(AddressID) OVER (PARTITION BY City) FROM Address",
		"SELECT LAG(AddressID, 1) OVER (ORDER BY AddressID) FROM Address",
		"SELECT AVG(AddressID) OVER (ORDER BY AddressID ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM Address",
	} {
		st, err := run(sql)
		if err != nil {
			t.Errorf("%q: %v", sql, err)
			continue
		}
		if st.Columns[0].(*FunctionCallNode).OverClause == nil {
			t.Errorf("%q: OVER 子句遺失", sql)
		}
	}
	// SUM OVER 不應觸發 GROUP BY 誤判
	if _, err := run("SELECT AddressID, SUM(AddressID) OVER (PARTITION BY City) FROM Address"); err != nil {
		t.Errorf("SUM OVER 不應要求 GROUP BY: %v", err)
	}
	// 純聚合則要求 GROUP BY
	_, err := run("SELECT AddressID, SUM(AddressID) FROM Address")
	wantMsg(t, err, "must appear in the GROUP BY clause")
}

func TestJoinAndSubquery(t *testing.T) {
	run := awRun(t)
	// 多表 JOIN，未限定欄位歧義
	_, err := run("SELECT CustomerID FROM SalesLT.Customer JOIN SalesLT.CustomerAddress ON 1=1")
	wantMsg(t, err, "ambiguous")
	// JOIN 類型
	for _, jt := range []struct{ sql, typ string }{
		{"SELECT c.CustomerID FROM SalesLT.Customer c JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID", "INNER"},
		{"SELECT c.CustomerID FROM SalesLT.Customer c LEFT JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID", "LEFT"},
		{"SELECT c.CustomerID FROM SalesLT.Customer c RIGHT JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID", "RIGHT"},
		{"SELECT c.CustomerID FROM SalesLT.Customer c FULL OUTER JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID", "FULL"},
		{"SELECT c.CustomerID FROM SalesLT.Customer c CROSS JOIN SalesLT.CustomerAddress ca", "CROSS"},
	} {
		st, err := run(jt.sql)
		if err != nil || st.Joins[0].Type != jt.typ {
			t.Errorf("%q: join type %v (%v)", jt.sql, st, err)
		}
	}
	// 子查詢
	for _, sql := range []string{
		"SELECT ProductID FROM SalesLT.Product WHERE ProductID IN (SELECT ProductID FROM SalesLT.SalesOrderDetail)",
		"SELECT ProductID FROM SalesLT.Product WHERE ProductID NOT IN (SELECT ProductID FROM SalesLT.SalesOrderDetail)",
		"SELECT ProductID FROM SalesLT.Product WHERE EXISTS (SELECT 1 FROM SalesLT.SalesOrderDetail WHERE ProductID = 1)",
		"SELECT ProductID FROM SalesLT.Product WHERE ProductID > ANY (SELECT ProductID FROM SalesLT.SalesOrderDetail)",
		"SELECT sub.City FROM (SELECT City FROM SalesLT.Address) sub",
	} {
		if _, err := run(sql); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
}

func TestCTEAndSetOps(t *testing.T) {
	run := awRun(t)
	for _, sql := range []string{
		"WITH c AS (SELECT AddressID FROM SalesLT.Address) SELECT AddressID FROM c",
		"WITH c1 AS (SELECT AddressID FROM SalesLT.Address), c2 AS (SELECT CustomerID FROM SalesLT.Customer) SELECT AddressID FROM c1",
		"SELECT AddressID FROM SalesLT.Address UNION SELECT AddressID FROM SalesLT.Address",
		"SELECT AddressID FROM SalesLT.Address INTERSECT SELECT AddressID FROM SalesLT.Address",
		"SELECT AddressID FROM SalesLT.Address EXCEPT SELECT AddressID FROM SalesLT.Address",
	} {
		if _, err := run(sql); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	// UNION 欄位數不符
	_, err := NewRunner(loadAdventureWorks(t)).Run("SELECT AddressID FROM SalesLT.Address UNION SELECT AddressID, City FROM SalesLT.Address", nil)
	wantMsg(t, err, "equal number of expressions")
}

func TestMSSQLBoundary(t *testing.T) {
	run := awRun(t)
	// 負數字面值 / 一元位元補數
	st, err := run("SELECT -5, ~1 FROM Address")
	if err != nil {
		t.Fatal(err)
	}
	if lit, ok := st.Columns[0].(*LiteralNode); !ok || lit.Value != "-5" {
		t.Errorf("負數字面值: %v", st.Columns[0])
	}
	// 位元運算子
	for _, sql := range []string{
		"SELECT AddressID & 1, AddressID | 2, AddressID ^ 3 FROM Address",
		"SELECT AddressID % 2 FROM Address",
	} {
		if _, err := run(sql); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	// ##global temp
	res, err := NewRunner(loadAdventureWorks(t)).RunMulti("SELECT AddressID INTO ##G FROM Address; SELECT AddressID FROM ##G", nil)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Binder.TempSchemas()["##G"] {
		t.Errorf("##G 應註冊: %v", res.Binder.TempSchemas())
	}
	// 字串函數
	for _, sql := range []string{
		"SELECT LEFT(City, 3), RIGHT(City, 2), REVERSE(City) FROM Address",
		"SELECT STUFF(City, 1, 2, 'XX'), REPLICATE(City, 2) FROM Address",
	} {
		if _, err := run(sql); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
}

func TestSelectFeatures(t *testing.T) {
	run := awRun(t)
	// TOP 變體
	for _, sql := range []string{
		"SELECT TOP 5 AddressID FROM Address",
		"SELECT TOP (10) AddressID FROM Address",
		"SELECT TOP 10 PERCENT AddressID FROM Address",
	} {
		if _, err := run(sql); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	// OFFSET/FETCH
	st, err := run("SELECT AddressID FROM Address ORDER BY AddressID OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY")
	if err != nil || st.OffsetCount == nil || *st.OffsetCount != 10 || st.FetchCount == nil || *st.FetchCount != 5 {
		t.Errorf("offset/fetch: %v %v", st, err)
	}
	// 3-part 表名
	if _, err := run("SELECT AddressID FROM [AdventureWorksLT].[SalesLT].[Address]"); err != nil {
		t.Errorf("3-part name: %v", err)
	}
	// GROUP BY + HAVING
	if _, err := run("SELECT City, COUNT(*) FROM Address GROUP BY City HAVING COUNT(*) > 1"); err != nil {
		t.Errorf("group by/having: %v", err)
	}
	// DISTINCT
	if st, _ := run("SELECT DISTINCT City FROM Address"); st == nil || !st.IsDistinct {
		t.Error("distinct")
	}
	// ORDER BY alias
	if _, err := run("SELECT AddressID AS x FROM Address ORDER BY x"); err != nil {
		t.Errorf("order by alias: %v", err)
	}
}
