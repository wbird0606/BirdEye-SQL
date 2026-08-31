package birdeye

import (
	"math"
	"reflect"
	"strconv"
	"strings"
)

// Serializer 對照 Python birdeye/serializer.py 的 ASTSerializer。
// 輸出與 Python json.dumps(obj, indent=2, ensure_ascii=False) 逐位元組一致
// （見 ADR 0002）。key 順序以手寫 ordered writer 精確複製 Python dict 插入順序。
type Serializer struct {
	paramInputMode string
}

func NewSerializer() *Serializer { return &Serializer{} }

// ── ordered JSON 值模型 ─────────────────────────────────────────────────────

type jkv struct {
	k string
	v any
}
type jobj []jkv
type jarr []any

// ToJSON 對照 to_json：從根節點的 meta 取 param_input_mode，再序列化並 indent=2 輸出。
func (s *Serializer) ToJSON(n Node) string {
	s.paramInputMode = ""
	if m := metaOf(n); m != nil {
		s.paramInputMode = m.ParamInputMode
	}
	var b strings.Builder
	encJSON(&b, s.serialize(n), 0)
	return b.String()
}

// ── 值編碼（Python json.dumps 風格）────────────────────────────────────────

func encIndent(b *strings.Builder, depth int) {
	for i := 0; i < depth; i++ {
		b.WriteString("  ")
	}
}

func encJSON(b *strings.Builder, v any, depth int) {
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if x {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case int:
		b.WriteString(strconv.Itoa(x))
	case float64:
		b.WriteString(encFloat(x))
	case string:
		encStr(b, x)
	case jobj:
		if len(x) == 0 {
			b.WriteString("{}")
			return
		}
		b.WriteString("{\n")
		for i, kv := range x {
			encIndent(b, depth+1)
			encStr(b, kv.k)
			b.WriteString(": ")
			encJSON(b, kv.v, depth+1)
			if i < len(x)-1 {
				b.WriteString(",")
			}
			b.WriteString("\n")
		}
		encIndent(b, depth)
		b.WriteString("}")
	case jarr:
		if len(x) == 0 {
			b.WriteString("[]")
			return
		}
		b.WriteString("[\n")
		for i, e := range x {
			encIndent(b, depth+1)
			encJSON(b, e, depth+1)
			if i < len(x)-1 {
				b.WriteString(",")
			}
			b.WriteString("\n")
		}
		encIndent(b, depth)
		b.WriteString("]")
	default:
		b.WriteString("null")
	}
}

// encStr 對照 Python json 的字串編碼（ensure_ascii=False）：
// 跳脫 " \ 與 <0x20 控制字元（\b\t\n\f\r 用短名，其餘 \u00XX），
// 不跳脫 / < > & 與非 ASCII（U+2028/2029 見 KNOWN_DEVIATIONS B2）。
func encStr(b *strings.Builder, s string) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			if r < 0x20 {
				const hex = "0123456789abcdef"
				b.WriteString(`\u00`)
				b.WriteByte(hex[(r>>4)&0xf])
				b.WriteByte(hex[r&0xf])
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
}

// encFloat 對照 Python repr(float) / json 的浮點輸出。
func encFloat(f float64) string {
	if math.IsInf(f, 1) {
		return "Infinity"
	}
	if math.IsInf(f, -1) {
		return "-Infinity"
	}
	if math.IsNaN(f) {
		return "NaN"
	}
	if f == math.Trunc(f) && math.Abs(f) < 1e16 {
		return strconv.FormatFloat(f, 'f', 1, 64) // 30 -> "30.0"（Python repr）
	}
	return strconv.FormatFloat(f, 'g', -1, 64)
}

// ── serialize：Node → ordered 值 ───────────────────────────────────────────

func (s *Serializer) serAny(v any) any {
	if v == nil {
		return nil
	}
	rv := reflect.ValueOf(v)
	switch rv.Kind() {
	case reflect.Ptr, reflect.Interface:
		if rv.IsNil() {
			return nil
		}
	case reflect.Slice:
		arr := jarr{}
		for i := 0; i < rv.Len(); i++ {
			arr = append(arr, s.serAny(rv.Index(i).Interface()))
		}
		return arr
	}
	switch x := v.(type) {
	case Node:
		return s.serialize(x)
	case string:
		return x
	case int:
		return x
	case bool:
		return x
	case float64:
		return x
	}
	return nil
}

func nilIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func derefInt(p *int) any {
	if p == nil {
		return nil
	}
	return *p
}

// dispIdentName 對照 _display_identifier_name：qmark 模式下 @P<n> 顯示為 "?"。
func (s *Serializer) dispIdentName(name string) string {
	if s.paramInputMode == "qmark" && isPositionalParam(name) {
		return "?"
	}
	return name
}

func isPositionalParam(name string) bool {
	u := strings.ToUpper(name)
	if !strings.HasPrefix(u, "@P") || len(u) <= 2 {
		return false
	}
	for _, c := range u[2:] {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

func (s *Serializer) serialize(n Node) any {
	if n == nil {
		return nil
	}
	if rv := reflect.ValueOf(n); (rv.Kind() == reflect.Ptr || rv.Kind() == reflect.Interface) && rv.IsNil() {
		return nil
	}

	obj := jobj{{"node_type", nodeTypeName(n)}}

	// 共同前綴：param_input_mode / bound_params / bound_param_values（僅語句根節點）
	if m := metaOf(n); m != nil {
		if m.ParamInputMode != "" {
			obj = append(obj, jkv{"param_input_mode", m.ParamInputMode})
		}
		if len(m.Params) > 0 {
			types := jobj{}
			vals := jobj{}
			for _, p := range m.Params {
				types = append(types, jkv{p.Name, p.Type})
				vals = append(vals, jkv{p.Name, s.serAny(p.Value)})
			}
			obj = append(obj, jkv{"bound_params", types})
			obj = append(obj, jkv{"bound_param_values", vals})
		}
	}
	// inferred_type：ExpressionNode 子類 + SelectStatement 有此屬性；UnionStatement 沒有
	if eb := exprOf(n); eb != nil {
		if _, isUnion := n.(*UnionStatement); !isUnion && eb.InferredType != "" && eb.InferredType != "UNKNOWN" {
			obj = append(obj, jkv{"inferred_type", eb.InferredType})
		}
	}

	switch x := n.(type) {
	case *ScriptNode:
		var stmts jarr
		for _, st := range x.Statements {
			if st != nil {
				stmts = append(stmts, s.serialize(st))
			}
		}
		if stmts == nil {
			stmts = jarr{}
		}
		obj = append(obj, jkv{"statements", stmts})

	case *SelectStatement:
		obj = append(obj,
			jkv{"ctes", s.serAny(x.CTEs)},
			jkv{"top", derefInt(x.TopCount)},
			jkv{"top_percent", x.TopPercent},
			jkv{"is_distinct", x.IsDistinct},
			jkv{"is_star", x.IsSelectStar},
			jkv{"columns", s.serAny(x.Columns)},
			jkv{"table", s.serialize2(x.Table)},
			jkv{"alias", nilIfEmpty(x.TableAlias)},
			jkv{"joins", s.serAny(x.Joins)},
			jkv{"applies", s.serAny(x.Applies)},
			jkv{"into_table", s.serialize2(x.IntoTable)},
			jkv{"where", s.serialize2(x.Where)},
			jkv{"group_by", s.serAny(x.GroupBy)},
			jkv{"having", s.serialize2(x.Having)},
			jkv{"order_by", s.serAny(x.OrderBy)},
			jkv{"offset_count", derefInt(x.OffsetCount)},
			jkv{"fetch_count", derefInt(x.FetchCount)},
		)

	case *UnionStatement:
		obj = append(obj,
			jkv{"op", x.Operator},
			jkv{"left", s.serialize2(x.Left)},
			jkv{"right", s.serialize2(x.Right)},
			jkv{"columns", s.serAny(x.Columns)},
		)

	case *CTENode:
		obj = append(obj, jkv{"name", x.Name}, jkv{"query", s.serialize2(x.Query)})

	case *BetweenExpressionNode:
		obj = append(obj,
			jkv{"target", s.serialize2(x.Expr)},
			jkv{"low", s.serialize2(x.Low)},
			jkv{"high", s.serialize2(x.High)},
			jkv{"is_not", x.IsNot},
		)

	case *CastExpressionNode:
		obj = append(obj,
			jkv{"expr", s.serialize2(x.Expr)},
			jkv{"target", x.TargetType},
			jkv{"is_convert", x.IsConvert},
		)

	case *UpdateStatement:
		obj = append(obj,
			jkv{"table", s.serialize2(x.Table)},
			jkv{"alias", nilIfEmpty(x.TableAlias)},
			jkv{"set", s.serAny(x.SetClauses)},
			jkv{"where", s.serialize2(x.Where)},
		)

	case *DeleteStatement:
		obj = append(obj,
			jkv{"table", s.serialize2(x.Table)},
			jkv{"alias", nilIfEmpty(x.TableAlias)},
			jkv{"where", s.serialize2(x.Where)},
		)

	case *InsertStatement:
		var values any
		if x.Source != nil {
			values = nil
		} else if len(x.ValueRows) <= 1 {
			values = s.serAny(x.Values)
		} else {
			values = nil
		}
		var valueRows any
		if len(x.ValueRows) > 0 {
			valueRows = s.serAny(x.ValueRows)
		}
		obj = append(obj,
			jkv{"table", s.serialize2(x.Table)},
			jkv{"columns", s.serAny(x.Columns)},
			jkv{"values", values},
			jkv{"value_rows", valueRows},
			jkv{"source", s.serialize2(x.Source)},
		)

	case *TruncateStatement:
		obj = append(obj, jkv{"table", s.serialize2(x.Table)})

	case *IdentifierNode:
		var internal any
		if s.paramInputMode == "qmark" && isPositionalParam(x.Name) {
			internal = strings.ToUpper(x.Name)
		}
		quals := jarr{}
		for _, q := range x.Qualifiers {
			quals = append(quals, q)
		}
		obj = append(obj,
			jkv{"name", s.dispIdentName(x.Name)},
			jkv{"internal_param_name", internal},
			jkv{"qualifiers", quals},
			jkv{"alias", nilIfEmpty(x.Alias)},
			jkv{"resolved_table", nilIfEmpty(x.ResolvedTable)},
		)

	case *LiteralNode:
		obj = append(obj, jkv{"value", x.Value}, jkv{"type", x.Type.String()})

	case *BinaryExpressionNode:
		obj = append(obj,
			jkv{"op", x.Operator},
			jkv{"left", s.serialize2(x.Left)},
			jkv{"right", s.serAny(x.Right)},
		)

	case *FunctionCallNode:
		var over any
		if x.OverClause != nil {
			over = s.serialize(x.OverClause)
		}
		obj = append(obj,
			jkv{"name", x.Name},
			jkv{"args", s.serAny(x.Args)},
			jkv{"over", over},
			jkv{"alias", nilIfEmpty(x.Alias)},
		)

	case *CaseExpressionNode:
		branches := jarr{}
		for _, br := range x.Branches {
			branches = append(branches, jobj{
				{"when", s.serialize2(br.When)},
				{"then", s.serialize2(br.Then)},
			})
		}
		obj = append(obj,
			jkv{"input", s.serialize2(x.InputExpr)},
			jkv{"branches", branches},
			jkv{"else", s.serialize2(x.ElseExpr)},
			jkv{"alias", nilIfEmpty(x.Alias)},
		)

	case *JoinNode:
		obj = append(obj,
			jkv{"join_type", x.Type},
			jkv{"table", s.serialize2(x.Table)},
			jkv{"alias", nilIfEmpty(x.Alias)},
			jkv{"on", s.serialize2(x.OnCondition)},
		)

	case *OrderByNode:
		obj = append(obj, jkv{"column", s.serialize2(x.Column)}, jkv{"direction", x.Direction})

	case *AssignmentNode:
		obj = append(obj, jkv{"column", s.serialize2(x.Column)}, jkv{"expr", s.serialize2(x.Right)})

	case *DeclareStatement:
		obj = append(obj,
			jkv{"var_name", x.VarName},
			jkv{"var_type", x.VarType},
			jkv{"default_value", s.serialize2(x.DefaultValue)},
		)

	case *ApplyNode:
		obj = append(obj,
			jkv{"apply_type", x.Type},
			jkv{"subquery", s.serialize2(x.Subquery)},
			jkv{"alias", nilIfEmpty(x.Alias)},
		)

	case *OverClauseNode:
		obj = append(obj,
			jkv{"partition_by", s.serAny(x.PartitionBy)},
			jkv{"order_by", s.serAny(x.OrderBy)},
			jkv{"frame_type", nilIfEmpty(x.FrameType)},
			jkv{"frame_start", nilIfEmpty(x.FrameStart)},
			jkv{"frame_end", nilIfEmpty(x.FrameEnd)},
		)

	case *IfStatement:
		obj = append(obj,
			jkv{"condition", s.serialize2(x.Condition)},
			jkv{"then_block", s.serAny(x.ThenBlock)},
			jkv{"else_block", s.serAny(x.ElseBlock)},
		)

	case *ExecStatement:
		obj = append(obj,
			jkv{"proc_name", s.serialize2(x.ProcName)},
			jkv{"args", s.serAny(x.Args)},
			jkv{"named_args", s.serAny(x.NamedArgs)},
			jkv{"return_var", s.serialize2(x.ReturnVar)},
		)

	case *SetStatement:
		obj = append(obj,
			jkv{"target", s.serStrOrNode(x.Target)},
			jkv{"value", s.serStrOrNode(x.Value)},
			jkv{"is_option", x.IsOption},
		)

	case *ColumnDefinitionNode:
		obj = append(obj,
			jkv{"name", x.Name},
			jkv{"data_type", x.DataType},
			jkv{"nullable", x.Nullable},
			jkv{"default", s.serialize2(x.Default)},
			jkv{"is_identity", x.IsIdentity},
			jkv{"is_primary_key", x.IsPrimaryKey},
		)

	case *CreateTableStatement:
		obj = append(obj,
			jkv{"table", s.serialize2(x.Table)},
			jkv{"if_not_exists", x.IfNotExists},
			jkv{"columns", s.serAny(x.Columns)},
		)

	case *DropTableStatement:
		obj = append(obj, jkv{"table", s.serialize2(x.Table)}, jkv{"if_exists", x.IfExists})

	case *AlterTableStatement:
		obj = append(obj,
			jkv{"table", s.serialize2(x.Table)},
			jkv{"action", x.Action},
			jkv{"column", s.serialize2(x.Column)},
		)

	case *MergeClauseNode:
		obj = append(obj,
			jkv{"match_type", x.MatchType},
			jkv{"condition", s.serialize2(x.Condition)},
			jkv{"action", x.Action},
			jkv{"set_clauses", s.serAny(x.SetClauses)},
			jkv{"insert_columns", s.serAny(x.InsertColumns)},
			jkv{"insert_values", s.serAny(x.InsertValues)},
		)

	case *MergeStatement:
		obj = append(obj,
			jkv{"target", s.serialize2(x.Target)},
			jkv{"target_alias", nilIfEmpty(x.TargetAlias)},
			jkv{"source", s.serialize2(x.Source)},
			jkv{"source_alias", nilIfEmpty(x.SourceAlias)},
			jkv{"on_condition", s.serialize2(x.OnCondition)},
			jkv{"clauses", s.serAny(x.Clauses)},
		)

	case *PrintStatement:
		obj = append(obj, jkv{"expr", s.serialize2(x.Expr)})
	}

	return obj
}

// serialize2 是 serialize 的 nil-safe 版本（用於子節點欄位；nil → null）。
func (s *Serializer) serialize2(n Node) any {
	if n == nil {
		return nil
	}
	if rv := reflect.ValueOf(n); (rv.Kind() == reflect.Ptr || rv.Kind() == reflect.Interface) && rv.IsNil() {
		return nil
	}
	// nodeList（IN/ANY/ALL 右側）在 Python 是 list → 走 serAny
	if nl, ok := n.(nodeList); ok {
		return s.serAny([]Node(nl))
	}
	return s.serialize(n)
}

func (s *Serializer) serStrOrNode(v any) any {
	switch x := v.(type) {
	case nil:
		return nil
	case string:
		return x
	case Node:
		return s.serialize2(x)
	}
	return nil
}
