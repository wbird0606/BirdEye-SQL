package birdeye

import (
	"regexp"
	"strings"
)

// RowFilter 對照 Python row_filter 的 filter dict（權限系統回傳、需注入 WHERE 的述詞）。
type RowFilter struct {
	Schema    string `json:"Schema"`
	Table     string `json:"Table"`
	Column    string `json:"Column"`
	Operator  string `json:"Operator"`
	ValueType string `json:"ValueType"`
	Value     any    `json:"Value"` // string 或（SUBQUERY 時）預解析的 AST dict
}

// RowFilterInjector 對照 Python birdeye/row_filter.py 的 RowFilterInjector：
// 走訪 AST JSON dict，對每個查詢指定資料表的語句注入額外 WHERE 條件。
type RowFilterInjector struct{}

func NewRowFilterInjector() *RowFilterInjector { return &RowFilterInjector{} }

// 只接受 ASCII 整數、十進位小數、指數 ≤ 3 位的科學記號。
var rowFilterNumericRE = regexp.MustCompile(`^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$`)

// Inject 對照 inject()：無 filter 時回傳原物件；否則 deep-copy 後注入。
func (ri *RowFilterInjector) Inject(astJSON map[string]any, rowFilters []RowFilter) map[string]any {
	if len(rowFilters) == 0 {
		return astJSON
	}
	cp := deepCopyMap(astJSON)
	ri.walk(cp, rowFilters)
	return cp
}

func deepCopyJSON(v any) any {
	switch x := v.(type) {
	case map[string]any:
		return deepCopyMap(x)
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = deepCopyJSON(e)
		}
		return out
	default:
		return v
	}
}

func deepCopyMap(m map[string]any) map[string]any {
	if m == nil {
		return nil
	}
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = deepCopyJSON(v)
	}
	return out
}

// ── AST 走訪 ────────────────────────────────────────────────────────────────

func (ri *RowFilterInjector) walk(nodeRaw any, rf []RowFilter) {
	if nodeRaw == nil {
		return
	}
	if list, ok := nodeRaw.([]any); ok {
		for _, item := range list {
			ri.walk(item, rf)
		}
		return
	}
	node, ok := nodeRaw.(map[string]any)
	if !ok {
		return
	}

	switch dstr(node, "node_type") {
	case "ScriptNode":
		for _, s := range dslice(node, "statements") {
			ri.walk(s, rf)
		}
	case "SelectStatement":
		ri.walkSubqueriesInSelect(node, rf)
		entries := buildAliasEntries(node)
		if applicable := matchFilters(entries, rf); len(applicable) > 0 {
			var conds []any
			for _, f := range applicable {
				conds = append(conds, makeCondition(f, entries))
			}
			node["where"] = andConditions(node["where"], conds)
		}
	case "UpdateStatement", "DeleteStatement":
		entries := buildAliasEntriesDML(node)
		if applicable := matchFilters(entries, rf); len(applicable) > 0 {
			var conds []any
			for _, f := range applicable {
				conds = append(conds, makeCondition(f, entries))
			}
			node["where"] = andConditions(node["where"], conds)
		}
	case "UnionStatement":
		ri.walk(node["left"], rf)
		ri.walk(node["right"], rf)
	case "IfStatement":
		for _, s := range dslice(node, "then_block") {
			ri.walk(s, rf)
		}
		for _, s := range dslice(node, "else_block") {
			ri.walk(s, rf)
		}
	}
}

func (ri *RowFilterInjector) walkSubqueriesInSelect(node map[string]any, rf []RowFilter) {
	for _, cte := range dslice(node, "ctes") {
		ri.walk(node2map(cte)["query"], rf)
	}
	if tbl := dmap(node, "table"); tbl != nil {
		if nt := dstr(tbl, "node_type"); nt == "SelectStatement" || nt == "UnionStatement" {
			ri.walk(tbl, rf)
		}
	}
	for _, j := range dslice(node, "joins") {
		jt := dmap(node2map(j), "table")
		if jt != nil {
			if nt := dstr(jt, "node_type"); nt == "SelectStatement" || nt == "UnionStatement" {
				ri.walk(jt, rf)
			}
		}
	}
	for _, ap := range dslice(node, "applies") {
		ri.walk(node2map(ap)["subquery"], rf)
	}
	for _, col := range dslice(node, "columns") {
		ri.walkExpr(col, rf)
	}
	ri.walkExpr(node["where"], rf)
	ri.walkExpr(node["having"], rf)
	for _, ob := range dslice(node, "order_by") {
		ri.walkExpr(node2map(ob)["column"], rf)
	}
}

func (ri *RowFilterInjector) walkExpr(nodeRaw any, rf []RowFilter) {
	if nodeRaw == nil {
		return
	}
	if list, ok := nodeRaw.([]any); ok {
		for _, item := range list {
			ri.walkExpr(item, rf)
		}
		return
	}
	node, ok := nodeRaw.(map[string]any)
	if !ok {
		return
	}
	switch dstr(node, "node_type") {
	case "SelectStatement", "UnionStatement":
		ri.walk(node, rf)
	case "BinaryExpressionNode":
		ri.walkExpr(node["left"], rf)
		ri.walkExpr(node["right"], rf)
	case "FunctionCallNode":
		for _, a := range dslice(node, "args") {
			ri.walkExpr(a, rf)
		}
	case "CastExpressionNode":
		ri.walkExpr(node["expr"], rf)
	case "BetweenExpressionNode":
		for _, k := range []string{"target", "low", "high"} {
			ri.walkExpr(node[k], rf)
		}
	case "CaseExpressionNode":
		ri.walkExpr(node["input"], rf)
		for _, br := range dslice(node, "branches") {
			bm := node2map(br)
			ri.walkExpr(bm["when"], rf)
			ri.walkExpr(bm["then"], rf)
		}
		ri.walkExpr(node["else"], rf)
	}
}

// ── alias entries ──────────────────────────────────────────────────────────
// 每個 entry：(schemaUpper, tableUpper, qualifier)；qualifier = alias 或原表名。

type aliasEntry struct{ schema, table, qualifier string }

func buildAliasEntries(selectNode map[string]any) []aliasEntry {
	var entries []aliasEntry
	reg := func(tblNode map[string]any, alias string) {
		if tblNode == nil || dstr(tblNode, "node_type") != "IdentifierNode" {
			return
		}
		quals := strSlice(dslice(tblNode, "qualifiers"))
		name := dstr(tblNode, "name")
		if name == "" {
			return
		}
		schema := ""
		if len(quals) > 0 {
			schema = quals[0]
		}
		q := alias
		if q == "" {
			q = name
		}
		entries = append(entries, aliasEntry{strings.ToUpper(schema), strings.ToUpper(name), q})
	}
	reg(dmap(selectNode, "table"), dstr(selectNode, "alias"))
	for _, j := range dslice(selectNode, "joins") {
		jm := node2map(j)
		reg(dmap(jm, "table"), dstr(jm, "alias"))
	}
	return entries
}

func buildAliasEntriesDML(node map[string]any) []aliasEntry {
	tbl := dmap(node, "table")
	if tbl == nil || dstr(tbl, "node_type") != "IdentifierNode" {
		return nil
	}
	quals := strSlice(dslice(tbl, "qualifiers"))
	name := dstr(tbl, "name")
	if name == "" {
		return nil
	}
	schema := ""
	if len(quals) > 0 {
		schema = quals[0]
	}
	q := dstr(node, "alias")
	if q == "" {
		q = name
	}
	return []aliasEntry{{strings.ToUpper(schema), strings.ToUpper(name), q}}
}

func matchFilters(entries []aliasEntry, rf []RowFilter) []RowFilter {
	var result []RowFilter
	for _, f := range rf {
		sUp := strings.ToUpper(f.Schema)
		tUp := strings.ToUpper(f.Table)
		for _, e := range entries {
			if e.table == tUp && (sUp == "" || e.schema == sUp) {
				result = append(result, f)
				break
			}
		}
	}
	return result
}

// ── condition builder ─────────────────────────────────────────────────────

func makeCondition(f RowFilter, entries []aliasEntry) map[string]any {
	schema := strings.ToUpper(f.Schema)
	table := strings.ToUpper(f.Table)
	column := f.Column
	operator := strings.ToUpper(f.Operator)
	if operator == "" {
		operator = "="
	}
	vtype := strings.ToUpper(f.ValueType)
	if vtype == "" {
		vtype = "LITERAL"
	}
	value := ""
	if s, ok := f.Value.(string); ok {
		value = s
	}

	qualifier := findQualifier(schema, table, entries)
	quals := []any{}
	if qualifier != "" {
		quals = []any{qualifier}
	}
	colNode := map[string]any{
		"node_type": "IdentifierNode", "name": column,
		"qualifiers": quals, "alias": nil,
	}

	var right any
	switch {
	case vtype == "SUBQUERY":
		m, ok := f.Value.(map[string]any)
		if !ok {
			panic(engineBail{valueErr(
				"RowFilter ValueType=SUBQUERY 需傳入預解析的 SelectStatement AST dict（table=" +
					f.Table + ", column=" + column + "）")})
		}
		right = m
	case operator == "IN" || operator == "NOT IN":
		var items []any
		for _, v := range strings.Split(value, ",") {
			v = strings.TrimSpace(v)
			if v != "" {
				items = append(items, makeLiteral(v))
			}
		}
		if items == nil {
			items = []any{}
		}
		right = items
	default:
		right = makeLiteral(value)
	}

	return map[string]any{
		"node_type": "BinaryExpressionNode", "op": operator,
		"left": colNode, "right": right, "alias": nil,
	}
}

func makeLiteral(value string) map[string]any {
	if rowFilterNumericRE.MatchString(value) {
		return map[string]any{"node_type": "LiteralNode", "value": value, "type": "NUMERIC_LITERAL", "alias": nil}
	}
	escaped := strings.ReplaceAll(value, "'", "''")
	prefix := ""
	for _, c := range value {
		if c > 127 {
			prefix = "N"
			break
		}
	}
	return map[string]any{"node_type": "LiteralNode", "value": prefix + "'" + escaped + "'", "type": "STRING_LITERAL", "alias": nil}
}

func findQualifier(schemaUp, tableUp string, entries []aliasEntry) string {
	for _, e := range entries {
		if e.table == tableUp && (schemaUp == "" || e.schema == schemaUp) {
			return e.qualifier
		}
	}
	return tableUp
}

func andConditions(existing any, conditions []any) any {
	result := existing
	for _, cond := range conditions {
		if result == nil {
			result = cond
		} else {
			result = map[string]any{
				"node_type": "BinaryExpressionNode", "op": "AND",
				"left": result, "right": cond, "alias": nil,
			}
		}
	}
	return result
}
