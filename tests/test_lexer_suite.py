import pytest
from birdeye.lexer import Lexer, TokenType

@pytest.mark.parametrize("sql, expected_types", [
    # 基礎 Token 序列
    ("SELECT UserID FROM Users", [
        TokenType.KEYWORD_SELECT, TokenType.IDENTIFIER, 
        TokenType.KEYWORD_FROM, TokenType.IDENTIFIER, TokenType.EOF
    ]),
    ("Users.UserName, Users.UserID", [
        TokenType.IDENTIFIER, TokenType.SYMBOL_DOT, TokenType.IDENTIFIER, 
        TokenType.SYMBOL_COMMA, TokenType.IDENTIFIER, TokenType.SYMBOL_DOT, 
        TokenType.IDENTIFIER, TokenType.EOF
    ]),
    # 常量識別
    ("SELECT 'Active', 100", [
        TokenType.KEYWORD_SELECT, TokenType.STRING_LITERAL, 
        TokenType.SYMBOL_COMMA, TokenType.NUMERIC_LITERAL, TokenType.EOF
    ]),
])
def test_lexer_token_logic(sql, expected_types):
    """驗證 Lexer 產出的 Token 序列類型與常量識別是否正確"""
    lexer = Lexer(sql)
    tokens = [t.type for t in lexer.tokenize()]
    assert tokens == expected_types

@pytest.mark.parametrize("sql, comment_text", [
    # 註解過濾驗證
    ("SELECT * FROM Users -- 這是機密註解\nWHERE 1=1", "這是機密註解"),
    ("SELECT /* 這裡被遮蔽了 */ UserID FROM Users", "這裡被遮蔽了"),
])
def test_lexer_comments_handling(sql, comment_text):
    """驗證單行與多行註解內容不應滲透進標識符內容中"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    for t in tokens:
        if t.type == TokenType.IDENTIFIER:
            text = sql[t.start:t.end]
            assert comment_text not in text

@pytest.mark.parametrize("sql, error_msg", [
    # 符號完整性檢查
    ("SELECT [UserID FROM Users", "Unclosed bracket"),
    ("SELECT 'Active FROM Users", "Unclosed string literal"),
])
def test_lexer_integrity_errors(sql, error_msg):
    """測試 Lexer 對於未閉合符號的報警機制"""
    lexer = Lexer(sql)
    with pytest.raises(ValueError, match=error_msg):
        lexer.tokenize()