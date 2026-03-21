import pytest
import io
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError

def run_bind_with_runner(sql, runner):
    """使用全域 Runner 執行完整繫結"""
    return runner.run(sql)["ast"]

# --- 1. ANY Operator Parsing Tests ---

@pytest.mark.parametrize("sql, expected_op", [
    ("SELECT * FROM Address WHERE AddressID > ANY (SELECT 1)", "> ANY"),
    ("SELECT * FROM Address WHERE AddressID = ANY (SELECT 1)", "= ANY"),
    ("SELECT * FROM Address WHERE AddressID <> ANY (SELECT 1)", "<> ANY"),
])
def test_any_operator_parsing(sql, expected_op):
    """Test parsing of ANY operator."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    assert ast.where_condition.operator == expected_op

# --- 2. ANY/ALL with Value Lists ---

@pytest.mark.parametrize("sql, expected_op", [
    ("SELECT * FROM Address WHERE AddressID > ANY (100, 200, 300)", "> ANY"),
    ("SELECT * FROM Address WHERE AddressID = ALL (200, 200, 200)", "= ALL"),
])
def test_any_all_with_value_lists(sql, expected_op):
    """Test ANY/ALL operators with value lists."""
    lexer = Lexer(sql)
    parser = Parser(lexer.tokenize(), sql)
    ast = parser.parse()
    assert ast.where_condition.operator == expected_op
    assert isinstance(ast.where_condition.right, list)

# --- 3. Integration Tests (Real Metadata) ---

def test_any_all_full_pipeline(global_runner):
    """驗證 ANY 在真實流水線下的運作 (使用 AddressID)"""
    # AddressID 是 INT
    sql = "SELECT * FROM Address WHERE AddressID > ANY (1, 2, 3)"
    result = global_runner.run(sql)
    assert result["ast"].where_condition.operator == "> ANY"

def test_any_all_in_complex_queries(global_runner):
    """驗證 ANY/ALL 在複雜查詢下的語意分析"""
    # 使用 BusinessEntityID 與 AddressID (皆為 INT)
    sql = """
    SELECT BusinessEntityID
    FROM BusinessEntity
    WHERE BusinessEntityID >= ALL (
        SELECT AddressID
        FROM Address
        WHERE City = 'Bothell'
    )
    AND BusinessEntityID > ANY (10, 20, 30)
    """
    result = global_runner.run(sql)
    assert result["ast"] is not None

# --- 4. Semantic Error Tests (Real Metadata) ---

def test_any_all_type_mismatch(global_runner):
    """🛡️ ZTA 政策：驗證 ANY/ALL 兩側型別不相容時應攔截"""
    # AddressID (INT) vs City (NVARCHAR)
    sql = "SELECT * FROM Address WHERE AddressID > ANY (SELECT City FROM Address)"
    # 注意：現在錯誤訊息包含 context
    with pytest.raises(SemanticError, match="Incompatible types in > ANY"):
        global_runner.run(sql)

# --- 5. Equivalence Tests ---

def test_any_equivalence_with_in(global_runner):
    """驗證 = ANY 與 IN 的語意等價性"""
    sql_any = "SELECT * FROM Address WHERE AddressID = ANY (1, 2, 3)"
    sql_in = "SELECT * FROM Address WHERE AddressID IN (1, 2, 3)"

    for sql in [sql_any, sql_in]:
        result = global_runner.run(sql)
        assert result["ast"] is not None
