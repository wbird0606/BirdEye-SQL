package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_branch_phase1_suite.py
// —— lexer / serializer / reconstructor / mermaid 的罕見分支。

// dummyNode：Python 用 type(node).__name__ 取名，Go 用編譯期 switch。
// 未知節點型別在 Go 走 nodeTypeName 的 default（回傳 ""）—— 記於 KNOWN_DEVIATIONS。
type dummyNode struct{ baseNode }

func TestBranchP1_LexerUnmatchedRParen(t *testing.T) {
	toks, err := NewLexer(")").Tokenize()
	if err != nil {
		t.Fatal(err)
	}
	if toks[0].Type != SymRParen {
		t.Errorf("toks[0] = %v", toks[0].Type)
	}
	if toks[len(toks)-1].Type != EOF {
		t.Errorf("last = %v", toks[len(toks)-1].Type)
	}
}

func TestBranchP1_SerializerPrintStatement(t *testing.T) {
	stmt := &PrintStatement{Expr: NewLiteral("hello", StringLiteral)}
	var payload map[string]any
	json.Unmarshal([]byte(NewSerializer().ToJSON(stmt)), &payload)
	if payload["node_type"] != "PrintStatement" {
		t.Errorf("node_type %v", payload["node_type"])
	}
	if payload["expr"].(map[string]any)["value"] != "hello" {
		t.Errorf("expr.value %v", payload["expr"])
	}
}

func TestBranchP1_SerializerUnknownNode(t *testing.T) {
	// Go：未知節點 → node_type ""（default 分支）。Python：type name。
	v := NewSerializer().serialize(&dummyNode{})
	obj, ok := v.(jobj)
	if !ok || len(obj) == 0 || obj[0].k != "node_type" || obj[0].v != "" {
		t.Errorf("unknown node serialize -> %v", v)
	}
}

func TestBranchP1_ReconstructorOffsetWithoutFetch(t *testing.T) {
	node := map[string]any{
		"node_type": "SelectStatement", "ctes": []any{}, "top": nil, "top_percent": false,
		"is_distinct": false, "is_star": true, "columns": []any{},
		"table": map[string]any{"node_type": "IdentifierNode", "name": "Address", "qualifiers": []any{}},
		"alias": nil, "joins": []any{}, "applies": []any{}, "into_table": nil, "where": nil,
		"group_by": []any{}, "having": nil, "order_by": []any{},
		"offset_count": float64(5), "fetch_count": nil,
	}
	sql := NewReconstructor().ReconstructValue(node)
	if !strings.Contains(sql, "OFFSET 5 ROWS") || strings.Contains(sql, "FETCH NEXT") {
		t.Errorf("got %q", sql)
	}
}

func TestBranchP1_ReconstructorLiteralAndCaseNoElse(t *testing.T) {
	rc := NewReconstructor()
	if lit := rc.sqlLiteral(map[string]any{"node_type": "LiteralNode", "value": "'abc'", "type": "STRING_LITERAL"}); lit != "'abc'" {
		t.Errorf("已加引號的 literal = %q", lit)
	}
	caseSQL := rc.sqlCase(map[string]any{
		"node_type": "CaseExpressionNode",
		"branches": []any{map[string]any{
			"when": map[string]any{"node_type": "LiteralNode", "value": "1", "type": "NUMERIC_LITERAL"},
			"then": map[string]any{"node_type": "LiteralNode", "value": "ok", "type": "STRING_LITERAL"},
		}},
	})
	if !strings.HasPrefix(caseSQL, "CASE") || strings.Contains(caseSQL, "ELSE") {
		t.Errorf("case no-else = %q", caseSQL)
	}
}

func TestBranchP1_ReconstructorOverClauseNoFrameBounds(t *testing.T) {
	sql := NewReconstructor().sqlOverClause(map[string]any{
		"node_type": "OverClauseNode", "partition_by": []any{}, "order_by": []any{},
		"frame_type": "ROWS", "frame_start": nil, "frame_end": nil,
	})
	if sql != "OVER (ROWS)" {
		t.Errorf("got %q", sql)
	}
}

func TestBranchP1_MermaidGuards(t *testing.T) {
	e := NewMermaidExporter()
	if e.cleanText("") != "" {
		t.Error("cleanText(\"\")")
	}
	if e.buildTree(nil) != "" {
		t.Error("buildTree(nil)")
	}
	if e.buildTree("not-a-dict") != "" {
		t.Error("buildTree(string)")
	}
	// SelectStatement 帶非 omap 子節點 → 邊不建立，但 flowchart 仍輸出
	code := e.ExportJSON(`{"node_type":"SelectStatement","table":null,"joins":[]}`)
	if !strings.Contains(code, "flowchart TD") {
		t.Errorf("%s", code)
	}
}
