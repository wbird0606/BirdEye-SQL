import pytest
from birdeye.lexer import Lexer

def test_lexer_unclosed_bracket():
    """測試：中括號未閉合應拋出 ValueError"""
    # 故意漏掉結尾的 ]
    sql = "SELECT [UserID FROM Users"
    lexer = Lexer(sql)
    
    # 預期在 tokenize 過程中發現結尾時狀態不對，拋出錯誤
    with pytest.raises(ValueError, match="Unclosed bracket"):
        lexer.tokenize()

def test_lexer_unclosed_string():
    """測試：單引號字串未閉合應拋出 ValueError"""
    # 故意漏掉結尾的 '
    sql = "SELECT 'Active FROM Users"
    lexer = Lexer(sql)
    
    with pytest.raises(ValueError, match="Unclosed string literal"):
        lexer.tokenize()