package birdeye

import (
	"strings"
	"testing"
)

// 對照 python-final:tests/test_parser_suite.py

func mustParse(t *testing.T, sql string) Node {
	t.Helper()
	toks, err := NewLexer(sql).Tokenize()
	if err != nil {
		t.Fatalf("lex %q: %v", sql, err)
	}
	n, err := NewParser(toks, sql).Parse()
	if err != nil {
		t.Fatalf("parse %q: %v", sql, err)
	}
	return n
}

func parseErr(t *testing.T, sql string) error {
	t.Helper()
	toks, err := NewLexer(sql).Tokenize()
	if err != nil {
		return err
	}
	_, err = NewParser(toks, sql).Parse()
	return err
}

// --- 1. 語句路由 ---

func TestParserStatementRouting(t *testing.T) {
	cases := []struct{ sql, want string }{
		{"SELECT * FROM Users", "SelectStatement"},
		{"UPDATE Users SET Name = 'A' WHERE ID = 1", "UpdateStatement"},
		{"DELETE FROM Users WHERE ID = 1", "DeleteStatement"},
		{"INSERT INTO Users (ID) VALUES (1)", "InsertStatement"},
		{"BULK INSERT INTO Logs", "SqlBulkCopyStatement"},
	}
	for _, c := range cases {
		if got := nodeTypeName(mustParse(t, c.sql)); got != c.want {
			t.Errorf("%q: got %s want %s", c.sql, got, c.want)
		}
	}
}

// --- 2. 基礎 SELECT 結構 ---

func TestParserSelectStructures(t *testing.T) {
	cases := []struct {
		sql      string
		isStar   bool
		colCount int
		table    string
	}{
		{"SELECT UserID, UserName FROM Orders", false, 2, "ORDERS"},
		{"SELECT*FROM[Users]", true, 0, "USERS"},
		{" \n\n\t  SELECT \r\n * \t\t FROM \n Users \n\n  ", true, 0, "USERS"},
	}
	for _, c := range cases {
		st, ok := mustParse(t, c.sql).(*SelectStatement)
		if !ok {
			t.Errorf("%q: 非 SelectStatement", c.sql)
			continue
		}
		if st.IsSelectStar != c.isStar {
			t.Errorf("%q: IsSelectStar got %v want %v", c.sql, st.IsSelectStar, c.isStar)
		}
		if len(st.Columns) != c.colCount {
			t.Errorf("%q: col count got %d want %d", c.sql, len(st.Columns), c.colCount)
		}
		tbl, _ := st.Table.(*IdentifierNode)
		if tbl == nil || strings.ToUpper(tbl.Name) != c.table {
			t.Errorf("%q: table got %v want %s", c.sql, st.Table, c.table)
		}
	}
}

// --- 3. ZTA 嚴格語法攔截 ---

func TestParserZTAStrictErrors(t *testing.T) {
	cases := []struct{ sql, want string }{
		{"UPDATE Users SET Name = 'X'", "WHERE clause is mandatory"},
		{"DELETE FROM Users", "WHERE clause is mandatory"},
		{"SELECT * FROM Users, Orders", "Expected FROM"},
		{"SELECT UserID, , UserName FROM Users", "Expected identifier"},
		{"SELECT UserID Users", "Expected FROM"},
		{"SELECT * FROM Users ; DROP TABLE Users--", "Unexpected token: DROP"},
		{"SELECT A, B, FROM Users", "Unexpected expression token: FROM"},
		{"SELECT * FROM Users ORDER BY A, B,", "Unexpected expression token:"},
		{"SELECT * FROM Users GROUP BY A, B,", "Unexpected expression token:"},
	}
	for _, c := range cases {
		err := parseErr(t, c.sql)
		if err == nil {
			t.Errorf("%q: 預期 syntax error，卻成功", c.sql)
			continue
		}
		if be, ok := err.(*Error); !ok || be.Kind != ErrSyntax {
			t.Errorf("%q: 錯誤分類非 syntax: %v", c.sql, err)
		}
		if !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q: 訊息 %q 不含 %q", c.sql, err.Error(), c.want)
		}
	}
}

// --- 4. 識別符與別名 ---

func TestParserMSSQLIdentifiers(t *testing.T) {
	cases := []struct{ sql, want string }{
		{"SELECT [First Name] FROM Users", "First Name"},
		{"SELECT [SELECT] FROM Users", "SELECT"},
	}
	for _, c := range cases {
		st := mustParse(t, c.sql).(*SelectStatement)
		id, _ := st.Columns[0].(*IdentifierNode)
		if id == nil || id.Name != c.want {
			t.Errorf("%q: col[0] got %v want %s", c.sql, st.Columns[0], c.want)
		}
	}
}

func TestParserAliasMixedCasing(t *testing.T) {
	for _, kw := range []string{"as", "As", "aS", "AS"} {
		sql := "SELECT UserID FROM Users " + kw + " u"
		st := mustParse(t, sql).(*SelectStatement)
		if st.TableAlias != "u" {
			t.Errorf("%q: TableAlias got %q want u", sql, st.TableAlias)
		}
	}
}
