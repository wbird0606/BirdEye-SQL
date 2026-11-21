package birdeye

import (
	"strings"
	"testing"
)

// 對照 python-final:tests/test_visualizer_suite.py
// conformance 已 byte 驗 tree 輸出；此處 1:1 鎖定關鍵標籤與 ZTA 安全標記。

func vizParse(t *testing.T, sql string) string {
	t.Helper()
	return NewVisualizer().Dump(mustParse(t, sql))
}

func vizFull(t *testing.T, aw *MetadataRegistry, sql string) string {
	t.Helper()
	res, err := NewRunner(aw).Run(sql, nil)
	if err != nil {
		t.Fatalf("run %q: %v", sql, err)
	}
	return res.Tree
}

func TestVisualizer_OutputIntegrity(t *testing.T) {
	cases := []struct {
		sql  string
		want []string
	}{
		{"SELECT UserID FROM Users",
			[]string{"SELECT_STATEMENT", "COLUMNS", "IDENTIFIER: UserID", "FROM", "IDENTIFIER: Users"}},
		{"SELECT u.UserID AS ID FROM Users AS u",
			[]string{"IDENTIFIER: u.UserID AS ID", "ALIAS: u"}},
		{"SELECT UPPER(UserName) FROM Users",
			[]string{"FUNCTION: UPPER", "IDENTIFIER: UserName"}},
		{"SELECT u.Name FROM Users u JOIN Orders o ON u.ID = o.UID",
			[]string{"INNER_JOIN", "IDENTIFIER: Orders", "ALIAS: o", "└── ON", "u.ID", "o.UID"}},
		{"UPDATE Users SET UserName = 'Bird' WHERE UserID = 1",
			[]string{"UPDATE_STATEMENT", "TABLE: Users", "SET", "EXPRESSION: =", "WHERE (MANDATORY)"}},
		{"DELETE FROM Users WHERE UserID = 1",
			[]string{"DELETE_STATEMENT", "FROM: Users", "WHERE (MANDATORY)"}},
		{"INSERT INTO Users (UserID, UserName) VALUES (1, '家維')",
			[]string{"INSERT_STATEMENT", "INTO: Users", "COLUMNS", "UserID", "UserName", "VALUES", "LITERAL: 1"}},
		{"BULK INSERT INTO Logs",
			[]string{"BULK_COPY_STATEMENT", "TARGET TABLE: Logs"}},
		{"DELETE FROM Users WHERE ID = 1 AND Status = 'Old'",
			[]string{"DELETE_STATEMENT", "EXPRESSION: AND", "EXPRESSION: =", "IDENTIFIER: Status"}},
	}
	for _, c := range cases {
		out := vizParse(t, c.sql)
		for _, w := range c.want {
			if !strings.Contains(out, w) {
				t.Errorf("%q 缺少 %q\n%s", c.sql, w, out)
			}
		}
	}
}

func TestVisualizer_ParseOnlyExtras(t *testing.T) {
	cases := []struct {
		sql  string
		want []string
		not  []string
	}{
		{"DECLARE @counter INT", []string{"DECLARE_STATEMENT", "@counter", "INT"}, nil},
		{"DECLARE @x INT = 0", []string{"DECLARE_STATEMENT", "DEFAULT", "LITERAL: 0"}, nil},
		{"SELECT sub.City FROM (SELECT City FROM T) sub", []string{"SELECT_STATEMENT", "ALIAS: sub"}, nil},
		{"SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY", []string{"OFFSET: 10", "FETCH NEXT: 5"}, nil},
		{"SELECT A FROM T CROSS JOIN T2", []string{"CROSS_JOIN"}, nil},
		{"SELECT A FROM T FULL OUTER JOIN T2 ON T.A = T2.A", []string{"FULL_JOIN"}, nil},
		{"SELECT TOP 10 PERCENT AddressID FROM T", []string{"TOP: 10 PERCENT"}, nil},
		{"SELECT TOP 5 AddressID FROM T", []string{"TOP: 5"}, []string{"PERCENT"}},
		{"INSERT INTO Address (AddressID) SELECT AddressID FROM Address", []string{"INSERT_STATEMENT", "SOURCE"}, nil},
		{"INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')", []string{"VALUES ROW #1", "VALUES ROW #2"}, nil},
		{"SELECT NULL", []string{"LITERAL: NULL"}, nil},
		{"SELECT CASE WHEN 1=1 THEN 1 ELSE NULL END", []string{"LITERAL: NULL"}, nil},
	}
	for _, c := range cases {
		out := vizParse(t, c.sql)
		for _, w := range c.want {
			if !strings.Contains(out, w) {
				t.Errorf("%q 缺少 %q\n%s", c.sql, w, out)
			}
		}
		for _, w := range c.not {
			if strings.Contains(out, w) {
				t.Errorf("%q 不應含 %q\n%s", c.sql, w, out)
			}
		}
	}
}

func TestVisualizer_ModuloBitwise(t *testing.T) {
	for _, sql := range []string{"SELECT AddressID % 2 FROM T", "SELECT AddressID & 1 FROM T"} {
		out := vizParse(t, sql)
		if !strings.Contains(out, "BINARY_EXPR") && !strings.Contains(out, "%") && !strings.Contains(out, "&") {
			t.Errorf("%q -> %s", sql, out)
		}
	}
}

func TestVisualizer_FullPipeline(t *testing.T) {
	aw := loadAdventureWorks(t)
	cases := []struct {
		sql  string
		want []string
	}{
		{"SELECT AddressID FROM Address", []string{"IDENTIFIER: AddressID", "[Type: INT]"}},
		{"SELECT GETDATE()", []string{"FUNCTION: GETDATE", "[Type: DATETIME]"}},
		{"WITH MyCTE AS (SELECT 1 AS A) SELECT A FROM MyCTE", []string{"WITH (CTEs)", "CTE: MYCTE", "SELECT_STATEMENT"}},
		{"SELECT 1 UNION ALL SELECT 2", []string{"SET_OPERATION: UNION ALL", "LEFT", "RIGHT"}},
		{"SELECT CAST(123 AS NVARCHAR)", []string{"CAST TO NVARCHAR", "LITERAL: 123"}},
		{"SELECT * FROM Address WHERE AddressID BETWEEN 1 AND 10", []string{"EXPRESSION: BETWEEN", "TARGET", "LOW", "HIGH"}},
		{"SELECT * FROM Address WHERE AddressID > ANY (1, 2, 3)", []string{"EXPRESSION: > ANY", "LIST", "ITEM#1", "LITERAL: 1"}},
		{"SELECT AddressID INTO #Temp FROM Address", []string{"INTO: #Temp"}},
		{"SELECT a.AddressID, sub.City FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub",
			[]string{"CROSS_APPLY", "ALIAS: sub"}},
		{"SELECT a.AddressID, sub.City FROM Address a OUTER APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub",
			[]string{"OUTER_APPLY"}},
		{"SELECT DISTINCT City FROM Address", []string{"DISTINCT"}},
		// Python 斷言為 "INTERSECT" in output or "UNION_STATEMENT" in output —— Go 引擎輸出 SET_OPERATION: INTERSECT
		{"SELECT AddressID FROM Address INTERSECT SELECT AddressID FROM Address", []string{"SET_OPERATION: INTERSECT"}},
		{"SELECT AddressID FROM Address EXCEPT SELECT AddressID FROM Address", []string{"SET_OPERATION: EXCEPT"}},
		{"SELECT (SELECT MAX(AddressID) FROM Address) AS MaxID", []string{"SELECT_STATEMENT"}},
		{"SELECT Sub.AddressID FROM (SELECT AddressID FROM Address UNION SELECT AddressID FROM Address) AS Sub",
			[]string{"SELECT_STATEMENT"}},
		{"SELECT CONCAT(City, ', ') FROM Address", []string{"SELECT_STATEMENT"}},
	}
	for _, c := range cases {
		out := vizFull(t, aw, c.sql)
		for _, w := range c.want {
			if !strings.Contains(out, w) {
				t.Errorf("%q 缺少 %q\n%s", c.sql, w, out)
			}
		}
	}
}
