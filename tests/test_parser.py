import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser, SelectStatement, IdentifierNode

def test_parser_simple_select_star():
    """測試：最基礎的 SELECT * 語句"""
    sql = "SELECT * FROM Users"
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    # Parser 需要原始字串才能把 Zero-copy token 還原成實際的字串值
    parser = Parser(tokens, sql)
    ast = parser.parse()
    
    assert isinstance(ast, SelectStatement)
    assert ast.is_select_star is True
    assert len(ast.columns) == 0
    assert ast.table.name.upper() == "USERS" # 統一轉大寫比對

def test_parser_select_columns():
    """測試：指定多個欄位的 SELECT 語句"""
    sql = "SELECT UserID, UserName FROM Orders"
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    parser = Parser(tokens, sql)
    ast = parser.parse()
    
    assert isinstance(ast, SelectStatement)
    assert ast.is_select_star is False
    assert len(ast.columns) == 2
    assert ast.columns[0].name.upper() == "USERID"
    assert ast.columns[1].name.upper() == "USERNAME"
    assert ast.table.name.upper() == "ORDERS"

def test_parser_missing_from_error():
    """測試：語法錯誤偵測 (缺少 FROM)"""
    sql = "SELECT UserID Users" # 故意漏掉 FROM 和逗號
    lexer = Lexer(sql)
    tokens = lexer.tokenize()

    parser = Parser(tokens, sql)

    # 將 match 從 "Expected FROM keyword" 改為 "Expected FROM"
    with pytest.raises(SyntaxError, match="Expected FROM"):
        parser.parse()