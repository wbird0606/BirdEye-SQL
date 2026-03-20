import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

# --- 1. 測試環境設置 ---

@pytest.fixture
def dml_reg():
    """
    建立 DML 測試專用的元數據註冊表。
    包含 Users 表與基本欄位，用於驗證變更操作的合法性。
    """
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Users,Email,VARCHAR\n"
        "Users,Status,VARCHAR\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_parse(sql):
    """執行 Lexer 與 Parser 的流水線，回傳 AST"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    return parser.parse()

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. 語法解析成功測試 (DML Parsing) ---

@pytest.mark.parametrize("sql, expected_type, expected_table, set_count", [
    # 基礎 UPDATE 語法 (使用真實 Product 表)
    ("UPDATE Product SET Name = 'Bird' WHERE ProductID = 1", "UpdateStatement", "PRODUCT", 1),
    # 多欄位 UPDATE 語法
    ("UPDATE Product SET Name = 'New', Color = 'Blue' WHERE ProductID = 1", "UpdateStatement", "PRODUCT", 2),
    # 基礎 DELETE 語法
    ("DELETE FROM Product WHERE ProductID = 1", "DeleteStatement", "PRODUCT", 0),
])
def test_dml_parsing_success(sql, expected_type, expected_table, set_count):
    """驗證 UPDATE 與 DELETE 是否能正確轉換為對應的 AST 節點"""
    # 解析階段不依賴元數據
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()

    assert ast.__class__.__name__ == expected_type
    assert ast.table.name.upper() == expected_table
    if expected_type == "UpdateStatement":
        assert len(ast.set_clauses) == set_count
    # 核心安全點：所有成功的 DML 必須具備 WHERE 條件
    assert ast.where_condition is not None

# --- 💡 TDD New: DML 語意錯誤與類型檢查 (Real Metadata) ---

@pytest.mark.parametrize("sql, error_match", [
    # 欄位不存在於 SET 子句中
    ("UPDATE Product SET GhostColumn = 1 WHERE ProductID = 1", "Column 'GhostColumn' not found in 'Product'"),
    # 欄位不存在於 WHERE 子句中
    ("DELETE FROM Product WHERE UnknownCol = 99", "Column 'UnknownCol' not found in 'Product'"),
    # 💡 類型不匹配測試 (ListPrice 是 money/numeric，給字串應報錯)
    ("UPDATE Product SET ListPrice = 'Free' WHERE ProductID = 1", "Cannot compare MONEY with NVARCHAR"),
])
def test_dml_semantic_errors(global_runner, sql, error_match):
    """驗證 Binder 是否能根據真實元數據精準攔截非法欄位或類型錯誤"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind_with_runner(sql, global_runner)