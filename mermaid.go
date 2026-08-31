package birdeye

import (
	"sort"
	"strings"
)

// MermaidExporter 對照 Python birdeye/mermaid_exporter.py：serialize 後的 AST（JSON）
// → Mermaid flowchart 語法。輸入為保留 key 順序的 *omap（對照 Python json.loads 的 dict）。
type MermaidExporter struct {
	nodeCount int
	lines     []string
}

func NewMermaidExporter() *MermaidExporter { return &MermaidExporter{} }

// ExportJSON 從 AST JSON 字串產生 mermaid（供 conformance / runner 使用）。
func (e *MermaidExporter) ExportJSON(astJSON string) string {
	v, err := parseOrderedJSON(astJSON)
	if err != nil {
		return "flowchart TD"
	}
	return e.Export(v)
}

// Export 對照 export()。
func (e *MermaidExporter) Export(astDict any) string {
	e.lines = []string{"flowchart TD"}
	e.nodeCount = 0
	e.buildTree(astDict)
	return strings.Join(e.lines, "\n")
}

// _OP_MAP：順序即 Python dict 迭代順序（>= 必須在 > 之前替換）。
var mermaidOpMap = []struct{ from, to string }{
	{"<>", "NEQ"}, {"!=", "NEQ"}, {">=", "GTE"}, {"<=", "LTE"},
	{">", "GT"}, {"<", "LT"}, {"&", "AND"}, {"=", "EQ"},
}

func (e *MermaidExporter) cleanText(text string) string {
	if text == "" {
		return ""
	}
	s := strings.NewReplacer(`"`, "", "'", "", "[", "", "]", "", "(", "", ")", "").Replace(text)
	for _, p := range mermaidOpMap {
		s = strings.ReplaceAll(s, p.from, p.to)
	}
	return s
}

func (e *MermaidExporter) nodeID() string {
	e.nodeCount++
	return "node_" + itoa(e.nodeCount)
}

var mermaidSkipKeys = map[string]bool{
	"node_type": true, "alias": true, "direction": true, "op": true, "name": true,
	"target": true, "is_convert": true, "is_not": true, "is_star": true, "top": true,
}

func mget(o *omap, k string) any {
	if v, ok := o.m[k]; ok {
		return v
	}
	return nil
}
func mstr(o *omap, k string) string {
	s, _ := mget(o, k).(string)
	return s
}

func (e *MermaidExporter) buildTree(node any) string {
	o, ok := node.(*omap)
	if !ok || o == nil {
		return ""
	}
	nt := mstr(o, "node_type")
	if nt == "" {
		nt = "Unknown"
	}
	nodeID := e.nodeID()

	label := e.label(nt, o)
	e.lines = append(e.lines, "  "+nodeID+`["`+e.cleanText(label)+`"];`)

	for _, key := range o.keys {
		if mermaidSkipKeys[key] {
			continue
		}
		value := o.m[key]

		if key == "bound_params" {
			if bp, ok := value.(*omap); ok {
				e.emitParams(nodeID, o, bp)
			}
			continue
		}
		if key == "bound_param_values" {
			continue
		}

		switch v := value.(type) {
		case *omap:
			if childID := e.buildTree(v); childID != "" {
				e.lines = append(e.lines, "  "+nodeID+` -- "`+e.cleanText(key)+`" --> `+childID+";")
			}
		case []any:
			for i, item := range v {
				if im, ok := item.(*omap); ok {
					if childID := e.buildTree(im); childID != "" {
						labelKey := key + "_" + itoa(i)
						if key == "statements" {
							labelKey = "STMT " + itoa(i+1)
						}
						e.lines = append(e.lines, "  "+nodeID+` -- "`+e.cleanText(labelKey)+`" --> `+childID+";")
					}
				}
			}
		}
	}
	return nodeID
}

func (e *MermaidExporter) emitParams(nodeID string, parent, bp *omap) {
	valMap, _ := parent.m["bound_param_values"].(*omap)
	names := map[string]bool{}
	for _, k := range bp.keys {
		names[k] = true
	}
	if valMap != nil {
		for _, k := range valMap.keys {
			names[k] = true
		}
	}
	sorted := make([]string, 0, len(names))
	for k := range names {
		sorted = append(sorted, k)
	}
	sort.Strings(sorted)

	qmarkMode := mstr(parent, "param_input_mode") == "qmark"
	for _, pName := range sorted {
		pType := "UNKNOWN"
		if bp != nil {
			if t, ok := bp.m[pName].(string); ok {
				pType = t
			}
		}
		var pVal any
		if valMap != nil {
			pVal = valMap.m[pName]
		}
		leafID := e.nodeID()
		disp := pName
		if qmarkMode && strings.HasPrefix(strings.ToUpper(pName), "@P") {
			disp = "?<" + pName + ">"
		}
		leaf := "PARAM: " + disp + " [" + pType + "] = " + pyReprJSON(pVal)
		e.lines = append(e.lines, "  "+leafID+`["`+e.cleanText(leaf)+`"];`)
		e.lines = append(e.lines, "  "+nodeID+` -- "param" --> `+leafID+";")
	}
}

// pyReprJSON 對照 repr()，但值來自 json（數字為 float64）。
func pyReprJSON(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case float64:
		if x == float64(int64(x)) {
			return itoa(int(x))
		}
		return encFloat(x)
	case string:
		if strings.Contains(x, "'") && !strings.Contains(x, `"`) {
			return `"` + x + `"`
		}
		return "'" + strings.NewReplacer(`\`, `\\`, `'`, `\'`).Replace(x) + "'"
	}
	return "None"
}

func (e *MermaidExporter) label(nt string, o *omap) string {
	typeInfo := func(key string) string {
		if inf, ok := o.m[key].(string); ok && inf != "" && inf != "UNKNOWN" {
			return " [" + inf + "]"
		}
		return ""
	}
	tname := func(k string) string {
		if t, ok := o.m[k].(*omap); ok {
			var quals []string
			if qs, ok := t.m["qualifiers"].([]any); ok {
				for _, q := range qs {
					quals = append(quals, str(q))
				}
			}
			return strings.Join(append(quals, mstr(t, "name")), ".")
		}
		return "?"
	}

	switch nt {
	case "ScriptNode":
		count := 0
		if s, ok := o.m["statements"].([]any); ok {
			count = len(s)
		}
		bp, _ := o.m["bound_params"].(*omap)
		bpv, _ := o.m["bound_param_values"].(*omap)
		info := ""
		if (bp != nil && len(bp.keys) > 0) || (bpv != nil && len(bpv.keys) > 0) {
			pn, vn := 0, 0
			if bp != nil {
				pn = len(bp.keys)
			}
			if bpv != nil {
				vn = len(bpv.keys)
			}
			info = ", params=" + itoa(pn) + ", values=" + itoa(vn)
		}
		return "SCRIPT (" + itoa(count) + " stmts" + info + ")"
	case "IdentifierNode":
		var quals []string
		if qs, ok := o.m["qualifiers"].([]any); ok {
			for _, q := range qs {
				quals = append(quals, str(q))
			}
		}
		name := mstr(o, "name")
		if internal, ok := o.m["internal_param_name"].(string); ok && internal != "" && name == "?" {
			name = "?<" + internal + ">"
		}
		return "ID: " + strings.Join(append(quals, name), ".") + typeInfo("inferred_type")
	case "LiteralNode":
		tn := mstr(o, "inferred_type")
		if tn == "" {
			tn = mstr(o, "type")
		}
		ti := ""
		if tn != "" && tn != "UNKNOWN" {
			ti = " [" + tn + "]"
		}
		return "LITERAL: " + valStr(o.m["value"]) + ti
	case "BinaryExpressionNode":
		return "OP: " + mstr(o, "op") + typeInfo("inferred_type")
	case "FunctionCallNode":
		return "FUNC: " + mstr(o, "name") + typeInfo("inferred_type")
	case "BetweenExpressionNode":
		return "BETWEEN"
	case "CastExpressionNode":
		return "CAST TO " + valStr(o.m["target"])
	case "UnionStatement":
		return "SET OP: " + mstr(o, "op")
	case "CTENode":
		return "CTE: " + mstr(o, "name")
	case "TruncateStatement":
		return "TRUNCATE"
	case "DeclareStatement":
		return "DECLARE " + mstr(o, "var_name") + " " + mstr(o, "var_type")
	case "SetStatement":
		tn := "?"
		if t, ok := o.m["target"].(*omap); ok {
			tn = mstr(t, "name")
		} else if s, ok := o.m["target"].(string); ok && s != "" {
			tn = s
		}
		return "SET " + tn + " ="
	case "IfStatement":
		return "IF"
	case "MergeStatement":
		l := "MERGE INTO " + tname("target")
		if a, ok := o.m["target_alias"].(string); ok && a != "" {
			l += " AS " + a
		}
		return l
	case "MergeClauseNode":
		return "WHEN " + mstr(o, "match_type") + " THEN " + mstr(o, "action")
	case "CreateTableStatement":
		return "CREATE TABLE " + tname("table")
	case "DropTableStatement":
		return "DROP TABLE " + tname("table")
	case "AlterTableStatement":
		return "ALTER TABLE"
	case "ExecStatement":
		return "EXEC " + tname("proc_name")
	case "PrintStatement":
		return "PRINT"
	}
	return nt
}

func valStr(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case float64:
		if x == float64(int64(x)) {
			return itoa(int(x))
		}
		return encFloat(x)
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	}
	return ""
}
