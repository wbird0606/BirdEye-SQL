package birdeye

import "fmt"

// TokenType 對應 Python birdeye/lexer.py 的 TokenType enum。
// String() 必須回傳與 Python `TokenType.<name>` 相同的字串，因為
// serializer 對 LiteralNode 會輸出 `"type": node.type.name`（見 ADR 0002）。
type TokenType int

const (
	// 關鍵字
	KwSelect TokenType = iota
	KwFrom
	KwAs
	KwWhere
	KwUpdate
	KwSet
	KwDelete
	KwInsert
	KwInto
	KwValues
	KwJoin
	KwInner
	KwLeft
	KwRight
	KwUnion
	KwAll
	KwWith
	KwTruncate
	KwTable
	KwAny
	KwOver
	KwPartition
	KwRows
	KwRange
	KwRow
	KwPreceding
	KwFollowing
	KwCurrent
	KwUnbounded
	KwOn
	KwAnd
	KwOr
	KwTop
	KwOrder
	KwBy
	KwAsc
	KwDesc
	KwGroup
	KwHaving
	KwIn
	KwExists
	KwIs
	KwNot
	KwNull
	KwLike
	KwBetween
	KwCast
	KwConvert
	KwDistinct
	KwPercent
	KwFull
	KwOffset
	KwFetch
	KwNext
	KwOnly
	KwDeclare
	KwGo
	KwCross
	KwApply
	KwOuter
	KwIntersect
	KwExcept
	KwIf
	KwBegin
	KwExec
	KwCreate
	KwDrop
	KwAlter
	KwMerge
	KwPrint
	KwAdd
	KwMatched
	KwUsing
	KwCase
	KwWhen
	KwThen
	KwElse
	KwEnd

	// 識別符與字面值
	Identifier
	StringLiteral
	NumericLiteral

	// 符號
	SymAsterisk
	SymComma
	SymDot
	SymEqual
	SymPlus
	SymMinus
	SymSlash
	SymLParen
	SymRParen
	SymSemicolon
	SymGT
	SymLT
	SymGE
	SymLE
	SymNE
	SymPercent
	SymAmpersand
	SymPipe
	SymCaret
	SymTilde

	EOF
)

var tokenTypeName = [...]string{
	KwSelect:    "KEYWORD_SELECT",
	KwFrom:      "KEYWORD_FROM",
	KwAs:        "KEYWORD_AS",
	KwWhere:     "KEYWORD_WHERE",
	KwUpdate:    "KEYWORD_UPDATE",
	KwSet:       "KEYWORD_SET",
	KwDelete:    "KEYWORD_DELETE",
	KwInsert:    "KEYWORD_INSERT",
	KwInto:      "KEYWORD_INTO",
	KwValues:    "KEYWORD_VALUES",
	KwJoin:      "KEYWORD_JOIN",
	KwInner:     "KEYWORD_INNER",
	KwLeft:      "KEYWORD_LEFT",
	KwRight:     "KEYWORD_RIGHT",
	KwUnion:     "KEYWORD_UNION",
	KwAll:       "KEYWORD_ALL",
	KwWith:      "KEYWORD_WITH",
	KwTruncate:  "KEYWORD_TRUNCATE",
	KwTable:     "KEYWORD_TABLE",
	KwAny:       "KEYWORD_ANY",
	KwOver:      "KEYWORD_OVER",
	KwPartition: "KEYWORD_PARTITION",
	KwRows:      "KEYWORD_ROWS",
	KwRange:     "KEYWORD_RANGE",
	KwRow:       "KEYWORD_ROW",
	KwPreceding: "KEYWORD_PRECEDING",
	KwFollowing: "KEYWORD_FOLLOWING",
	KwCurrent:   "KEYWORD_CURRENT",
	KwUnbounded: "KEYWORD_UNBOUNDED",
	KwOn:        "KEYWORD_ON",
	KwAnd:       "KEYWORD_AND",
	KwOr:        "KEYWORD_OR",
	KwTop:       "KEYWORD_TOP",
	KwOrder:     "KEYWORD_ORDER",
	KwBy:        "KEYWORD_BY",
	KwAsc:       "KEYWORD_ASC",
	KwDesc:      "KEYWORD_DESC",
	KwGroup:     "KEYWORD_GROUP",
	KwHaving:    "KEYWORD_HAVING",
	KwIn:        "KEYWORD_IN",
	KwExists:    "KEYWORD_EXISTS",
	KwIs:        "KEYWORD_IS",
	KwNot:       "KEYWORD_NOT",
	KwNull:      "KEYWORD_NULL",
	KwLike:      "KEYWORD_LIKE",
	KwBetween:   "KEYWORD_BETWEEN",
	KwCast:      "KEYWORD_CAST",
	KwConvert:   "KEYWORD_CONVERT",
	KwDistinct:  "KEYWORD_DISTINCT",
	KwPercent:   "KEYWORD_PERCENT",
	KwFull:      "KEYWORD_FULL",
	KwOffset:    "KEYWORD_OFFSET",
	KwFetch:     "KEYWORD_FETCH",
	KwNext:      "KEYWORD_NEXT",
	KwOnly:      "KEYWORD_ONLY",
	KwDeclare:   "KEYWORD_DECLARE",
	KwGo:        "KEYWORD_GO",
	KwCross:     "KEYWORD_CROSS",
	KwApply:     "KEYWORD_APPLY",
	KwOuter:     "KEYWORD_OUTER",
	KwIntersect: "KEYWORD_INTERSECT",
	KwExcept:    "KEYWORD_EXCEPT",
	KwIf:        "KEYWORD_IF",
	KwBegin:     "KEYWORD_BEGIN",
	KwExec:      "KEYWORD_EXEC",
	KwCreate:    "KEYWORD_CREATE",
	KwDrop:      "KEYWORD_DROP",
	KwAlter:     "KEYWORD_ALTER",
	KwMerge:     "KEYWORD_MERGE",
	KwPrint:     "KEYWORD_PRINT",
	KwAdd:       "KEYWORD_ADD",
	KwMatched:   "KEYWORD_MATCHED",
	KwUsing:     "KEYWORD_USING",
	KwCase:      "KEYWORD_CASE",
	KwWhen:      "KEYWORD_WHEN",
	KwThen:      "KEYWORD_THEN",
	KwElse:      "KEYWORD_ELSE",
	KwEnd:       "KEYWORD_END",

	Identifier:     "IDENTIFIER",
	StringLiteral:  "STRING_LITERAL",
	NumericLiteral: "NUMERIC_LITERAL",

	SymAsterisk:  "SYMBOL_ASTERISK",
	SymComma:     "SYMBOL_COMMA",
	SymDot:       "SYMBOL_DOT",
	SymEqual:     "SYMBOL_EQUAL",
	SymPlus:      "SYMBOL_PLUS",
	SymMinus:     "SYMBOL_MINUS",
	SymSlash:     "SYMBOL_SLASH",
	SymLParen:    "SYMBOL_LPAREN",
	SymRParen:    "SYMBOL_RPAREN",
	SymSemicolon: "SYMBOL_SEMICOLON",
	SymGT:        "SYMBOL_GT",
	SymLT:        "SYMBOL_LT",
	SymGE:        "SYMBOL_GE",
	SymLE:        "SYMBOL_LE",
	SymNE:        "SYMBOL_NE",
	SymPercent:   "SYMBOL_PERCENT",
	SymAmpersand: "SYMBOL_AMPERSAND",
	SymPipe:      "SYMBOL_PIPE",
	SymCaret:     "SYMBOL_CARET",
	SymTilde:     "SYMBOL_TILDE",

	EOF: "EOF",
}

func (t TokenType) String() string {
	if int(t) >= 0 && int(t) < len(tokenTypeName) && tokenTypeName[t] != "" {
		return tokenTypeName[t]
	}
	return fmt.Sprintf("TokenType(%d)", int(t))
}

// keywords 對照 Python lexer.tokenize() 內的 keywords dict（大寫查表）。
var keywords = map[string]TokenType{
	"SELECT": KwSelect, "FROM": KwFrom, "AS": KwAs, "WHERE": KwWhere,
	"UPDATE": KwUpdate, "SET": KwSet, "DELETE": KwDelete, "INSERT": KwInsert,
	"INTO": KwInto, "VALUES": KwValues, "JOIN": KwJoin, "INNER": KwInner,
	"LEFT": KwLeft, "RIGHT": KwRight, "UNION": KwUnion, "ALL": KwAll,
	"WITH": KwWith, "TRUNCATE": KwTruncate, "TABLE": KwTable, "ANY": KwAny,
	"OVER": KwOver, "PARTITION": KwPartition, "ROWS": KwRows, "RANGE": KwRange,
	"ROW": KwRow, "PRECEDING": KwPreceding, "FOLLOWING": KwFollowing,
	"CURRENT": KwCurrent, "UNBOUNDED": KwUnbounded, "ON": KwOn, "AND": KwAnd,
	"OR": KwOr, "TOP": KwTop, "ORDER": KwOrder, "BY": KwBy, "ASC": KwAsc,
	"DESC": KwDesc, "GROUP": KwGroup, "HAVING": KwHaving, "IN": KwIn,
	"EXISTS": KwExists, "IS": KwIs, "NOT": KwNot, "NULL": KwNull, "LIKE": KwLike,
	"BETWEEN": KwBetween, "CAST": KwCast, "CONVERT": KwConvert,
	"DISTINCT": KwDistinct, "PERCENT": KwPercent, "FULL": KwFull,
	"OFFSET": KwOffset, "FETCH": KwFetch, "NEXT": KwNext, "ONLY": KwOnly,
	"DECLARE": KwDeclare, "GO": KwGo, "CROSS": KwCross, "APPLY": KwApply,
	"OUTER": KwOuter, "INTERSECT": KwIntersect, "EXCEPT": KwExcept,
	"CASE": KwCase, "WHEN": KwWhen, "THEN": KwThen, "ELSE": KwElse, "END": KwEnd,
	"IF": KwIf, "BEGIN": KwBegin, "EXEC": KwExec, "EXECUTE": KwExec,
	"CREATE": KwCreate, "DROP": KwDrop, "ALTER": KwAlter, "MERGE": KwMerge,
	"PRINT": KwPrint, "ADD": KwAdd, "MATCHED": KwMatched, "USING": KwUsing,
}

// Token 對照 Python 的 Token(type, value, start, end)。
// Start / End 是 rune（碼位）索引，與 Python 字串索引一致。
type Token struct {
	Type  TokenType
	Value string
	Start int
	End   int
}

func (t Token) String() string {
	return fmt.Sprintf("Token(%s, %q, %d, %d)", t.Type, t.Value, t.Start, t.End)
}
