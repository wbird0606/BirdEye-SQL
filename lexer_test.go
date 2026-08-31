package birdeye

import (
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_lexer_suite.py

func tokenTypes(t *testing.T, sql string) []TokenType {
	t.Helper()
	toks, err := NewLexer(sql).Tokenize()
	if err != nil {
		t.Fatalf("Tokenize(%q) error: %v", sql, err)
	}
	out := make([]TokenType, len(toks))
	for i, tk := range toks {
		out[i] = tk.Type
	}
	return out
}

func eqTypes(a, b []TokenType) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// --- 1. Token 序列邏輯測試 ---

func TestLexerTokenLogic(t *testing.T) {
	cases := []struct {
		sql  string
		want []TokenType
	}{
		{"SELECT UserID FROM Users", []TokenType{
			KwSelect, Identifier, KwFrom, Identifier, EOF,
		}},
		{"UPDATE Users SET Name = 'Bird' WHERE ID = 1", []TokenType{
			KwUpdate, Identifier, KwSet, Identifier,
			SymEqual, StringLiteral, KwWhere,
			Identifier, SymEqual, NumericLiteral, EOF,
		}},
		{"WHERE ID = 1 AND Status = 'A' OR Name = 'B'", []TokenType{
			KwWhere, Identifier, SymEqual, NumericLiteral,
			KwAnd, Identifier, SymEqual, StringLiteral,
			KwOr, Identifier, SymEqual, StringLiteral, EOF,
		}},
		{"SELECT 1.1 + 2.25", []TokenType{
			KwSelect, NumericLiteral, SymPlus, NumericLiteral, EOF,
		}},
		{"Users.UserName, dbo.Users.ID", []TokenType{
			Identifier, SymDot, Identifier, SymComma,
			Identifier, SymDot, Identifier, SymDot,
			Identifier, EOF,
		}},
		{"WHERE Name LIKE '%Bird%'", []TokenType{
			KwWhere, Identifier, KwLike, StringLiteral, EOF,
		}},
		{"SELECT 'O''Brien' FROM Users", []TokenType{
			KwSelect, StringLiteral, KwFrom, Identifier, EOF,
		}},
	}
	for _, c := range cases {
		if got := tokenTypes(t, c.sql); !eqTypes(got, c.want) {
			t.Errorf("%q\n got %v\nwant %v", c.sql, got, c.want)
		}
	}
}

// --- 2. 註解過濾安全性測試 ---

func TestLexerCommentsHandling(t *testing.T) {
	cases := []struct {
		sql     string
		comment string
	}{
		{"SELECT * FROM Users -- 這是機密註解\nWHERE 1=1", "這是機密註解"},
		{"SELECT /* 遮蔽 */ UserID FROM Users", "遮蔽"},
		{"UPDATE Users /* 審計備註 */ SET Name = 'Bird' WHERE ID = 1", "審計備註"},
		{"DELETE FROM Users -- 刪除離職員工\nWHERE Status = 'Old'", "刪除離職員工"},
		{"INSERT INTO Logs /* 系統自動寫入 */ VALUES (1, 'Success')", "系統自動寫入"},
	}
	for _, c := range cases {
		toks, err := NewLexer(c.sql).Tokenize()
		if err != nil {
			t.Fatalf("Tokenize(%q): %v", c.sql, err)
		}
		runes := []rune(c.sql)
		for _, tk := range toks {
			if tk.Type != Identifier {
				continue
			}
			slice := string(runes[tk.Start:tk.End])
			if strings.Contains(slice, c.comment) {
				t.Errorf("%q: 註解 %q 滲入 IDENTIFIER token 內容 %q", c.sql, c.comment, slice)
			}
		}
	}
}

// --- 3. 語意完整性錯誤攔截 ---

func TestLexerIntegrityErrors(t *testing.T) {
	cases := []struct {
		sql  string
		want string
	}{
		{"SELECT [UserID FROM Users", "Unclosed bracket"},
		{"SELECT 'Active FROM Users", "Unclosed string literal"},
		{"INSERT INTO Users (UserID, Name VALUES (1, 'B')", "Unclosed bracket"},
		{"SELECT * FROM Users /* 開始註解但未閉合", "Unclosed nested block comment"},
	}
	for _, c := range cases {
		_, err := NewLexer(c.sql).Tokenize()
		if err == nil {
			t.Errorf("%q: 預期錯誤 %q，卻成功", c.sql, c.want)
			continue
		}
		if !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q: 錯誤 %q 不含 %q", c.sql, err.Error(), c.want)
		}
		if be, ok := err.(*Error); ok && be.Kind != ErrValue && be.Kind != ErrSyntax {
			t.Errorf("%q: 錯誤分類 %v 不是 value/syntax", c.sql, be.Kind)
		}
	}
}
