package birdeye

import (
	"encoding/json"
	"strings"
)

// Reconstructor 對照 Python birdeye/reconstructor.py 的 ASTReconstructor：
// 把 serializer 輸出的 AST JSON 轉回可執行 SQL。輸入為 JSON 字串（與 Python
// from_json_str 相同），確保 byte-parity 與 Phase 2 的 /rewrite 端點相容。
type Reconstructor struct {
	paramInputMode string
}

func NewReconstructor() *Reconstructor { return &Reconstructor{} }

// Reconstruct 對照 from_json_str。
func (rc *Reconstructor) Reconstruct(astJSON string) (string, error) {
	var v any
	if err := json.Unmarshal([]byte(astJSON), &v); err != nil {
		return "", valueErr("reconstruct: invalid JSON: " + err.Error())
	}
	return rc.toSQL(node2map(v)), nil
}

// ReconstructValue 對照 to_sql(dict)：直接吃已解析的值。
func (rc *Reconstructor) ReconstructValue(v any) string {
	return rc.toSQL(node2map(v))
}

func node2map(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func (rc *Reconstructor) toSQL(n map[string]any) string {
	if n == nil {
		return ""
	}
	if pim, ok := n["param_input_mode"].(string); ok {
		rc.paramInputMode = pim
	}
	nt, _ := n["node_type"].(string)
	switch nt {
	case "ScriptNode":
		return rc.sqlScript(n)
	case "SelectStatement":
		return rc.sqlSelect(n)
	case "UnionStatement":
		return rc.sqlUnion(n)
	case "UpdateStatement":
		return rc.sqlUpdate(n)
	case "DeleteStatement":
		return rc.sqlDelete(n)
	case "InsertStatement":
		return rc.sqlInsert(n)
	case "TruncateStatement":
		return "TRUNCATE TABLE " + rc.toSQL(dmap(n, "table"))
	case "DeclareStatement":
		return rc.sqlDeclare(n)
	case "IfStatement":
		return rc.sqlIf(n)
	case "ExecStatement":
		return rc.sqlExec(n)
	case "SetStatement":
		return rc.sqlSet(n)
	case "CreateTableStatement":
		return rc.sqlCreateTable(n)
	case "DropTableStatement":
		return rc.sqlDropTable(n)
	case "AlterTableStatement":
		return rc.sqlAlterTable(n)
	case "MergeStatement":
		return rc.sqlMerge(n)
	case "PrintStatement":
		return rc.sqlPrint(n)
	case "IdentifierNode":
		return rc.sqlIdentifier(n)
	}
	return ""
}

// ── dict helpers ────────────────────────────────────────────────────────────

func dmap(n map[string]any, k string) map[string]any {
	m, _ := n[k].(map[string]any)
	return m
}
func dslice(n map[string]any, k string) []any {
	s, _ := n[k].([]any)
	return s
}
func dstr(n map[string]any, k string) string {
	s, _ := n[k].(string)
	return s
}
func dbool(n map[string]any, k string) bool {
	b, _ := n[k].(bool)
	return b
}
func dnum(n map[string]any, k string) (float64, bool) {
	f, ok := n[k].(float64)
	return f, ok
}
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	case float64:
		return x != 0
	}
	return true
}

// ── 語句 ────────────────────────────────────────────────────────────────────

func (rc *Reconstructor) sqlScript(n map[string]any) string {
	var parts []string
	for _, s := range dslice(n, "statements") {
		parts = append(parts, rc.toSQL(node2map(s)))
	}
	return strings.Join(parts, ";\n")
}

func (rc *Reconstructor) sqlSelect(n map[string]any) string {
	var parts []string
	if ctes := dslice(n, "ctes"); len(ctes) > 0 {
		var cp []string
		for _, c := range ctes {
			cm := node2map(c)
			cp = append(cp, dstr(cm, "name")+" AS ("+rc.toSQL(dmap(cm, "query"))+")")
		}
		parts = append(parts, "WITH "+strings.Join(cp, ", "))
	}

	sel := "SELECT"
	if dbool(n, "is_distinct") {
		sel += " DISTINCT"
	}
	if top, ok := dnum(n, "top"); ok {
		sel += " TOP " + itoa(int(top))
		if dbool(n, "top_percent") {
			sel += " PERCENT"
		}
	}
	parts = append(parts, sel)

	if dbool(n, "is_star") {
		parts = append(parts, "*")
	} else {
		var cs []string
		for _, c := range dslice(n, "columns") {
			cs = append(cs, rc.sqlExpr(c))
		}
		parts = append(parts, strings.Join(cs, ", "))
	}

	if into := dmap(n, "into_table"); into != nil {
		parts = append(parts, "INTO "+rc.toSQL(into))
	}

	if tbl := n["table"]; truthy(tbl) {
		parts = append(parts, "FROM")
		parts = append(parts, rc.sqlTableRef(node2map(tbl), dstr(n, "alias")))
	}

	for _, j := range dslice(n, "joins") {
		parts = append(parts, rc.sqlJoin(node2map(j)))
	}
	for _, ap := range dslice(n, "applies") {
		parts = append(parts, rc.sqlApply(node2map(ap)))
	}
	if w := n["where"]; truthy(w) {
		parts = append(parts, "WHERE "+rc.sqlExpr(w))
	}
	if g := dslice(n, "group_by"); len(g) > 0 {
		var gs []string
		for _, x := range g {
			gs = append(gs, rc.sqlExpr(x))
		}
		parts = append(parts, "GROUP BY "+strings.Join(gs, ", "))
	}
	if h := n["having"]; truthy(h) {
		parts = append(parts, "HAVING "+rc.sqlExpr(h))
	}
	if o := dslice(n, "order_by"); len(o) > 0 {
		var os []string
		for _, x := range o {
			os = append(os, rc.sqlOrderBy(node2map(x)))
		}
		parts = append(parts, "ORDER BY "+strings.Join(os, ", "))
	}
	if off, ok := dnum(n, "offset_count"); ok {
		parts = append(parts, "OFFSET "+itoa(int(off))+" ROWS")
		if f, ok := dnum(n, "fetch_count"); ok {
			parts = append(parts, "FETCH NEXT "+itoa(int(f))+" ROWS ONLY")
		}
	}
	return strings.Join(parts, " ")
}

func (rc *Reconstructor) sqlUnion(n map[string]any) string {
	op := dstr(n, "op")
	if op == "" {
		op = "UNION"
	}
	return rc.toSQL(dmap(n, "left")) + " " + op + " " + rc.toSQL(dmap(n, "right"))
}

func (rc *Reconstructor) sqlUpdate(n map[string]any) string {
	var parts []string
	if ctes := dslice(n, "ctes"); len(ctes) > 0 {
		var cp []string
		for _, c := range ctes {
			cm := node2map(c)
			cp = append(cp, dstr(cm, "name")+" AS ("+rc.toSQL(dmap(cm, "query"))+")")
		}
		parts = append(parts, "WITH "+strings.Join(cp, ", "))
	}
	tbl := rc.sqlTableRef(dmap(n, "table"), dstr(n, "alias"))
	var sets []string
	for _, s := range firstSlice(n, "set", "set_clauses") {
		sets = append(sets, rc.sqlAssignment(node2map(s)))
	}
	parts = append(parts, "UPDATE "+tbl+" SET "+strings.Join(sets, ", "))
	if w := firstVal(n, "where_condition", "where"); truthy(w) {
		parts = append(parts, "WHERE "+rc.sqlExpr(w))
	}
	return strings.Join(parts, " ")
}

func (rc *Reconstructor) sqlDelete(n map[string]any) string {
	var parts []string
	if ctes := dslice(n, "ctes"); len(ctes) > 0 {
		var cp []string
		for _, c := range ctes {
			cm := node2map(c)
			cp = append(cp, dstr(cm, "name")+" AS ("+rc.toSQL(dmap(cm, "query"))+")")
		}
		parts = append(parts, "WITH "+strings.Join(cp, ", "))
	}
	parts = append(parts, "DELETE FROM "+rc.sqlTableRef(dmap(n, "table"), dstr(n, "alias")))
	if w := firstVal(n, "where_condition", "where"); truthy(w) {
		parts = append(parts, "WHERE "+rc.sqlExpr(w))
	}
	return strings.Join(parts, " ")
}

func (rc *Reconstructor) sqlInsert(n map[string]any) string {
	tbl := rc.toSQL(dmap(n, "table"))
	cols := dslice(n, "columns")
	colList := ""
	if len(cols) > 0 {
		var cs []string
		for _, c := range cols {
			cs = append(cs, rc.toSQL(node2map(c)))
		}
		colList = " (" + strings.Join(cs, ", ") + ")"
	}
	if src := n["source"]; truthy(src) {
		return "INSERT INTO " + tbl + colList + " " + rc.toSQL(node2map(src))
	}
	rows := dslice(n, "value_rows")
	if len(rows) == 0 {
		if single := dslice(n, "values"); len(single) > 0 {
			rows = []any{any(single)}
		}
	}
	var rowSQL []string
	for _, row := range rows {
		var vs []string
		for _, v := range row.([]any) {
			vs = append(vs, rc.sqlExpr(v))
		}
		rowSQL = append(rowSQL, "("+strings.Join(vs, ", ")+")")
	}
	return "INSERT INTO " + tbl + colList + " VALUES " + strings.Join(rowSQL, ", ")
}

func (rc *Reconstructor) sqlDeclare(n map[string]any) string {
	sql := "DECLARE " + dstr(n, "var_name") + " " + dstr(n, "var_type")
	if dv := n["default_value"]; truthy(dv) {
		sql += " = " + rc.sqlExpr(dv)
	}
	return sql
}

func (rc *Reconstructor) sqlIf(n map[string]any) string {
	cond := "1=1"
	if c := n["condition"]; truthy(c) {
		cond = rc.sqlExpr(c)
	}
	var thenParts []string
	for _, s := range dslice(n, "then_block") {
		thenParts = append(thenParts, rc.toSQL(node2map(s)))
	}
	parts := []string{"IF " + cond, "BEGIN " + strings.Join(thenParts, " ") + " END"}
	if els := dslice(n, "else_block"); len(els) > 0 {
		var elseParts []string
		for _, s := range els {
			elseParts = append(elseParts, rc.toSQL(node2map(s)))
		}
		parts = append(parts, "ELSE", "BEGIN "+strings.Join(elseParts, " ")+" END")
	}
	return strings.Join(parts, " ")
}

func (rc *Reconstructor) sqlExec(n map[string]any) string {
	proc := ""
	if pm := dmap(n, "proc_name"); pm != nil {
		proc = rc.toSQL(pm)
	} else if s, ok := n["proc_name"].(string); ok {
		proc = s
	}
	var argParts []string
	for _, a := range dslice(n, "args") {
		argParts = append(argParts, rc.sqlExpr(a))
	}
	// Python bug（KNOWN_DEVIATIONS A2）：讀 na['name'] / na['value']，但 serializer
	// 對 named_args（AssignmentNode）存的是 column / expr → KeyError。忠實複製：
	for _, na := range dslice(n, "named_args") {
		nm := node2map(na)
		if nm == nil {
			continue
		}
		name, hasName := nm["name"]
		val, hasVal := nm["value"]
		if !hasName || !hasVal {
			panic(engineBail{&Error{ErrSystem, "'name'"}}) // 對照 Python KeyError
		}
		argParts = append(argParts, str(name)+" = "+rc.sqlExpr(val))
	}
	retSQL := ""
	if rm := dmap(n, "return_var"); rm != nil {
		retSQL = rc.toSQL(rm) + " = "
	} else if s, ok := n["return_var"].(string); ok && s != "" {
		retSQL = s + " = "
	}
	return strings.TrimSpace("EXEC " + retSQL + proc + " " + strings.Join(argParts, ", "))
}

func (rc *Reconstructor) sqlSet(n map[string]any) string {
	if dbool(n, "is_option") {
		target := strOrExpr(rc, n["target"])
		value := strOrExpr(rc, n["value"])
		return "SET " + target + " " + value
	}
	target := ""
	if t := n["target"]; truthy(t) {
		target = rc.sqlExpr(t)
	}
	value := "NULL"
	if v := n["value"]; truthy(v) {
		value = rc.sqlExpr(v)
	}
	return "SET " + target + " = " + value
}

func (rc *Reconstructor) sqlCreateTable(n map[string]any) string {
	tbl := rc.toSQL(dmap(n, "table"))
	ifNot := ""
	if dbool(n, "if_not_exists") {
		ifNot = "IF NOT EXISTS "
	}
	var defs []string
	for _, c := range dslice(n, "columns") {
		defs = append(defs, rc.sqlColumnDef(node2map(c)))
	}
	return "CREATE TABLE " + ifNot + tbl + " (" + strings.Join(defs, ", ") + ")"
}

func (rc *Reconstructor) sqlColumnDef(n map[string]any) string {
	parts := []string{dstr(n, "name"), dstr(n, "data_type")}
	if dbool(n, "is_identity") {
		parts = append(parts, "IDENTITY")
	}
	if v, ok := n["nullable"].(bool); ok && !v {
		parts = append(parts, "NOT NULL")
	}
	if dbool(n, "is_primary_key") {
		parts = append(parts, "PRIMARY KEY")
	}
	if d := n["default"]; truthy(d) {
		parts = append(parts, "DEFAULT "+rc.sqlExpr(d))
	}
	return strings.Join(parts, " ")
}

func (rc *Reconstructor) sqlDropTable(n map[string]any) string {
	tbl := rc.toSQL(dmap(n, "table"))
	ifEx := ""
	if dbool(n, "if_exists") {
		ifEx = "IF EXISTS "
	}
	return "DROP TABLE " + ifEx + tbl
}

func (rc *Reconstructor) sqlAlterTable(n map[string]any) string {
	tbl := rc.toSQL(dmap(n, "table"))
	action := dstr(n, "action")
	colSQL := ""
	if col := dmap(n, "column"); col != nil {
		colSQL = " " + rc.sqlColumnDef(col)
	}
	return "ALTER TABLE " + tbl + " " + action + colSQL
}

func (rc *Reconstructor) sqlMerge(n map[string]any) string {
	target := rc.sqlTableRef(dmap(n, "target"), dstr(n, "target_alias"))
	source := rc.sqlTableRef(dmap(n, "source"), dstr(n, "source_alias"))
	on := "1=1"
	if o := n["on_condition"]; truthy(o) {
		on = rc.sqlExpr(o)
	}
	parts := []string{"MERGE INTO " + target, "USING " + source, "ON " + on}
	for _, c := range dslice(n, "clauses") {
		parts = append(parts, rc.sqlMergeClause(node2map(c)))
	}
	return strings.Join(parts, " ") + ";"
}

func (rc *Reconstructor) sqlMergeClause(n map[string]any) string {
	mt := dstr(n, "match_type")
	if mt == "" {
		mt = "MATCHED"
	}
	condSQL := ""
	if c := n["condition"]; truthy(c) {
		condSQL = " AND " + rc.sqlExpr(c)
	}
	action := dstr(n, "action")
	if action == "" {
		action = "UPDATE"
	}
	switch action {
	case "UPDATE":
		var sets []string
		for _, s := range dslice(n, "set_clauses") {
			sets = append(sets, rc.sqlAssignment(node2map(s)))
		}
		return "WHEN " + mt + condSQL + " THEN UPDATE SET " + strings.Join(sets, ", ")
	case "INSERT":
		cols := dslice(n, "insert_columns")
		colsSQL := ""
		if len(cols) > 0 {
			var cs []string
			for _, c := range cols {
				cs = append(cs, rc.toSQL(node2map(c)))
			}
			colsSQL = "(" + strings.Join(cs, ", ") + ")"
		}
		var vs []string
		for _, v := range dslice(n, "insert_values") {
			vs = append(vs, rc.sqlExpr(v))
		}
		return "WHEN " + mt + condSQL + " THEN INSERT " + colsSQL + " VALUES (" + strings.Join(vs, ", ") + ")"
	case "DELETE":
		return "WHEN " + mt + condSQL + " THEN DELETE"
	}
	return "WHEN " + mt + condSQL + " THEN " + action
}

func (rc *Reconstructor) sqlPrint(n map[string]any) string {
	expr := ""
	if e := n["expr"]; truthy(e) {
		expr = rc.sqlExpr(e)
	}
	return "PRINT " + expr
}

// ── 表達式 ──────────────────────────────────────────────────────────────────

func (rc *Reconstructor) sqlExpr(node any) string {
	if node == nil {
		return "NULL"
	}
	if list, ok := node.([]any); ok {
		var xs []string
		for _, x := range list {
			xs = append(xs, rc.sqlExpr(x))
		}
		return "(" + strings.Join(xs, ", ") + ")"
	}
	n := node2map(node)
	if n == nil {
		return ""
	}
	nt := dstr(n, "node_type")
	var sql string
	switch nt {
	case "IdentifierNode":
		sql = rc.sqlIdentifier(n)
	case "LiteralNode":
		sql = rc.sqlLiteral(n)
	case "BinaryExpressionNode":
		sql = rc.sqlBinary(n)
	case "FunctionCallNode":
		sql = rc.sqlFunctionCall(n)
	case "CaseExpressionNode":
		sql = rc.sqlCase(n)
	case "BetweenExpressionNode":
		sql = rc.sqlBetween(n)
	case "CastExpressionNode":
		sql = rc.sqlCast(n)
	default:
		sql = rc.toSQL(n)
	}
	if alias := dstr(n, "alias"); alias != "" {
		sql += " AS " + alias
	}
	return sql
}

func (rc *Reconstructor) sqlIdentifier(n map[string]any) string {
	name := dstr(n, "name")
	if rc.paramInputMode == "qmark" && isPositionalParam(name) {
		name = "?"
	}
	parts := append(strSlice(dslice(n, "qualifiers")), name)
	return strings.Join(parts, ".")
}

func (rc *Reconstructor) sqlLiteral(n map[string]any) string {
	v := dstr(n, "value")
	t := dstr(n, "type")
	if t == "STRING_LITERAL" {
		if !(strings.HasPrefix(v, "'") && strings.HasSuffix(v, "'")) {
			v = "'" + v + "'"
		}
	}
	return v
}

func (rc *Reconstructor) sqlBinary(n map[string]any) string {
	op := dstr(n, "op")
	if op == "" {
		op = dstr(n, "operator")
	}
	left := rc.sqlExpr(n["left"])
	rightRaw := n["right"]

	if op == "IS NULL" || op == "IS NOT NULL" {
		return left + " " + op
	}
	if op == "IN" || op == "NOT IN" {
		if list, ok := rightRaw.([]any); ok {
			var xs []string
			for _, x := range list {
				xs = append(xs, rc.sqlExpr(x))
			}
			return left + " " + op + " (" + strings.Join(xs, ", ") + ")"
		}
		return left + " " + op + " (" + rc.sqlExpr(rightRaw) + ")"
	}
	right := rc.sqlExpr(rightRaw)
	if rm := node2map(rightRaw); rm != nil {
		if nt := dstr(rm, "node_type"); nt == "SelectStatement" || nt == "UnionStatement" {
			right = "(" + right + ")"
		}
	}
	if op == "AND" || op == "OR" {
		return "(" + left + " " + op + " " + right + ")"
	}
	return left + " " + op + " " + right
}

func (rc *Reconstructor) sqlFunctionCall(n map[string]any) string {
	name := dstr(n, "name")
	args := dslice(n, "args")
	if name == "EXISTS" || name == "NOT EXISTS" {
		inner := ""
		if len(args) > 0 {
			inner = rc.sqlExpr(args[0])
		}
		return name + " (" + inner + ")"
	}
	var as []string
	for _, a := range args {
		as = append(as, rc.sqlExpr(a))
	}
	sql := name + "(" + strings.Join(as, ", ") + ")"
	if over := dmap(n, "over"); over != nil {
		sql += " " + rc.sqlOverClause(over)
	}
	return sql
}

func (rc *Reconstructor) sqlCase(n map[string]any) string {
	parts := []string{"CASE"}
	if inp := firstVal(n, "input", "input_expr"); truthy(inp) {
		parts = append(parts, rc.sqlExpr(inp))
	}
	for _, br := range dslice(n, "branches") {
		bm := node2map(br)
		parts = append(parts, "WHEN "+rc.sqlExpr(bm["when"])+" THEN "+rc.sqlExpr(bm["then"]))
	}
	if els := firstVal(n, "else", "else_expr"); truthy(els) {
		parts = append(parts, "ELSE "+rc.sqlExpr(els))
	}
	parts = append(parts, "END")
	return strings.Join(parts, " ")
}

func (rc *Reconstructor) sqlBetween(n map[string]any) string {
	expr := rc.sqlExpr(firstVal(n, "target", "expr"))
	low := rc.sqlExpr(n["low"])
	high := rc.sqlExpr(n["high"])
	notStr := ""
	if dbool(n, "is_not") {
		notStr = "NOT "
	}
	return expr + " " + notStr + "BETWEEN " + low + " AND " + high
}

func (rc *Reconstructor) sqlCast(n map[string]any) string {
	expr := rc.sqlExpr(n["expr"])
	target := firstStr(n, "target", "target_type")
	if dbool(n, "is_convert") {
		return "CONVERT(" + target + ", " + expr + ")"
	}
	return "CAST(" + expr + " AS " + target + ")"
}

func (rc *Reconstructor) sqlJoin(n map[string]any) string {
	jt := firstStr(n, "join_type", "type")
	if jt == "" {
		jt = "INNER"
	}
	var kw string
	switch jt {
	case "INNER":
		kw = "JOIN"
	case "CROSS":
		kw = "CROSS JOIN"
	case "FULL":
		kw = "FULL OUTER JOIN"
	default:
		kw = jt + " JOIN"
	}
	tbl := rc.sqlTableRef(dmap(n, "table"), dstr(n, "alias"))
	onSQL := ""
	if on := firstVal(n, "on", "on_condition"); truthy(on) {
		onSQL = " ON " + rc.sqlExpr(on)
	}
	return kw + " " + tbl + onSQL
}

func (rc *Reconstructor) sqlApply(n map[string]any) string {
	kw := dstr(n, "type") + " APPLY"
	if dstr(n, "type") == "" {
		kw = "CROSS APPLY"
	}
	subq := rc.toSQL(dmap(n, "subquery"))
	aliasSQL := ""
	if a := dstr(n, "alias"); a != "" {
		aliasSQL = " AS " + a
	}
	return kw + " (" + subq + ")" + aliasSQL
}

func (rc *Reconstructor) sqlAssignment(n map[string]any) string {
	col := rc.toSQL(dmap(n, "column"))
	val := rc.sqlExpr(firstVal(n, "expr", "right", "expression"))
	return col + " = " + val
}

func (rc *Reconstructor) sqlOrderBy(n map[string]any) string {
	col := rc.sqlExpr(n["column"])
	dir := dstr(n, "direction")
	if dir == "" {
		dir = "ASC"
	}
	return col + " " + dir
}

func (rc *Reconstructor) sqlOverClause(n map[string]any) string {
	var inner []string
	if pb := dslice(n, "partition_by"); len(pb) > 0 {
		var ps []string
		for _, p := range pb {
			ps = append(ps, rc.sqlExpr(p))
		}
		inner = append(inner, "PARTITION BY "+strings.Join(ps, ", "))
	}
	if ob := dslice(n, "order_by"); len(ob) > 0 {
		var os []string
		for _, o := range ob {
			os = append(os, rc.sqlOrderBy(node2map(o)))
		}
		inner = append(inner, "ORDER BY "+strings.Join(os, ", "))
	}
	if ft := dstr(n, "frame_type"); ft != "" {
		fp := ft
		if fs := dstr(n, "frame_start"); fs != "" {
			fp += " " + fs
		}
		if fe := dstr(n, "frame_end"); fe != "" {
			fp += " AND " + fe
		}
		inner = append(inner, fp)
	}
	if len(inner) > 0 {
		return "OVER (" + strings.Join(inner, " ") + ")"
	}
	return "OVER ()"
}

func (rc *Reconstructor) sqlTableRef(t map[string]any, alias string) string {
	if t == nil {
		return ""
	}
	nt := dstr(t, "node_type")
	aliasSQL := ""
	if alias != "" {
		aliasSQL = " AS " + alias
	}
	if nt == "SelectStatement" || nt == "UnionStatement" {
		return "(" + rc.toSQL(t) + ")" + aliasSQL
	}
	return rc.toSQL(t) + aliasSQL
}

// ── 小工具 ─────────────────────────────────────────────────────────────────

func firstVal(n map[string]any, keys ...string) any {
	for _, k := range keys {
		if v, ok := n[k]; ok && v != nil {
			return v
		}
	}
	return nil
}
func firstStr(n map[string]any, keys ...string) string {
	for _, k := range keys {
		if s, ok := n[k].(string); ok && s != "" {
			return s
		}
	}
	return ""
}
func firstSlice(n map[string]any, keys ...string) []any {
	for _, k := range keys {
		if s, ok := n[k].([]any); ok {
			return s
		}
	}
	return nil
}
func strOrExpr(rc *Reconstructor, v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	if v == nil {
		return ""
	}
	return rc.sqlExpr(v)
}
func strSlice(s []any) []string {
	out := make([]string, 0, len(s))
	for _, x := range s {
		out = append(out, str(x))
	}
	return out
}
func str(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
