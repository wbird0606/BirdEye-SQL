package birdeye

import (
	"strings"
	"testing"
)

// 對照 python-final:tests/test_mermaid_suite.py
// Python 傳入手建 dict 給 exporter.export()；Go 的 Export 吃 *omap，故以等價 JSON 串走 ExportJSON。

func TestMermaid_BasicNodes(t *testing.T) {
	code := NewMermaidExporter().ExportJSON(
		`{"node_type":"SelectStatement","table":{"node_type":"IdentifierNode","name":"Users"},"columns":[{"node_type":"IdentifierNode","name":"ID"}]}`)
	for _, w := range []string{"flowchart TD", "ID: Users", "ID: ID"} {
		if !strings.Contains(code, w) {
			t.Errorf("缺少 %q\n%s", w, code)
		}
	}
}

func TestMermaid_AdvancedNodes(t *testing.T) {
	code := NewMermaidExporter().ExportJSON(
		`{"node_type":"UnionStatement","op":"UNION ALL",` +
			`"left":{"node_type":"SelectStatement","table":{"node_type":"IdentifierNode","name":"T1"}},` +
			`"right":{"node_type":"SelectStatement","table":{"node_type":"IdentifierNode","name":"T2"}}}`)
	for _, w := range []string{"SET OP: UNION ALL", "ID: T1", "ID: T2"} {
		if !strings.Contains(code, w) {
			t.Errorf("缺少 %q\n%s", w, code)
		}
	}
}

func TestMermaid_CTE(t *testing.T) {
	code := NewMermaidExporter().ExportJSON(
		`{"node_type":"SelectStatement","ctes":[{"node_type":"CTENode","name":"MYCTE","query":{"node_type":"SelectStatement"}}]}`)
	if !strings.Contains(code, "CTE: MYCTE") {
		t.Errorf("缺少 CTE: MYCTE\n%s", code)
	}
}
