import pytest
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser

def test_lexer_with_spaces_in_brackets():
    """
    Issue #16 測試：中括號內應支援空格 (MSSQL 標識符慣用法)
    例如 [First Name] 應該被解析為一個單一的 IDENTIFIER
    """
    sql = "SELECT [First Name] FROM Users"
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    # 預期 Token 流：
    # tokens[0] -> SELECT (KEYWORD)
    # tokens[1] -> [ (SYMBOL_BRACKET_L)
    # tokens[2] -> First Name (這必須是單一的 IDENTIFIER，且包含空格)
    # tokens[3] -> ] (SYMBOL_BRACKET_R)
    
    # 驗證 Token 類型
    assert tokens[2].type == TokenType.IDENTIFIER
    
    # 驗證 Token 內容 (透過切片還原)
    identifier_text = sql[tokens[2].start:tokens[2].end]
    assert identifier_text == "First Name", f"Expected 'First Name' but got '{identifier_text}'"

def test_parser_with_space_identifiers():
    """測試 Parser 是否能處理帶空格的 AST 節點"""
    sql = "SELECT [Last Name] FROM Users"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    assert ast.columns[0].name == "Last Name"