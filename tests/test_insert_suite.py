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

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. INSERT 語法解析測試 (Real Metadata) ---

@pytest.mark.parametrize("sql, expected_table, col_count, val_count", [
    # 指定欄位的標準寫入 (Product 表)
    ("INSERT INTO Product (ProductID, Name) VALUES (1, 'Bird')", "PRODUCT", 2, 2),
    # 帶有函數調用的寫入
    ("INSERT INTO Product (ProductID, Name, SellStartDate) VALUES (1, 'A', GETDATE())", "PRODUCT", 3, 3),
])
def test_insert_parsing_success(global_runner, sql, expected_table, col_count, val_count):
    """驗證 INSERT 語句是否能正確解析為 AST 節點"""
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.__class__.__name__ == "InsertStatement"
    assert ast.table.name.upper() == expected_table
    assert len(ast.columns) == col_count
    assert len(ast.values) == val_count

# --- 3. ZTA 欄位對齊與語意防禦 (Real Metadata) ---

@pytest.mark.parametrize("sql, error_match", [
    # 欄位數量不匹配 (指定 2 欄但給 1 值)
    ("INSERT INTO Product (ProductID, Name) VALUES (1)", "Column count mismatch: Expected 2, got 1"),
    # 寫入不存在的欄位
    ("INSERT INTO Product (GhostColumn) VALUES (1)", "Column 'GhostColumn' not found in 'Product'"),
    # 💡 嚴格類型防禦：StandardCost 是 money，給字串應報錯
    ("INSERT INTO Product (StandardCost) VALUES ('High')", "Cannot compare MONEY with NVARCHAR"),
    # 全表寫入數量檢查 (Product 在 output.csv 中有 25 欄)
    ("INSERT INTO Product VALUES (1, 'A')", "Column count mismatch: Expected 25, got 2"),
])
def test_insert_semantic_errors(global_runner, sql, error_match):
    """驗證 Binder 是否能根據真實元數據執行 ZTA 寫入檢查"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind_with_runner(sql, global_runner)

# --- 4. SqlBulkCopy 語義映射測試 (Bulk Insert) ---

def test_bulk_copy_mapping():
    """
    驗證 SqlBulkCopy 映射節點，這在處理大量軍事數據寫入時具備高效能語義。
    """
    sql = "BULK INSERT INTO Product"
    ast = run_parse(sql)
    assert ast.__class__.__name__ == "SqlBulkCopyStatement"
    assert ast.table.name.upper() == "PRODUCT"

def test_bulk_copy_semantic_validation(global_runner):
    """驗證 BulkCopy 的目標表必須存在於真實元數據中"""
    sql = "BULK INSERT INTO NonExistentTable"
    with pytest.raises(SemanticError, match="Table 'NonExistentTable' not found"):
        run_bind_with_runner(sql, global_runner)