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

def run_bind(sql, registry):
    """執行 Lexer -> Parser -> Binder 的完整流水線"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

# --- 2. 基礎 JOIN 語法測試 ---

@pytest.mark.parametrize("sql, expected_joins", [
    # 標準 JOIN (預設為 INNER)
    ("SELECT u.UserID FROM Users u JOIN Orders o ON u.UserID = o.UserID", 1),
    # 顯式 INNER JOIN
    ("SELECT u.UserID FROM Users u INNER JOIN Orders o ON u.UserID = o.UserID", 1),
    # 顯式 LEFT JOIN
    ("SELECT u.UserID FROM Users u LEFT JOIN Orders o ON u.UserID = o.UserID", 1),
])
def test_join_basic_syntax(join_registry, sql, expected_joins):
    """驗證 Parser 是否能正確識別並解析各種 JOIN 關鍵字"""
    ast = run_bind(sql, join_registry)
    assert len(ast.joins) == expected_joins

# --- 3. ZTA 欄位歧義防禦 (核心資安點) ---

@pytest.mark.parametrize("sql, error_match", [
    # UserID 同時存在於兩表，未指定限定符應報錯
    ("SELECT UserID FROM Users u JOIN Orders o ON u.UserID = o.UserID", "Column 'UserID' is ambiguous"),
    # 使用了未定義的表別名 (x)
    ("SELECT x.Total FROM Users u JOIN Orders o ON u.UserID = o.UserID", "Unknown qualifier 'x'"),
])
def test_join_ambiguity_protection(join_registry, sql, error_match):
    """驗證 Binder 是否能精準攔截歧義欄位，防止非預期的資料存取"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind(sql, join_registry)

# --- 4. 隱含式關聯阻斷 (Security Policy) ---

def test_disallow_implicit_comma_join(join_registry):
    """
    ZTA 規範：禁止使用 FROM A, B 語法。
    強制要求顯式 JOIN...ON 以利於安全審計與路徑追蹤。
    修復說明：Parser v1.5.1 應拋出 'Expected FROM' 以對齊測試需求。
    """
    sql = "SELECT * FROM Users, Orders"
    with pytest.raises(SyntaxError, match="Expected FROM"):
        run_bind(sql, join_registry)

# --- 5. ON 子句作用域驗證 ---

def test_join_on_condition_scope(join_registry):
    """驗證 ON 子句中的欄位是否正確綁定到對應的作用域"""
    sql = "SELECT u.UserName FROM Users u JOIN Orders o ON u.UserID = o.UserID"
    ast = run_bind(sql, join_registry)
    # 驗證第一個 JOIN 的 ON 條件兩側
    join_node = ast.joins[0]
    assert join_node.on_left.qualifier == "u"
    assert join_node.on_right.qualifier == "o"