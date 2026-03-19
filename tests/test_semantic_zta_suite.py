import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def registry():
    """
    統一的 Mock Registry，定義了 Users 與 Orders 表。
    用於驗證 Binder 是否能正確比對元數據。
    """
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Orders,OrderID,INT\n"
        "Orders,UserID,INT\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind(sql, registry):
    """
    執行完整的語意綁定流水線：Lexer -> Parser -> Binder。
    """
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

# --- 2. ZTA 核心語意強制執行測試 ---

@pytest.mark.parametrize("sql, is_valid, error_match", [
    # 成功案例：正確使用別名
    ("SELECT u.UserID FROM Users AS u", True, None),
    # 失敗案例：別名定義後禁止使用原表名 (ZTA 核心政策)
    ("SELECT Users.UserID FROM Users AS u", False, "Original table name 'Users' cannot be used when alias 'u' is defined"),
    # 失敗案例：引用不存在的表格
    ("SELECT UserID FROM GhostTable", False, "Table 'GhostTable' not found"),
    # 失敗案例：引用不存在的欄位
    ("SELECT Password FROM Users", False, "Column 'Password' not found in 'Users'"),
    # 失敗案例：使用未定義的限定符
    ("SELECT Ghost.UserID FROM Users AS u", False, "Unknown qualifier 'Ghost'"),
])
def test_zta_semantic_enforcement(registry, sql, is_valid, error_match):
    """驗證 ZTA 核心原則：縮小攻擊面與嚴格路徑檢查。"""
    if is_valid:
        run_bind(sql, registry)
    else:
        with pytest.raises(SemanticError, match=error_match):
            run_bind(sql, registry)

# --- 3. 星號展開邏輯測試 (Star Expansion) ---

@pytest.mark.parametrize("sql, expected_count", [
    # 全域星號展開
    ("SELECT * FROM Users", 2),
    # 限定星號展開 (修復後的關鍵功能)
    ("SELECT Users.* FROM Users", 2),
    # 帶有別名的星號展開
    ("SELECT u.* FROM Users u", 2),
])
def test_star_expansion_logic(registry, sql, expected_count):
    """驗證 SELECT * 根據元數據自動展開的正確性與魯棒性。"""
    ast = run_bind(sql, registry)
    assert len(ast.columns) == expected_count

# --- 4. 複雜路徑與別名識別測試 ---

@pytest.mark.parametrize("sql, expected_col, expected_qualifier, table_alias", [
    # 多層級限定符 (模擬 Schema.Table.Column)
    ("SELECT dbo.Users.UserID FROM Users", "UserID", "dbo.Users", None),
    # 中括號與多層級路徑整合
    ("SELECT [Database].[dbo].[Users].[UserID] FROM [Users]", "UserID", "Database.dbo.Users", None),
    # 帶空白與特殊格式的別名
    ("SELECT u . UserID FROM Users AS u", "UserID", "u", "u"),
])
def test_complex_identifiers_and_aliases(registry, sql, expected_col, expected_qualifier, table_alias):
    """測試多層級限定符與帶標識符逃逸的整合綁定邏輯。"""
    ast = run_bind(sql, registry)
    assert ast.columns[0].name == expected_col
    assert ast.columns[0].qualifier == expected_qualifier
    if table_alias:
        assert ast.table_alias == table_alias

# --- 5. 元數據查找魯棒性測試 ---

@pytest.mark.parametrize("table, column, expected_exists", [
    ("users", "userid", True),     # 測試大小寫不敏感
    ("USERS", "USERNAME", True),
    ("Orders", "OrderID", True),
    ("users", "password", False),  # 測試不存在的欄位
    ("InvalidTable", "userid", False), # 測試不存在的表
])
def test_registry_lookups(registry, table, column, expected_exists):
    """確保 MetadataRegistry 的查找邏輯精準且不受大小寫影響。"""
    assert registry.has_column(table, column) is expected_exists

def test_zta_alias_invalidation_deep(registry):
    """
    深度驗證 ZTA 作用域隔離：確保定義別名後，原有名稱在所有作用域中均失效。
    """
    sql = "SELECT Users.UserID FROM Users u"
    with pytest.raises(SemanticError, match="Original table name 'Users' cannot be used"):
        run_bind(sql, registry)