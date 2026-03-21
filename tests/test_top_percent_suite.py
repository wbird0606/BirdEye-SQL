"""
Issue #59: TOP N PERCENT
TDD 測試套件 — Red → Green
"""
import pytest
import json
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.serializer import ASTSerializer
from birdeye.visualizer import ASTVisualizer


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


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
