import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError


def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]


# --- (from test_semantic_zta_suite.py) ---

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
        lexer = Lexer(sql)
        parser = Parser(lexer.tokenize(), sql)
        ast = parser.parse()
        binder = Binder(registry)
        binder.bind(ast)


# --- (from test_type_checking_suite.py) ---

# --- 1. 函數參數型別檢查 ---

def test_function_parameter_type_mismatch(global_runner):
    """驗證函數參數型別不匹配時的報警"""
    sql = "SELECT UPPER(ProductID) FROM Product"
    with pytest.raises(SemanticError, match="Function 'UPPER' expects NVARCHAR"):
        run_bind_with_runner(sql, global_runner)

# --- 2. 運算子型別安全 ---

def test_binary_op_type_mismatch(global_runner):
    """驗證運算子兩側型別家族不相容時的攔截"""
    sql = "SELECT Name + 100 FROM Product"
    with pytest.raises(SemanticError, match=r"Operator '\+' cannot be applied to"):
        run_bind_with_runner(sql, global_runner)

# --- 3. CASE 分支型別一致性 ---

def test_case_result_consistency(global_runner):
    """🛡️ ZTA 政策：驗證 CASE 所有分支結果型別家族是否相容"""
    sql = "SELECT CASE WHEN ProductID = 1 THEN 'Admin' ELSE 999 END FROM Product"
    with pytest.raises(SemanticError, match="CASE branches have incompatible types"):
        run_bind_with_runner(sql, global_runner)

def test_arithmetic_on_strings_blocked(global_runner):
    """驗證字串類型禁止進行算術除法"""
    sql = "SELECT Name / 2 FROM Product"
    with pytest.raises(SemanticError, match="Operator '/' cannot be applied"):
        run_bind_with_runner(sql, global_runner)


# --- (from test_scope_stack_suite.py) ---

@pytest.fixture
def scope_reg():
    reg = MetadataRegistry()
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,ID,INT\n"
        "Users,UserID,INT\n"
        "Users,UserName,NVARCHAR\n"
        "Orders,OrderID,INT\n"
        "Orders,UserID,INT\n"
        "A,ID,INT\n"
        "B,ID,INT\n"
    )
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind(sql, registry):
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

# --- 2. 子查詢語法解析測試 (Parsing) ---

def test_subquery_in_where_parsing():
    """驗證 Parser 是否支援 WHERE 子句中的嵌套 SELECT"""
    sql = "SELECT UserName FROM Users WHERE UserID IN (SELECT UserID FROM Orders)"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    assert ast.where_condition.right.__class__.__name__ == "SelectStatement"

# --- 3. 作用域隔離與遞迴搜尋 (Semantic) ---

def test_subquery_scope_isolation(scope_reg):
    """
    🛡️ ZTA 政策：子查詢內部的別名不應洩漏到外部。
    """
    sql = "SELECT * FROM Users u WHERE UserID IN (SELECT UserID FROM Orders o) AND o.OrderID > 0"
    with pytest.raises(SemanticError, match="Unknown qualifier 'o'"):
        run_bind(sql, scope_reg)

def test_correlated_subquery_binding(scope_reg):
    """
    🛡️ ZTA 核心：驗證「相關子查詢」的遞迴作用域。
    內層查詢必須能看見外層的別名 'u'。
    """
    sql = """
        SELECT UserName FROM Users u
        WHERE EXISTS (
            SELECT 1 FROM Orders o WHERE o.UserID = u.UserID
        )
    """
    ast = run_bind(sql, scope_reg)
    inner_select = ast.where_condition.args[0]
    inner_where = inner_select.where_condition
    assert inner_where.right.qualifier == "u"

# --- 4. 深度嵌套挑戰 ---

def test_triple_nested_scopes(scope_reg):
    """驗證三層作用域的穩定性"""
    sql = "SELECT * FROM Users WHERE ID IN (SELECT ID FROM A WHERE ID IN (SELECT ID FROM B))"
    try:
        run_bind(sql, scope_reg)
    except SemanticError as e:
        if "Table 'A' not found" in str(e): pass
        else: raise
