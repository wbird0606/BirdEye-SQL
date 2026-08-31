package birdeye

import (
	"strings"
	"unicode"
)

// Lexer 對照 Python birdeye/lexer.py 的 Lexer。
// src 以 []rune 保存，pos / Token.Start / Token.End 皆為碼位索引，與 Python
// 字串索引語意一致。
type Lexer struct {
	src      []rune
	pos      int
	tokens   []Token
	brackets []rune // 對照 _bracket_stack
}

// NewLexer 建立 lexer。
func NewLexer(source string) *Lexer {
	return &Lexer{src: []rune(source)}
}

// peek 回傳 pos+offset 處的 rune；越界回傳 0（對照 Python _peek 的 None）。
func (l *Lexer) peek(offset int) rune {
	i := l.pos + offset
	if i < 0 || i >= len(l.src) {
		return 0
	}
	return l.src[i]
}

// advance 消耗並回傳目前 rune；越界回傳 0。
func (l *Lexer) advance() rune {
	if l.pos >= len(l.src) {
		return 0
	}
	ch := l.src[l.pos]
	l.pos++
	return ch
}

func (l *Lexer) emit(t TokenType, value string, start, end int) {
	l.tokens = append(l.tokens, Token{Type: t, Value: value, Start: start, End: end})
}

func isIdentStart(ch rune) bool {
	return unicode.IsLetter(ch) || ch == '_' || ch == '#' || ch == '@'
}

func isIdentPart(ch rune) bool {
	return unicode.IsLetter(ch) || unicode.IsDigit(ch) || ch == '_' || ch == '#'
}

// Tokenize 把來源轉成 token 序列（結尾必有 EOF）。
func (l *Lexer) Tokenize() ([]Token, error) {
	for l.pos < len(l.src) {
		ch := l.peek(0)

		if unicode.IsSpace(ch) {
			l.advance()
			continue
		}

		// 1. 註解
		if ch == '-' && l.peek(1) == '-' {
			l.advance()
			l.advance()
			for c := l.peek(0); c != 0 && c != '\n'; c = l.peek(0) {
				l.advance()
			}
			continue
		}
		if ch == '/' && l.peek(1) == '*' {
			l.advance()
			l.advance()
			closed := false
			for l.peek(0) != 0 {
				if l.peek(0) == '*' && l.peek(1) == '/' {
					l.advance()
					l.advance()
					closed = true
					break
				}
				l.advance()
			}
			if !closed {
				return nil, valueErr("Unclosed nested block comment")
			}
			continue
		}

		// 2. 識別符與關鍵字（支援 # 臨時表、@ 變數）
		if isIdentStart(ch) {
			if (ch == 'N' || ch == 'n') && l.peek(1) == '\'' {
				// N'' Unicode 字串前綴：消耗 N，落到下方字串解析
				l.advance()
				ch = l.peek(0)
			} else {
				start := l.pos
				l.advance()
				for isIdentPart(l.peek(0)) {
					l.advance()
				}
				text := string(l.src[start:l.pos])
				tt, ok := keywords[strings.ToUpper(text)]
				if !ok {
					tt = Identifier
				}
				l.emit(tt, text, start, l.pos)
				continue
			}
		}

		// 3. 數字
		if unicode.IsDigit(ch) {
			start := l.pos
			for unicode.IsDigit(l.peek(0)) {
				l.advance()
			}
			if l.peek(0) == '.' && unicode.IsDigit(l.peek(1)) {
				l.advance()
				for unicode.IsDigit(l.peek(0)) {
					l.advance()
				}
			}
			l.emit(NumericLiteral, string(l.src[start:l.pos]), start, l.pos)
			continue
		}

		// 4. 字串（含 '' 轉義）
		if ch == '\'' {
			start := l.pos
			l.advance()
			for l.peek(0) != 0 {
				if l.peek(0) == '\'' {
					if l.peek(1) == '\'' {
						l.advance()
						l.advance()
						continue
					}
					break
				}
				l.advance()
			}
			if l.peek(0) == 0 {
				return nil, valueErr("Unclosed string literal")
			}
			l.advance() // 關閉引號
			raw := string(l.src[start:l.pos])
			l.emit(StringLiteral, strings.ReplaceAll(raw, "''", "'"), start, l.pos)
			continue
		}

		// 5. MSSQL 中括號識別符
		if ch == '[' {
			start := l.pos
			l.advance()
			l.brackets = append(l.brackets, '[')
			for c := l.peek(0); c != 0 && c != ']'; c = l.peek(0) {
				l.advance()
			}
			if l.peek(0) == 0 {
				return nil, valueErr("Unclosed bracket")
			}
			l.advance() // ]
			l.brackets = l.brackets[:len(l.brackets)-1]
			l.emit(Identifier, string(l.src[start+1:l.pos-1]), start, l.pos)
			continue
		}

		// 6 & 7. 運算子與括號
		switch ch {
		case '=':
			l.emit(SymEqual, "=", l.pos, l.pos+1)
			l.advance()
		case '>':
			if l.peek(1) == '=' {
				l.emit(SymGE, ">=", l.pos, l.pos+2)
				l.advance()
				l.advance()
			} else {
				l.emit(SymGT, ">", l.pos, l.pos+1)
				l.advance()
			}
		case '<':
			if l.peek(1) == '=' {
				l.emit(SymLE, "<=", l.pos, l.pos+2)
				l.advance()
				l.advance()
			} else if l.peek(1) == '>' {
				l.emit(SymNE, "<>", l.pos, l.pos+2)
				l.advance()
				l.advance()
			} else {
				l.emit(SymLT, "<", l.pos, l.pos+1)
				l.advance()
			}
		case '!':
			if l.peek(1) == '=' {
				l.emit(SymNE, "!=", l.pos, l.pos+2)
				l.advance()
				l.advance()
			} else {
				l.advance()
			}
		case '*':
			l.emit(SymAsterisk, "*", l.pos, l.pos+1)
			l.advance()
		case ',':
			l.emit(SymComma, ",", l.pos, l.pos+1)
			l.advance()
		case '.':
			l.emit(SymDot, ".", l.pos, l.pos+1)
			l.advance()
		case '+':
			l.emit(SymPlus, "+", l.pos, l.pos+1)
			l.advance()
		case '-':
			l.emit(SymMinus, "-", l.pos, l.pos+1)
			l.advance()
		case '/':
			l.emit(SymSlash, "/", l.pos, l.pos+1)
			l.advance()
		case '%':
			l.emit(SymPercent, "%", l.pos, l.pos+1)
			l.advance()
		case '&':
			l.emit(SymAmpersand, "&", l.pos, l.pos+1)
			l.advance()
		case '|':
			l.emit(SymPipe, "|", l.pos, l.pos+1)
			l.advance()
		case '^':
			l.emit(SymCaret, "^", l.pos, l.pos+1)
			l.advance()
		case '~':
			l.emit(SymTilde, "~", l.pos, l.pos+1)
			l.advance()
		case ';':
			l.emit(SymSemicolon, ";", l.pos, l.pos+1)
			l.advance()
		case '(':
			l.emit(SymLParen, "(", l.pos, l.pos+1)
			l.brackets = append(l.brackets, '(')
			l.advance()
		case ')':
			if n := len(l.brackets); n > 0 && l.brackets[n-1] == '(' {
				l.brackets = l.brackets[:n-1]
			}
			l.emit(SymRParen, ")", l.pos, l.pos+1)
			l.advance()
		default:
			l.advance()
		}
	}

	if len(l.brackets) > 0 {
		return nil, valueErr("Unclosed bracket")
	}
	l.emit(EOF, "", l.pos, l.pos)
	return l.tokens, nil
}
