import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def insert_reg():
    """
    建立寫入測試專用的元數據。
    包含 Users 與 Logs 表，用於驗證不同寫入場景的結構對齊。
    """
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Users,Email,VARCHAR\n"
        "Logs,LogID,INT\n"
        "Logs,Message,VARCHAR\n"
        "Logs,CreatedAt,DATETIME\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_parse(sql):
    """執行解析流程"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    return parser.parse()

def run_bind(sql, registry):
    """執行語意綁定流程"""
    ast = run_parse(sql)
    binder = Binder(registry)
    return binder.bind(ast)

# --- 2. INSERT 語法解析測試 (Parsing) ---

@pytest.mark.parametrize("sql, expected_table, col_count, val_count", [
    # 指定欄位的標準寫入
    ("INSERT INTO Users (UserID, UserName) VALUES (1, 'Bird')", "USERS", 2, 2),
    # 不指定欄位的全表寫入
    ("INSERT INTO Users VALUES (10, '家維', 'weiiiii@airforce.gov')", "USERS", 0, 3),
    # 帶有函數調用的寫入
    ("INSERT INTO Logs (LogID, Message, CreatedAt) VALUES (1, 'Login', GETDATE())", "LOGS", 3, 3),
])
def test_insert_parsing_success(sql, expected_table, col_count, val_count):
    """驗證 INSERT 語句是否能正確解析為 AST 節點"""
    ast = run_parse(sql)
    assert ast.__class__.__name__ == "InsertStatement"
    assert ast.table.name.upper() == expected_table
    assert len(ast.columns) == col_count
    assert len(ast.values) == val_count

# --- 3. ZTA 欄位對齊與語意防禦 (Semantic) ---

@pytest.mark.parametrize("sql, error_match", [
    # 欄位數量不匹配 (指定 2 欄但給 3 值)
    ("INSERT INTO Users (UserID, UserName) VALUES (1, 'Bird', 'Extra')", "Column count mismatch: Expected 2, got 3"),
    # 全表寫入時數量不匹配 (Users 有 3 欄，只給 2 值)
    ("INSERT INTO Users VALUES (1, 'MissingEmail')", "Column count mismatch: Expected 3, got 2"),
    # 寫入不存在的欄位
    ("INSERT INTO Users (GhostColumn) VALUES (1)", "Column 'GhostColumn' not found in 'Users'"),
    # 寫入不存在的表
    ("INSERT INTO GhostTable VALUES (1)", "Table 'GhostTable' not found"),
])
def test_insert_semantic_errors(insert_reg, sql, error_match):
    """驗證 Binder 是否能精準執行 ZTA 的寫入完整性檢查"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind(sql, insert_reg)

# --- 4. SqlBulkCopy 語義映射測試 (Bulk Insert) ---

def test_bulk_copy_mapping():
    """
    驗證 SqlBulkCopy 映射節點，這在處理大量軍事數據寫入時具備高效能語義。
    """
    sql = "BULK INSERT INTO Logs"
    ast = run_parse(sql)
    assert ast.__class__.__name__ == "SqlBulkCopyStatement"
    assert ast.table.name.upper() == "LOGS"

def test_bulk_copy_semantic_validation(insert_reg):
    """驗證 BulkCopy 的目標表必須存在於元數據中"""
    sql = "BULK INSERT INTO NonExistentTable"
    with pytest.raises(SemanticError, match="Table 'NonExistentTable' not found"):
        run_bind(sql, insert_reg)