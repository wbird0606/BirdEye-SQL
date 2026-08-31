package birdeye

import (
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_clause_coverage_gaps.py（web/app 端點測試屬 Phase 2，略）。

func TestClauseCov_LexerNString(t *testing.T) {
	cases := []string{"SELECT N'Hello World'", "SELECT n'Test String'", "SELECT N'中文字符'", "SELECT N''", "SELECT N'It''s a test'"}
	for _, sql := range cases {
		toks, err := NewLexer(sql).Tokenize()
		if err != nil {
			t.Fatalf("%q: %v", sql, err)
		}
		if toks[1].Type != StringLiteral {
			t.Errorf("%q toks[1] = %v", sql, toks[1].Type)
		}
	}
	whole, _ := NewLexer("N'abc'").Tokenize()
	if whole[0].Type != StringLiteral || whole[0].Value != "'abc'" {
		t.Errorf("N'abc' -> %v %q", whole[0].Type, whole[0].Value)
	}
}

func TestClauseCov_ParserMatchConsume(t *testing.T) {
	for _, sql := range []string{
		"SELECT * FROM", "SELECT WHERE ProductID = 1", "SELECT * FROM ;",
		"SELECT * FROM A JOIN B ON A.id = B.id WHERE", "DELETE * WHERE OrderID = 1",
	} {
		if parseErr(t, sql) == nil {
			t.Errorf("%q 應報 syntax error", sql)
		}
	}

	// match：型別不符 / EOF → false，pos 不變
	p := NewParser([]Token{{Type: KwSelect, Value: "SELECT"}, {Type: EOF}}, "SELECT")
	if _, ok := p.match(KwFrom); ok || p.pos != 0 {
		t.Errorf("match wrong type: ok=%v pos=%d", ok, p.pos)
	}
	p2 := NewParser([]Token{{Type: KwSelect, Value: "SELECT"}}, "SELECT")
	p2.pos = 1
	if _, ok := p2.match(KwSelect); ok {
		t.Error("match EOF 應為 false")
	}

	// consume 不符 → panic engineBail
	p3 := NewParser([]Token{{Type: KwSelect, Value: "SELECT"}, {Type: EOF}}, "SELECT")
	err := recoverBail(func() { p3.consume(KwFrom, "expected FROM") })
	if err == nil || !strings.Contains(err.Msg, "expected FROM") {
		t.Errorf("consume mismatch -> %v", err)
	}
}

func TestClauseCov_MatchAliasCACC(t *testing.T) {
	cases := []struct {
		toks []Token
		want TokenType // -1 表示應為 false
	}{
		{[]Token{{Type: Identifier, Value: "alias"}}, Identifier},
		{[]Token{{Type: KwOver, Value: "OVER"}}, KwOver},
		{[]Token{{Type: KwSelect, Value: "SELECT"}}, TokenType(-1)},
		{nil, TokenType(-1)},
	}
	for i, c := range cases {
		p := NewParser(c.toks, "alias")
		tok, ok := p.matchAlias()
		if c.want == TokenType(-1) {
			if ok {
				t.Errorf("[%d] 應為 false，得 %v", i, tok.Type)
			}
		} else if !ok || tok.Type != c.want {
			t.Errorf("[%d] 得 ok=%v type=%v，want %v", i, ok, tok.Type, c.want)
		}
	}
}

func TestClauseCov_Registry(t *testing.T) {
	reg := mkReg(t, "table_name,column_name,data_type\nOrders,OrderID,INT\nOrders,Price,DECIMAL\n")
	if f := reg.GetFunction("TRY_CAST"); f == nil || f.Name != "TRY_CAST" || f.FuncType != "SCALAR" {
		t.Errorf("TRY_CAST: %+v", f)
	}
	if reg.GetFunction("ISNULL") == nil {
		t.Error("ISNULL missing")
	}
	if f := reg.GetFunction("SUM"); f == nil || f.FuncType != "AGGREGATE" {
		t.Errorf("SUM: %+v", f)
	}
	if !reg.IsAggregate("SUM") || reg.IsAggregate("LEN") || reg.IsAggregate("NONEXISTENT_FUNC_12345") {
		t.Error("IsAggregate CACC")
	}
	if reg.GetFunction("NONEXISTENT_FUNC_12345") != nil {
		t.Error("unknown function 應為 nil")
	}
}

func TestClauseCov_RunnerBoundaries(t *testing.T) {
	reg := mkReg(t, `table_name,column_name,data_type
Address,AddressID,INT
Address,AddressLine1,VARCHAR
Address,City,VARCHAR
City,CityID,INT
City,Name,VARCHAR
`)
	run := func(sql string) {
		if _, err := NewRunner(reg).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	if _, err := NewRunner(reg).Run("SELECT FROM Address", nil); err == nil {
		t.Error("SELECT FROM 應報錯")
	}
	run("SELECT * FROM Address WHERE AddressID = 1 AND City = 'NYC' OR AddressLine1 LIKE '%St%'")
	run("SELECT CASE WHEN AddressID < 10 THEN 'Low' WHEN AddressID < 100 THEN 'Medium' ELSE 'High' END FROM Address")
	run("SELECT * FROM Address WHERE AddressLine1 IS NULL")
	run("SELECT * FROM Address WHERE AddressLine1 IS NOT NULL")
	run("SELECT CAST(AddressID AS VARCHAR) FROM Address")
	run("SELECT CAST('123' AS INT) FROM Address")
	run("SELECT CAST(GETDATE() AS DATE) FROM Address")
}

func TestClauseCov_CACCExtended(t *testing.T) {
	reg := mkReg(t, `table_name,column_name,data_type
Orders,OrderID,INT
Orders,CustomerID,INT
Orders,OrderDate,DATETIME
Orders,Amount,DECIMAL
Customers,CustomerID,INT
Customers,Name,VARCHAR
`)
	run := func(sql string) {
		if _, err := NewRunner(reg).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	run("SELECT OrderID FROM Orders UNION SELECT CustomerID FROM Customers")
	run("SELECT OrderID FROM Orders UNION ALL SELECT CustomerID FROM Customers")
	run("SELECT OrderID FROM Orders EXCEPT SELECT CustomerID FROM Customers")
	run("SELECT OrderID FROM Orders INTERSECT SELECT CustomerID FROM Customers")
	run("SELECT LEN(Name) FROM Customers")
	run("SELECT COUNT(*) FROM Orders")
	run("SELECT SUBSTRING(Name, 1, 3) FROM Customers")
	run("SELECT NULL")
	run("SELECT * FROM Orders WHERE OrderDate = NULL")
	run("SELECT CAST(NULL AS INT)")
	run("SELECT o.OrderID FROM Orders o WHERE o.CustomerID = 1")
	run("SELECT o.OrderID, c.Name FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID")
	run("SELECT * FROM Orders o1 JOIN Orders o2 ON o1.OrderID = o2.OrderID")
	run("SELECT GETDATE()")
	run("SELECT ABS(-10)")
	run("SELECT COALESCE(OrderDate, GETDATE()) FROM Orders")
	run("SELECT * FROM Orders WHERE OrderID BETWEEN 1 AND 100")

	if parseErr(t, "DELETE * WHERE OrderID = 1") == nil {
		t.Error("DELETE * 應報錯")
	}

	lexOK := func(s string, want TokenType) {
		toks, err := NewLexer(s).Tokenize()
		if err != nil || toks[0].Type != want {
			t.Errorf("%q -> %v %v", s, toks[0].Type, err)
		}
	}
	lexOK("123", NumericLiteral)
	lexOK("'hello'", StringLiteral)
	lexOK("'it''s'", StringLiteral)
}

func TestClauseCov_TopMissingParen(t *testing.T) {
	toks := []Token{
		{Type: KwSelect, Value: "SELECT"}, {Type: KwTop, Value: "TOP"},
		{Type: SymLParen, Value: "("}, {Type: NumericLiteral, Value: "5"},
		{Type: Identifier, Value: "OrderID"}, {Type: KwFrom, Value: "FROM"},
		{Type: Identifier, Value: "Orders"}, {Type: EOF},
	}
	_, err := NewParser(toks, "SELECT TOP (5 OrderID FROM Orders").Parse()
	if e, ok := err.(*Error); !ok || !strings.Contains(e.Msg, "Expected ')'") {
		t.Errorf("TOP (5 缺 ) -> %v", err)
	}
}
