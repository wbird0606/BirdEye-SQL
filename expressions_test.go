package birdeye

import (
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_expressions_suite.py（31）
// 完整 pipeline 輸出已由 conformance byte 驗；此處鎖定 AST 結構與型別推導。

func exprRoot(t *testing.T, sql string) Node {
	t.Helper()
	n := mustParse(t, sql)
	switch s := n.(type) {
	case *SelectStatement:
		return s.Columns[0]
	case *UpdateStatement:
		return s.SetClauses[0].Right
	case *InsertStatement:
		return s.Values[0]
	case *DeleteStatement:
		return s.Where
	}
	return nil
}

func opOf(n Node) string {
	if b, ok := n.(*BinaryExpressionNode); ok {
		return b.Operator
	}
	return ""
}

func TestExpressionPrecedence(t *testing.T) {
	cases := []struct{ sql, top, child string }{
		{"SELECT UserID + 100 FROM Users", "+", ""},
		{"SELECT (1 + 2) * 3 FROM Users", "*", "+"},
		{"SELECT 1 + 2 * 3 FROM Users", "+", "*"},
		{"SELECT (ListPrice - Cost) / Cost FROM Product", "/", "-"},
	}
	for _, c := range cases {
		n := exprRoot(t, c.sql).(*BinaryExpressionNode)
		if n.Operator != c.top {
			t.Errorf("%q: top op %q want %q", c.sql, n.Operator, c.top)
		}
		if c.child != "" && opOf(n.Left) != c.child && opOf(n.Right) != c.child {
			t.Errorf("%q: 子運算子 %q 不在 AST", c.sql, c.child)
		}
	}
}

func TestComparisonExpression(t *testing.T) {
	cases := map[string]string{
		"SELECT * FROM Users WHERE Salary > 5000":        ">",
		"SELECT * FROM Users WHERE Age < 18":             "<",
		"SELECT * FROM Users WHERE ID >= 10":             ">=",
		"SELECT * FROM Users WHERE Status != 'Active'":   "!=",
		"SELECT * FROM Users WHERE Status <> 'Old'":      "<>",
		"SELECT * FROM Users WHERE Status IS NULL":       "IS NULL",
		"SELECT * FROM Users WHERE Status IS NOT NULL":   "IS NOT NULL",
		"SELECT * FROM Users WHERE Name LIKE '%Bird%'":   "LIKE",
		"SELECT * FROM Users WHERE Name NOT LIKE 'Cat%'": "NOT LIKE",
	}
	for sql, want := range cases {
		w := mustParse(t, sql).(*SelectStatement).Where
		if b, ok := w.(*BinaryExpressionNode); !ok || b.Operator != want {
			t.Errorf("%q: where op got %v want %q", sql, w, want)
		}
	}
}

func TestDMLExpressionIntegration(t *testing.T) {
	if b, ok := exprRoot(t, "UPDATE Users SET Salary = Salary * 1.1 WHERE ID = 1").(*BinaryExpressionNode); !ok ||
		b.Operator != "*" || b.Left.(*IdentifierNode).Name != "Salary" {
		t.Error("update arith")
	}
	if opOf(exprRoot(t, "DELETE FROM Users WHERE Age = 20 OR Status = 'Old'")) != "OR" {
		t.Error("delete OR")
	}
	if f, ok := exprRoot(t, "INSERT INTO Logs VALUES (UPPER('System'))").(*FunctionCallNode); !ok || f.Name != "UPPER" {
		t.Error("insert func")
	}
}

func TestComplexZTACondition(t *testing.T) {
	n := exprRoot(t, "DELETE FROM Users WHERE ID = 1 AND (Status = 'A' OR Status = 'B')").(*BinaryExpressionNode)
	if n.Operator != "AND" || n.Right.(*BinaryExpressionNode).Operator != "OR" {
		t.Fatal(n)
	}
	if n.Right.(*BinaryExpressionNode).Left.(*BinaryExpressionNode).Left.(*IdentifierNode).Name != "Status" {
		t.Fatal("nested name")
	}
}

func TestFunctionAndStar(t *testing.T) {
	c := exprRoot(t, "SELECT CONCAT(FirstName, ' ', LastName) FROM Users").(*FunctionCallNode)
	if c.Name != "CONCAT" || len(c.Args) != 3 {
		t.Error("concat args")
	}
	cs := exprRoot(t, "SELECT COUNT(*) FROM Users").(*FunctionCallNode)
	if cs.Name != "COUNT" || cs.Args[0].(*IdentifierNode).Name != "*" {
		t.Error("count star")
	}
}

func TestBetweenCaseCast(t *testing.T) {
	aw := loadAdventureWorks(t)
	rb := func(sql string) (Node, error) {
		res, err := NewRunner(aw).Run(sql, nil)
		if err != nil {
			return nil, err
		}
		return res.AST, nil
	}

	// BETWEEN
	n, _ := rb("SELECT ProductID FROM Product WHERE ListPrice BETWEEN 100 AND 500")
	bn := n.(*SelectStatement).Where.(*BetweenExpressionNode)
	if bn.IsNot || bn.Low.(*LiteralNode).Value != "100" || bn.High.(*LiteralNode).Value != "500" {
		t.Error("between")
	}
	n2, _ := rb("SELECT ProductID FROM Product WHERE ListPrice NOT BETWEEN 10 AND 20")
	if !n2.(*SelectStatement).Where.(*BetweenExpressionNode).IsNot {
		t.Error("not between")
	}
	n3, _ := rb("SELECT * FROM SalesOrderHeader WHERE OrderDate BETWEEN '2023-01-01' AND GETDATE()")
	if exprOf(n3.(*SelectStatement).Where).InferredType != "BIT" {
		t.Error("between date/string compat")
	}
	if _, err := rb("SELECT * FROM Product WHERE ListPrice BETWEEN 100 AND 'High'"); err == nil ||
		!strings.Contains(err.Error(), "Incompatible types in BETWEEN") {
		t.Errorf("between incompat: %v", err)
	}
	if _, err := rb("SELECT * FROM Product WHERE ListPrice BETWEEN 100 OR 500"); err == nil ||
		!strings.Contains(err.Error(), "Expected AND") {
		t.Errorf("between missing AND: %v", err)
	}

	// CASE
	nc, _ := rb("SELECT CASE WHEN AddressID > 100 THEN 'High' ELSE 'Low' END FROM Address")
	if exprOf(nc.(*SelectStatement).Columns[0]).InferredType != "NVARCHAR" {
		t.Error("case type")
	}
	if _, err := rb("SELECT CASE WHEN GhostCol = 1 THEN 1 ELSE 0 END FROM Address"); err == nil ||
		!strings.Contains(err.Error(), "Column 'GhostCol' not found") {
		t.Errorf("case ghost col: %v", err)
	}
	if _, err := rb("SELECT CASE WHEN AddressID > 0 THEN 1 ELSE 'Zero' END FROM Address"); err == nil ||
		!strings.Contains(err.Error(), "CASE branches have incompatible types") {
		t.Errorf("case incompat: %v", err)
	}

	// CAST / CONVERT
	nca, _ := rb("SELECT CAST(ListPrice AS NVARCHAR) FROM Product")
	ce := nca.(*SelectStatement).Columns[0].(*CastExpressionNode)
	if ce.TargetType != "NVARCHAR" || ce.InferredType != "NVARCHAR" {
		t.Error("cast")
	}
	ncv, _ := rb("SELECT CONVERT(INT, ListPrice) FROM Product")
	cv := ncv.(*SelectStatement).Columns[0].(*CastExpressionNode)
	if !cv.IsConvert || cv.TargetType != "INT" || cv.InferredType != "INT" {
		t.Error("convert")
	}
	nx, _ := rb("SELECT 'Price: ' + CAST(ListPrice AS NVARCHAR) FROM Product")
	if exprOf(nx.(*SelectStatement).Columns[0]).InferredType != "NVARCHAR" {
		t.Error("cast in expr")
	}
}
