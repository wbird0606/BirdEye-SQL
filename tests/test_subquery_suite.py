import pytest
import io
import json
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.ast import UnionStatement, SelectStatement
from birdeye.serializer import ASTSerializer
from birdeye.visualizer import ASTVisualizer


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


def run_bind_with_runner(sql, runner):
    """輔助函式：執行完整流水線並回傳 AST"""
    return runner.run(sql)["ast"]


# --- (from test_subquery_any_all_suite.py) ---

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
    sql = "SELECT * FROM Address WHERE AddressID > ANY (1, 2, 3)"
    result = global_runner.run(sql)
    assert result["ast"].where_condition.operator == "> ANY"

def test_any_all_in_complex_queries(global_runner):
    """驗證 ANY/ALL 在複雜查詢下的語意分析"""
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
    sql = "SELECT * FROM Address WHERE AddressID > ANY (SELECT City FROM Address)"
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


# --- (from test_union_suite.py) ---

# --- 1. UNION 語法解析測試 ---

def test_union_parsing_success(global_runner):
    """驗證 Parser 是否能正確識別 UNION 並連結兩個 SELECT"""
    sql = "SELECT AddressID FROM Address UNION SELECT 1"
    ast = run_bind_with_runner(sql, global_runner)

    assert isinstance(ast, UnionStatement)
    assert ast.operator == "UNION"
    assert isinstance(ast.left, SelectStatement)
    assert isinstance(ast.right, SelectStatement)

def test_union_all_parsing_success(global_runner):
    """驗證 UNION ALL 語法"""
    sql = "SELECT City FROM Address UNION ALL SELECT 'Taipei'"
    ast = run_bind_with_runner(sql, global_runner)
    assert ast.operator == "UNION ALL"

# --- 2. ZTA 結構安全性驗證 (核心資安點) ---

def test_union_column_count_mismatch(global_runner):
    """🛡️ ZTA 政策：UNION 兩側欄位數量必須完全一致"""
    sql = "SELECT AddressID, City FROM Address UNION SELECT 1"
    with pytest.raises(SemanticError, match="All queries combined using a UNION operator must have an equal number of expressions"):
        run_bind_with_runner(sql, global_runner)

def test_union_type_compatibility_invalid(global_runner):
    """🛡️ ZTA 政策：UNION 對應位置的欄位型別家族必須相容"""
    sql = "SELECT AddressID FROM Address UNION SELECT 'SomeString'"
    with pytest.raises(SemanticError, match="Incompatible types in UNION"):
        run_bind_with_runner(sql, global_runner)

# --- 3. 遞迴 UNION 測試 ---

def test_union_triple_recursive(global_runner):
    """驗證多重 UNION 的鏈式解析"""
    sql = "SELECT 1 UNION SELECT 2 UNION SELECT 3"
    ast = run_bind_with_runner(sql, global_runner)
    assert isinstance(ast, UnionStatement)
    assert isinstance(ast.left, UnionStatement)


# --- (from test_derived_table_suite.py) ---

# ─────────────────────────────────────────────
# MAX / MIN 函數
# ─────────────────────────────────────────────

def test_max_function(global_runner):
    """SELECT MAX(AddressID) 應成功"""
    result = global_runner.run("SELECT MAX(AddressID) FROM Address")
    assert result["status"] == "success"


def test_min_function(global_runner):
    """SELECT MIN(AddressID) 應成功"""
    result = global_runner.run("SELECT MIN(AddressID) FROM Address")
    assert result["status"] == "success"


def test_max_in_having(global_runner):
    """HAVING MAX(...) 應成功"""
    result = global_runner.run(
        "SELECT City FROM Address GROUP BY City HAVING MAX(AddressID) > 1"
    )
    assert result["status"] == "success"


def test_min_in_subquery(global_runner):
    """子查詢中的 MIN 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE AddressID = (SELECT MIN(AddressID) FROM Address)"
    )
    assert result["status"] == "success"


def test_max_return_type(global_runner):
    """MAX 回傳型別應與欄位型別相同 (INT)"""
    result = global_runner.run("SELECT MAX(AddressID) FROM Address")
    ast = result["ast"]
    assert ast.columns[0].inferred_type == "INT"


# ─────────────────────────────────────────────
# 衍生資料表 FROM (SELECT ...) alias
# ─────────────────────────────────────────────

def test_derived_table_basic(global_runner):
    """FROM (SELECT ...) sub 應成功綁定"""
    result = global_runner.run(
        "SELECT sub.City FROM (SELECT City FROM Address) sub"
    )
    assert result["status"] == "success"


def test_derived_table_column_access(global_runner):
    """衍生資料表的欄位可透過 alias 存取"""
    result = global_runner.run(
        "SELECT sub.AddressID FROM (SELECT AddressID, City FROM Address) sub"
    )
    assert result["status"] == "success"


def test_derived_table_with_where(global_runner):
    """衍生資料表搭配外層 WHERE 應成功"""
    result = global_runner.run(
        "SELECT sub.City FROM (SELECT City, AddressID FROM Address) sub "
        "WHERE sub.AddressID > 0"
    )
    assert result["status"] == "success"


def test_derived_table_parser_produces_select_as_table():
    """Parser 應將衍生資料表解析為含 subquery 的 SelectStatement"""
    ast = parse("SELECT sub.City FROM (SELECT City FROM T) sub")
    assert ast.table is not None
    assert ast.table_alias == "sub"


def test_derived_table_no_alias_raises():
    """衍生資料表沒有 alias 應拋出 SyntaxError"""
    with pytest.raises(SyntaxError):
        parse("SELECT City FROM (SELECT City FROM Address)")


# ─────────────────────────────────────────────
# JOIN (SELECT ...) alias ON ...
# ─────────────────────────────────────────────

def test_join_subquery_basic(global_runner):
    """JOIN (SELECT ...) sub ON ... 應成功"""
    result = global_runner.run(
        "SELECT a.City FROM Address a "
        "JOIN (SELECT AddressID FROM Address) sub ON a.AddressID = sub.AddressID"
    )
    assert result["status"] == "success"


def test_join_subquery_column_access(global_runner):
    """JOIN 子查詢的欄位可透過 alias 存取"""
    result = global_runner.run(
        "SELECT a.City, sub.AddressID FROM Address a "
        "LEFT JOIN (SELECT AddressID FROM Address WHERE AddressID > 0) sub "
        "ON a.AddressID = sub.AddressID"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# N'' Unicode 字串前綴
# ─────────────────────────────────────────────

def test_lexer_n_prefix_string():
    """N'...' 應被詞法分析為單一 STRING_LITERAL token"""
    tokens = Lexer("SELECT N'Taipei'").tokenize()
    string_tokens = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
    assert len(string_tokens) == 1
    assert string_tokens[0].value.strip("'") == "Taipei"


def test_n_prefix_in_where(global_runner):
    """WHERE City = N'Taipei' 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE City = N'Taipei'"
    )
    assert result["status"] == "success"


def test_n_prefix_in_select(global_runner):
    """SELECT N'hello' 應成功"""
    result = global_runner.run("SELECT N'hello'")
    assert result["status"] == "success"


def test_n_prefix_in_insert(global_runner):
    """INSERT VALUES 中使用 N'' 應成功"""
    result = global_runner.run(
        "INSERT INTO Address (AddressID, City) VALUES (999, N'台北')"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Visualizer / Serializer 同步
# ─────────────────────────────────────────────

def test_derived_table_serialization(global_runner):
    """衍生資料表序列化後 table 應為 SelectStatement"""
    ast = parse("SELECT sub.City FROM (SELECT City FROM T) sub")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["table"]["node_type"] == "SelectStatement"
    assert data["alias"] == "sub"


def test_derived_table_visualizer(global_runner):
    """衍生資料表視覺化應顯示 SUBQUERY 節點"""
    ast = parse("SELECT sub.City FROM (SELECT City FROM T) sub")
    output = ASTVisualizer().dump(ast)
    assert "SUBQUERY" in output or "SELECT_STATEMENT" in output
