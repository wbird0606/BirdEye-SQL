import pytest
from birdeye.lexer import Lexer, TokenType

def test_lexer_single_line_comment():
    """測試：應完全忽略單行註解 (-- 之後的內容)"""
    sql = "SELECT * FROM Users -- 這是機密註解\nWHERE 1=1"
    # 注意：雖然我們現在的 Parser 還沒支援 WHERE，但 Lexer 應該要能跳過註解
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    # 預期 Token：SELECT, *, FROM, Users, (換行後的) WHERE, 1, =, 1, EOF
    # 目前我們的 Lexer 看到 '--' 可能會報錯或將其視為標識符
    token_types = [t.type for t in tokens]
    
    # 驗證 'Users' 之後不應該出現任何註解內容
    # 目前你的程式碼會抓到 '-' 然後崩潰或誤判
    assert TokenType.IDENTIFIER in token_types # Users
    # 確保註解文字沒有被當成標識符
    for t in tokens:
        if t.type == TokenType.IDENTIFIER:
            text = sql[t.start:t.end]
            assert "這是機密註解" not in text

def test_lexer_multi_line_comment():
    """測試：應完全忽略多行註解 (/* ... */)"""
    sql = "SELECT /* 這裡被遮蔽了 */ UserID FROM Users"
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    # 預期 Token：SELECT, UserID, FROM, Users, EOF
    # 總共 5 個 Token
    assert len(tokens) == 5
    assert tokens[1].type == TokenType.IDENTIFIER # UserID