"""
Issue #5 (round 4): 運算子補齊 + UNION 衍生資料表
- Modulo operator %
- Bitwise AND operator &
- UNION / UNION ALL as derived table (subquery in FROM)
TDD 測試套件 — Red → Green
"""
import pytest


# ─────────────────────────────────────────────
# Modulo operator %
# ─────────────────────────────────────────────

def test_modulo_basic(global_runner):
    """AddressID % 2 應成功"""
    result = global_runner.run("SELECT AddressID % 2 FROM Address")
    assert result["status"] == "success"


def test_modulo_in_where(global_runner):
    """WHERE 中使用 % 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE AddressID % 2 = 0"
    )
    assert result["status"] == "success"


def test_modulo_with_alias(global_runner):
    """% 運算結果附帶 alias 應成功"""
    result = global_runner.run(
        "SELECT AddressID % 10 AS Remainder FROM Address"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Bitwise AND operator &
# ─────────────────────────────────────────────

def test_bitwise_and_basic(global_runner):
    """AddressID & 1 應成功"""
    result = global_runner.run("SELECT AddressID & 1 FROM Address")
    assert result["status"] == "success"


def test_bitwise_and_in_where(global_runner):
    """WHERE 中使用 & 應成功"""
    result = global_runner.run(
        "SELECT AddressID FROM Address WHERE AddressID & 1 = 1"
    )
    assert result["status"] == "success"


def test_bitwise_and_with_alias(global_runner):
    """& 運算結果附帶 alias 應成功"""
    result = global_runner.run(
        "SELECT AddressID & 255 AS Masked FROM Address"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# UNION as derived table
# ─────────────────────────────────────────────

def test_union_as_derived_table(global_runner):
    """FROM (SELECT ... UNION SELECT ...) AS Sub 應成功"""
    result = global_runner.run(
        "SELECT Sub.AddressID FROM "
        "(SELECT AddressID FROM Address UNION SELECT AddressID FROM Address) AS Sub"
    )
    assert result["status"] == "success"


def test_union_all_as_derived_table(global_runner):
    """FROM (SELECT ... UNION ALL SELECT ...) AS Sub 應成功"""
    result = global_runner.run(
        "SELECT Sub.AddressID FROM "
        "(SELECT AddressID FROM Address UNION ALL SELECT AddressID FROM Address) AS Sub"
    )
    assert result["status"] == "success"


def test_union_derived_table_with_where(global_runner):
    """UNION 衍生資料表搭配外層 WHERE 應成功"""
    result = global_runner.run(
        "SELECT Sub.AddressID FROM "
        "(SELECT AddressID FROM Address WHERE StateProvinceID = 1 "
        "UNION SELECT AddressID FROM Address WHERE StateProvinceID = 2) AS Sub "
        "WHERE Sub.AddressID > 0"
    )
    assert result["status"] == "success"


def test_union_derived_table_select_star(global_runner):
    """UNION 衍生資料表搭配 SELECT * 應成功"""
    result = global_runner.run(
        "SELECT * FROM "
        "(SELECT AddressID FROM Address UNION SELECT AddressID FROM Address) AS Sub"
    )
    assert result["status"] == "success"


# ─────────────────────────────────────────────
# Combined: modulo + bitwise
# ─────────────────────────────────────────────

def test_modulo_and_bitwise_combined(global_runner):
    """同時使用 % 和 & 應成功"""
    result = global_runner.run(
        "SELECT AddressID % 10 AS Mod, AddressID & 255 AS Bits FROM Address"
    )
    assert result["status"] == "success"
