import pytest
from birdeye.lexer import Lexer, TokenType

def test_lexer_zero_copy_basic():
    """測試：基礎 SQL 解析，驗證絕對不產生新字串，只記錄 Index"""
    sql = "SELECT UserID FROM Users"
    #      012345 6 789012 3 4567 8 90123
    #      SELECT   UserID   FROM   Users
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    # 預期 Token 數量：SELECT, UserID, FROM, Users, EOF
    assert len(tokens) == 5
    
    # 1. SELECT (index 0~6, 注意 python slice 是左閉右開，所以 end 是 6)
    assert tokens[0].type == TokenType.KEYWORD_SELECT
    assert tokens[0].start == 0
    assert tokens[0].end == 6
    
    # 2. UserID (index 7~13)
    assert tokens[1].type == TokenType.IDENTIFIER
    assert tokens[1].start == 7
    assert tokens[1].end == 13

def test_lexer_ignore_whitespace_and_case():
    """測試：自動忽略空白字元、換行，並能識別大小寫混雜的關鍵字"""
    sql = "  sElEcT \n\t * \r\n fRoM table1  "
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    assert tokens[0].type == TokenType.KEYWORD_SELECT
    assert tokens[0].start == 2
    assert tokens[0].end == 8
    
    assert tokens[1].type == TokenType.SYMBOL_ASTERISK
    assert tokens[1].start == 12
    assert tokens[1].end == 13
    
    assert tokens[2].type == TokenType.KEYWORD_FROM
    assert tokens[2].start == 17  # 正確的起點
    assert tokens[2].end == 21    # 正確的終點

def test_lexer_symbols_and_punctuation():
    """測試：符號解析 (逗號、句號)"""
    sql = "Users.UserName, Users.UserID"
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    
    # 預期結構: IDENTIFIER, DOT, IDENTIFIER, COMMA, IDENTIFIER, DOT, IDENTIFIER, EOF
    assert tokens[1].type == TokenType.SYMBOL_DOT
    assert tokens[3].type == TokenType.SYMBOL_COMMA