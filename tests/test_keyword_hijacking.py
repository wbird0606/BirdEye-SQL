import pytest
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser

def test_lexer_escaped_keyword():
    """測試：中括號內的關鍵字不應被誤認為 KEYWORD"""
    # 在 SQL 中，[SELECT] 是一個合法的欄位名稱
    sql = "SELECT [SELECT] FROM [Users]"
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    # 預期的 Token 流：
    # tokens[0] -> SELECT (KEYWORD)
    # tokens[1] -> [ (SYMBOL)
    # tokens[2] -> SELECT (這應該是 IDENTIFIER，因為它在括號內)
    
    assert tokens[2].type == TokenType.IDENTIFIER, f"Expected IDENTIFIER but got {tokens[2].type}"
    assert tokens[2].type != TokenType.KEYWORD_SELECT

def test_parser_with_escaped_keywords():
    """測試：Parser 應能正確處理以關鍵字命名的欄位"""
    sql = "SELECT [SELECT], [FROM] FROM Users"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    # 驗證 Parser 是否成功解析出名為 "SELECT" 與 "FROM" 的欄位
    assert ast.columns[0].name == "SELECT"
    assert ast.columns[1].name == "FROM"