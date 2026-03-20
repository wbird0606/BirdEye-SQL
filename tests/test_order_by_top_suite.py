import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def bird_reg():
    """建立包含基礎表的元數據，用於驗證排序欄位的合法性"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Users,Email,VARCHAR\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_parse(sql):
    """執行 Lexer 與 Parser 流水線"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    return parser.parse()

def run_bind(sql, registry):
    """執行完整語意綁定"""
    ast = run_parse(sql)
    binder = Binder(registry)
    return binder.bind(ast)

# --- 2. Lexer 關鍵字測試 ---

def test_lexer_new_keywords():
    """驗證 Lexer 是否能識別排序與分頁相關的關鍵字"""
    sql = "SELECT TOP 10 * FROM Users ORDER BY UserID ASC DESC"
    lexer = Lexer(sql)
    tokens = [t.type for t in lexer.tokenize()]
    
    # 預期包含新增的關鍵字類型 (待實作於 lexer.py)
    assert TokenType.KEYWORD_TOP in tokens
    assert TokenType.KEYWORD_ORDER in tokens
    assert TokenType.KEYWORD_BY in tokens
    assert TokenType.KEYWORD_ASC in tokens
    assert TokenType.KEYWORD_DESC in tokens

# --- 3. Parser 結構測試 (Parsing) ---

@pytest.mark.parametrize("sql, expected_top, order_count", [
    # 基礎 TOP 測試
    ("SELECT TOP 10 * FROM Users", 10, 0),
    # 基礎 ORDER BY 測試
    ("SELECT * FROM Users ORDER BY UserID", None, 1),
    # 複合測試：TOP + ORDER BY (DESC)
    ("SELECT TOP 5 UserName FROM Users ORDER BY UserID DESC", 5, 1),
    # 多欄位排序測試
    ("SELECT * FROM Users ORDER BY UserName ASC, UserID DESC", None, 2),
])
def test_order_by_top_parsing(sql, expected_top, order_count):
    """驗證 Parser 是否能正確將 TOP 與 ORDER BY 資訊掛載至 SelectStatement"""
    ast = run_parse(sql)
    assert ast.__class__.__name__ == "SelectStatement"
    
    # 檢查 TOP 屬性 (需擴充 ast.py)
    if expected_top:
        assert ast.top_count == expected_top
    
    # 檢查 ORDER BY 節點數量 (需擴充 ast.py)
    assert len(ast.order_by_terms) == order_count

# --- 4. 語意綁定與 ZTA 政策測試 (Semantic) ---

def test_order_by_semantic_binding(bird_reg):
    """驗證 ORDER BY 中的欄位是否正確解析其作用域"""
    sql = "SELECT UserName FROM Users u ORDER BY u.UserID"
    ast = run_bind(sql, bird_reg)
    
    # 驗證 OrderByNode 中的標識符是否已綁定限定符
    order_node = ast.order_by_terms[0]
    assert order_node.column.qualifier.upper() == "U"

def test_order_by_invalid_column(bird_reg):
    """驗證排序不存在的欄位時應拋出錯誤"""
    sql = "SELECT * FROM Users ORDER BY GhostColumn"
    with pytest.raises(SemanticError, match="Column 'GhostColumn' not found in 'Users'"):
        run_bind(sql, bird_reg)

def test_order_by_ambiguous_column(bird_reg):
    """驗證在 JOIN 場景下，ORDER BY 欄位歧義攔截"""
    # 擴充元數據以產生歧義
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Orders,UserID,INT\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    
    sql = "SELECT * FROM Users JOIN Orders ON Users.UserID = Orders.UserID ORDER BY UserID"
    with pytest.raises(SemanticError, match="Column 'UserID' is ambiguous"):
        run_bind(sql, reg)

# --- 5. 語法容錯測試 ---

def test_top_missing_number():
    """驗證 TOP 後方若缺少數值應拋出語法錯誤"""
    sql = "SELECT TOP * FROM Users"
    with pytest.raises(SyntaxError, match="Expected numeric literal after TOP"):
        run_parse(sql)

# --- 💡 TDD New: ORDER BY Alias Resolution ---

def test_order_by_alias_resolution(bird_reg):
    """
    驗證 ORDER BY 是否能正確解析 SELECT 清單中定義的別名 (TDD Regression)
    """
    # Score 是別名，不是 Users 的實體欄位
    sql = "SELECT UserID + 100 AS Score FROM Users ORDER BY Score DESC"
    ast = run_bind(sql, bird_reg)
    
    # 驗證 ORDER BY 成功解析並推導類型為 INT (由 UserID 推導而來)
    order_node = ast.order_by_terms[0].column
    assert order_node.inferred_type == "INT"