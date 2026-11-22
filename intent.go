package birdeye

import (
	"encoding/json"
	"sort"
	"strings"
)

// Intent 對照 Python intent_extractor 產出的 dict。Column 為 nil 表示資料表層級。
type Intent struct {
	Schema string  `json:"schema"`
	Table  string  `json:"table"`
	Column *string `json:"column"`
	Intent string  `json:"intent"`
}

const (
	IntentRead   = "READ"
	IntentFilter = "FILTER"
	IntentInsert = "INSERT"
	IntentUpdate = "UPDATE"
	IntentDelete = "DELETE"
)

// IntentExtractor 對照 Python birdeye/intent_extractor.py 的 IntentExtractor。
type IntentExtractor struct {
	seen map[[4]string]bool
}

func NewIntentExtractor() *IntentExtractor {
	return &IntentExtractor{seen: map[[4]string]bool{}}
}

type schemaTable struct{ schema, table string }
type strSetT map[string]bool

// aliasMap 對照 Python 的 alias_map dict：保留插入順序（intent 清單順序依賴它）。
type aliasMap struct {
	order []string
	m     map[string]schemaTable
}

func newAliasMap() *aliasMap { return &aliasMap{m: map[string]schemaTable{}} }

func (a *aliasMap) set(k string, v schemaTable) {
	if _, ok := a.m[k]; !ok {
		a.order = append(a.order, k)
	}
	a.m[k] = v
}

func (a *aliasMap) get(k string) (schemaTable, bool) {
	v, ok := a.m[k]
	return v, ok
}

// distinct 依插入順序回傳去重後的 (schema, table)。
func (a *aliasMap) distinct() []schemaTable {
	seen := map[schemaTable]bool{}
	var out []schemaTable
	for _, k := range a.order {
		st := a.m[k]
		if !seen[st] {
			seen[st] = true
			out = append(out, st)
		}
	}
	return out
}

// ExtractFromStr 對照 extract_from_str。
func (ie *IntentExtractor) ExtractFromStr(jsonStr string) ([]Intent, error) {
	var v any
	if err := json.Unmarshal([]byte(jsonStr), &v); err != nil {
		return nil, valueErr("intent: invalid JSON: " + err.Error())
	}
	return ie.Extract(v), nil
}

// Extract 對照 extract。頂層可為單一 dict 或 list（多語句 JSON）。
func (ie *IntentExtractor) Extract(astDict any) []Intent {
	ie.seen = map[[4]string]bool{}
	var intents []Intent
	if list, ok := astDict.([]any); ok { // 對照 Python _walk 的 isinstance(node, list) 分支
		for _, item := range list {
			ie.walk(node2map(item), &intents, strSetT{})
		}
		return intents
	}
	ie.walk(node2map(astDict), &intents, strSetT{})
	return intents
}

func (ie *IntentExtractor) add(intents *[]Intent, schema, table string, column *string, intent string) {
	if table == "" {
		return
	}
	col := ""
	if column != nil {
		col = *column
	}
	key := [4]string{schema, table, col, intent}
	if ie.seen[key] {
		return
	}
	ie.seen[key] = true
	*intents = append(*intents, Intent{Schema: schema, Table: table, Column: column, Intent: intent})
}

func sp(s string) *string { return &s }

// ── 頂層分派 ────────────────────────────────────────────────────────────────

func (ie *IntentExtractor) walk(node map[string]any, intents *[]Intent, cteNames strSetT) {
	if node == nil {
		return
	}
	switch dstr(node, "node_type") {
	case "ScriptNode":
		for _, s := range dslice(node, "statements") {
			ie.walk(node2map(s), intents, cteNames)
		}
	case "SelectStatement":
		ie.walkSelect(node, intents, cteNames, nil)
	case "UnionStatement":
		ie.walk(dmap(node, "left"), intents, cteNames)
		ie.walk(dmap(node, "right"), intents, cteNames)
	case "UpdateStatement":
		ie.walkUpdate(node, intents, cteNames)
	case "DeleteStatement":
		ie.walkDelete(node, intents, cteNames)
	case "InsertStatement":
		ie.walkInsert(node, intents, cteNames)
	case "TruncateStatement":
		s, tbl := tableInfo(dmap(node, "table"))
		if tbl != "" && !cteNames[tbl] {
			ie.add(intents, s, tbl, nil, IntentDelete)
		}
	case "IfStatement":
		ie.walkExpr(node["condition"], newAliasMap(), IntentFilter, intents, cteNames, nil)
		for _, s := range dslice(node, "then_block") {
			ie.walk(node2map(s), intents, cteNames)
		}
		for _, s := range dslice(node, "else_block") {
			ie.walk(node2map(s), intents, cteNames)
		}
	case "MergeStatement":
		ie.walkMerge(node, intents, cteNames)
	case "SetStatement":
		if !dbool(node, "is_option") {
			ie.walkExpr(node["value"], newAliasMap(), IntentRead, intents, cteNames, nil)
		}
	case "DeclareStatement":
		if dv := node["default_value"]; dv != nil {
			ie.walkExpr(dv, newAliasMap(), IntentRead, intents, cteNames, nil)
		}
	}
}

// ── SelectStatement ─────────────────────────────────────────────────────────

func (ie *IntentExtractor) walkSelect(node map[string]any, intents *[]Intent, cteNames strSetT, parentAlias *aliasMap) {
	localCTEs := strSetT{}
	for k := range cteNames {
		localCTEs[k] = true
	}
	for _, cRaw := range dslice(node, "ctes") {
		c := node2map(cRaw)
		localCTEs[strings.ToUpper(dstr(c, "name"))] = true
		ie.walk(node2map(c["query"]), intents, localCTEs)
	}

	am, derived := ie.buildAliasMap(node, localCTEs, intents)
	if parentAlias != nil {
		merged := newAliasMap()
		for _, k := range parentAlias.order {
			merged.set(k, parentAlias.m[k])
		}
		for _, k := range am.order {
			merged.set(k, am.m[k])
		}
		am = merged
	}

	columns := dslice(node, "columns")
	if dbool(node, "is_star") && len(columns) == 0 {
		for _, st := range am.distinct() {
			ie.add(intents, st.schema, st.table, nil, IntentRead)
		}
	} else {
		starAggEmitted := map[schemaTable]bool{}
		for _, colRaw := range columns {
			col := node2map(colRaw)
			if dstr(col, "node_type") == "FunctionCallNode" && hasStarArg(col) {
				for _, key := range am.order {
					st := am.m[key]
					if !starAggEmitted[st] && !derived[key] {
						starAggEmitted[st] = true
						ie.add(intents, st.schema, st.table, nil, IntentRead)
					}
				}
			} else {
				ie.walkExpr(colRaw, am, IntentRead, intents, localCTEs, derived)
			}
		}
	}

	if into := dmap(node, "into_table"); into != nil {
		s, tbl := tableInfo(into)
		if tbl != "" && !localCTEs[tbl] {
			ie.add(intents, s, tbl, nil, IntentInsert)
		}
	}

	ie.walkExpr(node["where"], am, IntentFilter, intents, localCTEs, derived)
	for _, j := range dslice(node, "joins") {
		ie.walkExpr(node2map(j)["on"], am, IntentFilter, intents, localCTEs, derived)
	}
	for _, g := range dslice(node, "group_by") {
		ie.walkExpr(g, am, IntentFilter, intents, localCTEs, derived)
	}
	ie.walkExpr(node["having"], am, IntentFilter, intents, localCTEs, derived)
	for _, ob := range dslice(node, "order_by") {
		ie.walkExpr(node2map(ob)["column"], am, IntentFilter, intents, localCTEs, derived)
	}
	for _, ap := range dslice(node, "applies") {
		ie.walkSubquery(node2map(ap)["subquery"], intents, localCTEs, am)
	}
}

func hasStarArg(col map[string]any) bool {
	for _, a := range dslice(col, "args") {
		am := node2map(a)
		if dstr(am, "node_type") == "IdentifierNode" && dstr(am, "name") == "*" {
			return true
		}
	}
	return false
}

// ── UpdateStatement ─────────────────────────────────────────────────────────

func (ie *IntentExtractor) walkUpdate(node map[string]any, intents *[]Intent, cteNames strSetT) {
	schema, tbl := tableInfo(dmap(node, "table"))
	if tbl == "" || cteNames[tbl] {
		return
	}
	am := newAliasMap()
	am.set(tbl, schemaTable{schema, tbl})
	if a := dstr(node, "alias"); a != "" {
		am.set(a, schemaTable{schema, tbl})
	}
	for _, asgnRaw := range dslice(node, "set") {
		asgn := node2map(asgnRaw)
		if colNode := node2map(asgn["column"]); colNode != nil && dstr(colNode, "node_type") == "IdentifierNode" {
			cs, ct, cn := resolveCol(colNode, am)
			schemaOut := cs
			if schemaOut == "" {
				schemaOut = schema
			}
			tableOut := ct
			if tableOut == "" {
				tableOut = tbl
			}
			ie.add(intents, schemaOut, tableOut, sp(cn), IntentUpdate)
		}
		ie.walkExpr(asgn["expr"], am, IntentRead, intents, cteNames, nil)
	}
	ie.walkExpr(node["where"], am, IntentFilter, intents, cteNames, nil)
}

func (ie *IntentExtractor) walkDelete(node map[string]any, intents *[]Intent, cteNames strSetT) {
	schema, tbl := tableInfo(dmap(node, "table"))
	if tbl == "" || cteNames[tbl] {
		return
	}
	am := newAliasMap()
	am.set(tbl, schemaTable{schema, tbl})
	if a := dstr(node, "alias"); a != "" {
		am.set(a, schemaTable{schema, tbl})
	}
	ie.add(intents, schema, tbl, nil, IntentDelete)
	ie.walkExpr(node["where"], am, IntentFilter, intents, cteNames, nil)
}

func (ie *IntentExtractor) walkInsert(node map[string]any, intents *[]Intent, cteNames strSetT) {
	schema, tbl := tableInfo(dmap(node, "table"))
	if tbl == "" || cteNames[tbl] {
		return
	}
	cols := dslice(node, "columns")
	if len(cols) > 0 {
		for _, cRaw := range cols {
			c := node2map(cRaw)
			if dstr(c, "node_type") == "IdentifierNode" {
				ie.add(intents, schema, tbl, sp(dstr(c, "name")), IntentInsert)
			}
		}
	} else {
		ie.add(intents, schema, tbl, nil, IntentInsert)
	}
	if src := node["source"]; src != nil {
		ie.walk(node2map(src), intents, cteNames)
	}
}

func (ie *IntentExtractor) walkMerge(node map[string]any, intents *[]Intent, cteNames strSetT) {
	sourceAlias := strings.ToUpper(dstr(node, "source_alias"))
	srcMap := dmap(node, "source")
	srcIsTable := srcMap != nil && dstr(srcMap, "node_type") == "IdentifierNode"
	if srcMap != nil && !srcIsTable {
		ie.walk(srcMap, intents, cteNames)
	}
	target := dmap(node, "target")
	targetAlias := dstr(node, "target_alias")
	schema, tbl := tableInfo(target)
	am := newAliasMap()
	if tbl != "" && !cteNames[strings.ToUpper(tbl)] {
		am.set(tbl, schemaTable{schema, tbl})
		if targetAlias != "" {
			am.set(targetAlias, schemaTable{schema, tbl})
		}
	}
	derived := strSetT{}
	if srcIsTable {
		// 來源為真實資料表：其欄位引用必須解析回該表並產生意圖（否則來源表之讀取會漏檢）。
		ss, st := tableInfo(srcMap)
		if st != "" && !cteNames[strings.ToUpper(st)] {
			am.set(st, schemaTable{ss, st})
			if sourceAlias != "" {
				am.set(dstr(node, "source_alias"), schemaTable{ss, st})
			}
		} else if sourceAlias != "" {
			derived[sourceAlias] = true
		}
	} else if sourceAlias != "" {
		derived[sourceAlias] = true
	}
	ie.walkExpr(node["on_condition"], am, IntentFilter, intents, cteNames, derived)
	for _, clRaw := range dslice(node, "clauses") {
		cl := node2map(clRaw)
		switch strings.ToUpper(dstr(cl, "action")) {
		case "UPDATE":
			for _, scRaw := range dslice(cl, "set_clauses") {
				sc := node2map(scRaw)
				if colNode := node2map(sc["column"]); colNode != nil && dstr(colNode, "node_type") == "IdentifierNode" {
					cs, ct, cn := resolveCol(colNode, am)
					so := cs
					if so == "" {
						so = schema
					}
					to := ct
					if to == "" {
						to = tbl
					}
					ie.add(intents, so, to, sp(cn), IntentUpdate)
				}
				ie.walkExpr(sc["expr"], am, IntentRead, intents, cteNames, derived)
			}
		case "INSERT":
			for _, cRaw := range dslice(cl, "insert_columns") {
				c := node2map(cRaw)
				if dstr(c, "node_type") == "IdentifierNode" {
					ie.add(intents, schema, tbl, sp(dstr(c, "name")), IntentInsert)
				}
			}
			for _, v := range dslice(cl, "insert_values") {
				ie.walkExpr(v, am, IntentRead, intents, cteNames, derived)
			}
		case "DELETE":
			ie.add(intents, schema, tbl, nil, IntentDelete)
		}
	}
}

// ── 運算式走訪 ──────────────────────────────────────────────────────────────

func (ie *IntentExtractor) walkExpr(exprRaw any, am *aliasMap, intentType string, intents *[]Intent, cteNames strSetT, derived strSetT) {
	if exprRaw == nil {
		return
	}
	if list, ok := exprRaw.([]any); ok {
		for _, x := range list {
			ie.walkExpr(x, am, intentType, intents, cteNames, derived)
		}
		return
	}
	expr := node2map(exprRaw)
	if expr == nil {
		return
	}
	switch dstr(expr, "node_type") {
	case "IdentifierNode":
		// 變數（@x）與 qmark 模式下顯示為 "?" 之位置參數都不是欄位，不產生意圖。
		if nm := dstr(expr, "name"); strings.HasPrefix(nm, "@") || nm == "?" {
			return
		}
		quals := strSlice(dslice(expr, "qualifiers"))
		if derived != nil && len(quals) == 1 && derived[quals[0]] {
			return
		}
		s, tbl, col := resolveCol(expr, am)
		if tbl != "" && !(s == "" && cteNames[strings.ToUpper(tbl)]) {
			ie.add(intents, s, tbl, sp(col), intentType)
		}
	case "BinaryExpressionNode":
		ie.walkExpr(expr["left"], am, intentType, intents, cteNames, nil)
		ie.walkExpr(expr["right"], am, intentType, intents, cteNames, nil)
	case "FunctionCallNode":
		for _, a := range dslice(expr, "args") {
			ie.walkExpr(a, am, intentType, intents, cteNames, nil)
		}
	case "CastExpressionNode":
		ie.walkExpr(expr["expr"], am, intentType, intents, cteNames, nil)
	case "BetweenExpressionNode":
		ie.walkExpr(expr["target"], am, intentType, intents, cteNames, nil)
		ie.walkExpr(expr["low"], am, intentType, intents, cteNames, nil)
		ie.walkExpr(expr["high"], am, intentType, intents, cteNames, nil)
	case "CaseExpressionNode":
		ie.walkExpr(expr["input"], am, intentType, intents, cteNames, nil)
		for _, brRaw := range dslice(expr, "branches") {
			br := node2map(brRaw)
			ie.walkExpr(br["when"], am, intentType, intents, cteNames, nil)
			ie.walkExpr(br["then"], am, intentType, intents, cteNames, nil)
		}
		ie.walkExpr(expr["else"], am, intentType, intents, cteNames, nil)
	case "SelectStatement", "UnionStatement":
		ie.walkSubquery(exprRaw, intents, cteNames, am)
	}
}

func (ie *IntentExtractor) walkSubquery(nodeRaw any, intents *[]Intent, cteNames strSetT, parentAlias *aliasMap) {
	if nodeRaw == nil {
		return
	}
	n := node2map(nodeRaw)
	switch dstr(n, "node_type") {
	case "SelectStatement":
		ie.walkSelect(n, intents, cteNames, parentAlias)
	case "UnionStatement":
		ie.walkSubquery(n["left"], intents, cteNames, parentAlias)
		ie.walkSubquery(n["right"], intents, cteNames, parentAlias)
	default:
		ie.walk(n, intents, cteNames)
	}
}

// ── alias map ──────────────────────────────────────────────────────────────

func (ie *IntentExtractor) buildAliasMap(selectNode map[string]any, cteNames strSetT, intents *[]Intent) (*aliasMap, strSetT) {
	am := newAliasMap()
	derived := strSetT{}

	register := func(tableNode map[string]any, alias string) {
		if tableNode == nil {
			return
		}
		nt := dstr(tableNode, "node_type")
		if nt == "SelectStatement" || nt == "UnionStatement" {
			if alias != "" {
				derived[alias] = true
			}
			if intents != nil {
				ie.walk(tableNode, intents, cteNames)
			}
			return
		}
		s, tbl := tableInfo(tableNode)
		if tbl == "" || cteNames[strings.ToUpper(tbl)] {
			return
		}
		am.set(tbl, schemaTable{s, tbl})
		if alias != "" {
			am.set(alias, schemaTable{s, tbl})
		}
	}

	register(dmap(selectNode, "table"), dstr(selectNode, "alias"))
	for _, j := range dslice(selectNode, "joins") {
		jm := node2map(j)
		register(dmap(jm, "table"), dstr(jm, "alias"))
	}
	return am, derived
}

// ── helpers ────────────────────────────────────────────────────────────────

func tableInfo(idNode map[string]any) (schema, table string) {
	if idNode == nil {
		return "", ""
	}
	quals := strSlice(dslice(idNode, "qualifiers"))
	name := dstr(idNode, "name")
	if len(quals) > 0 {
		return quals[0], name
	}
	return "", name
}

func resolveCol(idNode map[string]any, am *aliasMap) (schema, table, column string) {
	quals := strSlice(dslice(idNode, "qualifiers"))
	col := dstr(idNode, "name")

	if len(quals) >= 2 {
		return quals[0], quals[1], col
	}
	if len(quals) == 1 {
		q := quals[0]
		if st, ok := am.get(q); ok {
			return st.schema, st.table, col
		}
		qUp := strings.ToUpper(q)
		for _, key := range am.order {
			if strings.ToUpper(key) == qUp {
				st := am.m[key]
				return st.schema, st.table, col
			}
		}
		return "", q, col
	}
	if resolved := dstr(idNode, "resolved_table"); resolved != "" {
		rUp := strings.ToUpper(resolved)
		for _, key := range am.order {
			st := am.m[key]
			if strings.ToUpper(st.table) == rUp {
				return st.schema, st.table, col
			}
		}
		return "", resolved, col
	}
	if d := am.distinct(); len(d) == 1 {
		return d[0].schema, d[0].table, col
	}
	return "", "", col
}

// ── ExtractTables ──────────────────────────────────────────────────────────

// ExtractTables 對照 extract_tables：收集所有真實資料表引用 (schema, table)。
func (ie *IntentExtractor) ExtractTables(astDict any) [][2]string {
	set := map[[2]string]bool{}
	ie.collectTables(node2map(astDict), set, strSetT{})
	out := make([][2]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i][0] != out[j][0] {
			return out[i][0] < out[j][0]
		}
		return out[i][1] < out[j][1]
	})
	return out
}

func (ie *IntentExtractor) collectTables(node map[string]any, tables map[[2]string]bool, cteNames strSetT) {
	if node == nil {
		return
	}
	nt := dstr(node, "node_type")
	switch nt {
	case "SelectStatement":
		local := strSetT{}
		for k := range cteNames {
			local[k] = true
		}
		for _, cRaw := range dslice(node, "ctes") {
			c := node2map(cRaw)
			local[strings.ToUpper(dstr(c, "name"))] = true
			ie.collectTables(node2map(c["query"]), tables, local)
		}
		if tm := dmap(node, "table"); tm != nil {
			if dstr(tm, "node_type") == "IdentifierNode" {
				s, tbl := tableInfo(tm)
				if tbl != "" && !local[strings.ToUpper(tbl)] {
					tables[[2]string{s, tbl}] = true
				}
			} else {
				ie.collectTables(tm, tables, local)
			}
		}
		for _, j := range dslice(node, "joins") {
			jt := dmap(node2map(j), "table")
			if jt != nil && dstr(jt, "node_type") == "IdentifierNode" {
				s, tbl := tableInfo(jt)
				if tbl != "" && !local[strings.ToUpper(tbl)] {
					tables[[2]string{s, tbl}] = true
				}
			}
		}
		ie.collectTables(dmap(node, "where"), tables, local)
		ie.collectTables(dmap(node, "having"), tables, local)
		for _, item := range dslice(node, "group_by") {
			ie.collectTables(node2map(item), tables, local)
		}
		for _, ob := range dslice(node, "order_by") {
			ie.collectTables(node2map(node2map(ob)["column"]), tables, local)
		}
		for _, ap := range dslice(node, "applies") {
			ie.collectTables(node2map(node2map(ap)["subquery"]), tables, local)
		}
		for _, col := range dslice(node, "columns") {
			ie.collectTables(node2map(col), tables, local)
		}
	case "ScriptNode":
		for _, s := range dslice(node, "statements") {
			ie.collectTables(node2map(s), tables, cteNames)
		}
	case "UnionStatement":
		ie.collectTables(dmap(node, "left"), tables, cteNames)
		ie.collectTables(dmap(node, "right"), tables, cteNames)
	case "UpdateStatement", "DeleteStatement", "TruncateStatement":
		t := dmap(node, "table")
		if t != nil && dstr(t, "node_type") == "IdentifierNode" {
			s, tbl := tableInfo(t)
			if tbl != "" && !cteNames[strings.ToUpper(tbl)] {
				tables[[2]string{s, tbl}] = true
			}
		}
		ie.collectTables(dmap(node, "where"), tables, cteNames)
		for _, asgn := range dslice(node, "set") {
			ie.collectTables(node2map(node2map(asgn)["expr"]), tables, cteNames)
		}
	case "InsertStatement":
		t := dmap(node, "table")
		if t != nil && dstr(t, "node_type") == "IdentifierNode" {
			s, tbl := tableInfo(t)
			if tbl != "" && !cteNames[strings.ToUpper(tbl)] {
				tables[[2]string{s, tbl}] = true
			}
		}
		if src := node["source"]; src != nil {
			ie.collectTables(node2map(src), tables, cteNames)
		}
	case "IfStatement":
		ie.collectTables(dmap(node, "condition"), tables, cteNames)
		for _, k := range []string{"then_block", "else_block"} {
			for _, st := range dslice(node, k) {
				ie.collectTables(node2map(st), tables, cteNames)
			}
		}
	case "MergeStatement":
		for _, k := range []string{"target", "source"} {
			m := dmap(node, k)
			if m == nil {
				continue
			}
			if dstr(m, "node_type") == "IdentifierNode" {
				s, tbl := tableInfo(m)
				if tbl != "" && !cteNames[strings.ToUpper(tbl)] {
					tables[[2]string{s, tbl}] = true
				}
			} else {
				ie.collectTables(m, tables, cteNames)
			}
		}
		ie.collectTables(dmap(node, "on_condition"), tables, cteNames)
	case "BinaryExpressionNode":
		ie.collectTables(dmap(node, "left"), tables, cteNames)
		ie.collectTables(dmap(node, "right"), tables, cteNames)
	case "FunctionCallNode":
		for _, a := range dslice(node, "args") {
			ie.collectTables(node2map(a), tables, cteNames)
		}
	case "CastExpressionNode":
		ie.collectTables(dmap(node, "expr"), tables, cteNames)
	case "BetweenExpressionNode":
		for _, k := range []string{"target", "low", "high"} {
			ie.collectTables(dmap(node, k), tables, cteNames)
		}
	case "CaseExpressionNode":
		ie.collectTables(dmap(node, "input"), tables, cteNames)
		for _, brRaw := range dslice(node, "branches") {
			br := node2map(brRaw)
			ie.collectTables(node2map(br["when"]), tables, cteNames)
			ie.collectTables(node2map(br["then"]), tables, cteNames)
		}
		ie.collectTables(dmap(node, "else"), tables, cteNames)
	}
}

// ── ExpandStarIntents ──────────────────────────────────────────────────────

// ExpandStarIntents 對照 expand_star_intents：把 column=nil 的 READ intent 展開成逐欄。
func (ie *IntentExtractor) ExpandStarIntents(intents []Intent, reg *MetadataRegistry) []Intent {
	var result []Intent
	for _, it := range intents {
		if it.Column == nil && it.Intent == IntentRead {
			cols := reg.GetColumns(it.Table)
			if len(cols) > 0 {
				for _, c := range cols {
					c := c
					result = append(result, Intent{Schema: it.Schema, Table: it.Table, Column: &c, Intent: IntentRead})
				}
			} else {
				result = append(result, it)
			}
		} else {
			result = append(result, it)
		}
	}
	return result
}
