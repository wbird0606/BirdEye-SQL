"""
Issue #5 (round 2):
  - MAX / MIN 函數缺失
  - 衍生資料表 FROM (SELECT ...) alias
  - N'' Unicode 字串前綴
  - JOIN (SELECT ...) alias ON ...
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
    from birdeye.ast import SelectStatement
    ast = parse("SELECT sub.City FROM (SELECT City FROM T) sub")
    # table 應是 SelectStatement（子查詢）或包裝節點
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
