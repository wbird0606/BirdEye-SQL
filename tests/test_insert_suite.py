import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

@pytest.fixture
def insert_reg():
    """建立寫入測試用的元數據"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Logs,LogID,INT\n"
        "Logs,Message,VARCHAR\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_parse(sql):
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    return parser.parse()

# --- 群組 1：INSERT 語法解析成功 ---
@pytest.mark.parametrize("sql, expected_table, col_count, val_count", [
    # 指定欄位的 INSERT
    ("INSERT INTO Users (UserID, UserName) VALUES (1, 'Bird')", "USERS", 2, 2),
    # 不指定欄位的 INSERT (全表寫入)
    ("INSERT INTO Users VALUES (2, '家維')", "USERS", 0, 2),
])
def test_insert_parsing_success(sql, expected_table, col_count, val_count):
    ast = run_parse(sql)
    assert ast.__class__.__name__ == "InsertStatement"
    assert ast.table.name.upper() == expected_table
    assert len(ast.columns) == col_count
    assert len(ast.values) == val_count

# --- 群組 2：語意校驗（欄位對齊與存在性） ---
@pytest.mark.parametrize("sql, error_match", [
    # 欄位數量不匹配
    ("INSERT INTO Users (UserID) VALUES (1, 'Extra')", "Column count mismatch"),
    # 寫入不存在的欄位
    ("INSERT INTO Users (Ghost) VALUES (1)", "Column 'Ghost' not found in 'Users'"),
])
def test_insert_semantic_errors(insert_reg, sql, error_match):
    ast = run_parse(sql)
    binder = Binder(insert_reg)
    with pytest.raises(SemanticError, match=error_match):
        binder.bind(ast)

# --- 群組 3：SqlBulkCopy 模擬解析 ---
def test_bulk_copy_semantic_mapping():
    """驗證 SqlBulkCopy 映射節點"""
    # 這裡模擬 BulkCopy 的特殊語法或 API 調用映射
    sql = "BULK INSERT INTO Logs" 
    ast = run_parse(sql)
    assert ast.__class__.__name__ == "SqlBulkCopyStatement"
    assert ast.table.name.upper() == "LOGS"