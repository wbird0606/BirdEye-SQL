package birdeye

// ErrKind 是錯誤分類。對照 Python：SyntaxError→Syntax、SemanticError→Semantic、
// ValueError→Value、其餘→System。conformance 只比對分類（見 ADR 0002 / grilling Q3）。
type ErrKind int

const (
	ErrSyntax ErrKind = iota
	ErrSemantic
	ErrValue
	ErrSystem
)

func (k ErrKind) String() string {
	switch k {
	case ErrSyntax:
		return "syntax"
	case ErrSemantic:
		return "semantic"
	case ErrValue:
		return "value"
	default:
		return "system"
	}
}

// Error 是引擎所有面向使用者錯誤的統一型別。
type Error struct {
	Kind ErrKind
	Msg  string
}

func (e *Error) Error() string { return e.Msg }

func syntaxErr(msg string) *Error   { return &Error{ErrSyntax, msg} }
func semanticErr(msg string) *Error { return &Error{ErrSemantic, msg} }
func valueErr(msg string) *Error    { return &Error{ErrValue, msg} }
