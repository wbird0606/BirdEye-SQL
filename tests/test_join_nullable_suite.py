import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder

@pytest.fixture
def nullable_reg():
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Orders,OrderID,INT\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def test_left_join_nullability_semantic(nullable_reg):
    """
    驗證 LEFT JOIN 時，右表應該被標記為 Nullable 作用域
    """
    sql = "SELECT u.UserID, o.OrderID FROM Users u LEFT JOIN Orders o ON u.UserID = o.OrderID"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    binder = Binder(nullable_reg)
    bound_ast = binder.bind(ast)
    
    # 這裡我們預期 Binder 內部有一個機制紀錄 nullable 表
    # 雖然目前 Binder 尚未實作此屬性，這就是我們要補上的部分
    assert bound_ast.joins[0].type == "LEFT"
    assert "O" in binder.nullable_scopes  # 預期右表 O 為 Nullable

def test_right_join_nullability_semantic(nullable_reg):
    """
    驗證 RIGHT JOIN 時，左表（主表）應該變為 Nullable
    """
    sql = "SELECT u.UserID, o.OrderID FROM Users u RIGHT JOIN Orders o ON u.UserID = o.OrderID"
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    
    binder = Binder(nullable_reg)
    bound_ast = binder.bind(ast)
    
    assert bound_ast.joins[0].type == "RIGHT"
    assert "U" in binder.nullable_scopes  # 預期左表 U 變為 Nullable