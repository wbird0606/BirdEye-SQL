import pytest
import io
import json
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.ast import LiteralNode
from birdeye.serializer import ASTSerializer
from birdeye.visualizer import ASTVisualizer


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


# --- (from test_order_by_top_suite.py) ---

@pytest.fixture
def bird_reg():
    """建立包含基礎表的元數據，用於驗證排序欄位的合法性"""
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
    """執行 Lexer 與 Parser 流水線"""
    lexer = Lexer(sql)
    tokens = lexer.tokenize()
    parser = Parser(tokens, sql)
    return parser.parse()

def run_bind(sql, registry):
    """執行完整語意綁定"""
    ast = run_parse(sql)
    binder = Binder(registry)
    return binder.bind(ast)

def run_bind_with_runner(sql, runner):
    """整合 BirdEyeRunner 執行完整驗證"""
    return runner.run(sql)["ast"]

# --- 2. Lexer 關鍵字測試 ---

def test_lexer_new_keywords():
    """驗證 Lexer 是否能識別排序與分頁相關的關鍵字"""
    sql = "SELECT TOP 10 * FROM Users ORDER BY UserID ASC DESC"
    lexer = Lexer(sql)
    tokens = [t.type for t in lexer.tokenize()]

    assert TokenType.KEYWORD_TOP in tokens
    assert TokenType.KEYWORD_ORDER in tokens
    assert TokenType.KEYWORD_BY in tokens
    assert TokenType.KEYWORD_ASC in tokens
    assert TokenType.KEYWORD_DESC in tokens

# --- 3. Parser 結構測試 (Parsing) ---

@pytest.mark.parametrize("sql, expected_top, order_count", [
    # 基礎 TOP 測試
    ("SELECT TOP 10 * FROM Users", 10, 0),
    # 基礎 ORDER BY 測試
    ("SELECT * FROM Users ORDER BY UserID", None, 1),
    # 複合測試：TOP + ORDER BY (DESC)
    ("SELECT TOP 5 UserName FROM Users ORDER BY UserID DESC", 5, 1),
    # 多欄位排序測試
    ("SELECT * FROM Users ORDER BY UserName ASC, UserID DESC", None, 2),
])
def test_order_by_top_parsing(sql, expected_top, order_count):
    """驗證 Parser 是否能正確將 TOP 與 ORDER BY 資訊掛載至 SelectStatement"""
    ast = run_parse(sql)
    assert ast.__class__.__name__ == "SelectStatement"

    if expected_top:
        assert ast.top_count == expected_top

    assert len(ast.order_by_terms) == order_count

# --- 4. 語意綁定與 ZTA 政策測試 (Semantic) ---

def test_order_by_semantic_binding(bird_reg):
    """驗證 ORDER BY 中的欄位是否正確解析其作用域"""
    sql = "SELECT UserName FROM Users u ORDER BY u.UserID"
    ast = run_bind(sql, bird_reg)

    order_node = ast.order_by_terms[0]
    assert order_node.column.qualifier.upper() == "U"

def test_order_by_invalid_column(bird_reg):
    """驗證排序不存在的欄位時應拋出錯誤"""
    sql = "SELECT * FROM Users ORDER BY GhostColumn"
    with pytest.raises(SemanticError, match="Column 'GhostColumn' not found in 'Users'"):
        run_bind(sql, bird_reg)

def test_order_by_ambiguous_column(bird_reg):
    """驗證在 JOIN 場景下，ORDER BY 欄位歧義攔截"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Users,UserID,INT\n"
        "Orders,UserID,INT\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))

    sql = "SELECT * FROM Users JOIN Orders ON Users.UserID = Orders.UserID ORDER BY UserID"
    with pytest.raises(SemanticError, match="Column 'UserID' is ambiguous"):
        run_bind(sql, reg)

# --- 5. 語法容錯測試 ---

def test_top_missing_number():
    """驗證 TOP 後方若缺少數值應拋出語法錯誤"""
    sql = "SELECT TOP * FROM Users"
    with pytest.raises(SyntaxError, match="Expected numeric literal after TOP"):
        run_parse(sql)

# --- 💡 TDD New: ORDER BY Alias Resolution ---

def test_order_by_alias_resolution(bird_reg):
    """
    驗證 ORDER BY 是否能正確解析 SELECT 清單中定義的別名 (TDD Regression)
    """
    sql = "SELECT UserID + 100 AS Score FROM Users ORDER BY Score DESC"
    ast = run_bind(sql, bird_reg)

    order_node = ast.order_by_terms[0].column
    assert order_node.inferred_type == "INT"


# --- (from test_top_percent_suite.py) ---

def test_lexer_percent_is_keyword():
    """PERCENT 應被詞法分析為 KEYWORD_PERCENT"""
    tokens = Lexer("SELECT TOP 10 PERCENT AddressID FROM Address").tokenize()
    types = [t.type for t in tokens]
    assert TokenType.KEYWORD_PERCENT in types


def test_parser_top_percent_flag():
    """TOP N PERCENT 應在 SelectStatement 上設定 top_percent = True"""
    ast = parse("SELECT TOP 10 PERCENT AddressID FROM T")
    assert ast.top_count == 10
    assert getattr(ast, "top_percent", False) is True


def test_parser_top_without_percent_flag_is_false():
    """TOP N (無 PERCENT) 的 top_percent 應為 False"""
    ast = parse("SELECT TOP 10 AddressID FROM T")
    assert ast.top_count == 10
    assert not getattr(ast, "top_percent", False)


def test_top_percent_basic(global_runner):
    """SELECT TOP 10 PERCENT 應成功綁定"""
    result = global_runner.run(
        "SELECT TOP 10 PERCENT AddressID FROM Address"
    )
    assert result["status"] == "success"


def test_top_percent_with_where(global_runner):
    """SELECT TOP N PERCENT 搭配 WHERE 應成功"""
    result = global_runner.run(
        "SELECT TOP 50 PERCENT City FROM Address WHERE AddressID > 0"
    )
    assert result["status"] == "success"


def test_top_percent_with_order_by(global_runner):
    """SELECT TOP N PERCENT 搭配 ORDER BY 應成功"""
    result = global_runner.run(
        "SELECT TOP 10 PERCENT AddressID FROM Address ORDER BY AddressID"
    )
    assert result["status"] == "success"


def test_top_percent_serialization():
    """TOP N PERCENT 應序列化為含 top_percent = true 的 JSON"""
    ast = parse("SELECT TOP 10 PERCENT AddressID FROM T")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["top"] == 10
    assert data.get("top_percent") is True


def test_top_without_percent_serialization():
    """TOP N (無 PERCENT) 序列化的 top_percent 應為 false"""
    ast = parse("SELECT TOP 10 AddressID FROM T")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["top"] == 10
    assert data.get("top_percent") is False


def test_top_percent_visualizer():
    """TOP N PERCENT 視覺化應顯示 PERCENT 標記"""
    ast = parse("SELECT TOP 10 PERCENT AddressID FROM T")
    output = ASTVisualizer().dump(ast)
    assert "TOP: 10 PERCENT" in output


# --- (from test_group_by_having_suite.py) ---

@pytest.fixture
def agg_reg():
    """建立包含銷售數據的元數據，用於測試聚合邏輯"""
    csv_data = (
        "table_name,column_name,data_type\n"
        "Sales,SaleID,INT\n"
        "Sales,ProductID,INT\n"
        "Sales,Amount,DECIMAL\n"
        "Sales,Region,VARCHAR\n"
    )
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(csv_data))
    return reg

# --- 2. GROUP BY 語法解析測試 (Real Metadata) ---

def test_group_by_parsing(global_runner):
    """驗證 Parser 是否能正確識別真實元數據下的 GROUP BY"""
    sql = "SELECT ProductID, SUM(LineTotal) FROM SalesOrderDetail GROUP BY ProductID"
    ast = run_bind_with_runner(sql, global_runner)

    assert len(ast.group_by_cols) == 1
    assert ast.group_by_cols[0].name == "ProductID"

# --- 3. HAVING 子句解析測試 (Real Metadata) ---

def test_having_parsing(global_runner):
    """驗證 HAVING 子句是否能正確解析真實元數據下的表達式"""
    sql = "SELECT ProductID FROM SalesOrderDetail GROUP BY ProductID HAVING SUM(LineTotal) > 1000"
    ast = run_bind_with_runner(sql, global_runner)

    assert ast.having_condition is not None
    assert ast.having_condition.operator == ">"

# --- 4. ZTA 聚合安全性校驗 (Real Metadata) ---

def test_error_non_aggregated_column_real_meta(global_runner):
    """🛡️ ZTA 政策：禁止選擇既不在 GROUP BY 中也沒有被聚合的欄位 (真實元數據)"""
    sql = "SELECT ProductID, SalesOrderID FROM SalesOrderDetail GROUP BY ProductID"
    with pytest.raises(SemanticError, match="Column 'SalesOrderID' must appear in the GROUP BY clause"):
        run_bind_with_runner(sql, global_runner)

def test_error_aggregate_in_where_real_meta(global_runner):
    """🛡️ ZTA 政策：禁止在 WHERE 子句中使用聚合函數 (真實元數據)"""
    sql = "SELECT ProductID FROM SalesOrderDetail WHERE SUM(LineTotal) > 100 GROUP BY ProductID"
    with pytest.raises(SemanticError, match="Aggregate functions are not allowed in WHERE clause"):
        run_bind_with_runner(sql, global_runner)

# --- 💡 TDD New: CASE WHEN 中的聚合完整性 ---

def test_error_case_agg_integrity(global_runner):
    """🛡️ ZTA 政策：驗證 CASE 邏輯內部的聚合完整性"""
    sql = """
        SELECT CASE
            WHEN ProductID > 0 THEN SUM(LineTotal)
            ELSE LineTotal
        END FROM SalesOrderDetail GROUP BY ProductID
    """
    with pytest.raises(SemanticError, match="Column 'LineTotal' must appear in the GROUP BY clause"):
        run_bind_with_runner(sql, global_runner)

# --- 💡 TDD New: 複雜表達式在 GROUP BY 中的完整性檢查 ---

def test_group_by_complex_expression_integrity(global_runner):
    """驗證當整個表達式 (如函數) 存在於 GROUP BY 中時，其內部欄位不會觸發未聚合錯誤"""
    sql = """
        SELECT SUBSTRING(Name, 1, 5) AS ShortName, COUNT(ProductID)
        FROM Product
        GROUP BY SUBSTRING(Name, 1, 5)
    """
    ast = run_bind_with_runner(sql, global_runner)
    assert len(ast.columns) == 2


# --- (from test_distinct_null_suite.py) ---

# ─────────────────────────────────────────────
# Issue #55: SELECT DISTINCT
# ─────────────────────────────────────────────

def test_lexer_distinct_is_keyword():
    """DISTINCT 應被詞法分析為 KEYWORD_DISTINCT"""
    tokens = Lexer("SELECT DISTINCT City FROM Address").tokenize()
    types = [t.type for t in tokens]
    assert TokenType.KEYWORD_DISTINCT in types


def test_parser_distinct_flag_on_statement():
    """Parser 應在 SelectStatement 上設定 is_distinct = True"""
    ast = parse("SELECT DISTINCT City FROM T")
    assert hasattr(ast, "is_distinct") and ast.is_distinct is True


def test_parser_non_distinct_flag_is_false():
    """一般 SELECT 的 is_distinct 應為 False"""
    ast = parse("SELECT City FROM T")
    assert not getattr(ast, "is_distinct", False)


def test_distinct_single_column(global_runner):
    """SELECT DISTINCT 單欄位應成功綁定"""
    result = global_runner.run("SELECT DISTINCT City FROM Address")
    assert result["status"] == "success"


def test_distinct_multiple_columns(global_runner):
    """SELECT DISTINCT 多欄位應成功綁定"""
    result = global_runner.run(
        "SELECT DISTINCT City, StateProvinceID FROM Address"
    )
    assert result["status"] == "success"


def test_distinct_with_where(global_runner):
    """SELECT DISTINCT 搭配 WHERE 應成功"""
    result = global_runner.run(
        "SELECT DISTINCT City FROM Address WHERE AddressID > 0"
    )
    assert result["status"] == "success"


def test_distinct_with_order_by(global_runner):
    """SELECT DISTINCT 搭配 ORDER BY 應成功"""
    result = global_runner.run(
        "SELECT DISTINCT City FROM Address ORDER BY City"
    )
    assert result["status"] == "success"


def test_distinct_serialization(global_runner):
    """SELECT DISTINCT 序列化後應包含 is_distinct 欄位"""
    ast = parse("SELECT DISTINCT City FROM T")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data.get("is_distinct") is True


def test_distinct_visualizer(global_runner):
    """SELECT DISTINCT 視覺化應顯示 DISTINCT 標記"""
    ast = parse("SELECT DISTINCT City FROM T")
    output = ASTVisualizer().dump(ast)
    assert "DISTINCT" in output


# ─────────────────────────────────────────────
# Issue #56: NULL 字面值
# ─────────────────────────────────────────────

def test_lexer_null_is_keyword():
    """NULL 應已被詞法分析為 KEYWORD_NULL"""
    tokens = Lexer("SELECT NULL").tokenize()
    types = [t.type for t in tokens]
    assert TokenType.KEYWORD_NULL in types


def test_parser_null_literal_node():
    """Parser 應將 NULL 解析為 LiteralNode，value='NULL'"""
    ast = parse("SELECT NULL")
    col = ast.columns[0]
    assert isinstance(col, LiteralNode)
    assert col.value == "NULL"


def test_select_null_standalone(global_runner):
    """SELECT NULL 應成功"""
    result = global_runner.run("SELECT NULL")
    assert result["status"] == "success"


def test_null_in_case_else(global_runner):
    """CASE ELSE NULL 應成功"""
    result = global_runner.run(
        "SELECT CASE WHEN AddressID = 1 THEN City ELSE NULL END FROM Address"
    )
    assert result["status"] == "success"


def test_null_in_where_is_null(global_runner):
    """WHERE col IS NULL 應成功 (原本即支援，確保不迴歸)"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE City IS NULL"
    )
    assert result["status"] == "success"


def test_null_in_select_with_alias(global_runner):
    """SELECT NULL AS EmptyCol 應成功"""
    result = global_runner.run("SELECT NULL AS EmptyCol")
    assert result["status"] == "success"


def test_null_in_binary_expression(global_runner):
    """NULL 可出現在比較表達式右側"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE City = NULL"
    )
    assert result["status"] == "success"
