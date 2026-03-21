"""
Issue #53: 支援關聯運算子 APPLY (CROSS/OUTER APPLY)
TDD 測試套件

測試分層：
  1. Lexer   - CROSS / APPLY / OUTER token 識別
  2. Parser  - ApplyNode 建構
  3. Binder  - 橫向作用域 (Lateral Scope) 與 nullable 推導
  4. Runner  - 完整整合
"""
import pytest
from birdeye.lexer import Lexer, TokenType
from birdeye.parser import Parser
from birdeye.ast import ApplyNode, SelectStatement


# ─────────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────────

def tokenize(sql):
    return Lexer(sql).tokenize()

def parse(sql):
    tokens = Lexer(sql).tokenize()
    return Parser(tokens, sql).parse()


# ─────────────────────────────────────────────
# 1. Lexer 測試
# ─────────────────────────────────────────────

def test_lexer_cross_is_keyword():
    """CROSS 應被識別為 KEYWORD_CROSS"""
    tokens = tokenize("CROSS APPLY")
    assert tokens[0].type == TokenType.KEYWORD_CROSS

def test_lexer_apply_is_keyword():
    """APPLY 應被識別為 KEYWORD_APPLY"""
    tokens = tokenize("CROSS APPLY")
    assert tokens[1].type == TokenType.KEYWORD_APPLY

def test_lexer_outer_is_keyword():
    """OUTER 應被識別為 KEYWORD_OUTER"""
    tokens = tokenize("OUTER APPLY")
    assert tokens[0].type == TokenType.KEYWORD_OUTER


# ─────────────────────────────────────────────
# 2. Parser 測試
# ─────────────────────────────────────────────

def test_parser_cross_apply_produces_apply_node():
    """CROSS APPLY 應在 stmt.applies 中產生 ApplyNode(type='CROSS')"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    ast = parse(sql)
    assert isinstance(ast, SelectStatement)
    assert len(ast.applies) == 1
    apply = ast.applies[0]
    assert isinstance(apply, ApplyNode)
    assert apply.type == "CROSS"
    assert apply.alias == "sub"

def test_parser_outer_apply_produces_apply_node():
    """OUTER APPLY 應產生 ApplyNode(type='OUTER')"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "OUTER APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    ast = parse(sql)
    assert len(ast.applies) == 1
    assert ast.applies[0].type == "OUTER"

def test_parser_apply_subquery_is_select_statement():
    """ApplyNode.subquery 應為 SelectStatement"""
    sql = (
        "SELECT a.AddressID "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    ast = parse(sql)
    assert isinstance(ast.applies[0].subquery, SelectStatement)

def test_parser_apply_can_coexist_with_join():
    """JOIN 與 APPLY 可同時出現在同一查詢"""
    sql = (
        "SELECT a.AddressID, b.City, sub.City "
        "FROM Address a "
        "INNER JOIN Address b ON a.AddressID = b.AddressID "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    ast = parse(sql)
    assert len(ast.joins) == 1
    assert len(ast.applies) == 1


# ─────────────────────────────────────────────
# 3. Binder / 語意分析測試
# ─────────────────────────────────────────────

def test_cross_apply_lateral_scope(global_runner):
    """
    CROSS APPLY 子查詢應能參照外側表欄位 (橫向作用域)。
    WHERE AddressID = a.AddressID 中的 a.AddressID 來自外側 FROM Address a。
    """
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"

def test_outer_apply_marks_columns_nullable(global_runner):
    """OUTER APPLY 的結果集欄位應被標記為 nullable (類似 LEFT JOIN)"""
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "OUTER APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    result = global_runner.run(sql)
    assert result["status"] == "success"
    # OUTER APPLY alias 應在 nullable_scopes 中
    binder_nullables = global_runner._binder.nullable_scopes
    assert "SUB" in binder_nullables

def test_apply_result_columns_accessible_in_outer_select(global_runner):
    """
    APPLY 子查詢投影的欄位 (City) 應能在外側 SELECT 中解析，
    且 sub.City 的型別應被正確推導。
    """
    sql = (
        "SELECT a.AddressID, sub.City "
        "FROM Address a "
        "CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub"
    )
    result = global_runner.run(sql)
    col_names = [c.name.upper() if not hasattr(c, 'alias') or not c.alias
                 else c.alias.upper()
                 for c in result["ast"].columns]
    assert "CITY" in col_names

def test_unknown_column_in_apply_raises_error(global_runner):
    """APPLY 子查詢中使用不存在的欄位應拋出 SemanticError"""
    from birdeye.binder import SemanticError
    sql = (
        "SELECT a.AddressID "
        "FROM Address a "
        "CROSS APPLY (SELECT NonExistentCol FROM Address WHERE AddressID = a.AddressID) sub"
    )
    with pytest.raises(SemanticError):
        global_runner.run(sql)
