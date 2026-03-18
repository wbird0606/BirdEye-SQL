import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder

@pytest.fixture
def registry():
    # 建立一個包含完整路徑模擬的元數據 [cite: 11]
    csv_data = "table_name,column_name,data_type\nUsers,UserID,INT\n"
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

def test_multi_part_identifiers_three_levels(registry):
    """測試：三層級限定符 (Schema.Table.Column)"""
    # 這是 MSSQL 非常常見的語法 
    sql = "SELECT dbo.Users.UserID FROM Users"
    ast = run_pipeline(sql, registry)
    
    # 驗證最後的欄位名稱是否正確識別
    assert ast.columns[0].name == "UserID"
    # 驗證前綴是否完整保留（我們之後需要重構 IdentifierNode 來存儲 List）
    assert ast.columns[0].qualifier == "dbo.Users"

def test_multi_part_identifiers_with_brackets(registry):
    """測試：帶中括號的多層級標識符"""
    sql = "SELECT [Database].[dbo].[Users].[UserID] FROM [Users]"
    ast = run_pipeline(sql, registry)
    assert ast.columns[0].name == "UserID"