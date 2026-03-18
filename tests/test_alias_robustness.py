import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser

def test_alias_with_extreme_whitespace():
    """測試：點號與別名周圍的極端空白"""
    sql = "SELECT u  .  UserID   FROM   Users   aS   u"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    assert ast.table_alias == "u"
    assert ast.columns[0].name == "UserID"
    assert ast.columns[0].qualifiers == ["u"]

def test_alias_mixed_casing():
    """測試：AS 關鍵字的大小寫混合"""
    # 測試 as, As, aS, AS
    for as_keyword in ["as", "As", "aS", "AS"]:
        sql = f"SELECT UserID FROM Users {as_keyword} u"
        lexer = Lexer(sql)
        parser = Parser(lexer.tokenize(), sql)
        ast = parser.parse()
        assert ast.table_alias == "u"