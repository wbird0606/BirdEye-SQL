package birdeye

import (
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_functions_suite.py（+ builtin_functions）

func funcReg(t *testing.T) *MetadataRegistry {
	reg := mkReg(t, "table_name,column_name,data_type\nUsers,UserName,NVARCHAR\nUsers,Password,NVARCHAR\n")
	reg.RegisterFunction("LEN", "SCALAR", 1, 1, nil, "")
	reg.RegisterFunction("UPPER", "SCALAR", 1, 1, nil, "")
	reg.RegisterFunction("LOWER", "SCALAR", 1, 1, nil, "")
	reg.RegisterFunction("SUBSTRING", "SCALAR", 3, 3, nil, "")
	reg.RegisterFunction("GETDATE", "SCALAR", 0, 0, nil, "")
	reg.RegisterFunction("SUM", "AGGREGATE", 1, 1, nil, "")
	return reg
}

func TestFunctions_ScalarBinding(t *testing.T) {
	aw := loadAdventureWorks(t)
	st := intgRun(t, aw, "SELECT UPPER(FirstName), LEN(LastName) FROM Customer").AST.(*SelectStatement)
	if st.Columns[0].(*FunctionCallNode).Name != "UPPER" || st.Columns[1].(*FunctionCallNode).Name != "LEN" {
		t.Errorf("cols: %+v", st.Columns)
	}
}

func TestFunctions_SemanticErrors(t *testing.T) {
	aw := loadAdventureWorks(t)
	cases := []struct{ sql, want string }{
		{"SELECT LEN(FirstName, LastName) FROM Customer", "Function 'LEN' expects 1 arguments, got 2"},
		{"SELECT SUBSTRING(FirstName, 'A', 'B') FROM Customer", "Function 'SUBSTRING' expects INT, but got NVARCHAR"},
		{"SELECT GHOST_FUNC(FirstName) FROM Customer", "Unknown function 'GHOST_FUNC'"},
		{"SELECT IS_SRVROLEMEMBER('sysadmin')", "Function 'IS_SRVROLEMEMBER' is restricted"},
	}
	for _, c := range cases {
		intgErr(t, aw, c.sql, c.want)
	}
}

func TestFunctions_NestedInCase(t *testing.T) {
	reg := funcReg(t)
	ast := mustBind(t, reg, "SELECT CASE WHEN LEN(UserName) > 5 THEN UPPER(UserName) ELSE LOWER(UserName) END FROM Users").(*SelectStatement)
	then := ast.Columns[0].(*CaseExpressionNode).Branches[0].Then.(*FunctionCallNode)
	if then.Name != "UPPER" {
		t.Errorf("branch then: %q", then.Name)
	}
}

func TestFunctions_BuiltinsRunClean(t *testing.T) {
	aw := loadAdventureWorks(t)
	oks := []string{
		// NULL 處理
		"SELECT ISNULL(City, 'Unknown') FROM Address",
		"SELECT COALESCE(City, AddressLine1) FROM Address",
		"SELECT NULLIF(City, AddressLine1) FROM Address",
		"SELECT IIF(AddressID > 0, 'Positive', 'Zero') FROM Address",
		// 數值
		"SELECT ABS(AddressID) FROM Address",
		"SELECT CEILING(AddressID) FROM Address",
		"SELECT FLOOR(AddressID) FROM Address",
		"SELECT ROUND(AddressID, 0) FROM Address",
		"SELECT POWER(AddressID, 2) FROM Address",
		// 字串
		"SELECT REPLACE(City, 'a', 'b') FROM Address",
		"SELECT LTRIM(RTRIM(City)) FROM Address",
		"SELECT CHARINDEX('a', City) FROM Address",
		"SELECT LEFT(City, 3), RIGHT(City, 3) FROM Address",
		// 日期
		"SELECT YEAR(ModifiedDate) FROM Address",
		"SELECT MONTH(ModifiedDate) FROM Address",
		"SELECT DAY(ModifiedDate) FROM Address",
		"SELECT DATEADD(DAY, 1, ModifiedDate) FROM Address",
		"SELECT DATEDIFF(DAY, ModifiedDate, GETDATE()) FROM Address",
		"SELECT DATEPART(YEAR, ModifiedDate) FROM Address",
	}
	for _, sql := range oks {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	// 日期部分識別符不被誤判為欄位
	for _, part := range []string{"DAY", "MONTH", "YEAR", "HOUR", "MINUTE", "SECOND"} {
		if _, err := NewRunner(aw).Run("SELECT DATEPART("+part+", ModifiedDate) FROM Address", nil); err != nil {
			t.Errorf("DATEPART(%s): %v", part, err)
		}
	}
	for _, part := range []string{"YEAR", "MONTH", "DAY", "HOUR"} {
		if _, err := NewRunner(aw).Run("SELECT DATEADD("+part+", 1, ModifiedDate) FROM Address", nil); err != nil {
			t.Errorf("DATEADD(%s): %v", part, err)
		}
	}
}

func TestWindow_ParseAndFrames(t *testing.T) {
	for _, sql := range []string{
		"SELECT ROW_NUMBER() OVER (ORDER BY Salary) FROM Employees",
		"SELECT RANK() OVER (ORDER BY Salary DESC) FROM Employees",
		"SELECT DENSE_RANK() OVER (ORDER BY Salary) FROM Employees",
		"SELECT NTILE(4) OVER (ORDER BY Salary) FROM Employees",
	} {
		st := mustParse(t, sql).(*SelectStatement)
		if len(st.Columns) == 0 || st.Columns[0].(*FunctionCallNode).OverClause == nil {
			t.Errorf("%q: over clause nil", sql)
		}
	}

	po := mustParse(t, "SELECT SUM(Salary) OVER (PARTITION BY DeptID) FROM Employees").(*SelectStatement)
	if len(po.Columns[0].(*FunctionCallNode).OverClause.PartitionBy) == 0 {
		t.Error("PARTITION BY 空")
	}
	oo := mustParse(t, "SELECT AVG(Salary) OVER (ORDER BY Salary) FROM Employees").(*SelectStatement)
	if len(oo.Columns[0].(*FunctionCallNode).OverClause.OrderBy) == 0 {
		t.Error("ORDER BY 空")
	}

	for _, sql := range []string{
		"SELECT SUM(Salary) OVER (ORDER BY Salary ROWS UNBOUNDED PRECEDING) FROM Employees",
		"SELECT SUM(Salary) OVER (ORDER BY Salary ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM Employees",
		"SELECT SUM(Salary) OVER (ORDER BY Salary RANGE BETWEEN 100 PRECEDING AND 100 FOLLOWING) FROM Employees",
	} {
		fc := mustParse(t, sql).(*SelectStatement).Columns[0].(*FunctionCallNode)
		if fc.OverClause == nil || fc.OverClause.FrameType == "" {
			t.Errorf("%q: frame_type 空", sql)
		}
	}

	multi := mustParse(t, "SELECT Name, Salary, ROW_NUMBER() OVER (ORDER BY Salary DESC) as rn, RANK() OVER (ORDER BY Salary DESC) as rnk, SUM(Salary) OVER (PARTITION BY DeptID ORDER BY Salary) as dept_total FROM Employees").(*SelectStatement)
	if len(multi.Columns) != 5 {
		t.Fatalf("cols %d", len(multi.Columns))
	}
	for _, i := range []int{2, 3, 4} {
		if multi.Columns[i].(*FunctionCallNode).OverClause == nil {
			t.Errorf("col %d over nil", i)
		}
	}
}

func TestWindow_SyntaxErrors(t *testing.T) {
	for _, sql := range []string{
		"SELECT ROW_NUMBER() OVER FROM Employees",
		"SELECT ROW_NUMBER() (ORDER BY Salary) FROM Employees",
		"SELECT ROW_NUMBER() OVER (ORDER) FROM Employees",
		"SELECT ROW_NUMBER() OVER (PARTITION) FROM Employees",
		"SELECT Name, Salary, ROW_NUMBER() OVER w as rn, SUM(Salary) OVER w as total FROM Employees WINDOW w AS (PARTITION BY DeptID ORDER BY Salary)",
	} {
		if parseErr(t, sql) == nil {
			t.Errorf("%q 應報 syntax error", sql)
		}
	}
}

func TestWindow_BinderAggNoGroupBy(t *testing.T) {
	aw := loadAdventureWorks(t)
	oks := []string{
		"SELECT SalesOrderID, CustomerID, SUM(SubTotal) OVER (PARTITION BY CustomerID) AS CustTotal FROM SalesLT.SalesOrderHeader",
		"SELECT SalesOrderID, CustomerID, ROW_NUMBER() OVER (PARTITION BY CustomerID ORDER BY OrderDate) AS rn, SUM(SubTotal) OVER (PARTITION BY CustomerID) AS CustTotal FROM SalesLT.SalesOrderHeader",
		"SELECT CustomerID, COUNT(*) AS cnt, SUM(SubTotal) OVER (PARTITION BY CustomerID) AS WinTotal FROM SalesLT.SalesOrderHeader GROUP BY CustomerID",
		"SELECT CustomerID FROM SalesLT.SalesOrderHeader WHERE CustomerID > 0",
	}
	for _, sql := range oks {
		if _, err := NewRunner(aw).RunMulti(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	if _, err := NewRunner(aw).RunMulti("SELECT SalesOrderID, COUNT(*) AS cnt FROM SalesLT.SalesOrderHeader", nil); err == nil ||
		!strings.Contains(err.Error(), "GROUP BY") {
		t.Errorf("plain aggregate 仍需 GROUP BY -> %v", err)
	}
}

func TestWindow_BinderValidationAndInference(t *testing.T) {
	reg := mkReg(t, `table_name,column_name,data_type
Employees,EmpID,INT
Employees,Name,VARCHAR
Employees,Salary,DECIMAL
Employees,DeptID,INT
`)
	// 型別推導 → BIGINT
	rn := mustBind(t, reg, "SELECT ROW_NUMBER() OVER (ORDER BY Salary) AS rn FROM Employees").(*SelectStatement)
	if inferredTypeOf(rn.Columns[0]) != "BIGINT" {
		t.Errorf("ROW_NUMBER type: %s", inferredTypeOf(rn.Columns[0]))
	}
	// PARTITION BY / ORDER BY / alias 於 OVER 中的無效欄位
	bad := []string{
		"SELECT SUM(Salary) OVER (PARTITION BY NonExistentCol) FROM Employees",
		"SELECT ROW_NUMBER() OVER (ORDER BY NonExistentCol) FROM Employees",
		"SELECT Salary, Salary * 1.1 AS AdjustedSalary, ROW_NUMBER() OVER (ORDER BY AdjustedSalary) AS rn FROM Employees",
	}
	for _, sql := range bad {
		_, err := NewBinder(reg).Bind(mustParse(t, sql), nil)
		if err == nil || !strings.Contains(err.Error(), "not found in 'Employees'") {
			t.Errorf("%q -> %v", sql, err)
		}
	}
	// WHERE 中的 window function 可被綁定，型別 BIT
	we := mustBind(t, reg, "SELECT * FROM Employees WHERE ROW_NUMBER() OVER (ORDER BY Salary) = 1").(*SelectStatement)
	if eb := exprOf(we.Where); eb == nil || eb.InferredType != "BIT" {
		t.Errorf("where type: %v", we.Where)
	}
	// full pipeline
	res, err := NewRunner(reg).Run("SELECT Name, ROW_NUMBER() OVER (ORDER BY Salary DESC) AS rn FROM Employees", nil)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(res.Tree, "OVER") || !strings.Contains(res.JSON, "ROW_NUMBER") ||
		inferredTypeOf(res.AST.(*SelectStatement).Columns[1]) != "BIGINT" {
		t.Errorf("full pipeline: %s", res.Tree)
	}
}
