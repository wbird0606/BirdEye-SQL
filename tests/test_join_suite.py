import pytest
import io
import json
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.serializer import ASTSerializer
from birdeye.visualizer import ASTVisualizer

# --- (from test_join_suite.py) ---

@pytest.fixture
def join_registry():
    """
    專為 JOIN 設計的元數據。
    包含 Users 與 Orders 表，且 UserID 欄位在兩表中均存在，用以測試歧義攔截。
    """
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Users,UserName,VARCHAR\n"
        "Orders,OrderID,INT\n"
        "Orders,UserID,INT\n"
        "Orders,Total,DECIMAL\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. 基礎 JOIN 語法測試 (Real Metadata) ---

@pytest.mark.parametrize("sql, expected_joins", [
    # 標準 JOIN (SalesOrderHeader h, SalesOrderDetail d)
    ("SELECT h.SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID", 1),
    # 顯式 LEFT JOIN (SalesOrderHeader h, Address a)
    ("SELECT h.SalesOrderID FROM SalesOrderHeader h LEFT JOIN Address a ON h.ShipToAddressID = a.AddressID", 1),
])
def test_join_basic_syntax(global_runner, sql, expected_joins):
    """驗證 Parser 是否能正確識別並解析真實元數據下的 JOIN"""
    ast = run_bind_with_runner(sql, global_runner)
    assert len(ast.joins) == expected_joins

# --- 3. ZTA 欄位歧義防禦 (核心資安點) ---

@pytest.mark.parametrize("sql, error_match", [
    # SalesOrderID 同時存在於 Header 與 Detail，未指定限定符應報錯
    ("SELECT SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID", "Column 'SalesOrderID' is ambiguous"),
    # ModifiedDate 同時存在於 Address 與 SalesOrderHeader
    ("SELECT ModifiedDate FROM Address a JOIN SalesOrderHeader h ON a.AddressID = h.ShipToAddressID", "Column 'ModifiedDate' is ambiguous"),
])
def test_join_ambiguity_protection(global_runner, sql, error_match):
    """驗證 Binder 是否能精準攔截真實元數據中的歧義欄位"""
    with pytest.raises(SemanticError, match=error_match):
        run_bind_with_runner(sql, global_runner)

# --- 4. ZTA 別名強制失效測試 (Alias Shadowing Defense) ---

def test_join_alias_invalidation_real_meta(global_runner):
    """🛡️ ZTA 政策：定義別名後，原有名稱在 JOIN 作用域中必須失效"""
    sql = "SELECT SalesOrderHeader.SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID"
    with pytest.raises(SemanticError, match="Original table name 'SalesOrderHeader' cannot be used when alias 'h' is defined"):
        run_bind_with_runner(sql, global_runner)

# --- 4. 隱含式關聯阻斷 (Security Policy) ---

def test_disallow_implicit_comma_join(global_runner):
    """
    ZTA 規範：禁止使用 FROM A, B 語法。
    強制要求顯式 JOIN...ON 以利於安全審計與路徑追蹤。
    """
    sql = "SELECT * FROM SalesOrderHeader, SalesOrderDetail"
    with pytest.raises(SyntaxError, match="Expected FROM"):
        run_bind_with_runner(sql, global_runner)

# --- 5. ON 子句作用域驗證 ---

def test_join_on_condition_scope(global_runner):
    """驗證 ON 子句中的欄位是否正確綁定到對應的作用域"""
    sql = "SELECT h.SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID"
    ast = run_bind_with_runner(sql, global_runner)

    join_node = ast.joins[0]
    assert join_node.on_left.qualifier == "h"
    assert join_node.on_right.qualifier == "d"


# --- (from test_join_multi_table_suite.py) ---

# --- 1. 多表歧義攔截測試 (Ambiguity Defense) ---

def test_multi_table_ambiguity(global_runner):
    """
    驗證歧義攔截：當 ProductID 同時存在於多表，未指定限定符應報錯。
    使用 SalesOrderDetail 與 Product (皆含 ProductID)。
    """
    sql = """
        SELECT ProductID
        FROM SalesOrderDetail d
        JOIN Product p ON d.ProductID = p.ProductID
    """
    with pytest.raises(SemanticError, match="Column 'ProductID' is ambiguous"):
        run_bind_with_runner(sql, global_runner)

# --- 2. ZTA 別名強制失效原則 (Alias Shadowing) ---

def test_alias_invalidation_chain(global_runner):
    """
    驗證 ZTA 政策：定義別名後，禁止以原始表名存取欄位。
    """
    sql = """
        SELECT Address.City
        FROM Address AS a
        JOIN Customer AS c ON a.AddressID = c.CustomerID
    """
    with pytest.raises(SemanticError, match="Original table name 'Address' cannot be used"):
        run_bind_with_runner(sql, global_runner)

# --- 3. 跨表欄位存在性檢查 ---

def test_multi_table_column_not_found(global_runner):
    """驗證在多表環境下，搜尋不存在的欄位應精確報錯"""
    sql = """
        SELECT d.SalesOrderID, p.GhostCol
        FROM SalesOrderDetail d
        JOIN Product p ON d.ProductID = p.ProductID
    """
    with pytest.raises(SemanticError, match="Column 'GhostCol' not found"):
        run_bind_with_runner(sql, global_runner)


# --- (from test_join_nullable_suite.py) ---

# --- 1. 可空性傳導測試 (Nullable Propagation) ---

def test_left_join_nullability(global_runner):
    """驗證 LEFT JOIN 右側表欄位在繫結後應被標記為 Nullable"""
    sql = "SELECT a.City, c.FirstName FROM Address a LEFT JOIN Customer c ON a.AddressID = c.CustomerID"

    runner_result = global_runner.run(sql)
    assert "ast" in runner_result

def test_right_join_nullability(global_runner):
    """驗證 RIGHT JOIN 左側表欄位應被標記為 Nullable"""
    sql = "SELECT a.City, c.FirstName FROM Address a RIGHT JOIN Customer c ON a.AddressID = c.CustomerID"
    runner_result = global_runner.run(sql)
    assert "ast" in runner_result


# --- (from test_join_not_pagination_suite.py) ---

def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


# ─────────────────────────────────────────────
# Issue #60: NOT IN
# ─────────────────────────────────────────────

def test_not_in_list(global_runner):
    """WHERE col NOT IN (v1, v2, v3) 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE AddressID NOT IN (1, 2, 3)"
    )
    assert result["status"] == "success"


def test_not_in_subquery(global_runner):
    """WHERE col NOT IN (SELECT ...) 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address "
        "WHERE AddressID NOT IN (SELECT AddressID FROM Address WHERE AddressID = 1)"
    )
    assert result["status"] == "success"


def test_not_in_produces_binary_expression():
    """NOT IN 應解析為 operator='NOT IN' 的 BinaryExpressionNode"""
    from birdeye.ast import BinaryExpressionNode
    ast = parse("SELECT A FROM T WHERE A NOT IN (1, 2)")
    assert isinstance(ast.where_condition, BinaryExpressionNode)
    assert ast.where_condition.operator == "NOT IN"


def test_not_in_type_mismatch_raises(global_runner):
    """NOT IN 型別不相容時應拋出 SemanticError"""
    with pytest.raises(SemanticError):
        global_runner.run(
            "SELECT AddressID FROM Address WHERE AddressID NOT IN ('X', 'Y')"
        )


# ─────────────────────────────────────────────
# Issue #61: NOT EXISTS
# ─────────────────────────────────────────────

def test_not_exists_basic(global_runner):
    """WHERE NOT EXISTS (SELECT ...) 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address "
        "WHERE NOT EXISTS (SELECT 1 FROM Address WHERE AddressID = 0)"
    )
    assert result["status"] == "success"


def test_not_exists_produces_function_node():
    """NOT EXISTS 應解析為 name='NOT EXISTS' 的 FunctionCallNode"""
    from birdeye.ast import FunctionCallNode
    ast = parse("SELECT A FROM T WHERE NOT EXISTS (SELECT 1 FROM T)")
    assert isinstance(ast.where_condition, FunctionCallNode)
    assert ast.where_condition.name == "NOT EXISTS"


def test_not_exists_with_correlated(global_runner):
    """NOT EXISTS 搭配相關子查詢應成功"""
    result = global_runner.run(
        "SELECT a.AddressID FROM Address a "
        "WHERE NOT EXISTS (SELECT 1 FROM Address b WHERE b.AddressID = a.AddressID AND b.AddressID < 0)"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Issue #62: CROSS JOIN
# ─────────────────────────────────────────────

def test_lexer_cross_join():
    """CROSS JOIN 的 CROSS token 應已存在 (KEYWORD_CROSS)"""
    tokens = Lexer("SELECT A FROM T CROSS JOIN T2").tokenize()
    types = [t.type for t in tokens]
    assert TokenType.KEYWORD_CROSS in types


def test_parser_cross_join_produces_join_node():
    """CROSS JOIN 應解析為 type='CROSS' 的 JoinNode（無 ON 條件）"""
    from birdeye.ast import JoinNode
    ast = parse("SELECT A FROM T CROSS JOIN T2")
    assert len(ast.joins) == 1
    assert ast.joins[0].type == "CROSS"
    assert ast.joins[0].on_condition is None


def test_cross_join_basic(global_runner):
    """CROSS JOIN 應成功綁定"""
    result = global_runner.run(
        "SELECT a.AddressID FROM Address a CROSS JOIN Address b"
    )
    assert result["status"] == "success"


def test_cross_join_with_where(global_runner):
    """CROSS JOIN 搭配 WHERE 應成功"""
    result = global_runner.run(
        "SELECT a.AddressID FROM Address a CROSS JOIN Address b "
        "WHERE a.AddressID = 1"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Issue #63: FULL OUTER JOIN
# ─────────────────────────────────────────────

def test_lexer_full_is_keyword():
    """FULL 應被詞法分析為 KEYWORD_FULL"""
    tokens = Lexer("SELECT A FROM T FULL OUTER JOIN T2 ON T.A = T2.A").tokenize()
    types = [t.type for t in tokens]
    assert TokenType.KEYWORD_FULL in types


def test_parser_full_outer_join():
    """FULL OUTER JOIN 應解析為 type='FULL' 的 JoinNode"""
    from birdeye.ast import JoinNode
    ast = parse("SELECT A FROM T FULL OUTER JOIN T2 ON T.A = T2.A")
    assert len(ast.joins) == 1
    assert ast.joins[0].type == "FULL"


def test_full_outer_join_basic(global_runner):
    """FULL OUTER JOIN 應成功綁定"""
    result = global_runner.run(
        "SELECT a.AddressID FROM Address a "
        "FULL OUTER JOIN Address b ON a.AddressID = b.AddressID"
    )
    assert result["status"] == "success"


def test_full_outer_join_columns_nullable(global_runner):
    """FULL OUTER JOIN 兩側皆應標記為 nullable (binder._last_root_nullables)"""
    global_runner.run(
        "SELECT a.AddressID FROM Address a "
        "FULL OUTER JOIN Address b ON a.AddressID = b.AddressID"
    )
    nullables = {n.upper() for n in global_runner._binder._last_root_nullables}
    assert "B" in nullables


# ─────────────────────────────────────────────
# Issue #64: OFFSET FETCH
# ─────────────────────────────────────────────

def test_lexer_offset_fetch_keywords():
    """OFFSET、ROWS、FETCH、NEXT、ONLY 應被詞法分析為關鍵字"""
    sql = "SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"
    tokens = Lexer(sql).tokenize()
    types = [t.type for t in tokens]
    assert TokenType.KEYWORD_OFFSET in types
    assert TokenType.KEYWORD_FETCH in types


def test_parser_offset_fetch():
    """OFFSET n ROWS FETCH NEXT n ROWS ONLY 應解析到 SelectStatement"""
    ast = parse(
        "SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"
    )
    assert ast.offset_count == 10
    assert ast.fetch_count == 5


def test_offset_fetch_basic(global_runner):
    """OFFSET FETCH 分頁語法應成功綁定"""
    result = global_runner.run(
        "SELECT AddressID FROM Address ORDER BY AddressID "
        "OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"
    )
    assert result["status"] == "success"


def test_offset_only(global_runner):
    """只有 OFFSET 沒有 FETCH 也應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address ORDER BY AddressID OFFSET 5 ROWS"
    )
    assert result["status"] == "success"


def test_offset_fetch_serialization():
    """OFFSET FETCH 應序列化為含 offset_count / fetch_count 的 JSON"""
    ast = parse(
        "SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"
    )
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["offset_count"] == 10
    assert data["fetch_count"] == 5


def test_offset_fetch_visualizer():
    """OFFSET FETCH 視覺化應顯示 OFFSET 與 FETCH 資訊"""
    ast = parse(
        "SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"
    )
    output = ASTVisualizer().dump(ast)
    assert "OFFSET: 10" in output
    assert "FETCH NEXT: 5" in output
