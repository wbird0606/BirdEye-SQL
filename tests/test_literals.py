import pytest
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser

def test_lexer_literals():
    """測試：Lexer 應能識別字串與數值常量"""
    sql = "SELECT 'Active', 100 FROM Users"
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    # 預期 Token 流：
    # tokens[1] -> 'Active' (STRING_LITERAL)
    # tokens[3] -> 100 (NUMERIC_LITERAL)
    
    # 目前執行會報警，因為 TokenType 中尚未定義這些類型
    assert tokens[1].type == TokenType.STRING_LITERAL
    assert tokens[3].type == TokenType.NUMERIC_LITERAL

def test_parser_literals_in_columns():
    """測試：Parser 應允許 Column List 中出現常量"""
    sql = "SELECT 'BirdEye' AS System, 2026 FROM Users"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    # 驗證 AST 節點
    assert ast.columns[0].name == "BirdEye"
    assert ast.columns[1].name == "2026"