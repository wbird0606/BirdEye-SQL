import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder

# --- 1. 測試環境設置 ---

@pytest.fixture
def nullable_reg():
    """建立測試空值語意的元數據"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Orders,OrderID,INT\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind_with_binder(sql, registry):
    """執行解析並回傳 Binder 實例以檢查內部狀態"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    ast = parser.parse()
    binder = Binder(registry)
    binder.bind(ast)
    return binder

# --- 2. Nullability 語意測試 ---

def test_left_join_nullability_semantic(nullable_reg):
    """
    驗證 LEFT JOIN 時，右表應該被標記為 Nullable 作用域。
    在 Users LEFT JOIN Orders 中，Orders 的欄位可能為空。
    """
    sql = "SELECT u.UserID, o.OrderID FROM Users u LEFT JOIN Orders o ON u.UserID = o.OrderID"
    binder = run_bind_with_binder(sql, nullable_reg)
    
    # 預期右表別名 'O' 被加入空值覺知名單
    assert "O" in binder.nullable_scopes
    # 主表 'U' 不應該在名單中
    assert "U" not in binder.nullable_scopes

def test_right_join_nullability_semantic(nullable_reg):
    """
    驗證 RIGHT JOIN 時，左表（主表）應該變為 Nullable。
    在 Users RIGHT JOIN Orders 中，Users 的欄位可能為空。
    """
    sql = "SELECT u.UserID, o.OrderID FROM Users u RIGHT JOIN Orders o ON u.UserID = o.OrderID"
    binder = run_bind_with_binder(sql, nullable_reg)
    
    # 預期左表別名 'U' 變為 Nullable
    assert "U" in binder.nullable_scopes
    # 右表 'O' 則是保證存在的
    assert "O" not in binder.nullable_scopes

def test_inner_join_no_nullability(nullable_reg):
    """
    驗證標準 INNER JOIN 不應產生 Nullable 標記。
    """
    sql = "SELECT u.UserID, o.OrderID FROM Users u JOIN Orders o ON u.UserID = o.OrderID"
    binder = run_bind_with_binder(sql, nullable_reg)
    
    # 內連接不應有任何表被標記為 Nullable
    assert len(binder.nullable_scopes) == 0

def test_multi_join_nullability_propagation(nullable_reg):
    """
    驗證多重 JOIN 下的空值傳遞。
    """
    # 這裡擴充一下元數據以支援三表
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Orders,OrderID,INT\n"
        "Profiles,ProfileID,INT\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    
    sql = """
        SELECT u.UserID, o.OrderID, p.ProfileID 
        FROM Users u 
        LEFT JOIN Orders o ON u.UserID = o.OrderID
        JOIN Profiles p ON u.UserID = p.ProfileID
    """
    binder = run_bind_with_binder(sql, reg)
    
    # 只有 'O' 是透過 LEFT JOIN 加入的，應為 Nullable
    assert "O" in binder.nullable_scopes
    assert "P" not in binder.nullable_scopes