import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

@pytest.fixture
def join_registry():
    """專為 JOIN 設計的元數據，包含具備重複欄位名的表格"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Orders,OrderID,INT\n"
        "Orders,UserID,INT\n"  # 與 Users 表重複的欄位
        "Orders,Total,DECIMAL\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind(sql, registry):
    """一條龍執行流水線"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

# --- A. 基礎語法測試 ---

@pytest.mark.parametrize("sql, expected_joins", [
    ("SELECT u.UserID FROM Users u JOIN Orders o ON u.UserID = o.UserID", 1),
    ("SELECT u.UserID FROM Users u INNER JOIN Orders o ON u.UserID = o.UserID", 1),
    ("SELECT u.UserID FROM Users u LEFT JOIN Orders o ON u.UserID = o.UserID", 1),
])
def test_join_basic_syntax(join_registry, sql, expected_joins):
    """驗證基礎 JOIN 語法解析與 Token 消費"""
    # 這裡目前會失敗，因為 Parser 尚未實作 JOIN 邏輯
    ast = run_bind(sql, join_registry)
    assert len(ast.joins) == expected_joins

# --- B. ZTA 欄位歧義防禦 (核心資安點) ---

@pytest.mark.parametrize("sql, error_match", [
    # UserID 同時存在於 Users 與 Orders，未指定 Prefix 應報錯
    ("SELECT UserID FROM Users u JOIN Orders o ON u.UserID = o.UserID", "Column 'UserID' is ambiguous"),
    # 即使只有一個表有該欄位，若使用了未定義的別名也應攔截
    ("SELECT x.Total FROM Users u JOIN Orders o ON u.UserID = o.UserID", "Unknown qualifier 'x'"),
])
def test_join_ambiguity_protection(join_registry, sql, error_match):
    """驗證多表環境下，Binder 是否能精準攔截歧義欄位"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind(sql, join_registry)

# --- C. 隱含式關聯阻斷 (Security Policy) ---

def test_disallow_implicit_comma_join(join_registry):
    """
    ZTA 規範：禁止使用 FROM A, B 語法。
    強制要求顯式 JOIN...ON 以利於安全審計與路徑追蹤。
    """
    sql = "SELECT * FROM Users, Orders"
    with pytest.raises(SyntaxError, match="Expected FROM"): # 或自定義錯誤
        run_bind(sql, join_registry)

# --- D. ON 子句作用域驗證 ---

def test_join_on_condition_scope(join_registry):
    """驗證 ON 子句中的欄位是否正確綁定到對應表"""
    sql = "SELECT u.UserName FROM Users u JOIN Orders o ON u.UserID = o.UserID"
    ast = run_bind(sql, join_registry)
    # 驗證 ON 條件中的兩側欄位是否都已綁定成功
    on_cond = ast.joins[0].on_condition
    assert on_cond.left.qualifier == "u"
    assert on_cond.right.qualifier == "o"