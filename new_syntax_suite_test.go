package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_new_syntax_suite.py
// —— 9 種 MSSQL 新 AST 節點：解析 + 序列化 + 重建。

func nsSerialize(t *testing.T, sql string) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal([]byte(NewSerializer().ToJSON(mustParse(t, sql))), &m); err != nil {
		t.Fatalf("serialize %q: %v", sql, err)
	}
	return m
}

func nsRoundTrip(t *testing.T, sql string) string {
	t.Helper()
	out, err := NewReconstructor().Reconstruct(NewSerializer().ToJSON(mustParse(t, sql)))
	if err != nil {
		t.Fatalf("round_trip %q: %v", sql, err)
	}
	return out
}

func nsReg(t *testing.T) *MetadataRegistry {
	return mkReg(t, `table_name,column_name,data_type
Customer,CustomerID,INT
Customer,Name,NVARCHAR
Customer,Phone,NVARCHAR
Orders,OrderID,INT
Orders,CustomerID,INT
Orders,Amount,DECIMAL
`)
}

func TestNewSyntax_If(t *testing.T) {
	if nodeTypeName(mustParse(t, "IF 1=1 BEGIN SELECT 1 END")) != "IfStatement" {
		t.Error("IF node type")
	}
	we := mustParse(t, "IF @x > 0 BEGIN SELECT 1 END ELSE BEGIN SELECT 0 END").(*IfStatement)
	if len(we.ThenBlock) == 0 || len(we.ElseBlock) == 0 {
		t.Errorf("IF then/else: %+v", we)
	}
	if len(mustParse(t, "IF 1=1 BEGIN SELECT 1 END").(*IfStatement).ElseBlock) != 0 {
		t.Error("no-else else_block 應為空")
	}
	d := nsSerialize(t, "IF 1=1 BEGIN SELECT 1 END ELSE BEGIN SELECT 0 END")
	for _, k := range []string{"condition", "then_block", "else_block"} {
		if _, ok := d[k]; !ok {
			t.Errorf("IF serialize 缺 %q", k)
		}
	}
	if !strings.HasPrefix(strings.ToUpper(strings.TrimSpace(nsRoundTrip(t, "IF 1=1 BEGIN SELECT 1 END"))), "IF") {
		t.Error("IF reconstruct 開頭")
	}
	rt := strings.ToUpper(nsRoundTrip(t, "IF 1=1 BEGIN SELECT 1 END ELSE BEGIN SELECT 0 END"))
	if !strings.Contains(rt, "IF") || !strings.Contains(rt, "ELSE") {
		t.Errorf("IF...ELSE reconstruct: %s", rt)
	}
}

func TestNewSyntax_Exec(t *testing.T) {
	ex := mustParse(t, "EXEC sp_helptext 'Customer'").(*ExecStatement)
	if nodeTypeName(ex) != "ExecStatement" || ex.ProcName == nil {
		t.Errorf("EXEC parse: %+v", ex)
	}
	if strings.ToUpper(ex.ProcName.(*IdentifierNode).Name) != "SP_HELPTEXT" {
		t.Errorf("proc_name: %v", ex.ProcName)
	}
	if len(ex.Args) < 1 {
		t.Errorf("EXEC args: %d", len(ex.Args))
	}
	// ZTA：xp_cmdshell 被攔截
	if err := recoverBail(func() { NewBinder(nsReg(t)).bindNode(mustParse(t, "EXEC xp_cmdshell 'dir'")) }); err == nil {
		t.Error("EXEC xp_cmdshell 應被攔截")
	}
	// 重建（手建 dict，避開 serializer A2）
	rc := NewReconstructor()
	s1 := rc.ReconstructValue(map[string]any{"node_type": "ExecStatement", "proc_name": "sp_helptext",
		"args":  []any{map[string]any{"node_type": "LiteralNode", "value": "Customer", "type": "STRING_LITERAL"}},
		"named_args": []any{}, "return_var": nil})
	if !strings.HasPrefix(strings.ToUpper(strings.TrimSpace(s1)), "EXEC") {
		t.Errorf("EXEC reconstruct: %q", s1)
	}
	s2 := rc.ReconstructValue(map[string]any{"node_type": "ExecStatement", "proc_name": "sp_helptext",
		"args": []any{}, "named_args": []any{}, "return_var": nil})
	if !strings.Contains(s2, "sp_helptext") {
		t.Errorf("EXEC reconstruct proc name: %q", s2)
	}
}

func TestNewSyntax_Set(t *testing.T) {
	if v := mustParse(t, "SET @counter = 1").(*SetStatement); nodeTypeName(v) != "SetStatement" || v.IsOption {
		t.Errorf("SET @var: %+v", v)
	}
	if o := mustParse(t, "SET NOCOUNT ON").(*SetStatement); nodeTypeName(o) != "SetStatement" || !o.IsOption {
		t.Errorf("SET OPTION: %+v", o)
	}
	d := nsSerialize(t, "SET @counter = 1")
	for _, k := range []string{"target", "value", "is_option"} {
		if _, ok := d[k]; !ok {
			t.Errorf("SET serialize 缺 %q", k)
		}
	}
	if !strings.HasPrefix(strings.ToUpper(strings.TrimSpace(nsRoundTrip(t, "SET @counter = 1"))), "SET") {
		t.Error("SET reconstruct 開頭")
	}
	so := strings.ToUpper(NewReconstructor().ReconstructValue(map[string]any{
		"node_type": "SetStatement", "target": "NOCOUNT", "value": "ON", "is_option": true}))
	if !strings.Contains(so, "NOCOUNT") || !strings.Contains(so, "ON") {
		t.Errorf("SET OPTION reconstruct: %q", so)
	}
}

func TestNewSyntax_CreateDropAlter(t *testing.T) {
	ct := mustParse(t, "CREATE TABLE #Temp (ID INT NOT NULL, Name NVARCHAR(100))").(*CreateTableStatement)
	if nodeTypeName(ct) != "CreateTableStatement" || len(ct.Columns) != 2 {
		t.Errorf("CREATE TABLE: %+v", ct)
	}
	res, err := NewRunner(nsReg(t)).Run("CREATE TABLE #Temp (ID INT NOT NULL, Name NVARCHAR(100))", nil)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Binder.TempSchemas()["#TEMP"] {
		t.Errorf("#TEMP 未註冊：%v", res.Binder.TempSchemas())
	}
	d := nsSerialize(t, "CREATE TABLE #Temp (ID INT NOT NULL)")
	if _, ok := d["table"]; !ok {
		t.Error("CREATE serialize table")
	}
	if _, ok := d["columns"]; !ok {
		t.Error("CREATE serialize columns")
	}
	if !strings.HasPrefix(strings.ToUpper(strings.TrimSpace(nsRoundTrip(t, "CREATE TABLE #Temp (ID INT NOT NULL)"))), "CREATE TABLE") {
		t.Error("CREATE reconstruct 開頭")
	}

	dt := mustParse(t, "DROP TABLE #Temp").(*DropTableStatement)
	if nodeTypeName(dt) != "DropTableStatement" || dt.IfExists {
		t.Errorf("DROP TABLE: %+v", dt)
	}
	if !mustParse(t, "DROP TABLE IF EXISTS Customer").(*DropTableStatement).IfExists {
		t.Error("DROP IF EXISTS")
	}
	dd := nsSerialize(t, "DROP TABLE #Temp")
	if _, ok := dd["table"]; !ok {
		t.Error("DROP serialize table")
	}
	if _, ok := dd["if_exists"]; !ok {
		t.Error("DROP serialize if_exists")
	}
	if !strings.HasPrefix(strings.ToUpper(strings.TrimSpace(nsRoundTrip(t, "DROP TABLE #Temp"))), "DROP TABLE") {
		t.Error("DROP reconstruct 開頭")
	}
	if !strings.Contains(strings.ToUpper(nsRoundTrip(t, "DROP TABLE IF EXISTS Customer")), "IF EXISTS") {
		t.Error("DROP IF EXISTS reconstruct")
	}

	at := mustParse(t, "ALTER TABLE Customer ADD Phone NVARCHAR(20)").(*AlterTableStatement)
	if nodeTypeName(at) != "AlterTableStatement" || at.Action != "ADD" {
		t.Errorf("ALTER ADD: %+v", at)
	}
	ad := nsSerialize(t, "ALTER TABLE Customer ADD Phone NVARCHAR(20)")
	for _, k := range []string{"table", "action", "column"} {
		if _, ok := ad[k]; !ok {
			t.Errorf("ALTER serialize 缺 %q", k)
		}
	}
	if !strings.HasPrefix(strings.ToUpper(strings.TrimSpace(nsRoundTrip(t, "ALTER TABLE Customer ADD Phone NVARCHAR(20)"))), "ALTER TABLE") {
		t.Error("ALTER reconstruct 開頭")
	}
	if mustParse(t, "ALTER TABLE Customer DROP COLUMN Phone").(*AlterTableStatement).Action != "DROP" {
		t.Error("ALTER DROP COLUMN action")
	}
}

const nsMergeSQL = "MERGE INTO Customer AS tgt USING Orders AS src ON tgt.CustomerID = src.CustomerID " +
	"WHEN MATCHED THEN UPDATE SET tgt.Name = src.Amount " +
	"WHEN NOT MATCHED THEN INSERT (CustomerID) VALUES (src.CustomerID)"

func TestNewSyntax_Merge(t *testing.T) {
	m := mustParse(t, nsMergeSQL).(*MergeStatement)
	if nodeTypeName(m) != "MergeStatement" || len(m.Clauses) < 1 {
		t.Errorf("MERGE parse: %+v", m)
	}
	d := nsSerialize(t, nsMergeSQL)
	for _, k := range []string{"target", "source", "on_condition", "clauses"} {
		if _, ok := d[k]; !ok {
			t.Errorf("MERGE serialize 缺 %q", k)
		}
	}
	rt := strings.ToUpper(nsRoundTrip(t, nsMergeSQL))
	if !strings.HasPrefix(strings.TrimSpace(rt), "MERGE") || !strings.Contains(rt, "USING") || !strings.Contains(rt, "ON") {
		t.Errorf("MERGE reconstruct: %s", rt)
	}
	del := mustParse(t, "MERGE INTO Customer AS tgt USING Orders AS src ON tgt.CustomerID = src.CustomerID WHEN MATCHED THEN DELETE").(*MergeStatement)
	found := false
	for _, c := range del.Clauses {
		if c.Action == "DELETE" {
			found = true
		}
	}
	if !found {
		t.Errorf("MERGE DELETE clause: %+v", del.Clauses)
	}
}

func TestNewSyntax_Print(t *testing.T) {
	p := mustParse(t, "PRINT 'hello'").(*PrintStatement)
	if nodeTypeName(p) != "PrintStatement" || p.Expr == nil {
		t.Errorf("PRINT parse: %+v", p)
	}
	if _, ok := nsSerialize(t, "PRINT 'hello'")["expr"]; !ok {
		t.Error("PRINT serialize expr")
	}
	rt := nsRoundTrip(t, "PRINT 'hello'")
	if !strings.HasPrefix(strings.ToUpper(strings.TrimSpace(rt)), "PRINT") || !strings.Contains(rt, "hello") {
		t.Errorf("PRINT reconstruct: %q", rt)
	}
}
