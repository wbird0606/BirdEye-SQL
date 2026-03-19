import pytest
from birdeye.lexer import Lexer
from birdeye.parser import Parser

# --- 1. 語句路由測試 (Statement Routing) ---

@pytest.mark.parametrize("sql, expected_node", [
    ("SELECT * FROM Users", "SelectStatement"),
    ("UPDATE Users SET Name = 'A' WHERE ID = 1", "UpdateStatement"),
    ("DELETE FROM Users WHERE ID = 1", "DeleteStatement"),
    ("INSERT INTO Users (ID) VALUES (1)", "InsertStatement"),
    ("BULK INSERT INTO Logs", "SqlBulkCopyStatement"),
])
def test_parser_statement_routing(sql, expected_node):
    """驗證 Parser 是否能根據起始 Token 正確路由至不同語句解析邏輯。"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    assert ast.__class__.__name__ == expected_node

# --- 2. 基礎 SELECT 結構與魯棒性測試 ---

@pytest.mark.parametrize("sql, is_star, col_count, table_name", [
    # 標準結構
    ("SELECT UserID, UserName FROM Orders", False, 2, "ORDERS"),
    # 星號與中括號
    ("SELECT*FROM[Users]", True, 0, "USERS"),
    # 極端空白與換行處理
    (" \n\n\t  SELECT \r\n * \t\t FROM \n Users \n\n  ", True, 0, "USERS"),
])
def test_parser_select_structures(sql, is_star, col_count, table_name):
    """測試各種 SELECT 變體與不規則排版的解析正確性。"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    assert ast.is_select_star is is_star
    assert len(ast.columns) == col_count
    assert ast.table.name.upper() == table_name

# --- 3. ZTA 核心防禦與嚴格語法攔截 ---

@pytest.mark.parametrize("sql, error_match", [
    # 零信任強制政策：變更操作必須帶 WHERE
    ("UPDATE Users SET Name = 'X'", "WHERE clause is mandatory"),
    ("DELETE FROM Users", "WHERE clause is mandatory"),
    # 零信任強制政策：禁止隱含式關聯 (Issue #23)
    ("SELECT * FROM Users, Orders", "Expected FROM"),
    # 語法正確性與 SQL 注入垃圾攔截
    ("SELECT UserID, , UserName FROM Users", "Expected identifier"),
    ("SELECT UserID Users", "Expected FROM"),
    ("SELECT * FROM Users ; DROP TABLE Users--", "Unexpected token: ;"),
])
def test_parser_zta_strict_errors(sql, error_match):
    """驗證 Parser 對非法語法、隱含關聯及高風險指令的精準攔截。"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    with pytest.raises(SyntaxError, match=error_match):
        parser.parse()

# --- 4. 標識符與別名處理測試 ---

@pytest.mark.parametrize("sql, expected_name", [
    # MSSQL 特有的中括號支援
    ("SELECT [First Name] FROM Users", "First Name"),
    # 關鍵字逃逸測試
    ("SELECT [SELECT] FROM Users", "SELECT"),
])
def test_parser_mssql_identifiers(sql, expected_name):
    """測試 MSSQL 標識符與關鍵字逃逸解析。"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    assert ast.columns[0].name == expected_name

@pytest.mark.parametrize("as_keyword", ["as", "As", "aS", "AS"])
def test_alias_mixed_casing(as_keyword):
    """測試 AS 關鍵字的大小寫不敏感性。"""
    sql = f"SELECT UserID FROM Users {as_keyword} u"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    assert ast.table_alias == "u"