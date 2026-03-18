import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder

@pytest.fixture
def registry():
    # 模擬計畫書中提到的 CSV 元數據結構 [cite: 11]
    csv_data = "table_name,column_name,data_type\nUsers,UserID,INT\nUsers,UserName,VARCHAR\n"
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_pipeline(sql, registry):
    """一條龍執行：Lexer -> Parser -> Binder"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    ast = parser.parse()
    binder = Binder(registry)
    return binder.bind(ast)

def test_mssql_bracket_identifiers(registry):
    """測試：MSSQL 特有的中括號標識符 [cite: 4, 9]"""
    sql = "SELECT [UserID] FROM [Users]"
    ast = run_pipeline(sql, registry)
    assert ast.columns[0].name == "UserID"
    assert ast.table.name == "Users"

def test_qualified_star_expansion(registry):
    """測試：帶前綴的星號展開 (Table.*) [cite: 11]"""
    sql = "SELECT Users.* FROM Users"
    ast = run_pipeline(sql, registry)
    # 應正確展開為該表的所有欄位
    assert len(ast.columns) == 2
    assert ast.columns[0].name == "UserID"
    assert ast.columns[1].name == "UserName"

def test_table_alias_binding(registry):
    """測試：別名綁定 (Alias Binding) [cite: 11]"""
    # 這是提案書中強調的語意覺知重點 [cite: 3]
    sql = "SELECT u.UserID FROM Users AS u"
    ast = run_pipeline(sql, registry)
    assert ast.table.name == "Users"
    assert ast.columns[0].name == "UserID"

def test_qualified_star_expansion(registry):
    sql = "SELECT Users.* FROM Users"
    ast = run_pipeline(sql, registry)
    assert len(ast.columns) == 2
    # 使用 .upper() 進行防禦性比對
    assert ast.columns[0].name.upper() == "USERID" 

def test_table_alias_binding(registry):
    sql = "SELECT u.UserID FROM Users AS u"
    ast = run_pipeline(sql, registry)
    assert ast.table.name.upper() == "USERS"
    assert ast.columns[0].name.upper() == "USERID"