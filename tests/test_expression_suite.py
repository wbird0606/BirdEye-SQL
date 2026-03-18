import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser

def test_parse_arithmetic_expression():
    """驗證加法表達式的解析邏輯"""
    sql = "SELECT UserID + 100 FROM Users"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    # 預期第一個欄位是 ExpressionNode
    col = ast.columns[0]
    assert col.left.name == "UserID"
    assert col.operator == "+"
    assert col.right.name == "100" # 數字目前暫記為 IdentifierNode 或 Literal

def test_parse_function_call():
    """驗證函數調用的解析邏輯"""
    sql = "SELECT COUNT(*) FROM Users"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    col = ast.columns[0]
    assert col.name.upper() == "COUNT"
    assert ast.is_select_star is True # 簡化處理：函數內的星號