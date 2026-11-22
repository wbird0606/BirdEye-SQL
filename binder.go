package birdeye

import (
	"math"
	"regexp"
	"strings"
)

// Binder 對照 Python birdeye/binder.py：語意分析（型別推導、名稱解析、ZTA 強制）。
// 遇語意錯誤以 panic(engineBail) 中止（對照 Python raise SemanticError）。
type Binder struct {
	registry *MetadataRegistry

	// allowedProcs 為允許呼叫之預存程序白名單（鍵為大寫之 "SCHEMA.NAME" 或 "NAME"）；
	// nil 表示一律不允許（預設拒絕）。
	allowedProcs map[string]bool

	scopes            []*scopeFrame // scope stack（保留插入順序）
	nullableStack     []map[string]bool
	lastRootNullables map[string]bool
	cteSchemas        map[string]*colSchema // CTE / 衍生資料表 alias(大寫) → schema
	variableScope     map[string]string     // @VAR(大寫) → type
	tempSchemas       map[string]*colSchema // #TABLE(大寫) → schema

	externalParams      map[string]string // @PARAM(大寫) → type
	externalParamValues map[string]any    // @PARAM(大寫) → 執行期值
	orderedParamNames   []string

	attachParamMeta bool
}

// ParamKV 是一組尚未正規化的外部參數。
type ParamKV struct {
	Name string
	Raw  any
}

// ParamInput 是依序的外部參數清單（nil = 無參數）。
type ParamInput struct{ Ordered []ParamKV }

func NewBinder(reg *MetadataRegistry) *Binder {
	return &Binder{
		registry:      reg,
		cteSchemas:    map[string]*colSchema{},
		variableScope: map[string]string{},
		tempSchemas:   map[string]*colSchema{},
	}
}

func (b *Binder) sem(msg string) { panic(engineBail{semanticErr(msg)}) }

var identifierPattern = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

// Bind 對照 bind()。就地標註 AST 並回傳根節點。
func (b *Binder) Bind(stmt Node, params *ParamInput) (out Node, err error) {
	defer func() {
		if r := recover(); r != nil {
			if be, ok := r.(engineBail); ok {
				out, err = nil, be.err
				return
			}
			out, err = nil, &Error{ErrSystem, panicMsg(r)}
		}
	}()

	b.scopes = nil
	b.nullableStack = nil
	b.lastRootNullables = map[string]bool{}
	b.cteSchemas = map[string]*colSchema{}
	b.attachParamMeta = true
	b.normalizeExternalParams(params)

	if len(b.externalParams) > 0 {
		if m := metaOf(stmt); m != nil {
			m.Params = b.buildParamBindings()
		}
	}

	if sc, ok := stmt.(*ScriptNode); ok {
		b.attachParamMeta = false
		for _, s := range sc.Statements {
			b.scopes = nil
			b.nullableStack = nil
			b.cteSchemas = map[string]*colSchema{}
			b.bindNode(s)
		}
		b.attachParamMeta = true
		return stmt, nil
	}
	b.bindNode(stmt)
	return stmt, nil
}

func (b *Binder) buildParamBindings() []ParamBinding {
	out := make([]ParamBinding, 0, len(b.orderedParamNames))
	for _, name := range b.orderedParamNames {
		out = append(out, ParamBinding{Name: name, Type: b.externalParams[name], Value: b.externalParamValues[name]})
	}
	return out
}

func (b *Binder) bindNode(stmt Node) Node {
	if b.attachParamMeta && len(b.externalParams) > 0 {
		if m := metaOf(stmt); m != nil {
			m.Params = b.buildParamBindings()
		}
	}
	switch s := stmt.(type) {
	case *SelectStatement:
		b.bindSelect(s)
	case *UnionStatement:
		b.bindUnion(s)
	case *UpdateStatement:
		b.bindUpdate(s)
	case *DeleteStatement:
		b.bindDelete(s)
	case *InsertStatement:
		b.bindInsert(s)
	case *TruncateStatement:
		b.bindTruncate(s)
	case *SqlBulkCopyStatement:
		b.bindBulkInsert(s)
	case *DeclareStatement:
		b.bindDeclare(s)
	case *IfStatement:
		b.bindIf(s)
	case *ExecStatement:
		b.bindExec(s)
	case *SetStatement:
		b.bindSet(s)
	case *CreateTableStatement:
		b.bindCreateTable(s)
	case *DropTableStatement, *AlterTableStatement:
		// 無需語意檢查
	case *MergeStatement:
		b.bindMerge(s)
	case *PrintStatement:
		b.bindPrint(s)
	}
	return stmt
}

// ── 參數正規化 ──────────────────────────────────────────────────────────────

func (b *Binder) normalizeExternalParams(params *ParamInput) {
	b.externalParams = map[string]string{}
	b.externalParamValues = map[string]any{}
	b.orderedParamNames = nil
	if params == nil {
		return
	}
	for _, kv := range params.Ordered {
		name := kv.Name
		if strings.HasPrefix(name, "@") {
			name = strings.ToUpper(name)
		} else {
			name = "@" + strings.ToUpper(name)
		}
		var runtimeValue any
		var inferred string
		if m, ok := kv.Raw.(map[string]any); ok {
			declared, _ := m["type"].(string)
			if declared == "" {
				declared, _ = m["data_type"].(string)
			}
			runtimeValue = m["value"]
			if declared != "" {
				inferred = strings.ToUpper(declared)
			} else {
				inferred = inferTypeFromValue(runtimeValue)
			}
		} else {
			runtimeValue = kv.Raw
			inferred = inferTypeFromValue(kv.Raw)
		}
		if _, exists := b.externalParams[name]; !exists {
			b.orderedParamNames = append(b.orderedParamNames, name)
		}
		b.externalParams[name] = inferred
		b.externalParamValues[name] = normalizeParamValue(runtimeValue)
	}
}

// inferTypeFromValue 對照 _infer_type_from_value。JSON 數字為 float64：
// 整數值視為 INT（Python int），有小數視為 FLOAT。見 KNOWN_DEVIATIONS。
func inferTypeFromValue(v any) string {
	switch x := v.(type) {
	case nil:
		return "UNKNOWN"
	case bool:
		return "BIT"
	case int:
		return "INT"
	case float64:
		if x == math.Trunc(x) {
			return "INT"
		}
		return "FLOAT"
	case string:
		return "NVARCHAR"
	case []byte:
		return "VARBINARY"
	}
	return "UNKNOWN"
}

// normalizeParamValue 把整數值的 float64 轉回 int，讓 serializer 輸出 30 而非 30.0。
func normalizeParamValue(v any) any {
	if f, ok := v.(float64); ok && f == math.Trunc(f) && math.Abs(f) < 1e15 {
		return int(f)
	}
	return v
}

// ── SELECT ──────────────────────────────────────────────────────────────────

func (b *Binder) bindSelect(stmt *SelectStatement) {
	isRoot := len(b.scopes) == 0

	for _, cte := range stmt.CTEs {
		b.bindCTE(cte)
	}

	b.pushScope()
	if stmt.Table != nil {
		b.registerScopeNode(stmt.Table, stmt.TableAlias)
		if stmt.Pivot != nil {
			b.applyPivot(stmt)
		}
	}
	for _, j := range stmt.Joins {
		al := strings.ToUpper(joinAlias(j))
		switch j.Type {
		case "LEFT":
			b.topNullable()[al] = true
		case "RIGHT":
			for _, k := range b.topScope().order {
				b.topNullable()[k] = true
			}
		case "FULL":
			b.topNullable()[al] = true
			for _, k := range b.topScope().order {
				b.topNullable()[k] = true
			}
		}
		b.registerScopeNode(j.Table, j.Alias)
		if j.OnCondition != nil {
			b.visitExpr(j.OnCondition)
		}
	}
	for _, ap := range stmt.Applies {
		b.bindApply(ap)
	}
	if stmt.IsSelectStar {
		b.expandGlobalStar(stmt)
	}
	for _, prefix := range stmt.StarPrefixes {
		b.expandQualifiedStar(stmt, prefix)
	}
	if stmt.Where != nil && b.isAggRaw(stmt.Where) {
		b.sem("Aggregate functions are not allowed in WHERE clause")
	}
	for _, c := range stmt.Columns {
		b.visitExpr(c)
	}
	if stmt.Where != nil {
		b.visitExpr(stmt.Where)
	}
	anyAgg := false
	for _, c := range stmt.Columns {
		if b.isAggRaw(c) {
			anyAgg = true
		}
	}
	if anyAgg || len(stmt.GroupBy) > 0 {
		for _, c := range stmt.Columns {
			b.checkAggIntegrity(c, stmt.GroupBy)
		}
	}
	for _, g := range stmt.GroupBy {
		if id, ok := g.(*IdentifierNode); ok {
			b.resolveStructuralIdentifier(id, "GROUP BY", true)
		}
		b.visitExpr(g)
	}
	projectedAliases := map[string]string{}
	for _, c := range stmt.Columns {
		if eb := exprOf(c); eb != nil && eb.Alias != "" {
			projectedAliases[strings.ToUpper(eb.Alias)] = eb.InferredType
		}
	}
	for _, o := range stmt.OrderBy {
		if id, ok := o.Column.(*IdentifierNode); ok {
			b.resolveStructuralIdentifier(id, "ORDER BY", true)
			if t, ok := projectedAliases[strings.ToUpper(id.Name)]; ok {
				id.InferredType = t
				continue
			}
		}
		b.visitExpr(o.Column)
	}
	if isRoot {
		b.lastRootNullables = copyBoolSet(b.topNullable())
	}
	if stmt.IntoTable != nil {
		schema := newColSchema()
		for _, col := range stmt.Columns {
			schema.set(columnOutputName(col), inferredTypeOf(col))
		}
		b.tempSchemas[strings.ToUpper(stmt.IntoTable.Name)] = schema
	}
	b.popScope()
}

// bindCTE 綁定一個 CTE query 並把它的投影欄位登記為 virtual schema。
func (b *Binder) bindCTE(cte *CTENode) {
	name := strings.ToUpper(cte.Name)
	// 遞迴 CTE（T-SQL 規則）：query 必須為 UNION [ALL] 且某一側引用自身。
	// 非 UNION 之自我引用仍視為非法（綁定時回報 Table not found，Fail-Closed）。
	if u, ok := cte.Query.(*UnionStatement); ok && unionReferencesName(u, name) {
		registered := false
		b.bindRecursiveUnion(u, cte, name, &registered)
	} else {
		b.bindNode(cte.Query)
	}
	b.cteSchemas[name] = b.cteSchemaOf(cte, queryColumns(cte.Query))
}

// cteSchemaOf 依 CTE 投影欄位建立 virtual schema；有欄位清單時以清單名稱取代輸出名稱。
func (b *Binder) cteSchemaOf(cte *CTENode, cols []Node) *colSchema {
	if len(cte.Columns) > 0 && len(cte.Columns) != len(cols) {
		b.sem("CTE '" + cte.Name + "' has " + itoa(len(cols)) + " columns but " +
			itoa(len(cte.Columns)) + " column names were specified")
	}
	sc := newColSchema()
	for i, c := range cols {
		colName := columnOutputName(c)
		if i < len(cte.Columns) {
			colName = cte.Columns[i]
		}
		sc.set(colName, inferredTypeOf(c))
	}
	return sc
}

// bindRecursiveUnion 先綁定錨點（最左側，不含自我引用）並登記 CTE schema，
// 再綁定遞迴成員，使其中對 CTE 自身之引用可被解析。
func (b *Binder) bindRecursiveUnion(u *UnionStatement, cte *CTENode, name string, registered *bool) {
	if l, ok := u.Left.(*UnionStatement); ok {
		b.bindRecursiveUnion(l, cte, name, registered)
	} else {
		b.bindNode(u.Left)
		if !*registered {
			b.cteSchemas[name] = b.cteSchemaOf(cte, unionSideColumns(u.Left))
			*registered = true
		}
	}
	b.bindNode(u.Right)
	b.finishUnion(u)
}

// unionReferencesName 判斷集合運算任一成員之 FROM／JOIN 是否直接引用 name。
func unionReferencesName(u *UnionStatement, name string) bool {
	for _, side := range []Node{u.Left, u.Right} {
		switch s := side.(type) {
		case *UnionStatement:
			if unionReferencesName(s, name) {
				return true
			}
		case *SelectStatement:
			if tableNodeIs(s.Table, name) {
				return true
			}
			for _, j := range s.Joins {
				if tableNodeIs(j.Table, name) {
					return true
				}
			}
		}
	}
	return false
}

func tableNodeIs(n Node, name string) bool {
	id, _ := n.(*IdentifierNode)
	return id != nil && len(id.Qualifiers) == 0 && strings.ToUpper(id.Name) == name
}

func (b *Binder) bindUnion(stmt *UnionStatement) {
	b.bindNode(stmt.Left)
	b.bindNode(stmt.Right)
	b.finishUnion(stmt)
}

// finishUnion 於兩側皆已綁定後檢查欄位數量／型別相容性並產生 union 之輸出欄位。
func (b *Binder) finishUnion(stmt *UnionStatement) {
	leftCols := unionSideColumns(stmt.Left)
	rightCols := unionSideColumns(stmt.Right)
	if len(leftCols) != len(rightCols) {
		b.sem("All queries combined using a " + stmt.Operator +
			" operator must have an equal number of expressions in their target lists. Got " +
			itoa(len(leftCols)) + " vs " + itoa(len(rightCols)))
	}
	stmt.Columns = nil
	for i := range leftCols {
		lt := inferredTypeOf(leftCols[i])
		rt := inferredTypeOf(rightCols[i])
		if !b.isTypeCompatible(lt, rt) {
			b.sem("Incompatible types in " + stmt.Operator + ": Column " + itoa(i+1) +
				" has types " + lt + " and " + rt)
		}
		colName := ""
		if eb := exprOf(leftCols[i]); eb != nil {
			colName = eb.Alias
		}
		if colName == "" {
			if id, ok := leftCols[i].(*IdentifierNode); ok {
				colName = id.Name
			}
		}
		if colName == "" {
			colName = "col_" + itoa(i+1)
		}
		nc := NewIdentifier(colName, nil)
		if lt != "UNKNOWN" {
			nc.InferredType = lt
		} else {
			nc.InferredType = rt
		}
		stmt.Columns = append(stmt.Columns, nc)
	}
}

// ── scope 註冊 ──────────────────────────────────────────────────────────────

func (b *Binder) virtualSchema(rt string) (*colSchema, bool) {
	if s, ok := b.cteSchemas[rt]; ok {
		return s, true
	}
	if s, ok := b.tempSchemas[rt]; ok {
		return s, true
	}
	return nil, false
}

func (b *Binder) registerScopeNode(tableNode Node, alias string) {
	switch tn := tableNode.(type) {
	case *SelectStatement:
		b.bindSelect(tn)
		b.registerDerived(tn.Columns, alias)
	case *UnionStatement:
		b.bindUnion(tn)
		b.registerDerived(tn.Columns, alias)
	default:
		b.registerScope(tableNode, alias)
	}
}

func (b *Binder) registerDerived(cols []Node, alias string) {
	schema := newColSchema()
	for _, col := range cols {
		schema.set(columnOutputName(col), inferredTypeOf(col))
	}
	key := "DERIVED"
	if alias != "" {
		key = strings.ToUpper(alias)
	}
	b.cteSchemas[key] = schema
	b.topScope().set(key, key)
}

func tableKey(tn *IdentifierNode) string {
	nameUp := strings.ToUpper(tn.Name)
	if len(tn.Qualifiers) > 0 {
		return strings.ToUpper(tn.Qualifiers[len(tn.Qualifiers)-1]) + "." + nameUp
	}
	return nameUp
}

func (b *Binder) registerScope(tableNode Node, alias string) {
	tn, _ := tableNode.(*IdentifierNode)
	if tn == nil {
		return
	}
	if strings.HasPrefix(tn.Name, "@") {
		b.resolveStructuralIdentifier(tn, "FROM/JOIN table", true)
	}
	rt := tableKey(tn)
	tableNameUp := strings.ToUpper(tn.Name)
	isTemp := strings.HasPrefix(tableNameUp, "#")
	if _, hasVirt := b.virtualSchema(rt); !isTemp && !hasVirt && !b.registry.HasTable(rt) {
		b.sem("Table '" + tn.Name + "' not found")
	}
	scopeKey := tableNameUp
	if alias != "" {
		scopeKey = strings.ToUpper(alias)
	}
	b.topScope().set(scopeKey, rt)
}

var datePartsSet = func() map[string]bool {
	m := map[string]bool{}
	for _, s := range strings.Fields(
		"YEAR QUARTER MONTH DAYOFYEAR DAY WEEK WEEKDAY HOUR MINUTE SECOND MILLISECOND " +
			"MICROSECOND NANOSECOND YY YYYY QQ Q MM M DY Y DD D WK WW DW W HH MI N SS S MS MCS NS TZO ISO_WEEK ISOWK ISOWW") {
		m[s] = true
	}
	return m
}()

func (b *Binder) resolveIdentifier(node *IdentifierNode) {
	if node.Name == "*" {
		return
	}
	if len(node.Qualifiers) == 0 && datePartsSet[strings.ToUpper(node.Name)] {
		node.InferredType = "NVARCHAR"
		return
	}
	if strings.HasPrefix(node.Name, "@") {
		key := strings.ToUpper(node.Name)
		if t, ok := b.variableScope[key]; ok {
			node.InferredType = t
			return
		}
		if t, ok := b.externalParams[key]; ok {
			node.InferredType = t
			return
		}
		node.InferredType = "UNKNOWN"
		return
	}

	var fQual string
	if q := node.Qualifier(); q != "" {
		fQual = strings.ToUpper(q)
	}
	colUp := strings.ToUpper(node.Name)
	foundQual := false

	for si := len(b.scopes) - 1; si >= 0; si-- {
		scope := b.scopes[si]
		if fQual != "" {
			for _, al := range scope.order {
				rt := scope.m[al]
				if fQual == rt && al != rt && al != rt[strings.LastIndex(rt, ".")+1:] {
					b.sem("Original table name '" + node.Qualifier() + "' cannot be used when alias '" +
						strings.ToLower(al) + "' is defined")
				}
			}
			mKey := fQual
			if _, ok := scope.get(mKey); !ok {
				parts := strings.Split(fQual, ".")
				mKey = parts[len(parts)-1]
			}
			if rt, ok := scope.get(mKey); ok {
				foundQual = true
				if vs, isVirt := b.virtualSchema(rt); isVirt {
					if t, ok := vs.get(colUp); ok {
						node.InferredType = t
						return
					}
					b.sem("Column '" + node.Name + "' not found in '" + capitalize(rt) + "'")
				}
				if b.registry.HasColumn(rt, colUp) {
					node.InferredType = b.registry.GetColumnType(rt, colUp)
					return
				}
				if len(b.registry.GetColumns(rt)) > 0 {
					b.sem("Column '" + node.Name + "' not found in '" + capitalize(rt) + "'")
				}
				return
			}
		} else {
			var matches [][2]string
			for _, sn := range scope.order {
				rt := scope.m[sn]
				if vs, isVirt := b.virtualSchema(rt); isVirt {
					if _, ok := vs.get(colUp); ok {
						matches = append(matches, [2]string{sn, rt})
					}
				} else if b.registry.HasColumn(rt, colUp) {
					matches = append(matches, [2]string{sn, rt})
				}
			}
			if len(matches) > 1 {
				var names []string
				for _, m := range matches {
					names = append(names, strings.ToUpper(m[1]))
				}
				sortStrings(names)
				b.sem("Column '" + node.Name + "' is ambiguous. Found in: " + strings.Join(names, ", "))
			}
			if len(matches) == 1 {
				rt := matches[0][1]
				if vs, isVirt := b.virtualSchema(rt); isVirt {
					t, _ := vs.get(colUp)
					node.InferredType = t
				} else {
					node.InferredType = b.registry.GetColumnType(rt, colUp)
				}
				parts := strings.Split(rt, ".")
				node.ResolvedTable = parts[len(parts)-1]
				return
			}
			if scope.len() == 1 {
				rt := scope.m[scope.order[0]]
				if vs, isVirt := b.virtualSchema(rt); isVirt {
					if t, ok := vs.get(colUp); ok {
						node.InferredType = t
						return
					}
					if len(vs.names) > 0 {
						b.sem("Column '" + node.Name + "' not found in '" + capitalize(rt) + "'")
					}
					return
				}
				if b.registry.HasColumn(rt, colUp) {
					node.InferredType = b.registry.GetColumnType(rt, colUp)
					return
				}
				if len(b.registry.GetColumns(rt)) > 0 {
					b.sem("Column '" + node.Name + "' not found in '" + capitalize(rt) + "'")
				}
			}
		}
	}
	if fQual != "" && !foundQual {
		b.sem("Unknown qualifier '" + node.Qualifier() + "'")
	}
	b.sem("Column '" + node.Name + "' not found")
}

// ── 型別相容 ────────────────────────────────────────────────────────────────

var (
	typeNums    = strSet("INT DECIMAL FLOAT MONEY SMALLINT TINYINT BIGINT NUMERIC REAL SMALLMONEY BIT FLAG NAMESTYLE")
	typeStrs    = strSet("NVARCHAR VARCHAR STRING CHAR NCHAR SYSNAME UNIQUEIDENTIFIER HIERARCHYID NAME ORDERNUMBER ACCOUNTNUMBER PHONE TEXT NTEXT")
	typeDates   = strSet("DATETIME DATE TIME DATETIME2 SMALLDATETIME DATETIMEOFFSET")
	typeSpatial = strSet("GEOGRAPHY GEOMETRY")
	typeBinary  = strSet("VARBINARY BINARY IMAGE")
	typeXML     = strSet("XML")
)

func (b *Binder) isTypeCompatible(t1, t2 string) bool {
	if t1 == t2 || t1 == "UNKNOWN" || t2 == "UNKNOWN" || t1 == "TABLE" || t2 == "TABLE" {
		return true
	}
	if typeNums[t1] && typeNums[t2] {
		return true
	}
	if typeStrs[t1] && typeStrs[t2] {
		return true
	}
	if typeDates[t1] && typeDates[t2] {
		return true
	}
	if typeSpatial[t1] && typeSpatial[t2] {
		return true
	}
	if typeBinary[t1] && typeBinary[t2] {
		return true
	}
	if typeXML[t1] && typeXML[t2] {
		return true
	}
	if (typeDates[t1] && typeStrs[t2]) || (typeStrs[t1] && typeDates[t2]) {
		return true
	}
	return false
}

func (b *Binder) bindOverClause(over *OverClauseNode) {
	if over == nil {
		return
	}
	for _, e := range over.PartitionBy {
		b.visitExpr(e)
	}
	for _, o := range over.OrderBy {
		b.visitExpr(o.Column)
	}
}

// ── 表達式訪問 ──────────────────────────────────────────────────────────────

var arithOps = map[string]bool{
	"+": true, "-": true, "*": true, "/": true, "%": true,
	"&": true, "|": true, "^": true, "~": true,
}
var cmpOps = map[string]bool{
	"=": true, ">": true, "<": true, ">=": true, "<=": true, "<>": true,
	"IN": true, "NOT IN": true, "LIKE": true, "NOT LIKE": true,
	"IS NULL": true, "IS NOT NULL": true,
}

func (b *Binder) visitExpr(expr Node) string {
	switch e := expr.(type) {
	case nil:
		return "UNKNOWN"
	case *IdentifierNode:
		b.resolveIdentifier(e)
		return e.InferredType
	case *LiteralNode:
		if e.InferredType == "DECIMAL" {
			return "INT"
		}
		return e.InferredType
	case *BinaryExpressionNode:
		return b.visitBinary(e)
	case *FunctionCallNode:
		return b.visitFunction(e)
	case *CaseExpressionNode:
		return b.visitCase(e)
	case *BetweenExpressionNode:
		return b.visitBetween(e)
	case *CastExpressionNode:
		b.visitExpr(e.Expr)
		e.InferredType = e.TargetType
		return e.TargetType
	case *SelectStatement:
		b.bindSelect(e)
		if len(e.Columns) == 1 {
			e.InferredType = inferredTypeOf(e.Columns[0])
		} else {
			e.InferredType = "UNKNOWN"
		}
		return e.InferredType
	case *UnionStatement:
		b.bindUnion(e)
		return "TABLE"
	case nodeList:
		return "UNKNOWN"
	}
	return "UNKNOWN"
}

func (b *Binder) visitBinary(expr *BinaryExpressionNode) string {
	rtRaw := b.visitExpr(expr.Right)
	lt := b.visitExpr(expr.Left)
	rt := rtRaw
	if rtRaw == "TABLE" {
		rt = lt
	}
	op := expr.Operator

	if arithOps[op] {
		if op == "+" {
			isNum := b.isTypeCompatible(lt, "INT") && b.isTypeCompatible(rt, "INT")
			isStr := b.isTypeCompatible(lt, "NVARCHAR") && b.isTypeCompatible(rt, "NVARCHAR")
			if !isNum && !isStr {
				b.sem("Operator '+' cannot be applied to " + lt + " and " + rt)
			}
			if isNum {
				expr.InferredType = "INT"
			} else {
				expr.InferredType = "NVARCHAR"
			}
		} else {
			if !b.isTypeCompatible(lt, "INT") || !b.isTypeCompatible(rt, "INT") {
				b.sem("Operator '" + op + "' cannot be applied")
			}
			expr.InferredType = "INT"
		}
		return expr.InferredType
	}

	if cmpOps[op] || strings.Contains(op, " ANY") || strings.Contains(op, " ALL") {
		switch {
		case strings.Contains(op, " ANY") || strings.Contains(op, " ALL"):
			if list, ok := expr.Right.(nodeList); ok {
				for _, item := range list {
					it := b.visitExpr(item)
					if !b.isTypeCompatible(lt, it) {
						b.sem("Incompatible types in " + op + ": " + lt + " vs " + it)
					}
				}
			} else if sub := asSubquery(expr.Right); sub != nil {
				b.bindNode(sub)
				if cols := queryColumns(sub); len(cols) > 0 {
					subRT := inferredTypeOf(cols[0])
					if !b.isTypeCompatible(lt, subRT) {
						b.sem("Incompatible types in " + op + ": " + lt + " vs " + subRT)
					}
				}
			}
			expr.InferredType = "BIT"
		case op == "IN" || op == "NOT IN":
			if list, ok := expr.Right.(nodeList); ok {
				for _, item := range list {
					it := b.visitExpr(item)
					if !b.isTypeCompatible(lt, it) {
						b.sem("Incompatible types in " + op + ": " + lt + " vs " + it)
					}
				}
			} else if sub := asSubquery(expr.Right); sub != nil {
				b.bindNode(sub)
			}
			expr.InferredType = "BIT"
		case op != "IS NULL" && op != "IS NOT NULL":
			if !b.isTypeCompatible(lt, rt) {
				b.sem("Cannot compare " + lt + " with " + rt)
			}
			expr.InferredType = "BIT"
		default:
			expr.InferredType = "BIT"
		}
		return expr.InferredType
	}
	return expr.InferredType
}

func (b *Binder) visitFunction(expr *FunctionCallNode) string {
	fName := strings.ToUpper(expr.Name)
	if b.registry.IsRestricted(fName) {
		b.sem("Function '" + fName + "' is restricted")
	}
	isWindowCall := expr.OverClause != nil
	if isWindowCall {
		if !b.registry.HasFunction(fName) {
			b.sem("Unknown function '" + fName + "' for window context")
		}
	} else {
		if !b.registry.HasFunction(fName) {
			b.sem("Unknown function '" + fName + "'")
		}
	}
	fMeta := b.registry.GetFunction(fName)
	if !(fMeta.MinArgs <= len(expr.Args) && len(expr.Args) <= fMeta.MaxArgs) {
		b.sem("Function '" + fName + "' expects " + itoa(fMeta.MinArgs) + " arguments, got " + itoa(len(expr.Args)))
	}
	for i, arg := range expr.Args {
		act := b.visitExpr(arg)
		if i < len(fMeta.ExpectedTypes) {
			exp := fMeta.ExpectedTypes[i]
			if exp != "ANY" && act != "UNKNOWN" && !b.isTypeCompatible(exp, act) {
				b.sem("Function '" + fName + "' expects " + exp + ", but got " + act)
			}
		}
	}
	if isWindowCall {
		b.bindOverClause(expr.OverClause)
		if fMeta.ReturnType != "ANY" {
			expr.InferredType = fMeta.ReturnType
		} else {
			expr.InferredType = "BIGINT"
		}
	} else {
		if fMeta.ReturnType == "ANY" && len(expr.Args) > 0 {
			argType := ""
			if eb := exprOf(expr.Args[0]); eb != nil && eb.InferredType != "UNKNOWN" {
				argType = eb.InferredType
			} else {
				argType = b.visitExpr(expr.Args[0])
			}
			if argType != "UNKNOWN" {
				expr.InferredType = argType
			} else {
				expr.InferredType = "ANY"
			}
		} else {
			expr.InferredType = fMeta.ReturnType
		}
	}
	return expr.InferredType
}

func (b *Binder) visitCase(expr *CaseExpressionNode) string {
	if expr.InputExpr != nil {
		b.visitExpr(expr.InputExpr)
	}
	var bTypes []string
	for _, br := range expr.Branches {
		b.visitExpr(br.When)
		bTypes = append(bTypes, b.visitExpr(br.Then))
	}
	if expr.ElseExpr != nil {
		bTypes = append(bTypes, b.visitExpr(expr.ElseExpr))
	}
	uniq := sortedUnique(bTypes)
	if len(uniq) > 1 {
		base := uniq[0]
		allCompat := true
		for _, t := range uniq {
			if !b.isTypeCompatible(base, t) {
				allCompat = false
			}
		}
		if !allCompat {
			rev := append([]string(nil), uniq...)
			for i, j := 0, len(rev)-1; i < j; i, j = i+1, j-1 {
				rev[i], rev[j] = rev[j], rev[i]
			}
			b.sem("CASE branches have incompatible types: " + strings.Join(rev, " and "))
		}
	}
	if len(bTypes) > 0 {
		expr.InferredType = bTypes[0]
	} else {
		expr.InferredType = "UNKNOWN"
	}
	return expr.InferredType
}

func (b *Binder) visitBetween(node *BetweenExpressionNode) string {
	t := b.visitExpr(node.Expr)
	l := b.visitExpr(node.Low)
	h := b.visitExpr(node.High)
	if !b.isTypeCompatible(t, l) || !b.isTypeCompatible(t, h) {
		b.sem("Incompatible types in BETWEEN: Cannot compare " + t + " with " + l + " and " + h)
	}
	node.InferredType = "BIT"
	return "BIT"
}

// ── DML bind ────────────────────────────────────────────────────────────────

func (b *Binder) bindUpdate(stmt *UpdateStatement) {
	for _, cte := range stmt.CTEs {
		b.bindCTE(cte)
	}
	b.pushScope()
	b.bindDMLSources(stmt.Table, stmt.TableAlias, stmt.FromTable, stmt.FromAlias, stmt.FromJoins)
	if stmt.Where != nil {
		b.visitExpr(stmt.Where)
	}
	for _, c := range stmt.SetClauses {
		b.checkTypeCompatibility(b.visitExpr(c.Column), b.visitExpr(c.Right), "SET assignment")
	}
	b.popScope()
}

func (b *Binder) bindDelete(stmt *DeleteStatement) {
	for _, cte := range stmt.CTEs {
		b.bindCTE(cte)
	}
	b.pushScope()
	b.bindDMLSources(stmt.Table, stmt.TableAlias, stmt.FromTable, stmt.FromAlias, stmt.FromJoins)
	if stmt.Where != nil {
		b.visitExpr(stmt.Where)
	}
	b.popScope()
}

// bindDMLSources 登記 UPDATE／DELETE 之資料來源。
// 無 FROM：目標表即唯一來源。有 FROM：先登記 FROM 來源與 JOIN，目標若為 FROM 清單內之別名
// （或未加別名之資料表名）則直接解析至該項（T-SQL 慣用寫法 UPDATE c ... FROM T c），
// 否則目標另行登記為獨立資料表（目標不存在時照常回報 Table not found）。
func (b *Binder) bindDMLSources(target *IdentifierNode, tableAlias string, fromTable Node, fromAlias string, joins []*JoinNode) {
	if fromTable == nil {
		b.registerScope(target, tableAlias)
		return
	}
	b.registerScopeNode(fromTable, fromAlias)
	for _, j := range joins {
		al := strings.ToUpper(joinAlias(j))
		switch j.Type {
		case "LEFT":
			b.topNullable()[al] = true
		case "RIGHT":
			for _, k := range b.topScope().order {
				b.topNullable()[k] = true
			}
		case "FULL":
			b.topNullable()[al] = true
			for _, k := range b.topScope().order {
				b.topNullable()[k] = true
			}
		}
		b.registerScopeNode(j.Table, j.Alias)
		if j.OnCondition != nil {
			b.visitExpr(j.OnCondition)
		}
	}
	if target != nil && len(target.Qualifiers) == 0 {
		if _, ok := b.topScope().m[strings.ToUpper(target.Name)]; ok {
			return
		}
	}
	b.registerScope(target, tableAlias)
}

func (b *Binder) bindInsert(stmt *InsertStatement) {
	b.pushScope()
	b.registerScope(stmt.Table, "")
	tn := tableKey(stmt.Table)
	if len(stmt.Columns) > 0 {
		for _, c := range stmt.Columns {
			if len(b.registry.GetColumns(tn)) > 0 && !b.registry.HasColumn(tn, strings.ToUpper(c.Name)) {
				b.sem("Column '" + c.Name + "' not found in '" + capitalize(tn) + "'")
			}
		}
	}
	var colNames []string
	if len(stmt.Columns) > 0 {
		for _, c := range stmt.Columns {
			colNames = append(colNames, strings.ToUpper(c.Name))
		}
	} else {
		colNames = b.registry.GetColumns(tn)
	}

	if stmt.Source != nil {
		b.bindNode(stmt.Source)
		srcCols := queryColumns(stmt.Source)
		if len(colNames) > 0 && len(colNames) != len(srcCols) {
			b.sem("Column count mismatch: Expected " + itoa(len(colNames)) + ", got " + itoa(len(srcCols)))
		}
		for i, col := range srcCols {
			if len(colNames) > 0 {
				lt := b.registry.GetColumnType(tn, colNames[i])
				b.checkTypeCompatibility(lt, inferredTypeOf(col), "INSERT into '"+colNames[i]+"'")
			}
		}
		b.popScope()
		return
	}

	rows := stmt.ValueRows
	if len(rows) == 0 {
		rows = [][]Node{stmt.Values}
	}
	for _, row := range rows {
		if len(colNames) > 0 && len(colNames) != len(row) {
			b.sem("Column count mismatch: Expected " + itoa(len(colNames)) + ", got " + itoa(len(row)))
		}
		for i, v := range row {
			rt := b.visitExpr(v)
			if len(colNames) > 0 {
				lt := b.registry.GetColumnType(tn, colNames[i])
				b.checkTypeCompatibility(lt, rt, "INSERT into '"+colNames[i]+"'")
			}
		}
	}
	b.popScope()
}

func (b *Binder) bindTruncate(stmt *TruncateStatement) {
	rt := tableKey(stmt.Table)
	if !b.registry.HasTable(rt) {
		b.sem("Table '" + stmt.Table.Name + "' not found")
	}
}

func (b *Binder) bindBulkInsert(stmt *SqlBulkCopyStatement) {
	if !b.registry.HasTable(tableKey(stmt.Table)) {
		b.sem("Table '" + stmt.Table.Name + "' not found")
	}
}

func (b *Binder) bindDeclare(stmt *DeclareStatement) {
	b.variableScope[strings.ToUpper(stmt.VarName)] = stmt.VarType
	if stmt.DefaultValue != nil {
		b.visitExpr(stmt.DefaultValue)
	}
}

func (b *Binder) bindIf(stmt *IfStatement) {
	if stmt.Condition != nil {
		b.visitExpr(stmt.Condition)
	}
	for _, s := range stmt.ThenBlock {
		if s != nil {
			b.bindNode(s)
		}
	}
	for _, s := range stmt.ElseBlock {
		if s != nil {
			b.bindNode(s)
		}
	}
}

var blockedProcs = strSet("XP_CMDSHELL SP_EXECUTESQL SP_OA_CREATE SP_OA_METHOD SP_OA_GETPROPERTY SP_CONFIGURE OPENROWSET OPENQUERY")

// procKeys 回傳預存程序呼叫可對應之白名單鍵（皆為大寫）：呼叫時所寫之完整名稱；
// 未指定 schema 者另視同 dbo.<name>（SQL Server 預設 schema）。
func procKeys(id *IdentifierNode) []string {
	full := strings.ToUpper(strings.Join(append(append([]string{}, id.Qualifiers...), id.Name), "."))
	keys := []string{full}
	if len(id.Qualifiers) == 0 {
		keys = append(keys, "DBO."+strings.ToUpper(id.Name))
	}
	return keys
}

// bindExec 對預存程序呼叫採「封鎖清單 + 白名單」：封鎖清單恆優先；其餘預存程序預設拒絕，
// 僅允許白名單（Binder.allowedProcs）所列者。預存程序內部讀寫之欄位對 BirdEye 不可見，
// 故不得預設放行，由管理者逐一審核後列入白名單。
func (b *Binder) bindExec(stmt *ExecStatement) {
	id, ok := stmt.ProcName.(*IdentifierNode)
	if !ok || id == nil || id.Name == "" {
		b.sem("Stored procedure call without a literal procedure name is not allowed by ZTA policy")
	}
	if blockedProcs[strings.ToUpper(id.Name)] {
		b.sem("Stored procedure '" + id.Name + "' is blocked by ZTA policy")
	}
	if strings.HasPrefix(id.Name, "@") {
		b.sem("Stored procedure name given by a variable is not allowed by ZTA policy")
	}
	allowed := false
	for _, k := range procKeys(id) {
		if b.allowedProcs[k] {
			allowed = true
			break
		}
	}
	if !allowed {
		b.sem("Stored procedure '" + strings.Join(append(append([]string{}, id.Qualifiers...), id.Name), ".") + "' is not on the ZTA allow-list")
	}
	for _, a := range stmt.Args {
		b.visitExpr(a)
	}
}

func (b *Binder) bindSet(stmt *SetStatement) {
	if !stmt.IsOption {
		if id, ok := stmt.Target.(*IdentifierNode); ok {
			varKey := strings.ToUpper(id.Name)
			if v, ok := stmt.Value.(Node); ok && v != nil {
				t := b.visitExpr(v)
				if t == "" {
					if prev, ok := b.variableScope[varKey]; ok {
						t = prev
					} else {
						t = "UNKNOWN"
					}
				}
				b.variableScope[varKey] = t
			}
			return
		}
	}
	if v, ok := stmt.Value.(Node); ok && v != nil {
		b.visitExpr(v)
	}
}

func (b *Binder) bindCreateTable(stmt *CreateTableStatement) {
	if stmt.Table == nil {
		return
	}
	tname := strings.ToUpper(stmt.Table.Name)
	if strings.HasPrefix(tname, "#") {
		schema := newColSchema()
		for _, col := range stmt.Columns {
			schema.set(col.Name, strings.ToUpper(col.DataType))
		}
		b.tempSchemas[tname] = schema
	}
}

func (b *Binder) bindMerge(stmt *MergeStatement) {
	b.pushScope()
	defer b.popScope()
	if stmt.Target != nil {
		b.registerScope(stmt.Target, stmt.TargetAlias)
	}
	if stmt.Source != nil {
		b.registerScopeNode(stmt.Source, stmt.SourceAlias)
	}
	if stmt.OnCondition != nil {
		b.visitExpr(stmt.OnCondition)
	}
	for _, clause := range stmt.Clauses {
		if clause.Condition != nil {
			b.visitExpr(clause.Condition)
		}
		for _, sc := range clause.SetClauses {
			if sc.Right != nil {
				b.visitExpr(sc.Right)
			}
		}
		for _, v := range clause.InsertValues {
			b.visitExpr(v)
		}
	}
}

func (b *Binder) bindPrint(stmt *PrintStatement) {
	if stmt.Expr != nil {
		b.visitExpr(stmt.Expr)
	}
}

func (b *Binder) bindApply(apply *ApplyNode) {
	sub, _ := apply.Subquery.(*SelectStatement)
	if sub == nil {
		return
	}
	b.bindSelect(sub)
	schema := newColSchema()
	for _, col := range sub.Columns {
		schema.set(columnOutputName(col), inferredTypeOf(col))
	}
	apply.Columns = append([]Node(nil), sub.Columns...)
	if apply.Alias != "" {
		aliasUp := strings.ToUpper(apply.Alias)
		b.cteSchemas[aliasUp] = schema
		b.topScope().set(aliasUp, aliasUp)
		if apply.Type == "OUTER" {
			b.topNullable()[aliasUp] = true
		}
	}
}

func (b *Binder) checkTypeCompatibility(lt, rt, ctx string) {
	if !b.isTypeCompatible(lt, rt) {
		b.sem("Incompatible types for " + ctx + ": Cannot compare " + lt + " with " + rt)
	}
}

// ── 聚合完整性 ──────────────────────────────────────────────────────────────

func (b *Binder) isAggRaw(expr Node) bool {
	switch e := expr.(type) {
	case *FunctionCallNode:
		if e.OverClause != nil {
			return false
		}
		if b.registry.IsAggregate(e.Name) {
			return true
		}
		for _, a := range e.Args {
			if b.isAggRaw(a) {
				return true
			}
		}
		return false
	case *BinaryExpressionNode:
		return b.isAggRaw(e.Left) || b.isAggRaw(e.Right)
	case *CaseExpressionNode:
		if e.InputExpr != nil && b.isAggRaw(e.InputExpr) {
			return true
		}
		for _, br := range e.Branches {
			if b.isAggRaw(br.When) || b.isAggRaw(br.Then) {
				return true
			}
		}
		if e.ElseExpr != nil {
			return b.isAggRaw(e.ElseExpr)
		}
		return false
	}
	return false
}

func (b *Binder) checkAggIntegrity(expr Node, groups []Node) {
	if b.isAggRaw(expr) {
		if ce, ok := expr.(*CaseExpressionNode); ok {
			if ce.InputExpr != nil {
				b.checkAggIntegrity(ce.InputExpr, groups)
			}
			for _, br := range ce.Branches {
				b.checkAggIntegrity(br.When, groups)
				if !b.isAggRaw(br.Then) {
					b.checkAggIntegrity(br.Then, groups)
				}
			}
			if ce.ElseExpr != nil && !b.isAggRaw(ce.ElseExpr) {
				b.checkAggIntegrity(ce.ElseExpr, groups)
			}
		}
		return
	}
	eJ := strippedStruct(expr)
	for _, g := range groups {
		if deepEqualJ(strippedStruct(g), eJ) {
			return
		}
	}
	switch e := expr.(type) {
	case *IdentifierNode:
		found := false
		for _, g := range groups {
			if gi, ok := g.(*IdentifierNode); ok && strings.EqualFold(gi.Name, e.Name) {
				found = true
			}
		}
		if !found {
			b.sem("Column '" + e.Name + "' must appear in the GROUP BY clause or be used in an aggregate function")
		}
	case *BinaryExpressionNode:
		b.checkAggIntegrity(e.Left, groups)
		b.checkAggIntegrity(e.Right, groups)
	case *FunctionCallNode:
		if e.OverClause != nil {
			return
		}
		sameInGroup := false
		for _, g := range groups {
			if gf, ok := g.(*FunctionCallNode); ok && gf.Name == e.Name && len(gf.Args) == len(e.Args) {
				sameInGroup = true
			}
		}
		if !sameInGroup {
			for _, a := range e.Args {
				b.checkAggIntegrity(a, groups)
			}
		}
	case *CaseExpressionNode:
		if e.InputExpr != nil {
			b.checkAggIntegrity(e.InputExpr, groups)
		}
		for _, br := range e.Branches {
			b.checkAggIntegrity(br.When, groups)
			b.checkAggIntegrity(br.Then, groups)
		}
		if e.ElseExpr != nil {
			b.checkAggIntegrity(e.ElseExpr, groups)
		}
	}
}

// strippedStruct 對照 _check_agg_integrity 的 _c(n)：序列化後移除 alias / resolved_table /
// resolved_from_param，供結構比對。
func strippedStruct(n Node) any {
	v := NewSerializer().serialize(n)
	stripStructKeys(v)
	return v
}

func stripStructKeys(v any) {
	switch x := v.(type) {
	case jobj:
		out := x[:0]
		for _, kv := range x {
			if kv.k == "alias" || kv.k == "resolved_table" || kv.k == "resolved_from_param" {
				continue
			}
			stripStructKeys(kv.v)
			out = append(out, kv)
		}
		_ = out
	case jarr:
		for _, e := range x {
			stripStructKeys(e)
		}
	}
}

func deepEqualJ(a, b any) bool {
	switch av := a.(type) {
	case jobj:
		bv, ok := b.(jobj)
		if !ok {
			return false
		}
		am := filterStripped(av)
		bm := filterStripped(bv)
		if len(am) != len(bm) {
			return false
		}
		for k, va := range am {
			vb, ok := bm[k]
			if !ok || !deepEqualJ(va, vb) {
				return false
			}
		}
		return true
	case jarr:
		bv, ok := b.(jarr)
		if !ok || len(av) != len(bv) {
			return false
		}
		for i := range av {
			if !deepEqualJ(av[i], bv[i]) {
				return false
			}
		}
		return true
	default:
		return a == b
	}
}

func filterStripped(o jobj) map[string]any {
	m := map[string]any{}
	for _, kv := range o {
		if kv.k == "alias" || kv.k == "resolved_table" || kv.k == "resolved_from_param" {
			continue
		}
		m[kv.k] = kv.v
	}
	return m
}

// ── star 展開 ───────────────────────────────────────────────────────────────

func (b *Binder) expandGlobalStar(stmt *SelectStatement) {
	sc := b.topScope()
	for _, al := range sc.order {
		b.appendStarCols(stmt, al, sc.m[al])
	}
}

func (b *Binder) expandQualifiedStar(stmt *SelectStatement, prefix string) {
	rt, ok := b.topScope().get(strings.ToUpper(prefix))
	if !ok {
		b.sem("Unknown qualifier '" + prefix + "' in star expansion")
	}
	b.appendStarCols(stmt, prefix, rt)
}

func (b *Binder) appendStarCols(stmt *SelectStatement, qualifier, rt string) {
	if vs, isVirt := b.virtualSchema(rt); isVirt {
		for _, c := range vs.names {
			n := NewIdentifier(c, []string{qualifier})
			n.InferredType, _ = vs.get(c)
			stmt.Columns = append(stmt.Columns, n)
		}
		return
	}
	for _, c := range b.registry.GetColumns(rt) {
		n := NewIdentifier(c, []string{qualifier})
		n.InferredType = b.registry.GetColumnType(rt, c)
		stmt.Columns = append(stmt.Columns, n)
	}
}

// ── 結構性參數 ──────────────────────────────────────────────────────────────

func (b *Binder) isSafeIdentifier(candidate string, allowQualified bool) bool {
	parts := strings.Split(candidate, ".")
	if len(parts) > 2 {
		return false
	}
	if len(parts) == 2 && !allowQualified {
		return false
	}
	for _, p := range parts {
		if !identifierPattern.MatchString(p) {
			return false
		}
	}
	return true
}

func (b *Binder) resolveStructuralIdentifier(node *IdentifierNode, context string, allowQualified bool) {
	if node == nil || !strings.HasPrefix(node.Name, "@") {
		return
	}
	key := strings.ToUpper(node.Name)
	raw, ok := b.externalParamValues[key]
	if !ok {
		b.sem(context + " placeholder '" + node.Name + "' requires a runtime parameter value")
	}
	rawStr, isStr := raw.(string)
	if !isStr || strings.TrimSpace(rawStr) == "" {
		b.sem(context + " placeholder '" + node.Name + "' must be a non-empty identifier string")
	}
	candidate := strings.TrimSpace(rawStr)
	if !b.isSafeIdentifier(candidate, allowQualified) {
		b.sem(context + " placeholder '" + node.Name + "' resolved to unsafe identifier '" + candidate + "'")
	}
	parts := strings.Split(candidate, ".")
	node.Name = parts[len(parts)-1]
	node.Qualifiers = parts[:len(parts)-1]
	node.ResolvedFromParam = key
}

// nullable_scopes 對照 property：堆疊頂端，空則 lastRootNullables。
func (b *Binder) nullableScopes() map[string]bool {
	if len(b.nullableStack) > 0 {
		return b.nullableStack[len(b.nullableStack)-1]
	}
	return b.lastRootNullables
}

// NullableScopes / LastRootNullables 供白箱測試檢視外連接的可空傳導狀態
// （對照 Python 測試存取 _binder.nullable_scopes / _last_root_nullables）。
func (b *Binder) NullableScopes() map[string]bool    { return b.nullableScopes() }
func (b *Binder) LastRootNullables() map[string]bool { return b.lastRootNullables }

// TempSchemas 供白箱測試檢視 SELECT INTO / CREATE TABLE # 註冊的臨時表。
func (b *Binder) TempSchemas() map[string]bool {
	out := map[string]bool{}
	for k := range b.tempSchemas {
		out[k] = true
	}
	return out
}

// ── scope stack helpers ─────────────────────────────────────────────────────

func (b *Binder) pushScope() {
	b.scopes = append(b.scopes, newScopeFrame())
	b.nullableStack = append(b.nullableStack, map[string]bool{})
}

func (b *Binder) popScope() {
	b.scopes = b.scopes[:len(b.scopes)-1]
	b.nullableStack = b.nullableStack[:len(b.nullableStack)-1]
}

func (b *Binder) topScope() *scopeFrame { return b.scopes[len(b.scopes)-1] }
func (b *Binder) topNullable() map[string]bool {
	return b.nullableStack[len(b.nullableStack)-1]
}
