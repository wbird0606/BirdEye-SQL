package birdeye

import (
	"strings"
	"testing"
)

// coverage_defensive_test.go：Go 語言本質的防禦性程式碼補測（Python 無對應：
// duck-typing 的 truthy、interface marker method、白箱 accessor 等）。

func TestDefensive_NodeMarkers(t *testing.T) {
	// aNode() 為 Node interface 的編譯期 marker，執行期永不被呼叫 —— 直接觸一下。
	baseNode{}.aNode()
	nodeList{}.aNode()
}

func TestDefensive_BinderAccessors(t *testing.T) {
	reg := mkReg(t, "table_name,column_name,data_type\nA,ID,INT\nB,ID,INT\n")
	res, err := NewRunner(reg).Run("SELECT A.ID FROM A LEFT JOIN B ON A.ID = B.ID", nil)
	if err != nil {
		t.Fatal(err)
	}
	// NullableScopes：綁定結束後堆疊已清空 → 回傳 lastRootNullables
	ns := res.Binder.NullableScopes()
	if !ns["B"] {
		t.Errorf("NullableScopes: %v", ns)
	}
	// nullableStack 非空時的分支：直接建構
	b := NewBinder(reg)
	b.nullableStack = append(b.nullableStack, map[string]bool{"X": true})
	if !b.nullableScopes()["X"] {
		t.Error("nullableScopes 堆疊頂端")
	}
}

func TestDefensive_ReconstructorTruthyBranches(t *testing.T) {
	rc := NewReconstructor()
	// sqlSelect 對 table / where / having 呼叫 truthy —— 用不同型別觸發各 case
	base := func(extra map[string]any) map[string]any {
		m := map[string]any{
			"node_type": "SelectStatement", "ctes": []any{}, "is_star": true, "columns": []any{},
			"table": nil, "joins": []any{}, "applies": []any{}, "into_table": nil,
			"where": nil, "group_by": []any{}, "having": nil, "order_by": []any{},
		}
		for k, v := range extra {
			m[k] = v
		}
		return m
	}
	// where 為 false（bool）/ ""（string）/ 空 slice / 0（float64）→ 皆視為 falsy，不輸出 WHERE
	for _, w := range []any{false, "", []any{}, float64(0)} {
		if got := rc.toSQL(base(map[string]any{"where": w})); strings.Contains(got, "WHERE") {
			t.Errorf("where=%v(%T) 不應輸出 WHERE：%q", w, w, got)
		}
	}
	// having 為非空字串 → truthy → 輸出（sqlExpr(string) 走 default）
	if got := rc.toSQL(base(map[string]any{"having": "x"})); !strings.Contains(got, "HAVING") {
		t.Errorf("having=\"x\" 應輸出 HAVING：%q", got)
	}
	// table 為非空 map → truthy
	if got := rc.toSQL(base(map[string]any{"table": map[string]any{"node_type": "IdentifierNode", "name": "T", "qualifiers": []any{}}})); !strings.Contains(got, "FROM T") {
		t.Errorf("table map 應輸出 FROM：%q", got)
	}
}

func TestDefensive_ReconstructorHelpers(t *testing.T) {
	rc := NewReconstructor()
	// strOrExpr：string / nil / node
	if strOrExpr(rc, "RAW") != "RAW" {
		t.Error("strOrExpr string")
	}
	if strOrExpr(rc, nil) != "" {
		t.Error("strOrExpr nil")
	}
	if strOrExpr(rc, map[string]any{"node_type": "LiteralNode", "value": "5", "type": "NUMERIC_LITERAL"}) != "5" {
		t.Error("strOrExpr node")
	}
	// str：非字串 → ""
	if str(123) != "" || str("a") != "a" {
		t.Error("str")
	}
	// SET OPTION：target / value 皆為字串 → strOrExpr string 分支
	if got := rc.ReconstructValue(map[string]any{
		"node_type": "SetStatement", "is_option": true, "target": "NOCOUNT", "value": "ON",
	}); got != "SET NOCOUNT ON" {
		t.Errorf("SET OPTION: %q", got)
	}
	// firstStr / firstSlice fallback（第一個 key 缺、第二個命中）
	if firstStr(map[string]any{"b": "hit"}, "a", "b") != "hit" {
		t.Error("firstStr fallback")
	}
	if len(firstSlice(map[string]any{"b": []any{1, 2}}, "a", "b")) != 2 {
		t.Error("firstSlice fallback")
	}
}

func TestDefensive_SerializerParamPaths(t *testing.T) {
	reg := mkReg(t, "table_name,column_name,data_type\nT,A,INT\n")
	// qmark 定位參數：serializer 應把 @P1 顯示為 "?"，並帶 bound_params
	res, err := NewRunner(reg).Run("SELECT A FROM T WHERE A = ?", []any{5})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(res.JSON, `"param_input_mode": "qmark"`) {
		t.Errorf("qmark mode 未標記：%s", res.JSON)
	}
	if !strings.Contains(res.Tree, "?") {
		t.Errorf("tree 未顯示 ?：%s", res.Tree)
	}
	// 具名參數
	res2, err := NewRunner(reg).Run("SELECT A FROM T WHERE A = @p",
		&OrderedParams{Keys: []string{"p"}, Vals: map[string]any{"p": 7}})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(res2.JSON, `"param_input_mode": "named"`) {
		t.Errorf("named mode 未標記：%s", res2.JSON)
	}
}
