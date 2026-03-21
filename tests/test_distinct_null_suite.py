"""
Issue #55: SELECT DISTINCT
Issue #56: SELECT NULL 字面值
TDD 測試套件 — Red → Green
"""
import pytest
from birdeye.binder import SemanticError
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.ast import LiteralNode


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


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
    import json
    from birdeye.serializer import ASTSerializer
    ast = parse("SELECT DISTINCT City FROM T")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data.get("is_distinct") is True


def test_distinct_visualizer(global_runner):
    """SELECT DISTINCT 視覺化應顯示 DISTINCT 標記"""
    from birdeye.visualizer import ASTVisualizer
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
