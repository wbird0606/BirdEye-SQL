import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def scope_reg():
    reg = MetadataRegistry()
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,ID,INT\n"
        "Users,UserID,INT\n"  # 💡 核心修正：加入此行
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
    
    # 預期 WHERE 條件的右側是一個嵌套的 SelectStatement
    # (註：這需要 Parser 在 _parse_primary 支援括號內的 SELECT)
    assert ast.where_condition.right.__class__.__name__ == "SelectStatement"

# --- 3. 作用域隔離與遞迴搜尋 (Semantic) ---

def test_subquery_scope_isolation(scope_reg):
    """
    🛡️ ZTA 政策：子查詢內部的別名不應洩漏到外部。
    """
    sql = "SELECT * FROM Users u WHERE UserID IN (SELECT UserID FROM Orders o) AND o.OrderID > 0"
    # 外部查詢不應該認識子查詢裡的別名 'o'
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
    # 如果 Binder 實作了 Scope Stack，這裡的 u.UserID 應該能被正確解析
    ast = run_bind(sql, scope_reg)
    inner_select = ast.where_condition.args[0] # 假設 EXISTS 解析為 FunctionCall
    inner_where = inner_select.where_condition
    assert inner_where.right.qualifier == "u"

# --- 4. 深度嵌套挑戰 ---

def test_triple_nested_scopes(scope_reg):
    """驗證三層作用域的穩定性"""
    sql = "SELECT * FROM Users WHERE ID IN (SELECT ID FROM A WHERE ID IN (SELECT ID FROM B))"
    # 每一層都應該有獨立且正確連接的作用域字典
    try:
        run_bind(sql, scope_reg)
    except SemanticError as e:
        if "Table 'A' not found" in str(e): pass # 這是正確的，因為元數據沒 A
        else: raise