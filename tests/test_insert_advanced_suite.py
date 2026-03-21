"""
Issue #57: INSERT INTO ... SELECT
Issue #58: Multi-row INSERT VALUES
TDD 測試套件 — Red → Green
"""
import pytest
import json
from birdeye.binder import SemanticError
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.serializer import ASTSerializer
from birdeye.visualizer import ASTVisualizer


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


# ─────────────────────────────────────────────
# Issue #57: INSERT INTO ... SELECT
# ─────────────────────────────────────────────

def test_parser_insert_select_produces_insert_statement():
    """INSERT INTO ... SELECT 應解析為 InsertStatement，source 為 SelectStatement"""
    from birdeye.ast import InsertStatement, SelectStatement
    ast = parse("INSERT INTO Address (AddressID, City) SELECT AddressID, City FROM Address")
    assert isinstance(ast, InsertStatement)
    assert isinstance(ast.source, SelectStatement)


def test_parser_insert_select_no_columns():
    """INSERT INTO T SELECT ... (不指定欄位) 應成功解析"""
    from birdeye.ast import InsertStatement
    ast = parse("INSERT INTO Address SELECT AddressID, City FROM Address")
    assert isinstance(ast, InsertStatement)


def test_insert_select_basic(global_runner):
    """INSERT INTO ... SELECT 基本用法應成功綁定"""
    result = global_runner.run(
        "INSERT INTO Address (AddressID, City) "
        "SELECT AddressID, City FROM Address WHERE AddressID = 1"
    )
    assert result["status"] == "success"


def test_insert_select_type_mismatch_raises(global_runner):
    """INSERT-SELECT 型別不相容時應拋出 SemanticError"""
    with pytest.raises(SemanticError):
        global_runner.run(
            "INSERT INTO Address (AddressID, City) "
            "SELECT City, AddressID FROM Address"
        )


def test_insert_select_column_count_mismatch_raises(global_runner):
    """INSERT-SELECT 欄位數不符時應拋出 SemanticError"""
    with pytest.raises(SemanticError):
        global_runner.run(
            "INSERT INTO Address (AddressID) "
            "SELECT AddressID, City FROM Address"
        )


def test_insert_select_serialization():
    """INSERT-SELECT 應序列化為含 source 欄位的 JSON"""
    ast = parse("INSERT INTO Address (AddressID) SELECT AddressID FROM Address")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["node_type"] == "InsertStatement"
    assert data["source"] is not None
    assert data["source"]["node_type"] == "SelectStatement"
    assert data["values"] is None


def test_insert_select_visualizer():
    """INSERT-SELECT 視覺化應顯示 SOURCE 節點"""
    ast = parse("INSERT INTO Address (AddressID) SELECT AddressID FROM Address")
    output = ASTVisualizer().dump(ast)
    assert "INSERT_STATEMENT" in output
    assert "SOURCE" in output


# ─────────────────────────────────────────────
# Issue #58: Multi-row INSERT VALUES
# ─────────────────────────────────────────────

def test_parser_multirow_values_count():
    """Multi-row VALUES 應解析出正確的列數"""
    from birdeye.ast import InsertStatement
    ast = parse("INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B'), (3, 'C')")
    assert isinstance(ast, InsertStatement)
    assert len(ast.value_rows) == 3


def test_parser_single_row_values_backward_compat():
    """單列 VALUES 仍應向後相容"""
    from birdeye.ast import InsertStatement
    ast = parse("INSERT INTO Address (AddressID, City) VALUES (1, 'Taipei')")
    assert isinstance(ast, InsertStatement)
    assert len(ast.value_rows) == 1


def test_multirow_insert_basic(global_runner):
    """Multi-row INSERT VALUES 基本用法應成功綁定"""
    result = global_runner.run(
        "INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')"
    )
    assert result["status"] == "success"


def test_multirow_insert_type_check(global_runner):
    """Multi-row VALUES 每一列皆應通過型別檢查"""
    result = global_runner.run(
        "INSERT INTO Address (AddressID, City) "
        "VALUES (10, 'X'), (20, 'Y'), (30, 'Z')"
    )
    assert result["status"] == "success"


def test_multirow_insert_type_mismatch_raises(global_runner):
    """Multi-row VALUES 其中一列型別錯誤時應拋出 SemanticError"""
    with pytest.raises(SemanticError):
        global_runner.run(
            "INSERT INTO Address (AddressID, City) VALUES (1, 'A'), ('bad', 2)"
        )


def test_multirow_insert_serialization():
    """Multi-row VALUES 應序列化為含多組 value_rows 的 JSON"""
    ast = parse("INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')")
    data = json.loads(ASTSerializer().to_json(ast))
    assert data["node_type"] == "InsertStatement"
    assert isinstance(data["value_rows"], list)
    assert len(data["value_rows"]) == 2


def test_multirow_insert_visualizer():
    """Multi-row VALUES 視覺化應顯示多組 VALUES ROW"""
    ast = parse("INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')")
    output = ASTVisualizer().dump(ast)
    assert "INSERT_STATEMENT" in output
    assert "VALUES ROW #1" in output
    assert "VALUES ROW #2" in output
