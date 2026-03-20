import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def join_registry():
    """
    專為 JOIN 設計的元數據。
    包含 Users 與 Orders 表，且 UserID 欄位在兩表中均存在，用以測試歧義攔截。
    """
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Orders,OrderID,INT\n"
        "Orders,UserID,INT\n"
        "Orders,Total,DECIMAL\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. 基礎 JOIN 語法測試 (Real Metadata) ---

@pytest.mark.parametrize("sql, expected_joins", [
    # 標準 JOIN (SalesOrderHeader h, SalesOrderDetail d)
    ("SELECT h.SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID", 1),
    # 顯式 LEFT JOIN (Address a, StateProvince s)
    ("SELECT a.AddressID FROM Address a LEFT JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID", 1),
])
def test_join_basic_syntax(global_runner, sql, expected_joins):
    """驗證 Parser 是否能正確識別並解析真實元數據下的 JOIN"""
    ast = run_bind_with_runner(sql, global_runner)
    assert len(ast.joins) == expected_joins

# --- 3. ZTA 欄位歧義防禦 (核心資安點) ---

@pytest.mark.parametrize("sql, error_match", [
    # SalesOrderID 同時存在於 Header 與 Detail，未指定限定符應報錯
    ("SELECT SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID", "Column 'SalesOrderID' is ambiguous"),
    # ModifiedDate 同時存在於 Address 與 StateProvince
    ("SELECT ModifiedDate FROM Address a JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID", "Column 'ModifiedDate' is ambiguous"),
])
def test_join_ambiguity_protection(global_runner, sql, error_match):
    """驗證 Binder 是否能精準攔截真實元數據中的歧義欄位"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind_with_runner(sql, global_runner)

# --- 4. ZTA 別名強制失效測試 (Alias Shadowing Defense) ---

def test_join_alias_invalidation_real_meta(global_runner):
    """🛡️ ZTA 政策：定義別名後，原有名稱在 JOIN 作用域中必須失效"""
    # 定義別名 'h' 後，禁止使用 'SalesOrderHeader'
    sql = "SELECT SalesOrderHeader.SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID"
    with pytest.raises(SemanticError, match="Original table name 'SalesOrderHeader' cannot be used when alias 'h' is defined"):
        run_bind_with_runner(sql, global_runner)

# --- 4. 隱含式關聯阻斷 (Security Policy) ---

def test_disallow_implicit_comma_join(global_runner):
    """
    ZTA 規範：禁止使用 FROM A, B 語法。
    強制要求顯式 JOIN...ON 以利於安全審計與路徑追蹤。
    """
    # 解析階段 (Parser) 就應阻斷，不論元數據為何
    sql = "SELECT * FROM SalesOrderHeader, SalesOrderDetail"
    with pytest.raises(SyntaxError, match="Expected FROM"):
        run_bind_with_runner(sql, global_runner)

# --- 5. ON 子句作用域驗證 ---

def test_join_on_condition_scope(global_runner):
    """驗證 ON 子句中的欄位是否正確綁定到對應的作用域"""
    sql = "SELECT h.SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID"
    ast = run_bind_with_runner(sql, global_runner)

    # 驗證第一個 JOIN 的 ON 條件兩側
    join_node = ast.joins[0]
    # h.SalesOrderID 應綁定到 h，d.SalesOrderID 應綁定到 d
    assert join_node.on_left.qualifier == "h"
    assert join_node.on_right.qualifier == "d"