package birdeye

import (
	"sort"
	"strconv"
	"strings"
	"unicode"
)

func itoa(i int) string { return strconv.Itoa(i) }

// strSet 把空白分隔的字串轉成 set。
func strSet(s string) map[string]bool {
	m := map[string]bool{}
	for _, w := range strings.Fields(s) {
		m[w] = true
	}
	return m
}

// capitalize 對照 Python str.capitalize()：首字母大寫，其餘小寫。
func capitalize(s string) string {
	if s == "" {
		return s
	}
	r := []rune(strings.ToLower(s))
	r[0] = unicode.ToUpper(r[0])
	return string(r)
}

func sortStrings(s []string) { sort.Strings(s) }

// sortedUnique 對照 Python sorted(list(set(xs)))。
func sortedUnique(xs []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, x := range xs {
		if !seen[x] {
			seen[x] = true
			out = append(out, x)
		}
	}
	sort.Strings(out)
	return out
}

func copyBoolSet(m map[string]bool) map[string]bool {
	out := make(map[string]bool, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// colSchema 是 CTE / 臨時表 / 衍生資料表的欄位 schema，保留欄位順序（byte-parity）。
type colSchema struct {
	names []string // 大寫，依插入順序
	types map[string]string
}

func newColSchema() *colSchema { return &colSchema{types: map[string]string{}} }

func (s *colSchema) set(name, typ string) {
	nu := strings.ToUpper(name)
	if _, ok := s.types[nu]; !ok {
		s.names = append(s.names, nu)
	}
	s.types[nu] = typ
}

func (s *colSchema) get(name string) (string, bool) {
	t, ok := s.types[strings.ToUpper(name)]
	return t, ok
}

// ── AST 走訪小工具 ─────────────────────────────────────────────────────────

// queryColumns 取出 SelectStatement / UnionStatement 的投影欄位。
func queryColumns(n Node) []Node {
	switch q := n.(type) {
	case *SelectStatement:
		return q.Columns
	case *UnionStatement:
		return q.Columns
	}
	return nil
}

func unionSideColumns(n Node) []Node { return queryColumns(n) }

// columnOutputName 對照 Python (c.alias or c.name)。
func columnOutputName(c Node) string {
	if eb := exprOf(c); eb != nil && eb.Alias != "" {
		return eb.Alias
	}
	if id, ok := c.(*IdentifierNode); ok {
		return id.Name
	}
	if eb := exprOf(c); eb != nil {
		return eb.Alias
	}
	return ""
}

func inferredTypeOf(c Node) string {
	if eb := exprOf(c); eb != nil {
		return eb.InferredType
	}
	return "UNKNOWN"
}

// joinAlias 對照 (j.alias or j.table.name)。
func joinAlias(j *JoinNode) string {
	if j.Alias != "" {
		return j.Alias
	}
	if id, ok := j.Table.(*IdentifierNode); ok {
		return id.Name
	}
	return ""
}

// asSubquery：若 n 為 SelectStatement / UnionStatement 則回傳，否則 nil。
func asSubquery(n Node) Node {
	switch n.(type) {
	case *SelectStatement, *UnionStatement:
		return n
	}
	return nil
}
