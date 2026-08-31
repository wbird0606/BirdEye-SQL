package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

func jsonUnmarshal(s string, v any) error { return json.Unmarshal([]byte(s), v) }

// coverage_test.go：針對 conformance 語料未觸及的 Go 分支補測
// （Python 端由 test_final_coverage / test_gap_to_100 / test_branch_phase* 覆蓋）。

func TestRunnerAPICoverage(t *testing.T) {
	aw := loadAdventureWorks(t)
	r := NewRunner(nil)
	if err := r.LoadMetadataFromCSV("table_name,column_name,data_type\nT,C,INT\n"); err != nil {
		t.Fatal(err)
	}
	if r.Registry().GetColumnType("T", "C") != "INT" {
		t.Fatal("LoadMetadataFromCSV")
	}
	n, err := NewRunner(aw).ParseOnly("SELECT AddressID FROM Address", nil)
	if err != nil || nodeTypeName(n) != "SelectStatement" {
		t.Fatalf("ParseOnly: %v %v", n, err)
	}
	sn, err := NewRunner(aw).ParseOnlyMulti("SELECT 1; SELECT 2", nil)
	if err != nil || nodeTypeName(sn) != "ScriptNode" {
		t.Fatalf("ParseOnlyMulti: %v %v", sn, err)
	}
	if _, err := NewRunner(aw).ParseOnly("SELECT x FROM GhostTable", nil); err != nil {
		t.Fatalf("ParseOnly 應忽略未知表: %v", err)
	}
}

func TestTokenStringCoverage(t *testing.T) {
	for tt := KwSelect; tt <= EOF; tt++ {
		if tt.String() == "" {
			t.Errorf("TokenType %d has empty String()", int(tt))
		}
	}
	if TokenType(9999).String() != "TokenType(9999)" {
		t.Errorf("unknown token String: %s", TokenType(9999).String())
	}
	if !strings.Contains((Token{Type: Identifier, Value: "x"}).String(), "IDENTIFIER") {
		t.Error("Token.String")
	}
}

func TestParserValueErrorPath(t *testing.T) {
	sql := "SELECT TOP 1.5 A FROM T"
	toks, _ := NewLexer(sql).Tokenize()
	_, perr := NewParser(toks, sql).Parse()
	if be, ok := perr.(*Error); !ok || be.Kind != ErrValue {
		t.Fatalf("TOP 1.5 應為 value error，得到 %v", perr)
	}
}

func TestSerializerEscapeCoverage(t *testing.T) {
	var b strings.Builder
	encStr(&b, "a\tb\nc\rd\be\ff\x01g\"h\\i")
	got := b.String()
	for _, want := range []string{"\\t", "\\n", "\\r", "\\b", "\\f", "\\u0001", "\\\"", "\\\\"} {
		if !strings.Contains(got, want) {
			t.Errorf("encStr 缺少 %q：%s", want, got)
		}
	}
	for in, want := range map[float64]string{30: "30.0", 1.5: "1.5"} {
		if encFloat(in) != want {
			t.Errorf("encFloat(%v) = %q want %q", in, encFloat(in), want)
		}
	}
}

func TestFloatParamCoverage(t *testing.T) {
	aw := loadAdventureWorks(t)
	res, err := NewRunner(aw).Run("SELECT @p AS x",
		&OrderedParams{Keys: []string{"p"}, Vals: map[string]any{"p": 1.5}})
	if err != nil {
		t.Fatal(err)
	}
	m := metaOf(res.AST)
	if m == nil || len(m.Params) != 1 || m.Params[0].Type != "FLOAT" {
		t.Fatalf("float param type: %+v", m)
	}
	if !strings.Contains(res.JSON, "1.5") {
		t.Errorf("float param JSON: %s", res.JSON)
	}
}

func TestNullablePropagationWhiteBox(t *testing.T) {
	reg := mkReg(t, "table_name,column_name,data_type\nA,ID,INT\nB,ID,INT\nC,ID,INT\n")
	res, err := NewRunner(reg).Run("SELECT A.ID FROM A LEFT JOIN B ON A.ID = B.ID", nil)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Binder.LastRootNullables()["B"] {
		t.Errorf("LEFT JOIN 後 B 應為 nullable：%v", res.Binder.LastRootNullables())
	}
	res2, _ := NewRunner(reg).Run("SELECT A.ID FROM A FULL JOIN B ON A.ID = B.ID", nil)
	nl := res2.Binder.LastRootNullables()
	if !nl["A"] || !nl["B"] {
		t.Errorf("FULL JOIN nullable：%v", nl)
	}
	res3, _ := NewRunner(reg).Run("SELECT A.ID FROM A RIGHT JOIN B ON A.ID = B.ID", nil)
	if !res3.Binder.LastRootNullables()["A"] {
		t.Errorf("RIGHT JOIN 後 A 應為 nullable：%v", res3.Binder.LastRootNullables())
	}
}

func TestBulkInsertAndTypeCompat(t *testing.T) {
	aw := loadAdventureWorks(t)
	if _, err := NewRunner(aw).Run("BULK INSERT INTO Address", nil); err != nil {
		t.Fatalf("BULK INSERT 已知表應成功: %v", err)
	}
	if _, err := NewRunner(aw).Run("BULK INSERT INTO GhostTable", nil); err == nil {
		t.Fatal("BULK INSERT 未知表應報錯")
	}
	if _, err := NewRunner(aw).Run("SELECT ModifiedDate FROM Address WHERE ModifiedDate = '2020-01-01'", nil); err != nil {
		t.Errorf("date vs string 應相容: %v", err)
	}
}

func TestIntentAuxAPI(t *testing.T) {
	aw := loadAdventureWorks(t)
	res, _ := NewRunner(aw).Run("SELECT a.City FROM SalesLT.Address a JOIN SalesLT.CustomerAddress ca ON a.AddressID = ca.AddressID", nil)

	is, err := NewIntentExtractor().ExtractFromStr(res.JSON)
	if err != nil || len(is) == 0 {
		t.Fatalf("ExtractFromStr: %v", err)
	}
	var m any
	if err := jsonUnmarshal(res.JSON, &m); err != nil {
		t.Fatal(err)
	}
	tables := NewIntentExtractor().ExtractTables(m)
	got := map[string]bool{}
	for _, tb := range tables {
		got[tb[0]+"."+tb[1]] = true
	}
	if !got["SalesLT.Address"] || !got["SalesLT.CustomerAddress"] {
		t.Errorf("ExtractTables: %v", tables)
	}

	// parse_only 版 ExtractTables（proxy 第一遍掃描）
	sn, _ := NewRunner(aw).ParseOnlyMulti("SELECT City FROM SalesLT.Address; SELECT Name FROM SalesLT.Product", nil)
	var sm any
	jsonUnmarshal(NewSerializer().ToJSON(sn), &sm)
	tt := NewIntentExtractor().ExtractTables(sm)
	if len(tt) != 2 {
		t.Errorf("ExtractTables multi: %v", tt)
	}
}

func TestOrderedJSONGet(t *testing.T) {
	v, err := parseOrderedJSON(`{"a":1,"b":[true,null,"x"],"c":{}}`)
	if err != nil {
		t.Fatal(err)
	}
	o := v.(*omap)
	if x, ok := o.get("a"); !ok || x.(float64) != 1 {
		t.Error("get a")
	}
	if _, ok := o.get("missing"); ok {
		t.Error("get missing")
	}
	if arr := o.m["b"].([]any); len(arr) != 3 {
		t.Error("array")
	}
}

func TestReconstructEdgePaths(t *testing.T) {
	// where_condition / expression key 變體（來自 binder 序列化 vs 直接建構）
	rc := NewReconstructor()
	upd := rc.ReconstructValue(map[string]any{
		"node_type": "UpdateStatement",
		"table":     map[string]any{"node_type": "IdentifierNode", "name": "T", "qualifiers": []any{}},
		"set_clauses": []any{map[string]any{"node_type": "AssignmentNode",
			"column":     map[string]any{"node_type": "IdentifierNode", "name": "A", "qualifiers": []any{}},
			"expression": map[string]any{"node_type": "LiteralNode", "value": "1", "type": "NUMERIC_LITERAL"}}},
		"where_condition": map[string]any{"node_type": "BinaryExpressionNode", "op": "=",
			"left":  map[string]any{"node_type": "IdentifierNode", "name": "B", "qualifiers": []any{}},
			"right": map[string]any{"node_type": "LiteralNode", "value": "2", "type": "NUMERIC_LITERAL"}},
	})
	if upd != "UPDATE T SET A = 1 WHERE B = 2" {
		t.Errorf("update alt keys: %q", upd)
	}
	del := rc.ReconstructValue(map[string]any{
		"node_type": "DeleteStatement",
		"table":     map[string]any{"node_type": "IdentifierNode", "name": "T", "qualifiers": []any{}},
		"where": map[string]any{"node_type": "BinaryExpressionNode", "op": "IS NULL",
			"left":  map[string]any{"node_type": "IdentifierNode", "name": "C", "qualifiers": []any{}},
			"right": nil},
	})
	if del != "DELETE FROM T WHERE C IS NULL" {
		t.Errorf("delete: %q", del)
	}
}

func TestTempSchemaWhiteBox(t *testing.T) {
	aw := loadAdventureWorks(t)
	res, err := NewRunner(aw).RunMulti("SELECT AddressID INTO #T FROM Address; SELECT AddressID FROM #T", nil)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Binder.TempSchemas()["#T"] {
		t.Errorf("#T 應註冊：%v", res.Binder.TempSchemas())
	}
}
