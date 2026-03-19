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

def run_bind(sql, registry):
    """執行完整的語意綁定流程"""
    ast = run_parse(sql)
    binder = Binder(registry)
    return binder.bind(ast)

# --- 2. 語法解析成功測試 (DML Parsing) ---

@pytest.mark.parametrize("sql, expected_type, expected_table, set_count", [
    # 基礎 UPDATE 語法
    ("UPDATE Users SET UserName = 'Bird' WHERE UserID = 1", "UpdateStatement", "USERS", 1),
    # 多欄位 UPDATE 語法
    ("UPDATE Users SET UserName = 'New', Email = 'test@mail' WHERE UserID = 1", "UpdateStatement", "USERS", 2),
    # 基礎 DELETE 語法
    ("DELETE FROM Users WHERE UserID = 1", "DeleteStatement", "USERS", 0),
    # 帶有複雜邏輯條件的 DELETE
    ("DELETE FROM Users WHERE UserID = 1 AND Status = 'Old'", "DeleteStatement", "USERS", 0),
])
def test_dml_parsing_success(sql, expected_type, expected_table, set_count):
    """驗證 UPDATE 與 DELETE 是否能正確轉換為對應的 AST 節點"""
    ast = run_parse(sql)
    assert ast.__class__.__name__ == expected_type
    assert ast.table.name.upper() == expected_table
    if expected_type == "UpdateStatement":
        assert len(ast.set_clauses) == set_count
    # 核心安全點：所有成功的 DML 必須具備 WHERE 條件
    assert ast.where_condition is not None

# --- 3. ZTA 安全攔截測試 (Mandatory WHERE) ---

@pytest.mark.parametrize("sql", [
    "UPDATE Users SET UserName = 'Hack'",      # 缺少 WHERE 子句
    "DELETE FROM Users",                       # 缺少 WHERE 子句
    "DELETE Users",                            # 簡寫但同樣缺少 WHERE 子句
    "UPDATE Users SET Status = 'A' -- 惡意註解截斷", # 註解後方無條件
])
def test_zta_mandatory_where_protection(sql):
    """
    驗證 ZTA 核心原則：禁止無條件的變更操作。
    任何嘗試執行全表變更的指令都必須在 Parser 層級被攔截。
    """
    with pytest.raises(SyntaxError, match="WHERE clause is mandatory for UPDATE/DELETE"):
        run_parse(sql)

# --- 4. 語意錯誤攔截測試 (Semantic Validation) ---

@pytest.mark.parametrize("sql, error_match", [
    # 欄位不存在於 SET 子句中
    ("UPDATE Users SET GhostColumn = 1 WHERE UserID = 1", "Column 'GhostColumn' not found in 'Users'"),
    # 欄位不存在於 WHERE 子句中
    ("DELETE FROM Users WHERE UnknownCol = 99", "Column 'UnknownCol' not found in 'Users'"),
    # 在 UPDATE 中引用未定義的表別名
    ("UPDATE Users SET UserName = 'A' WHERE x.UserID = 1", "Unknown qualifier 'x'"),
])
def test_dml_semantic_errors(dml_reg, sql, error_match):
    """驗證 Binder 是否能根據元數據精準攔截非法欄位或作用域錯誤"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind(sql, dml_reg)