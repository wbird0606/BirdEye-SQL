import pytest
from birdeye.lexer import Lexer, TokenType

# --- 1. Token 序列邏輯測試 ---
@pytest.mark.parametrize("sql, expected_types", [
    # 基礎查詢 Token
    ("SELECT UserID FROM Users", [
        TokenType.KEYWORD_SELECT, TokenType.IDENTIFIER, 
        TokenType.KEYWORD_FROM, TokenType.IDENTIFIER, TokenType.EOF
    ]),
    # DML 關鍵字與變更操作 (Issue #27, #28)
    ("UPDATE Users SET Name = 'Bird' WHERE ID = 1", [
        TokenType.KEYWORD_UPDATE, TokenType.IDENTIFIER, TokenType.KEYWORD_SET, TokenType.IDENTIFIER, 
        TokenType.SYMBOL_EQUAL, TokenType.STRING_LITERAL, TokenType.KEYWORD_WHERE, 
        TokenType.IDENTIFIER, TokenType.SYMBOL_EQUAL, TokenType.NUMERIC_LITERAL, TokenType.EOF
    ]),
    # 邏輯運算子與複合條件
    ("WHERE ID = 1 AND Status = 'A' OR Name = 'B'", [
        TokenType.KEYWORD_WHERE, TokenType.IDENTIFIER, TokenType.SYMBOL_EQUAL, TokenType.NUMERIC_LITERAL,
        TokenType.KEYWORD_AND, TokenType.IDENTIFIER, TokenType.SYMBOL_EQUAL, TokenType.STRING_LITERAL,
        TokenType.KEYWORD_OR, TokenType.IDENTIFIER, TokenType.SYMBOL_EQUAL, TokenType.STRING_LITERAL, TokenType.EOF
    ]),
    # 浮點數支援驗證 (修復 1.1 解析漏洞)
    ("SELECT 1.1 + 2.25", [
        TokenType.KEYWORD_SELECT, TokenType.NUMERIC_LITERAL, TokenType.SYMBOL_PLUS, TokenType.NUMERIC_LITERAL, TokenType.EOF
    ]),
    # 多層級路徑識別
    ("Users.UserName, dbo.Users.ID", [
        TokenType.IDENTIFIER, TokenType.SYMBOL_DOT, TokenType.IDENTIFIER, TokenType.SYMBOL_COMMA,
        TokenType.IDENTIFIER, TokenType.SYMBOL_DOT, TokenType.IDENTIFIER, TokenType.SYMBOL_DOT, 
        TokenType.IDENTIFIER, TokenType.EOF
    ]),
])
def test_lexer_token_logic(sql, expected_types):
    """驗證 Lexer 產出的 Token 序列類型與常量識別是否正確"""
    lexer = Lexer(sql)
    tokens = [t.type for t in lexer.tokenize()]
    assert tokens == expected_types

# --- 2. 註解過濾安全性測試 ---
@pytest.mark.parametrize("sql, comment_text", [
    # SELECT 中的註解過濾
    ("SELECT * FROM Users -- 這是機密註解\nWHERE 1=1", "這是機密註解"),
    ("SELECT /* 遮蔽 */ UserID FROM Users", "遮蔽"),
    # DML 語句中的註解混淆測試
    ("UPDATE Users /* 審計備註 */ SET Name = 'Bird' WHERE ID = 1", "審計備註"),
    ("DELETE FROM Users -- 刪除離職員工\nWHERE Status = 'Old'", "刪除離職員工"),
    # INSERT 中的註解
    ("INSERT INTO Logs /* 系統自動寫入 */ VALUES (1, 'Success')", "系統自動寫入"),
])
def test_lexer_comments_handling(sql, comment_text):
    """驗證註解內容不應滲透進標識符中，確保 ZTA 審計的原始語意乾淨"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    for t in tokens:
        if t.type == TokenType.IDENTIFIER:
            text = sql[t.start:t.end]
            assert comment_text not in text

# --- 3. 語意完整性錯誤攔截 ---
@pytest.mark.parametrize("sql, error_msg", [
    # 標識符與字串完整性
    ("SELECT [UserID FROM Users", "Unclosed bracket"),
    ("SELECT 'Active FROM Users", "Unclosed string literal"),
    # INSERT 括號完整性 (Issue #28)
    ("INSERT INTO Users (UserID, Name VALUES (1, 'B')", "Unclosed bracket"), 
    # 註解完整性
    ("SELECT * FROM Users /* 開始註解但未閉合", "Unclosed nested block comment"),
])
def test_lexer_integrity_errors(sql, error_msg):
    """測試 Lexer 對於 DQL/DML 各種未閉合符號的報警機制"""
    lexer = Lexer(sql)
    # 同時支援 ValueError 或 SyntaxError 攔截
    with pytest.raises((ValueError, SyntaxError), match=error_msg):
        lexer.tokenize()