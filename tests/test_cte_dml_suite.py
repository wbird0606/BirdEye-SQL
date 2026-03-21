"""
CTE + DML (UPDATE / DELETE / INSERT) 整合測試
WITH CTE AS (...) UPDATE / DELETE / INSERT ... 應成功
TDD 測試套件 — Red → Green
"""
import pytest
from birdeye.binder import SemanticError
from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.ast import UpdateStatement, DeleteStatement


def parse(sql):
    return Parser(Lexer(sql).tokenize(), sql).parse()


# ─────────────────────────────────────────────
# CTE + UPDATE
# ─────────────────────────────────────────────

def test_parser_cte_update_has_ctes():
    """WITH CTE ... UPDATE 的 UpdateStatement 應附帶 ctes"""
    ast = parse(
        "WITH CTE AS (SELECT AddressID FROM Address) "
        "UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM CTE)"
    )
    assert isinstance(ast, UpdateStatement)
    assert hasattr(ast, 'ctes') and len(ast.ctes) == 1
    assert ast.ctes[0].name == "CTE"


def test_cte_update_basic(global_runner):
    """WITH CTE AS (...) UPDATE ... WHERE IN (SELECT FROM CTE) 應成功"""
    result = global_runner.run(
        "WITH CTE AS (SELECT AddressID FROM Address) "
        "UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM CTE)"
    )
    assert result["status"] == "success"


def test_cte_update_filtered(global_runner):
    """WITH 帶過濾條件的 CTE 用於 UPDATE 應成功"""
    result = global_runner.run(
        "WITH FilteredIDs AS (SELECT AddressID FROM Address WHERE StateProvinceID = 1) "
        "UPDATE Address SET City = 'Updated' "
        "WHERE AddressID IN (SELECT AddressID FROM FilteredIDs)"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# CTE + DELETE
# ─────────────────────────────────────────────

def test_parser_cte_delete_has_ctes():
    """WITH CTE ... DELETE 的 DeleteStatement 應附帶 ctes"""
    ast = parse(
        "WITH CTE AS (SELECT AddressID FROM Address WHERE AddressID < 0) "
        "DELETE FROM Address WHERE AddressID IN (SELECT AddressID FROM CTE)"
    )
    assert isinstance(ast, DeleteStatement)
    assert hasattr(ast, 'ctes') and len(ast.ctes) == 1


def test_cte_delete_basic(global_runner):
    """WITH CTE AS (...) DELETE ... WHERE IN (SELECT FROM CTE) 應成功"""
    result = global_runner.run(
        "WITH CTE AS (SELECT AddressID FROM Address WHERE AddressID < 0) "
        "DELETE FROM Address WHERE AddressID IN (SELECT AddressID FROM CTE)"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Multiple CTEs + DML
# ─────────────────────────────────────────────

def test_multiple_ctes_with_update(global_runner):
    """多個 CTE 搭配 UPDATE 應成功"""
    result = global_runner.run(
        "WITH A AS (SELECT AddressID FROM Address), "
        "B AS (SELECT AddressID FROM Address WHERE StateProvinceID = 1) "
        "UPDATE Address SET City = 'X' "
        "WHERE AddressID IN (SELECT AddressID FROM A) "
        "AND AddressID IN (SELECT AddressID FROM B)"
    )
    assert result["status"] == "success"


def test_cte_not_visible_outside_dml(global_runner):
    """CTE 只在該語句內有效，不應影響後續查詢"""
    global_runner.run(
        "WITH TempCTE AS (SELECT AddressID FROM Address) "
        "UPDATE Address SET City = 'X' WHERE AddressID IN (SELECT AddressID FROM TempCTE)"
    )
    # 下一個 run() TempCTE 不應存在
    with pytest.raises(SemanticError):
        global_runner.run("SELECT AddressID FROM TempCTE")
