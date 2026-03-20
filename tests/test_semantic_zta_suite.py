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

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. ZTA 核心語意強制執行測試 (Real Metadata) ---

@pytest.mark.parametrize("sql, is_valid, error_match", [
    # 成功案例：正確使用別名 (Person 表)
    ("SELECT p.FirstName FROM Person AS p", True, None),
    # 失敗案例：別名定義後禁止使用原表名 (ZTA 核心政策)
    ("SELECT Person.FirstName FROM Person AS p", False, "Original table name 'Person' cannot be used when alias 'p' is defined"),
    # 失敗案例：引用不存在的表格
    ("SELECT * FROM GhostTable", False, "Table 'GhostTable' not found"),
])
def test_zta_semantic_enforcement_real_meta(global_runner, sql, is_valid, error_match):
    """驗證 ZTA 核心原則：縮小攻擊面與嚴格路徑檢查。"""
    if is_valid:
        run_bind_with_runner(sql, global_runner)
    else:
        with pytest.raises(SemanticError, match=error_match):
            run_bind_with_runner(sql, global_runner)

# --- 3. 星號展開邏輯測試 (Star Expansion with Real Meta) ---

@pytest.mark.parametrize("sql, expected_count", [
    # Address 表在 output.csv 中有 9 個欄位
    ("SELECT * FROM Address", 9),
    # 限定星號展開
    ("SELECT a.* FROM Address a", 9),
])
def test_star_expansion_logic_real_meta(global_runner, sql, expected_count):
    """驗證 SELECT * 根據真實元數據自動展開的正確性。"""
    ast = run_bind_with_runner(sql, global_runner)
    assert len(ast.columns) == expected_count

# --- 💡 TDD New: 星號展開與別名衝突防禦 ---

def test_zta_star_alias_conflict_real_meta(global_runner):
    """🛡️ ZTA 政策：星號展開限定符也必須遵守別名失效原則"""
    # 定義別名 'a' 後，禁止使用 'Address.*'
    sql = "SELECT Address.* FROM Address a"
    with pytest.raises(SemanticError, match="Unknown qualifier 'Address' in star expansion"):
        run_bind_with_runner(sql, global_runner)

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
    # 使用本地的 registry mock (為了測試 dbo.Users 等虛擬結構)
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    bound_ast = binder.bind(ast)

    assert bound_ast.columns[0].name == expected_col
    assert bound_ast.columns[0].qualifier == expected_qualifier
    if table_alias:
        assert bound_ast.table_alias == table_alias
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
        # 使用本地 mock 流程
        lexer = Lexer(sql)
        parser = Parser(lexer.tokenize(), sql)
        ast = parser.parse()
        binder = Binder(registry)
        binder.bind(ast)