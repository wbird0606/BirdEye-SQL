package birdeye

// AST 節點對照 Python birdeye/ast.py。Go struct 名稱與 Python class 名稱一致，
// 因為 serializer / visualizer / reconstructor / intent 都靠 class 名稱分派，
// 且 serializer 會輸出 node_type（= class 名稱，見 ADR 0002）。
//
// 慣例：
//   - 節點一律以指標 *T 傳遞
//   - 子節點型別多為 Node（對應 Python 的鴨子型別），nil == Python None
//   - InferredType == "" 視同 "UNKNOWN"；建構子會填 "UNKNOWN"
//   - string 欄位為空字串時，serializer 依 Python 對應欄位決定輸出 "" 或 null

// Node 是所有 AST 節點的標記介面。
type Node interface{ aNode() }

type baseNode struct{}

func (baseNode) aNode() {}

// NodeMeta 保存 binder / runner 掛在「根節點」上的執行期資訊（Python 用 setattr）。
// Params 用有序 slice 保存以維持 serializer 輸出的 key 順序（byte-parity，ADR 0002）。
type NodeMeta struct {
	ParamInputMode string         // "" = 未設定
	Params         []ParamBinding // nil = 未綁定參數
}

// ParamBinding 對照 Python 的 bound_params[name] / bound_param_values[name]。
type ParamBinding struct {
	Name  string // "@X"（大寫）
	Type  string
	Value any
}

// exprBase 對照 Python ExpressionNode 基底（alias / inferred_type）。
// 真正的運算式節點，以及可當純量子查詢的 SelectStatement / UnionStatement，都內嵌它。
type exprBase struct {
	Alias        string
	InferredType string
}

func (e *exprBase) exprRef() *exprBase { return e }

func newExprBase() exprBase { return exprBase{InferredType: "UNKNOWN"} }

// exprOf 取出節點的 exprBase；沒有則回傳 nil。
func exprOf(n Node) *exprBase {
	if e, ok := n.(interface{ exprRef() *exprBase }); ok {
		return e.exprRef()
	}
	return nil
}

// ── 1. 語句節點 ─────────────────────────────────────────────────────────────

type SelectStatement struct {
	baseNode
	NodeMeta
	exprBase // 允許當純量子查詢

	IsSelectStar bool
	IsDistinct   bool
	StarPrefixes []string
	TopCount     *int
	TopPercent   bool
	OffsetCount  *int
	FetchCount   *int
	Columns      []Node
	Table        Node // *IdentifierNode 或衍生資料表 (*SelectStatement / *UnionStatement)
	TableAlias   string
	Joins        []*JoinNode
	Where        Node
	GroupBy      []Node
	Having       Node
	OrderBy      []*OrderByNode
	CTEs         []*CTENode
	IntoTable    *IdentifierNode
	Applies      []*ApplyNode
	ForClause    string // FOR XML / FOR JSON 子句（已白名單正規化），空字串表示無
	Pivot        *PivotClause
}

// PivotClause 為基底 FROM 來源（Table／TableAlias）之後接的 PIVOT／UNPIVOT（KNOWN_DEVIATIONS A18）。
// 轉置後之輸出欄位僅能經 Alias 引用；原來源之別名不再可見。
type PivotClause struct {
	Kind     string   // "PIVOT" 或 "UNPIVOT"
	Agg      string   // PIVOT 之聚合函式（SUM／MAX／MIN／AVG／COUNT）；UNPIVOT 為空
	ValueCol string   // PIVOT：被聚合之欄位；UNPIVOT：轉置後承載值之新欄位名稱
	ForCol   string   // PIVOT：其值成為新欄位之來源欄位；UNPIVOT：承載來源欄位名稱之新欄位
	InList   []string // PIVOT：新欄位名稱；UNPIVOT：被轉為列之來源欄位
	Alias    string   // 必填
}

func NewSelectStatement() *SelectStatement {
	return &SelectStatement{exprBase: newExprBase()}
}

type CTENode struct {
	baseNode
	Name    string
	Columns []string // 選用之欄位清單：WITH r(a, b) AS (...)
	Query   Node     // *SelectStatement 或 *UnionStatement
}

type UpdateStatement struct {
	baseNode
	NodeMeta
	Table      *IdentifierNode
	TableAlias string
	SetClauses []*AssignmentNode
	CTEs       []*CTENode
	Where      Node
	// T-SQL 之 UPDATE ... FROM ...：Table 可為 FROM 清單內之別名（見 KNOWN_DEVIATIONS A16）
	FromTable Node
	FromAlias string
	FromJoins []*JoinNode
}

type DeleteStatement struct {
	baseNode
	NodeMeta
	Table      *IdentifierNode
	TableAlias string
	Where      Node
	CTEs       []*CTENode
	// T-SQL 之 DELETE [FROM] 目標 FROM ...
	FromTable Node
	FromAlias string
	FromJoins []*JoinNode
}

type InsertStatement struct {
	baseNode
	NodeMeta
	Table     *IdentifierNode
	Columns   []*IdentifierNode
	Values    []Node   // 單列（向後相容）
	ValueRows [][]Node // 多列
	Source    Node     // *SelectStatement / *UnionStatement（INSERT-SELECT）
}

type TruncateStatement struct {
	baseNode
	NodeMeta
	Table *IdentifierNode
}

type DeclareStatement struct {
	baseNode
	NodeMeta
	VarName      string
	VarType      string
	DefaultValue Node
}

type SqlBulkCopyStatement struct {
	baseNode
	NodeMeta
	Table *IdentifierNode
}

type UnionStatement struct {
	baseNode
	NodeMeta
	exprBase

	Left     Node
	Operator string // UNION / UNION ALL / INTERSECT / EXCEPT
	Right    Node
	Columns  []Node // binder 合併後的虛擬投影欄位
}

func NewUnionStatement(left Node, op string, right Node) *UnionStatement {
	return &UnionStatement{exprBase: newExprBase(), Left: left, Operator: op, Right: right}
}

type ScriptNode struct {
	baseNode
	NodeMeta
	Statements []Node
}

// ── 2. 運算式節點 ───────────────────────────────────────────────────────────

type IdentifierNode struct {
	baseNode
	exprBase
	Name              string
	Qualifiers        []string
	ResolvedTable     string // binder 解析非限定欄位後填入（table 名，不含 schema）
	ResolvedFromParam string // 結構性參數解析來源（"@X"）
}

func NewIdentifier(name string, qualifiers []string) *IdentifierNode {
	return &IdentifierNode{exprBase: newExprBase(), Name: name, Qualifiers: qualifiers}
}

// Qualifier 對照 Python property：qualifiers 以 "." 相接，無則空字串。
func (n *IdentifierNode) Qualifier() string {
	if len(n.Qualifiers) == 0 {
		return ""
	}
	out := n.Qualifiers[0]
	for _, q := range n.Qualifiers[1:] {
		out += "." + q
	}
	return out
}

type LiteralNode struct {
	baseNode
	exprBase
	Value string
	Type  TokenType
}

func NewLiteral(value string, typ TokenType) *LiteralNode {
	n := &LiteralNode{exprBase: newExprBase(), Value: value, Type: typ}
	switch typ {
	case NumericLiteral:
		n.InferredType = "INT"
	case StringLiteral:
		n.InferredType = "NVARCHAR"
	}
	return n
}

type BinaryExpressionNode struct {
	baseNode
	exprBase
	Left     Node
	Operator string
	Right    Node // Node、[]Node（IN / ANY / ALL 清單）或子查詢
}

func NewBinaryExpr(left Node, op string, right Node) *BinaryExpressionNode {
	return &BinaryExpressionNode{exprBase: newExprBase(), Left: left, Operator: op, Right: right}
}

type FunctionCallNode struct {
	baseNode
	exprBase
	Name       string
	Args       []Node
	OverClause *OverClauseNode
}

func NewFunctionCall(name string, args []Node) *FunctionCallNode {
	return &FunctionCallNode{exprBase: newExprBase(), Name: name, Args: args}
}

type CaseBranch struct {
	When Node
	Then Node
}

type CaseExpressionNode struct {
	baseNode
	exprBase
	InputExpr Node
	Branches  []CaseBranch
	ElseExpr  Node
}

func NewCaseExpr(input Node) *CaseExpressionNode {
	return &CaseExpressionNode{exprBase: newExprBase(), InputExpr: input}
}

type BetweenExpressionNode struct {
	baseNode
	exprBase
	Expr  Node
	Low   Node
	High  Node
	IsNot bool
}

func NewBetweenExpr(expr, low, high Node, isNot bool) *BetweenExpressionNode {
	return &BetweenExpressionNode{exprBase: newExprBase(), Expr: expr, Low: low, High: high, IsNot: isNot}
}

type CastExpressionNode struct {
	baseNode
	exprBase
	Expr       Node
	TargetType string
	IsConvert  bool
}

func NewCastExpr(expr Node, targetType string, isConvert bool) *CastExpressionNode {
	return &CastExpressionNode{exprBase: newExprBase(), Expr: expr, TargetType: targetType, IsConvert: isConvert}
}

type OverClauseNode struct {
	baseNode
	PartitionBy []Node
	OrderBy     []*OrderByNode
	FrameType   string // "ROWS" / "RANGE" / ""
	FrameStart  string
	FrameEnd    string
}

// ── 3. 結構輔助節點 ─────────────────────────────────────────────────────────

type JoinNode struct {
	baseNode
	Type        string // INNER / LEFT / RIGHT / FULL / CROSS
	Table       Node
	Alias       string
	OnCondition Node
	OnLeft      Node
	OnRight     Node
}

func NewJoinNode(typ string, table Node) *JoinNode {
	return &JoinNode{Type: typ, Table: table}
}

type ApplyNode struct {
	baseNode
	Type     string // CROSS / OUTER
	Subquery Node
	Alias    string
	Columns  []Node
}

type OrderByNode struct {
	baseNode
	Column    Node
	Direction string // ASC / DESC
}

type AssignmentNode struct {
	baseNode
	Column Node // *IdentifierNode
	Right  Node
}

// ── 4. 新語法節點 ───────────────────────────────────────────────────────────

type IfStatement struct {
	baseNode
	NodeMeta
	Condition Node
	ThenBlock []Node
	ElseBlock []Node
}

type ExecStatement struct {
	baseNode
	NodeMeta
	ProcName  Node // *IdentifierNode
	Args      []Node
	NamedArgs []*AssignmentNode
	ReturnVar Node // *IdentifierNode
}

type SetStatement struct {
	baseNode
	NodeMeta
	Target   any // *IdentifierNode 或 string（SET OPTION）
	Value    any // Node 或 string（SET OPTION）
	IsOption bool
}

type ColumnDefinitionNode struct {
	baseNode
	Name         string
	DataType     string
	Nullable     bool
	Default      Node
	IsIdentity   bool
	IsPrimaryKey bool
}

func NewColumnDefinition() *ColumnDefinitionNode {
	return &ColumnDefinitionNode{Nullable: true}
}

type CreateTableStatement struct {
	baseNode
	NodeMeta
	Table       *IdentifierNode
	IfNotExists bool
	Columns     []*ColumnDefinitionNode
}

type DropTableStatement struct {
	baseNode
	NodeMeta
	Table    *IdentifierNode
	IfExists bool
}

type AlterTableStatement struct {
	baseNode
	NodeMeta
	Table  *IdentifierNode
	Action string // ADD / DROP
	Column Node   // *ColumnDefinitionNode（ADD）或 *IdentifierNode（DROP）
}

type MergeClauseNode struct {
	baseNode
	MatchType     string
	Condition     Node
	Action        string // UPDATE / INSERT / DELETE
	SetClauses    []*AssignmentNode
	InsertColumns []*IdentifierNode
	InsertValues  []Node
}

type MergeStatement struct {
	baseNode
	NodeMeta
	Target      *IdentifierNode
	TargetAlias string
	Source      Node
	SourceAlias string
	OnCondition Node
	Clauses     []*MergeClauseNode
}

type PrintStatement struct {
	baseNode
	NodeMeta
	Expr Node
}

// ── nodeTypeName：回傳 Python class 名稱 ────────────────────────────────────

func nodeTypeName(n Node) string {
	switch n.(type) {
	case *SelectStatement:
		return "SelectStatement"
	case *CTENode:
		return "CTENode"
	case *UpdateStatement:
		return "UpdateStatement"
	case *DeleteStatement:
		return "DeleteStatement"
	case *InsertStatement:
		return "InsertStatement"
	case *TruncateStatement:
		return "TruncateStatement"
	case *DeclareStatement:
		return "DeclareStatement"
	case *SqlBulkCopyStatement:
		return "SqlBulkCopyStatement"
	case *UnionStatement:
		return "UnionStatement"
	case *ScriptNode:
		return "ScriptNode"
	case *IdentifierNode:
		return "IdentifierNode"
	case *LiteralNode:
		return "LiteralNode"
	case *BinaryExpressionNode:
		return "BinaryExpressionNode"
	case *FunctionCallNode:
		return "FunctionCallNode"
	case *CaseExpressionNode:
		return "CaseExpressionNode"
	case *BetweenExpressionNode:
		return "BetweenExpressionNode"
	case *CastExpressionNode:
		return "CastExpressionNode"
	case *OverClauseNode:
		return "OverClauseNode"
	case *JoinNode:
		return "JoinNode"
	case *ApplyNode:
		return "ApplyNode"
	case *OrderByNode:
		return "OrderByNode"
	case *AssignmentNode:
		return "AssignmentNode"
	case *IfStatement:
		return "IfStatement"
	case *ExecStatement:
		return "ExecStatement"
	case *SetStatement:
		return "SetStatement"
	case *ColumnDefinitionNode:
		return "ColumnDefinitionNode"
	case *CreateTableStatement:
		return "CreateTableStatement"
	case *DropTableStatement:
		return "DropTableStatement"
	case *AlterTableStatement:
		return "AlterTableStatement"
	case *MergeClauseNode:
		return "MergeClauseNode"
	case *MergeStatement:
		return "MergeStatement"
	case *PrintStatement:
		return "PrintStatement"
	default:
		return ""
	}
}

// metaOf 取出語句節點的 *NodeMeta；非語句回傳 nil。
func metaOf(n Node) *NodeMeta {
	switch s := n.(type) {
	case *SelectStatement:
		return &s.NodeMeta
	case *UpdateStatement:
		return &s.NodeMeta
	case *DeleteStatement:
		return &s.NodeMeta
	case *InsertStatement:
		return &s.NodeMeta
	case *TruncateStatement:
		return &s.NodeMeta
	case *DeclareStatement:
		return &s.NodeMeta
	case *SqlBulkCopyStatement:
		return &s.NodeMeta
	case *UnionStatement:
		return &s.NodeMeta
	case *ScriptNode:
		return &s.NodeMeta
	case *IfStatement:
		return &s.NodeMeta
	case *ExecStatement:
		return &s.NodeMeta
	case *SetStatement:
		return &s.NodeMeta
	case *CreateTableStatement:
		return &s.NodeMeta
	case *DropTableStatement:
		return &s.NodeMeta
	case *AlterTableStatement:
		return &s.NodeMeta
	case *MergeStatement:
		return &s.NodeMeta
	case *PrintStatement:
		return &s.NodeMeta
	}
	return nil
}
