import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser

def test_strict_double_comma():
    """測試：禁止連續逗號 (SELECT UserID, , UserName)"""
    sql = "SELECT UserID, , UserName FROM Users"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    # 預期拋出 SyntaxError，且訊息包含 "Expected identifier"
    with pytest.raises(SyntaxError, match="Expected identifier"):
        parser.parse()

def test_strict_trailing_comma():
    """測試：禁止尾隨逗號 (SELECT UserID, FROM Users)"""
    sql = "SELECT UserID, FROM Users"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    with pytest.raises(SyntaxError, match="Expected identifier"):
        parser.parse()