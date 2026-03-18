import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

@pytest.fixture
def registry():
    csv_data = "table_name,column_name,data_type\nUsers,UserID,INT\nUsers,UserName,VARCHAR\n"
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind(sql, registry):
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

def test_binder_enforce_alias_scope(registry):
    """
    Issue #19 測試：當定義了別名 u 時，禁止使用原名 Users 限定欄位。
    """
    # 這是錯誤的語法：SELECT Users.UserID FROM Users AS u
    sql = "SELECT Users.UserID FROM Users AS u"
    
    # 預期拋出 SemanticError，提示應使用別名而非原名
    with pytest.raises(SemanticError, match="Original table name 'Users' cannot be used when alias 'u' is defined"):
        run_bind(sql, registry)

def test_binder_valid_alias_usage(registry):
    """驗證正常的別名使用仍可通過"""
    sql = "SELECT u.UserID FROM Users AS u"
    ast = run_bind(sql, registry)
    assert ast.table.name.upper() == "USERS"
    assert ast.columns[0].qualifier == "u"