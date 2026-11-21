package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 python-final:tests/test_subquery_suite.py（any_all / union / derived_table）

func TestSubquery_AnyAllParsing(t *testing.T) {
	cases := []struct{ sql, op string }{
		{"SELECT * FROM Address WHERE AddressID > ANY (SELECT 1)", "> ANY"},
		{"SELECT * FROM Address WHERE AddressID = ANY (SELECT 1)", "= ANY"},
		{"SELECT * FROM Address WHERE AddressID <> ANY (SELECT 1)", "<> ANY"},
	}
	for _, c := range cases {
		w := mustParse(t, c.sql).(*SelectStatement).Where.(*BinaryExpressionNode)
		if w.Operator != c.op {
			t.Errorf("%q -> %q", c.sql, w.Operator)
		}
	}
	for _, c := range []struct{ sql, op string }{
		{"SELECT * FROM Address WHERE AddressID > ANY (100, 200, 300)", "> ANY"},
		{"SELECT * FROM Address WHERE AddressID = ALL (200, 200, 200)", "= ALL"},
	} {
		w := mustParse(t, c.sql).(*SelectStatement).Where.(*BinaryExpressionNode)
		if w.Operator != c.op {
			t.Errorf("%q -> %q", c.sql, w.Operator)
		}
		if _, ok := w.Right.(nodeList); !ok {
			t.Errorf("%q right 非 list：%T", c.sql, w.Right)
		}
	}
}

func TestSubquery_AnyAllPipeline(t *testing.T) {
	aw := loadAdventureWorks(t)
	w := intgRun(t, aw, "SELECT * FROM Address WHERE AddressID > ANY (1, 2, 3)").AST.(*SelectStatement).Where.(*BinaryExpressionNode)
	if w.Operator != "> ANY" {
		t.Errorf("op %q", w.Operator)
	}
	for _, sql := range []string{
		"SELECT CustomerID FROM Customer WHERE CustomerID >= ALL (SELECT AddressID FROM Address WHERE City = 'Bothell') AND CustomerID > ANY (10, 20, 30)",
		"SELECT * FROM Address WHERE AddressID = ANY (1, 2, 3)",
		"SELECT * FROM Address WHERE AddressID IN (1, 2, 3)",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	intgErr(t, aw, "SELECT * FROM Address WHERE AddressID > ANY (SELECT City FROM Address)", "Incompatible types in > ANY")
}

func TestSubquery_Union(t *testing.T) {
	aw := loadAdventureWorks(t)

	u := intgRun(t, aw, "SELECT AddressID FROM Address UNION SELECT 1").AST.(*UnionStatement)
	if u.Operator != "UNION" {
		t.Errorf("op %q", u.Operator)
	}
	if _, ok := u.Left.(*SelectStatement); !ok {
		t.Errorf("left %T", u.Left)
	}
	if _, ok := u.Right.(*SelectStatement); !ok {
		t.Errorf("right %T", u.Right)
	}

	ua := intgRun(t, aw, "SELECT City FROM Address UNION ALL SELECT 'Taipei'").AST.(*UnionStatement)
	if ua.Operator != "UNION ALL" {
		t.Errorf("union all op %q", ua.Operator)
	}

	intgErr(t, aw, "SELECT AddressID, City FROM Address UNION SELECT 1", "must have an equal number of expressions")
	intgErr(t, aw, "SELECT AddressID FROM Address UNION SELECT 'SomeString'", "Incompatible types in UNION")

	triple := intgRun(t, aw, "SELECT 1 UNION SELECT 2 UNION SELECT 3").AST.(*UnionStatement)
	if _, ok := triple.Left.(*UnionStatement); !ok {
		t.Errorf("triple union left %T", triple.Left)
	}
}

func TestSubquery_AggAndDerived(t *testing.T) {
	aw := loadAdventureWorks(t)
	oks := []string{
		"SELECT MAX(AddressID) FROM Address",
		"SELECT MIN(AddressID) FROM Address",
		"SELECT City FROM Address GROUP BY City HAVING MAX(AddressID) > 1",
		"SELECT AddressID FROM Address WHERE AddressID = (SELECT MIN(AddressID) FROM Address)",
		"SELECT sub.City FROM (SELECT City FROM Address) sub",
		"SELECT sub.AddressID FROM (SELECT AddressID, City FROM Address) sub",
		"SELECT sub.City FROM (SELECT City, AddressID FROM Address) sub WHERE sub.AddressID > 0",
		"SELECT a.City FROM Address a JOIN (SELECT AddressID FROM Address) sub ON a.AddressID = sub.AddressID",
		"SELECT a.City, sub.AddressID FROM Address a LEFT JOIN (SELECT AddressID FROM Address WHERE AddressID > 0) sub ON a.AddressID = sub.AddressID",
	}
	for _, sql := range oks {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	if colType(intgRun(t, aw, "SELECT MAX(AddressID) FROM Address").AST.(*SelectStatement).Columns[0]) != "INT" {
		t.Error("MAX return type")
	}

	st := mustParse(t, "SELECT sub.City FROM (SELECT City FROM T) sub").(*SelectStatement)
	if st.Table == nil || st.TableAlias != "sub" {
		t.Errorf("derived table: %v %q", st.Table, st.TableAlias)
	}
	if parseErr(t, "SELECT City FROM (SELECT City FROM Address)") == nil {
		t.Error("derived table 無 alias 應報錯")
	}

	data := map[string]any{}
	json.Unmarshal([]byte(NewSerializer().ToJSON(st)), &data)
	if data["table"].(map[string]any)["node_type"] != "SelectStatement" || data["alias"] != "sub" {
		t.Errorf("derived serialize: %v", data)
	}
	if out := NewVisualizer().Dump(st); !strings.Contains(out, "SUBQUERY") && !strings.Contains(out, "SELECT_STATEMENT") {
		t.Errorf("derived viz: %s", out)
	}
}

func TestSubquery_NString(t *testing.T) {
	aw := loadAdventureWorks(t)
	toks := mustTokens(t, "SELECT N'Taipei'")
	var strs []Token
	for _, tk := range toks {
		if tk.Type == StringLiteral {
			strs = append(strs, tk)
		}
	}
	if len(strs) != 1 || strings.Trim(strs[0].Value, "'") != "Taipei" {
		t.Errorf("N'Taipei' tokens: %+v", strs)
	}
	for _, sql := range []string{
		"SELECT AddressID FROM Address WHERE City = N'Taipei'",
		"SELECT N'hello'",
		"INSERT INTO Address (AddressID, City) VALUES (999, N'台北')",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
}
