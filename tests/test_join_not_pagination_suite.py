"""
Issue #60: NOT IN
Issue #61: NOT EXISTS
Issue #62: CROSS JOIN
Issue #63: FULL OUTER JOIN
Issue #64: OFFSET FETCH
TDD 測試套件 — Red → Green
"""
import pytest
import json
from birdeye.binder import SemanticError
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.serializer import ASTSerializer
from birdeye.visualizer import ASTVisualizer


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
