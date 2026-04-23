import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.reconstructor import ASTReconstructor


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
    # 成功案例：正確使用別名 (Customer 表)
    ("SELECT c.FirstName FROM Customer AS c", True, None),
    # 失敗案例：別名定義後禁止使用原表名 (ZTA 核心政策)
    ("SELECT Customer.FirstName FROM Customer AS c", False, "Original table name 'Customer' cannot be used when alias 'c' is defined"),
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

def test_external_param_type_inference(global_runner):
    """外部傳入的 params 應參與語意推導，讓 @param 不再停在 UNKNOWN。"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE AddressID = @customerId",
        params={"customerId": 123},
    )
    assert result["status"] == "success"
    assert result["ast"].where_condition.right.inferred_type == "INT"
    assert "BOUND PARAMS" in result["tree"]
    assert "@CUSTOMERID: INT" in result["tree"]


def test_structural_param_resolution_success(global_runner):
    """結構參數有安全值時，應解析為實際識別符並通過綁定。"""
    result = global_runner.run(
        "SELECT TOP 5 ProductID FROM @tableName ORDER BY @sortCol",
        params={"tableName": "Product", "sortCol": "ProductID"},
    )
    assert result["status"] == "success"
    assert result["ast"].table.name == "Product"
    assert result["ast"].order_by_terms[0].column.name == "ProductID"


def test_structural_param_resolution_blocks_unsafe_identifier(global_runner):
    """結構參數若解析為可疑識別符（含注入片段）應拒絕。"""
    with pytest.raises(SemanticError, match="requires a runtime parameter value"):
        run_bind_with_runner(
            "SELECT TOP 5 ProductID FROM Product ORDER BY @sortCol",
            global_runner,
        )

    with pytest.raises(SemanticError, match="unsafe identifier"):
        global_runner.run(
            "SELECT TOP 5 ProductID FROM Product ORDER BY @sortCol",
            params={"sortCol": "ProductID; DROP TABLE Users;--"},
        )


def test_structural_param_resolution_blocks_missing_runtime_value(global_runner):
    """結構參數未提供 runtime 值時，應 fail-closed。"""
    with pytest.raises(SemanticError, match="requires a runtime parameter value"):
        global_runner.run("SELECT TOP 1 * FROM @tableName")


def test_structural_param_resolution_blocks_unknown_table(global_runner):
    """FROM 結構參數解析後若資料表不存在，應由語意層拒絕。"""
    with pytest.raises(SemanticError, match="Table 'GhostTable' not found"):
        global_runner.run(
            "SELECT TOP 1 * FROM @tableName",
            params={"tableName": "GhostTable"},
        )


def test_structural_param_changes_ast_and_json(global_runner):
    """同一 SQL 在不同結構參數下，AST/JSON 應反映不同語意。"""
    sql = "SELECT ProductID, Name, ListPrice FROM Product ORDER BY @sortCol"

    by_id = global_runner.run(sql, params={"sortCol": "ProductID"})
    by_name = global_runner.run(sql, params={"sortCol": "Name"})

    assert by_id["status"] == "success"
    assert by_name["status"] == "success"
    assert by_id["ast"].order_by_terms[0].column.name == "ProductID"
    assert by_name["ast"].order_by_terms[0].column.name == "Name"
    assert by_id["json"] != by_name["json"]


def test_qmark_params_success(global_runner):
    """支援 ? + list 位置參數，並正確映射型別與值。"""
    result = global_runner.run(
        "SELECT ProductID FROM Product WHERE ProductID = ? AND Name = ?",
        params=[1, "Adjustable Race"],
    )
    assert result["status"] == "success"
    assert "?: INT" in result["tree"]
    assert "?: NVARCHAR" in result["tree"]
    assert "?: 1" in result["tree"]

    reconstructed = ASTReconstructor().from_json_str(result["json"])
    assert "ProductID = ?" in reconstructed
    assert "Name = ?" in reconstructed


def test_qmark_params_count_mismatch_raises(global_runner):
    """? 數量與 params 長度不一致時應 fail-closed。"""
    with pytest.raises(ValueError, match="PARAM_COUNT_MISMATCH"):
        global_runner.run(
            "SELECT ProductID FROM Product WHERE ProductID = ? AND Name = ?",
            params=[1],
        )


def test_qmark_params_mixed_mode_blocked(global_runner):
    """SQL 使用 ? 但 params 傳 object 時應拒絕。"""
    with pytest.raises(ValueError, match="PARAM_MODE_MIXED"):
        global_runner.run(
            "SELECT ProductID FROM Product WHERE ProductID = ?",
            params={"productId": 1},
        )


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
