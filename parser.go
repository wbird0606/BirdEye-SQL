package birdeye

import (
	"fmt"
	"strconv"
	"strings"
)

func panicMsg(r any) string {
	if e, ok := r.(error); ok {
		return e.Error()
	}
	return fmt.Sprintf("%v", r)
}

// Parser 對照 Python birdeye/parser.py 的遞迴下降 parser。
// 內部方法遇錯以 panic(parseBail) 中止（對照 Python raise SyntaxError），
// 由 Parse / ParseScript 的 recover 轉回 error。
type Parser struct {
	toks       []Token
	src        []rune
	pos        int
	isQualStar bool
}

type parseBail struct{ err *Error }

// NewParser 建立 parser。source 供 _get_text 的 fallback 切片（罕用）。
func NewParser(tokens []Token, source string) *Parser {
	return &Parser{toks: tokens, src: []rune(source)}
}

func (p *Parser) fail(msg string)      { panic(parseBail{syntaxErr(msg)}) }
func (p *Parser) failValue(msg string) { panic(parseBail{valueErr(msg)}) }

// ── 基礎工具 ────────────────────────────────────────────────────────────────

func (p *Parser) peek(offset int) *Token {
	i := p.pos + offset
	if i < 0 || i >= len(p.toks) {
		return nil
	}
	return &p.toks[i]
}

func (p *Parser) advance() Token {
	t := p.toks[p.pos]
	p.pos++
	return t
}

// match：若下一個 token 型別在 types 內則消耗並回傳。
func (p *Parser) match(types ...TokenType) (Token, bool) {
	t := p.peek(0)
	if t == nil {
		return Token{}, false
	}
	for _, ty := range types {
		if t.Type == ty {
			return p.advance(), true
		}
	}
	return Token{}, false
}

func (p *Parser) matchOK(types ...TokenType) bool {
	_, ok := p.match(types...)
	return ok
}

func (p *Parser) consume(t TokenType, msg string) Token {
	if tok, ok := p.match(t); ok {
		return tok
	}
	p.fail(msg)
	panic("unreachable")
}

func (p *Parser) check(t TokenType) bool {
	tk := p.peek(0)
	return tk != nil && tk.Type == t
}

func (p *Parser) getText(t Token) string {
	text := t.Value
	if text == "" {
		if t.Start >= 0 && t.End <= len(p.src) && t.Start <= t.End {
			text = string(p.src[t.Start:t.End])
		}
	}
	return strings.Trim(text, "[]")
}

func (p *Parser) atoi(s string) int {
	n, err := strconv.Atoi(s)
	if err != nil {
		p.failValue("invalid literal for int(): '" + s + "'")
	}
	return n
}

// 可作為別名的非保留關鍵字。
var unreservedAsAlias = map[TokenType]bool{
	KwOuter: true, KwInner: true, KwFull: true, KwLeft: true, KwRight: true,
	KwCross: true, KwTop: true, KwAll: true, KwNext: true, KwRows: true,
	KwOnly: true, KwRange: true, KwCurrent: true, KwFollowing: true,
	KwPreceding: true, KwOver: true, KwPartition: true,
}

func (p *Parser) matchAlias() (Token, bool) {
	t := p.peek(0)
	if t != nil && (t.Type == Identifier || unreservedAsAlias[t.Type]) {
		return p.advance(), true
	}
	return Token{}, false
}

// ── 1. 主入口 ───────────────────────────────────────────────────────────────

// Parse 解析單一語句。
func (p *Parser) Parse() (n Node, err error) {
	defer func() {
		if r := recover(); r != nil {
			if b, ok := r.(parseBail); ok {
				n, err = nil, b.err
				return
			}
			// runtime panic（如越界索引）對照 Python 未預期例外 → 分類 system
			n, err = nil, &Error{ErrSystem, panicMsg(r)}
		}
	}()

	tok := p.peek(0)
	if tok == nil || tok.Type == EOF {
		p.fail("Empty source")
	}

	var ctes []*CTENode
	if tok.Type == KwWith {
		ctes = p.parseCTEs()
		tok = p.peek(0)
	}
	if tok == nil {
		p.fail("Unexpected end of input")
	}

	stmt := p.parseStatementBody(tok, ctes)

	p.match(SymSemicolon)
	if pk := p.peek(0); pk != nil && pk.Type != EOF {
		p.fail("Unexpected token: " + p.getText(*pk))
	}
	return stmt, nil
}

// ParseScript 以分號分隔解析一或多條語句，回傳 *ScriptNode。
func (p *Parser) ParseScript() (n Node, err error) {
	defer func() {
		if r := recover(); r != nil {
			if b, ok := r.(parseBail); ok {
				n, err = nil, b.err
				return
			}
			// runtime panic（如越界索引）對照 Python 未預期例外 → 分類 system
			n, err = nil, &Error{ErrSystem, panicMsg(r)}
		}
	}()

	var stmts []Node
	for {
		pk := p.peek(0)
		if pk == nil || pk.Type == EOF {
			break
		}
		stmts = append(stmts, p.parseOneStatement())
	}
	if len(stmts) == 0 {
		p.fail("Empty source")
	}
	return &ScriptNode{Statements: stmts}, nil
}

func (p *Parser) parseOneStatement() Node {
	tok := p.peek(0)
	if tok == nil || tok.Type == EOF {
		p.fail("Unexpected end of input")
	}
	var ctes []*CTENode
	if tok.Type == KwWith {
		ctes = p.parseCTEs()
		tok = p.peek(0)
	}
	if tok == nil {
		p.fail("Unexpected end of input")
	}
	stmt := p.parseStatementBody(tok, ctes)
	p.match(SymSemicolon)
	return stmt
}

// parseStatementBody 依起始 token 分派（對照 parse() / _parse_one_statement() 共同邏輯）。
func (p *Parser) parseStatementBody(tok *Token, ctes []*CTENode) Node {
	switch tok.Type {
	case KwSelect:
		st := p.parseSelectWithSetOps()
		if len(ctes) > 0 {
			attachCTEs(st, ctes)
		}
		return st
	case KwUpdate:
		st := p.parseUpdate()
		if len(ctes) > 0 {
			st.CTEs = ctes
		}
		return st
	case KwDelete:
		st := p.parseDelete()
		if len(ctes) > 0 {
			st.CTEs = ctes
		}
		return st
	case KwInsert:
		return p.parseInsert()
	case KwTruncate:
		return p.parseTruncate()
	case KwDeclare:
		return p.parseDeclare()
	case KwIf:
		p.advance()
		return p.parseIf()
	case KwBegin:
		stmts := p.parseBlock()
		return stmts[0]
	case KwExec:
		p.advance()
		return p.parseExec()
	case KwCreate:
		p.advance()
		return p.parseCreate()
	case KwDrop:
		p.advance()
		return p.parseDrop()
	case KwAlter:
		p.advance()
		return p.parseAlter()
	case KwMerge:
		p.advance()
		return p.parseMerge()
	case KwPrint:
		p.advance()
		return p.parsePrint()
	case KwSet:
		p.advance()
		return p.parseSetStatement()
	case Identifier:
		if strings.ToUpper(p.getText(*tok)) == "BULK" {
			return p.parseBulkInsert()
		}
	}
	p.fail("Unexpected token: " + p.getText(*tok))
	panic("unreachable")
}

func attachCTEs(st Node, ctes []*CTENode) {
	switch s := st.(type) {
	case *SelectStatement:
		s.CTEs = ctes
	case *UnionStatement:
		// Python: UnionStatement 沒有 ctes 屬性，但 parse() 仍 `stmt.ctes = ctes`
		// （動態加）。這裡忽略：Union + CTE 由 parseSelectWithSetOps 的左節點承接。
	}
}

// ── 2. CTE ──────────────────────────────────────────────────────────────────

func (p *Parser) parseCTEs() []*CTENode {
	p.consume(KwWith, "Expected WITH")
	var ctes []*CTENode
	for {
		nameTok := p.consume(Identifier, "Expected CTE name")
		name := strings.ToUpper(p.getText(nameTok))
		p.consume(KwAs, "Expected AS after CTE name")
		p.consume(SymLParen, "Expected ( before CTE query")
		q := p.parseSelectWithSetOps()
		p.consume(SymRParen, "Expected ) after CTE query")
		ctes = append(ctes, &CTENode{Name: name, Query: q})
		if !p.matchOK(SymComma) {
			break
		}
	}
	return ctes
}

// ── 3. SELECT / 集合運算 ────────────────────────────────────────────────────

func (p *Parser) parseSelectWithSetOps() Node {
	var node Node = p.parseSingleSelect()
	for {
		if p.matchOK(KwUnion) {
			op := "UNION"
			if p.matchOK(KwAll) {
				op = "UNION ALL"
			}
			node = NewUnionStatement(node, op, p.parseSingleSelect())
		} else if p.matchOK(KwIntersect) {
			node = NewUnionStatement(node, "INTERSECT", p.parseSingleSelect())
		} else if p.matchOK(KwExcept) {
			node = NewUnionStatement(node, "EXCEPT", p.parseSingleSelect())
		} else {
			break
		}
	}
	return node
}

func (p *Parser) parseSingleSelect() *SelectStatement {
	stmt := NewSelectStatement()
	p.consume(KwSelect, "Expected SELECT")

	if p.matchOK(KwDistinct) {
		stmt.IsDistinct = true
	}

	if p.matchOK(KwTop) {
		hasParen := p.matchOK(SymLParen)
		numTok, ok := p.match(NumericLiteral)
		if !ok {
			p.fail("Expected numeric literal after TOP")
		}
		v := p.atoi(numTok.Value)
		stmt.TopCount = &v
		if hasParen {
			if !p.matchOK(SymRParen) {
				p.fail("Expected ')' after TOP count")
			}
		}
		if p.matchOK(KwPercent) {
			stmt.TopPercent = true
		}
	}

	for {
		if p.matchOK(SymAsterisk) {
			stmt.IsSelectStar = true
		} else {
			p.isQualStar = false
			expr := p.parseExpression()
			if p.isQualStar {
				id := expr.(*IdentifierNode)
				var prefix string
				if len(id.Qualifiers) == 0 {
					prefix = id.Name
				} else {
					prefix = strings.Join(append(append([]string{}, id.Qualifiers...), id.Name), ".")
				}
				stmt.StarPrefixes = append(stmt.StarPrefixes, prefix)
			} else {
				hasAs := p.matchOK(KwAs)
				var alias Token
				var ok bool
				if hasAs {
					alias, ok = p.matchAlias()
				} else {
					alias, ok = p.match(Identifier)
				}
				if ok {
					if eb := exprOf(expr); eb != nil {
						eb.Alias = p.getText(alias)
					}
				}
				stmt.Columns = append(stmt.Columns, expr)
			}
		}
		if !p.matchOK(SymComma) {
			break
		}
	}

	// SELECT ... INTO #table
	if p.matchOK(KwInto) {
		id, _ := p.parseFullIdentifierSafe()
		stmt.IntoTable = id
	}

	if p.matchOK(KwFrom) {
		if p.check(SymLParen) {
			p.advance()
			subq := p.parseSelectWithSetOps()
			p.consume(SymRParen, "Expected ) after derived table")
			p.match(KwAs)
			aliasTok, ok := p.matchAlias()
			if !ok {
				p.fail("Derived table must have an alias")
			}
			stmt.Table = subq
			stmt.TableAlias = p.getText(aliasTok)
		} else {
			id, _ := p.parseFullIdentifierSafe()
			stmt.Table = id
			hasAs := p.matchOK(KwAs)
			var aliasTok Token
			var ok bool
			if hasAs {
				aliasTok, ok = p.matchAlias()
			} else {
				aliasTok, ok = p.match(Identifier)
			}
			if ok {
				stmt.TableAlias = p.getText(aliasTok)
			}
		}

		if p.check(SymComma) {
			p.fail("Expected FROM")
		}

		p.parseFromTail(stmt)
	} else {
		needsFrom := stmt.IsSelectStar
		for _, c := range stmt.Columns {
			if p.containsIdentifier(c) {
				needsFrom = true
			}
		}
		if needsFrom {
			p.consume(KwFrom, "Expected FROM")
		}
	}

	if p.matchOK(KwWhere) {
		stmt.Where = p.parseExpression()
	}
	if p.matchOK(KwGroup) {
		p.consume(KwBy, "Expected BY after GROUP")
		for {
			stmt.GroupBy = append(stmt.GroupBy, p.parseExpression())
			if !p.matchOK(SymComma) {
				break
			}
		}
	}
	if p.matchOK(KwHaving) {
		stmt.Having = p.parseExpression()
	}
	if p.matchOK(KwOrder) {
		p.consume(KwBy, "Expected BY after ORDER")
		for {
			colExpr := p.parseExpression()
			dir := "ASC"
			if p.matchOK(KwDesc) {
				dir = "DESC"
			} else if p.matchOK(KwAsc) {
				dir = "ASC"
			}
			stmt.OrderBy = append(stmt.OrderBy, &OrderByNode{Column: colExpr, Direction: dir})
			if !p.matchOK(SymComma) {
				break
			}
		}
	}
	if p.matchOK(KwOffset) {
		numTok := p.consume(NumericLiteral, "Expected number after OFFSET")
		v := p.atoi(numTok.Value)
		stmt.OffsetCount = &v
		p.match(KwRows)
		if p.matchOK(KwFetch) {
			p.match(KwNext)
			fetchTok := p.consume(NumericLiteral, "Expected number after FETCH")
			fv := p.atoi(fetchTok.Value)
			stmt.FetchCount = &fv
			p.match(KwRows)
			p.match(KwOnly)
		}
	}
	return stmt
}

// parseFromTail 處理 FROM 之後的 JOIN / APPLY / CROSS JOIN 迴圈。
func (p *Parser) parseFromTail(stmt *SelectStatement) {
	for {
		var applyType string
		if p.matchOK(KwCross) {
			if p.check(KwApply) {
				p.advance()
				applyType = "CROSS"
			} else if p.check(KwJoin) {
				p.advance()
				tbl, _ := p.parseFullIdentifierSafe()
				j := NewJoinNode("CROSS", tbl)
				hasAs := p.matchOK(KwAs)
				var al Token
				var ok bool
				if hasAs {
					al, ok = p.matchAlias()
				} else {
					al, ok = p.match(Identifier)
				}
				if ok {
					j.Alias = p.getText(al)
				}
				stmt.Joins = append(stmt.Joins, j)
				continue
			} else {
				p.fail("Expected APPLY or JOIN after CROSS")
			}
		} else if p.matchOK(KwOuter) {
			if p.check(KwApply) {
				p.advance()
				applyType = "OUTER"
			} else {
				p.fail("Expected APPLY after OUTER")
			}
		}
		if applyType != "" {
			p.consume(SymLParen, "Expected ( after APPLY")
			subquery := p.parseSelectWithSetOps()
			p.consume(SymRParen, "Expected ) after APPLY subquery")
			p.match(KwAs)
			al, ok := p.matchAlias()
			alias := ""
			if ok {
				alias = p.getText(al)
			}
			stmt.Applies = append(stmt.Applies, &ApplyNode{Type: applyType, Subquery: subquery, Alias: alias})
			continue
		}

		jt := "INNER"
		if p.matchOK(KwLeft) {
			jt = "LEFT"
		} else if p.matchOK(KwRight) {
			jt = "RIGHT"
		} else if p.matchOK(KwFull) {
			jt = "FULL"
		}
		p.match(KwInner)
		p.match(KwOuter)
		if p.matchOK(KwJoin) {
			var j *JoinNode
			if p.check(SymLParen) {
				p.advance()
				subq := p.parseSelectWithSetOps()
				p.consume(SymRParen, "Expected ) after JOIN subquery")
				p.match(KwAs)
				alTok, ok := p.matchAlias()
				if !ok {
					p.fail("JOIN subquery must have an alias")
				}
				j = NewJoinNode(jt, subq)
				j.Alias = p.getText(alTok)
			} else {
				tbl, _ := p.parseFullIdentifierSafe()
				j = NewJoinNode(jt, tbl)
				hasAs := p.matchOK(KwAs)
				var al Token
				var ok bool
				if hasAs {
					al, ok = p.matchAlias()
				} else {
					al, ok = p.match(Identifier)
				}
				if ok {
					j.Alias = p.getText(al)
				}
			}
			p.consume(KwOn, "Expected ON")
			cond := p.parseExpression()
			j.OnCondition = cond
			if be, ok := cond.(*BinaryExpressionNode); ok {
				j.OnLeft, j.OnRight = be.Left, be.Right
			}
			stmt.Joins = append(stmt.Joins, j)
		} else {
			break
		}
	}
}

func (p *Parser) containsIdentifier(n Node) bool {
	switch v := n.(type) {
	case *IdentifierNode:
		return !strings.HasPrefix(v.Name, "@")
	case *BinaryExpressionNode:
		return p.containsIdentifier(v.Left) || p.containsIdentifierNode(v.Right)
	case *FunctionCallNode:
		for _, a := range v.Args {
			if p.containsIdentifier(a) {
				return true
			}
		}
		return false
	case *CaseExpressionNode:
		if v.InputExpr != nil && p.containsIdentifier(v.InputExpr) {
			return true
		}
		for _, b := range v.Branches {
			if p.containsIdentifier(b.When) || p.containsIdentifier(b.Then) {
				return true
			}
		}
		if v.ElseExpr != nil {
			return p.containsIdentifier(v.ElseExpr)
		}
		return false
	}
	return false
}

func (p *Parser) containsIdentifierNode(n Node) bool {
	if n == nil {
		return false
	}
	return p.containsIdentifier(n)
}

// ── 4. DML ──────────────────────────────────────────────────────────────────

func (p *Parser) parseTruncate() Node {
	p.consume(KwTruncate, "Expected TRUNCATE")
	p.consume(KwTable, "Expected TABLE after TRUNCATE")
	tbl, _ := p.parseFullIdentifierSafe()
	return &TruncateStatement{Table: tbl}
}

func (p *Parser) parseUpdate() *UpdateStatement {
	stmt := &UpdateStatement{}
	p.consume(KwUpdate, "Expected UPDATE")
	stmt.Table, _ = p.parseFullIdentifierSafe()
	p.consume(KwSet, "Expected SET")
	for {
		col, _ := p.parseFullIdentifierSafe()
		p.consume(SymEqual, "Expected =")
		val := p.parseExpression()
		stmt.SetClauses = append(stmt.SetClauses, &AssignmentNode{Column: col, Right: val})
		if !p.matchOK(SymComma) {
			break
		}
	}
	p.consume(KwWhere, "WHERE clause is mandatory for UPDATE/DELETE")
	stmt.Where = p.parseExpression()
	return stmt
}

func (p *Parser) parseDelete() *DeleteStatement {
	stmt := &DeleteStatement{}
	p.consume(KwDelete, "Expected DELETE")
	p.match(KwFrom)
	stmt.Table, _ = p.parseFullIdentifierSafe()
	p.consume(KwWhere, "WHERE clause is mandatory for UPDATE/DELETE")
	stmt.Where = p.parseExpression()
	return stmt
}

func (p *Parser) parseInsert() Node {
	stmt := &InsertStatement{}
	p.consume(KwInsert, "Expected INSERT")
	p.consume(KwInto, "Expected INTO")
	stmt.Table, _ = p.parseFullIdentifierSafe()
	if p.matchOK(SymLParen) {
		for {
			col, _ := p.parseFullIdentifierSafe()
			stmt.Columns = append(stmt.Columns, col)
			if !p.matchOK(SymComma) {
				break
			}
		}
		p.consume(SymRParen, "Unclosed bracket")
	}
	if p.check(KwSelect) {
		stmt.Source = p.parseSelectWithSetOps()
		return stmt
	}
	p.consume(KwValues, "Expected VALUES")
	for {
		p.consume(SymLParen, "Expected (")
		var row []Node
		for {
			row = append(row, p.parseExpression())
			if !p.matchOK(SymComma) {
				break
			}
		}
		p.consume(SymRParen, "Expected )")
		stmt.ValueRows = append(stmt.ValueRows, row)
		if !p.matchOK(SymComma) {
			break
		}
	}
	if len(stmt.ValueRows) > 0 {
		stmt.Values = stmt.ValueRows[0]
	}
	return stmt
}

func (p *Parser) parseBulkInsert() Node {
	p.advance() // BULK
	p.consume(KwInsert, "Expected INSERT")
	p.consume(KwInto, "Expected INTO")
	stmt := &SqlBulkCopyStatement{}
	stmt.Table, _ = p.parseFullIdentifierSafe()
	return stmt
}

func (p *Parser) parseDeclare() Node {
	p.consume(KwDeclare, "Expected DECLARE")
	varTok := p.consume(Identifier, "Expected variable name after DECLARE")
	varName := p.getText(varTok)
	typeTok := p.consume(Identifier, "Expected type after variable name")
	varType := strings.ToUpper(p.getText(typeTok))
	if p.matchOK(SymLParen) {
		for {
			tk := p.peek(0)
			if tk == nil || tk.Type == SymRParen {
				break
			}
			p.advance()
		}
		p.consume(SymRParen, "Expected ) after type size")
	}
	var def Node
	if p.matchOK(SymEqual) {
		def = p.parseExpression()
	}
	return &DeclareStatement{VarName: varName, VarType: varType, DefaultValue: def}
}

// ── 5. 表達式引擎 ───────────────────────────────────────────────────────────

func (p *Parser) parseExpression() Node { return p.parseLogicalOr() }

func (p *Parser) parseLogicalOr() Node {
	node := p.parseLogicalAnd()
	for p.matchOK(KwOr) {
		node = NewBinaryExpr(node, "OR", p.parseLogicalAnd())
	}
	return node
}

func (p *Parser) parseLogicalAnd() Node {
	node := p.parseComparison()
	for p.matchOK(KwAnd) {
		node = NewBinaryExpr(node, "AND", p.parseComparison())
	}
	return node
}

func (p *Parser) parseComparison() Node {
	node := p.parseTerm()
	for {
		if p.matchOK(KwIs) {
			isNot := p.matchOK(KwNot)
			p.consume(KwNull, "Expected NULL after IS")
			op := "IS NULL"
			if isNot {
				op = "IS NOT NULL"
			}
			node = NewBinaryExpr(node, op, NewLiteral("NULL", Identifier))
			continue
		}
		if p.matchOK(KwBetween) {
			low := p.parseTerm()
			p.consume(KwAnd, "Expected AND after BETWEEN low")
			high := p.parseTerm()
			node = NewBetweenExpr(node, low, high, false)
			continue
		}
		if p.matchOK(KwNot) {
			if p.matchOK(KwLike) {
				node = NewBinaryExpr(node, "NOT LIKE", p.parseTerm())
			} else if p.matchOK(KwBetween) {
				low := p.parseTerm()
				p.consume(KwAnd, "Expected AND after BETWEEN low")
				high := p.parseTerm()
				node = NewBetweenExpr(node, low, high, true)
			} else if p.matchOK(KwIn) {
				p.consume(SymLParen, "Expected ( after NOT IN")
				right := p.parseInRHS()
				p.consume(SymRParen, "Expected ) after NOT IN list")
				node = NewBinaryExpr(node, "NOT IN", right)
			} else {
				p.fail("Expected LIKE, BETWEEN, or IN after NOT")
			}
			continue
		}
		if p.matchOK(KwLike) {
			node = NewBinaryExpr(node, "LIKE", p.parseTerm())
			continue
		}
		if p.matchOK(KwIn) {
			p.consume(SymLParen, "Expected ( after IN")
			right := p.parseInRHS()
			p.consume(SymRParen, "Expected ) after IN list")
			node = NewBinaryExpr(node, "IN", right)
			continue
		}

		opTok, ok := p.match(SymEqual, SymGT, SymLT, SymGE, SymLE, SymNE)
		if !ok {
			break
		}
		opStr := p.getText(opTok)
		if modTok, ok := p.match(KwAny, KwAll); ok {
			opStr = opStr + " " + strings.ToUpper(p.getText(modTok))
			p.consume(SymLParen, "Expected ( after "+opStr)
			var right Node
			if p.check(KwSelect) {
				right = p.parseSelectWithSetOps()
			} else {
				if p.check(SymRParen) {
					p.fail("Expected expression list after " + opStr)
				}
				right = p.parseExprList()
			}
			p.consume(SymRParen, "Expected ) after "+opStr+" list")
			node = NewBinaryExpr(node, opStr, right)
		} else {
			node = NewBinaryExpr(node, opStr, p.parseTerm())
		}
	}
	return node
}

// parseInRHS：IN / NOT IN 右側 —— 子查詢或 nodeList。
func (p *Parser) parseInRHS() Node {
	if p.check(KwSelect) {
		return p.parseSelectWithSetOps()
	}
	return p.parseExprList()
}

// parseExprList 回傳 nodeList（對照 Python 的 list）。
func (p *Parser) parseExprList() Node {
	var items nodeList
	for {
		items = append(items, p.parseExpression())
		if !p.matchOK(SymComma) {
			break
		}
	}
	return items
}

// nodeList 對照 Python 中 BinaryExpressionNode.right 為 list 的情況。
type nodeList []Node

func (nodeList) aNode() {}

func (p *Parser) parseTerm() Node {
	node := p.parseFactor()
	for {
		if p.matchOK(SymPlus) {
			node = NewBinaryExpr(node, "+", p.parseFactor())
		} else if p.matchOK(SymMinus) {
			node = NewBinaryExpr(node, "-", p.parseFactor())
		} else {
			break
		}
	}
	return node
}

func (p *Parser) parseFactor() Node {
	node := p.parsePrimary()
	for {
		switch {
		case p.matchOK(SymAsterisk):
			node = NewBinaryExpr(node, "*", p.parsePrimary())
		case p.matchOK(SymSlash):
			node = NewBinaryExpr(node, "/", p.parsePrimary())
		case p.matchOK(SymPercent):
			node = NewBinaryExpr(node, "%", p.parsePrimary())
		case p.matchOK(SymAmpersand):
			node = NewBinaryExpr(node, "&", p.parsePrimary())
		case p.matchOK(SymPipe):
			node = NewBinaryExpr(node, "|", p.parsePrimary())
		case p.matchOK(SymCaret):
			node = NewBinaryExpr(node, "^", p.parsePrimary())
		default:
			return node
		}
	}
}

var keywordFunctions = map[TokenType]bool{KwLeft: true, KwRight: true}

func (p *Parser) parsePrimary() Node {
	tok := p.peek(0)
	if tok == nil {
		p.fail("Unexpected end of input")
	}

	switch tok.Type {
	case KwCast:
		p.advance()
		p.consume(SymLParen, "Expected ( after CAST")
		expr := p.parseExpression()
		p.consume(KwAs, "Expected AS in CAST")
		typeTok := p.consume(Identifier, "Expected target type in CAST")
		targetType := strings.ToUpper(p.getText(typeTok))
		p.skipParenGroup()
		p.consume(SymRParen, "Expected ) after CAST type")
		return NewCastExpr(expr, targetType, false)

	case KwConvert:
		p.advance()
		p.consume(SymLParen, "Expected ( after CONVERT")
		typeTok := p.consume(Identifier, "Expected target type in CONVERT")
		targetType := strings.ToUpper(p.getText(typeTok))
		p.skipParenGroup()
		p.consume(SymComma, "Expected comma in CONVERT")
		expr := p.parseExpression()
		if p.matchOK(SymComma) {
			p.parseExpression() // style 參數，消耗
		}
		p.consume(SymRParen, "Expected ) after CONVERT")
		return NewCastExpr(expr, targetType, true)

	case KwCase:
		p.advance()
		return p.parseCaseExpression()

	case KwExists:
		p.advance()
		p.consume(SymLParen, "Expected ( after EXISTS")
		sub := p.parseSelectWithSetOps()
		p.consume(SymRParen, "Expected ) after EXISTS")
		return NewFunctionCall("EXISTS", []Node{sub})

	case KwNot:
		p.advance()
		if p.matchOK(KwExists) {
			p.consume(SymLParen, "Expected ( after NOT EXISTS")
			sub := p.parseSelectWithSetOps()
			p.consume(SymRParen, "Expected ) after NOT EXISTS")
			return NewFunctionCall("NOT EXISTS", []Node{sub})
		}
		p.fail("Expected EXISTS after NOT")

	case SymLParen:
		p.advance()
		var node Node
		if p.check(KwSelect) {
			node = p.parseSelectWithSetOps()
		} else {
			node = p.parseExpression()
		}
		p.consume(SymRParen, "Expected )")
		return node

	case SymTilde:
		p.advance()
		operand := p.parsePrimary()
		return NewBinaryExpr(NewLiteral("0", NumericLiteral), "~", operand)

	case SymAsterisk:
		p.advance()
		return NewIdentifier("*", nil)

	case SymComma:
		p.fail("Expected identifier")

	case SymMinus:
		p.advance()
		operand := p.parsePrimary()
		if lit, ok := operand.(*LiteralNode); ok && lit.Type == NumericLiteral {
			lit.Value = "-" + lit.Value
			return lit
		}
		return NewBinaryExpr(NewLiteral("0", NumericLiteral), "-", operand)

	case NumericLiteral:
		return NewLiteral(p.getText(p.advance()), NumericLiteral)

	case StringLiteral:
		return NewLiteral(strings.Trim(p.getText(p.advance()), "'"), StringLiteral)

	case KwNull:
		p.advance()
		return NewLiteral("NULL", KwNull)
	}

	// 關鍵字作為函數名（LEFT / RIGHT）
	if keywordFunctions[tok.Type] {
		if nx := p.peek(1); nx != nil && nx.Type == SymLParen {
			funcName := strings.ToUpper(p.getText(p.advance()))
			p.consume(SymLParen, "Expected (")
			var args []Node
			if !p.check(SymRParen) {
				for {
					args = append(args, p.parseExpression())
					if !p.matchOK(SymComma) {
						break
					}
				}
			}
			p.consume(SymRParen, "Expected )")
			fn := NewFunctionCall(funcName, args)
			fn.OverClause = p.parseOverClause()
			return fn
		}
	}

	if tok.Type == Identifier {
		idNode, isFunc := p.parseFullIdentifierSafe()
		if p.matchOK(SymDot) {
			if p.matchOK(SymAsterisk) {
				p.isQualStar = true
				return idNode
			}
			p.fail("Expected * after .")
		}
		if isFunc {
			return p.parseFunctionCall(idNode)
		}
		return idNode
	}

	p.fail("Unexpected expression token: " + p.getText(*tok))
	panic("unreachable")
}

// skipParenGroup 吸收可選的 (…) 型別長度，如 VARCHAR(10) 或 DECIMAL(18,2)。
func (p *Parser) skipParenGroup() {
	if p.matchOK(SymLParen) {
		for {
			tk := p.peek(0)
			if tk == nil || tk.Type == SymRParen {
				break
			}
			p.advance()
		}
		p.consume(SymRParen, "Expected ) after type size")
	}
}

func (p *Parser) parseFunctionCall(idNode *IdentifierNode) Node {
	funcName := strings.ToUpper(idNode.Name)
	switch funcName {
	case "TRY_CAST":
		p.consume(SymLParen, "Expected ( after TRY_CAST")
		expr := p.parseExpression()
		p.consume(KwAs, "Expected AS in TRY_CAST")
		typeTok := p.consume(Identifier, "Expected target type in TRY_CAST")
		targetType := strings.ToUpper(p.getText(typeTok))
		p.skipParenGroup()
		p.consume(SymRParen, "Expected ) after TRY_CAST")
		return NewCastExpr(expr, targetType, false)
	case "TRY_CONVERT":
		p.consume(SymLParen, "Expected ( after TRY_CONVERT")
		typeTok := p.consume(Identifier, "Expected target type in TRY_CONVERT")
		targetType := strings.ToUpper(p.getText(typeTok))
		p.skipParenGroup()
		p.consume(SymComma, "Expected comma in TRY_CONVERT")
		expr := p.parseExpression()
		if p.matchOK(SymComma) {
			p.parseExpression()
		}
		p.consume(SymRParen, "Expected ) after TRY_CONVERT")
		return NewCastExpr(expr, targetType, true)
	}
	p.consume(SymLParen, "Expected (")
	var args []Node
	p.match(KwDistinct) // 吸收 COUNT(DISTINCT ...)
	if !p.check(SymRParen) {
		for {
			args = append(args, p.parseExpression())
			if !p.matchOK(SymComma) {
				break
			}
		}
	}
	p.consume(SymRParen, "Expected )")
	fn := NewFunctionCall(idNode.Name, args)
	fn.OverClause = p.parseOverClause()
	return fn
}

func (p *Parser) parseCaseExpression() Node {
	var input Node
	if !p.check(KwWhen) {
		input = p.parseExpression()
	}
	caseNode := NewCaseExpr(input)
	for p.matchOK(KwWhen) {
		when := p.parseExpression()
		p.consume(KwThen, "Expected THEN after WHEN")
		then := p.parseExpression()
		caseNode.Branches = append(caseNode.Branches, CaseBranch{When: when, Then: then})
	}
	if len(caseNode.Branches) == 0 {
		p.fail("CASE expression must have at least one WHEN branch")
	}
	if p.matchOK(KwElse) {
		caseNode.ElseExpr = p.parseExpression()
	}
	p.consume(KwEnd, "Expected END at the end of CASE")
	return caseNode
}

// parseFullIdentifierSafe 回傳 (識別符, 是否為函數呼叫)。
func (p *Parser) parseFullIdentifierSafe() (*IdentifierNode, bool) {
	var parts []string
	for {
		parts = append(parts, p.getText(p.consume(Identifier, "Expected identifier")))
		if p.check(SymDot) {
			if nx := p.peek(1); nx != nil && nx.Type == SymAsterisk {
				break
			}
			p.advance()
		} else {
			break
		}
	}
	isFunc := p.check(SymLParen)
	name := parts[len(parts)-1]
	quals := parts[:len(parts)-1]
	return NewIdentifier(name, append([]string{}, quals...)), isFunc
}

func (p *Parser) parseOverClause() *OverClauseNode {
	if !p.matchOK(KwOver) {
		return nil
	}
	p.consume(SymLParen, "Expected ( after OVER")
	over := &OverClauseNode{}
	if p.matchOK(KwPartition) {
		p.consume(KwBy, "Expected BY after PARTITION")
		for {
			over.PartitionBy = append(over.PartitionBy, p.parseExpression())
			if !p.matchOK(SymComma) {
				break
			}
		}
	}
	if p.matchOK(KwOrder) {
		p.consume(KwBy, "Expected BY after ORDER")
		for {
			colExpr := p.parseExpression()
			dir := "ASC"
			if p.matchOK(KwDesc) {
				dir = "DESC"
			} else if p.matchOK(KwAsc) {
				dir = "ASC"
			}
			over.OrderBy = append(over.OrderBy, &OrderByNode{Column: colExpr, Direction: dir})
			if !p.matchOK(SymComma) {
				break
			}
		}
	}
	if tk := p.peek(0); tk != nil && (tk.Type == KwRows || tk.Type == KwRange) {
		over.FrameType = strings.ToUpper(p.getText(p.advance()))
		if p.matchOK(KwBetween) {
			over.FrameStart = p.parseFrameBoundary()
			p.consume(KwAnd, "Expected AND in frame specification")
			over.FrameEnd = p.parseFrameBoundary()
		} else {
			over.FrameStart = p.parseFrameBoundary()
		}
	}
	p.consume(SymRParen, "Expected ) after OVER clause")
	return over
}

func (p *Parser) parseFrameBoundary() string {
	if p.matchOK(KwUnbounded) {
		if p.matchOK(KwPreceding) {
			return "UNBOUNDED PRECEDING"
		}
		if p.matchOK(KwFollowing) {
			return "UNBOUNDED FOLLOWING"
		}
		p.fail("Expected PRECEDING or FOLLOWING after UNBOUNDED")
	}
	if p.matchOK(KwCurrent) {
		p.consume(KwRow, "Expected ROW after CURRENT")
		return "CURRENT ROW"
	}
	numTok := p.consume(NumericLiteral, "Expected number or boundary in frame specification")
	if p.matchOK(KwPreceding) {
		return numTok.Value + " PRECEDING"
	}
	if p.matchOK(KwFollowing) {
		return numTok.Value + " FOLLOWING"
	}
	p.fail("Expected PRECEDING or FOLLOWING after number")
	panic("unreachable")
}

// ── 6. 新語法 ───────────────────────────────────────────────────────────────

func (p *Parser) parseBlock() []Node {
	if p.matchOK(KwBegin) {
		var stmts []Node
		for {
			tk := p.peek(0)
			if tk == nil || tk.Type == KwEnd || tk.Type == KwElse {
				break
			}
			before := p.pos
			s := p.parseSingleStmt()
			if s != nil {
				stmts = append(stmts, s)
			}
			p.match(SymSemicolon)
			if p.pos == before {
				// KNOWN_DEVIATIONS A1：Python 在此無限迴圈；Go 改為報錯
				p.fail("Unexpected token in BEGIN...END block: " + p.getText(*p.peek(0)))
			}
		}
		p.match(KwEnd)
		if len(stmts) == 0 {
			return []Node{nil}
		}
		return stmts
	}
	s := p.parseSingleStmt()
	if s == nil {
		return []Node{nil}
	}
	return []Node{s}
}

func (p *Parser) parseSingleStmt() Node {
	tok := p.peek(0)
	if tok == nil {
		return nil
	}
	switch tok.Type {
	case KwSelect, KwWith:
		return p.parseSelectWithSetOps()
	case KwInsert:
		return p.parseInsert()
	case KwUpdate:
		return p.parseUpdate()
	case KwDelete:
		return p.parseDelete()
	case KwTruncate:
		return p.parseTruncate()
	case KwDeclare:
		return p.parseDeclare()
	case KwIf:
		p.advance()
		return p.parseIf()
	case KwExec:
		p.advance()
		return p.parseExec()
	case KwCreate:
		p.advance()
		return p.parseCreate()
	case KwDrop:
		p.advance()
		return p.parseDrop()
	case KwAlter:
		p.advance()
		return p.parseAlter()
	case KwMerge:
		p.advance()
		return p.parseMerge()
	case KwPrint:
		p.advance()
		return p.parsePrint()
	case KwSet:
		p.advance()
		return p.parseSetStatement()
	case Identifier:
		if strings.ToUpper(p.getText(*tok)) == "BULK" {
			return p.parseBulkInsert()
		}
	}
	return nil
}

func (p *Parser) parseIf() Node {
	stmt := &IfStatement{}
	stmt.Condition = p.parseExpression()
	stmt.ThenBlock = p.parseBlock()
	if p.check(KwElse) {
		p.advance()
		stmt.ElseBlock = p.parseBlock()
	}
	return stmt
}

func (p *Parser) parseExec() Node {
	stmt := &ExecStatement{}
	if tk := p.peek(0); tk != nil && tk.Type == Identifier && strings.HasPrefix(p.getText(*tk), "@") {
		saved := p.pos
		varTok := p.advance()
		if p.matchOK(SymEqual) {
			stmt.ReturnVar = NewIdentifier(p.getText(varTok), nil)
		} else {
			p.pos = saved
		}
	}
	stmt.ProcName, _ = p.parseFullIdentifierSafe()
	for {
		tok := p.peek(0)
		if tok == nil || tok.Type == SymSemicolon || tok.Type == KwGo || tok.Type == EOF || tok.Type == KwEnd {
			break
		}
		if tok.Type == Identifier && strings.HasPrefix(p.getText(*tok), "@") {
			saved := p.pos
			nameTok := p.advance()
			if p.matchOK(SymEqual) {
				expr := p.parseExpression()
				stmt.NamedArgs = append(stmt.NamedArgs, &AssignmentNode{
					Column: NewIdentifier(p.getText(nameTok), nil), Right: expr})
			} else {
				p.pos = saved
				stmt.Args = append(stmt.Args, p.parseExpression())
			}
		} else {
			stmt.Args = append(stmt.Args, p.parseExpression())
		}
		if !p.matchOK(SymComma) {
			break
		}
	}
	return stmt
}

func (p *Parser) parseSetStatement() Node {
	stmt := &SetStatement{}
	tok := p.peek(0)
	if tok != nil && strings.HasPrefix(p.getText(*tok), "@") {
		stmt.Target = NewIdentifier(p.getText(p.advance()), nil)
		p.consume(SymEqual, "Expected = after variable in SET")
		stmt.Value = p.parseExpression()
		stmt.IsOption = false
	} else {
		optTok := p.advance()
		stmt.Target = strings.ToUpper(p.getText(optTok))
		valTok := p.advance()
		stmt.Value = strings.ToUpper(p.getText(valTok))
		stmt.IsOption = true
	}
	return stmt
}

func (p *Parser) parsePrint() Node {
	return &PrintStatement{Expr: p.parseExpression()}
}

func (p *Parser) parseCreate() Node {
	p.consume(KwTable, "Expected TABLE after CREATE")
	stmt := &CreateTableStatement{}
	if p.check(KwIf) {
		p.advance()
		p.consume(KwNot, "Expected NOT after IF")
		if !p.matchOK(KwExists) {
			p.consume(Identifier, "Expected EXISTS")
		}
		stmt.IfNotExists = true
	}
	stmt.Table, _ = p.parseFullIdentifierSafe()
	p.consume(SymLParen, "Expected ( after table name in CREATE TABLE")
	for {
		tk := p.peek(0)
		if tk == nil || tk.Type == SymRParen {
			break
		}
		if tk.Type == Identifier {
			u := strings.ToUpper(p.getText(*tk))
			if u == "PRIMARY" || u == "CONSTRAINT" || u == "INDEX" || u == "UNIQUE" {
				for {
					n := p.peek(0)
					if n == nil || n.Type == SymComma || n.Type == SymRParen {
						break
					}
					p.advance()
				}
				if !p.matchOK(SymComma) {
					break
				}
				continue
			}
		}
		stmt.Columns = append(stmt.Columns, p.parseColumnDef())
		if !p.matchOK(SymComma) {
			break
		}
	}
	p.consume(SymRParen, "Expected ) after column definitions")
	return stmt
}

func (p *Parser) parseColumnDef() *ColumnDefinitionNode {
	col := NewColumnDefinition()
	col.Name = p.getText(p.advance())
	col.DataType = strings.ToUpper(p.getText(p.advance()))
	if p.matchOK(SymLParen) {
		var parts []string
		for {
			tk := p.peek(0)
			if tk == nil || tk.Type == SymRParen {
				break
			}
			parts = append(parts, p.getText(p.advance()))
		}
		p.match(SymRParen)
		col.DataType += "(" + strings.Join(parts, ",") + ")"
	}
	for {
		tk := p.peek(0)
		if tk == nil || tk.Type == SymComma || tk.Type == SymRParen {
			break
		}
		txt := strings.ToUpper(p.getText(*tk))
		switch txt {
		case "NOT":
			p.advance()
			if strings.ToUpper(p.getText(p.advance())) == "NULL" {
				col.Nullable = false
			}
		case "NULL":
			p.advance()
			col.Nullable = true
		case "IDENTITY":
			p.advance()
			col.IsIdentity = true
			if p.matchOK(SymLParen) {
				for {
					n := p.peek(0)
					if n == nil || n.Type == SymRParen {
						break
					}
					p.advance()
				}
				p.match(SymRParen)
			}
		case "PRIMARY":
			p.advance()
			if n := p.peek(0); n != nil && strings.ToUpper(p.getText(*n)) == "KEY" {
				p.advance()
			}
			col.IsPrimaryKey = true
		case "DEFAULT":
			p.advance()
			col.Default = p.parseExpression()
		default:
			return col
		}
	}
	return col
}

func (p *Parser) parseDrop() Node {
	p.consume(KwTable, "Expected TABLE after DROP")
	stmt := &DropTableStatement{}
	if p.check(KwIf) {
		p.advance()
		if n := p.peek(0); n != nil && strings.ToUpper(p.getText(*n)) == "EXISTS" {
			p.advance()
			stmt.IfExists = true
		}
	}
	stmt.Table, _ = p.parseFullIdentifierSafe()
	return stmt
}

func (p *Parser) parseAlter() Node {
	p.consume(KwTable, "Expected TABLE after ALTER")
	stmt := &AlterTableStatement{}
	stmt.Table, _ = p.parseFullIdentifierSafe()
	if p.matchOK(KwAdd) {
		stmt.Action = "ADD"
		stmt.Column = p.parseColumnDef()
	} else if n := p.peek(0); n != nil && strings.ToUpper(p.getText(*n)) == "DROP" {
		p.advance()
		stmt.Action = "DROP"
		if c := p.peek(0); c != nil && strings.ToUpper(p.getText(*c)) == "COLUMN" {
			p.advance()
		}
		colTok := p.advance()
		stmt.Column = NewIdentifier(p.getText(colTok), nil)
	} else {
		p.fail("Expected ADD or DROP after table name in ALTER TABLE")
	}
	return stmt
}

func (p *Parser) parseMerge() Node {
	stmt := &MergeStatement{}
	p.match(KwInto)
	stmt.Target, _ = p.parseFullIdentifierSafe()
	if tk := p.peek(0); tk != nil && tk.Type != KwUsing {
		hasAs := p.matchOK(KwAs)
		var al Token
		var ok bool
		if hasAs {
			al, ok = p.matchAlias()
		} else {
			al, ok = p.match(Identifier)
		}
		if ok {
			stmt.TargetAlias = p.getText(al)
		}
	}
	p.consume(KwUsing, "Expected USING in MERGE")
	if p.check(SymLParen) {
		p.advance()
		stmt.Source = p.parseSelectWithSetOps()
		p.consume(SymRParen, "Expected ) after MERGE source")
	} else {
		stmt.Source, _ = p.parseFullIdentifierSafe()
	}
	hasAs := p.matchOK(KwAs)
	var al Token
	var ok bool
	if hasAs {
		al, ok = p.matchAlias()
	} else {
		al, ok = p.match(Identifier)
	}
	if ok {
		stmt.SourceAlias = p.getText(al)
	}
	p.consume(KwOn, "Expected ON in MERGE")
	stmt.OnCondition = p.parseExpression()
	for p.check(KwWhen) {
		stmt.Clauses = append(stmt.Clauses, p.parseMergeClause())
	}
	return stmt
}

func (p *Parser) parseMergeClause() *MergeClauseNode {
	p.consume(KwWhen, "Expected WHEN")
	clause := &MergeClauseNode{}
	if p.matchOK(KwNot) {
		p.consume(KwMatched, "Expected MATCHED after NOT")
		if n := p.peek(0); n != nil && strings.ToUpper(p.getText(*n)) == "BY" {
			p.advance()
			src := strings.ToUpper(p.getText(p.advance()))
			if src == "SOURCE" {
				clause.MatchType = "NOT_MATCHED_BY_SOURCE"
			} else {
				clause.MatchType = "NOT_MATCHED"
			}
		} else {
			clause.MatchType = "NOT_MATCHED"
		}
	} else {
		p.consume(KwMatched, "Expected MATCHED")
		clause.MatchType = "MATCHED"
	}
	if p.matchOK(KwAnd) {
		clause.Condition = p.parseExpression()
	}
	p.consume(KwThen, "Expected THEN in MERGE clause")
	if p.matchOK(KwUpdate) {
		clause.Action = "UPDATE"
		p.consume(KwSet, "Expected SET after UPDATE in MERGE")
		for {
			col, _ := p.parseFullIdentifierSafe()
			p.consume(SymEqual, "Expected = in SET")
			expr := p.parseExpression()
			clause.SetClauses = append(clause.SetClauses, &AssignmentNode{Column: col, Right: expr})
			if !p.matchOK(SymComma) {
				break
			}
		}
	} else if p.matchOK(KwInsert) {
		clause.Action = "INSERT"
		if p.matchOK(SymLParen) {
			for {
				col, _ := p.parseFullIdentifierSafe()
				clause.InsertColumns = append(clause.InsertColumns, col)
				if !p.matchOK(SymComma) {
					break
				}
			}
			p.consume(SymRParen, "Expected ) after INSERT columns")
		}
		p.consume(KwValues, "Expected VALUES in MERGE INSERT")
		p.consume(SymLParen, "Expected ( after VALUES")
		for {
			clause.InsertValues = append(clause.InsertValues, p.parseExpression())
			if !p.matchOK(SymComma) {
				break
			}
		}
		p.consume(SymRParen, "Expected ) after INSERT values")
	} else if p.matchOK(KwDelete) {
		clause.Action = "DELETE"
	} else {
		p.fail("Expected UPDATE, INSERT, or DELETE in MERGE clause")
	}
	return clause
}
