package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 python-final:tests/test_final_coverage_suite.py

const finalCSV = `table_name,column_name,data_type
Address,AddressID,INT
Address,City,NVARCHAR
Customer,CustomerID,INT
Customer,CompanyName,NVARCHAR
`

func fcRun(t *testing.T, sql string) {
	t.Helper()
	if _, err := NewRunner(mkReg(t, finalCSV)).Run(sql, nil); err != nil {
		t.Errorf("%q 應成功: %v", sql, err)
	}
}
func fcSemErr(t *testing.T, sql, sub string) {
	t.Helper()
	_, err := NewRunner(mkReg(t, finalCSV)).Run(sql, nil)
	if err == nil || (sub != "" && !strings.Contains(err.Error(), sub)) {
		t.Errorf("%q -> %v want 含 %q", sql, err, sub)
	}
}
func fcSyntaxErr(t *testing.T, sql, sub string) {
	t.Helper()
	err := parseErr(t, sql)
	if err == nil || !strings.Contains(err.Error(), sub) {
		t.Errorf("%q -> %v want 含 %q", sql, err, sub)
	}
}

func TestFinalCov_Binder(t *testing.T) {
	fcSemErr(t, "WITH cte AS (SELECT CustomerID FROM Customer) SELECT cte.NoSuchCol FROM cte JOIN Address ON cte.CustomerID = Address.AddressID", "")
	fcSemErr(t, "SELECT NoSuchColAnywhere FROM Customer JOIN Address ON Customer.CustomerID = Address.AddressID", "not found")
	fcSemErr(t, "SELECT AddressID FROM Address WHERE AddressID > ANY (1, 'hello')", "Incompatible")
	fcRun(t, "IF 1=1 SELECT AddressID FROM Address")
	fcRun(t, "IF 1=1 SELECT AddressID FROM Address ELSE SELECT City FROM Address")
	fcSemErr(t, "EXEC SomeProc 1, 2, 3", "allow-list")
	fcRun(t, "SET NOCOUNT ON")
	fcRun(t, "MERGE Address USING Address ON 1 = 1 WHEN MATCHED THEN UPDATE SET AddressID = 1")
	fcRun(t, "MERGE Address USING Address ON 1 = 1 WHEN MATCHED AND 1 = 1 THEN UPDATE SET AddressID = 1")
	fcRun(t, "PRINT 'hello world'")
	fcSemErr(t, "SELECT CASE WHEN CustomerID > 0 THEN 'yes' ELSE CompanyName END, COUNT(*) FROM Customer GROUP BY CustomerID", "")

	// bindOverClause(nil) no-op
	NewBinder(NewMetadataRegistry()).bindOverClause(nil)

	// 未知窗函數 + OVER
	reg := mkReg(t, "table_name,column_name,data_type\nAddress,City,NVARCHAR\n")
	fn := NewFunctionCall("FAKE_WINDOW", nil)
	fn.OverClause = &OverClauseNode{OrderBy: []*OrderByNode{{Column: NewIdentifier("City", nil), Direction: "ASC"}}}
	err := recoverBail(func() { NewBinder(reg).visitExpr(fn) })
	if err == nil || !strings.Contains(err.Msg, "Unknown function 'FAKE_WINDOW' for window context") {
		t.Errorf("unknown window fn -> %v", err)
	}
}

func TestFinalCov_BinderSetScript(t *testing.T) {
	r := NewRunner(mkReg(t, finalCSV))
	if _, err := r.RunScript("DECLARE @x INT\nSET @x = 5\nSELECT AddressID FROM Address WHERE AddressID = @x", nil); err != nil {
		t.Errorf("SET var script: %v", err)
	}
}

func TestFinalCov_BinderResolveIdentifierEmptyVirtualSchema(t *testing.T) {
	b := NewBinder(NewMetadataRegistry())
	b.tempSchemas["#GHOST"] = newColSchema()
	b.scopes = append(b.scopes, newScopeFrame())
	b.scopes[0].set("#GHOST", "#GHOST")
	b.nullableStack = append(b.nullableStack, map[string]bool{})
	if err := recoverBail(func() { b.resolveIdentifier(NewIdentifier("AnyCol", nil)) }); err != nil {
		t.Errorf("空 virtual schema pass-through: %v", err)
	}
}

func TestFinalCov_Parser(t *testing.T) {
	fcSyntaxErr(t, "SELECT * FROM Address WHERE AddressID NOT 5", "Expected LIKE, BETWEEN, or IN after NOT")
	fcSyntaxErr(t, "SELECT (NOT 5) FROM Address", "Expected EXISTS after NOT")
	fcSyntaxErr(t, "SELECT Address. FROM Address", "Expected identifier")
	fcSyntaxErr(t, "IF 1=1 ROLLBACK", "Unexpected")
	fcSyntaxErr(t, "SELECT SUM(Salary) OVER (ORDER BY Salary ROWS UNBOUNDED) FROM Address", "Expected PRECEDING or FOLLOWING after UNBOUNDED")
	fcSyntaxErr(t, "SELECT SUM(Salary) OVER (ORDER BY Salary ROWS CURRENT) FROM Address", "Expected ROW after CURRENT")
	fcSyntaxErr(t, "SELECT SUM(Salary) OVER (ORDER BY Salary ROWS 5) FROM Address", "Expected PRECEDING or FOLLOWING after number")

	for _, sql := range []string{
		"SELECT 1 | 2", "SELECT 3 ^ 1", "SELECT ~1", "SELECT -GETDATE()",
		"IF 1=1 BEGIN SELECT 1 ELSE",
		"IF 1=1 ALTER TABLE Address ADD NewCol INT",
		"IF 1=1 BULK INSERT INTO Address",
		"EXEC @dynamic_proc 1, 2",
		"CREATE TABLE IF NOT EXISTS #tmp (id INT)",
	} {
		if mustParse(t, sql) == nil {
			t.Errorf("%q 應可解析", sql)
		}
	}
}

func TestFinalCov_Lexer(t *testing.T) {
	toks := mustTokens(t, "SELECT 1")
	if !strings.Contains(toks[0].String(), "Token") && !strings.Contains(toks[0].String(), "KEYWORD") {
		t.Errorf("Token.String: %s", toks[0].String())
	}
	has := func(sql string, want TokenType) {
		for _, tk := range mustTokens(t, sql) {
			if tk.Type == want {
				return
			}
		}
		t.Errorf("%q 缺少 token %v", sql, want)
	}
	has("WHERE x <= 5", SymLE)
	has("1 | 2 ^ 3 & ~4", SymPipe)
	has("1 | 2 ^ 3 & ~4", SymCaret)
	has("1 | 2 ^ 3 & ~4", SymTilde)
	// 不認得的字元 / '!' 不接 '=' → 略過不 crash
	if _, err := NewLexer("SELECT 1!2").Tokenize(); err != nil {
		t.Errorf("'!' 略過: %v", err)
	}
	if _, err := NewLexer("SELECT 1 $ 2").Tokenize(); err != nil {
		t.Errorf("'$' 略過: %v", err)
	}
}

func TestFinalCov_Reconstructor(t *testing.T) {
	rt := func(sql, want string) {
		data := map[string]any{}
		json.Unmarshal([]byte(NewSerializer().ToJSON(mustParse(t, sql))), &data)
		got, err := NewReconstructor().Reconstruct(mustJSON(data))
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(got, want) {
			t.Errorf("%q -> %q missing %q", sql, got, want)
		}
	}
	rt("CREATE TABLE #tmp (id INT IDENTITY(1,1))", "IDENTITY")
	rt("CREATE TABLE #tmp (id INT PRIMARY KEY)", "PRIMARY KEY")
	rt("CREATE TABLE #tmp (id INT DEFAULT 0)", "DEFAULT")
	rt("MERGE Address USING Address ON 1 = 1 WHEN MATCHED THEN DELETE", "DELETE")

	// MERGE clause 非標準 action → 原樣輸出
	rc := NewReconstructor()
	res := rc.ReconstructValue(map[string]any{
		"node_type": "MergeClauseNode", "match_type": "MATCHED", "condition": nil,
		"action": "UNKNOWN_ACTION", "set_clauses": []any{}, "insert_columns": []any{}, "insert_values": []any{},
	})
	if !strings.Contains(res, "UNKNOWN_ACTION") {
		t.Errorf("merge unknown action: %q", res)
	}

	// OVER frame bounds
	fnSQL := rc.ReconstructValue(map[string]any{
		"node_type": "FunctionCallNode", "name": "ROW_NUMBER", "args": []any{},
		"over": map[string]any{"node_type": "OverClauseNode",
			"partition_by": []any{map[string]any{"node_type": "IdentifierNode", "name": "CustomerID", "qualifiers": []any{}, "alias": nil}},
			"order_by": []any{map[string]any{"node_type": "OrderByNode",
				"column":    map[string]any{"node_type": "IdentifierNode", "name": "OrderDate", "qualifiers": []any{}, "alias": nil},
				"direction": "DESC"}},
			"frame_type": "ROWS", "frame_start": "UNBOUNDED PRECEDING", "frame_end": "CURRENT ROW"},
		"alias": nil,
	})
	if !strings.Contains(fnSQL, "ROWS UNBOUNDED PRECEDING AND CURRENT ROW") {
		t.Errorf("over frame: %q", fnSQL)
	}
	if got := rc.ReconstructValue(map[string]any{"node_type": "OverClauseNode",
		"partition_by": []any{}, "order_by": []any{}, "frame_type": nil, "frame_start": nil, "frame_end": nil}); got != "OVER ()" {
		t.Errorf("empty OVER: %q", got)
	}
}

func mustJSON(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

func TestFinalCov_Registry(t *testing.T) {
	reg := mkReg(t, "table_name,column_name,data_type\nT,C,INT\n")
	if !reg.HasTable("T") || !reg.HasColumn("T", "C") {
		t.Error("basic load")
	}
	// 空欄位列被略過
	reg2 := mkReg(t, "table_name,column_name,data_type\n,,\nT,C,INT\n")
	if !reg2.HasTable("T") || reg2.HasTable("") {
		t.Error("empty row skip")
	}
	// GetColumnType 未知表 / 未知欄位 → "UNKNOWN"
	if reg.GetColumnType("Ghost", "X") != "UNKNOWN" || reg.GetColumnType("T", "Ghost") != "UNKNOWN" {
		t.Error("GetColumnType unknown")
	}
	if reg.GetColumnType("T", "C") != "INT" {
		t.Error("GetColumnType known")
	}
}

func TestFinalCov_Serializer(t *testing.T) {
	s := NewSerializer()
	arr := s.serAny([]Node{NewLiteral("1", NumericLiteral), NewLiteral("2", NumericLiteral)})
	if ja, ok := arr.(jarr); !ok || len(ja) != 2 {
		t.Errorf("serAny tuple -> %v", arr)
	}
	data := map[string]any{}
	json.Unmarshal([]byte(NewSerializer().ToJSON(mustParse(t, "IF 1=1 SELECT 1 ELSE SELECT 2"))), &data)
	if data["node_type"] != "IfStatement" {
		t.Errorf("IfStatement serialize: %v", data["node_type"])
	}
	if _, ok := data["then_block"]; !ok {
		t.Error("then_block missing")
	}
	if _, ok := data["else_block"]; !ok {
		t.Error("else_block missing")
	}
}

func TestFinalCov_Visualizer(t *testing.T) {
	upd := &UpdateStatement{Table: NewIdentifier("Address", nil), TableAlias: "a",
		SetClauses: []*AssignmentNode{{Column: NewIdentifier("City", nil), Right: NewLiteral("X", StringLiteral)}},
		Where: NewBinaryExpr(NewIdentifier("AddressID", nil), "=", NewLiteral("1", NumericLiteral))}
	if out := NewVisualizer().Dump(upd); !strings.Contains(out, "UPDATE_STATEMENT") || !strings.Contains(out, "ALIAS: a") {
		t.Errorf("update alias: %s", out)
	}
	del := &DeleteStatement{Table: NewIdentifier("Address", nil), TableAlias: "a",
		Where: NewBinaryExpr(NewIdentifier("AddressID", nil), "=", NewLiteral("1", NumericLiteral))}
	if out := NewVisualizer().Dump(del); !strings.Contains(out, "DELETE_STATEMENT") || !strings.Contains(out, "ALIAS: a") {
		t.Errorf("delete alias: %s", out)
	}
	ins := &InsertStatement{Table: NewIdentifier("T", nil), Columns: nil,
		Values: []Node{NewLiteral("1", NumericLiteral)}}
	if out := NewVisualizer().Dump(ins); !strings.Contains(out, "INSERT_STATEMENT") || !strings.Contains(out, "VALUES") {
		t.Errorf("insert values: %s", out)
	}
	if out := NewVisualizer().Dump(mustParse(t, "SELECT CASE CustomerID WHEN 1 THEN 'a' ELSE 'b' END FROM Customer")); !strings.Contains(out, "CASE_EXPRESSION") || !strings.Contains(out, "CustomerID") {
		t.Errorf("case input: %s", out)
	}

	fn := NewFunctionCall("ROW_NUMBER", nil)
	fn.OverClause = &OverClauseNode{
		PartitionBy: []Node{NewIdentifier("CustomerID", nil)},
		OrderBy:     []*OrderByNode{{Column: NewIdentifier("OrderDate", nil), Direction: "DESC"}},
		FrameType:   "ROWS", FrameStart: "UNBOUNDED PRECEDING", FrameEnd: "CURRENT ROW",
	}
	out := NewVisualizer().Dump(fn)
	for _, w := range []string{"OVER_CLAUSE", "PARTITION_BY", "ORDER_BY", "FRAME: ROWS", "START: UNBOUNDED PRECEDING", "END: CURRENT ROW"} {
		if !strings.Contains(out, w) {
			t.Errorf("over clause 缺少 %q\n%s", w, out)
		}
	}
}

func TestFinalCov_Intent(t *testing.T) {
	am := newAliasMap()
	s, tb, col := resolveCol(map[string]any{"qualifiers": []any{"SalesLT", "Customer"}, "name": "CustomerID"}, am)
	if s != "SalesLT" || tb != "Customer" || col != "CustomerID" {
		t.Errorf("3-part qualifier: %q %q %q", s, tb, col)
	}
	var intents []Intent
	NewIntentExtractor().add(&intents, "", "", sp("col"), "READ")
	if len(intents) != 0 {
		t.Errorf("add empty table: %+v", intents)
	}
}
