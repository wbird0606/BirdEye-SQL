package birdeye

import (
	"sort"
	"strconv"
	"strings"
)

// Visualizer 對照 Python birdeye/visualizer.py 的 ASTVisualizer：AST → 帶型別標註的文字樹。
type Visualizer struct {
	lines []string
}

func NewVisualizer() *Visualizer { return &Visualizer{} }

// Dump 對照 dump()。
func (v *Visualizer) Dump(node Node) string {
	v.lines = nil
	v.visit(node, 0, "ROOT")
	return strings.Join(v.lines, "\n")
}

func (v *Visualizer) add(s string) { v.lines = append(v.lines, s) }

func ind(n int) string { return strings.Repeat("  ", n) }

func qmarkMode(n Node) bool {
	if m := metaOf(n); m != nil {
		return m.ParamInputMode == "qmark"
	}
	return false
}

func displayParamName(n Node, name string) string {
	if qmarkMode(n) && strings.HasPrefix(strings.ToUpper(name), "@P") {
		return "?"
	}
	return name
}

// paramSortKey 對照 _param_sort_key：@Pn 依數字排前，其餘依字串。
func sortParamsForTree(ps []ParamBinding) []ParamBinding {
	out := append([]ParamBinding(nil), ps...)
	rank := func(name string) (int, int, string) {
		u := strings.ToUpper(name)
		if strings.HasPrefix(u, "@P") && len(u) > 2 {
			if n, err := strconv.Atoi(u[2:]); err == nil {
				return 0, n, name
			}
		}
		return 1, 0, name
	}
	sort.SliceStable(out, func(i, j int) bool {
		a0, a1, a2 := rank(out[i].Name)
		b0, b1, b2 := rank(out[j].Name)
		if a0 != b0 {
			return a0 < b0
		}
		if a1 != b1 {
			return a1 < b1
		}
		return a2 < b2
	})
	return out
}

func pyRepr(val any) string {
	switch x := val.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case int:
		return strconv.Itoa(x)
	case float64:
		return encFloat(x)
	case string:
		if strings.Contains(x, "'") && !strings.Contains(x, `"`) {
			return `"` + x + `"`
		}
		return "'" + strings.NewReplacer(`\`, `\\`, `'`, `\'`).Replace(x) + "'"
	}
	return strconv.Quote(strings.TrimSpace(itoa(0)))
}

func inferTypeInfo(n Node) string {
	if eb := exprOf(n); eb != nil && eb.InferredType != "" && eb.InferredType != "UNKNOWN" {
		return " [Type: " + eb.InferredType + "]"
	}
	return ""
}

func aliasInfo(n Node) string {
	if eb := exprOf(n); eb != nil && eb.Alias != "" {
		return " AS " + eb.Alias
	}
	return ""
}

func (v *Visualizer) paramBlock(root Node, m *NodeMeta, curInd string) {
	if m == nil || len(m.Params) == 0 {
		return
	}
	sorted := sortParamsForTree(m.Params)
	v.add(curInd + "  ├── BOUND PARAMS (types)")
	for _, p := range sorted {
		v.add(curInd + "  │   └── " + displayParamName(root, p.Name) + ": " + p.Type)
	}
	v.add(curInd + "  ├── BOUND PARAM VALUES")
	for _, p := range sorted {
		v.add(curInd + "  │   └── " + displayParamName(root, p.Name) + ": " + pyRepr(p.Value))
	}
}

func (v *Visualizer) visit(node Node, indent int, label string) {
	prefix := ""
	if indent > 0 {
		prefix = ind(indent) + "└── "
	}
	cur := ind(indent)

	switch n := node.(type) {
	case *ScriptNode:
		m := &n.NodeMeta
		info := ""
		if len(m.Params) > 0 {
			info = ", params=" + itoa(len(m.Params))
		}
		v.add(prefix + "SCRIPT (" + itoa(len(n.Statements)) + " statements" + info + ")")
		v.paramBlock(node, m, cur)
		for i, stmt := range n.Statements {
			conn := "├── "
			if i == len(n.Statements)-1 {
				conn = "└── "
			}
			v.add(cur + "  " + conn + "STATEMENT #" + itoa(i+1))
			v.visit(stmt, indent+2, "STMT")
		}

	case *SelectStatement:
		m := &n.NodeMeta
		info := ""
		if len(m.Params) > 0 {
			info = " [Params: " + itoa(len(m.Params)) + "]"
		}
		v.add(prefix + "SELECT_STATEMENT" + info)
		v.paramBlock(node, m, cur)
		if len(n.CTEs) > 0 {
			v.add(cur + "  ├── WITH (CTEs)")
			for _, c := range n.CTEs {
				v.visit(c, indent+2, "CTE")
			}
		}
		if n.IsDistinct {
			v.add(cur + "  ├── DISTINCT")
		}
		if n.TopCount != nil {
			ps := ""
			if n.TopPercent {
				ps = " PERCENT"
			}
			v.add(cur + "  ├── TOP: " + itoa(*n.TopCount) + ps)
		}
		if n.IsSelectStar && len(n.Columns) == 0 {
			v.add(cur + "  ├── COLUMNS: *")
		} else {
			v.add(cur + "  ├── COLUMNS")
			for _, c := range n.Columns {
				v.visit(c, indent+2, "COL")
			}
		}
		if n.Table != nil {
			v.add(cur + "  ├── FROM")
			v.visit(n.Table, indent+2, "TABLE")
			if n.TableAlias != "" {
				v.add(cur + "    └── ALIAS: " + n.TableAlias)
			}
		} else {
			v.add(cur + "  ├── FROM: <DUAL/NONE> (Scalar/Literal Query)")
		}
		if len(n.Joins) > 0 {
			v.add(cur + "  ├── JOINS")
			for _, j := range n.Joins {
				v.visit(j, indent+2, "JOIN")
			}
		}
		if len(n.Applies) > 0 {
			v.add(cur + "  ├── APPLY")
			for _, ap := range n.Applies {
				v.visit(ap, indent+2, "APPLY")
			}
		}
		if n.IntoTable != nil {
			v.add(cur + "  ├── INTO: " + n.IntoTable.Name)
		}
		if n.Where != nil {
			v.add(cur + "  ├── WHERE")
			v.visit(n.Where, indent+2, "COND")
		}
		if len(n.GroupBy) > 0 {
			v.add(cur + "  ├── GROUP BY")
			for _, g := range n.GroupBy {
				v.visit(g, indent+2, "G_COL")
			}
		}
		if n.Having != nil {
			v.add(cur + "  ├── HAVING")
			v.visit(n.Having, indent+2, "COND")
		}
		if len(n.OrderBy) > 0 {
			v.add(cur + "  ├── ORDER BY")
			for _, o := range n.OrderBy {
				v.visit(o, indent+2, "ORDER")
			}
		}
		if n.OffsetCount != nil {
			v.add(cur + "  ├── OFFSET: " + itoa(*n.OffsetCount))
		}
		if n.FetchCount != nil {
			v.add(cur + "  └── FETCH NEXT: " + itoa(*n.FetchCount))
		}

	case *UnionStatement:
		v.add(prefix + "SET_OPERATION: " + n.Operator)
		v.add(cur + "  ├── LEFT")
		v.visit(n.Left, indent+2, "QUERY")
		v.add(cur + "  └── RIGHT")
		v.visit(n.Right, indent+2, "QUERY")

	case *CTENode:
		v.add(prefix + "CTE: " + n.Name)
		v.add(cur + "  └── QUERY")
		v.visit(n.Query, indent+2, "SUBQUERY")

	case *UpdateStatement:
		v.add(prefix + "UPDATE_STATEMENT")
		v.add(cur + "  ├── TABLE: " + n.Table.Name)
		if n.TableAlias != "" {
			v.add(cur + "  ├── ALIAS: " + n.TableAlias)
		}
		v.add(cur + "  ├── SET")
		for _, c := range n.SetClauses {
			v.visit(c, indent+2, "CLAUSE")
		}
		v.add(cur + "  └── WHERE (MANDATORY)")
		v.visit(n.Where, indent+2, "COND")

	case *DeleteStatement:
		v.add(prefix + "DELETE_STATEMENT")
		v.add(cur + "  ├── FROM: " + n.Table.Name)
		if n.TableAlias != "" {
			v.add(cur + "  ├── ALIAS: " + n.TableAlias)
		}
		v.add(cur + "  └── WHERE (MANDATORY)")
		v.visit(n.Where, indent+2, "COND")

	case *InsertStatement:
		v.add(prefix + "INSERT_STATEMENT")
		v.add(cur + "  ├── INTO: " + n.Table.Name)
		if len(n.Columns) > 0 {
			v.add(cur + "  ├── COLUMNS")
			for _, c := range n.Columns {
				v.add(cur + "  │   └── " + c.Name)
			}
		}
		if n.Source != nil {
			v.add(cur + "  └── SOURCE")
			v.visit(n.Source, indent+2, "SELECT")
		} else if len(n.ValueRows) > 0 {
			for i, row := range n.ValueRows {
				v.add(cur + "  ├── VALUES ROW #" + itoa(i+1))
				for _, val := range row {
					v.visit(val, indent+3, "VAL")
				}
			}
		} else {
			v.add(cur + "  └── VALUES")
			for _, val := range n.Values {
				v.visit(val, indent+2, "VAL")
			}
		}

	case *TruncateStatement:
		v.add(prefix + "TRUNCATE_STATEMENT")
		v.add(cur + "  └── TABLE: " + n.Table.Name)

	case *DropTableStatement:
		ife := ""
		if n.IfExists {
			ife = " IF EXISTS"
		}
		v.add(prefix + "DROP_TABLE_STATEMENT" + ife)
		if n.Table != nil {
			v.add(cur + "  └── TABLE: " + n.Table.Name)
		}

	case *CreateTableStatement:
		ifn := ""
		if n.IfNotExists {
			ifn = " IF NOT EXISTS"
		}
		v.add(prefix + "CREATE_TABLE_STATEMENT" + ifn)
		if n.Table != nil {
			v.add(cur + "  ├── TABLE: " + n.Table.Name)
		}
		if len(n.Columns) > 0 {
			v.add(cur + "  └── COLUMNS (" + itoa(len(n.Columns)) + ")")
		}

	case *AlterTableStatement:
		v.add(prefix + "ALTER_TABLE_STATEMENT")
		if n.Table != nil {
			v.add(cur + "  ├── TABLE: " + n.Table.Name)
		}
		if n.Action != "" {
			v.add(cur + "  ├── ACTION: " + n.Action)
		}
		if n.Column != nil {
			v.visit(n.Column, indent+2, "COLUMN")
		}

	case *SqlBulkCopyStatement:
		v.add(prefix + "BULK_COPY_STATEMENT")
		v.add(cur + "  └── TARGET TABLE: " + n.Table.Name)

	case *SetStatement:
		if n.IsOption {
			v.add(prefix + "SET_OPTION")
			if s, ok := n.Target.(Node); ok && s != nil {
				v.visit(s, indent+1, "OPTION")
			}
		} else {
			v.add(prefix + "SET_STATEMENT")
			if s, ok := n.Target.(Node); ok && s != nil {
				v.visit(s, indent+1, "TARGET")
			}
			if val, ok := n.Value.(Node); ok && val != nil {
				v.add(cur + "  └── VALUE")
				v.visit(val, indent+2, "EXPR")
			}
		}

	case *IfStatement:
		v.add(prefix + "IF_STATEMENT")
		if n.Condition != nil {
			v.add(cur + "  ├── CONDITION")
			v.visit(n.Condition, indent+2, "COND")
		}
		if len(n.ThenBlock) > 0 {
			v.add(cur + "  ├── THEN (" + itoa(len(n.ThenBlock)) + " stmt(s))")
			for _, s := range n.ThenBlock {
				v.visit(s, indent+2, "THEN")
			}
		}
		if len(n.ElseBlock) > 0 {
			v.add(cur + "  └── ELSE (" + itoa(len(n.ElseBlock)) + " stmt(s))")
			for _, s := range n.ElseBlock {
				v.visit(s, indent+2, "ELSE")
			}
		}

	case *ExecStatement:
		proc := "?"
		if id, ok := n.ProcName.(*IdentifierNode); ok {
			proc = strings.Join(append(append([]string{}, id.Qualifiers...), id.Name), ".")
		}
		v.add(prefix + "EXEC_STATEMENT: " + proc)
		if n.ReturnVar != nil {
			v.add(cur + "  ├── RETURN_VAR: " + reprNode(n.ReturnVar))
		}
		for _, a := range n.Args {
			v.visit(a, indent+1, "ARG")
		}
		for _, kv := range n.NamedArgs {
			v.visit(kv, indent+1, "PARAM")
		}

	case *MergeStatement:
		v.add(prefix + "MERGE_STATEMENT")
		if n.Target != nil {
			al := ""
			if n.TargetAlias != "" {
				al = " AS " + n.TargetAlias
			}
			v.add(cur + "  ├── TARGET: " + n.Target.Name + al)
		}
		if n.Source != nil {
			v.add(cur + "  ├── USING")
			v.visit(n.Source, indent+2, "SOURCE")
			if n.SourceAlias != "" {
				v.add(cur + "    └── ALIAS: " + n.SourceAlias)
			}
		}
		if n.OnCondition != nil {
			v.add(cur + "  ├── ON")
			v.visit(n.OnCondition, indent+2, "COND")
		}
		for _, c := range n.Clauses {
			v.visit(c, indent+1, "CLAUSE")
		}

	case *MergeClauseNode:
		mt := n.MatchType
		if mt == "" {
			mt = "?"
		}
		ac := n.Action
		if ac == "" {
			ac = "?"
		}
		v.add(prefix + "MERGE_CLAUSE: " + mt + " / " + ac)
		if n.Condition != nil {
			v.visit(n.Condition, indent+1, "AND COND")
		}
		for _, a := range n.SetClauses {
			v.visit(a, indent+1, "SET")
		}

	case *PrintStatement:
		v.add(prefix + "PRINT_STATEMENT")
		if n.Expr != nil {
			v.visit(n.Expr, indent+1, "EXPR")
		}

	case *FunctionCallNode:
		argInfo := " ()"
		if len(n.Args) > 0 {
			argInfo = " (" + itoa(len(n.Args)) + " args)"
		}
		v.add(prefix + "FUNCTION: " + n.Name + argInfo + inferTypeInfo(n) + aliasInfo(n))
		for _, a := range n.Args {
			v.visit(a, indent+1, "ARG")
		}
		if n.OverClause != nil {
			v.visit(n.OverClause, indent+1, "OVER")
		}

	case *CaseExpressionNode:
		v.add(prefix + "CASE_EXPRESSION" + inferTypeInfo(n))
		if n.InputExpr != nil {
			v.visit(n.InputExpr, indent+2, "INPUT")
		}
		for i, br := range n.Branches {
			v.add(cur + "  ├── BRANCH #" + itoa(i+1))
			v.visit(br.When, indent+3, "WHEN")
			v.visit(br.Then, indent+3, "THEN")
		}
		if n.ElseExpr != nil {
			v.add(cur + "  ├── ELSE")
			v.visit(n.ElseExpr, indent+2, "RESULT")
		}
		if n.Alias != "" {
			v.add(cur + "  └── ALIAS: " + n.Alias)
		}

	case *BinaryExpressionNode:
		v.add(prefix + "EXPRESSION: " + n.Operator + inferTypeInfo(n))
		v.visit(n.Left, indent+1, "LEFT")
		if list, ok := n.Right.(nodeList); ok {
			v.add(ind(indent+1) + "└── LIST")
			for i, item := range list {
				v.add(ind(indent+2) + "├── ITEM#" + itoa(i+1))
				v.visit(item, indent+3, "")
			}
		} else {
			v.visit(n.Right, indent+1, "RIGHT")
		}

	case *BetweenExpressionNode:
		op := "BETWEEN"
		if n.IsNot {
			op = "NOT BETWEEN"
		}
		v.add(prefix + "EXPRESSION: " + op + inferTypeInfo(n))
		v.add(cur + "  ├── TARGET")
		v.visit(n.Expr, indent+2, "TARGET")
		v.add(cur + "  ├── LOW")
		v.visit(n.Low, indent+2, "LOW")
		v.add(cur + "  └── HIGH")
		v.visit(n.High, indent+2, "HIGH")

	case *CastExpressionNode:
		fn := "CAST"
		if n.IsConvert {
			fn = "CONVERT"
		}
		v.add(prefix + fn + " TO " + n.TargetType + inferTypeInfo(n))
		v.add(cur + "  └── EXPR")
		v.visit(n.Expr, indent+2, "EXPR")

	case *IdentifierNode:
		full := n.Name
		if len(n.Qualifiers) > 0 {
			full = strings.Join(append(append([]string{}, n.Qualifiers...), n.Name), ".")
		}
		resolved := ""
		if n.ResolvedTable != "" {
			resolved = " → " + n.ResolvedTable
		}
		v.add(prefix + "IDENTIFIER: " + full + resolved + inferTypeInfo(n) + aliasInfo(n))

	case *LiteralNode:
		v.add(prefix + "LITERAL: " + n.Value + inferTypeInfo(n))

	case *JoinNode:
		v.add(prefix + n.Type + "_JOIN")
		v.visit(n.Table, indent+1, "TABLE")
		if n.Alias != "" {
			v.add(cur + "    └── ALIAS: " + n.Alias)
		}
		if n.OnCondition != nil {
			v.add(cur + "    └── ON")
			v.visit(n.OnCondition, indent+3, "COND")
		}

	case *OrderByNode:
		v.add(prefix + "SORT_BY: " + n.Direction)
		v.visit(n.Column, indent+1, "COL")

	case *AssignmentNode:
		v.add(prefix + "SET_OP: =")
		v.visit(n.Column, indent+1, "TARGET")
		v.visit(n.Right, indent+1, "VALUE")

	case *DeclareStatement:
		v.add(prefix + "DECLARE_STATEMENT")
		v.add(cur + "  ├── VAR: " + n.VarName)
		v.add(cur + "  ├── TYPE: " + n.VarType)
		if n.DefaultValue != nil {
			v.add(cur + "  └── DEFAULT")
			v.visit(n.DefaultValue, indent+2, "EXPR")
		}

	case *ApplyNode:
		v.add(prefix + n.Type + "_APPLY")
		if n.Alias != "" {
			v.add(cur + "  ├── ALIAS: " + n.Alias)
		}
		v.add(cur + "  └── SUBQUERY")
		v.visit(n.Subquery, indent+2, "SUBQUERY")

	case *OverClauseNode:
		v.add(prefix + "OVER_CLAUSE")
		if len(n.PartitionBy) > 0 {
			v.add(cur + "  ├── PARTITION_BY")
			for _, e := range n.PartitionBy {
				v.visit(e, indent+2, "EXPR")
			}
		}
		if len(n.OrderBy) > 0 {
			v.add(cur + "  ├── ORDER_BY")
			for _, o := range n.OrderBy {
				v.visit(o, indent+2, "COL")
			}
		}
		if n.FrameType != "" {
			v.add(cur + "  └── FRAME: " + n.FrameType)
			if n.FrameStart != "" {
				v.add(cur + "      ├── START: " + n.FrameStart)
			}
			if n.FrameEnd != "" {
				v.add(cur + "      └── END: " + n.FrameEnd)
			}
		}
	}
}

// reprNode 對照 Python f-string 對 IdentifierNode 的 str()（無 __str__ → 物件 repr）。
// return_var 只在 EXEC 出現，Python 印的是物件 repr；實務上罕見，簡化為名稱。
func reprNode(n Node) string {
	if id, ok := n.(*IdentifierNode); ok {
		return id.Name
	}
	return ""
}
