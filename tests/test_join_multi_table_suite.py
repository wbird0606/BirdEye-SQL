import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def multi_reg():
    """
    建立包含 Users, Orders, Products 的複雜元數據註冊表。
    用於驗證多表關聯下的欄位可見性與歧義性。
    """
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
    """一條龍執行：Lexer -> Parser -> Binder"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

# --- 2. 作用域可見性測試 (Visibility) ---

def test_three_table_join_visibility(multi_reg):
    """
    驗證 ZTA 增量註冊機制：C 表的 ON 條件必須能看見 A 表與 B 表的欄位。
    """
    sql = """
        SELECT u.UserName, p.ProductName 
        FROM Users u 
        JOIN Orders o ON u.UserID = o.UserID 
        JOIN Products p ON o.ProductID = p.ProductID
    """
    ast = run_bind(sql, multi_reg)
    assert len(ast.joins) == 2
    # 檢查第二個 JOIN (Products) 的 ON 條件是否正確綁定到前方的 Orders (o) 與自身的 Products (p)
    last_on = ast.joins[1]
    assert last_on.on_left.qualifier == "o"
    assert last_on.on_right.qualifier == "p"

# --- 3. 歧義與別名安全性測試 (ZTA Security) ---

def test_multi_table_ambiguity(multi_reg):
    """
    驗證歧義攔截：當 ProductID 同時存在於 Orders 與 Products，未指定限定符應報錯。
    """
    sql = """
        SELECT ProductID 
        FROM Users u 
        JOIN Orders o ON u.UserID = o.UserID 
        JOIN Products p ON o.ProductID = p.ProductID
    """
    # 預期拋出語意錯誤，並列出衝突的來源表
    with pytest.raises(SemanticError, match="Column 'ProductID' is ambiguous. Found in: ORDERS, PRODUCTS"):
        run_bind(sql, multi_reg)

def test_alias_invalidation_chain(multi_reg):
    """
    驗證 ZTA 別名強制失效原則：一旦 Users 定義了別名 u，禁止再以 Users 名稱存取欄位。
    """
    sql = """
        SELECT u.UserName 
        FROM Users u 
        JOIN Orders o ON u.UserID = o.UserID 
        JOIN Products p ON Users.UserID = p.ProductID  -- 這裡是非法的，應使用 u.UserID
    """
    with pytest.raises(SemanticError, match="Original table name 'Users' cannot be used when alias 'u' is defined"):
        run_bind(sql, multi_reg)

# --- 4. 嚴格順序檢查 (Strict Path Validation) ---

def test_disallow_forward_reference(multi_reg):
    """
    驗證 ZTA 嚴格模式：禁止「前瞻引用」。第一個 JOIN 不能引用尚未定義的後方表別名。
    """
    sql = """
        SELECT u.UserName 
        FROM Users u 
        JOIN Orders o ON u.UserID = p.ProductID  -- 錯誤：p 在下一行才加入作用域
        JOIN Products p ON o.ProductID = p.ProductID
    """
    with pytest.raises(SemanticError, match="Unknown qualifier 'p'"):
        run_bind(sql, multi_reg)

# --- 5. 複雜過濾條件測試 (Integrated) ---

def test_multi_table_where_clause(multi_reg):
    """
    驗證三表關聯下的 WHERE 子句欄位校驗。
    """
    sql = """
        SELECT u.UserName 
        FROM Users u 
        JOIN Orders o ON u.UserID = o.UserID 
        WHERE p.ProductName = 'AI-Bot'  -- 這裡 p 尚未在 SELECT 階段被綁定，但在完整解析後應可見
    """
    # 如果 p 已在 JOIN 列表，則 WHERE 應通過；若未 JOIN 則應失敗
    with pytest.raises(SemanticError, match="Unknown qualifier 'p'"):
        run_bind(sql, multi_reg)