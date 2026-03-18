import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser

@pytest.mark.parametrize("sql, is_star, col_count, table_name", [
    # SELECT 結構變體
    ("SELECT * FROM Users", True, 0, "USERS"),
    ("SELECT UserID, UserName FROM Orders", False, 2, "ORDERS"),
    # 極端空白魯棒性
    (" \n\n\t  SELECT \r\n * \t\t FROM \n Users \n\n  ", True, 0, "USERS"),
    ("SELECT*FROM[Users]", True, 0, "USERS"),
])
def test_parser_select_structures(sql, is_star, col_count, table_name):
    """測試各種 SELECT 結構與排版的正確性"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    assert ast.is_select_star is is_star
    assert len(ast.columns) == col_count
    assert ast.table.name.upper() == table_name

@pytest.mark.parametrize("sql, expected_name", [
    # MSSQL 中括號支援
    ("SELECT [First Name] FROM Users", "First Name"),
    ("SELECT [UserID] FROM Users", "UserID"),
    # 關鍵字作為標識符 (Escaped)
    ("SELECT [SELECT] FROM Users", "SELECT"),
    ("SELECT [FROM] FROM Users", "FROM"),
])
def test_parser_mssql_identifiers(sql, expected_name):
    """測試 MSSQL 特有的中括號與關鍵字逃逸解析"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    assert ast.columns[0].name == expected_name

@pytest.mark.parametrize("sql, error_match", [
    # 嚴格語法攔截
    ("SELECT UserID, , UserName FROM Users", "Expected identifier"),
    ("SELECT UserID, FROM Users", "Expected identifier"),
    ("SELECT UserID Users", "Expected FROM"),
    ("SELECT * FROM Users ; DROP TABLE Users--", "Unexpected token: ;"),
])
def test_parser_strict_syntax_errors(sql, error_match):
    """驗證 Parser 對非法語法或 SQL 注入垃圾的精準攔截"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    with pytest.raises(SyntaxError, match=error_match):
        parser.parse()

@pytest.mark.parametrize("as_keyword", ["as", "As", "aS", "AS"])
def test_alias_mixed_casing(as_keyword):
    """測試 AS 關鍵字的大小寫不敏感性"""
    sql = f"SELECT UserID FROM Users {as_keyword} u"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    assert ast.table_alias == "u"