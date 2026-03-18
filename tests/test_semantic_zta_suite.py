import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

@pytest.fixture
def registry():
    """統一的 Mock Registry"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Orders,OrderID,INT\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind(sql, registry):
    """一條龍執行：Lexer -> Parser -> Binder"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

@pytest.mark.parametrize("sql, is_valid, error_match", [
    # ZTA 別名作用域強制性
    ("SELECT u.UserID FROM Users AS u", True, None),
    ("SELECT Users.UserID FROM Users AS u", False, "Original table name 'Users' cannot be used when alias 'u' is defined"),
    # 元數據精準攔截
    ("SELECT UserID FROM GhostTable", False, "Table 'GhostTable' not found"),
    ("SELECT Password FROM Users", False, "Column 'Password' not found in 'Users'"),
    ("SELECT Ghost.UserID FROM Users AS u", False, "Unknown qualifier 'Ghost'"),
])
def test_zta_semantic_enforcement(registry, sql, is_valid, error_match):
    """驗證 ZTA 核心原則：縮小攻擊面與嚴格路徑檢查"""
    if is_valid:
        run_bind(sql, registry)
    else:
        with pytest.raises(SemanticError, match=error_match):
            run_bind(sql, registry)

@pytest.mark.parametrize("sql, expected_count", [
    # 星號展開邏輯
    ("SELECT * FROM Users", 2),
    ("SELECT Users.* FROM Users", 2),
])
def test_star_expansion_logic(registry, sql, expected_count):
    """驗證 SELECT * 根據元數據自動展開的正確性"""
    ast = run_bind(sql, registry)
    assert len(ast.columns) == expected_count

@pytest.mark.parametrize("sql, expected_col, expected_qualifier, table_alias", [
    # 多層級路徑與別名魯棒性
    ("SELECT dbo.Users.UserID FROM Users", "UserID", "dbo.Users", None),
    ("SELECT u . UserID FROM Users AS u", "UserID", "u", "u"),
    ("SELECT [Database].[dbo].[Users].[UserID] FROM [Users]", "UserID", "Database.dbo.Users", None),
])
def test_complex_identifiers_and_aliases(registry, sql, expected_col, expected_qualifier, table_alias):
    """測試多層級限定符與帶空白別名的整合綁定"""
    ast = run_bind(sql, registry)
    assert ast.columns[0].name == expected_col
    assert ast.columns[0].qualifier == expected_qualifier
    if table_alias:
        assert ast.table_alias == table_alias

# 在 test_semantic_zta_suite.py 末尾補上
@pytest.mark.parametrize("table, column, expected_exists", [
    ("users", "userid", True),
    ("USERS", "USERNAME", True),
    ("Orders", "OrderID", True),
    ("users", "password", False),     # 欄位不存在
    ("InvalidTable", "userid", False), # 表不存在
])
def test_registry_lookups(registry, table, column, expected_exists):
    """確保元數據查找不受大小寫影響且邏輯精準"""
    assert registry.has_column(table, column) is expected_exists