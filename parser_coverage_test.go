package birdeye

import "testing"

// 對照 python-final:tests/test_parser_coverage_suite.py
// —— 新 MSSQL 語法特性的 parser 分支（SyntaxError 路徑、IF BEGIN...END 內各語句
//    的 _parse_single_stmt 分派、EXEC return var/named args、CREATE TABLE 欄位修飾、
//    MERGE 子查詢 source / NOT MATCHED BY SOURCE / AND condition）。

func pcParseErrKind(t *testing.T, sql string) {
	t.Helper()
	err := parseErr(t, sql)
	if e, ok := err.(*Error); !ok || e.Kind != ErrSyntax {
		t.Errorf("%q -> %v（want syntax error）", sql, err)
	}
}

func TestParserCoverage_BeginEndAndErrors(t *testing.T) {
	if mustParse(t, "BEGIN SELECT 1 END") == nil {
		t.Error("BEGIN...END 應回傳語句")
	}
	pcParseErrKind(t, "FOOBAR 1 2 3")
	pcParseErrKind(t, "SELECT 1 FROM T CROSS FOOBAR X")
	if parseErr(t, "SELECT 1 FROM T OUTER FOOBAR X") == nil {
		t.Error("OUTER 無 APPLY 應報錯")
	}
	pcParseErrKind(t, "ALTER TABLE Customer MODIFY Name NVARCHAR(100)")
	pcParseErrKind(t, "MERGE INTO Target AS t USING Source AS s ON t.ID = s.ID WHEN MATCHED THEN FOOBAR;")
}

func TestParserCoverage_IfBlockDispatch(t *testing.T) {
	cases := []struct {
		sql string
		typ string
	}{
		{"IF 1=1 BEGIN INSERT INTO Customer (CustomerID) VALUES (1) END", "InsertStatement"},
		{"IF 1=1 BEGIN UPDATE Customer SET CustomerID = 1 WHERE CustomerID = 2 END", "UpdateStatement"},
		{"IF 1=1 BEGIN DELETE FROM Customer WHERE CustomerID = 1 END", "DeleteStatement"},
		{"IF 1=1 BEGIN TRUNCATE TABLE Customer END", "TruncateStatement"},
		{"IF 1=1 BEGIN DECLARE @x INT END", "DeclareStatement"},
		{"IF 1=1 BEGIN IF 2=2 BEGIN SELECT 1 END END", "IfStatement"},
		{"IF 1=1 BEGIN EXEC sp_help; END", "ExecStatement"},
		{"IF 1=1 BEGIN CREATE TABLE #T (ID INT) END", "CreateTableStatement"},
		{"IF 1=1 BEGIN DROP TABLE #T END", "DropTableStatement"},
		{"IF 1=1 BEGIN MERGE INTO Target AS t USING Source AS s ON t.ID = s.ID WHEN MATCHED THEN UPDATE SET t.Name = s.Name; END", "MergeStatement"},
		{"IF 1=1 BEGIN PRINT 'hello' END", "PrintStatement"},
		{"IF 1=1 BEGIN SET @x = 1 END", "SetStatement"},
	}
	for _, c := range cases {
		n := mustParse(t, c.sql)
		ifs, ok := n.(*IfStatement)
		if !ok {
			t.Errorf("%q -> %s（want IfStatement）", c.sql, nodeTypeName(n))
			continue
		}
		if len(ifs.ThenBlock) != 1 || nodeTypeName(ifs.ThenBlock[0]) != c.typ {
			t.Errorf("%q then_block -> %v want [%s]", c.sql, dumpTypes(ifs.ThenBlock), c.typ)
		}
	}

	// ELSE 分支（BEGIN block 遇 ELSE 收束）
	els := mustParse(t, "IF 1=1 BEGIN SELECT 1 END ELSE SELECT 0").(*IfStatement)
	if len(els.ElseBlock) != 1 {
		t.Errorf("else_block len %d", len(els.ElseBlock))
	}
	// IF 無 BEGIN — 單語句 block
	nb := mustParse(t, "IF 1=1 SELECT 1").(*IfStatement)
	if len(nb.ThenBlock) != 1 {
		t.Errorf("no-begin then_block len %d", len(nb.ThenBlock))
	}
}

func dumpTypes(ns []Node) []string {
	out := make([]string, len(ns))
	for i, n := range ns {
		out[i] = nodeTypeName(n)
	}
	return out
}

func TestParserCoverage_Exec(t *testing.T) {
	rv := mustParse(t, "EXEC @result = sp_myproc 'arg1'").(*ExecStatement)
	if rv.ReturnVar == nil || rv.ReturnVar.(*IdentifierNode).Name != "@result" {
		t.Errorf("return_var: %+v", rv.ReturnVar)
	}
	pos := mustParse(t, "EXEC sp_help 'Customer', 1").(*ExecStatement)
	if len(pos.Args) != 2 {
		t.Errorf("positional args %d", len(pos.Args))
	}
	named := mustParse(t, "EXEC sp_myproc @name = 'Alice', @age = 30").(*ExecStatement)
	if len(named.NamedArgs) != 2 {
		t.Errorf("named args %d", len(named.NamedArgs))
	}
	fb := mustParse(t, "EXEC sp_myproc @x").(*ExecStatement)
	if len(fb.Args) < 1 {
		t.Errorf("@x 無 = 應為 positional：%+v", fb.Args)
	}
}

func TestParserCoverage_CreateTable(t *testing.T) {
	ine := mustParse(t, "CREATE TABLE IF NOT EXISTS #Temp (ID INT)").(*CreateTableStatement)
	if !ine.IfNotExists {
		t.Error("if_not_exists 應為 true")
	}
	con := mustParse(t, "CREATE TABLE Customer (ID INT NOT NULL, CONSTRAINT pk_c UNIQUE)").(*CreateTableStatement)
	if len(con.Columns) < 1 {
		t.Errorf("table-level constraint 應被略過，欄位 ID 仍解析：%d", len(con.Columns))
	}
	if c := mustParse(t, "CREATE TABLE T (Name NVARCHAR(50) NULL)").(*CreateTableStatement).Columns[0]; !c.Nullable {
		t.Error("NULL modifier -> nullable true")
	}
	id := mustParse(t, "CREATE TABLE T (ID INT IDENTITY(1,1) NOT NULL)").(*CreateTableStatement).Columns[0]
	if !id.IsIdentity || id.Nullable {
		t.Errorf("IDENTITY(1,1) NOT NULL: identity=%v nullable=%v", id.IsIdentity, id.Nullable)
	}
	if pk := mustParse(t, "CREATE TABLE T (ID INT PRIMARY KEY)").(*CreateTableStatement).Columns[0]; !pk.IsPrimaryKey {
		t.Error("PRIMARY KEY modifier")
	}
	if d := mustParse(t, "CREATE TABLE T (Status INT DEFAULT 0)").(*CreateTableStatement).Columns[0]; d.Default == nil {
		t.Error("DEFAULT 0 -> default 非 nil")
	}
}

func TestParserCoverage_Merge(t *testing.T) {
	sub := mustParse(t, "MERGE INTO Target AS t USING (SELECT ID, Name FROM Source) AS s ON t.ID = s.ID WHEN MATCHED THEN UPDATE SET t.Name = s.Name;").(*MergeStatement)
	if _, ok := sub.Source.(*SelectStatement); !ok {
		t.Errorf("subquery source -> %s", nodeTypeName(sub.Source))
	}
	nms := mustParse(t, "MERGE INTO Target AS t USING Source AS s ON t.ID = s.ID WHEN NOT MATCHED BY SOURCE THEN DELETE;").(*MergeStatement)
	if nms.Clauses[0].MatchType != "NOT_MATCHED_BY_SOURCE" || nms.Clauses[0].Action != "DELETE" {
		t.Errorf("NOT MATCHED BY SOURCE: %+v", nms.Clauses[0])
	}
	andc := mustParse(t, "MERGE INTO Target AS t USING Source AS s ON t.ID = s.ID WHEN MATCHED AND t.Name <> s.Name THEN UPDATE SET t.Name = s.Name;").(*MergeStatement)
	if andc.Clauses[0].Condition == nil {
		t.Error("MERGE clause AND condition 應非 nil")
	}
}
