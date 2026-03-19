import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

@pytest.fixture
def multi_reg():
    """建立包含 Users, Orders, Products 的複雜元數據"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Orders,OrderID,INT\n"
        "Orders,UserID,INT\n"
        "Orders,ProductID,INT\n"
        "Products,ProductID,INT\n"
        "Products,ProductName,VARCHAR\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind(sql, registry):
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

# --- 測試 A：三表作用域可見性 ---
def test_three_table_join_visibility(multi_reg):
    """驗證 C 表的 ON 條件可以看見 A 與 B 表的欄位"""
    sql = """
        SELECT u.UserName, p.ProductName 
        FROM Users u 
        JOIN Orders o ON u.UserID = o.UserID 
        JOIN Products p ON o.ProductID = p.ProductID
    """
    ast = run_bind(sql, multi_reg)
    assert len(ast.joins) == 2
    # 檢查最後一個 JOIN (Products) 的 ON 條件
    last_on = ast.joins[1]
    assert last_on.on_left.qualifier == "o"
    assert last_on.on_right.qualifier == "p"

# --- 測試 B：多表歧義攔截 ---
def test_multi_table_ambiguity(multi_reg):
    """驗證 ProductID 同時存在於 Orders 與 Products，未指定 Prefix 應報錯"""
    sql = """
        SELECT ProductID 
        FROM Users u 
        JOIN Orders o ON u.UserID = o.UserID 
        JOIN Products p ON o.ProductID = p.ProductID
    """
    with pytest.raises(SemanticError, match="Column 'ProductID' is ambiguous. Found in: ORDERS, PRODUCTS"):
        run_bind(sql, multi_reg)

# --- 測試 C：別名失效連鎖反應 (ZTA 核心) ---
def test_alias_invalidation_chain(multi_reg):
    """
    若 Users 已給別名 u，在後續任何地方（含第二個 JOIN 的 ON）
    使用 Users.UserID 都應被視為非法操作。
    """
    sql = """
        SELECT u.UserName 
        FROM Users u 
        JOIN Orders o ON u.UserID = o.UserID 
        JOIN Products p ON Users.UserID = p.ProductID
    """
    with pytest.raises(SemanticError, match="Original table name 'Users' cannot be used when alias 'u' is defined"):
        run_bind(sql, multi_reg)

def test_disallow_forward_reference(multi_reg):
    """
    ZTA 嚴格模式：第一個 JOIN 不准引用後面才出現的 Products 表 (p)
    """
    sql = """
        SELECT u.UserName 
        FROM Users u 
        JOIN Orders o ON u.UserID = p.ProductID  -- 這裡 p 還沒出現！
        JOIN Products p ON o.ProductID = p.ProductID
    """
    # 預期：應該噴出 Unknown qualifier 'p'
    with pytest.raises(SemanticError, match="Unknown qualifier 'p'"):
        run_bind(sql, multi_reg)