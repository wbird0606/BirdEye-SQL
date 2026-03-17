import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# 準備測試用的 Registry
@pytest.fixture
def registry():
    csv_data = "table_name,column_name,data_type\nUsers,UserID,INT\nUsers,UserName,VARCHAR\n"
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_pipeline(sql, registry):
    """輔助函數：一條龍執行 Lexer -> Parser -> Binder"""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

def test_bva_extreme_whitespace(registry):
    """BVA 測試 1：極端空白與換行符號攻擊"""
    # 混雜 \t, \n, \r 甚至連續多個空白
    sql = " \n\n\t  SELECT \r\n * \t\t FROM \n Users \n\n  "
    ast = run_pipeline(sql, registry)
    assert ast.table.name.upper() == "USERS"
    assert ast.is_select_star is True

def test_bva_empty_query():
    """BVA 測試 2：空字串攻擊"""
    sql = "   \n  "
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    
    # 應該要拋出語法錯誤，因為連 SELECT 都沒有
    with pytest.raises(SyntaxError, match="Expected SELECT keyword"):
        parser.parse()

def test_bva_trailing_garbage_injection(registry):
    """BVA 測試 3 (致命弱點！)：夾帶惡意 SQL 注入的尾隨垃圾"""
    # 駭客企圖在合法的 SELECT 後面夾帶惡意指令
    sql = "SELECT * FROM Users ; DROP TABLE Users--"
    
    # 嚴格的 Parser 應該要在解析完 Users 後，發現後面還有東西沒處理完而報錯！
    with pytest.raises(SyntaxError, match="Unexpected tokens after parsing"):
        run_pipeline(sql, registry)