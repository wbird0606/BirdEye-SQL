package birdeye

import (
	"regexp"
	"strings"
)

// PIVOT／UNPIVOT（KNOWN_DEVIATIONS A18）。
//
// 僅支援接在「基底 FROM 來源」（資料表或衍生資料表）之後的 PIVOT／UNPIVOT；
// JOIN 之來源、UPDATE／DELETE ... FROM 內之 PIVOT 一律 Fail-Closed。
// 名稱以白名單字元集驗證後才保存（重建後之 SQL 會被執行，不容許引號或括號混入）。

var (
	pivotNameRe  = regexp.MustCompile(`^[\p{L}\p{N}_ .\-]+$`)
	pivotAggs    = map[string]bool{"SUM": true, "MAX": true, "MIN": true, "AVG": true, "COUNT": true}
	pivotPlainRe = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)
)

// atPivotClause 判斷目前位置是否為 PIVOT ( 或 UNPIVOT ( 之開頭。
func (p *Parser) atPivotClause() bool {
	t, n := p.peek(0), p.peek(1)
	if t == nil || n == nil || t.Type != Identifier || n.Type != SymLParen {
		return false
	}
	w := strings.ToUpper(p.rawTokText(*t))
	return w == "PIVOT" || w == "UNPIVOT"
}

func (p *Parser) pivotIdent(what string) string {
	t := p.consume(Identifier, "Expected "+what+" in PIVOT/UNPIVOT")
	name := p.getText(t)
	if !pivotNameRe.MatchString(name) {
		p.fail("Unsupported characters in " + what)
	}
	return name
}

// parsePivotClause 解析 PIVOT (...) [AS] 別名 或 UNPIVOT (...) [AS] 別名。
func (p *Parser) parsePivotClause() *PivotClause {
	pc := &PivotClause{Kind: strings.ToUpper(p.rawTokText(p.advance()))}
	p.consume(SymLParen, "Expected ( after "+pc.Kind)
	if pc.Kind == "PIVOT" {
		agg := p.forWord("aggregate function")
		if !pivotAggs[agg] {
			p.fail("Unsupported PIVOT aggregate: " + agg)
		}
		pc.Agg = agg
		p.consume(SymLParen, "Expected ( after PIVOT aggregate")
		pc.ValueCol = p.pivotIdent("PIVOT value column")
		p.consume(SymRParen, "Expected ) after PIVOT value column")
	} else {
		pc.ValueCol = p.pivotIdent("UNPIVOT value column")
	}
	if w := p.forWord("FOR"); w != "FOR" {
		p.fail("Expected FOR in " + pc.Kind)
	}
	pc.ForCol = p.pivotIdent(pc.Kind + " FOR column")
	if w := p.forWord("IN"); w != "IN" {
		p.fail("Expected IN in " + pc.Kind)
	}
	p.consume(SymLParen, "Expected ( after IN")
	for {
		pc.InList = append(pc.InList, p.pivotIdent(pc.Kind+" IN column"))
		if !p.matchOK(SymComma) {
			break
		}
	}
	p.consume(SymRParen, "Expected ) after IN list")
	p.consume(SymRParen, "Expected ) after "+pc.Kind)
	p.match(KwAs)
	al, ok := p.matchAlias()
	if !ok {
		p.fail(pc.Kind + " requires an alias")
	}
	pc.Alias = p.getText(al)
	if !pivotNameRe.MatchString(pc.Alias) {
		p.fail("Unsupported characters in " + pc.Kind + " alias")
	}
	return pc
}

// bracketName 將名稱以方括號輸出（名稱已通過白名單，不含括號）。
func bracketName(s string) string { return "[" + s + "]" }

// plainOrBracket 為單純識別字時原樣輸出，否則加方括號。
func plainOrBracket(s string) string {
	if pivotPlainRe.MatchString(s) {
		return s
	}
	return bracketName(s)
}

// sqlPivot 重建 PIVOT／UNPIVOT 子句。
func (rc *Reconstructor) sqlPivot(pv map[string]any) string {
	var in []string
	for _, v := range dslice(pv, "in_list") {
		if s, ok := v.(string); ok {
			in = append(in, bracketName(s))
		}
	}
	list := strings.Join(in, ", ")
	alias := " AS " + plainOrBracket(dstr(pv, "alias"))
	if dstr(pv, "kind") == "UNPIVOT" {
		return "UNPIVOT (" + bracketName(dstr(pv, "value_col")) + " FOR " + bracketName(dstr(pv, "for_col")) + " IN (" + list + "))" + alias
	}
	return "PIVOT (" + dstr(pv, "agg") + "(" + bracketName(dstr(pv, "value_col")) + ") FOR " + bracketName(dstr(pv, "for_col")) + " IN (" + list + "))" + alias
}

// applyPivot 於綁定時以 PIVOT／UNPIVOT 之輸出欄位取代基底來源在目前範圍中之登記：
// 轉置後只能經 PIVOT 別名引用輸出欄位，原來源之別名與欄位不再可見。
func (b *Binder) applyPivot(stmt *SelectStatement) {
	pv := stmt.Pivot
	src := newColSchema()
	switch t := stmt.Table.(type) {
	case *IdentifierNode:
		rt := tableKey(t)
		if vs, ok := b.virtualSchema(rt); ok {
			for _, n := range vs.names {
				src.set(n, vs.types[n])
			}
		} else {
			for _, n := range b.registry.GetColumns(rt) {
				src.set(n, b.registry.GetColumnType(rt, strings.ToUpper(n)))
			}
		}
	default:
		for _, c := range queryColumns(stmt.Table) {
			if n := columnOutputName(c); n != "" {
				src.set(n, inferredTypeOf(c))
			}
		}
	}
	need := func(col string) {
		if _, ok := src.get(col); !ok {
			b.sem("Column '" + col + "' not found in " + pv.Kind + " source")
		}
	}
	out := newColSchema()
	add := func(name, typ string) {
		if _, dup := out.get(name); dup {
			b.sem("Duplicate column '" + name + "' in " + pv.Kind + " output")
		}
		out.set(name, typ)
	}
	used := map[string]bool{}
	if pv.Kind == "PIVOT" {
		need(pv.ValueCol)
		need(pv.ForCol)
		used[strings.ToUpper(pv.ValueCol)] = true
		used[strings.ToUpper(pv.ForCol)] = true
		for _, n := range src.names {
			if !used[n] {
				add(n, src.types[n])
			}
		}
		for _, v := range pv.InList {
			add(v, "UNKNOWN")
		}
	} else {
		firstType := "UNKNOWN"
		for i, v := range pv.InList {
			need(v)
			used[strings.ToUpper(v)] = true
			if i == 0 {
				firstType = src.types[strings.ToUpper(v)]
			}
		}
		for _, n := range src.names {
			if !used[n] {
				add(n, src.types[n])
			}
		}
		add(pv.ValueCol, firstType)
		add(pv.ForCol, "NVARCHAR")
	}
	key := strings.ToUpper(pv.Alias)
	b.scopes[len(b.scopes)-1] = newScopeFrame()
	b.nullableStack[len(b.nullableStack)-1] = map[string]bool{}
	b.cteSchemas[key] = out
	b.topScope().set(key, key)
}
