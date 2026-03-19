import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

@pytest.fixture
def dml_reg():
    """建立 DML 測試用的元數據"""
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
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    return parser.parse()

# --- 群組 1：成功的語法解析 (UPDATE / DELETE) ---
@pytest.mark.parametrize("sql, expected_type, expected_table, set_count", [
    # 基礎 UPDATE
    ("UPDATE Users SET UserName = 'Bird' WHERE UserID = 1", "UpdateStatement", "USERS", 1),
    # 多欄位 UPDATE
    ("UPDATE Users SET UserName = 'New', Email = 'test@mail' WHERE UserID = 1", "UpdateStatement", "USERS", 2),
    # 基礎 DELETE
    ("DELETE FROM Users WHERE UserID = 1", "DeleteStatement", "USERS", 0),
])
def test_dml_parsing_success(sql, expected_type, expected_table, set_count):
    ast = run_parse(sql)
    assert ast.__class__.__name__ == expected_type
    assert ast.table.name.upper() == expected_table
    if expected_type == "UpdateStatement":
        assert len(ast.set_clauses) == set_count
    assert ast.where_condition is not None

# --- 群組 2：ZTA 安全攔截 (強制 WHERE 子句) ---
@pytest.mark.parametrize("sql", [
    "UPDATE Users SET UserName = 'Hack'", # 缺少 WHERE
    "DELETE FROM Users",                  # 缺少 WHERE
    "DELETE Users",                       # 簡寫但同樣缺 WHERE
])
def test_zta_mandatory_where_protection(sql):
    """驗證 ZTA 核心原則：禁止無條件的變更操作"""
    with pytest.raises(SyntaxError, match="WHERE clause is mandatory for UPDATE/DELETE"):
        run_parse(sql)

# --- 群組 3：語意錯誤攔截 (欄位存在性) ---
@pytest.mark.parametrize("sql, error_match", [
    # 欄位不存在於元數據
    ("UPDATE Users SET GhostColumn = 1 WHERE UserID = 1", "Column 'GhostColumn' not found in 'Users'"),
    # WHERE 子句中的欄位不存在
    ("DELETE FROM Users WHERE UnknownCol = 99", "Column 'UnknownCol' not found in 'Users'"),
])
def test_dml_semantic_errors(dml_reg, sql, error_match):
    ast = run_parse(sql)
    binder = Binder(dml_reg)
    with pytest.raises(SemanticError, match=error_match):
        binder.bind(ast)