package birdeye

import (
	"regexp"
	"strings"
)

// FOR XML / FOR JSON 為 SELECT 結尾之輸出格式子句，只改變結果集的呈現方式，
// 不改變被讀取的欄位與資料表，故意圖萃取與列過濾不受影響。
//
// 本實作只接受已知之模式與選項，內容以白名單重組後保存於 SelectStatement.ForClause，
// 重建 SQL 時原樣輸出（重建後之 SQL 會被執行，故任何未知記號均 Fail-Closed）。
// 與 Python 基準之差異見 KNOWN_DEVIATIONS.md（A15）。

var (
	forWordRe = regexp.MustCompile(`^[A-Za-z_][A-Za-z_]*$`)
	// 模式名稱與 ROOT 名稱之安全字元集（不含引號，避免重建 SQL 時被注入）
	forNameRe = regexp.MustCompile(`^[A-Za-z0-9_.:\- ]*$`)
)

var (
	forXMLModes  = map[string]bool{"AUTO": true, "RAW": true, "PATH": true, "EXPLICIT": true}
	forJSONModes = map[string]bool{"AUTO": true, "PATH": true}
)

// rawTokText 回傳記號之原始文字（不剝除方括號），用於區分 FOR 與 [FOR]。
func (p *Parser) rawTokText(t Token) string {
	if t.Value != "" {
		return t.Value
	}
	if t.Start >= 0 && t.End <= len(p.src) && t.Start <= t.End {
		return string(p.src[t.Start:t.End])
	}
	return ""
}

// atForClause 判斷目前位置是否為 FOR XML / FOR JSON 子句之開頭。
func (p *Parser) atForClause() bool {
	t, n := p.peek(0), p.peek(1)
	if t == nil || n == nil || t.Type != Identifier {
		return false
	}
	if !strings.EqualFold(p.rawTokText(*t), "FOR") {
		return false
	}
	u := strings.ToUpper(p.rawTokText(*n))
	return u == "XML" || u == "JSON"
}

// matchPlainAlias 與 match(Identifier) 相同，但不把 FOR XML／FOR JSON 之 FOR 當成別名。
func (p *Parser) matchPlainAlias() (Token, bool) {
	if p.atForClause() || p.atPivotClause() {
		return Token{}, false
	}
	return p.match(Identifier)
}

// forWord 讀取一個純字母之關鍵字記號並轉大寫。
func (p *Parser) forWord(what string) string {
	t := p.peek(0)
	if t == nil || t.Type == EOF {
		p.fail("Unexpected end of FOR clause: expected " + what)
	}
	w := p.rawTokText(*t)
	if !forWordRe.MatchString(w) {
		p.fail("Unsupported FOR clause token: " + w)
	}
	p.advance()
	return strings.ToUpper(w)
}

// forName 讀取括號內之字串名稱：( 'name' )。
func (p *Parser) forName(what string) string {
	p.consume(SymLParen, "Expected ( after "+what)
	t := p.consume(StringLiteral, "Expected string literal in "+what)
	name := strings.Trim(p.rawTokText(t), "'")
	if !forNameRe.MatchString(name) {
		p.fail("Unsupported characters in " + what)
	}
	p.consume(SymRParen, "Expected ) after "+what)
	return "('" + name + "')"
}

// parseForClause 解析並正規化 FOR XML / FOR JSON 子句，回傳可直接重建之文字。
func (p *Parser) parseForClause() string {
	p.advance() // FOR
	kind := p.forWord("XML or JSON")
	out := "FOR " + kind

	mode := p.forWord("mode")
	modes := forXMLModes
	if kind == "JSON" {
		modes = forJSONModes
	}
	if !modes[mode] {
		p.fail("Unsupported FOR " + kind + " mode: " + mode)
	}
	out += " " + mode
	if (mode == "RAW" || mode == "PATH") && p.check(SymLParen) {
		out += p.forName("FOR " + kind + " " + mode)
	}

	seen := map[string]bool{}
	for p.matchOK(SymComma) {
		opt := p.forWord("option")
		if seen[opt] {
			p.fail("Duplicate FOR clause option: " + opt)
		}
		seen[opt] = true
		switch {
		case kind == "XML" && opt == "ELEMENTS":
			out += ", ELEMENTS"
			if t := p.peek(0); t != nil {
				switch strings.ToUpper(p.rawTokText(*t)) {
				case "XSINIL", "ABSENT":
					out += " " + p.forWord("ELEMENTS option")
				}
			}
		case kind == "XML" && opt == "TYPE":
			out += ", TYPE"
		case kind == "XML" && opt == "BINARY":
			if b := p.forWord("BASE64"); b != "BASE64" {
				p.fail("Unsupported BINARY option: " + b)
			}
			out += ", BINARY BASE64"
		case opt == "ROOT":
			out += ", ROOT"
			if p.check(SymLParen) {
				out += p.forName("ROOT")
			}
		case kind == "JSON" && (opt == "INCLUDE_NULL_VALUES" || opt == "WITHOUT_ARRAY_WRAPPER"):
			out += ", " + opt
		default:
			p.fail("Unsupported FOR " + kind + " option: " + opt)
		}
	}
	return out
}
