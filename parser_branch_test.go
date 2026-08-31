package birdeye

import "testing"

// 對照 birdeye_1150831/tests/test_branch_phase2_parser_suite.py
// —— parser 的罕見分支。monkeypatch 型測試改以等價的可觀察行為 / 直接呼叫驗證。

func TestParserBranch_PeekOutOfRange(t *testing.T) {
	toks, _ := NewLexer("SELECT 1").Tokenize()
	if NewParser(toks, "SELECT 1").peek(9999) != nil {
		t.Error("peek(9999) 應為 nil")
	}
}

func TestParserBranch_BareWith(t *testing.T) {
	// 對照 test_parser_parse_unexpected_end_after_with（monkeypatch）：WITH 後無語句
	if parseErr(t, "WITH") == nil {
		t.Error("bare WITH 應報錯")
	}
}

func TestParserBranch_ScriptDMLPaths(t *testing.T) {
	sn, err := NewParser(mustTokens(t, "INSERT INTO Address VALUES (1); TRUNCATE TABLE Address; DECLARE @x INT"),
		"INSERT INTO Address VALUES (1); TRUNCATE TABLE Address; DECLARE @x INT").ParseScript()
	if err != nil {
		t.Fatal(err)
	}
	if s := sn.(*ScriptNode); len(s.Statements) != 3 {
		t.Errorf("statements %d want 3", len(s.Statements))
	}
}

func mustTokens(t *testing.T, sql string) []Token {
	t.Helper()
	toks, err := NewLexer(sql).Tokenize()
	if err != nil {
		t.Fatalf("lex: %v", err)
	}
	return toks
}

func TestParserBranch_JoinEdges(t *testing.T) {
	if parseErr(t, "SELECT * FROM Address a JOIN (SELECT 1 AS x) ON 1 = 1") == nil {
		t.Error("JOIN 子查詢無 alias 應報錯")
	}
	// JOIN ON 非二元條件
	ast := mustParse(t, "SELECT * FROM Address a JOIN Address b ON 1").(*SelectStatement)
	if len(ast.Joins) != 1 || ast.Joins[0].OnLeft != nil || ast.Joins[0].OnRight != nil {
		t.Errorf("ON 1: joins=%d onLeft=%v onRight=%v", len(ast.Joins), ast.Joins[0].OnLeft, ast.Joins[0].OnRight)
	}
}

func TestParserBranch_ContainsIdentifierCaseFalse(t *testing.T) {
	p := NewParser(nil, "")
	c := NewCaseExpr(NewLiteral("1", NumericLiteral))
	c.Branches = append(c.Branches, CaseBranch{
		When: NewLiteral("2", NumericLiteral),
		Then: NewLiteral("3", NumericLiteral),
	})
	if p.containsIdentifier(c) {
		t.Error("純 literal 的 CASE 不含 identifier")
	}
}

func TestParserBranch_MiscParses(t *testing.T) {
	// 皆應可解析（不 panic / error）
	ok := []string{
		"SELECT F()",
		"SELECT SUM(1) OVER (PARTITION BY AddressID) FROM Address",
		"SELECT SUM(1) OVER (ORDER BY AddressID) FROM Address",
		"SELECT SUM(1) OVER (ORDER BY AddressID ROWS UNBOUNDED FOLLOWING) FROM Address",
		"CREATE TABLE T ()",
		"CREATE TABLE T (c INT NOT KEY)",
		"CREATE TABLE T (id INT IDENTITY)",
		"CREATE TABLE T (id INT PRIMARY)",
	}
	for _, sql := range ok {
		if mustParse(t, sql) == nil {
			t.Errorf("%q 應可解析", sql)
		}
	}
	// A1：IF BEGIN 內非語句 → Go 報錯（KNOWN_DEVIATIONS A1，Python 為無限迴圈）
	if parseErr(t, "IF 1=1 BEGIN 123 END") == nil {
		t.Error("IF BEGIN 內非語句應報錯（A1）")
	}
	if parseErr(t, "SELECT CASE 1 END") == nil {
		t.Error("CASE 無 WHEN 應報錯")
	}
}

func TestParserBranch_DropAlterMerge(t *testing.T) {
	if !mustParse(t, "DROP TABLE IF EXISTS T").(*DropTableStatement).IfExists {
		t.Error("DROP TABLE IF EXISTS -> if_exists true")
	}
	if mustParse(t, "ALTER TABLE T DROP COLUMN c").(*AlterTableStatement).Action != "DROP" {
		t.Error("ALTER TABLE DROP COLUMN -> action DROP")
	}
	m1 := mustParse(t, "MERGE INTO T USING S ON 1=1 WHEN MATCHED THEN UPDATE SET a=1, b=2").(*MergeStatement)
	if m1.Clauses[0].Action != "UPDATE" || len(m1.Clauses[0].SetClauses) != 2 {
		t.Errorf("MERGE UPDATE multi set: %+v", m1.Clauses[0])
	}
	m2 := mustParse(t, "MERGE INTO T USING S ON 1=1 WHEN NOT MATCHED THEN INSERT VALUES (1)").(*MergeStatement)
	if m2.Clauses[0].Action != "INSERT" || len(m2.Clauses[0].InsertColumns) != 0 {
		t.Errorf("MERGE INSERT no columns: %+v", m2.Clauses[0])
	}
}
