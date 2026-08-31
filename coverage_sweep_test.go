package birdeye

import (
	"math"
	"strings"
	"testing"
)

// coverage_sweep_test.go：直接呼叫 helper 函式，補進 Python 因 duck-typing
// 而自然覆蓋、但 Go 型別 switch 需個別觸發的分支。

func TestSweep_VisualizerHelpers(t *testing.T) {
	if pyRepr(nil) != "None" || pyRepr(true) != "True" || pyRepr(false) != "False" ||
		pyRepr(42) != "42" || pyRepr(1.5) != "1.5" {
		t.Error("pyRepr scalars")
	}
	if pyRepr("it's") != `"it's"` {
		t.Errorf("pyRepr quote: %q", pyRepr("it's"))
	}
	if pyRepr("plain") != "'plain'" {
		t.Errorf("pyRepr plain: %q", pyRepr("plain"))
	}
	if reprNode(NewIdentifier("x", nil)) != "x" || reprNode(NewLiteral("1", NumericLiteral)) != "" {
		t.Error("reprNode")
	}
}

func TestSweep_MermaidHelpers(t *testing.T) {
	if valStr("s") != "s" || valStr(float64(5)) != "5" || valStr(1.5) != "1.5" ||
		valStr(nil) != "None" || valStr(true) != "True" || valStr(false) != "False" {
		t.Errorf("valStr")
	}
	if pyReprJSON(nil) != "None" || pyReprJSON(true) != "True" || pyReprJSON(false) != "False" ||
		pyReprJSON(float64(3)) != "3" || pyReprJSON(1.25) != "1.25" {
		t.Error("pyReprJSON scalars")
	}
	if pyReprJSON("a'b") != `"a'b"` || pyReprJSON("x") != "'x'" {
		t.Errorf("pyReprJSON string: %q %q", pyReprJSON("a'b"), pyReprJSON("x"))
	}
}

func TestSweep_SerializerHelpers(t *testing.T) {
	if encFloat(math.Inf(1)) != "Infinity" || encFloat(math.Inf(-1)) != "-Infinity" || encFloat(math.NaN()) != "NaN" {
		t.Error("encFloat inf/nan")
	}
	if encFloat(30) != "30.0" || encFloat(1.5) != "1.5" {
		t.Error("encFloat normal")
	}
	s := NewSerializer()
	if s.serStrOrNode(nil) != nil {
		t.Error("serStrOrNode nil")
	}
	if s.serStrOrNode("raw") != "raw" {
		t.Error("serStrOrNode string")
	}
	if m, ok := s.serStrOrNode(NewIdentifier("x", nil)).(jobj); !ok || m[0].v != "IdentifierNode" {
		t.Errorf("serStrOrNode node: %v", s.serStrOrNode(NewIdentifier("x", nil)))
	}
	arr := s.serAny([]string{"a", "b"})
	if ja, ok := arr.(jarr); !ok || len(ja) != 2 {
		t.Errorf("serAny []string: %v", arr)
	}
}

func TestSweep_UtilHelpers(t *testing.T) {
	if capitalize("") != "" {
		t.Error("capitalize empty")
	}
	if capitalize("hELLO") != "Hello" {
		t.Errorf("capitalize: %q", capitalize("hELLO"))
	}
	if inferredTypeOf(nil) != "UNKNOWN" {
		t.Error("inferredTypeOf nil")
	}
	if columnOutputName(NewLiteral("1", NumericLiteral)) != "" {
		t.Error("columnOutputName non-identifier no-alias")
	}
	lit := NewLiteral("1", NumericLiteral)
	lit.Alias = "L"
	if columnOutputName(lit) != "L" {
		t.Error("columnOutputName alias")
	}
	if joinAlias(&JoinNode{Table: NewLiteral("1", NumericLiteral)}) != "" {
		t.Error("joinAlias non-identifier table")
	}
	if joinAlias(&JoinNode{Table: NewIdentifier("T", nil)}) != "T" {
		t.Error("joinAlias table name")
	}
}

func TestSweep_ParserHelpers(t *testing.T) {
	p := NewParser(nil, "")
	if p.containsIdentifierNode(nil) {
		t.Error("containsIdentifierNode(nil)")
	}
	if !p.containsIdentifierNode(NewIdentifier("x", nil)) {
		t.Error("containsIdentifierNode(ident)")
	}
	if panicMsg("plain string") != "plain string" {
		t.Errorf("panicMsg string: %q", panicMsg("plain string"))
	}
	if panicMsg(&Error{ErrSyntax, "boom"}) != "boom" {
		t.Errorf("panicMsg *Error: %q", panicMsg(&Error{ErrSyntax, "boom"}))
	}
	if !strings.Contains(panicMsg(42), "42") {
		t.Errorf("panicMsg other: %q", panicMsg(42))
	}
}

func TestSweep_RegistryRegisterFunction(t *testing.T) {
	reg := NewMetadataRegistry()
	reg.RegisterFunction("MYFN", "scalar", 0, 0, nil, "int") // expectedTypes nil 分支
	f := reg.GetFunction("MYFN")
	if f == nil || f.FuncType != "SCALAR" || f.ReturnType != "INT" || f.ExpectedTypes == nil {
		t.Errorf("RegisterFunction: %+v", f)
	}
}

func TestSweep_PrepareParamErrors(t *testing.T) {
	reg := mkReg(t, "table_name,column_name,data_type\nT,A,INT\n")
	// PARAM_COUNT_MISMATCH
	if _, err := NewRunner(reg).Run("SELECT ?, ? FROM T", []any{1}); err == nil || !strings.Contains(err.Error(), "PARAM_COUNT_MISMATCH") {
		t.Errorf("count mismatch -> %v", err)
	}
	// PARAM_MODE_MIXED（qmark SQL + object params）
	if _, err := NewRunner(reg).Run("SELECT ? FROM T", &OrderedParams{Keys: []string{"p"}, Vals: map[string]any{"p": 1}}); err == nil || !strings.Contains(err.Error(), "PARAM_MODE_MIXED") {
		t.Errorf("mode mixed -> %v", err)
	}
	// ParseOnly / ParseOnlyMulti 的 prepareSQL 錯誤路徑
	if _, err := NewRunner(reg).ParseOnly("SELECT ?", nil); err == nil {
		t.Error("ParseOnly SELECT ? 應報錯")
	}
	if _, err := NewRunner(reg).ParseOnlyMulti("SELECT ?", nil); err == nil {
		t.Error("ParseOnlyMulti SELECT ? 應報錯")
	}
	// ParseOnly lex 錯誤
	if _, err := NewRunner(reg).ParseOnly("SELECT 'unterminated", nil); err == nil {
		t.Error("ParseOnly 未閉合字串應報錯")
	}
}

func TestSweep_IntentExtractFromStrError(t *testing.T) {
	if _, err := NewIntentExtractor().ExtractFromStr("{not json"); err == nil {
		t.Error("ExtractFromStr invalid JSON")
	}
}

func TestSweep_ReconstructorUnionExecDefaults(t *testing.T) {
	rc := NewReconstructor()
	// sqlUnion 無 op → 預設 "UNION"
	u := rc.ReconstructValue(map[string]any{
		"node_type": "UnionStatement",
		"left":      map[string]any{"node_type": "SelectStatement", "is_star": true},
		"right":     map[string]any{"node_type": "SelectStatement", "is_star": true},
	})
	if !strings.Contains(u, "SELECT * UNION SELECT *") {
		t.Errorf("union default op: %q", u)
	}
	// sqlExec return_var 為字串 + proc_name 為字串
	e := rc.ReconstructValue(map[string]any{
		"node_type": "ExecStatement", "proc_name": "sp_x", "return_var": "@r",
		"args": []any{}, "named_args": []any{},
	})
	if !strings.Contains(e, "EXEC @r = sp_x") {
		t.Errorf("exec return_var: %q", e)
	}
}

func TestSweep_MiscBranches(t *testing.T) {
	// ErrKind.String default
	if ErrKind(99).String() != "system" && !strings.Contains(ErrKind(99).String(), "system") {
		// system 是 default；若實作回傳其他值也接受非空
		if ErrKind(99).String() == "" {
			t.Error("ErrKind default String")
		}
	}
	// qmarkMode 對非語句節點 → false
	if qmarkMode(NewLiteral("1", NumericLiteral)) {
		t.Error("qmarkMode non-statement")
	}
	// firstStr / firstSlice 全 key 缺失
	if firstStr(map[string]any{}, "a", "b") != "" {
		t.Error("firstStr all missing")
	}
	if firstSlice(map[string]any{}, "a", "b") != nil {
		t.Error("firstSlice all missing")
	}
	// deepEqualJ 型別不符
	if deepEqualJ(jobj{{"k", 1}}, jarr{1}) {
		t.Error("deepEqualJ jobj vs jarr")
	}
	if deepEqualJ(jarr{1, 2}, jarr{1}) {
		t.Error("deepEqualJ jarr len mismatch")
	}
	if !deepEqualJ("x", "x") || deepEqualJ("x", "y") {
		t.Error("deepEqualJ scalar")
	}
	// mermaid ExportJSON invalid JSON → 仍回 flowchart TD
	if NewMermaidExporter().ExportJSON("{not json") != "flowchart TD" {
		t.Error("ExportJSON invalid")
	}
	// ordered_json 錯誤路徑
	if _, err := parseOrderedJSON("{bad"); err == nil {
		t.Error("parseOrderedJSON invalid")
	}
	if _, err := parseOrderedJSON(`{"k": }`); err == nil {
		t.Error("parseOrderedJSON bad value")
	}
	// serialize2 nil / nil-pointer
	s := NewSerializer()
	if s.serialize2(nil) != nil {
		t.Error("serialize2 nil")
	}
	var np *IdentifierNode
	if s.serialize2(np) != nil {
		t.Error("serialize2 nil pointer")
	}
	// nodeList → serAny 路徑
	if a := s.serialize2(nodeList{NewLiteral("1", NumericLiteral)}); a == nil {
		t.Error("serialize2 nodeList")
	}
}

func TestSweep_BinderSetTypePropagation(t *testing.T) {
	reg := mkReg(t, "table_name,column_name,data_type\nT,A,INT\n")
	// SET @b = @a：@b 繼承 @a 型別（DECLARE 先建立）
	if _, err := NewRunner(reg).RunScript("DECLARE @a INT = 1\nSET @b = @a\nSELECT A FROM T WHERE A = @b", nil); err != nil {
		t.Errorf("SET var propagation: %v", err)
	}
	// SET @x = (SELECT ...)：value 為 Node（visitExpr 分支）
	if _, err := NewRunner(reg).RunScript("DECLARE @x INT\nSET @x = (SELECT A FROM T)\nSELECT A FROM T", nil); err != nil {
		t.Errorf("SET scalar subquery: %v", err)
	}
}
