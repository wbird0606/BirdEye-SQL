package birdeye

import (
	"fmt"
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
		ri.injectSelect(node, rf)
	case "InsertStatement":
		// 目標表之「寫入」不加 WHERE（列過濾為可見範圍，非寫入驗證）；僅過濾「讀取」來源。
		if src := node["source"]; src != nil {
			ri.walk(src, rf)
		}
		ri.walkExpr(node["values"], rf)
		for _, row := range dslice(node, "value_rows") {
			ri.walkExpr(row, rf)
		}
	case "MergeStatement":
		ri.injectMerge(node, rf)
	case "UpdateStatement", "DeleteStatement":
		// WHERE／SET 內之子查詢讀取其他（或同一）資料表，須先各自過濾
		ri.walkExpr(node["where"], rf)
		for _, a := range dslice(node, "set") {
			if am := node2map(a); am != nil {
				ri.walkExpr(firstVal(am, "expr", "right", "expression"), rf)
			}
		}
		if dmap(node, "from_table") != nil {
			ri.injectDMLFrom(node, rf)
			return
		}
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

// injectDMLFrom 處理 UPDATE／DELETE ... FROM：
//   - FROM 來源與 JOIN 之每個資料表（含自我 JOIN 之每個別名）皆套用列過濾，規則同 SELECT；
//   - 寫入目標若為 FROM 清單內之別名（或未加別名之資料表名），即為該 FROM 項目本身，過濾以 WHERE 表達；
//     否則目標為獨立資料表，另以其表名為限定詞注入 WHERE 條件；
//   - FROM 內之衍生資料表與 ON 條件中之子查詢先各自過濾。
func (ri *RowFilterInjector) injectDMLFrom(node map[string]any, rf []RowFilter) {
	adapter := map[string]any{"table": node["from_table"], "alias": node["from_alias"], "joins": node["from_joins"]}
	ri.walkSubqueriesInSelect(adapter, rf) // 含 JOIN 衍生資料表與 ON 條件內之子查詢

	targetQual := ""
	if t := dmap(node, "table"); t != nil && len(strSlice(dslice(t, "qualifiers"))) == 0 {
		name := dstr(t, "name")
		for _, e := range buildAliasEntries(adapter) {
			if strings.EqualFold(e.qualifier, name) {
				targetQual = e.qualifier
				break
			}
		}
	}

	adapter["where"] = node["where"]
	ri.injectFrom(adapter, rf, targetQual)
	node["where"] = adapter["where"]
	node["from_table"] = adapter["table"]
	node["from_alias"] = adapter["alias"]

	if targetQual == "" { // 目標為獨立資料表
		entries := buildAliasEntriesDML(node)
		if applicable := matchFilters(entries, rf); len(applicable) > 0 {
			var conds []any
			for _, f := range applicable {
				conds = append(conds, makeCondition(f, entries))
			}
			node["where"] = andConditions(node["where"], conds)
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
		// ON 條件中之子查詢同樣讀取資料，須各自過濾（KNOWN_DEVIATIONS A17）
		ri.walkExpr(node2map(j)["on"], rf)
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

// ── SELECT 注入（含外部 JOIN 與自我 JOIN）─────────────────────────────────────

type fromItem struct {
	holder   map[string]any // 持有 "table"／"alias" 之節點：SELECT 本身（基底表）或某個 join
	entry    *aliasEntry    // 僅當 table 為資料表識別字時非 nil
	rawName  string
	nullable bool  // 外部 JOIN 中可為 NULL 之一側
	conds    []any // 該項專屬（衍生資料表內）之過濾條件
}

// injectSelect 對單一 SELECT 之 FROM／JOIN 注入列過濾：
//   - 一般（非 NULL 側）資料表：條件以 AND 併入 WHERE（與既有行為一致）；
//   - 外部 JOIN 之可為 NULL 側：改以 (SELECT * FROM T WHERE 條件) AS 別名 取代該資料表，
//     否則 WHERE 會剔除保留列，使外部 JOIN 退化為內部 JOIN（FULL JOIN 時亦會漏出應被過濾之列）；
//   - 同一資料表出現多個別名（自我 JOIN）時，每個別名皆套用過濾。
func (ri *RowFilterInjector) injectSelect(node map[string]any, rf []RowFilter) {
	ri.injectFrom(node, rf, "")
}

// injectFrom 為 injectSelect 之實作。targetQual 非空時，表示該限定詞（別名或表名）為
// UPDATE／DELETE 之寫入目標：目標不能被衍生資料表取代，其過濾一律以 WHERE 條件表達
// （不論其是否位於外部 JOIN 之可為 NULL 側；NULL 側之列本即不會被更新或刪除）。
func (ri *RowFilterInjector) injectFrom(node map[string]any, rf []RowFilter, targetQual string) {
	var items []*fromItem
	reg := func(holder map[string]any) {
		it := &fromItem{holder: holder}
		if tbl := dmap(holder, "table"); tbl != nil && dstr(tbl, "node_type") == "IdentifierNode" {
			quals := strSlice(dslice(tbl, "qualifiers"))
			name := dstr(tbl, "name")
			if name != "" {
				schema := ""
				if len(quals) > 0 {
					schema = quals[0]
				}
				q := dstr(holder, "alias")
				if q == "" {
					q = name
				}
				it.entry = &aliasEntry{strings.ToUpper(schema), strings.ToUpper(name), q}
				it.rawName = name
			}
		}
		if holder["pivot"] != nil {
			// PIVOT／UNPIVOT 之來源：WHERE 作用於轉置後之輸出，無法限縮來源列，
			// 故一律改以過濾後衍生資料表取代來源（與外部 JOIN 之可為 NULL 側相同之處理）。
			it.nullable = true
		}
		items = append(items, it)
	}
	reg(node)
	joins := dslice(node, "joins")
	for _, j := range joins {
		reg(node2map(j))
	}
	for k, j := range joins {
		jt := strings.ToUpper(firstStr(node2map(j), "join_type", "type"))
		at := k + 1
		switch {
		case strings.Contains(jt, "LEFT"):
			items[at].nullable = true
		case strings.Contains(jt, "RIGHT"):
			for p := 0; p < at; p++ {
				items[p].nullable = true
			}
		case strings.Contains(jt, "FULL"):
			for p := 0; p <= at; p++ {
				items[p].nullable = true
			}
		}
	}

	if targetQual != "" {
		for _, it := range items {
			if it.entry != nil && strings.EqualFold(it.entry.qualifier, targetQual) {
				it.nullable = false
			}
		}
	}

	var whereConds []any
	for _, f := range rf { // 以過濾條件為主序，維持既有輸出順序
		sUp, tUp := strings.ToUpper(f.Schema), strings.ToUpper(f.Table)
		for _, it := range items {
			e := it.entry
			if e == nil || e.table != tUp || (sUp != "" && e.schema != sUp) {
				continue
			}
			if it.nullable {
				inner := aliasEntry{e.schema, e.table, it.rawName}
				it.conds = append(it.conds, makeCondition(f, []aliasEntry{inner}))
			} else {
				whereConds = append(whereConds, makeCondition(f, []aliasEntry{*e}))
			}
		}
	}
	for _, it := range items {
		if len(it.conds) == 0 {
			continue
		}
		it.holder["table"] = newFilteredDerived(it.holder["table"], it.conds)
		if dstr(it.holder, "alias") == "" {
			it.holder["alias"] = it.rawName // 外層對該資料表之限定詞（表名）仍可解析
		}
	}
	if len(whereConds) > 0 {
		node["where"] = andConditions(node["where"], whereConds)
	}
}

// newFilteredDerived 建立 (SELECT * FROM T WHERE 條件) 衍生資料表節點。
// 欄位集合與解析器／序列化器對 SELECT 節點之輸出一致（由 rewrite_dml_test.go 之結構測試鎖定），
// 以免注入之節點與真實 AST 形狀偏離。
func newFilteredDerived(table any, conds []any) map[string]any {
	return map[string]any{
		"node_type": "SelectStatement", "ctes": []any{}, "top": nil, "top_percent": false,
		"is_distinct": false, "is_star": true, "columns": []any{},
		"table": table, "alias": nil, "joins": []any{}, "applies": []any{},
		"into_table": nil, "where": andConditions(nil, conds), "group_by": []any{},
		"having": nil, "order_by": []any{}, "offset_count": nil, "fetch_count": nil,
	}
}

// filterMatchesTable：列過濾是否適用於 (schema, table)。
func filterMatchesTable(f RowFilter, schema, table string) bool {
	sUp := strings.ToUpper(f.Schema)
	return strings.ToUpper(f.Table) == strings.ToUpper(table) && (sUp == "" || strings.ToUpper(schema) == sUp)
}

// injectMerge：
//   - 來源為資料表 → 改以過濾後衍生資料表取代；來源為子查詢 → 遞迴過濾其內部；
//   - 目標表：T-SQL 之 MERGE 目標不可為衍生資料表，無法以替換方式過濾，
//     故當目標表有適用之列過濾時 Fail-Closed 拒絕，而非產生語意不完整之改寫。
func (ri *RowFilterInjector) injectMerge(node map[string]any, rf []RowFilter) {
	if t := dmap(node, "target"); t != nil && dstr(t, "node_type") == "IdentifierNode" {
		s, name := tableInfo(t)
		for _, f := range rf {
			if filterMatchesTable(f, s, name) {
				panic(fmt.Errorf("MERGE 目標表 %s 具有列過濾條件，本代理不支援（Fail-Closed）", name))
			}
		}
	}
	if src := dmap(node, "source"); src != nil {
		switch dstr(src, "node_type") {
		case "SelectStatement", "UnionStatement":
			ri.walk(src, rf)
		case "IdentifierNode":
			s, name := tableInfo(src)
			var conds []any
			for _, f := range rf {
				if filterMatchesTable(f, s, name) {
					conds = append(conds, makeCondition(f, []aliasEntry{{strings.ToUpper(s), strings.ToUpper(name), name}}))
				}
			}
			if len(conds) > 0 {
				node["source"] = newFilteredDerived(src, conds)
				if dstr(node, "source_alias") == "" {
					node["source_alias"] = name
				}
			}
		}
	}
	ri.walkExpr(node["on_condition"], rf)
	for _, clRaw := range dslice(node, "clauses") {
		cl := node2map(clRaw)
		ri.walkExpr(cl["condition"], rf)
		for _, a := range dslice(cl, "set_clauses") {
			if am := node2map(a); am != nil {
				ri.walkExpr(firstVal(am, "expr", "right", "expression"), rf)
			}
		}
		for _, v := range dslice(cl, "insert_values") {
			ri.walkExpr(v, rf)
		}
	}
}
