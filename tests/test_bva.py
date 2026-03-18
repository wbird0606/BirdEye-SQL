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

    # 修正 Match 字串：從 "Expected SELECT keyword" 改為 "Expected SELECT"
    with pytest.raises(SyntaxError, match="Expected SELECT"):
        parser.parse()

def test_bva_trailing_garbage_injection(registry):
    """BVA 測試 3：夾帶惡意 SQL 注入的尾隨垃圾"""
    sql = "SELECT * FROM Users ; DROP TABLE Users--"
    
    # 修正 Match 字串：現在會精準指出是哪個 Token (Unexpected token: ;)
    with pytest.raises(SyntaxError, match="Unexpected token: ;"):
        run_pipeline(sql, registry)